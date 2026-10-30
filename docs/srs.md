# Especificación de requisitos de software (SRS): JARVIS

- **Versión del documento:** 1.6 (cubre hasta la v0.8.1)
- **Fecha:** 2026-10-30
- **Estado:** vivo; se actualiza al cerrar cada versión

## 1. Introducción

### 1.1 Propósito

Este documento describe qué debe hacer JARVIS y con qué restricciones. Sirve de referencia para
implementar cada versión, para escribir sus tests y para quien revise el proyecto como portafolio.
Las decisiones de diseño (el *cómo*) están en los ADR de [`docs/adr/`](adr/).

### 1.2 Alcance

JARVIS es un asistente personal con IA que ayuda a una persona a organizar su día: consulta sus
reuniones, le envía un resumen diario y conversa con ella por consola y por Telegram, por escrito o
con notas de voz. Se construye
en versiones pequeñas (ver el roadmap en [`CLAUDE.md`](../CLAUDE.md)).

### 1.3 Definiciones

| Término | Significado |
|---|---|
| Usuario | La persona dueña de JARVIS (por ahora, una sola). |
| Agente | El loop que conversa con Claude y ejecuta tools (ADR 001). |
| Tool | Función que el modelo puede pedir ejecutar (por ejemplo, `get_reuniones`). |
| Efecto externo | Acción que cambia algo fuera de JARVIS: enviar un mensaje, crear o borrar un evento. |
| Fuente de calendario | Origen de las reuniones: datos de ejemplo o Google Calendar. |
| Canal | Vía por la que el usuario habla con JARVIS o recibe avisos: consola, Telegram, Gmail. |
| Conversación | Secuencia de mensajes con historial compartido; en Telegram termina por inactividad o con `/nuevo`. |
| Transcripción | Paso de una nota de voz a texto; hoy se hace en el PC con Whisper. |

## 2. Descripción general

### 2.1 Perspectiva

JARVIS es una aplicación Python que corre en el PC del usuario (Windows como plataforma principal).
Usa servicios externos: la API de Anthropic (modelo de lenguaje), Google Calendar y Gmail
(OAuth del propio usuario) y la API de bots de Telegram (con un bot propio del usuario).

### 2.2 Usuarios

Un único usuario técnico-intermedio: sabe usar una terminal y seguir pasos de configuración en
Google Cloud y en Telegram (@BotFather), guiado por el README.

### 2.3 Restricciones

- **R-1.** Python 3.12, dependencias gestionadas con `uv`.
- **R-2.** SDK oficial de Anthropic con loop propio, sin frameworks de agentes (ADR 001).
- **R-3.** Modelo configurable por `JARVIS_MODEL`.
- **R-4.** Solo vías oficiales de cada servicio (sin automatizar clientes web de mensajería ni similares).
- **R-5.** Sin servidores propios en la nube por ahora: todo corre en el PC del usuario.

### 2.4 Supuestos

- El PC está encendido y con sesión iniciada cuando se espera el resumen o una respuesta por Telegram.
- El usuario tiene una cuenta de Google y una de Telegram.

## 3. Requisitos funcionales

### v0.1: agente por consola

- **RF-01.** El usuario conversa con JARVIS desde la consola (`uv run jarvis`); `salir` termina.
- **RF-02.** El historial se mantiene durante la sesión de consola.
- **RF-03.** El agente puede usar tools; como máximo 10 iteraciones de tool use por mensaje.
- **RF-04.** Las tools se registran en un registro central; agregar una no requiere modificar el agente.
- **RF-05.** Si una tool falla, el error vuelve al modelo como resultado (`is_error`) y la sesión sigue.
- **RF-06.** Toda tool con efectos externos pide confirmación (s/n) antes de ejecutarse.
- **RF-07.** `enviar_mensaje(destinatario, texto)` está simulada: muestra el mensaje y pide confirmación.

### v0.2: Google Calendar

