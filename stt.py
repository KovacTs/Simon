from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
from typing import Optional
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


class STTManager:
    """Módulo de captura y transcripción de voz usando el micrófono."""

    def __init__(self, language: str = config.LANGUAGE):
        self.language = language
        self.recognizer = sr.Recognizer()
        
        # Umbral de energía optimizado para evitar que corte palabras
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.dynamic_energy_ratio = 1.5
        self.recognizer.pause_threshold = 0.9  # Espera 0.9 segundos de silencio antes de dar por terminada la frase
        self.recognizer.phrase_threshold = 0.3
        self.recognizer.non_speaking_duration = 0.5

        # Reutilizar la instancia del micrófono para evitar reabrir el dispositivo continuamente
        self._mic = sr.Microphone()

    def calibrate(self, duration: float = 1.0):
        """Calibra el nivel de ruido ambiental."""
        try:
            with self._mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=duration)
            # Asegurar que el umbral no sea excesivamente alto ni bajo
            if self.recognizer.energy_threshold < 200:
                self.recognizer.energy_threshold = 200
            elif self.recognizer.energy_threshold > 2000:
                self.recognizer.energy_threshold = 1000
            return True
        except Exception:
            return False

    def listen_and_transcribe(self, timeout: Optional[float] = 6.0, phrase_time_limit: Optional[float] = 10.0) -> Optional[str]:
        """
        Escucha por el micrófono hasta que detecta una frase y la transcribe a texto.
        Devuelve el texto en minúsculas o None si no se reconoció nada.
        """
        try:
            with self._mic as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            
            # Reconocimiento usando el servicio de Google en español
            # Primero intenta con el idioma configurado (ej: es-CL o es-419)
            try:
                texto = self.recognizer.recognize_google(audio, language=self.language)
            except sr.UnknownValueError:
                # Intento de respaldo con español general
                texto = self.recognizer.recognize_google(audio, language="es-419")

            return texto.strip()
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return None
        except Exception as e:
            raise e
