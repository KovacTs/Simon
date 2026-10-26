import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables desde el archivo .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

HA_URL = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "").strip()
LANGUAGE = os.getenv("LANGUAGE", "es-CL")
TTS_VOICE = os.getenv("TTS_VOICE", "es-CL-LorenzoNeural")
