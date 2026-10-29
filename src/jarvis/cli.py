"""Punto de entrada por consola.

- `uv run jarvis`: chat con JARVIS.
- `uv run jarvis google-login`: autoriza la lectura de Google Calendar.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime

import anthropic

from jarvis.agent import Agent
from jarvis.agenda import CalendarError, CalendarSource, build_calendar
from jarvis.config import ConfigError, load_google_settings, load_settings, read_env
from jarvis.prompts import build_system_prompt
from jarvis.tools import build_registry

EXIT_COMMAND = "salir"


def ask_confirmation(prompt: str, read: Callable[[str], str] = input) -> bool:
    """Muestra la acción pendiente y pregunta s/n hasta obtener una respuesta válida."""
    print(f"\n{prompt}")
    while True:
        try:
            answer = read("¿Confirmas? (s/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer in ("s", "si", "sí"):
            return True
        if answer in ("n", "no"):
            return False
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
    from jarvis.agenda.google_auth import login

    google = load_google_settings(read_env())
    print("Vas a autorizar a JARVIS a leer tu Google Calendar (solo lectura).")
    try:
        login(google.credentials_file, google.token_file)
    except CalendarError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAutorización cancelada.", file=sys.stderr)
        sys.exit(1)
    print(f"Autorización guardada en {google.token_file}.")
    print("Pon JARVIS_CALENDAR=google en tu .env y ejecuta `uv run jarvis`.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS, tu asistente personal.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("google-login", help="Autoriza la lectura de Google Calendar.")
    args = parser.parse_args(argv)

    if args.command == "google-login":
        run_google_login()
    else:
        run_chat()


if __name__ == "__main__":
    main()
