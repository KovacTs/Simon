import asyncio
import os
import subprocess
import tempfile
import edge_tts
import config

class TTSManager:
    """Sintetizador de voz usando edge-tts y reproducción local con ffplay."""

    def __init__(self, voice: str = config.TTS_VOICE):
        self.voice = voice

    async def _synthesize_and_play(self, text: str):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(temp_path)

            # Reproducir audio con ffplay sin ventana gráfica y saliendo al finalizar
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", temp_path],
                check=False
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def speak(self, text: str):
        """Sintetiza y reproduce el texto en voz alta de manera síncrona."""
        if not text or not text.strip():
            return
        asyncio.run(self._synthesize_and_play(text))
