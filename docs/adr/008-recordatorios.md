# ADR 008: Recordatorios locales entregados por el proceso de Telegram

- **Estado:** Aceptada
- **Fecha:** 2026-10-30
- **Versión:** v0.7

## Contexto

JARVIS debe poder "recordarte cosas": el usuario pide en lenguaje natural un recordatorio
("mañana a las 9", "en 2 horas") y a esa hora recibe un aviso. Desde la v0.6, el proceso de Telegram
corre todo el tiempo en segundo plano mientras el PC está encendido.

## Decisión

1. **Tres tools del agente**: `crear_recordatorio`, `listar_recordatorios` y
   `cancelar_recordatorio`.
   - `crear_recordatorio` acepta `fecha_hora` (local, `YYYY-MM-DD HH:MM`) **o** `en_minutos`. El
     plazo relativo evita depender de que el modelo conozca la hora exacta (en la consola solo
     recibe la fecha).
   - Rechaza fechas pasadas o a más de un año, y textos vacíos o de más de 500 caracteres.
2. **Sin confirmación.** La regla de confirmar se aplica a acciones con efectos *externos*.
   Crear o cancelar un recordatorio es interno a JARVIS, reversible, y el agente siempre dice
   qué hizo; pedir confirmación añadiría fricción sin proteger nada.
3. **Almacenamiento en SQLite** (`reminders` en `jarvis.db`), con la hora en UTC y estados
   `pending → sent → done`, `pending → cancelled`, y `sent → pending` al posponer.
   Los cerrados se borran a los 30 días.
4. **Entrega por el proceso de Telegram** (`ReminderDelivery`), que revisa cada 30 s los
   vencidos. Se marca como enviado *después* de enviarlo: ante un fallo es preferible un aviso
   repetido a uno perdido; si el envío falla, se reintenta en la siguiente revisión. Los avisos
   con más de 5 minutos de retraso (PC apagado) indican la hora original.
5. **Botones [Posponer 10 min] [Hecho]** en el aviso. El canal de chat se generaliza
   (`send_with_buttons`, `replace_message`) y `ChatService` acepta un `button_handler` para los
   botones que no son de una confirmación, incluso mientras espera una.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Una tarea del Programador de tareas por recordatorio | Crea y borra tareas de Windows sin parar, frágil, y no funciona igual fuera de Windows. |
| Temporizadores en memoria | Se pierden al reiniciar el PC o el proceso. |
| Pedir confirmación al crear | Fricción sin beneficio: nada sale de JARVIS y se puede cancelar. |
| Recordatorios de Google Calendar / Tasks | Requiere permisos de escritura en Google; se evaluará con la escritura en el calendario. |
| Marcar como enviado antes de enviar | Si el envío falla o el proceso muere, el recordatorio se perdería. |

## Consecuencias

- Los recordatorios solo llegan mientras el proceso de Telegram corre (PC encendido y sesión
  iniciada); los atrasados se entregan al volver.
- La resolución es de unos 30 segundos.
- La entrega reutilizable (`ReminderDelivery`) servirá de base para los avisos proactivos
  (por ejemplo, antes de cada reunión).
- Aún no hay recordatorios recurrentes ("todos los lunes"); quedan para una versión futura.
