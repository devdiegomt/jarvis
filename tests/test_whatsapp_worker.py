from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
import pytest

from anthropic_fakes import FakeClient, text_response, tool_response
from jarvis.agent import Agent
from jarvis.memory import ConversationStore
from jarvis.tools import Confirmer, Tool, ToolRegistry
from jarvis.whatsapp.client import WhatsAppError
from jarvis.whatsapp.webhook import IncomingMessage
from jarvis.whatsapp.worker import (
    AI_ERROR_TEXT,
    CONFIRMATION_TIMEOUT_TEXT,
    HELP_TEXT,
    NEW_CONVERSATION_TEXT,
    ONLY_TEXT_TEXT,
    WhatsAppWorker,
)

OWNER = "573001234567"
NOW = datetime(2026, 10, 29, 15, 30, tzinfo=UTC)
ACTION_SCHEMA = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}


class FakeWhatsApp:
    def __init__(self, fail_mark_read: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.read: list[str] = []
        self.fail_mark_read = fail_mark_read

    def send_text(self, to: str, text: str) -> None:
        self.sent.append((to, text))

    def mark_read(self, message_id: str, show_typing: bool = True) -> None:
        if self.fail_mark_read:
            raise WhatsAppError("sin red")
        self.read.append(message_id)

    @property
    def texts(self) -> list[str]:
        return [text for _, text in self.sent]


class Setup:
    def __init__(self, tmp_path: Path, responses: list[Any], **worker_kwargs: Any) -> None:
        self.whatsapp = FakeWhatsApp(worker_kwargs.pop("fail_mark_read", False))
        self.anthropic = FakeClient(responses)
        self.store = ConversationStore(tmp_path / "jarvis.db", now=lambda: NOW)
        self.actions: list[str] = []
        self.worker = WhatsAppWorker(
            client=self.whatsapp,  # type: ignore[arg-type]
            store=self.store,
            agent_factory=self._agent_factory,
            system_prompt=lambda: "Eres JARVIS por WhatsApp.",
            now=lambda: NOW,
            **worker_kwargs,
        )

    def _agent_factory(self, history: list, system_prompt: str, confirm: Confirmer) -> Agent:
        registry = ToolRegistry(confirm=confirm)
        registry.register(
            Tool(
                name="accion",
                description="Acción con efectos externos.",
                input_schema=ACTION_SCHEMA,
                func=lambda texto: self.actions.append(texto) or "hecho",
                confirmation_prompt=lambda tool_input: f"Voy a hacer: {tool_input['texto']}",
            )
        )
        return Agent(
            client=self.anthropic,  # type: ignore[arg-type]
            registry=registry,
            model="m",
            system_prompt=system_prompt,
            history=history,
        )

    def receive(self, *texts: str | None) -> None:
        for index, text in enumerate(texts):
            self.worker.submit(IncomingMessage(id=f"wamid.{len(self.whatsapp.read)}.{index}", sender=OWNER, text=text))

    def process(self) -> None:
        assert self.worker.process_next(timeout=0)


def test_text_message_gets_agent_reply(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Tienes 2 reuniones.")])

    setup.receive("¿Qué tengo hoy?")
    setup.process()

    assert setup.whatsapp.sent == [(OWNER, "Tienes 2 reuniones.")]
    assert setup.whatsapp.read == ["wamid.0.0"]
    call = setup.anthropic.messages.calls[0]
    assert call["system"] == "Eres JARVIS por WhatsApp."
    assert call["messages"][0]["content"][0]["text"] == "[2026-10-29 15:30] ¿Qué tengo hoy?"


def test_history_persists_between_messages(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Hola."), text_response("Sigues siendo tú.")])

    setup.receive("Hola")
    setup.process()
    setup.receive("¿Te acuerdas?")
    setup.process()

    second_call = setup.anthropic.messages.calls[1]["messages"]
    assert [m["role"] for m in second_call] == ["user", "assistant", "user"]


def test_confirmation_approved_by_next_message(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [tool_response(("t1", "accion", {"texto": "avisar a Ana"})), text_response("Listo.")])

    setup.receive("Avisa a Ana", "sí")
    setup.process()

    assert setup.actions == ["avisar a Ana"]
    assert setup.whatsapp.texts[0] == "Voy a hacer: avisar a Ana\n\n¿Confirmas? (s/n)"
    assert setup.whatsapp.texts[-1] == "Listo."


def test_confirmation_rejected(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [tool_response(("t1", "accion", {"texto": "x"})), text_response("Cancelado.")])

    setup.receive("Hazlo", "no")
    setup.process()

    assert setup.actions == []
    result = setup.anthropic.messages.calls[1]["messages"][-1]["content"][0]
    assert "canceló" in result["content"]


def test_invalid_answer_asks_again(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [tool_response(("t1", "accion", {"texto": "x"})), text_response("Listo.")])

    setup.receive("Hazlo", "quizás", "s")
    setup.process()

    assert "Responde 's' o 'n'." in setup.whatsapp.texts
    assert setup.actions == ["x"]


def test_confirmation_timeout_cancels(tmp_path: Path) -> None:
    setup = Setup(
        tmp_path, [tool_response(("t1", "accion", {"texto": "x"})), text_response("Ok.")], confirmation_timeout=0
    )

    setup.receive("Hazlo")
    setup.process()

    assert setup.actions == []
    assert CONFIRMATION_TIMEOUT_TEXT in setup.whatsapp.texts


@pytest.mark.parametrize(("text", "expected"), [("/ayuda", HELP_TEXT), ("/AYUDA ", HELP_TEXT), (None, ONLY_TEXT_TEXT)])
def test_commands_and_non_text(tmp_path: Path, text: str | None, expected: str) -> None:
    setup = Setup(tmp_path, [])

    setup.receive(text)
    setup.process()

    assert setup.whatsapp.texts == [expected]
    assert setup.anthropic.messages.calls == []


def test_new_command_starts_fresh_conversation(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Hola."), text_response("Hola de nuevo.")])

    setup.receive("Hola")
    setup.process()
    setup.receive("/nuevo")
    setup.process()
    setup.receive("Hola otra vez")
    setup.process()

    assert NEW_CONVERSATION_TEXT in setup.whatsapp.texts
    assert len(setup.anthropic.messages.calls[1]["messages"]) == 1


def test_api_error_replies_and_keeps_history_usable(tmp_path: Path) -> None:
    error = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    setup = Setup(tmp_path, [error, text_response("Ahora sí.")])

    setup.receive("Hola")
    setup.process()
    setup.receive("¿Estás?")
    setup.process()

    assert setup.whatsapp.texts == [AI_ERROR_TEXT, "Ahora sí."]
    roles = [m["role"] for m in setup.anthropic.messages.calls[1]["messages"]]
    assert roles == ["user"]  # el mensaje fallido y el nuevo se unen en un solo turno


def test_mark_read_failure_does_not_block_reply(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Hola.")], fail_mark_read=True)

    setup.receive("Hola")
    setup.process()

    assert setup.whatsapp.texts == ["Hola."]


def test_process_next_returns_false_when_queue_is_empty(tmp_path: Path) -> None:
    assert not Setup(tmp_path, []).worker.process_next(timeout=0)
