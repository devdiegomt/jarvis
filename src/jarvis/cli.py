"""Punto de entrada por consola: `uv run jarvis`."""

import sys
from collections.abc import Callable
from datetime import date

import anthropic

from jarvis.agent import Agent
from jarvis.config import ConfigError, load_settings
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


def build_agent() -> Agent:
    settings = load_settings()
    client = anthropic.Anthropic(api_key=settings.api_key)
    return Agent(
        client=client,
        registry=build_registry(confirm=ask_confirmation),
        model=settings.model,
        system_prompt=build_system_prompt(date.today()),
    )


def main() -> None:
    try:
        agent = build_agent()
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"JARVIS listo. Escribe '{EXIT_COMMAND}' para terminar.\n")
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


if __name__ == "__main__":
    main()
