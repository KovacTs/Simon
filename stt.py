from collections import deque
from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
import io
from typing import Optional
import wave
import numpy as np
import sounddevice as sd
import speech_recognition as sr
import config

# --- Silenciar mensajes de advertencia de ALSA/PortAudio en Linux ---
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

    def py_error_handler(filename, line, function, err, fmt):
        pass

    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary("libasound.so.2")
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass
# -------------------------------------------------------------------


class SileroVADDetector:
    """
    Detector de Actividad de Voz basado en Silero VAD (ONNX).
    Permite cortar la grabación en < 300 ms en cuanto el usuario termina de hablar.
    """

    SAMPLE_RATE = 16000
    CHUNK_SAMPLES = 512  # 32 ms a 16kHz (requerido por Silero VAD)

    def __init__(
        self,
        threshold: float = config.VAD_THRESHOLD,
        silence_ms: int = config.VAD_SILENCE_MS,
        min_speech_ms: int = config.VAD_MIN_SPEECH_MS,
    ):
        self.threshold = threshold
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self._model = None
        self._torch = None
        self._load_model()

    def _load_model(self):
        try:
            import torch
            from silero_vad import load_silero_vad

            self._torch = torch
            self._model = load_silero_vad(onnx=True)
        except Exception:
            self._model = None

    def reset(self):
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()

    def is_speech(self, chunk_float32: np.ndarray) -> float:
        """Devuelve la probabilidad de voz [0.0, 1.0] para un bloque de 512 muestras a 16kHz."""
        if self._model is None or self._torch is None:
            # Fallback por energía RMS si Silero no está disponible
            rms = float(np.sqrt(np.mean(np.square(chunk_float32))))
            return min(1.0, rms * 15.0)

        if len(chunk_float32) != self.CHUNK_SAMPLES:
            if len(chunk_float32) < self.CHUNK_SAMPLES:
                chunk_float32 = np.pad(chunk_float32, (0, self.CHUNK_SAMPLES - len(chunk_float32)))
            else:
                chunk_float32 = chunk_float32[: self.CHUNK_SAMPLES]

        tensor = self._torch.from_numpy(chunk_float32.astype(np.float32))
        prob = float(self._model(tensor, self.SAMPLE_RATE).item())
        return prob


