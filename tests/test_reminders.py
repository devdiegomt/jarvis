import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from jarvis.agenda import SampleCalendar
from jarvis.chat import ButtonAnswer, ChannelError
from jarvis.reminder_delivery import ReminderDelivery
from jarvis.reminders import ReminderStore
from jarvis.tools import build_registry

TZ = ZoneInfo("America/Bogota")
OWNER = "987654321"


class Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 30, 8, 0, tzinfo=TZ)  # jueves, 8:00

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


class FakeChannel:
    name = "prueba"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, list[tuple[str, str]]]] = []
        self.replaced: list[tuple[Any, str]] = []
        self.acks: list[tuple[str, str]] = []
        self.fail = fail

    def send_text(self, to: str, text: str) -> None:
        raise AssertionError("los recordatorios se envían con botones")

    def show_typing(self, to: str) -> None:
        pass

    def send_with_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> int:
        if self.fail:
            raise ChannelError("sin red")
        assert to == OWNER
        self.sent.append((text, buttons))
        return len(self.sent)

    def replace_message(self, to: str, handle: Any, text: str) -> None:
        self.replaced.append((handle, text))

    def acknowledge(self, answer: ButtonAnswer, text: str = "") -> None:
        self.acks.append((answer.id, text))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> ReminderStore:
    return ReminderStore(tmp_path / "jarvis.db", now=clock)


def at(hour: int, minute: int = 0, day: int = 30) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# --- Almacenamiento ---------------------------------------------------------


def test_create_and_list_pending_in_order(store: ReminderStore) -> None:
    later = store.create("pagar la factura", at(18))
    sooner = store.create("llamar a Laura", at(9))

    assert [r.id for r in store.pending()] == [sooner.id, later.id]
    assert store.get(sooner.id).due_at == at(9)  # type: ignore[union-attr]


def test_due_returns_only_reminders_whose_time_came(store: ReminderStore, clock: Clock) -> None:
    store.create("a", at(9))
    store.create("b", at(10))

    clock.advance(hours=1, minutes=30)  # 9:30

    assert [r.text for r in store.due()] == ["a"]


def test_cancel_only_pending(store: ReminderStore, clock: Clock) -> None:
    reminder = store.create("a", at(9))

    assert store.cancel(reminder.id)
    assert not store.cancel(reminder.id)
    assert store.pending() == []


def test_snooze_and_done_only_after_sent(store: ReminderStore, clock: Clock) -> None:
    reminder = store.create("a", at(9))
    assert store.snooze(reminder.id) is None
    assert not store.mark_done(reminder.id)

    clock.advance(hours=1)
    store.mark_sent(reminder.id)
    snoozed = store.snooze(reminder.id)

    assert snoozed is not None and snoozed.status == "pending"
    assert snoozed.due_at == at(9, 10)


def test_purge_removes_only_old_closed_reminders(store: ReminderStore, clock: Clock) -> None:
    closed = store.create("viejo", at(9))
    store.cancel(closed.id)
    pending = store.create("futuro", at(9, day=31))

    clock.advance(days=31)

    assert store.purge_old() == 1
    assert store.get(closed.id) is None
    assert store.get(pending.id) is not None


# --- Tools ------------------------------------------------------------------


def run(store: ReminderStore, clock: Clock, tool: str, **tool_input: Any):  # type: ignore[no-untyped-def]
    registry = build_registry(SampleCalendar(TZ), reminders=store, now=clock)
    return registry.execute(tool, tool_input)


def test_reminder_tools_are_registered_and_need_no_confirmation(store: ReminderStore, clock: Clock) -> None:
    registry = build_registry(SampleCalendar(TZ), reminders=store, now=clock)

    names = registry.names()
    assert {"crear_recordatorio", "listar_recordatorios", "cancelar_recordatorio"} <= set(names)
    assert not any(registry.get(name).requires_confirmation for name in names if "recordatorio" in name)  # type: ignore[union-attr]


def test_reminder_tools_are_optional() -> None:
    assert "crear_recordatorio" not in build_registry(SampleCalendar(TZ)).names()


def test_create_with_date_and_time(store: ReminderStore, clock: Clock) -> None:
    result = run(store, clock, "crear_recordatorio", texto="Llamar a Laura", fecha_hora="2026-10-31 09:00")

    assert not result.is_error
    assert json.loads(result.content)["creado"]["fecha_hora"] == "2026-10-31 09:00"
    assert store.pending()[0].due_at == at(9, day=31)


def test_create_in_minutes(store: ReminderStore, clock: Clock) -> None:
    result = run(store, clock, "crear_recordatorio", texto="Tomar agua", en_minutos=120)

    assert json.loads(result.content)["creado"]["fecha_hora"] == "2026-10-30 10:00"


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"texto": "a"}, "solo uno"),
        ({"texto": "a", "fecha_hora": "2026-10-31 09:00", "en_minutos": 5}, "solo uno"),
        ({"texto": "a", "fecha_hora": "2026-10-30 07:00"}, "ya pasó"),
        ({"texto": "a", "fecha_hora": "2028-01-01 09:00"}, "próximo año"),
        ({"texto": "a", "fecha_hora": "mañana"}, "YYYY-MM-DD HH:MM"),
        ({"texto": "   ", "en_minutos": 5}, "vacío"),
    ],
)
def test_create_validation(store: ReminderStore, clock: Clock, tool_input: dict, expected: str) -> None:
    result = run(store, clock, "crear_recordatorio", **tool_input)

    assert result.is_error
    assert expected in result.content
    assert store.pending() == []


