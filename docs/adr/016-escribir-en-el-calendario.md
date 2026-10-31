# ADR 016: Escribir en el calendario con confirmación, solo en eventos propios

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.12

## Contexto

Hasta la v0.11, JARVIS solo leía el calendario (`calendar.readonly`). El usuario quiere pedirle
que agende, mueva o cancele eventos. Es la primera vez que JARVIS cambia algo fuera de sus propios
datos en un servicio real.

## Decisión

1. **Tres tools con confirmación:** `crear_evento`, `mover_evento` y `cancelar_evento`. La pregunta
   muestra el detalle (título, día y horas en español, lugar) y los **choques de horario**; en
   eventos recurrentes avisa que solo cambia esa ocasión.
2. **Solo eventos que organiza el usuario** (`organizer.self` en Google): las invitaciones de otras
   personas no se mueven ni se cancelan, para no afectar reuniones ajenas. `get_reuniones` devuelve
   `id` y `organizas_tu` para que el modelo sepa qué puede tocar.
3. **Nunca se avisa a nadie:** sin invitados y con `sendUpdates="none"` en cada escritura. Los
   eventos creados llevan una marca privada (`extendedProperties.private.jarvis`).
4. **Validar antes de preguntar:** preparar la confirmación también valida (formato, horas pasadas,
   evento existente y propio); si falla, el registro de tools devuelve el error al modelo sin
   molestar al usuario (antes, un fallo ahí no estaba contemplado).
5. **Permiso mínimo para escribir:** `calendar.events` (ver y editar eventos, no compartir ni borrar
   calendarios) en lugar de `calendar`. Con un token antiguo de solo lectura, JARVIS sigue leyendo y,
   al intentar escribir, explica cómo dar el permiso (`google-login`); `estado` lo indica.
6. **Calendario de ejemplo escribible en memoria**, para probar sin tocar Google.

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| Permitir cambiar cualquier evento | Mover o cancelar una invitación afecta la reunión de otras personas. |
| Solo eventos creados por JARVIS | No podría mover las citas que el usuario agendó a mano. |
| Invitar participantes | Envía correos a terceros: un efecto externo mayor, para una versión posterior. |
| Permiso `calendar` completo | Da acceso a compartir y borrar calendarios, que JARVIS no necesita. |

## Consecuencias

- Hay que volver a autorizar Google una vez (`google-login`) para aceptar el permiso nuevo.
- Por ahora no se crean eventos de día completo ni recurrentes, y no se mueven los de día completo.
- Los registros solo anotan "evento creado/movido/cancelado", nunca títulos ni detalles.
