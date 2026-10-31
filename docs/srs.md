# Especificación de requisitos de software (SRS): JARVIS

- **Versión del documento:** 2.6 (cubre hasta la v0.15)
- **Fecha:** 2026-10-31
- **Estado:** vivo; se actualiza al cerrar cada versión

## 1. Introducción

### 1.1 Propósito

Este documento describe qué debe hacer JARVIS y con qué restricciones. Sirve de referencia para
implementar cada versión, para escribir sus tests y para quien revise el proyecto como portafolio.
Las decisiones de diseño (el *cómo*) están en los ADR de [`docs/adr/`](adr/).

### 1.2 Alcance

JARVIS es un asistente personal con IA que ayuda a una persona a organizar su día: consulta sus
reuniones, le avisa de los correos de sus clientes, le envía un resumen diario y conversa con ella por consola y por Telegram, por escrito o
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
| Pendiente | Algo por hacer sin hora fija, con fecha límite opcional (a diferencia de un recordatorio, no avisa a una hora). |
| Memoria a largo plazo | Datos duraderos sobre el usuario que JARVIS conserva entre conversaciones hasta que el usuario los borra. |
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

### v0.9: pendientes y memoria a largo plazo

- **RF-41.** El usuario agrega, lista, completa y borra pendientes en lenguaje natural, con fecha
  límite opcional; los atrasados se marcan como tales.
- **RF-42.** El resumen diario incluye los pendientes que vencen ese día o están atrasados.
- **RF-43.** JARVIS guarda por iniciativa propia los datos duraderos que el usuario le cuenta
  (personas, preferencias, rutinas, trabajo), avisándole cuando lo hace, y los usa en futuras
  conversaciones; también los olvida cuando el usuario lo pide o cuando dejan de ser ciertos.
- **RF-44.** `/memoria` muestra todo lo que JARVIS recuerda, sin consultar la IA.
- **RF-45.** `jarvis estado` muestra cuántos pendientes y datos de memoria hay (sin su texto).

### v0.10: "Hey JARVIS" en el PC

- **RF-46.** Con `JARVIS_PALABRA_ACTIVACION=si`, JARVIS en segundo plano escucha el micrófono del PC
  y, al oír "Hey JARVIS", suena un tono, graba el pedido hasta que el usuario se calla (máximo 15 s),
  lo transcribe y responde en voz alta por los parlantes.
- **RF-47.** Las conversaciones por voz en el PC usan las mismas tools, memoria, pendientes y
  recordatorios que Telegram, en conversaciones propias; las confirmaciones se preguntan en voz alta
  y se responden "sí" o "no" de viva voz (sin respuesta, se cancela).
- **RF-48.** Si no se oye nada o no se entiende, JARVIS lo dice en voz alta; si falta algo (voz,
  transcripción, modelos, micrófono), el resto de JARVIS sigue funcionando y queda en el registro.
- **RF-49.** `jarvis escuchar` prueba "Hey JARVIS" en primer plano mostrando lo que pasa;
  `preparar-voz` descarga sus modelos; `JARVIS_ACTIVACION_UMBRAL` ajusta la sensibilidad y `estado`
  muestra si está activo.

### v0.10.2: voz de Azure

- **RF-50.** Con `JARVIS_RESPUESTA_VOZ=azure`, las respuestas habladas (Telegram y "Hey JARVIS") usan
  una voz neuronal de Azure AI Speech (`JARVIS_AZURE_VOZ`, por defecto `es-CO-SalomeNeural`).
- **RF-51.** Si Azure falla (red, clave, límite de uso), responde la voz de Piper si está
  disponible; si tampoco, la respuesta llega por escrito. Una clave o región rechazadas, o el límite
  agotado, se explican una vez.
- **RF-52.** `jarvis probar-voz "texto"` dice el texto por los parlantes con la voz configurada (con
  Azure, sin respaldo, para ver sus errores); `estado` muestra el motor, la voz y el respaldo.

### v0.11: búsqueda en internet

- **RF-53.** JARVIS busca en internet cuando la respuesta depende de información actual (clima,
  noticias, precios, horarios), con un máximo de 5 búsquedas por mensaje; no busca lo que ya está en
  el calendario, los recordatorios, los pendientes o la memoria.
- **RF-54.** Si el usuario comparte un enlace, JARVIS puede leerlo y resumirlo; solo abre enlaces que
  aparecen en la conversación.
- **RF-55.** En Telegram, las respuestas que usaron internet terminan con sus fuentes (título y
  enlace); por voz no se leen enlaces, pero se dice de dónde sale el dato.
- **RF-56.** La ubicación configurada (`JARVIS_CIUDAD`, `JARVIS_PAIS`) mejora las búsquedas locales
  (va en las instrucciones del modelo); `JARVIS_BUSQUEDA=no` las desactiva y `estado` muestra si están activas.

### v0.12: escribir en el calendario