def test_list_and_cancel(store: ReminderStore, clock: Clock) -> None:
    run(store, clock, "crear_recordatorio", texto="Llamar a Laura", en_minutos=60)
    listed = json.loads(run(store, clock, "listar_recordatorios").content)
    reminder_id = listed["recordatorios"][0]["id"]

    cancelled = run(store, clock, "cancelar_recordatorio", id=reminder_id)
    again = run(store, clock, "cancelar_recordatorio", id=reminder_id)

    assert listed["ahora"] == "2026-10-30 08:00"
    assert json.loads(cancelled.content)["cancelado"]["texto"] == "Llamar a Laura"
    assert again.is_error
    assert "No hay recordatorios pendientes" in run(store, clock, "listar_recordatorios").content


# --- Entrega y botones ------------------------------------------------------


def delivery(store: ReminderStore, clock: Clock, channel: FakeChannel) -> ReminderDelivery:
    return ReminderDelivery(store, channel, OWNER, TZ, clock)


def test_due_reminder_is_sent_once_with_buttons(store: ReminderStore, clock: Clock) -> None:
    channel = FakeChannel()
    reminder = store.create("Llamar a Laura", at(9))
    clock.advance(hours=1, minutes=30)  # 9:30: media hora tarde (por ejemplo, el PC estaba apagado)

    assert delivery(store, clock, channel).deliver_due() == 1
    assert delivery(store, clock, channel).deliver_due() == 0

    text, buttons = channel.sent[0]
    assert text == "⏰ Recordatorio: Llamar a Laura\n(Atrasado: era para hoy a las 09:00.)"
    assert [data for _, data in buttons] == [f"rem:{reminder.id}:posponer", f"rem:{reminder.id}:hecho"]
    assert store.get(reminder.id).status == "sent"  # type: ignore[union-attr]


def test_on_time_reminder_is_not_marked_late(store: ReminderStore, clock: Clock) -> None:
    channel = FakeChannel()
    store.create("Llamar a Laura", at(8, 1))
    clock.advance(minutes=1)

    delivery(store, clock, channel).deliver_due()

    assert channel.sent[0][0] == "⏰ Recordatorio: Llamar a Laura"


def test_reminder_from_another_day_says_the_date(store: ReminderStore, clock: Clock) -> None:
    channel = FakeChannel()
    store.create("Pagar", at(9))
    clock.advance(days=1)

    delivery(store, clock, channel).deliver_due()

    assert "era para el 30/10 a las 09:00" in channel.sent[0][0]


def test_failed_send_stays_pending_for_next_check(store: ReminderStore, clock: Clock) -> None:
    reminder = store.create("Llamar a Laura", at(8, 1))
    clock.advance(minutes=1)

    assert delivery(store, clock, FakeChannel(fail=True)).deliver_due() == 0
    assert store.get(reminder.id).status == "pending"  # type: ignore[union-attr]


def sent_reminder(store: ReminderStore, clock: Clock, channel: FakeChannel) -> int:
    reminder = store.create("Llamar a Laura", at(8, 1))
    clock.advance(minutes=1)
    delivery(store, clock, channel).deliver_due()
    return reminder.id


def test_snooze_button(store: ReminderStore, clock: Clock) -> None:
    channel = FakeChannel()
    reminder_id = sent_reminder(store, clock, channel)

    handled = delivery(store, clock, channel).handle_button(
        ButtonAnswer("cb1", OWNER, f"rem:{reminder_id}:posponer", handle=1)
    )

    assert handled
    assert channel.acks == [("cb1", "Pospuesto 10 minutos")]
    assert channel.replaced == [(1, "⏰ Recordatorio: Llamar a Laura\n\n⏸ Pospuesto hasta las 08:11")]
    clock.advance(minutes=10)
    assert [r.id for r in store.due()] == [reminder_id]


def test_done_button(store: ReminderStore, clock: Clock) -> None:
    channel = FakeChannel()
    reminder_id = sent_reminder(store, clock, channel)

    delivery(store, clock, channel).handle_button(ButtonAnswer("cb1", OWNER, f"rem:{reminder_id}:hecho", handle=1))

    assert channel.acks == [("cb1", "¡Listo!")]
    assert channel.replaced[0][1].endswith("✅ Hecho")
    assert store.get(reminder_id).status == "done"  # type: ignore[union-attr]


def test_buttons_of_a_closed_reminder(store: ReminderStore, clock: Clock) -> None:
    channel = FakeChannel()
    reminder_id = sent_reminder(store, clock, channel)
    handler = delivery(store, clock, channel).handle_button
    handler(ButtonAnswer("cb1", OWNER, f"rem:{reminder_id}:hecho", handle=1))

    handler(ButtonAnswer("cb2", OWNER, f"rem:{reminder_id}:posponer", handle=1))

    assert channel.acks[-1] == ("cb2", "Este recordatorio ya no está activo.")


def test_other_buttons_are_not_handled(store: ReminderStore, clock: Clock) -> None:
    handler = delivery(store, clock, FakeChannel()).handle_button

    assert not handler(ButtonAnswer("cb1", OWNER, "abc123:si"))
