"""Entrega de recordatorios por el canal de chat y atención de sus botones [Posponer] y [Hecho]."""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, tzinfo

from jarvis.chat import ButtonAnswer, ChannelError, ChatChannel
from jarvis.reminders import SNOOZE_MINUTES, Reminder, ReminderStore

CHECK_INTERVAL_SECONDS = 30
PURGE_INTERVAL = timedelta(hours=24)
LATE_AFTER = timedelta(minutes=5)  # a partir de aquí, el aviso se marca como atrasado
BUTTON_PREFIX = "rem"

logger = logging.getLogger("jarvis.chat")


class ReminderDelivery:
    """Envía los recordatorios vencidos por el canal de chat y atiende sus botones."""

    def __init__(
        self,
        store: ReminderStore,
        channel: ChatChannel,
        owner: str,
        timezone: tzinfo,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._channel = channel
        self._owner = owner
        self._tz = timezone
        self._now = now
        self._last_purge: datetime | None = None

    def deliver_due(self) -> int:
        """Envía los recordatorios vencidos. Devuelve cuántos se enviaron.

        Se marca como enviado después de enviarlo: si algo falla entre medias, es preferible
        un aviso repetido a uno perdido. Si el canal falla, se reintenta en la próxima revisión.
        """
        sent = 0
        for reminder in self._store.due():
            buttons = [
                ("⏰ Posponer 10 min", f"{BUTTON_PREFIX}:{reminder.id}:posponer"),
                ("✅ Hecho", f"{BUTTON_PREFIX}:{reminder.id}:hecho"),
            ]
            try:
                self._channel.send_with_buttons(self._owner, self._message(reminder), buttons)
            except ChannelError as exc:
                logger.warning("No se pudo enviar el recordatorio %d: %s", reminder.id, exc)
                break
            self._store.mark_sent(reminder.id)
            logger.info("Recordatorio %d enviado.", reminder.id)
            sent += 1
        return sent

    def handle_button(self, answer: ButtonAnswer) -> bool:
        """Atiende [Posponer] y [Hecho]. Devuelve False si el botón no es de un recordatorio."""
        prefix, _, rest = answer.data.partition(":")
        id_text, _, action = rest.partition(":")
        if prefix != BUTTON_PREFIX or not id_text.isdigit():
            return False

        reminder = self._store.get(int(id_text))
        if action == "posponer" and reminder and (snoozed := self._store.snooze(reminder.id)):
            self._channel.acknowledge(answer, f"Pospuesto {SNOOZE_MINUTES} minutos")
            until = f"{self._local(snoozed.due_at):%H:%M}"
            self._replace(answer, f"⏰ Recordatorio: {reminder.text}\n\n⏸ Pospuesto hasta las {until}")
        elif action == "hecho" and reminder and self._store.mark_done(reminder.id):
            self._channel.acknowledge(answer, "¡Listo!")
            self._replace(answer, f"⏰ Recordatorio: {reminder.text}\n\n✅ Hecho")
        else:
            self._channel.acknowledge(answer, "Este recordatorio ya no está activo.")
        return True

    def run_forever(
        self, interval: float = CHECK_INTERVAL_SECONDS, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        while True:
            try:
                self.deliver_due()
                self._purge_if_due()
            except Exception:
                logger.exception("Error inesperado al revisar los recordatorios.")
            sleep(interval)

    def _message(self, reminder: Reminder) -> str:
        text = f"⏰ Recordatorio: {reminder.text}"
        if self._now() - reminder.due_at > LATE_AFTER:
            text += f"\n(Atrasado: era para {self._describe(reminder.due_at)}.)"
        return text

    def _describe(self, moment: datetime) -> str:
        local = self._local(moment)
        if local.date() == self._now().astimezone(self._tz).date():
            return f"hoy a las {local:%H:%M}"
        return f"el {local:%d/%m} a las {local:%H:%M}"

    def _local(self, moment: datetime) -> datetime:
        return moment.astimezone(self._tz)

    def _replace(self, answer: ButtonAnswer, text: str) -> None:
        if answer.handle is None:
            return
        try:
            self._channel.replace_message(answer.sender, answer.handle, text)
        except ChannelError as exc:
            logger.warning("No se pudo actualizar el mensaje del recordatorio: %s", exc)

    def _purge_if_due(self) -> None:
        now = self._now()
        if self._last_purge is None or now - self._last_purge >= PURGE_INTERVAL:
            deleted = self._store.purge_old()
            self._last_purge = now
            if deleted:
                logger.info("Borrados %d recordatorios antiguos.", deleted)