- **RF-57.** El usuario agenda eventos en lenguaje natural (título, inicio, duración, lugar y notas
  opcionales); no se aceptan horas pasadas ni a más de dos años.
- **RF-58.** El usuario mueve o cancela eventos que organiza él; las invitaciones de otras personas no
  se tocan. En eventos recurrentes, el cambio afecta solo esa ocasión.
- **RF-59.** Agendar, mover o cancelar siempre pide confirmación mostrando el detalle y los choques de
  horario; nunca se invita ni se avisa a otras personas.
- **RF-60.** Con la autorización anterior (solo lectura), JARVIS sigue leyendo el calendario y explica
  cómo dar el permiso nuevo al intentar escribir; `estado` lo indica.

### v0.13: avisos proactivos

- **RF-61.** JARVIS avisa por Telegram antes de cada reunión con hora (`JARVIS_AVISO_REUNION`, 10
  minutos por defecto; 0 lo apaga), con horario, participantes, lugar y enlace de la videollamada.
- **RF-62.** Cada reunión se avisa una sola vez, aunque JARVIS se reinicie; si se mueve, se avisa a la
  hora nueva. No se avisa tarde (si la reunión ya empezó) ni de eventos de día completo.
- **RF-63.** De domingo a jueves, a partir de `JARVIS_VISTAZO_MANANA` (20:00 por defecto; `no` lo
  apaga), JARVIS envía una vez un vistazo a mañana: reuniones y pendientes que vencen.
- **RF-64.** `estado` muestra qué avisos están activos.

### v0.14: correos de clientes

- **RF-65.** El usuario arma, hablando con JARVIS, una lista de contactos vigilados (direcciones o
  dominios enteros) y la ve con `/clientes`; agregar o quitar no pide confirmación.
- **RF-66.** Cuando llega un correo de un contacto vigilado, JARVIS avisa por Telegram con remitente,
  asunto y un fragmento, revisando cada `JARVIS_CORREO_MINUTOS` (2 por defecto; `JARVIS_CORREO=no` lo apaga).
- **RF-67.** Cada correo se avisa una sola vez, aunque JARVIS se reinicie; nunca se avisa de correos
  anteriores a la activación de los avisos o a la incorporación del contacto, ni de más de 24 horas atrás.
- **RF-68.** El usuario pide buscar y leer sus correos ("¿qué me escribió Laura esta semana?") y
  JARVIS los resume; lo que dice un correo se trata como información, nunca como instrucciones.
- **RF-69.** Sin el permiso de lectura de Gmail, JARVIS sigue funcionando, pausa los avisos de correo
  y `estado` explica cómo darlo.

### v0.15: gastar menos y medir el gasto

- **RF-70.** Cada respuesta de Claude (chat, voz, consola y comentario del resumen) registra sus tokens
  de entrada, de caché y de salida, y sus búsquedas; `/gasto` y `estado` muestran el costo estimado de
  hoy, los últimos 7 días y el mes, y el registro, el de cada respuesta.
- **RF-71.** El clima de la ciudad configurada (`JARVIS_CIUDAD`, `JARVIS_PAIS`) se consulta en Open-Meteo
  con la tool `get_clima` (ahora y hasta 7 días); el modelo la prefiere a la búsqueda en internet.
- **RF-72.** El resumen de la mañana y el vistazo a mañana incluyen una línea de clima, armada en código;
  sin clima disponible, se envían sin ella.
- **RF-73.** `/hoy`, `/pendientes`, `/recordatorios`, `/clima` y `/gasto` se responden en código, sin
  consultar a Claude, y aparecen en el menú de Telegram y en `/ayuda`.

## 4. Requisitos no funcionales

### 4.1 Seguridad

- **RNF-01.** Ninguna credencial (API keys, tokens, secretos) está en el código ni en el repositorio:
  van en `.env` o en `~/.config/jarvis/`, ignorados por git. `.env.example` lista los nombres sin valores.
- **RNF-02.** Permiso mínimo en cada servicio: `calendar.events` (ver y editar eventos, no
  calendarios); `gmail.readonly` (leer, sin enviar, borrar ni modificar) solo para los avisos de
  correo; `gmail.send` solo si el resumen va por Gmail.
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
- **RNF-08d.** Con Piper, las respuestas con voz se generan en el PC, en memoria. Con Azure (opcional),
  el texto de las respuestas habladas se envía a Microsoft por HTTPS verificado con el almacén del
  sistema; la clave va en `.env` y nunca aparece en registros ni errores, y los registros no guardan
  el texto.
- **RNF-08e.** Los datos de la memoria a largo plazo se guardan solo en el equipo y no caducan:
  se borran cuando el usuario lo pide. No se guardan números largos (tarjetas, cuentas, documentos).
  Los pendientes hechos se borran a los 30 días. Los registros no contienen el texto de ninguno.
- **RNF-08f.** La memoria tiene un tope (200 datos de hasta 300 caracteres) y entra en el system prompt
  solo al empezar una conversación, sin editar el historial de la conversación en curso.
