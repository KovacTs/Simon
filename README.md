# Simón - Asistente de Voz para Home Assistant

**Simón** es un asistente de voz en Python diseñado para controlar tu hogar inteligente a través de [Home Assistant](http://localhost:8123) usando lenguaje natural.

---

## 🚀 Características

- **Comprensión en lenguaje natural:** Se conecta directamente a la API de conversación de Home Assistant (`/api/conversation/process`).
- **Sintetizador de voz neural (TTS):** Voces naturales en español (usando `edge-tts`).
- **Reconocimiento de voz (STT):** Captura de audio por micrófono con filtrado de ruido y transcripción instantánea en español.
- **3 Modos de uso:**
  1. **Modo Texto:** Prueba comandos escribiendo directamente en la terminal.
  2. **Pulsar para hablar (Push-to-Talk):** Presiona `[Enter]`, habla y escucha la respuesta.
  3. **Modo Voz continuo:** Escucha constantemente tus órdenes.

---

## 🛠️ Configuración inicial

### 1. Obtener Token en Home Assistant
1. Entra a [http://localhost:8123](http://localhost:8123).
2. Haz clic en tu perfil (avatar o iniciales en la esquina inferior izquierda).
3. Ve a la pestaña **Seguridad** (o baja hasta la sección *Tokens de acceso de larga duración*).
4. Haz clic en **Crear token**, ponle de nombre `Simon` y cópialo.

### 2. Configurar el archivo `.env`
Pega tu token en el archivo `.env`:

```env
HA_URL=http://localhost:8123
HA_TOKEN=tu_token_aqui
LANGUAGE=es-CL
TTS_VOICE=es-CL-LorenzoNeural
```

*(También puedes simplemente ejecutar el programa y Simón te pedirá el token si falta).*

---

## ▶️ Ejecución

Para iniciar a Simón, ejecuta desde la carpeta del proyecto:

```bash
cd ~/Proyectos/Simon
uv run python main.py
```

---

## 💡 Ejemplos de comandos para probar con Simón

- *"Enciende la luz"*
- *"Apaga la ampolleta"*
- *"Pon el brillo de la luz al 50%"*
- *"¿Qué hora es?"*
- *"Cambia la luz a color rojo"*
