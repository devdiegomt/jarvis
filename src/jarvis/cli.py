"""Punto de entrada por consola.

- `uv run jarvis`: chat con JARVIS.
- `uv run jarvis google-login`: autoriza el acceso a Google.
- `uv run jarvis resumen [--dry-run] [--force]`: envía el resumen del día.
- `uv run jarvis programar-resumen` / `quitar-resumen`: programa o quita el resumen diario.
- `uv run jarvis telegram`: chatear con JARVIS por Telegram.
- `uv run jarvis telegram-vincular`: obtener tu ID de Telegram (TELEGRAM_OWNER_ID).
- `uv run jarvis programar-telegram` / `quitar-telegram`: JARVIS en segundo plano al iniciar sesión.
- `uv run jarvis preparar-voz`: descarga el modelo de Whisper y la voz de Piper (notas de voz).
- `uv run jarvis estado`: configuración, tareas programadas y registros.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime

import anthropic

from jarvis import summary_cli
from jarvis.agent import Agent
from jarvis.agenda import CalendarSource, build_calendar
from jarvis.config import (
    ConfigError,
    SpeechSettings,
    VoiceSettings,
    load_google_settings,
    load_settings,
    load_speech_settings,
    load_summary_settings,
    load_voice_settings,
    read_env,
)
from jarvis.confirmation import CONFIRMATION_QUESTION, parse_yes_no
from jarvis.long_term_memory import MemoryStore
from jarvis.prompts import build_system_prompt
from jarvis.reminders import ReminderStore
from jarvis.tasks import TaskStore
from jarvis.tools import build_registry

EXIT_COMMAND = "salir"


def ask_confirmation(prompt: str, read: Callable[[str], str] = input) -> bool:
    """Muestra la acción pendiente y pregunta s/n hasta obtener una respuesta válida."""
    print(f"\n{prompt}")
    while True:
        try:
            answer = parse_yes_no(read(f"{CONFIRMATION_QUESTION}: "))
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer is not None:
            return answer
        print("Responde 's' o 'n'.")


def build_agent() -> tuple[Agent, CalendarSource]:
    settings = load_settings()
    calendar = build_calendar(settings)
    client = anthropic.Anthropic(api_key=settings.api_key)

    def now() -> datetime:
        return datetime.now(settings.timezone)

    # Los recordatorios creados aquí los envía el proceso de Telegram.
    db_path = settings.summary.db_path
    reminders, tasks, memories = (
        ReminderStore(db_path, now=now),
        TaskStore(db_path, now=now),
        MemoryStore(db_path, now=now),
    )
    agent = Agent(
        client=client,
        registry=build_registry(
            calendar, confirm=ask_confirmation, reminders=reminders, now=now, tasks=tasks, memories=memories
        ),
        model=settings.model,
        system_prompt=build_system_prompt(now().date(), memories.all()),
    )
    return agent, calendar


def run_chat() -> None:
    try:
        agent, calendar = build_agent()
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"JARVIS listo (calendario: {calendar.name}). Escribe '{EXIT_COMMAND}' para terminar.\n")
    while True:
        try:
            user_message = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_message:
            continue
        if user_message.lower() == EXIT_COMMAND:
            break

        try:
            reply = agent.send(user_message)
        except KeyboardInterrupt:
            print("\n(Interrumpido)\n")
            continue
        except anthropic.AuthenticationError:
            print("JARVIS: la API key no es válida. Revisa ANTHROPIC_API_KEY en tu .env.\n")
            continue
        except anthropic.APIConnectionError:
            print("JARVIS: no pude conectar con la API. Revisa tu conexión e inténtalo de nuevo.\n")
            continue
        except anthropic.APIStatusError as exc:
            print(f"JARVIS: la API devolvió un error ({exc.status_code}). Inténtalo de nuevo.\n")
            continue
        print(f"JARVIS: {reply}\n")

    print("Hasta luego.")


def run_google_login() -> None:
    from jarvis.google_auth import (
        CALENDAR_SCOPE,
        GMAIL_SEND_SCOPE,
        GoogleAuthError,
        describe_scopes,
        login,
    )

    env = read_env()
    google = load_google_settings(env)
    try:
        summary = load_summary_settings(env)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)

    # Permiso mínimo: Gmail solo si el resumen diario se envía por Gmail.
    scopes = [CALENDAR_SCOPE] + ([GMAIL_SEND_SCOPE] if summary.uses_gmail else [])
    print(f"Vas a autorizar a JARVIS a {describe_scopes(scopes)}.")
    try:
        login(google.credentials_file, google.token_file, scopes)
    except GoogleAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAutorización cancelada.", file=sys.stderr)
        sys.exit(1)
    print(f"Autorización guardada en {google.token_file}.")
    print("Con JARVIS_CALENDAR=google en tu .env, `uv run jarvis` usará tu calendario real.")


def run_prepare_voice() -> None:
    """`jarvis preparar-voz`: descarga una sola vez el modelo de Whisper y la voz de Piper."""
    try:
        env = read_env()
        voice, speech = load_voice_settings(env), load_speech_settings(env)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)
    if not voice.enabled and not speech.enabled:
        print("Las notas de voz y las respuestas con voz están desactivadas en tu .env.")
        return

    ok = True
    if voice.enabled:
        ok = _prepare_transcription(voice) and ok
    if speech.enabled:
        ok = _prepare_speech(speech) and ok
    if not ok:
        sys.exit(1)
    print("\nListo. Envíale una nota de voz a tu bot para probarlo.")


def _prepare_transcription(voice: VoiceSettings) -> bool:
    """Descarga el modelo de Whisper (para entender notas de voz). False si falló."""
    from jarvis.voice import INSTALL_HINT, VoiceDownloadError, download_model, model_downloaded, whisper_installed

    if not whisper_installed():
        print(f"Falta instalar la transcripción de voz: ejecuta {INSTALL_HINT}.", file=sys.stderr)
        return False
    target = voice.models_dir / voice.model
    if model_downloaded(target):
        print(f"El modelo de voz «{voice.model}» ya está descargado en {target}.")
        return True
    print(f"Descargando el modelo de voz «{voice.model}». Se hace una sola vez y puede tardar unos")
    print("minutos (el modelo «small» pesa unos 500 MB)…\n")
    try:
        download_model(voice.model, voice.models_dir)
    except VoiceDownloadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False
    print(f"Modelo guardado en {target}.")
    return True


def _prepare_speech(speech: SpeechSettings) -> bool:
    """Descarga la voz de Piper (para responder con voz). False si falló."""
    from jarvis.speech import INSTALL_HINT, SpeechDownloadError, download_voice, piper_installed, voice_downloaded

    if not piper_installed():
        print(f"Falta instalar la respuesta con voz: ejecuta {INSTALL_HINT}.", file=sys.stderr)
        return False
    if voice_downloaded(speech.voices_dir, speech.voice):
        print(f"La voz «{speech.voice}» ya está descargada en {speech.voices_dir}.")
        return True
    print(f"Descargando la voz «{speech.voice}» (unos 60 MB)…")
    try:
        path = download_voice(speech.voice, speech.voices_dir)
    except SpeechDownloadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False
    print(f"Voz guardada en {path}.")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS, tu asistente personal.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("google-login", help="Autoriza el acceso a Google (Calendar y Gmail).")

    summary = commands.add_parser("resumen", help="Envía el resumen del día (Telegram o Gmail).")
    summary.add_argument("--dry-run", action="store_true", help="Muestra el correo sin enviarlo.")
    summary.add_argument("--force", action="store_true", help="Lo envía aunque ya se haya enviado hoy.")
    summary.add_argument("--programado", action="store_true", help=argparse.SUPPRESS)

    commands.add_parser("programar-resumen", help="Programa el resumen de lunes a viernes.")
    commands.add_parser("quitar-resumen", help="Quita la programación del resumen.")
    telegram = commands.add_parser("telegram", help="Conecta JARVIS a tu bot de Telegram para chatear.")
    telegram.add_argument("--programado", action="store_true", help=argparse.SUPPRESS)
    commands.add_parser("telegram-vincular", help="Muestra tu ID de Telegram para TELEGRAM_OWNER_ID.")
    commands.add_parser("programar-telegram", help="Arranca JARVIS en segundo plano al iniciar sesión.")
    commands.add_parser("quitar-telegram", help="Detiene JARVIS en segundo plano y quita el arranque.")
    commands.add_parser("preparar-voz", help="Descarga lo necesario para entender y responder con voz.")
    commands.add_parser("estado", help="Muestra la configuración, las tareas programadas y los registros.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "google-login":
        run_google_login()
    elif args.command == "resumen":
        summary_cli.run_summary(dry_run=args.dry_run, force=args.force, scheduled=args.programado)
    elif args.command == "programar-resumen":
        summary_cli.run_schedule_install()
    elif args.command == "quitar-resumen":
        summary_cli.run_schedule_remove()
    elif args.command == "telegram":
        from jarvis.telegram.app import run_telegram

        run_telegram(scheduled=args.programado)
    elif args.command == "telegram-vincular":
        from jarvis.telegram.app import run_link

        run_link()
    elif args.command == "programar-telegram":
        from jarvis.telegram.app import run_schedule_install

        run_schedule_install()
    elif args.command == "quitar-telegram":
        from jarvis.telegram.app import run_schedule_remove

        run_schedule_remove()
    elif args.command == "preparar-voz":
        run_prepare_voice()
    elif args.command == "estado":
        from jarvis.status import run_status

        run_status()
    else:
        run_chat()


if __name__ == "__main__":
    main()
