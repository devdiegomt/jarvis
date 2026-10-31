"""Piezas comunes de JARVIS para los canales de chat (Telegram y la voz del PC).

Se construyen una sola vez por proceso: así Whisper y Piper se cargan una vez aunque los usen
varios canales, y todos comparten los mismos recordatorios, pendientes y memoria.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import anthropic

from jarvis.agent import Agent
from jarvis.agenda import CalendarSource
from jarvis.config import Settings
from jarvis.long_term_memory import MemoryStore
from jarvis.memory import ConversationStore
from jarvis.reminders import ReminderStore
from jarvis.speech import Speaker, build_speaker
from jarvis.tasks import TaskStore
from jarvis.tools import Confirmer, build_registry
from jarvis.voice import Transcriber, build_transcriber


@dataclass
class Assistant:
    settings: Settings
    calendar: CalendarSource
    now: Callable[[], datetime]
    conversations: ConversationStore
    reminders: ReminderStore
    tasks: TaskStore
    memories: MemoryStore
    transcriber: Transcriber | None
    speaker: Speaker | None
    anthropic_client: anthropic.Anthropic

    def agent_factory(self, history: list, system_prompt: str, confirm: Confirmer) -> Agent:
        return Agent(
            client=self.anthropic_client,
            registry=build_registry(
                self.calendar,
                confirm=confirm,
                reminders=self.reminders,
                now=self.now,
                tasks=self.tasks,
                memories=self.memories,
                web=self.settings.web,
            ),
            model=self.settings.model,
            system_prompt=system_prompt,
            history=history,
            effort=self.settings.effort,
        )

    def start_warm_up(self) -> threading.Thread:
        """Carga Whisper y Piper en segundo plano al arrancar, para que la primera nota de voz o el
        primer "Hey JARVIS" no esperen varios segundos. Si la voz no está lista, no hace nada."""
        thread = threading.Thread(target=self._warm_up, name="jarvis-precarga-voz", daemon=True)
        thread.start()
        return thread

    def _warm_up(self) -> None:
        for component in (self.transcriber, self.speaker):
            preload = getattr(component, "preload", None)
            if preload is not None:
                preload()


def build_assistant(settings: Settings, calendar: CalendarSource) -> Assistant:
    def now() -> datetime:
        return datetime.now(settings.timezone)

    db_path = settings.summary.db_path
    return Assistant(
        settings=settings,
        calendar=calendar,
        now=now,
        conversations=ConversationStore(db_path, now=now),
        reminders=ReminderStore(db_path, now=now),
        tasks=TaskStore(db_path, now=now),
        memories=MemoryStore(db_path, now=now),
        transcriber=build_transcriber(settings.voice),
        speaker=build_speaker(settings.speech),
        anthropic_client=anthropic.Anthropic(api_key=settings.api_key),
    )
