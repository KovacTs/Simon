import os
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

import config
from ha_client import HomeAssistantClient
from brain import SimonBrain
from tts import TTSManager
from stt import STTManager

console = Console()

def save_token_to_env(token: str):
    env_file = Path(__file__).resolve().parent / ".env"
    lines = []
    token_written = False

    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.startswith("HA_TOKEN="):
            new_lines.append(f"HA_TOKEN={token.strip()}\n")
            token_written = True
        else:
            new_lines.append(line)

    if not token_written:
        new_lines.append(f"\nHA_TOKEN={token.strip()}\n")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def show_banner():
    console.print(
        Panel.fit(
            "[bold cyan]SIMON[/bold cyan] - [bold white]Asistente de Voz para Home Assistant[/bold white]\n"
            f"[dim]Conectado a: {config.HA_URL} | Voz: {config.TTS_VOICE}[/dim]",
            border_style="cyan"
        )
    )


def ensure_connection(ha: HomeAssistantClient):
    res = ha.test_connection()
    if res["ok"]:
        console.print(f"[bold green]✔ Conexión con Home Assistant establecida con éxito.[/bold green]\n")
        return True

    console.print(f"[bold yellow]⚠ Aviso:[/bold yellow] {res['error']}")
    console.print("\n[dim]Para vincular Simon con tu Home Assistant:[/dim]")
    console.print("1. Abre [cyan]http://localhost:8123[/cyan] en tu navegador.")
    console.print("2. Haz clic en tu perfil (iniciales o avatar en la esquina inferior izquierda).")
    console.print("3. Entra a la pestaña [bold]'Seguridad'[/bold] (o baja hasta la sección 'Tokens de acceso de larga duración').")
    console.print("4. Haz clic en [bold]'Crear token'[/bold], dale de nombre 'Simon' y copia el código generado.\n")

    token_input = Prompt.ask("[bold green]Pega tu token aquí (o presiona Enter para omitir por ahora)[/bold green]", password=True)
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


def process_query(texto: str, brain: SimonBrain, tts: TTSManager):
    console.print(f"\n[bold yellow]Tú:[/bold yellow] {texto}")
    
    with console.status("[cyan]Simón está pensando...[/cyan]", spinner="dots"):
        respuesta = brain.process(texto)

    console.print(f"[bold cyan]Simón:[/bold cyan] {respuesta}\n")
    tts.speak(respuesta)


def mode_text(brain: SimonBrain, tts: TTSManager):
    console.print("[dim]Modo texto activado. Escribe 'salir' para volver al menú.[/dim]\n")
    while True:
        try:
            texto = Prompt.ask("[bold green]Escribe un comando[/bold green]")
            if not texto.strip():
                continue
            if texto.lower() in ("salir", "exit", "quit"):
                break
            process_query(texto, brain, tts)
        except (KeyboardInterrupt, EOFError):
            break


def mode_push_to_talk(brain: SimonBrain, tts: TTSManager, stt: STTManager):
    console.print("[dim]Modo 'Pulsar para hablar' activado. Presiona Ctrl+C para salir.[/dim]")
    with console.status("[dim]Calibrando micrófono...[/dim]"):
        stt.calibrate(0.8)

    while True:
        try:
            Prompt.ask("[bold green]Presiona [Enter] y habla...[/bold green]")
            with console.status("[bold red]🎙️ Escuchando... habla ahora[/bold red]"):
                texto = stt.listen_and_transcribe(timeout=6.0, phrase_time_limit=8.0)
            
            if texto:
                process_query(texto, brain, tts)
            else:
                console.print("[dim]No se detectó audio comprensible.[/dim]\n")
        except (KeyboardInterrupt, EOFError):
            break


def mode_voice_continuous(brain: SimonBrain, tts: TTSManager, stt: STTManager):
    console.print("[dim]Modo voz continuo activado. Habla diciendo 'Simón' o tu orden directa. Presiona Ctrl+C para salir.[/dim]\n")
    with console.status("[dim]Calibrando micrófono para ruido ambiente...[/dim]"):
        stt.calibrate(1.0)

    while True:
        try:
            with console.status("[dim]Esperando voz...[/dim]"):
                texto = stt.listen_and_transcribe(timeout=None, phrase_time_limit=10.0)

            if texto:
                process_query(texto, brain, tts)
        except (KeyboardInterrupt, EOFError):
            break


def main():
    show_banner()
    ha = HomeAssistantClient()
    brain = SimonBrain(ha)
    tts = TTSManager()
    stt = STTManager()

    ensure_connection(ha)

    while True:
        console.print("[bold white]Selecciona el modo de interacción:[/bold white]")
        console.print("  [cyan]1[/cyan]. Modo Texto (Escribir en la terminal)")
        console.print("  [cyan]2[/cyan]. Modo 'Pulsar para hablar' (Presionar Enter y hablar)")
        console.print("  [cyan]3[/cyan]. Modo Voz continuo (Siempre escuchando)")
        console.print("  [cyan]4[/cyan]. Probar voz de Simón (TTS)")
        console.print("  [cyan]5[/cyan]. Salir")

        opcion = Prompt.ask("\nElige una opción", choices=["1", "2", "3", "4", "5"], default="1")

        if opcion == "1":
            mode_text(brain, tts)
        elif opcion == "2":
            mode_push_to_talk(brain, tts, stt)
        elif opcion == "3":
            mode_voice_continuous(brain, tts, stt)
        elif opcion == "4":
            tts.speak("Hola, soy Simón, tu nuevo asistente personal conectado a Home Assistant.")
            console.print("[green]✔ Audio reproducido.[/green]\n")
        elif opcion == "5":
            console.print("[dim]¡Hasta luego![/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()
