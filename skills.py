import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union
import requests
import config
from ha_client import HomeAssistantClient

# Mapa de colores en español a RGB para luces inteligentes
COLOR_MAP_RGB: Dict[str, List[int]] = {
    "rojo": [255, 0, 0],
    "roja": [255, 0, 0],
    "azul": [0, 80, 255],
    "verde": [0, 255, 0],
    "amarillo": [255, 220, 0],
    "amarilla": [255, 220, 0],
    "blanco": [255, 255, 255],
    "blanca": [255, 255, 255],
    "calido": [255, 180, 107],
    "cálido": [255, 180, 107],
    "calida": [255, 180, 107],
    "cálida": [255, 180, 107],
    "frio": [200, 225, 255],
    "frío": [200, 225, 255],
    "morado": [160, 32, 240],
    "purpura": [160, 32, 240],
    "púrpura": [160, 32, 240],
    "violeta": [148, 0, 211],
    "rosado": [255, 105, 180],
    "rosa": [255, 105, 180],
    "naranja": [255, 120, 0],
    "cian": [0, 255, 255],
    "turquesa": [64, 224, 208],
}

# Códigos meteorológicos WMO de Open-Meteo en español
WMO_WEATHER_CODES: Dict[int, str] = {
    0: "cielo despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con escarcha",
    51: "llovizna ligera",
    53: "llovizna moderada",
    55: "llovizna intensa",
    61: "lluvia ligera",
    63: "lluvia moderada",
    65: "lluvia fuerte",
    71: "nevada ligera",
    73: "nevada moderada",
    75: "nevada intensa",
    80: "chubascos ligeros",
    81: "chubascos moderados",
    82: "chubascos fuertes",
    95: "tormenta eléctrica",
}


def parse_duration_seconds(duration: Union[int, float, str, None]) -> int:
    """Convierte una duración en segundos (int/float) o texto ('10m', '5 minutos', '45s') a segundos enteros."""
    if duration is None:
        return 0
    if isinstance(duration, (int, float)):
        return max(0, int(duration))

    text = str(duration).strip().lower()
    if text.isdigit():
        return int(text)

    total = 0
    hours = re.findall(r"(\d+)\s*(?:h|hora|horas)", text)
    mins = re.findall(r"(\d+)\s*(?:m|min|minuto|minutos)", text)
    secs = re.findall(r"(\d+)\s*(?:s|seg|segundo|segundos)", text)

    for h in hours:
        total += int(h) * 3600
    for m in mins:
        total += int(m) * 60
    for s in secs:
        total += int(s)

    if total == 0:
        nums = re.findall(r"\d+", text)
        if nums:
            # Si no especificó unidad, asumimos segundos si es >=10 o minutos si viene de lenguaje natural
            val = int(nums[0])
            total = val * 60 if "min" in text else val
    return total


