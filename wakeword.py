from collections import deque
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import unicodedata
import numpy as np
import sounddevice as sd
import config

MODELS_DIR = Path(__file__).resolve().parent / "models"


def _normalize_text(text: str) -> str:
    """Elimina tildes y signos de puntuación para comparar frases de activación."""
    text = text.lower().strip()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class WakeWordDetector:
    """
    Detector de Palabra de Activación (Fase 1) basado en openWakeWord + Silero VAD.
    - Ejecuta openWakeWord en bloques de 80 ms (1280 muestras a 16kHz, <1% CPU).
    - Soporta modelos ONNX personalizados en `models/oye_simon.onnx` o preentrenados (`hey_jarvis`, `alexa`).
    - Incluye detección híbrida en español para 'Oye Simón' / 'Simón' sobre segmentos cortos con voz activa.
    """

    SAMPLE_RATE = 16000
    FRAME_SAMPLES = 1280  # 80 ms (estándar nativo de openWakeWord)

    def __init__(
        self,
        model_name: str = config.WAKE_WORD_MODEL,
        threshold: float = config.WAKE_WORD_THRESHOLD,
        wake_phrases: Optional[List[str]] = None,
    ):
        self.model_name = model_name
        self.threshold = threshold
        self.wake_phrases = [_normalize_text(p) for p in (wake_phrases or config.WAKE_PHRASES)]
        self.oww_model = None
        self._load_openwakeword()

    def _load_openwakeword(self):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import openwakeword
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            # Buscar primero si hay un modelo personalizado .onnx en models/
            custom_models = list(MODELS_DIR.glob("*.onnx"))
            if custom_models:
                model_paths = [str(m) for m in custom_models]
            elif Path(self.model_name).exists():
                model_paths = [self.model_name]
            else:
                model_paths = [self.model_name]

            try:
                self.oww_model = Model(
                    wakeword_models=model_paths,
                    inference_framework="onnx",
                )
            except Exception:
                download_models()
                self.oww_model = Model(
                    wakeword_models=model_paths,
                    inference_framework="onnx",
                )
        except Exception:
            self.oww_model = None

    def reset(self):
        if self.oww_model is not None:
            self.oww_model.reset()

    def match_wake_phrase(self, transcript: str) -> Dict[str, Any]:
        """
        Verifica si un texto transcrito contiene la palabra clave ('Oye Simón' / 'Simón').
        Si el usuario dijo además el comando en la misma frase (ej. 'Oye Simón enciende la luz'),
        extrae `inline_command` para procesarlo sin latencia adicional.
        """
        norm = _normalize_text(transcript)
        if not norm:
            return {"matched": False, "trigger": None, "inline_command": None}

        # Patrón directo para "oye simon", "hey simon", "hola simon", "simon"
        match = re.search(r"\b(?:(?:oye|hey|hola|ok)\s+)?sim[oó]?n\b", norm)
        if match:
            trigger = match.group(0).strip()
            # Extraer lo que se dijo después de la palabra de activación
            after_idx = match.end()
            # Usamos una búsqueda equivalente en el texto original para conservar acentos del comando
            orig_match = re.search(
                r"\b(?:(?:oye|hey|hola|ok)\s+)?sim[oó]n[,:\s]*",
                transcript,
                flags=re.IGNORECASE,
            )
            inline_cmd = transcript[orig_match.end() :].strip() if orig_match else norm[after_idx:].strip()
            return {
                "matched": True,
                "trigger": trigger,
                "inline_command": inline_cmd if len(inline_cmd) >= 2 else None,
            }

        for phrase in self.wake_phrases:
            if phrase and phrase in norm:
                idx = norm.find(phrase) + len(phrase)
                inline_cmd = norm[idx:].strip()
                return {
                    "matched": True,
                    "trigger": phrase,
                    "inline_command": inline_cmd if len(inline_cmd) >= 2 else None,
                }

        return {"matched": False, "trigger": None, "inline_command": None}

    def wait_for_wake_word(self, stt_manager=None) -> Dict[str, Any]:
        """
        Duerme en segundo plano escuchando el stream de audio a 16kHz con bajo consumo de CPU.
        Despierta instantáneamente cuando:
        1) El modelo neural `openWakeWord` supera `self.threshold`, o
        2) Se detecta una locución corta que coincide con 'Oye Simón' / 'Simón'.
        """
        self.reset()
        if stt_manager is not None:
            stt_manager.vad.reset()

        pre_buffer = deque(maxlen=4)  # ~320 ms previos
        speech_frames: List[np.ndarray] = []
        in_speech = False
        silence_frames = 0
        # 4 frames de 80ms = 320ms de silencio para evaluar la palabra clave hablada
        max_silence_frames = 4
        max_speech_frames = 45  # ~3.6 segundos máximo para evaluar wake word

        with sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.FRAME_SAMPLES,
        ) as stream:
            while True:
                data, _ = stream.read(self.FRAME_SAMPLES)
                pcm16 = data[:, 0].copy()
                float32_frame = pcm16.astype(np.float32) / 32768.0

                # 1. Inferencia ultraligera con openWakeWord (ONNX)
                if self.oww_model is not None:
                    prediction = self.oww_model.predict(pcm16)
                    for mdl_name, score in prediction.items():
                        if float(score) >= self.threshold:
                            self.reset()
                            return {
                                "detected": True,
                                "trigger": mdl_name,
                                "score": float(score),
                                "inline_command": None,
                            }

                # 2. Detección híbrida para "Oye Simón" / "Simón" asistida por Silero VAD
                if stt_manager is not None:
                    # Evaluamos el frame de 1280 muestras en dos bloques de 512 para Silero VAD
                    p1 = stt_manager.vad.is_speech(float32_frame[:512])
                    p2 = stt_manager.vad.is_speech(float32_frame[512:1024])
                    speech_prob = max(p1, p2)

                    if not in_speech:
                        pre_buffer.append(float32_frame)
                        if speech_prob >= config.VAD_THRESHOLD:
                            in_speech = True
                            silence_frames = 0
                            speech_frames = list(pre_buffer)
                    else:
                        speech_frames.append(float32_frame)
                        if speech_prob >= config.VAD_THRESHOLD:
                            silence_frames = 0
                        else:
                            silence_frames += 1

                        if silence_frames >= max_silence_frames or len(speech_frames) >= max_speech_frames:
                            audio_segment = np.concatenate(speech_frames)
                            in_speech = False
                            speech_frames = []
                            silence_frames = 0
                            stt_manager.vad.reset()

                            # Transcribir segmento corto para verificar si dijo "Oye Simón" o "Simón"
                            if len(audio_segment) >= int(self.SAMPLE_RATE * 0.3):
                                text = stt_manager.transcribe_audio_array(
                                    audio_segment,
                                    initial_prompt="Oye Simón, Simón, enciende la luz, apaga la luz.",
                                )
                                if text:
                                    res = self.match_wake_phrase(text)
                                    if res["matched"]:
                                        self.reset()
                                        return {
                                            "detected": True,
                                            "trigger": res["trigger"],
                                            "score": 1.0,
                                            "inline_command": res["inline_command"],
                                        }
