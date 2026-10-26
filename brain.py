from collections import deque
from datetime import datetime
import json
import random
import re
from typing import Any, Callable, Deque, Dict, List, Optional
import config
from ha_client import HomeAssistantClient
from skills import COLOR_MAP_RGB, SimonToolkit


class SimonBrain:
    """
    Cerebro de Simón (Fase 2) con Selector de Motor y Baja Latencia:
    Modos soportados (config.LLM_PROVIDER):
    - 'local': Motor local instantáneo (< 20 ms) con Tools + Memoria Contextual de 5 turnos.
    - 'hybrid': Domótica, temporizadores y clima en < 20 ms local; preguntas abiertas van a Gemini u Ollama.
    - 'gemini': Todo pasa por Google Gemini API Key (con ejecución en 1 paso para acciones visuales).
    - 'ollama': Todo pasa por tu servidor local de Ollama (llama3.2, qwen2.5, gemma2).
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        on_timer_finished: Optional[Callable[[str], None]] = None,
    ):
        self.ha = ha_client
        self.toolkit = SimonToolkit(ha_client, on_timer_finished=on_timer_finished)
        self.history: Deque[Dict[str, Any]] = deque(maxlen=config.MEMORY_MAX_TURNS)
        self.last_action_status: Optional[str] = None  # "confirm" | "error" | None
        self.silent_ack: bool = False  # True cuando solo debe sonar un beep sin texto ni voz

        self.provider = config.LLM_PROVIDER if config.LLM_PROVIDER != "auto" else "hybrid"
        self._gemini_client = None
        self._ollama_client = None
        self._init_llm_clients()

    def _init_llm_clients(self):
        if config.GEMINI_API_KEY:
            try:
                from google import genai
                from google.genai import types

                self._gemini_client = genai.Client(
                    api_key=config.GEMINI_API_KEY,
                    http_options=types.HttpOptions(
                        retry_options=types.HttpRetryOptions(attempts=1)
                    ),
                )
            except Exception:
                self._gemini_client = None

        try:
            import ollama

            self._ollama_client = ollama.Client(host=config.OLLAMA_URL)
        except Exception:
            self._ollama_client = None

    def set_provider(self, provider: str, model_name: Optional[str] = None):
        """Cambia en caliente el motor de IA ('local', 'hybrid', 'gemini', 'ollama')."""
        self.provider = provider.strip().lower()
        config.LLM_PROVIDER = self.provider
        if model_name:
            if self.provider == "gemini":
                config.GEMINI_MODEL = model_name.strip()
            elif self.provider == "ollama":
                config.OLLAMA_MODEL = model_name.strip()
        self._init_llm_clients()

    def update_gemini_key(self, api_key: str) -> bool:
        """Actualiza en caliente la API Key de Google Gemini."""
        config.GEMINI_API_KEY = api_key.strip()
        self._init_llm_clients()
        return self._gemini_client is not None

    def get_active_engine_name(self) -> str:
        """Devuelve una descripción legible del motor de IA activo."""
        if self.provider == "local":
            return "⚡ Motor Local Instantáneo (<20ms, sin LLM externo)"
        if self.provider == "gemini":
            if self._gemini_client is not None:
                return f"☁️ Google Gemini ({config.GEMINI_MODEL})"
            return "☁️ Google Gemini (Sin API Key -> Fallback Local)"
        if self.provider == "ollama":
            status = "Conectado" if self._is_ollama_ready() else "No detectado -> Fallback Local"
            return f"🦙 Ollama Local ({config.OLLAMA_MODEL} - {status})"
        # Modo hybrid
        if self._gemini_client is not None:
            return f"🚀 Híbrido Rápido (Domótica <20ms + Gemini {config.GEMINI_MODEL})"
        if self._is_ollama_ready():
            return f"🚀 Híbrido Rápido (Domótica <20ms + Ollama {config.OLLAMA_MODEL})"
        return "🚀 Híbrido Rápido (Motor Local + Memoria Contextual)"

    def _is_ollama_ready(self) -> bool:
        if self._ollama_client is None:
            return False
        try:
            self._ollama_client.list()
            return True
        except Exception:
            return False

    def _record_turn(self, user_text: str, assistant_text: str):
        self.history.append(
            {
                "user": user_text,
                "assistant": assistant_text or "[Acción visual confirmada con beep]",
                "entity_id": self.toolkit.last_entity_id,
                "friendly_name": self.toolkit.last_friendly_name,
            }
        )

    def _build_system_prompt(self) -> str:
        """Construye el prompt del sistema con contexto de dispositivos y memoria."""
        states = self.ha.get_states()
        devices_summary = []
        for s in states[:25]:
            eid = s.get("entity_id", "")
            if eid.startswith(("light.", "switch.", "lock.", "sensor.", "weather.", "media_player.", "scene.")):
                fname = s.get("attributes", {}).get("friendly_name", eid)
                st = s.get("state", "")
                devices_summary.append(f"- {eid} ({fname}): estado={st}")

        devices_str = "\n".join(devices_summary) if devices_summary else "- light.ampolleta (Ampolleta principal)"
        last_dev = (
            f"{self.toolkit.last_entity_id} ({self.toolkit.last_friendly_name})"
            if self.toolkit.last_entity_id
            else "Ninguno todavía"
        )
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        return (
            "Eres Simón, un asistente de voz natural y cercano en español.\n"
            "Habla de corrido como una persona real, evitando usar comas innecesarias, listas o lenguaje robótico.\n"
            "Responde en una sola frase corta, fluida y natural sin markdown ni asteriscos.\n"
            f"Fecha y hora actual: {now_str}.\n"
            f"Último dispositivo controlado o mencionado en contexto: {last_dev}.\n"
            "Si el usuario usa pronombres como 'ponla en rojo', 'apágala', 'bájale el brillo al 50%' o 'cómo está', "
            "asume que se refiere al último dispositivo mencionado en el historial de conversación.\n"
            "Dispositivos disponibles en Home Assistant:\n"
            f"{devices_str}\n"
            "Usa siempre las herramientas disponibles (control_device, query_sensor_state, manage_timer, get_weather_forecast) "
            "cuando el usuario pida encender/apagar/cambiar color o brillo de dispositivos, consultar sensores, gestionar temporizadores o saber el clima."
        )

    def _execute_tool_call_dict(self, fn_name: str, fn_args: Dict[str, Any]) -> Any:
        tools_list = self.toolkit.get_tools_list()
        tools_map = {fn.__name__: fn for fn in tools_list}
        if fn_name in tools_map:
            res = tools_map[fn_name](**(fn_args or {}))
            if isinstance(res, dict) and res.get("ok"):
                self.last_action_status = "confirm"
            else:
                self.last_action_status = "error"
            return res
        return {"ok": False, "error": f"Herramienta desconocida: {fn_name}"}

    def _process_with_gemini(self, text_clean: str) -> Optional[str]:
        if self._gemini_client is None:
            return None
        try:
            from google.genai import types

            history_lines = []
            for turn in self.history:
                history_lines.append(f"Usuario: {turn['user']}\nSimón: {turn['assistant']}")
            context_block = "\n".join(history_lines)
            full_prompt = (
                f"Historial reciente:\n{context_block}\n\nNueva solicitud: {text_clean}"
                if context_block
                else text_clean
            )

            candidate_models = []
            for m in [config.GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]:
                if m and m not in candidate_models:
                    candidate_models.append(m)

            for model_name in candidate_models:
                try:
                    # Desactivamos AFC automático para que, si es una acción visual (BRIEF_MODE),
                    # ejecutemos la herramienta localmente y evitemos una 2da llamada HTTP a Google (mitad de latencia).
                    resp = self._gemini_client.models.generate_content(
                        model=model_name,
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=self._build_system_prompt(),
                            tools=self.toolkit.get_tools_list(),
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                            temperature=0.3,
                        ),
                    )

                    if resp.function_calls:
                        tool_outputs = []
                        for fc in resp.function_calls:
                            args = dict(fc.args) if fc.args else {}
                            res = self._execute_tool_call_dict(fc.name, args)
                            tool_outputs.append((fc.name, res))

                        # Si fue una acción visualmente verificable (encender/apagar/color/brillo),
                        # terminamos de inmediato sin hacer un segundo viaje a la nube.
                        if self.toolkit.last_visual_action_ok and config.BRIEF_MODE:
                            self.last_action_status = "confirm"
                            self.silent_ack = True
                            return ""

                        # Para herramientas que sí requieren respuesta hablada (clima, temporizador, sensor),
                        # formateamos la respuesta al instante sin esperar otro round-trip HTTP.
                        return self._format_tool_results_naturally(tool_outputs)

                    if resp and resp.text:
                        self.last_action_status = "confirm"
                        return resp.text.strip()
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _format_tool_results_naturally(self, tool_outputs: List[ Any]) -> str:
        """Formatea el resultado de una herramienta en lenguaje fluido en < 1 ms sin segundo viaje al LLM."""
        replies = []
        for fn_name, res in tool_outputs:
            if not isinstance(res, dict):
                continue
            if fn_name == "get_weather_forecast":
                if res.get("ok"):
                    city = res.get("city", config.WEATHER_CITY)
                    curr = res.get("current_temp")
                    cond = res.get("condition", "despejado")
                    fc = res.get("forecast", [])
                    if fc:
                        f0 = fc[0]
                        replies.append(
                            f"En {city} hay {curr} grados con {cond}, máxima de {f0['temp_max']} grados y {f0['rain_probability']} por ciento de probabilidad de lluvia."
                        )
                    else:
                        replies.append(f"En {city} hay {curr} grados con {cond}.")
                else:
                    replies.append("No pude obtener el pronóstico del clima en este momento.")
            elif fn_name == "manage_timer":
                act = res.get("action")
                if not res.get("ok"):
                    replies.append(res.get("message") or res.get("error") or "No pude gestionar el temporizador.")
                elif act == "start":
                    lbl = res.get("label", "general")
                    lbl_str = f" para {lbl}" if lbl != "general" else ""
                    replies.append(f"Temporizador de {res['duration_human']}{lbl_str} en marcha.")
                elif act == "cancel":
                    replies.append("Temporizador cancelado.")
                else:
                    timers = res.get("active_timers", [])
                    if not timers:
                        replies.append("No tienes ningún temporizador activo.")
                    else:
                        parts = [f"al temporizador {t['label']} le quedan {t['remaining_human']}" for t in timers]
                        replies.append("Ahora mismo " + " y ".join(parts) + ".")
            elif fn_name == "query_sensor_state":
                if res.get("ok"):
                    st = res.get("state", "desconocido")
                    est = "encendida" if st == "on" else ("apagada" if st == "off" else f"{st} {res.get('unit', '')}".strip())
                    replies.append(f"{res.get('friendly_name', 'El dispositivo')} está {est}.")
                else:
                    replies.append("No pude consultar el estado del dispositivo.")
            elif fn_name == "control_device":
                if res.get("ok"):
                    replies.append(f"Listo {res.get('friendly_name', 'dispositivo')} ajustado.")
                else:
                    replies.append("No pude comunicarme con Home Assistant para controlar el dispositivo.")
        return " ".join(replies).strip() or "Listo."

    def _process_with_ollama(self, text_clean: str) -> Optional[str]:
        if not self._is_ollama_ready():
            return None
        try:
            messages = [{"role": "system", "content": self._build_system_prompt()}]
            for turn in self.history:
                messages.append({"role": "user", "content": turn["user"]})
                messages.append({"role": "assistant", "content": turn["assistant"]})
            messages.append({"role": "user", "content": text_clean})

            resp = self._ollama_client.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                tools=self.toolkit.get_tools_list(),
            )

            msg = resp.get("message", {}) if isinstance(resp, dict) else resp.message
            tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)

            if tool_calls:
                tool_outputs = []
                for tc in tool_calls:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else tc.function
                    fn_name = fn.get("name") if isinstance(fn, dict) else fn.name
                    fn_args = fn.get("arguments", {}) if isinstance(fn, dict) else fn.arguments
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except Exception:
                            fn_args = {}
                    res = self._execute_tool_call_dict(fn_name, fn_args or {})
                    tool_outputs.append((fn_name, res))

                if self.toolkit.last_visual_action_ok and config.BRIEF_MODE:
                    self.last_action_status = "confirm"
                    self.silent_ack = True
                    return ""

                return self._format_tool_results_naturally(tool_outputs)
            else:
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                if content:
                    self.last_action_status = "confirm"
                    return content.strip()
        except Exception:
            return None
        return None

    def _try_fast_local_command(self, raw_text: str, text_clean: str) -> Optional[str]:
        """
        Intenta resolver comandos directos (saludos, hora, luces, pronombres en contexto,
        temporizadores y clima) en < 10 ms sin latencia de LLM.
        Devuelve None si es una pregunta abierta que no coincide con ninguna habilidad directa.
        """
        # 1. Saludos, estado, identidad, agradecimientos, despedidas
        if re.search(r"^(hola|buenas|buenos d[ií]as|buenas tardes|hey|qu[eé] tal)\b", text_clean):
            return random.choice(
                [
                    "Hola ¿en qué te puedo ayudar?",
                    "Hola dime qué necesitas.",
                    "Buenas aquí estoy atento.",
                ]
            )

        if re.search(r"c[oó]mo est[aá]s|c[oó]mo te va|qu[eé] cuentas", text_clean):
            return "Todo muy bien por aquí y atento a lo que necesites."

        if re.search(r"qui[eé]n eres|c[oó]mo te llamas|qu[eé] eres", text_clean):
            return "Soy Simón tu asistente de voz para el hogar."

        if re.search(r"^(gracias|muchas gracias|vale gracias|te lo agradezco)", text_clean):
            return random.choice(["De nada cualquier cosa me avisas.", "Con gusto para eso estoy."])

        if re.search(r"^(chao|adi[oó]s|hasta luego|nos vemos)", text_clean):
            return "Hasta luego que tengas un excelente día."

        if re.search(r"qu[eé] hora es|dime la hora", text_clean):
            now = datetime.now()
            return f"Son las {now.strftime('%H:%M')}."

        if re.search(r"qu[eé] puedes hacer|ayuda|comandos", text_clean):
            return (
                "Puedo controlar tus luces recordando el contexto, crear temporizadores, "
                "consultar sensores y darte el pronóstico del clima."
            )

        # 2. Herramienta: Temporizadores (manage_timer)
        if any(w in text_clean for w in ["temporizador", "timer", "alarma", "cuenta regresiva"]):
            if re.search(
                r"\b(cancela|cancelar|det[eé]n|detener|parar|borra|elimina|apaga)\b|(?:\bpara\s+el\s+(?:temporizador|timer))",
                text_clean,
            ):
                res = self.toolkit.manage_timer(action="cancel")
                if res.get("ok"):
                    self.last_action_status = "confirm"
                    return "Temporizador cancelado."
                self.last_action_status = "error"
                return res.get("message", "No hay temporizadores activos.")

            if any(w in text_clean for w in ["cuánto", "cuanto", "queda", "falta", "estado", "activos"]):
                res = self.toolkit.manage_timer(action="status")
                timers = res.get("active_timers", [])
                if not timers:
                    return "No tienes ningún temporizador activo en este momento."
                parts = [f"al temporizador {t['label']} le quedan {t['remaining_human']}" for t in timers]
                return "Ahora mismo " + " y ".join(parts) + "."

            label_match = re.search(
                r"(?:para|de nombre|llamado)\s+(?:los\s+|las\s+|el\s+|la\s+)?([a-záéíóúñ0-9\s]+)$",
                text_clean,
            )
            label = label_match.group(1).strip() if label_match else "general"
            res = self.toolkit.manage_timer(action="start", duration=text_clean, label=label)
            if res.get("ok"):
                self.last_action_status = "confirm"
                lbl_str = f" para {label}" if label != "general" else ""
                return f"Temporizador de {res['duration_human']}{lbl_str} en marcha."
            self.last_action_status = "error"
            return "Dime de cuánto tiempo quieres el temporizador por ejemplo cinco minutos."

        # 3. Herramienta: Clima y Pronóstico (get_weather_forecast)
        if any(
            w in text_clean
            for w in ["clima", "tiempo", "llover", "lluvia", "temperatura afuera", "pronóstico", "pronostico", "frío", "calor"]
        ):
            days = 3 if any(w in text_clean for w in ["semana", "próximos", "proximos", "días", "dias"]) else 1
            if "mañana" in text_clean:
                days = 2
            res = self.toolkit.get_weather_forecast(days=days)
            if res.get("ok"):
                self.last_action_status = "confirm"
                city = res.get("city", config.WEATHER_CITY)
                if res.get("source") == "home_assistant":
                    return f"En {city} está {res.get('condition')} con {res.get('temperature')} grados."
                curr_temp = res.get("current_temp")
                cond = res.get("condition", "despejado")
                forecasts = res.get("forecast", [])
                if "mañana" in text_clean and len(forecasts) >= 2:
                    f_tom = forecasts[1]
                    return (
                        f"Mañana en {city} estará {f_tom['condition']} con máxima de {f_tom['temp_max']} grados "
                        f"y {f_tom['rain_probability']} por ciento de probabilidad de lluvia."
                    )
                if forecasts:
                    f_today = forecasts[0]
                    return (
                        f"En {city} hay {curr_temp} grados con {cond}, "
                        f"la máxima será de {f_today['temp_max']} grados con {f_today['rain_probability']} por ciento de lluvia."
                    )
                return f"Ahora en {city} hay {curr_temp} grados con {cond}."
            self.last_action_status = "error"
            return "No pude obtener el pronóstico del clima en este momento."

        # 4. Resolución Contextual de Dispositivos (Memoria de las últimas 5 intervenciones)
        has_light_noun = any(
            w in text_clean for w in ["luz", "luces", "ampolleta", "foco", "b05", "iluminaci", "lampara", "lámpara"]
        )
        has_pronoun = bool(
            re.search(
                r"\b(ponla|ponlo|ap[aá]gala|ap[aá]galo|enci[eé]ndela|enci[eé]ndelo|pr[eé]ndela|pr[eé]ndelo|"
                r"b[aá]jale|s[uú]bele|c[aá]mbiala|c[aá]mbialo|la|lo)\b",
                text_clean,
            )
        )
        detected_color = next((c for c in COLOR_MAP_RGB if re.search(rf"\b{c}\b", text_clean)), None)
        pct_match = re.search(r"(\d{1,3})\s*(?:%|por\s*ciento)", text_clean)

        has_recent_device_context = bool(
            self.toolkit.last_entity_id
            or any(turn.get("entity_id") for turn in self.history)
        )

        is_device_interaction = has_light_noun or (
            has_recent_device_context and (has_pronoun or detected_color is not None or pct_match is not None)
        )

        if is_device_interaction:
            target_hint = "last" if (not has_light_noun and has_recent_device_context) else "luz"

            # 4a. Consulta de estado del sensor/dispositivo
            if any(
                w in text_clean
                for w in ["estado", "está encendida", "esta encendida", "está apagada", "esta apagada", "cómo está", "como esta"]
            ):
                res = self.toolkit.query_sensor_state(target_hint)
                if res.get("ok"):
                    self.last_action_status = "confirm"
                    estado_esp = "encendida" if res["state"] == "on" else ("apagada" if res["state"] == "off" else res["state"])
                    return f"La {res['friendly_name']} está {estado_esp}."
                self.last_action_status = "error"
                return "No pude consultar el estado del dispositivo en Home Assistant."

            # 4b. Apagar dispositivo
            if any(
                w in text_clean
                for w in ["apaga", "apagar", "apágala", "apagala", "apágalo", "apagalo", "desactiva", "corta"]
            ):
                res = self.toolkit.control_device("light", "turn_off", target_hint)
                if res.get("ok"):
                    self.last_action_status = "confirm"
                    if config.BRIEF_MODE:
                        self.silent_ack = True
                        return ""
                    return f"He apagado la {res['friendly_name']}."
                self.last_action_status = "error"
                return f"No pude apagar la {res['friendly_name']} porque Home Assistant no respondió."

            # 4c. Encender o ajustar color / brillo
            params: Dict[str, Any] = {}
            if detected_color:
                params["rgb_color"] = COLOR_MAP_RGB[detected_color]
            if pct_match:
                params["brightness_pct"] = max(1, min(100, int(pct_match.group(1))))

            if (
                params
                or any(
                    w in text_clean
                    for w in [
                        "enciende",
                        "enciéndela",
                        "enciendela",
                        "prende",
                        "préndela",
                        "prendela",
                        "activa",
                        "ilumina",
                        "ponla",
                        "ponlo",
                        "cambia",
                        "cámbiala",
                        "sube",
                        "súbele",
                        "baja",
                        "bájale",
                    ]
                )
            ):
                res = self.toolkit.control_device("light", "turn_on", target_hint, params=params)
                if res.get("ok"):
                    self.last_action_status = "confirm"
                    if config.BRIEF_MODE:
                        self.silent_ack = True
                        return ""
                    return f"Listo {res['friendly_name']} ajustada."
                else:
                    self.toolkit.last_entity_id = res["entity_id"]
                    self.toolkit.last_friendly_name = res["friendly_name"]
                    self.last_action_status = "error"
                    return "No pude comunicarme con Home Assistant para ajustar la luz."

        return None

    def process(self, raw_text: str) -> str:
        """
        Procesa una intervención del usuario según el motor seleccionado:
        - 'local': 100% local instantáneo (< 20ms).
        - 'hybrid': Comandos de domótica/temporizadores/clima en < 20ms local, y preguntas abiertas vía Gemini/Ollama.
        - 'gemini': Usa Google Gemini API Key (optimizado en 1 round-trip).
        - 'ollama': Usa Ollama local.
        """
        self.last_action_status = None
        self.silent_ack = False
        self.toolkit.last_visual_action_ok = False

        text = raw_text.strip()
        text_lower = text.lower()

        # Limpiar prefijos de activación ('oye simón', 'simón')
        text_clean = re.sub(r"^(?:(?:oye|hey|hola|ok)\s+)?sim[oó]n[,:\s]*", "", text_lower).strip()
        if not text_clean:
            text_clean = text_lower

        # MODO 1: Híbrido Rápido o Local -> intenta ruta ultrarrápida (< 15ms) primero
        if self.provider in ("local", "hybrid", "auto"):
            fast_reply = self._try_fast_local_command(raw_text, text_clean)
            if fast_reply is not None:
                self._record_turn(text_clean, fast_reply)
                return fast_reply

            # Si es modo 'hybrid' y no fue un comando directo, consultar Gemini u Ollama para preguntas abiertas
            if self.provider in ("hybrid", "auto"):
                if self._gemini_client is not None:
                    llm_reply = self._process_with_gemini(text_clean)
                    if llm_reply is not None:
                        self._record_turn(text_clean, llm_reply)
                        return llm_reply
                if self._is_ollama_ready():
                    ollama_reply = self._process_with_ollama(text_clean)
                    if ollama_reply is not None:
                        self._record_turn(text_clean, ollama_reply)
                        return ollama_reply

        # MODO 2: Google Gemini directo
        elif self.provider == "gemini":
            llm_reply = self._process_with_gemini(text_clean)
            if llm_reply is not None:
                self._record_turn(text_clean, llm_reply)
                return llm_reply

        # MODO 3: Ollama Local directo
        elif self.provider == "ollama":
            ollama_reply = self._process_with_ollama(text_clean)
            if ollama_reply is not None:
                self._record_turn(text_clean, ollama_reply)
                return ollama_reply

        # Respaldo final (local + conversación de Home Assistant)
        fallback_reply = self._try_fast_local_command(raw_text, text_clean)
        if fallback_reply is not None:
            self._record_turn(text_clean, fallback_reply)
            return fallback_reply

        res = self.ha.process_conversation(text_clean)
        if res.get("ok"):
            speech = res.get("speech", "").strip()
            if speech and "no entend" not in speech.lower() and "no se reconoci" not in speech.lower():
                self.last_action_status = "confirm"
                self._record_turn(text_clean, speech)
                return speech

        self.last_action_status = "error"
        reply = f"No entendí la orden {raw_text}."
        self._record_turn(text_clean, reply)
        return reply
