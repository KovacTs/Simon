# Simón - Asistente de Voz Inteligente para Home Assistant

**Simón** es un asistente de voz local en Python estilo Alexa diseñado para controlar tu hogar inteligente a través de [Home Assistant](http://localhost:8123) usando lenguaje natural, detección de palabra de activación (`openWakeWord`), corte rápido de voz (`Silero VAD`) y cerebro con IA Generativa + Function Calling.

---

## 🚀 Características (Fases 1 y 2 Completadas)

### 🟢 Fase 1: Wake Word, Chimes y VAD Ultrarrápido
- **Detección de Palabra de Activación (`wakeword.py`):** Integra `openWakeWord` (ONNX) y detección híbrida en español para despertar al decir **"Oye Simón"** o **"Simón"** (también soporta comandos seguidos en una sola frase como *"Oye Simón, enciende la luz"*).
- **Feedback Auditivo / Chimes (`chimes.py`):** Síntesis y reproducción de tonos para activación (`wake.wav`), confirmación de acción (`confirm.wav`), error (`error.wav`) y alarma de temporizador (`alarm.wav`).
- **Detección de Fin de Frase (`stt.py` - Silero VAD):** Cierra la escucha inmediatamente apenas dejas de hablar (`280 ms` < `300 ms`), transcribiendo localmente con `Faster-Whisper` (con respaldo en Google STT).

### 🧠 Fase 2: Cerebro con IA Generativa, Tool Calling y Memoria Contextual
- **Motor LLM Dual (`brain.py`):**
  - **Opción A (Nube):** Google Gemini (`google-genai`) con *Function Calling*.
  - **Opción B (Local):** Ollama (`ollama`) con soporte para `llama3.2`, `qwen2.5` o `gemma2`.
  - **Motor Híbrido Local:** Si no se configura Gemini ni Ollama, enruta localmente hacia las mismas herramientas manteniendo memoria contextual.
- **Sistema de Herramientas (`skills.py`):**
  - `control_device(domain, service, entity_id, params)` — Encendido, apagado, colores RGB y porcentaje de brillo.
  - `query_sensor_state(entity_id)` — Consulta de estado y atributos de sensores/luces.
  - `manage_timer(action, duration, label)` — Temporizadores concurrentes en segundo plano con alarma sonora.
  - `get_weather_forecast(days)` — Clima actual y pronóstico vía Home Assistant u Open-Meteo.
- **Memoria Contextual (Últimas 5 intervenciones):**
  - Entiende pronombres y referencias implícitas al último dispositivo:
    - *Usuario:* "Enciende la ampolleta"
    - *Usuario:* "Ahora ponla en rojo" -> *Cambia el color de la misma ampolleta a rojo.*

---

## 🛠️ Configuración (`.env`)

Copia `.env.example` a `.env` y ajusta tus parámetros:

```env
HA_URL=http://localhost:8123
HA_TOKEN=tu_token_aqui
LANGUAGE=es-CL
TTS_VOICE=es-CL-LorenzoNeural

# Fase 1: Wake Word y Silero VAD (<300ms)
WAKE_WORD_MODEL=hey_jarvis
WAKE_PHRASES=oye simón,oye simon,simón,simon
VAD_SILENCE_MS=280
STT_ENGINE=auto

# Fase 2: Cerebro LLM (auto | gemini | ollama | local)
LLM_PROVIDER=auto
GEMINI_API_KEY=
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
MEMORY_MAX_TURNS=5
```

---

## ▶️ Ejecución

```bash
cd ~/Proyectos/Simon
uv run python main.py
```
