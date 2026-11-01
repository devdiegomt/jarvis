"""Canal de chat de la app (PWA y Siri) sobre la misma lógica que Telegram (`ChatService`).

El servicio de chat procesa los eventos en su hilo y "envía" lo que diría por Telegram a una bandeja
de salida. Cada pedido HTTP entrega su evento y espera esa salida hasta que el chat termina el turno
o hace una pregunta con botones (una confirmación), que la app contesta con otro pedido.
"""

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from jarvis.chat import ButtonAnswer, ChannelError, ChatEvent, IncomingMessage, VoiceNote

OWNER = "app"  # la app tiene un solo usuario: el dueño de JARVIS
REPLY_TIMEOUT_SECONDS = 120.0
BUSY_TIMEOUT_SECONDS = 5.0


@dataclass
class Reply:
    """Lo que JARVIS respondió a un pedido de la app."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    question: dict[str, Any] | None = None  # confirmación pendiente: {"id", "texto", "botones"}
    finished: bool = False  # False si se agotó el tiempo de espera (la respuesta llegará luego)

    def to_dict(self) -> dict[str, Any]:
        texts = [m["texto"] for m in self.messages if m.get("tipo") == "texto"]
        if self.question is not None:
            texts.append(self.question["texto"])
        return {
            "mensajes": self.messages,
            "pregunta": self.question,
            "terminado": self.finished,
            # Todo en un solo texto, para que un Atajo de Siri lo lea en voz alta.
            "texto": "\n\n".join(texts),
        }


_FINISHED = object()


class ApiChannel:
    """`ChatChannel` de la app: lo que el chat envía queda en una bandeja de salida."""

    name = "app"

    def __init__(self) -> None:
        self._outbox: queue.Queue[Any] = queue.Queue()

    def send_text(self, to: str, text: str) -> None:
        self._outbox.put({"tipo": "texto", "texto": text})

    def show_typing(self, to: str) -> None:
        pass  # la app muestra su propio "escribiendo…" mientras espera

    def send_with_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> str:
        handle = uuid.uuid4().hex[:12]
        question = {"id": handle, "texto": text, "botones": [{"texto": t, "dato": d} for t, d in buttons]}
        self._outbox.put({"tipo": "pregunta", **question})
        return handle

    def replace_message(self, to: str, handle: Any, text: str) -> None:
        self._outbox.put({"tipo": "actualiza", "id": handle, "texto": text})

    def acknowledge(self, answer: ButtonAnswer, text: str = "") -> None:
        if text:
            self._outbox.put({"tipo": "texto", "texto": text})

    def download_voice(self, note: VoiceNote) -> bytes:
        raise ChannelError("La app no envía notas de voz: usa el dictado del teclado.")

    def send_voice(self, to: str, audio: bytes) -> None:
        pass  # la app recibe texto; Siri lo lee en voz alta

    def event_finished(self, event: ChatEvent) -> None:
        """Lo llama el chat al terminar cada evento: cierra la espera del pedido HTTP."""
        self._outbox.put(_FINISHED)

    def collect(self, timeout: float) -> Reply:
        """Junta la salida hasta que el turno termina o queda una pregunta pendiente."""
        reply = Reply()
        deadline = time.monotonic() + timeout
        while True:
            try:
                item = self._outbox.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                return reply
            if item is _FINISHED:
                reply.finished = True
                return reply
            if item["tipo"] == "pregunta":
                reply.question = {k: v for k, v in item.items() if k != "tipo"}
                return reply
            reply.messages.append(item)

    def drain(self) -> list[dict[str, Any]]:
        """Lo que quedó de un pedido anterior que se cansó de esperar."""
        pending = []
        while True:
            try:
                item = self._outbox.get_nowait()
            except queue.Empty:
                return pending
            if item is not _FINISHED:
                pending.append(item)


class ChatBridge:
    """Entrega los pedidos de la app al chat de a uno y devuelve lo que respondió."""

    def __init__(self, channel: ApiChannel, submit: Any, reply_timeout: float = REPLY_TIMEOUT_SECONDS) -> None:
        self._channel = channel
        self._submit = submit
        self._reply_timeout = reply_timeout
        self._lock = threading.Lock()
        self._open_question: dict[str, Any] | None = None  # confirmación que sigue esperando respuesta

    def send_text(self, text: str) -> Reply:
        return self._exchange(IncomingMessage(uuid.uuid4().hex, OWNER, text))

    def press_button(self, data: str) -> Reply:
        return self._exchange(ButtonAnswer(uuid.uuid4().hex, OWNER, data))

    def _exchange(self, event: ChatEvent) -> Reply:
        if not self._lock.acquire(timeout=BUSY_TIMEOUT_SECONDS):
            raise BusyError("JARVIS todavía está respondiendo el mensaje anterior.")
        try:
            earlier = self._channel.drain()
            self._submit(event)
            reply = self._channel.collect(self._reply_timeout)
            reply.messages[:0] = earlier
            self._track_question(reply)
            return reply
        finally:
            self._lock.release()


    def _track_question(self, reply: Reply) -> None:
        """Si la pregunta sigue abierta (por ejemplo, se respondió algo que no es «sí» ni «no»),
        se vuelve a entregar con la respuesta para que la app siga mostrando sus botones."""
        open_question = self._open_question
        if open_question is not None and any(
            m.get("tipo") == "actualiza" and m.get("id") == open_question["id"] for m in reply.messages
        ):
            open_question = None  # ya se respondió o venció
        if reply.question is not None:
            open_question = reply.question
        elif open_question is not None:
            reply.question = open_question
        self._open_question = open_question


class BusyError(Exception):
    """Otro pedido de la app sigue en curso."""
