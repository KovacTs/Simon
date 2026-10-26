import asyncio
import os
import re
import subprocess
import tempfile
import edge_tts
import config


class TTSManager:
    """
    Sintetizador de voz neural optimizado para hablar con fluidez natural,
    sin pausas robóticas entre cláusulas.
    """

    def __init__(
        self,
        voice: str = config.TTS_VOICE,
        rate: str = config.TTS_RATE,
        pitch: str = config.TTS_PITCH,
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

    @staticmethod
    def _fluidize_text(text: str) -> str:
        """
        Limpia signos y comas innecesarias que hacen que edge-tts inserte
        pausas robóticas o entrecortadas a mitad de una frase corta.
        """
        cleaned = re.sub(r"[*_`#~]+", "", text).strip()
        # Quitar comas tras interjecciones cortas ("Hola, ¿cómo..." -> "Hola ¿cómo...")
        cleaned = re.sub(
            r"\b(hola|buenas|claro|listo|vale|oye|mira|bueno|actualmente|hoy|mañana),\s+",
            r"\1 ",
            cleaned,
            flags=re.IGNORECASE,
        )
        # Reemplazar dos puntos o punto y coma por espacio fluido
        cleaned = re.sub(r"\s*[:;]\s*", " ", cleaned)
        # Evitar pausas largas entre oraciones cortas uniendo puntos intermedios con coma suave
        cleaned = re.sub(r"\.\s+(?=[a-záéíóúñ¿¡])", ", ", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip()

    async def _synthesize_and_play(self, text: str):
        fluid_text = self._fluidize_text(text)
        if not fluid_text:
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            communicate = edge_tts.Communicate(
                fluid_text,
                self.voice,
                rate=self.rate,
                pitch=self.pitch,
            )
            await communicate.save(temp_path)

            # Reproducir con ffplay recortando silencios artificiales largos (>160ms) entre palabras
            subprocess.run(
                [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    "-af",
                    "silenceremove=stop_periods=-1:stop_duration=0.16:stop_threshold=-45dB",
                    temp_path,
                ],
                check=False,
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def speak(self, text: str):
        """Sintetiza y reproduce el texto en voz alta de manera síncrona."""
        if not text or not text.strip():
            return
        asyncio.run(self._synthesize_and_play(text))
