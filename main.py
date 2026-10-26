import os
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

import config
from ha_client import HomeAssistantClient
from brain import SimonBrain
from tts import TTSManager
from stt import STTManager
from chimes import ChimeManager
from wakeword import WakeWordDetector

console = Console()


def save_env_variable(key: str, value: str):
    env_file = Path(__file__).resolve().parent / ".env"
    lines = []
    key_written = False

    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            new_lines.append(f"{key}={value.strip()}\n")
            key_written = True
        else:
            new_lines.append(line)

    if not key_written:
        new_lines.append(f"\n{key}={value.strip()}\n")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def save_token_to_env(token: str):
    save_env_variable("HA_TOKEN", token)


def show_banner(brain: SimonBrain):
    engine_name = brain.get_active_engine_name()
    brief_label = "Activo (Solo Beep en luces)" if config.BRIEF_MODE else "Desactivado"
    console.print(
        Panel.fit(
            "[bold cyan]SIMÓN[/bold cyan] - [bold white]Asistente de Voz Inteligente (Home Assistant)[/bold white]\n"
            f"[dim]HA: {config.HA_URL} | Voz: {config.TTS_VOICE} ({config.TTS_RATE}) | VAD: Silero ({config.VAD_SILENCE_MS}ms)[/dim]\n"
            f"[dim]Cerebro IA: {engine_name} | Modo Breve: {brief_label}[/dim]",
            border_style="cyan",
        )
    )


def ensure_connection(ha: HomeAssistantClient):
    res = ha.test_connection()
    if res["ok"]:
        console.print("[bold green]✔ Conexión con Home Assistant establecida con éxito.[/bold green]\n")
        return True

    console.print(f"[bold yellow]⚠ Aviso:[/bold yellow] {res['error']}")
    console.print("\n[dim]Para vincular Simón con tu Home Assistant:[/dim]")
    console.print("1. Abre [cyan]http://localhost:8123[/cyan] en tu navegador.")
    console.print("2. Haz clic en tu perfil (iniciales o avatar en la esquina inferior izquierda).")
    console.print("3. Entra a la pestaña [bold]'Seguridad'[/bold] (o baja hasta 'Tokens de acceso de larga duración').")
    console.print("4. Haz clic en [bold]'Crear token'[/bold], dale de nombre 'Simon' y copia el código generado.\n")

    token_input = Prompt.ask(
        "[bold green]Pega tu token aquí (o presiona Enter para omitir por ahora)[/bold green]",
        password=True,
    )
    if token_input.strip():
        save_token_to_env(token_input)
        ha.update_token(token_input)
        verify = ha.test_connection()
        if verify["ok"]:
            console.print("[bold green]✔ Token guardado y verificado correctamente.[/bold green]\n")
            return True
        else:
            console.print(f"[bold red]✖ Error con el nuevo token: {verify['error']}[/bold red]\n")
            return False
    return False