- **RNF-08g.** "Hey JARVIS" está apagado por defecto. El audio del micrófono se analiza en memoria
  en bloques de 80 ms y se descarta; solo el pedido que sigue a la palabra de activación se graba,
  en memoria, para transcribirlo en el PC. Nada se escribe en disco ni sale del equipo, y los
  registros solo anotan activaciones y duraciones. Mientras JARVIS habla, el micrófono se ignora.
- **RNF-08h.** Los correos no se guardan en el equipo: la lista de contactos vigilados y los IDs de
  los correos ya avisados (30 días) son lo único que queda en `jarvis.db`. Los registros no contienen
  remitentes, asuntos ni texto de correos.

### 4.3 Fiabilidad y rapidez

- **RNF-09f.** Las llamadas a Claude usan la caché de prompts (prefijo automático, 5 minutos): tools,
  system prompt e historial se leen de la caché sin editar el historial. Lo que se puede resolver en
  código (avisos, comandos directos, clima) no usa IA.
- **RNF-09g.** El registro de consumo guarda solo números (tokens, búsquedas, modelo y canal), nunca
  contenido, y se borra a los 400 días. A Open-Meteo solo se envían la ciudad y sus coordenadas; el
  pronóstico se guarda en memoria como mucho 30 minutos.
- **RNF-09e.** Las conexiones HTTPS con Telegram se mantienen abiertas y se reutilizan (una por hilo),
  para no repetir el saludo TCP + TLS en cada llamada; si Telegram cerró una conexión inactiva, se
  reintenta una sola vez con una nueva, y nunca tras un tiempo agotado (no se duplican mensajes). El
  registro anota cuánto tarda cada llamada (método y segundos, nunca el contenido ni el token).
- **RNF-09d.** Los avisos se arman en código, sin IA (instantáneos y sin costo); el calendario se
  consulta como mucho cada 5 minutos y los avisos enviados se registran en `jarvis.db` (sin títulos)
  durante 30 días.
- **RNF-09c.** Las búsquedas usan las tools de servidor de Anthropic (sin otro proveedor ni clave): las
  consultas pasan por Anthropic, que ya recibe la conversación. Cada búsqueda se paga aparte, por eso
  hay un tope por mensaje y el registro anota cuántas se hicieron (nunca qué se buscó).

- **RNF-09b.** Las respuestas de chat y voz piden a Claude un esfuerzo bajo por defecto
  (`JARVIS_ESFUERZO`); Whisper y Piper se cargan al arrancar, y la transcripción usa búsqueda
  simple. El registro anota la duración de cada etapa (transcripción, IA, voz), nunca su contenido.

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
- Enviar mensajes reales a terceros: `enviar_mensaje` sigue simulada; JARVIS no responde correos.
- Invitar a otras personas a los eventos, eventos de día completo o recurrentes creados por JARVIS.
- Imágenes o archivos en el chat; otras voces en la nube (por ejemplo, ElevenLabs).
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
| RF-41 a RF-45 | `tasks.py`, `long_term_memory.py`, `tools/pendientes.py`, `tools/memoria.py`, `prompts.py`, `chat.py`, `summary.py`, `status.py` | `test_tasks.py`, `test_long_term_memory.py`, `test_chat.py`, `test_status.py` |
| RF-46 a RF-49 | `wake_word.py`, `pc_voice.py`, `assistant.py`, `prompts.py`, `telegram/app.py`, `cli.py`, `status.py` | `test_pc_voice.py`, `test_status.py` |
| RF-50 a RF-52 | `azure_speech.py`, `speech.py`, `config.py`, `cli.py`, `wake_word.py` | `test_azure_speech.py` |
| RF-53 a RF-56 | `tools/internet.py`, `tools/registry.py`, `agent.py`, `chat.py`, `prompts.py`, `config.py`, `status.py` | `test_internet.py` |
| RF-57 a RF-60 | `tools/calendario.py`, `agenda/`, `google_auth.py`, `tools/registry.py`, `status.py`, `cli.py` | `test_calendar_writing.py` |
| RF-61 a RF-64 | `proactive.py`, `agenda/google.py`, `config.py`, `telegram/app.py`, `status.py` | `test_proactive.py` |
| RF-65 a RF-69 | `mail_watch.py`, `gmail_reader.py`, `tools/correo.py`, `proactive.py`, `chat.py`, `prompts.py`, `google_auth.py`, `status.py` | `test_mail.py` |
| RF-70 a RF-73 | `usage.py`, `agent.py`, `weather.py`, `tools/clima.py`, `quick.py`, `chat.py`, `summary.py`, `proactive.py`, `status.py` | `test_usage.py`, `test_weather.py` |
| RNF-01 a RNF-08 | `config.py`, `google_auth.py`, `telegram/client.py`, logs | `test_config.py`, `test_google_auth.py`, `test_telegram.py` |
