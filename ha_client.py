from typing import Any, Dict, List, Optional
import time
import requests
import config

class HomeAssistantClient:
    """Cliente para comunicarse con la API de Home Assistant con caché de baja latencia."""

    def __init__(self, url: str = config.HA_URL, token: str = config.HA_TOKEN):
        self.url = url.rstrip("/")
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        self._states_cache: List[Dict[str, Any]] = []
        self._states_cache_ts: float = 0.0
        self._cache_ttl: float = 10.0  # Segundos de validez de caché para evitar llamadas repetidas

    def update_token(self, token: str):
        self.token = token.strip()
        self._headers["Authorization"] = f"Bearer {self.token}"
        self._states_cache_ts = 0.0

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión a Home Assistant y la validez del token."""
        if not self.token:
            return {"ok": False, "error": "Token no configurado en .env"}
        try:
            resp = requests.get(f"{self.url}/api/", headers=self._headers, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "message": data.get("message", "API activa")}
            elif resp.status_code == 401:
                return {"ok": False, "error": "Token inválido o no autorizado (401)"}
            else:
                return {"ok": False, "error": f"Error del servidor HTTP {resp.status_code}"}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error": f"No se pudo conectar a {self.url}. ¿Está corriendo el contenedor?"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def process_conversation(self, text: str, language: str = config.LANGUAGE) -> Dict[str, Any]:
        """
        Envía texto en lenguaje natural a Home Assistant para que lo procese.
        Ejemplos: 'enciende la luz', 'apaga la ampolleta', '¿qué hora es?'.
        """
        endpoint = f"{self.url}/api/conversation/process"
        payload = {
            "text": text,
            "language": language.split("-")[0],  # ej: 'es'
        }
        try:
            resp = requests.post(endpoint, headers=self._headers, json=payload, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                speech = ""
                try:
                    speech = data["response"]["speech"]["plain"]["speech"]
                except (KeyError, TypeError):
                    speech = "Comando procesado."
                return {"ok": True, "speech": speech, "raw": data}
            else:
                return {"ok": False, "error": f"Error {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_states(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Obtiene la lista de todas las entidades usando caché en memoria para baja latencia."""
        now = time.monotonic()
        if not force_refresh and self._states_cache and (now - self._states_cache_ts) < self._cache_ttl:
            return self._states_cache
        try:
            resp = requests.get(f"{self.url}/api/states", headers=self._headers, timeout=1.5)
            resp.raise_for_status()
            self._states_cache = resp.json()
            self._states_cache_ts = now
            return self._states_cache
        except Exception:
            return self._states_cache

    def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene el estado y atributos de una entidad específica en Home Assistant."""
        try:
            resp = requests.get(f"{self.url}/api/states/{entity_id}", headers=self._headers, timeout=1.5)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    def call_service(self, domain: str, service: str, service_data: Optional[Dict[str, Any]] = None) -> bool:
        """Llama a un servicio específico, por ejemplo 'light', 'turn_on'."""
        try:
            endpoint = f"{self.url}/api/services/{domain}/{service}"
            resp = requests.post(endpoint, headers=self._headers, json=service_data or {}, timeout=2.0)
            return resp.status_code in (200, 201)
        except Exception:
            return False