def select_engine_menu(brain: SimonBrain):
    """Menú interactivo para seleccionar entre Motor Local, Híbrido, Gemini API Key u Ollama."""
    console.print(
        Panel(
            f"[bold cyan]Selector de Motor de Cerebro / IA[/bold cyan]\n"
            f"Motor actual: [bold green]{brain.get_active_engine_name()}[/bold green]\n\n"
            "  [cyan]1[/cyan]. ⚡ [bold]Motor Local Instantáneo[/bold] ([green]< 20 ms[/green] - Sin LLM externo, usa Tools + Memoria 5 turnos)\n"
            "  [cyan]2[/cyan]. 🚀 [bold]Modo Híbrido Rápido (Recomendado)[/bold] (Domótica en [green]< 20 ms[/green] local + Gemini/Ollama para preguntas abiertas)\n"
            "  [cyan]3[/cyan]. ☁️  [bold]Google Gemini API Key[/bold] (Todo pasa por la nube de Gemini)\n"
            "  [cyan]4[/cyan]. 🦙 [bold]Ollama Local[/bold] (Todo pasa por un LLM local en tu PC: llama3.2, qwen2.5, gemma2)\n"
            "  [cyan]5[/cyan]. 🔑 Cambiar / Actualizar GEMINI_API_KEY\n"
            "  [cyan]6[/cyan]. Volver",
            border_style="cyan",
        )
    )
    choice = Prompt.ask("Selecciona una opción", choices=["1", "2", "3", "4", "5", "6"], default="2")

    if choice == "1":
        brain.set_provider("local")
        save_env_variable("LLM_PROVIDER", "local")
        console.print(f"[bold green]✔ Motor cambiado a: {brain.get_active_engine_name()}[/bold green]\n")

    elif choice == "2":
        brain.set_provider("hybrid")
        save_env_variable("LLM_PROVIDER", "hybrid")
        console.print(f"[bold green]✔ Motor cambiado a: {brain.get_active_engine_name()}[/bold green]\n")

    elif choice == "3":
        if not config.GEMINI_API_KEY:
            console.print("[yellow]Aún no tienes una GEMINI_API_KEY configurada.[/yellow]")
            key_in = Prompt.ask("[bold green]Pega tu GEMINI_API_KEY[/bold green]", password=True)
            if key_in.strip():
                save_env_variable("GEMINI_API_KEY", key_in)
                brain.update_gemini_key(key_in)

        console.print("\n[bold]Elige el modelo de Gemini:[/bold]")
        console.print("  [cyan]1[/cyan]. gemini-3.5-flash-lite [green](Más rápido / Menor latencia)[/green]")
        console.print("  [cyan]2[/cyan]. gemini-3.6-flash [yellow](Más potente, mayor latencia)[/yellow]")
        m_choice = Prompt.ask("Modelo", choices=["1", "2"], default="1")
        model_name = "gemini-3.5-flash-lite" if m_choice == "1" else "gemini-3.6-flash"

        brain.set_provider("gemini", model_name=model_name)
        save_env_variable("LLM_PROVIDER", "gemini")
        save_env_variable("GEMINI_MODEL", model_name)
        console.print(f"[bold green]✔ Motor cambiado a: {brain.get_active_engine_name()}[/bold green]\n")

    elif choice == "4":
        model_name = Prompt.ask(
            "[bold green]Nombre del modelo en Ollama[/bold green]",
            default=config.OLLAMA_MODEL or "llama3.2",
        )
        brain.set_provider("ollama", model_name=model_name)
        save_env_variable("LLM_PROVIDER", "ollama")
        save_env_variable("OLLAMA_MODEL", model_name)
        console.print(f"[bold green]✔ Motor cambiado a: {brain.get_active_engine_name()}[/bold green]\n")

    elif choice == "5":
        key_input = Prompt.ask("[bold green]Pega tu GEMINI_API_KEY (o Enter para cancelar)[/bold green]", password=True)
        if key_input.strip():
            save_env_variable("GEMINI_API_KEY", key_input)
            if brain.update_gemini_key(key_input):
                console.print(
                    f"[bold green]✔ API Key actualizada. Motor activo: {brain.get_active_engine_name()}[/bold green]\n"
                )


def process_query(texto: str, brain: SimonBrain, tts: TTSManager, chimes: ChimeManager):
    console.print(f"\n[bold yellow]Tú:[/bold yellow] {texto}")

    t0 = time.perf_counter()
    with console.status("[cyan]Simón está procesando...[/cyan]", spinner="dots"):
        respuesta = brain.process(texto)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Si fue una acción visualmente verificable (encender, apagar, color, brillo),
    # solo emitimos el sonido/beep de verificación sin respuesta textual ni hablada.
    if brain.silent_ack:
        chimes.play_confirm()
        console.print(f"[dim]🔔 Acción visual ejecutada ({elapsed_ms} ms)[/dim]\n")
        return

    if brain.last_action_status == "confirm":
        chimes.play_confirm()
    elif brain.last_action_status == "error":
        chimes.play_error()

    if respuesta:
        console.print(f"[bold cyan]Simón[/bold cyan] [dim]({elapsed_ms} ms)[/dim]: {respuesta}\n")
        tts.speak(respuesta)


def mode_wake_word(
    brain: SimonBrain,
    tts: TTSManager,
    stt: STTManager,
    chimes: ChimeManager,
    wake_detector: WakeWordDetector,
):
    console.print(
        Panel(
            "[bold green]Modo Wake Word ('Oye Simón' / openWakeWord) activo[/bold green]\n"
            f"Motor activo: [cyan]{brain.get_active_engine_name()}[/cyan]\n"
            f"Di [bold cyan]'Oye Simón'[/bold cyan] (o el modelo [cyan]{config.WAKE_WORD_MODEL}[/cyan]) para despertarlo.\n"
            "[dim]Presiona Ctrl+C para volver al menú principal.[/dim]",
            border_style="green",
        )
    )
    stt.calibrate(0.5)

    while True:
        try:
            with console.status("[dim]💤 Durmiendo... esperando 'Oye Simón'[/dim]", spinner="dots"):
                wake_event = wake_detector.wait_for_wake_word(stt_manager=stt)

            if not wake_event.get("detected"):
                continue

            trigger = wake_event.get("trigger", "Oye Simón")
            inline_cmd = wake_event.get("inline_command")
            console.print(f"[bold green]🔔 Wake Word detectado:[/bold green] [cyan]{trigger}[/cyan]")
            chimes.play_wake()

            if inline_cmd:
                process_query(inline_cmd, brain, tts, chimes)
            else:
                with console.status(
                    f"[bold red]🎙️ Escuchando orden (corte Silero VAD {config.VAD_SILENCE_MS}ms)...[/bold red]"
                ):
                    texto = stt.listen_and_transcribe(timeout=5.0, phrase_time_limit=10.0)

                if texto:
                    process_query(texto, brain, tts, chimes)
                else:
                    chimes.play_error()
                    console.print("[dim]No se detectó comando tras la activación.[/dim]\n")
        except (KeyboardInterrupt, EOFError):
            console.print()
            break


