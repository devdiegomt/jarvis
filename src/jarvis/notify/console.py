"""Canal de prueba: muestra el mensaje en la consola en lugar de enviarlo."""

from collections.abc import Callable


class ConsoleNotifier:
    name = "consola (sin enviar)"

    def __init__(self, write: Callable[[str], None] = print) -> None:
        self._write = write

    def send(self, subject: str, body: str) -> None:
        self._write(f"Asunto: {subject}\n\n{body}")
