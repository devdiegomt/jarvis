from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
import pytest

from anthropic_fakes import FakeClient, text_response, tool_response
from jarvis.agent import Agent
from jarvis.chat import (
    AI_ERROR_TEXT,
    APPROVED_MARK,
    ASK_AGAIN_TEXT,
    EXPIRED_TEXT,
    HELP_TEXT,
    NEW_CONVERSATION_TEXT,
    ONLY_TEXT_TEXT,
    REJECTED_MARK,
    TIMEOUT_MARK,
    WELCOME_TEXT,
    HEARD_TEMPLATE,
    NO_MEMORIES_TEXT,
    SPEECH_DISABLED_TEXT,
    VOICE_DISABLED_TEXT,
    VOICE_DOWNLOAD_ERROR_TEXT,
    VOICE_EMPTY_TEXT,
    VOICE_TOO_LONG_TEXT,
    ButtonAnswer,
    ChannelError,
    ChatService,
    IncomingMessage,
    VoiceNote,
    split_text,
)
from jarvis.long_term_memory import MemoryStore
from jarvis.memory import ConversationStore
from jarvis.tools import Confirmer, Tool, ToolRegistry
from jarvis.speech import SpeechError, SpeechUnavailableError
from jarvis.voice import TranscriptionError

OWNER = "123456789"
NOW = datetime(2026, 10, 29, 15, 30, tzinfo=UTC)
ACTION_SCHEMA = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}


class FakeChannel:
    name = "prueba"

    def __init__(self, fail_typing: bool = False) -> None:
        self.sent: list[str] = []
        self.typing = 0
        self.questions: list[tuple[str, list[tuple[str, str]]]] = []
        self.closed: list[tuple[int, str]] = []
        self.acks: list[tuple[str, str]] = []
        self.fail_typing = fail_typing
        self.downloads: list[VoiceNote] = []
        self.fail_download = False
        self.voices: list[bytes] = []
        self.fail_voice = False
        self.on_ask: Callable[[], None] | None = None  # simula lo que hace el usuario al ver la pregunta

    def send_text(self, to: str, text: str) -> None:
        self.sent.append(text)

    def show_typing(self, to: str) -> None:
        if self.fail_typing:
            raise ChannelError("sin red")
        self.typing += 1

    def send_with_buttons(self, to: str, prompt: str, buttons: list[tuple[str, str]]) -> int:
        self.questions.append((prompt, buttons))
        if self.on_ask:
            self.on_ask()
        return len(self.questions)

    def replace_message(self, to: str, handle: int, text: str) -> None:
        self.closed.append((handle, text))

    def acknowledge(self, answer: ButtonAnswer, text: str = "") -> None:
        self.acks.append((answer.id, text))

    def download_voice(self, note: VoiceNote) -> bytes:
        if self.fail_download:
            raise ChannelError("sin red")
        self.downloads.append(note)
        return f"audio:{note.ref}".encode()

    def send_voice(self, to: str, audio: bytes) -> None:
        if self.fail_voice:
            raise ChannelError("sin red")
        self.voices.append(audio)

    def button(self, value: str, question: int = -1) -> str:
        """Dato del botón Sí ("si") o No ("no") de una pregunta enviada."""
        confirmation_id = self.questions[question][1][0][1].split(":")[0]
        return f"{confirmation_id}:{value}"


class Setup:
    def __init__(self, tmp_path: Path, responses: list[Any], **kwargs: Any) -> None:
        self.channel = FakeChannel(kwargs.pop("fail_typing", False))
        self.anthropic = FakeClient(responses)
        self.store = ConversationStore(tmp_path / "jarvis.db", now=lambda: NOW)
        self.actions: list[str] = []
        self.chat = ChatService(
            channel=self.channel,
            store=self.store,
            agent_factory=self._agent_factory,
            system_prompt=lambda: "Eres JARVIS en el chat.",
            now=lambda: NOW,
            **kwargs,
        )
        self._counter = 0

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

    def message(self, text: str | None) -> None:
        self._counter += 1
        self.chat.submit(IncomingMessage(id=f"m{self._counter}", sender=OWNER, text=text))

    def voice(self, ref: str, duration: int = 4) -> None:
        self._counter += 1
        self.chat.submit(IncomingMessage(id=f"m{self._counter}", sender=OWNER, text=None, voice=VoiceNote(ref, duration)))

    def click(self, data: str) -> None:
        self._counter += 1
        self.chat.submit(ButtonAnswer(id=f"c{self._counter}", sender=OWNER, data=data))

    def process(self) -> None:
        assert self.chat.process_next(timeout=0)


