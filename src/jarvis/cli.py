"""Punto de entrada por consola.

- `uv run jarvis`: chat con JARVIS.
- `uv run jarvis google-login`: autoriza el acceso a Google.
- `uv run jarvis resumen [--dry-run] [--force]`: envía el resumen del día.
- `uv run jarvis programar-resumen` / `quitar-resumen`: programa o quita el resumen diario.
- `uv run jarvis whatsapp`: servidor para chatear con JARVIS por WhatsApp.
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
    load_google_settings,
    load_settings,
    load_summary_settings,
    read_env,
)
from jarvis.confirmation import CONFIRMATION_QUESTION, parse_yes_no
from jarvis.prompts import build_system_prompt
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
    agent = Agent(
        client=client,
        registry=build_registry(calendar=calendar, confirm=ask_confirmation),
        model=settings.model,
        system_prompt=build_system_prompt(datetime.now(settings.timezone).date()),
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

    # Permiso mínimo: Gmail solo si el resumen diario está configurado.
    scopes = [CALENDAR_SCOPE] + ([GMAIL_SEND_SCOPE] if summary.enabled else [])
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS, tu asistente personal.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("google-login", help="Autoriza el acceso a Google (Calendar y Gmail).")

    summary = commands.add_parser("resumen", help="Envía por correo el resumen del día.")
    summary.add_argument("--dry-run", action="store_true", help="Muestra el correo sin enviarlo.")
    summary.add_argument("--force", action="store_true", help="Lo envía aunque ya se haya enviado hoy.")
    summary.add_argument("--programado", action="store_true", help=argparse.SUPPRESS)

    commands.add_parser("programar-resumen", help="Programa el resumen de lunes a viernes.")
    commands.add_parser("quitar-resumen", help="Quita la programación del resumen.")
    commands.add_parser("whatsapp", help="Arranca el servidor para chatear por WhatsApp.")
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
    elif args.command == "whatsapp":
        from jarvis.whatsapp.app import run_whatsapp

        run_whatsapp()
    else:
        run_chat()


if __name__ == "__main__":
    main()
