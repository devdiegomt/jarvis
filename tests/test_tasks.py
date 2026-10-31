import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from anthropic_fakes import FakeClient, text_response
from jarvis.agenda import SampleCalendar
from jarvis.summary import build_summary, send_daily_summary
from jarvis.tasks import TaskLimitError, TaskStore
from jarvis.tools import build_registry

TZ = ZoneInfo("America/Bogota")
TODAY = date(2026, 10, 30)


class Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 30, 8, 0, tzinfo=TZ)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> TaskStore:
    return TaskStore(tmp_path / "jarvis.db", now=clock)


# --- Almacenamiento ---------------------------------------------------------


def test_open_tasks_with_date_come_first_by_urgency(store: TaskStore) -> None:
    no_date = store.add("Ordenar el escritorio")
    later = store.add("Pagar la factura", date(2026, 11, 5))
    sooner = store.add("Renovar el pasaporte", date(2026, 10, 31))

    assert [t.id for t in store.open()] == [sooner.id, later.id, no_date.id]


def test_due_by_includes_overdue_but_not_future_or_undated(store: TaskStore) -> None:
    overdue = store.add("Atrasado", date(2026, 10, 28))
    today = store.add("Hoy", TODAY)
    store.add("Futuro", date(2026, 11, 2))
    store.add("Sin fecha")

    assert [t.id for t in store.due_by(TODAY)] == [overdue.id, today.id]


def test_complete_and_delete(store: TaskStore) -> None:
    done = store.add("Hecho")
    gone = store.add("Ya no hace falta")

    assert store.complete(done.id) and not store.complete(done.id)
    assert store.delete(gone.id) and not store.delete(gone.id)
    assert store.open() == []
    assert store.get(done.id).done  # type: ignore[union-attr]


def test_purge_removes_only_old_completed_tasks(store: TaskStore, clock: Clock) -> None:
    done = store.add("Hecho")
    store.complete(done.id)
    still_open = store.add("Abierto")

    clock.advance(days=31)

    assert store.purge_old() == 1
    assert store.get(done.id) is None and store.get(still_open.id) is not None


def test_open_task_limit(store: TaskStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.tasks.MAX_OPEN_TASKS", 2)
    store.add("a")
    store.add("b")

    with pytest.raises(TaskLimitError):
        store.add("c")


# --- Tools ------------------------------------------------------------------


def run(store: TaskStore, clock: Clock, tool: str, **tool_input: Any):  # type: ignore[no-untyped-def]
    return build_registry(SampleCalendar(TZ), tasks=store, now=clock).execute(tool, tool_input)


def test_task_tools_are_registered_and_need_no_confirmation(store: TaskStore, clock: Clock) -> None:
    registry = build_registry(SampleCalendar(TZ), tasks=store, now=clock)
    names = {"agregar_pendiente", "listar_pendientes", "completar_pendiente", "borrar_pendiente"}

    assert names <= set(registry.names())
    assert not any(registry.get(name).requires_confirmation for name in names)  # type: ignore[union-attr]
    assert "agregar_pendiente" not in build_registry(SampleCalendar(TZ)).names()


def test_add_and_list_marks_overdue(store: TaskStore, clock: Clock) -> None:
    run(store, clock, "agregar_pendiente", texto="Renovar el pasaporte", fecha_limite="2026-10-29")
    run(store, clock, "agregar_pendiente", texto="Llamar al banco")

    listed = json.loads(run(store, clock, "listar_pendientes").content)

    assert listed["hoy"] == "2026-10-30"
    assert listed["pendientes"][0] == {
        "id": 1,
        "texto": "Renovar el pasaporte",
        "fecha_limite": "2026-10-29",
        "atrasado": True,
    }
    assert listed["pendientes"][1] == {"id": 2, "texto": "Llamar al banco"}


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [({"texto": "  "}, "vacío"), ({"texto": "a", "fecha_limite": "el viernes"}, "YYYY-MM-DD")],
)
def test_add_validation(store: TaskStore, clock: Clock, tool_input: dict, expected: str) -> None:
    result = run(store, clock, "agregar_pendiente", **tool_input)

    assert result.is_error and expected in result.content
    assert store.open() == []


def test_complete_and_delete_tools(store: TaskStore, clock: Clock) -> None:
    run(store, clock, "agregar_pendiente", texto="Uno")
    run(store, clock, "agregar_pendiente", texto="Dos")

    completed = run(store, clock, "completar_pendiente", id=1)
    deleted = run(store, clock, "borrar_pendiente", id=2)

    assert json.loads(completed.content)["completado"]["texto"] == "Uno"
    assert json.loads(deleted.content)["borrado"]["texto"] == "Dos"
    assert run(store, clock, "completar_pendiente", id=1).is_error
    assert "No hay pendientes abiertos" in run(store, clock, "listar_pendientes").content


# --- Resumen diario ---------------------------------------------------------


def test_summary_lists_tasks_for_today_and_overdue(store: TaskStore) -> None:
    store.add("Renovar el pasaporte", date(2026, 10, 28))
    store.add("Pagar la factura", TODAY)

    summary = build_summary(TODAY, [], None, "Ejemplo", store.due_by(TODAY))

    assert summary.subject.endswith("(sin reuniones, 2 pendientes)")
    assert "Pendientes para hoy:\n- Renovar el pasaporte (atrasado: era para el 28/10)\n- Pagar la factura" in summary.body


def test_summary_without_tasks_has_no_section() -> None:
    assert "Pendientes" not in build_summary(TODAY, [], None, "Ejemplo").body


def test_send_daily_summary_reads_tasks_and_shares_them_with_claude(store: TaskStore, clock: Clock) -> None:
    store.add("Pagar la factura", TODAY)
    store.add("Algún día", None)
    client = FakeClient([text_response("Aprovecha el hueco para pagar la factura.")])
    sent: list[tuple[str, str]] = []
    notifier = type("N", (), {"name": "falso", "send": lambda _self, subject, body: sent.append((subject, body))})()

    send_daily_summary(
        day=TODAY,
        calendar=SampleCalendar(TZ),
        notifier=notifier,
        client=client,  # type: ignore[arg-type]
        model="m",
        log=None,
        now=clock,
        tasks=store,
    )

    payload = json.loads(client.messages.calls[0]["messages"][0]["content"])
    assert payload["pendientes"] == ["Pagar la factura"]
    assert "Pendientes para hoy:\n- Pagar la factura" in sent[0][1]
    assert "Algún día" not in sent[0][1]