- **RF-08.** `get_reuniones` devuelve las reuniones de una fecha o de un rango de hasta 14 días.
- **RF-09.** La fuente de calendario se elige con `JARVIS_CALENDAR=sample|google`; con `google`
  y sin autorización, JARVIS no arranca y explica qué hacer.
- **RF-10.** `uv run jarvis google-login` autoriza el acceso con OAuth de escritorio.
- **RF-11.** Las horas se muestran en la zona horaria del usuario (`JARVIS_TIMEZONE`); se
  distinguen eventos de día completo y se omiten los cancelados o rechazados.

### v0.3: resumen diario

- **RF-12.** `uv run jarvis resumen` envía un texto con la agenda del día y un comentario breve
  generado por Claude, por el canal elegido en `JARVIS_RESUMEN_CANAL` (Telegram o Gmail; v0.5).
- **RF-13.** Si Claude falla, el correo se envía igual, con la agenda y sin comentario.
- **RF-14.** No se envía más de un resumen por día, salvo con `--force`; `--dry-run` lo muestra
  sin enviarlo.
- **RF-15.** `programar-resumen` lo programa de lunes a viernes a `JARVIS_RESUMEN_HORA`;
  `quitar-resumen` lo elimina.
- **RF-16.** El destinatario es fijo por configuración (correo o cuenta de Telegram del usuario);
  el modelo no puede cambiarlo.

### v0.4 → v0.5: chat por Telegram

La v0.4 implementó estos requisitos con WhatsApp; la v0.5 los traslada a Telegram y retira WhatsApp
(ADR 005).

- **RF-17.** `uv run jarvis telegram` conecta JARVIS a un bot de Telegram del usuario y responde
  con el mismo agente y las mismas tools que la consola.
- **RF-18.** Solo se atienden mensajes de la cuenta del usuario (`TELEGRAM_OWNER_ID`) en chat
  privado; sin ese ID configurado, el chat no arranca. `jarvis telegram-vincular` lo obtiene.
- **RF-19.** Las confirmaciones se piden en el chat con botones Sí/No (también vale escribir "s/n");
  sin respuesta en 5 minutos, la acción se cancela. Los botones de preguntas antiguas avisan que
  expiraron.
- **RF-20.** El historial del chat persiste entre reinicios; una conversación nueva empieza
  tras 6 horas de inactividad o con `/nuevo`. `/start` da la bienvenida y `/ayuda` lista los comandos.
- **RF-21.** Los mensajes que no son texto reciben una respuesta indicando que solo se entiende texto.
- **RF-22.** Las respuestas de más de 4096 caracteres se dividen en varios mensajes.

### v0.6: JARVIS siempre disponible

- **RF-23.** `programar-telegram` hace que JARVIS arranque en segundo plano, sin ventanas, al
  iniciar sesión en Windows (y en ese momento); `quitar-telegram` lo detiene y quita el arranque.
- **RF-24.** En segundo plano, JARVIS se reconecta solo tras cortes de red o suspensión, y espera
  si otra copia está usando el bot en lugar de terminar.
- **RF-25.** `jarvis estado` muestra la configuración, el estado de las tareas programadas y las
  últimas líneas de los registros.
- **RF-26.** `resumen --dry-run` indica por qué canal se enviaría el resumen.

### v0.7: recordatorios

- **RF-27.** El usuario crea recordatorios en lenguaje natural, con fecha y hora o con un plazo
  relativo; no se aceptan fechas pasadas ni a más de un año.
- **RF-28.** El usuario puede listar y cancelar sus recordatorios pendientes.
- **RF-29.** A la hora indicada, JARVIS envía el recordatorio por Telegram con botones
  [Posponer 10 min] y [Hecho]; si se entrega con más de 5 minutos de retraso, indica la hora original.
- **RF-30.** Un recordatorio no se envía dos veces; si el envío falla, se reintenta.
- **RF-31.** `jarvis estado` muestra cuántos recordatorios hay pendientes y la hora del próximo
  (sin su texto).