def format_seconds_es(seconds: int) -> str:
    """Formatea segundos en texto natural en español."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h > 0:
        parts.append(f"{h} {'hora' if h == 1 else 'horas'}")
    if m > 0:
        parts.append(f"{m} {'minuto' if m == 1 else 'minutos'}")
    if s > 0 or not parts:
        parts.append(f"{s} {'segundo' if s == 1 else 'segundos'}")
    return " y ".join(parts)


class SimonToolkit:
    """
    Sistema de Herramientas (Tools / Function Calling) de Fase 2 para Simón:
    - control_device(domain, service, entity_id, params)
    - query_sensor_state(entity_id)
    - manage_timer(action, duration, label)
    - get_weather_forecast(days)
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        on_timer_finished: Optional[Callable[[str], None]] = None,
    ):
        self.ha = ha_client
        self.on_timer_finished = on_timer_finished
        self._timers: Dict[str, Dict[str, Any]] = {}
        self._timers_lock = threading.Lock()
        self.last_entity_id: Optional[str] = None
        self.last_friendly_name: Optional[str] = None
        self.last_visual_action_ok: bool = False

    def __deepcopy__(self, memo):
        return self

    def resolve_entity(self, entity_id_or_name: Optional[str], domain: Optional[str] = None) -> Dict[str, str]:
        """
        Resuelve un entity_id real de Home Assistant a partir de un ID parcial,
        nombre amigable o el último dispositivo en memoria contextual.
        """
        states = self.ha.get_states()
        if not states:
            fallback_id = entity_id_or_name or self.last_entity_id or f"{domain or 'light'}.default"
            return {"entity_id": fallback_id, "friendly_name": fallback_id}

        # Filtrar por dominio si fue indicado
        candidates = states
        if domain:
            domain_candidates = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
            if domain_candidates:
                candidates = domain_candidates

        query = (entity_id_or_name or "").strip().lower()

        # Si el usuario o LLM usó un pronombre o dejó vacío, usar la última entidad en contexto
        if not query or query in ("last", "context", "default", "luz", "ampolleta", "foco", "lampara", "lámpara"):
            if self.last_entity_id:
                for s in candidates:
                    if s.get("entity_id") == self.last_entity_id:
                        return {
                            "entity_id": s["entity_id"],
                            "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                        }
            # Si no hay última entidad pero hay candidatos del dominio (ej. primera luz)
            first = candidates[0]
            return {
                "entity_id": first["entity_id"],
                "friendly_name": first.get("attributes", {}).get("friendly_name", first["entity_id"]),
            }

        # 1. Coincidencia exacta de entity_id
        for s in states:
            if s.get("entity_id", "").lower() == query:
                return {
                    "entity_id": s["entity_id"],
                    "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                }

        # 2. Coincidencia parcial en friendly_name o entity_id
        for s in candidates:
            eid = s.get("entity_id", "").lower()
            fname = s.get("attributes", {}).get("friendly_name", "").lower()
            if query in eid or query in fname or fname in query:
                return {
                    "entity_id": s["entity_id"],
                    "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                }

        # 3. Fallback al primer dispositivo del dominio
        first = candidates[0]
        return {
            "entity_id": first["entity_id"],
            "friendly_name": first.get("attributes", {}).get("friendly_name", first["entity_id"]),
        }

    def control_device(
        self,
        domain: str,
        service: str,
        entity_id: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Controla un dispositivo en Home Assistant (luces, interruptores, cerraduras, escenas, media_player).

        Args:
            domain: Dominio de Home Assistant, ej. 'light', 'switch', 'lock', 'media_player', 'scene'.
            service: Servicio a ejecutar, ej. 'turn_on', 'turn_off', 'toggle', 'lock', 'unlock'.
            entity_id: ID de la entidad (ej. 'light.ampolleta') o nombre del dispositivo.
            params: Parámetros opcionales como {'brightness_pct': 50, 'rgb_color': [255, 0, 0], 'color_name': 'rojo'}.
        """
        domain = (domain or "light").strip().lower()
        service = (service or "turn_on").strip().lower()
        resolved = self.resolve_entity(entity_id, domain=domain)
        target_id = resolved["entity_id"]
        friendly_name = resolved["friendly_name"]

        service_data: Dict[str, Any] = {"entity_id": target_id}
        if params and isinstance(params, dict):
            clean_params = dict(params)
            # Convertir nombre de color en español a rgb_color si viene en params
            if "color" in clean_params and "rgb_color" not in clean_params:
                c_val = str(clean_params.pop("color")).lower().strip()
                if c_val in COLOR_MAP_RGB:
                    clean_params["rgb_color"] = COLOR_MAP_RGB[c_val]
            if "color_name" in clean_params and "rgb_color" not in clean_params:
                c_val = str(clean_params.get("color_name")).lower().strip()
                if c_val in COLOR_MAP_RGB:
                    clean_params.pop("color_name", None)
                    clean_params["rgb_color"] = COLOR_MAP_RGB[c_val]
            service_data.update(clean_params)

        ok = self.ha.call_service(domain, service, service_data)
        if ok:
            self.last_entity_id = target_id
            self.last_friendly_name = friendly_name
            if domain in ("light", "switch", "scene"):
                self.last_visual_action_ok = True

        return {
            "ok": ok,
            "domain": domain,
            "service": service,
            "entity_id": target_id,
            "friendly_name": friendly_name,
            "params": service_data,
        }

    def query_sensor_state(self, entity_id: str = "") -> Dict[str, Any]:
        """
        Consulta el estado actual y atributos de un sensor o dispositivo en Home Assistant.

        Args:
            entity_id: ID de la entidad (ej. 'light.b05', 'sensor.temperatura') o nombre a buscar.
        """
        resolved = self.resolve_entity(entity_id)
        target_id = resolved["entity_id"]
        state_obj = self.ha.get_state(target_id)

        if not state_obj:
            return {
                "ok": False,
                "entity_id": target_id,
                "error": f"No se pudo obtener el estado de {target_id} en Home Assistant.",
            }

        self.last_entity_id = target_id
        attrs = state_obj.get("attributes", {})
        self.last_friendly_name = attrs.get("friendly_name", target_id)

        return {
            "ok": True,
            "entity_id": target_id,
            "friendly_name": self.last_friendly_name,
            "state": state_obj.get("state", "desconocido"),
            "unit": attrs.get("unit_of_measurement", ""),
            "brightness": attrs.get("brightness"),
            "rgb_color": attrs.get("rgb_color"),
        }

    def manage_timer(
        self,
        action: str,
        duration: Union[int, str] = 0,
        label: str = "general",
    ) -> Dict[str, Any]:
        """
        Crea, consulta o cancela temporizadores locales en segundo plano.

        Args:
            action: Acción a realizar: 'start' (crear/iniciar), 'status' (consultar tiempo restante) o 'cancel' (cancelar).
            duration: Duración en segundos (ej. 600) o texto (ej. '10m', '5 minutos'). Requerido para 'start'.
            label: Etiqueta del temporizador (ej. 'fideos', 'horno', 'general').
        """
        act = (action or "status").strip().lower()
        lbl = (label or "general").strip().lower()

        if act in ("start", "create", "set", "iniciar", "crear", "poner"):
            seconds = parse_duration_seconds(duration)
            if seconds <= 0:
                return {"ok": False, "error": "La duración del temporizador debe ser mayor a 0 segundos."}

            with self._timers_lock:
                # Si ya había uno con la misma etiqueta, cancelarlo antes de reemplazarlo
                old = self._timers.get(lbl)
                if old and old.get("timer"):
                    old["timer"].cancel()

                end_time = time.time() + seconds

                def _trigger_alarm(timer_label: str = lbl):
                    with self._timers_lock:
                        self._timers.pop(timer_label, None)
                    if self.on_timer_finished:
                        self.on_timer_finished(timer_label)

                t = threading.Timer(seconds, _trigger_alarm)
                t.daemon = True
                t.start()

                self._timers[lbl] = {
                    "label": lbl,
                    "duration": seconds,
                    "end_time": end_time,
                    "timer": t,
                }

            return {
                "ok": True,
                "action": "start",
                "label": lbl,
                "duration_seconds": seconds,
                "duration_human": format_seconds_es(seconds),
            }

        elif act in ("cancel", "stop", "delete", "cancelar", "detener", "parar"):
            with self._timers_lock:
                if lbl in self._timers:
                    self._timers[lbl]["timer"].cancel()
                    del self._timers[lbl]
                    return {"ok": True, "action": "cancel", "label": lbl, "cancelled": [lbl]}
                elif self._timers:
                    # Cancelar todos si no especificó etiqueta exacta
                    cancelled_labels = list(self._timers.keys())
                    for info in self._timers.values():
                        info["timer"].cancel()
                    self._timers.clear()
                    return {"ok": True, "action": "cancel", "cancelled": cancelled_labels}
                return {"ok": False, "action": "cancel", "message": "No hay ningún temporizador activo para cancelar."}

        else:  # status / query / list
            now = time.time()
            active_list = []
            with self._timers_lock:
                for k, info in list(self._timers.items()):
                    rem = int(round(info["end_time"] - now))
                    if rem > 0:
                        active_list.append(
                            {
                                "label": k,
                                "remaining_seconds": rem,
                                "remaining_human": format_seconds_es(rem),
                            }
                        )
                    else:
                        self._timers.pop(k, None)

            return {
                "ok": True,
                "action": "status",
                "active_timers": active_list,
            }

    def get_weather_forecast(self, days: int = 1) -> Dict[str, Any]:
        """
        Obtiene el clima actual y el pronóstico meteorológico para los próximos días.

        Args:
            days: Cantidad de días de pronóstico a consultar (1 a 7). Por defecto 1 (hoy).
        """
        days = max(1, min(7, int(days or 1)))

        # 1. Intentar primero obtener entidad weather.* desde Home Assistant
        states = self.ha.get_states()
        for s in states:
            if s.get("entity_id", "").startswith("weather."):
                attrs = s.get("attributes", {})
                return {
                    "ok": True,
                    "source": "home_assistant",
                    "city": attrs.get("friendly_name", config.WEATHER_CITY),
                    "condition": s.get("state"),
                    "temperature": attrs.get("temperature"),
                    "humidity": attrs.get("humidity"),
                    "wind_speed": attrs.get("wind_speed"),
                }

        # 2. Consultar Open-Meteo API abierta (sin requerir API key)
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": config.WEATHER_LAT,
                "longitude": config.WEATHER_LON,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": days,
            }
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            current = data.get("current", {})
            daily = data.get("daily", {})
            w_code = int(current.get("weather_code", 0))
            condition_es = WMO_WEATHER_CODES.get(w_code, "condiciones variables")

            forecasts = []
            dates = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            rain_probs = daily.get("precipitation_probability_max", [])
            d_codes = daily.get("weather_code", [])

            for i in range(min(days, len(dates))):
                forecasts.append(
                    {
                        "date": dates[i],
                        "temp_max": max_temps[i] if i < len(max_temps) else None,
                        "temp_min": min_temps[i] if i < len(min_temps) else None,
                        "rain_probability": rain_probs[i] if i < len(rain_probs) else 0,
                        "condition": WMO_WEATHER_CODES.get(int(d_codes[i]), "variable")
                        if i < len(d_codes)
                        else condition_es,
                    }
                )

            return {
                "ok": True,
                "source": "open-meteo",
                "city": config.WEATHER_CITY,
                "current_temp": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed": current.get("wind_speed_10m"),
                "condition": condition_es,
                "forecast": forecasts,
            }
        except Exception as e:
            return {"ok": False, "error": f"No se pudo obtener el pronóstico del clima: {e}"}

    def get_tools_list(self) -> List[Callable]:
        """Devuelve la lista de funciones de herramientas con firmas compatibles con Gemini y Ollama."""
        toolkit = self

        def control_device(
            domain: str,
            service: str,
            entity_id: str = "",
            color_name: str = "",
            brightness_pct: int = 0,
        ) -> Dict[str, Any]:
            """
            Controla un dispositivo en Home Assistant (encender, apagar, cambiar color o brillo de luces, interruptores, escenas).

            Args:
                domain: Dominio de Home Assistant, ej. 'light', 'switch', 'lock', 'media_player', 'scene'.
                service: Servicio a ejecutar, ej. 'turn_on', 'turn_off', 'toggle', 'lock', 'unlock'.
                entity_id: ID de la entidad (ej. 'light.ampolleta') o 'last' para el último dispositivo en contexto.
                color_name: Color opcional en español para luces (ej. 'rojo', 'azul', 'verde', 'blanco', 'calido', 'morado').
                brightness_pct: Porcentaje de brillo opcional entre 1 y 100 (0 si no se desea cambiar brillo).
            """
            params: Dict[str, Any] = {}
            if color_name:
                params["color_name"] = color_name
            if brightness_pct and int(brightness_pct) > 0:
                params["brightness_pct"] = max(1, min(100, int(brightness_pct)))
            return toolkit.control_device(domain=domain, service=service, entity_id=entity_id, params=params)

        def query_sensor_state(entity_id: str = "") -> Dict[str, Any]:
            """
            Consulta el estado actual y atributos de un sensor o dispositivo en Home Assistant.

            Args:
                entity_id: ID de la entidad (ej. 'light.ampolleta', 'sensor.temperatura') o nombre a buscar.
            """
            return toolkit.query_sensor_state(entity_id=entity_id)

        def manage_timer(action: str, duration: str = "", label: str = "general") -> Dict[str, Any]:
            """
            Crea, consulta o cancela temporizadores locales en segundo plano.

            Args:
                action: Acción a realizar: 'start' (iniciar), 'status' (consultar cuánto queda) o 'cancel' (cancelar).
                duration: Duración como texto (ej. '5 minutos', '30 segundos', '120') cuando action es 'start'.
                label: Etiqueta del temporizador (ej. 'fideos', 'horno', 'general').
            """
            return toolkit.manage_timer(action=action, duration=duration, label=label)

        def get_weather_forecast(days: int = 1) -> Dict[str, Any]:
            """
            Obtiene el clima actual y el pronóstico meteorológico para los próximos días.

            Args:
                days: Cantidad de días de pronóstico a consultar (1 para hoy, 2 para mañana, hasta 7).
            """
            return toolkit.get_weather_forecast(days=days)

        return [
            control_device,
            query_sensor_state,
            manage_timer,
            get_weather_forecast,
        ]

