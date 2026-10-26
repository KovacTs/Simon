import re
import random
from typing import Dict, Any, List, Optional
from ha_client import HomeAssistantClient

class SimonBrain:
    """Cerebro de Simón que combina conversación informal, atajos directos y Home Assistant."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client

    def _get_lights(self) -> List[Dict[str, Any]]:
        """Obtiene todas las luces disponibles en Home Assistant."""
        try:
            states = self.ha.get_states()
            return [s for s in states if s.get("entity_id", "").startswith("light.")]
        except Exception:
            return []

    def process(self, raw_text: str) -> str:
        text = raw_text.strip().lower()
        # Limpiar llamadas como 'simon', 'oye simon'
        text_clean = re.sub(r"^(oye\s+)?sim[oó]n[,:\s]*", "", text).strip()
        if not text_clean:
            text_clean = text

        # 1. Saludos
        if re.search(r"^(hola|buenas|buenos d[ií]as|buenas tardes|buenas noches|hey|qu[eé] tal)", text_clean):
            opciones = [
                "¡Hola! ¿En qué te puedo ayudar?",
                "¡Hola! Aquí estoy listo para ayudarte.",
                "¡Buenas! Dime qué necesitas encender o apagar.",
            ]
            return random.choice(opciones)

        # 2. Estado de ánimo / Cómo estás
        if re.search(r"c[oó]mo est[aá]s|c[oó]mo te va|qu[eé] cuentas", text_clean):
            opciones = [
                "¡Todo excelente por aquí! Listo para recibir tus órdenes.",
                "Muy bien, conectado y atento a tus comandos.",
            ]
            return random.choice(opciones)

        # 3. Identidad
        if re.search(r"qui[eé]n eres|c[oó]mo te llamas|qu[eé] eres", text_clean):
            return "Soy Simón, tu asistente personal conectado a Home Assistant."

        # 4. Agradecimientos
        if re.search(r"^(gracias|muchas gracias|vale gracias|te lo agradezco)", text_clean):
            opciones = [
                "¡De nada! Cualquier cosa me avisas.",
                "Con gusto, aquí estoy.",
                "¡Para eso estoy!",
            ]
            return random.choice(opciones)

        # 5. Despedidas
        if re.search(r"^(chao|adi[oó]s|hasta luego|nos vemos|buenas noches$)", text_clean):
            return "¡Hasta luego! Que tengas un excelente día."

        # 6. Ayuda
        if re.search(r"qu[eé] puedes hacer|ayuda|comandos", text_clean):
            return (
                "Puedo controlar tus luces y dispositivos de Home Assistant. "
                "Prueba con: 'enciende la luz', 'apaga la ampolleta', 'luz al 50%' o '¿qué hora es?'."
            )

        # 7. Control inteligente de iluminación (sin depender de la rigidez de nombres de HA)
        lights = self._get_lights()
        is_light_command = any(word in text_clean for word in ["luz", "ampolleta", "foco", "b05", "iluminaci", "lampara", "lámpara"])

        # Detectar encendido de luces
        if is_light_command and any(w in text_clean for w in ["enciende", "prende", "activar", "activa", "ilumina"]):
            if lights:
                target = lights[0]["entity_id"]
                friendly_name = lights[0].get("attributes", {}).get("friendly_name", "ampolleta")
                ok = self.ha.call_service("light", "turn_on", {"entity_id": target})
                if ok:
                    return f"Listo, he encendido la {friendly_name}."
                return "Intenté encender la luz pero ocurrió un error."
            return "No encontré ninguna luz configurada en Home Assistant."

        # Detectar apagado de luces
        if is_light_command and any(w in text_clean for w in ["apaga", "apagar", "desactiva", "desactivar", "corta"]):
            if lights:
                target = lights[0]["entity_id"]
                friendly_name = lights[0].get("attributes", {}).get("friendly_name", "ampolleta")
                ok = self.ha.call_service("light", "turn_off", {"entity_id": target})
                if ok:
                    return f"Listo, he apagado la {friendly_name}."
                return "Intenté apagar la luz pero ocurrió un error."
            return "No encontré ninguna luz configurada en Home Assistant."

        # Detectar consulta de estado de la luz
        if is_light_command and any(w in text_clean for w in ["estado", "está", "esta encendida", "esta prendida", "esta apagada"]):
            if lights:
                state = lights[0].get("state", "desconocido")
                friendly_name = lights[0].get("attributes", {}).get("friendly_name", "ampolleta")
                estado_esp = "encendida" if state == "on" else "apagada"
                return f"La {friendly_name} está {estado_esp}."

        # 8. Para otras órdenes, delegar al procesador de conversación de Home Assistant
        res = self.ha.process_conversation(text_clean)
        if res.get("ok"):
            speech = res.get("speech", "").strip()
            if speech and "no entend" not in speech.lower() and "no se reconoci" not in speech.lower():
                return speech

        return (
            f"No logré identificar la acción para '{raw_text}'. "
            "Prueba diciendo: 'enciende la luz', 'apaga la ampolleta' o '¿qué hora es?'."
        )