def confirmation_flow(tmp_path: Path, **kwargs: Any) -> Setup:
    """El modelo pide `accion` y luego responde "Listo."."""
    return Setup(tmp_path, [tool_response(("t1", "accion", {"texto": "avisar a Ana"})), text_response("Listo.")], **kwargs)


# --- Mensajes ---------------------------------------------------------------


def test_text_message_gets_agent_reply(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Tienes 2 reuniones.")])

    setup.message("¿Qué tengo hoy?")
    setup.process()

    assert setup.channel.sent == ["Tienes 2 reuniones."]
    assert setup.channel.typing == 1
    call = setup.anthropic.messages.calls[0]
    assert call["system"] == "Eres JARVIS en el chat."
    assert call["messages"][0]["content"][0]["text"] == "[2026-10-29 15:30] ¿Qué tengo hoy?"


def test_history_persists_between_messages(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Hola."), text_response("Sigues siendo tú.")])

    setup.message("Hola")
    setup.process()
    setup.message("¿Te acuerdas?")
    setup.process()

    assert [m["role"] for m in setup.anthropic.messages.calls[1]["messages"]] == ["user", "assistant", "user"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("/start", WELCOME_TEXT), ("/ayuda", HELP_TEXT), ("/AYUDA@JarvisBot", HELP_TEXT), (None, ONLY_TEXT_TEXT)],
)
def test_commands_and_non_text(tmp_path: Path, text: str | None, expected: str) -> None:
    setup = Setup(tmp_path, [])

    setup.message(text)
    setup.process()

    assert setup.channel.sent == [expected]
    assert setup.anthropic.messages.calls == []


def test_new_command_starts_fresh_conversation(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Hola."), text_response("Hola de nuevo.")])

    setup.message("Hola")
    setup.process()
    setup.message("/nuevo")
    setup.process()
    setup.message("Hola otra vez")
    setup.process()

    assert NEW_CONVERSATION_TEXT in setup.channel.sent
    assert len(setup.anthropic.messages.calls[1]["messages"]) == 1


def test_api_error_replies_and_keeps_history_usable(tmp_path: Path) -> None:
    error = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    setup = Setup(tmp_path, [error, text_response("Ahora sí.")])

    setup.message("Hola")
    setup.process()
    setup.message("¿Estás?")
    setup.process()

    assert setup.channel.sent == [AI_ERROR_TEXT, "Ahora sí."]
    roles = [m["role"] for m in setup.anthropic.messages.calls[1]["messages"]]
    assert roles == ["user"]  # el mensaje fallido y el nuevo se unen en un solo turno


def test_typing_failure_does_not_block_reply(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [text_response("Hola.")], fail_typing=True)

    setup.message("Hola")
    setup.process()

    assert setup.channel.sent == ["Hola."]


def test_old_button_outside_a_confirmation_is_expired(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [])

    setup.click("viejo:si")
    setup.process()

    assert setup.channel.acks == [("c1", EXPIRED_TEXT)]


def test_process_next_returns_false_when_queue_is_empty(tmp_path: Path) -> None:
    assert not Setup(tmp_path, []).chat.process_next(timeout=0)


# --- Confirmaciones ---------------------------------------------------------
# El chat procesa en un solo hilo: la respuesta se encola antes y se lee durante la confirmación.


def setup_with_click(tmp_path: Path, value: str) -> Setup:
    """Al recibir la pregunta, el usuario pulsa el botón Sí ("si") o No ("no")."""
    setup = confirmation_flow(tmp_path)
    setup.channel.on_ask = lambda: setup.click(setup.channel.button(value))
    return setup


def test_confirmation_with_yes_button(tmp_path: Path) -> None:
    setup = setup_with_click(tmp_path, "si")

    setup.message("Avisa a Ana")
    setup.process()

    prompt, buttons = setup.channel.questions[0]
    assert prompt == "Voy a hacer: avisar a Ana"
    assert [label for label, _ in buttons] == ["✅ Sí", "❌ No"]
    assert setup.actions == ["avisar a Ana"]
    assert setup.channel.closed == [(1, f"Voy a hacer: avisar a Ana\n\n{APPROVED_MARK}")]
    assert setup.channel.acks[0][1] == ""
    assert setup.channel.sent == ["Listo."]


def test_confirmation_with_no_button(tmp_path: Path) -> None:
    setup = setup_with_click(tmp_path, "no")

    setup.message("Avisa a Ana")
    setup.process()

    assert setup.actions == []
    assert setup.channel.closed[0][1].endswith(REJECTED_MARK)
    result = setup.anthropic.messages.calls[1]["messages"][-1]["content"][0]
    assert "canceló" in result["content"]


def test_confirmation_with_typed_answer(tmp_path: Path) -> None:
    setup = confirmation_flow(tmp_path)

    setup.message("Avisa a Ana")
    setup.message("quizás")
    setup.message("sí")
    setup.process()

    assert ASK_AGAIN_TEXT in setup.channel.sent
    assert setup.actions == ["avisar a Ana"]


def test_button_from_another_question_is_expired_and_ignored(tmp_path: Path) -> None:
    setup = confirmation_flow(tmp_path)

    setup.message("Avisa a Ana")
    setup.click("otra-pregunta:si")
    setup.message("n")
    setup.process()

    assert setup.channel.acks == [("c2", EXPIRED_TEXT)]
    assert setup.actions == []


def test_confirmation_timeout_cancels(tmp_path: Path) -> None:
    setup = confirmation_flow(tmp_path, confirmation_timeout=0)

    setup.message("Avisa a Ana")
    setup.process()

    assert setup.actions == []
    assert setup.channel.closed[0][1].endswith(TIMEOUT_MARK)


# --- Utilidades -------------------------------------------------------------


def test_split_text_prefers_paragraph_boundaries() -> None:
    text = "uno " * 10 + "\n\n" + "dos " * 10

    chunks = split_text(text, limit=50)

    assert chunks[0] == ("uno " * 10).strip()
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_text_never_returns_empty_message() -> None:
    assert split_text("   ", limit=100) == ["(sin respuesta)"]


def test_other_buttons_go_to_the_button_handler(tmp_path: Path) -> None:
    handled: list[str] = []
    setup = Setup(tmp_path, [], button_handler=lambda answer: handled.append(answer.data) or True)

    setup.click("rem:1:hecho")
    setup.process()

    assert handled == ["rem:1:hecho"]
    assert setup.channel.acks == []


def test_reminder_button_during_a_confirmation_is_still_handled(tmp_path: Path) -> None:
    handled: list[str] = []
    setup = confirmation_flow(tmp_path, button_handler=lambda answer: handled.append(answer.data) or True)

    setup.message("Avisa a Ana")
    setup.click("rem:1:posponer")
    setup.message("s")
    setup.process()

    assert handled == ["rem:1:posponer"]
    assert setup.actions == ["avisar a Ana"]


# --- Notas de voz -----------------------------------------------------------


class FakeTranscriber:
    name = "prueba"

    def __init__(self, texts: dict[str, str] | None = None, error: Exception | None = None) -> None:
        self.texts = texts or {}
        self.error = error
        self.audios: list[bytes] = []

    def transcribe(self, audio: bytes) -> str:
        self.audios.append(audio)
        if self.error:
            raise self.error
        return self.texts.get(audio.decode().removeprefix("audio:"), "")


def test_voice_note_is_transcribed_echoed_and_answered(tmp_path: Path) -> None:
    transcriber = FakeTranscriber({"v1": "¿Qué tengo hoy?"})
    setup = Setup(tmp_path, [text_response("Tienes 2 reuniones.")], transcriber=transcriber)

    setup.voice("v1")
    setup.process()

    assert transcriber.audios == [b"audio:v1"]
    assert setup.channel.sent == [HEARD_TEMPLATE.format("¿Qué tengo hoy?"), "Tienes 2 reuniones."]
    text = setup.anthropic.messages.calls[0]["messages"][0]["content"][0]["text"]
    assert text == "[2026-10-29 15:30] (nota de voz) ¿Qué tengo hoy?"


@pytest.mark.parametrize(
    ("kwargs", "duration", "expected"),
    [
        ({}, 4, VOICE_DISABLED_TEXT),
        ({"transcriber": FakeTranscriber()}, 4, VOICE_EMPTY_TEXT),
        ({"transcriber": FakeTranscriber()}, 5 * 60 + 1, VOICE_TOO_LONG_TEXT),
        ({"transcriber": FakeTranscriber(error=TranscriptionError("Falta el modelo."))}, 4, "Falta el modelo."),
    ],
)
def test_voice_notes_that_cannot_be_answered(tmp_path: Path, kwargs: dict, duration: int, expected: str) -> None:
    setup = Setup(tmp_path, [], **kwargs)

    setup.voice("v1", duration=duration)
    setup.process()

    assert setup.channel.sent == [expected]
    assert setup.anthropic.messages.calls == []


def test_long_voice_note_is_not_downloaded(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [], transcriber=FakeTranscriber())

    setup.voice("v1", duration=10 * 60)
    setup.process()

    assert setup.channel.downloads == []


def test_voice_download_failure_is_reported(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [], transcriber=FakeTranscriber({"v1": "hola"}))
    setup.channel.fail_download = True

    setup.voice("v1")
    setup.process()

    assert setup.channel.sent == [VOICE_DOWNLOAD_ERROR_TEXT]


def test_confirmation_answered_with_a_voice_note(tmp_path: Path) -> None:
    setup = confirmation_flow(tmp_path, transcriber=FakeTranscriber({"v1": "¡Sí!"}))

    setup.message("Avisa a Ana")
    setup.voice("v1")
    setup.process()

    assert setup.actions == ["avisar a Ana"]
    assert HEARD_TEMPLATE.format("¡Sí!") in setup.channel.sent


# --- Respuestas con voz -----------------------------------------------------


class FakeSpeaker:
    name = "prueba"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.texts: list[str] = []

    def speak(self, text: str) -> bytes:
        self.texts.append(text)
        if self.error:
            raise self.error
        return f"voz:{text}".encode()


def voice_setup(tmp_path: Path, replies: int = 1, **kwargs: Any) -> Setup:
    kwargs.setdefault("speaker", FakeSpeaker())
    responses = [text_response(f"Respuesta {i}.") for i in range(replies)]
    return Setup(tmp_path, responses, transcriber=FakeTranscriber({"v1": "Hola"}), **kwargs)


def test_voice_note_gets_a_voice_reply_and_the_text(tmp_path: Path) -> None:
    setup = voice_setup(tmp_path)

    setup.voice("v1")
    setup.process()

    assert setup.channel.voices == [b"voz:Respuesta 0."]
    assert setup.channel.sent[-1] == "Respuesta 0."


def test_text_message_gets_only_text_by_default(tmp_path: Path) -> None:
    setup = voice_setup(tmp_path)

    setup.message("Hola")
    setup.process()

    assert setup.channel.voices == []
    assert setup.channel.sent == ["Respuesta 0."]


def test_voice_command_offers_the_modes(tmp_path: Path) -> None:
    setup = voice_setup(tmp_path)

    setup.message("/voz")
    setup.process()

    prompt, buttons = setup.channel.questions[0]
    assert "Ahora: solo cuando me envías una nota de voz" in prompt
    assert [data for _, data in buttons] == ["voz:espejo", "voz:siempre", "voz:nunca"]


@pytest.mark.parametrize(("mode", "voice_for_text", "voice_for_voice"), [("siempre", True, True), ("nunca", False, False)])
def test_voice_mode_is_saved_and_applied(tmp_path: Path, mode: str, voice_for_text: bool, voice_for_voice: bool) -> None:
    setup = voice_setup(tmp_path, replies=2)

    setup.click(f"voz:{mode}")
    setup.process()
    setup.message("Hola")
    setup.process()
    spoken_after_text = len(setup.channel.voices)
    setup.voice("v1")
    setup.process()

    assert setup.store.get_preference("prueba", OWNER, "respuesta_voz") == mode
    assert setup.channel.closed[0][1].startswith("Listo: te responderé")
    assert (spoken_after_text == 1) is voice_for_text
    assert (len(setup.channel.voices) > spoken_after_text) is voice_for_voice


def test_unknown_voice_mode_button_is_expired(tmp_path: Path) -> None:
    setup = voice_setup(tmp_path)

    setup.click("voz:gritando")
    setup.process()

    assert setup.channel.acks == [("c1", EXPIRED_TEXT)]


def test_voice_command_when_speech_is_disabled(tmp_path: Path) -> None:
    setup = voice_setup(tmp_path, speaker=None)

    setup.message("/voz")
    setup.process()

    assert setup.channel.sent == [SPEECH_DISABLED_TEXT]


@pytest.mark.parametrize("problem", ["speech", "channel"])
def test_voice_failures_still_send_the_text(tmp_path: Path, problem: str) -> None:
    setup = voice_setup(tmp_path, speaker=FakeSpeaker(SpeechError("falló")) if problem == "speech" else FakeSpeaker())
    setup.channel.fail_voice = problem == "channel"

    setup.voice("v1")
    setup.process()

    assert setup.channel.sent[-1] == "Respuesta 0."
    assert "falló" not in setup.channel.sent


def test_missing_voice_is_explained_only_once(tmp_path: Path) -> None:
    setup = voice_setup(tmp_path, replies=2, speaker=FakeSpeaker(SpeechUnavailableError("Falta la voz.")))

    setup.voice("v1")
    setup.process()
    setup.voice("v1")
    setup.process()

    assert setup.channel.sent.count("Falta la voz.") == 1
    assert setup.channel.sent[-1] == "Respuesta 1."


# --- Memoria a largo plazo --------------------------------------------------


def test_memory_command_lists_what_jarvis_remembers_without_the_ai(tmp_path: Path) -> None:
    memories = MemoryStore(tmp_path / "jarvis.db", now=lambda: NOW)
    memories.add("Su socia se llama Laura.")
    setup = Setup(tmp_path, [], memories=memories)

    setup.message("/memoria")
    setup.process()

    assert setup.channel.sent == [
        "Esto es lo que recuerdo de ti:\n\n1. Su socia se llama Laura.\n\n"
        "Para que olvide algo, dime por ejemplo «olvida el 1»."
    ]
    assert setup.anthropic.messages.calls == []


def test_memory_command_when_empty(tmp_path: Path) -> None:
    setup = Setup(tmp_path, [], memories=MemoryStore(tmp_path / "jarvis.db", now=lambda: NOW))

    setup.message("/memoria")
    setup.process()

    assert setup.channel.sent == [NO_MEMORIES_TEXT]


def test_extra_purges_run_daily(tmp_path: Path) -> None:
    calls: list[str] = []
    setup = Setup(tmp_path, [text_response("Hola."), text_response("Otra vez.")], purges=[lambda: calls.append("x") or 0])

    setup.message("Hola")
    setup.process()
    setup.message("Hola de nuevo")
    setup.process()

    assert calls == ["x"]  # una vez al día, no en cada mensaje
