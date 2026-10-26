import os
import subprocess
from pathlib import Path
import numpy as np
import sounddevice as sd
import soundfile as sf
import config

CHIMES_DIR = Path(__file__).resolve().parent / "assets" / "chimes"


class ChimeManager:
    """
    Generador y reproductor de efectos auditivos (Chimes) para Simón (Fase 1).
    Incluye sonidos para:
    - Activación por Wake Word (wake)
    - Confirmación de acción exitosa (confirm)
    - Error o acción fallida (error)
    - Alarma de temporizador (alarm)
    """

    SAMPLE_RATE = 24000

    def __init__(self, enabled: bool = config.CHIMES_ENABLED):
        self.enabled = enabled
        CHIMES_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_default_chimes()

    def _generate_tone(
        self,
        freq_start: float,
        freq_end: float,
        duration_ms: float,
        volume: float = 0.35,
    ) -> np.ndarray:
        """Genera un tono sinusoidal suave con envolvente fade-in / fade-out."""
        num_samples = int(self.SAMPLE_RATE * (duration_ms / 1000.0))
        t = np.linspace(0, duration_ms / 1000.0, num_samples, endpoint=False)
        freqs = np.linspace(freq_start, freq_end, num_samples)
        phase = 2 * np.pi * np.cumsum(freqs) / self.SAMPLE_RATE
        wave = np.sin(phase) + 0.25 * np.sin(2 * phase)  # Armónico suave

        # Envolvente suave para evitar clics de audio
        attack = max(1, int(num_samples * 0.12))
        release = max(1, int(num_samples * 0.35))
        envelope = np.ones(num_samples)
        envelope[:attack] = np.linspace(0.0, 1.0, attack)
        envelope[-release:] = np.linspace(1.0, 0.0, release)

        audio = (wave * envelope * volume).astype(np.float32)
        return np.clip(audio, -1.0, 1.0)

    def _ensure_default_chimes(self):
        """Pre-genera los archivos WAV de chimes si no existen en assets/chimes/."""
        wake_path = CHIMES_DIR / "wake.wav"
        if not wake_path.exists():
            # Doble tono ascendente brillante (estilo Alexa/asistente moderno: Mi5 -> La5)
            t1 = self._generate_tone(659.25, 659.25, 85, volume=0.32)
            gap = np.zeros(int(self.SAMPLE_RATE * 0.025), dtype=np.float32)
            t2 = self._generate_tone(880.0, 987.77, 130, volume=0.38)
            sf.write(str(wake_path), np.concatenate([t1, gap, t2]), self.SAMPLE_RATE)

        confirm_path = CHIMES_DIR / "confirm.wav"
        if not confirm_path.exists():
            # Acorde corto ascendente de confirmación (Do5 -> Sol5)
            t1 = self._generate_tone(523.25, 587.33, 70, volume=0.28)
            gap = np.zeros(int(self.SAMPLE_RATE * 0.02), dtype=np.float32)
            t2 = self._generate_tone(783.99, 783.99, 110, volume=0.32)
            sf.write(str(confirm_path), np.concatenate([t1, gap, t2]), self.SAMPLE_RATE)

        error_path = CHIMES_DIR / "error.wav"
        if not error_path.exists():
            # Tono descendente grave para indicar fallo o cancelación (Mi4 -> Do4)
            t1 = self._generate_tone(329.63, 311.13, 110, volume=0.32)
            gap = np.zeros(int(self.SAMPLE_RATE * 0.03), dtype=np.float32)
            t2 = self._generate_tone(261.63, 220.0, 160, volume=0.35)
            sf.write(str(error_path), np.concatenate([t1, gap, t2]), self.SAMPLE_RATE)

        alarm_path = CHIMES_DIR / "alarm.wav"
        if not alarm_path.exists():
            # Secuencia rítmica para temporizador completado
            beep = self._generate_tone(880.0, 880.0, 120, volume=0.45)
            short_gap = np.zeros(int(self.SAMPLE_RATE * 0.07), dtype=np.float32)
            long_gap = np.zeros(int(self.SAMPLE_RATE * 0.25), dtype=np.float32)
            pattern = np.concatenate([beep, short_gap, beep, short_gap, beep, long_gap, beep, short_gap, beep])
            sf.write(str(alarm_path), pattern, self.SAMPLE_RATE)

    def _play_file(self, wav_path: Path):
        if not self.enabled or not wav_path.exists():
            return
        try:
            data, sr = sf.read(str(wav_path), dtype="float32")
            sd.play(data, sr)
            sd.wait()
        except Exception:
            # Fallback silencioso a ffplay si sounddevice está ocupado
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(wav_path)],
                    check=False,
                )
            except Exception:
                pass

    def play_wake(self):
        """Sonido corto al detectar la palabra de activación ('Oye Simón')."""
        self._play_file(CHIMES_DIR / "wake.wav")

    def play_confirm(self):
        """Sonido de confirmación al ejecutar una acción con éxito."""
        self._play_file(CHIMES_DIR / "confirm.wav")

    def play_error(self):
        """Sonido de fallo o cuando no se comprendió la orden."""
        self._play_file(CHIMES_DIR / "error.wav")

    def play_alarm(self):
        """Sonido de alarma para temporizadores finalizados."""
        self._play_file(CHIMES_DIR / "alarm.wav")
