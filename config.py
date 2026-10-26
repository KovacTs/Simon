import os
import socket
from pathlib import Path
from dotenv import load_dotenv

# Evitar timeouts de 3-5s por IPv6 sin ruta al conectar con edge-tts, Gemini u Open-Meteo
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_preferred_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0:
        try:
            return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        except Exception:
            pass
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _ipv4_preferred_getaddrinfo

# Cargar variables desde el archivo .env
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

# --- Home Assistant ---
HA_URL = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "").strip()

# --- Idioma y Voz (TTS) ---
LANGUAGE = os.getenv("LANGUAGE", "es-CL")
TTS_VOICE = os.getenv("TTS_VOICE", "es-CL-LorenzoNeural")
TTS_RATE = os.getenv("TTS_RATE", "+12%")
TTS_PITCH = os.getenv("TTS_PITCH", "+0Hz")

# --- Fase 1: Wake Word, Chimes, Silero VAD y STT ---
WAKE_WORD_MODEL = os.getenv("WAKE_WORD_MODEL", "hey_jarvis").strip()
WAKE_WORD_THRESHOLD = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
WAKE_PHRASES = [
    p.strip().lower()
    for p in os.getenv("WAKE_PHRASES", "oye simón,oye simon,simón,simon,hey simon").split(",")
    if p.strip()
]
CHIMES_ENABLED = os.getenv("CHIMES_ENABLED", "true").lower() in ("1", "true", "yes", "si", "sí")
# Modo silencioso (Brief Mode): para acciones visuales (luces: encender, apagar, color, brillo)
# solo reproduce un beep/chime de confirmación sin respuesta hablada ni texto innecesario
BRIEF_MODE = os.getenv("BRIEF_MODE", "true").lower() in ("1", "true", "yes", "si", "sí")

# Silero VAD (< 300ms fin de frase según Roadmap)
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "280"))
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "250"))

# Motor STT: "auto", "faster_whisper" o "google"
STT_ENGINE = os.getenv("STT_ENGINE", "auto").strip().lower()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base").strip()

# --- Fase 2: Cerebro LLM (Gemini / Ollama / Híbrido / Local) + Memoria Contextual ---
# Proveedores soportados: "hybrid" (rápido local + LLM), "local" (100% local <20ms), "gemini" (API Key), "ollama" (LLM local)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "hybrid").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2").strip()

MEMORY_MAX_TURNS = int(os.getenv("MEMORY_MAX_TURNS", "5"))

# --- Ubicación por defecto para Clima (Open-Meteo fallback) ---
WEATHER_CITY = os.getenv("WEATHER_CITY", "Santiago")
WEATHER_LAT = float(os.getenv("WEATHER_LAT", "-33.4489"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "-70.6693"))