### v0.8: notas de voz

- **RF-32.** El usuario envía notas de voz por Telegram; JARVIS las transcribe, le muestra lo que
  entendió y responde como si se lo hubiera escrito.
- **RF-33.** Las confirmaciones también se pueden responder con una nota de voz ("sí" / "no").
- **RF-34.** Si la voz no está instalada, falta el modelo, la nota dura más de 5 minutos o no se
  entiende nada, JARVIS lo dice con un mensaje claro en español (y cómo solucionarlo).
- **RF-35.** `jarvis preparar-voz` descarga una sola vez el modelo de voz configurado
  (`JARVIS_WHISPER_MODELO`); `JARVIS_TRANSCRIPCION=no` desactiva las notas de voz.
- **RF-36.** `jarvis estado` y el arranque del bot indican si las notas de voz están activas.

### v0.8.1: respuestas con voz

- **RF-37.** Por defecto, JARVIS responde con una nota de voz (y el texto) cuando el usuario le
  habla con una nota de voz, y solo por escrito cuando le escribe.
- **RF-38.** Con `/voz` el usuario elige cuándo responder con voz: si le habla, siempre o nunca. La
  elección se guarda y sobrevive a reinicios.
- **RF-39.** La respuesta escrita llega siempre; si la voz falla, la respuesta llega igual por escrito
  y, si falta instalar o descargar la voz, se explica una vez cómo hacerlo.
- **RF-40.** `jarvis preparar-voz` descarga también la voz configurada (`JARVIS_PIPER_VOZ`);
  `JARVIS_RESPUESTA_VOZ=no` desactiva las respuestas con voz. `estado` indica si están activas.

## 4. Requisitos no funcionales

### 4.1 Seguridad

- **RNF-01.** Ninguna credencial (API keys, tokens, secretos) está en el código ni en el repositorio:
  van en `.env` o en `~/.config/jarvis/`, ignorados por git. `.env.example` lista los nombres sin valores.
- **RNF-02.** Permiso mínimo en cada servicio: `calendar.readonly`; `gmail.send` solo si el resumen
  está configurado.
- **RNF-03.** Los tokens OAuth se guardan con permisos de archivo solo para el usuario.
- **RNF-04.** JARVIS no abre puertos en el PC: recibe los mensajes de Telegram consultando su API
  (long polling). El token del bot nunca aparece en logs ni en mensajes de error.
- **RNF-05.** Las acciones programadas no son tools: el modelo no puede dispararlas ni cambiar su destino.
- **RNF-05b.** Las conexiones HTTPS siempre verifican el certificado, usando el almacén de
  certificados del sistema operativo (v0.5.1); nunca se desactiva la verificación.

### 4.2 Privacidad

- **RNF-06.** Los logs no contienen el contenido de mensajes, correos ni reuniones: solo resultados,
  IDs y tipos de error.
- **RNF-07.** El historial del chat se guarda solo en el equipo del usuario y se borra a los 30 días.
- **RNF-08.** No se guarda el contenido de los resúmenes enviados, solo la fecha y hora del envío.
- **RNF-08b.** Los recordatorios se guardan solo en el equipo; los cerrados se borran a los 30 días
  y los registros solo contienen sus IDs.
- **RNF-08c.** El audio de las notas de voz se procesa en memoria en el PC y nunca se guarda en disco
  ni se envía a terceros; los registros solo contienen su duración y el tiempo de transcripción.
- **RNF-08d.** Las respuestas con voz se generan en el PC, en memoria: su texto no se envía a ningún
  servicio de voz externo.

### 4.3 Fiabilidad

- **RNF-09.** Un fallo de un servicio externo no rompe el programa: se informa al usuario con un
  mensaje claro en español.
- **RNF-10.** El resumen programado reintenta hasta 3 veces ante fallos temporales; los errores de
  autorización no se reintentan.
- **RNF-11.** Las actualizaciones que Telegram reenvía tras un reinicio no producen respuestas
  duplicadas; los fallos de red se reintentan con espera creciente.