def mode_text(brain: SimonBrain, tts: TTSManager, chimes: ChimeManager):
    console.print(
        "[dim]Modo texto activado. Escribe '/motor' para cambiar entre Local/Híbrido/Gemini/Ollama o 'salir' para volver.[/dim]\n"
    )
    while True:
        try:
            texto = Prompt.ask("[bold green]Escribe un comando[/bold green]")
            if not texto.strip():
                continue
            if texto.lower() in ("salir", "exit", "quit"):
                break
            if texto.lower().strip() in ("/motor", "/ia", "motor"):
                select_engine_menu(brain)
                continue
            process_query(texto, brain, tts, chimes)
        except (KeyboardInterrupt, EOFError):
            break


def mode_push_to_talk(brain: SimonBrain, tts: TTSManager, stt: STTManager, chimes: ChimeManager):
    console.print("[dim]Modo 'Pulsar para hablar' activado (Silero VAD < 300ms). Presiona Ctrl+C para salir.[/dim]")
    stt.calibrate(0.5)

    while True:
        try:
            Prompt.ask("[bold green]Presiona [Enter] y habla...[/bold green]")
            chimes.play_wake()
            with console.status("[bold red]🎙️ Escuchando... habla ahora[/bold red]"):
                texto = stt.listen_and_transcribe(timeout=6.0, phrase_time_limit=10.0)

            if texto:
                process_query(texto, brain, tts, chimes)
            else:
                chimes.play_error()
                console.print("[dim]No se detectó audio comprensible.[/dim]\n")
        except (KeyboardInterrupt, EOFError):
            break


def mode_voice_continuous(brain: SimonBrain, tts: TTSManager, stt: STTManager, chimes: ChimeManager):
    console.print(
        "[dim]Modo voz continuo activado (con corte rápido Silero VAD). Presiona Ctrl+C para salir.[/dim]\n"
    )
    stt.calibrate(0.5)

    while True:
        try:
            with console.status("[dim]Esperando voz...[/dim]"):
                texto = stt.listen_and_transcribe(timeout=None, phrase_time_limit=10.0)

            if texto:
                process_query(texto, brain, tts, chimes)
        except (KeyboardInterrupt, EOFError):
            break


def main():
    ha = HomeAssistantClient()
    chimes = ChimeManager()
    tts = TTSManager()

    def on_timer_done(label: str):
        lbl_msg = f" para {label}" if label and label != "general" else ""
        console.print(f"\n[bold magenta]⏰ ¡TEMPORIZADOR FINALIZADO{lbl_msg.upper()}![/bold magenta]")
        chimes.play_alarm()
        tts.speak(f"Atención el temporizador{lbl_msg} ya terminó.")

    brain = SimonBrain(ha, on_timer_finished=on_timer_done)
    stt = STTManager()
    wake_detector = WakeWordDetector()

    show_banner(brain)
    ensure_connection(ha)

    while True:
        console.print(f"[bold white]Selecciona el modo de interacción[/bold white] [dim](Motor: {brain.get_active_engine_name()})[/dim]:")
        console.print("  [cyan]1[/cyan]. Modo Wake Word ('Oye Simón' / openWakeWord - Estilo Alexa)")
        console.print("  [cyan]2[/cyan]. Modo Texto (Escribir en la terminal)")
        console.print("  [cyan]3[/cyan]. Modo 'Pulsar para hablar' (Presionar Enter y hablar)")
        console.print("  [cyan]4[/cyan]. Modo Voz continuo (Siempre escuchando)")
        console.print("  [cyan]5[/cyan]. Probar voz fluida y Chimes de Simón")
        console.print("  [cyan]6[/cyan]. ⚙️  Cambiar Motor de IA (Local Instantáneo / Híbrido / Gemini API / Ollama)")
        console.print("  [cyan]7[/cyan]. Salir")

        opcion = Prompt.ask("\nElige una opción", choices=["1", "2", "3", "4", "5", "6", "7"], default="1")

        if opcion == "1":
            mode_wake_word(brain, tts, stt, chimes, wake_detector)
        elif opcion == "2":
            mode_text(brain, tts, chimes)
        elif opcion == "3":
            mode_push_to_talk(brain, tts, stt, chimes)
        elif opcion == "4":
            mode_voice_continuous(brain, tts, stt, chimes)
        elif opcion == "5":
            console.print("[cyan]Reproduciendo chime de activación...[/cyan]")
            chimes.play_wake()
            tts.speak("Hola soy Simón tu asistente de voz y ahora hablo de forma mucho más fluida y natural.")
            console.print("[cyan]Reproduciendo beep de confirmación visual...[/cyan]")
            chimes.play_confirm()
            console.print("[green]✔ Audio y chimes reproducidos.[/green]\n")
        elif opcion == "6":
            select_engine_menu(brain)
        elif opcion == "7":
            console.print("[dim]¡Hasta luego![/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()
