# ADR 017: Avisos proactivos armados en código por el proceso de Telegram

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.13

## Contexto

JARVIS solo hablaba cuando el usuario le escribía, además del resumen de la mañana y los
recordatorios pedidos. Un asistente útil avisa por su cuenta de lo que viene: la próxima reunión y
cómo pinta el día siguiente.

## Decisión

1. **Aviso antes de cada reunión con hora**, por Telegram, `JARVIS_AVISO_REUNION` minutos antes (10
   por defecto; 0 lo apaga). Incluye horario, hasta 3 participantes, lugar y enlace de la
   videollamada (Meet, la conferencia del evento o un enlace puesto como lugar).
2. **Vistazo a mañana** de domingo a jueves, a partir de `JARVIS_VISTAZO_MANANA` (20:00; `no` lo
   apaga): reuniones de mañana y pendientes que vencen. Si el PC se enciende más tarde esa noche, se
   envía igual, una vez.
3. **Armados en código, sin IA:** instantáneos, sin costo y con horas exactas (como la agenda del
   resumen diario).
4. **En el proceso de Telegram**, en un hilo que revisa cada minuto (como los recordatorios). El
   calendario se consulta como mucho cada 5 minutos, para no gastar cuota de Google ni red.
5. **Sin repetir:** un registro en `jarvis.db` (`sent_notices`) con la clave del aviso (reunión + hora
   de inicio, o el día del vistazo), sin títulos, guardado 30 días. Si una reunión se mueve, su clave
   cambia y se avisa a la hora nueva. Se anota después de enviar: si el envío falla, se reintenta.
6. **Sin avisos tardíos:** si la reunión ya empezó (por ejemplo, el PC estaba apagado), no se avisa.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Que Claude redacte cada aviso | Más lento y con costo por aviso, sin aportar a un mensaje que es pura agenda. |
| Notificaciones de Google Calendar | No llegan por Telegram ni se integran con JARVIS (voz, vistazo, pendientes). |
| Una tarea del Programador de tareas por aviso | Frágil y difícil de mantener; el proceso de Telegram ya corre todo el día. |
| Consultar el calendario cada minuto | 1440 consultas al día sin necesidad; cada 5 minutos basta con el aviso de 10 minutos. |

## Consecuencias

- Los avisos dependen de que el PC esté encendido y JARVIS en segundo plano.
- Un cambio en el calendario puede tardar hasta 5 minutos en reflejarse en los avisos.
- La base para más avisos (por ejemplo, correos de clientes en la próxima versión) queda en
  `ProactiveNotifier`.