- **RNF-11b.** Los registros rotan (1 MB por archivo, como máximo 4 archivos) para no crecer sin
  límite con JARVIS corriendo todo el día.
- **RNF-11c.** Un fallo al descargar o transcribir una nota de voz no detiene el chat; el proceso en
  segundo plano nunca descarga modelos.

### 4.4 Calidad y mantenibilidad

- **RNF-12.** Código, funciones y variables en inglés; comentarios, docs y mensajes al usuario en español.
- **RNF-13.** Type hints en todo; funciones pequeñas con una sola responsabilidad.
- **RNF-14.** Cada funcionalidad viene con tests; las APIs externas y el sistema operativo se mockean.
- **RNF-15.** Los tests corren en GitHub Actions en cada pull request y en cada push a `main`, sin
  instalar las dependencias opcionales de voz.
- **RNF-16.** Cada decisión de arquitectura relevante se documenta en un ADR.

### 4.5 Plataforma

- **RNF-17.** Windows es la plataforma principal; la programación del resumen y del chat en segundo
  plano usa el Programador de tareas, siempre con la sesión del usuario iniciada (sin guardar su
  contraseña). En Mac y Linux, el resto funciona y se indica la línea de `cron` equivalente.

## 5. Fuera de alcance (por ahora)

- Leer los chats personales del usuario (WhatsApp, Telegram) o escribir desde su cuenta.
- Enviar mensajes reales a terceros: `enviar_mensaje` sigue simulada.
- Crear, modificar o borrar eventos del calendario.
- Imágenes o archivos en el chat; voces en la nube (por ejemplo, ElevenLabs).
- WhatsApp como canal (retirado en la v0.5; ver ADR 004 y ADR 005).
- Varios usuarios, servidor en la nube, Alexa y llamadas telefónicas (ver roadmap).

## 6. Trazabilidad

| Requisito | Dónde se implementa | Tests principales |
|---|---|---|
| RF-01 a RF-07 | `agent.py`, `tools/`, `cli.py` | `test_agent.py`, `test_tools.py`, `test_cli.py` |
| RF-08 a RF-11 | `agenda/`, `google_auth.py`, `tools/reuniones.py` | `test_google_calendar.py`, `test_google_auth.py`, `test_tools.py` |
| RF-12 a RF-16 | `summary.py`, `summary_cli.py`, `notify/`, `scheduler.py`, `storage.py` | `test_summary.py`, `test_gmail.py`, `test_scheduler.py`, `test_storage.py` |
| RF-17 a RF-22 | `chat.py`, `telegram/`, `memory.py`, `confirmation.py` | `test_chat.py`, `test_telegram.py`, `test_memory.py`, `test_confirmation.py` |
| RF-23 a RF-26 | `scheduler.py`, `telegram/app.py`, `status.py`, `logs.py`, `summary_cli.py` | `test_scheduler.py`, `test_status.py`, `test_logs.py`, `test_telegram.py`, `test_summary_cli.py` |
| RF-27 a RF-31 | `reminders.py`, `reminder_delivery.py`, `tools/recordatorios.py`, `chat.py` | `test_reminders.py`, `test_chat.py`, `test_status.py` |
| RF-32 a RF-36 | `voice.py`, `chat.py`, `telegram/`, `confirmation.py`, `cli.py`, `status.py` | `test_voice.py`, `test_chat.py`, `test_telegram.py`, `test_confirmation.py`, `test_status.py` |
| RF-37 a RF-40 | `speech.py`, `chat.py`, `memory.py`, `telegram/client.py`, `cli.py`, `status.py` | `test_speech.py`, `test_chat.py`, `test_memory.py`, `test_telegram.py`, `test_status.py` |
| RNF-01 a RNF-08 | `config.py`, `google_auth.py`, `telegram/client.py`, logs | `test_config.py`, `test_google_auth.py`, `test_telegram.py` |