class STTManager:
    """
    Módulo de captura de audio con Silero VAD (< 300ms fin de frase)
    y transcripción mediante Faster-Whisper local (con respaldo en Google STT).
    """

    SAMPLE_RATE = 16000
    CHUNK_SAMPLES = 512  # 32 ms por frame

    def __init__(self, language: str = config.LANGUAGE):
        self.language = language
        self.vad = SileroVADDetector()
        self.engine = config.STT_ENGINE
        self._whisper_model = None

        # Respaldo clásico con SpeechRecognition
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = max(0.25, config.VAD_SILENCE_MS / 1000.0)
        self.recognizer.non_speaking_duration = 0.25

        if self.engine in ("auto", "faster_whisper"):
            self._init_whisper()

    def _init_whisper(self):
        try:
            from faster_whisper import WhisperModel

            try:
                self._whisper_model = WhisperModel(
                    config.WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
            except Exception:
                self._whisper_model = WhisperModel(
                    config.WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",
                )
        except Exception:
            self._whisper_model = None

    def calibrate(self, duration: float = 0.5) -> bool:
        """Reinicia estados del modelo Silero VAD o calibra energía de respaldo."""
        self.vad.reset()
        return True

    def record_with_vad(
        self,
        timeout: Optional[float] = 6.0,
        phrase_time_limit: Optional[float] = 10.0,
        silence_ms: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """
        Captura audio a 16kHz desde el micrófono usando Silero VAD.
        Corta inmediatamente tras `silence_ms` (por defecto 280 ms < 300 ms) de silencio
        luego de haber detectado voz.
        """
        self.vad.reset()
        chunk_ms = (self.CHUNK_SAMPLES / self.SAMPLE_RATE) * 1000.0  # 32 ms
        target_silence_ms = silence_ms if silence_ms is not None else self.vad.silence_ms
        max_silence_chunks = max(1, int(round(target_silence_ms / chunk_ms)))
        min_speech_chunks = max(1, int(round(self.vad.min_speech_ms / chunk_ms)))
        max_wait_chunks = int((timeout * 1000.0) / chunk_ms) if timeout else None
        max_phrase_chunks = int((phrase_time_limit * 1000.0) / chunk_ms) if phrase_time_limit else 350

        # Pre-buffer de ~250ms para no cortar la primera sílaba al empezar a hablar
        pre_buffer = deque(maxlen=8)
        recorded_chunks = []

        speech_started = False
        speech_chunks_count = 0
        silence_chunks_count = 0
        waited_chunks = 0

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=self.CHUNK_SAMPLES,
            ) as stream:
                while True:
                    data, _ = stream.read(self.CHUNK_SAMPLES)
                    chunk = data[:, 0].copy()
                    prob = self.vad.is_speech(chunk)

                    if not speech_started:
                        pre_buffer.append(chunk)
                        if prob >= self.vad.threshold:
                            speech_started = True
                            speech_chunks_count = 1
                            silence_chunks_count = 0
                            recorded_chunks.extend(pre_buffer)
                        else:
                            waited_chunks += 1
                            if max_wait_chunks is not None and waited_chunks >= max_wait_chunks:
                                return None
                    else:
                        recorded_chunks.append(chunk)
                        if prob >= self.vad.threshold:
                            speech_chunks_count += 1
                            silence_chunks_count = 0
                        else:
                            silence_chunks_count += 1

                        # Cortar inmediatamente (< 300ms) cuando termina la frase
                        if speech_chunks_count >= min_speech_chunks and silence_chunks_count >= max_silence_chunks:
                            break

                        if len(recorded_chunks) >= max_phrase_chunks:
                            break
        except Exception:
            return None

        if not recorded_chunks or speech_chunks_count < min_speech_chunks:
            return None

        return np.concatenate(recorded_chunks)

    def transcribe_audio_array(self, audio_float32: np.ndarray, initial_prompt: Optional[str] = None) -> Optional[str]:
        """Transcribe un arreglo numpy float32 (16kHz) a texto en español."""
        if audio_float32 is None or len(audio_float32) == 0:
            return None

        # 1. Intentar con Faster-Whisper local si está activo
        if self._whisper_model is not None and self.engine in ("auto", "faster_whisper"):
            try:
                lang_code = self.language.split("-")[0].lower()
                prompt = initial_prompt or "Simón, Oye Simón, enciende la luz, apaga la ampolleta, temporizador, clima, Home Assistant."
                segments, _ = self._whisper_model.transcribe(
                    audio_float32,
                    language=lang_code,
                    beam_size=1,
                    best_of=1,
                    without_timestamps=True,
                    vad_filter=False,
                    initial_prompt=prompt,
                    condition_on_previous_text=False,
                )
                text = " ".join(seg.text.strip() for seg in segments).strip()
                if text:
                    return text
            except Exception:
                pass

        # 2. Respaldo con Google SpeechRecognition convirtiendo el buffer a WAV en memoria
        try:
            pcm16 = (np.clip(audio_float32, -1.0, 1.0) * 32767).astype(np.int16)
            wav_io = io.BytesIO()
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(pcm16.tobytes())
            wav_bytes = wav_io.getvalue()
            audio_data = sr.AudioData(wav_bytes, self.SAMPLE_RATE, 2)
            try:
                return self.recognizer.recognize_google(audio_data, language=self.language).strip()
            except sr.UnknownValueError:
                return self.recognizer.recognize_google(audio_data, language="es-419").strip()
        except Exception:
            return None

    def listen_and_transcribe(
        self,
        timeout: Optional[float] = 6.0,
        phrase_time_limit: Optional[float] = 10.0,
    ) -> Optional[str]:
        """
        Escucha por el micrófono con corte rápido Silero VAD (< 300ms)
        y transcribe la frase usando Faster-Whisper o Google STT.
        """
        audio = self.record_with_vad(timeout=timeout, phrase_time_limit=phrase_time_limit)
        if audio is not None:
            return self.transcribe_audio_array(audio)
        return None
