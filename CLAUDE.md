# JARVIS — Asistente personal con IA

## Qué es
JARVIS es un asistente personal que me ayuda a organizar mi día: me recuerda reuniones,
me avisa de mensajes de clientes y ejecuta tareas simples por mí. Es un proyecto de
portafolio y un posible producto, así que el código debe ser limpio, documentado y testeado.

El proyecto crece por versiones pequeñas. Implementa SOLO la versión que se pida en cada sesión.

## Roadmap
- **v0.1 (hecha):** loop del agente por consola con tools simuladas (`get_reuniones`, `enviar_mensaje`),
  historial en memoria durante la sesión. Ver `docs/adr/001-loop-propio-sin-framework.md`.
- **v0.2 (hecha):** Google Calendar real (solo lectura) con OAuth de escritorio, fuentes de
  calendario intercambiables (`JARVIS_CALENDAR=sample|google`) y tests en GitHub Actions.
  Ver `docs/adr/002-google-calendar-oauth-escritorio.md`.
- **v0.3 (hecha):** resumen diario por Gmail (lunes a viernes, Programador de tareas de Windows),
  con comentario de Claude y agenda generada en código; SQLite para no duplicar envíos.
  Ver `docs/adr/003-resumen-diario-gmail.md`.
- **v0.4 (hecha, sustituida):** chat por WhatsApp (Meta Cloud API). Retirada en la v0.5; ver
  `docs/adr/004-whatsapp-cloud-api-local.md`.
- **v0.5 (hecha):** Telegram como canal único: chat con botones de confirmación (long polling, sin
  puertos abiertos) y resumen diario por Telegram (`JARVIS_RESUMEN_CANAL`, Gmail como alternativa).
  Lógica del chat independiente del canal (`chat.py`). Ver `docs/adr/005-telegram-como-canal.md`.
  v0.5.1: HTTPS verificado con el almacén de certificados del sistema (`truststore`), para equipos
  con antivirus o proxy que inspeccionan el tráfico. Ver `docs/adr/006-verificacion-tls-sistema.md`.
- **v0.6 (hecha):** JARVIS en segundo plano al iniciar sesión en Windows (`programar-telegram`),
  comando `estado`, registros rotativos y canal visible en `resumen --dry-run`.
  Ver `docs/adr/007-telegram-en-segundo-plano.md`. v0.6.1: `estado` encuentra PowerShell aunque no
  esté en el PATH y muestra la última ejecución y el resultado de cada tarea.
- **v0.7 (hecha):** recordatorios (crear, listar, cancelar) entregados por Telegram con botones
  [Posponer 10 min] [Hecho]. Ver `docs/adr/008-recordatorios.md`.
- **v0.8 (hecha):** notas de voz en Telegram, transcritas en el PC con Whisper (`faster-whisper`,
  grupo opcional `voz`); modelo descargado con `preparar-voz`; interfaz `Transcriber` para cambiar
  de motor. Ver `docs/adr/009-notas-de-voz-whisper-local.md`.
- **v0.8.1 (hecha):** respuestas con voz generadas en el PC con Piper (interfaz `Speaker`), en espejo
  por defecto y configurables con `/voz`; el texto llega siempre. Ver `docs/adr/010-respuestas-con-voz-piper.md`.
- **v0.9 (hecha):** pendientes (con fecha límite, en el resumen diario) y memoria a largo plazo:
  datos del usuario guardados por iniciativa del modelo, añadidos al system prompt de cada
  conversación nueva y visibles con `/memoria`. Ver `docs/adr/011-pendientes-y-memoria-a-largo-plazo.md`.
- **v0.10 (hecha):** "Hey JARVIS" en el PC con openWakeWord (interfaz `WakeWordDetector`): tono,
  grabación hasta el silencio, Whisper, chat por un canal propio (`PcVoiceChannel`) y respuesta por
  los parlantes con Piper; dentro del proceso en segundo plano, apagado por defecto
  (`JARVIS_PALABRA_ACTIVACION`), y `jarvis escuchar` para probarlo. Ver `docs/adr/012-hey-jarvis-en-el-pc.md`.
  v0.10.1: respuestas más rápidas: esfuerzo bajo de Claude en chat y voz (`JARVIS_ESFUERZO`),
  Whisper con búsqueda simple, Whisper y Piper precargados al arrancar, cierre del pedido tras
  0,7 s de silencio y tiempos de cada etapa en el registro. Ver `docs/adr/013-respuestas-rapidas.md`.
  v0.10.2: voz de Azure AI Speech (`JARVIS_RESPUESTA_VOZ=azure`, Salomé por defecto) vía API REST,
  con Piper de respaldo, y `jarvis probar-voz`. Ver `docs/adr/014-voz-de-azure.md`.
- **v0.11 (hecha):** búsqueda en internet y lectura de enlaces con las tools de servidor de Anthropic
  (`web_search`, `web_fetch`; tope de 5 búsquedas por mensaje), ubicación del usuario
  (`JARVIS_CIUDAD`, `JARVIS_PAIS`) y fuentes al final del texto en Telegram.
  Ver `docs/adr/015-busqueda-en-internet.md`. v0.11.1: el registro guarda el motivo que da la API
  cuando rechaza una petición (tipo, código y mensaje recortado; nunca el contenido). v0.11.2: la
  ubicación ya no va en `user_location` de la búsqueda (la API rechazaba el país CO), solo en el prompt.
- **v0.12 (hecha):** escribir en el calendario: `crear_evento`, `mover_evento` y `cancelar_evento`,
  siempre con confirmación (detalle y choques), solo sobre eventos que organiza el usuario y sin
  invitar ni avisar a nadie; permiso `calendar.events`. Ver `docs/adr/016-escribir-en-el-calendario.md`.
- **v0.13 (hecha):** avisos proactivos por Telegram, armados en código: antes de cada reunión
  (`JARVIS_AVISO_REUNION`, con enlace de la videollamada) y vistazo a mañana de domingo a jueves
  (`JARVIS_VISTAZO_MANANA`); sin repetir avisos aunque JARVIS se reinicie.
  Ver `docs/adr/017-avisos-proactivos.md`.
- **v0.14 (hecha):** avisos de correos de clientes por Telegram: lista de contactos vigilados
  (direcciones o dominios) manejada hablando con JARVIS y visible con `/clientes`, revisión cada 2
  minutos (`JARVIS_CORREO_MINUTOS`), sin avisar correos viejos ni repetidos; buscar y leer correos a
  pedido; permiso `gmail.readonly`. Ver `docs/adr/018-avisos-de-correo.md`.
  v0.14.1: conexiones HTTPS con Telegram reutilizadas (una por hilo, `http.client`, reintento único
  si Telegram cerró una inactiva) y tiempo de cada llamada en el registro. Ver `docs/adr/019-conexion-telegram-reutilizada.md`.
- **v0.15 (hecha):** gastar menos y medir: prompt caching automático, tokens y costo estimado por
  respuesta (`api_usage`, `/gasto`, `estado`), clima con Open-Meteo (`get_clima`, también en el resumen
  y el vistazo a mañana) y comandos sin IA (`/hoy`, `/pendientes`, `/recordatorios`, `/clima`).
  Ver `docs/adr/020-gastar-menos-y-medir.md` y la visión en `docs/vision.md`.
- **v0.16 (hecha):** JARVIS en el iPhone: API HTTP propia (librería estándar) que solo escucha en
  127.0.0.1 y se publica con `tailscale serve`, con clave (`jarvis api-clave`, solo su huella en el
  equipo); app web instalable (PWA: Hoy y Chat), Atajo de Siri y widget de Scriptable. Canal
  `ApiChannel` sobre `ChatService`. Ver `docs/adr/021-api-por-tailscale.md`.
- **Siguiente:** a decidir con el usuario (notificaciones push en la PWA, módulo de dinero o de movilidad).
- Después: módulos de dinero o movilidad; app nativa de iOS cuando haya Mac; alojamiento (servidor,
  nube) según cómo escale.
- Futuro: Alexa, llamadas telefónicas, multiusuario.

Los requisitos de cada versión están en `docs/srs.md` (actualizarlo al cerrar cada versión).

## Stack
- Python 3.12
- SDK oficial de Anthropic (`anthropic`), con tool use manual (loop propio, no frameworks de agentes)
- Google Calendar API y Gmail API (`google-api-python-client`, `google-auth-oauthlib`):
  `calendar.events`, `gmail.readonly` (avisos de clientes) y, solo si el resumen va por Gmail, `gmail.send`
- Modelo configurable por variable de entorno `JARVIS_MODEL` (default: `claude-sonnet-5-5`)
- API de bots de Telegram vía `http.client` con conexiones reutilizadas (long polling, sin webhook),
  con `truststore` para verificar HTTPS con el almacén de certificados del sistema
- `faster-whisper`, `piper-tts`, `openwakeword` y `sounddevice` (grupo opcional `voz`) para entender,
  responder y escuchar "Hey JARVIS" en el PC
- Azure AI Speech (API REST vía `urllib` + `truststore`), opcional, para una voz más natural
- Open-Meteo (API REST gratuita, sin clave, vía `urllib` + `truststore`) para el clima
- API para el iPhone con `http.server` (librería estándar), publicada con Tailscale (`tailscale serve`);
  app web (PWA) en HTML, CSS y JS propios, sin frameworks ni CDNs
- SQLite para persistencia local (más adelante Postgres)
- `python-dotenv` para configuración, `pytest` para tests
- Gestión de dependencias con `uv` y `pyproject.toml`

## Estructura
```
jarvis/
├── src/jarvis/
│   ├── agent.py        # loop del agente (con caché de prompts y suma de tokens)
│   ├── usage.py        # SQLite: tokens y costo estimado por respuesta (/gasto)
│   ├── weather.py      # clima con Open-Meteo (pronóstico en memoria 30 min)
│   ├── quick.py        # comandos sin IA: /hoy, /pendientes, /recordatorios, /clima, /gasto
│   ├── dates.py        # fechas en español
│   ├── config.py       # carga de .env y settings
│   ├── prompts.py      # system prompts (consola y chat)
│   ├── agenda/         # fuentes de calendario
│   │   ├── base.py     # Meeting, CalendarSource (interfaz) y errores
│   │   ├── sample.py   # datos de ejemplo
│   │   └── google.py   # Google Calendar (leer, agendar, mover y cancelar)
│   ├── google_auth.py  # OAuth de escritorio con Google, token y permisos
│   ├── notify/         # canales de envío: Notifier (interfaz), consola, Gmail y Telegram
│   ├── summary.py      # resumen diario: comentario de Claude, agenda, envío y reintentos
│   ├── summary_cli.py  # comandos resumen, programar-resumen y quitar-resumen
│   ├── scheduler.py    # Programador de tareas de Windows: resumen y Telegram (y líneas de cron)
│   ├── status.py       # comando `jarvis estado`
│   ├── logs.py         # registros rotativos (solo resultados, nunca contenido)
│   ├── storage.py      # SQLite: registro de resúmenes enviados
│   ├── memory.py       # SQLite: conversaciones del chat, retención, duplicados y preferencias (/voz)
│   ├── reminders.py    # SQLite: recordatorios (crear, cancelar, posponer, vencidos)
│   ├── reminder_delivery.py # entrega de recordatorios por el chat y sus botones
│   ├── proactive.py    # avisos por iniciativa de JARVIS: reuniones, vistazo a mañana y correos
│   ├── mail_watch.py   # SQLite: contactos vigilados (direcciones o dominios de clientes)
│   ├── gmail_reader.py # Gmail de solo lectura: buscar y leer correos
│   ├── tasks.py        # SQLite: pendientes (con fecha límite opcional)
│   ├── long_term_memory.py # SQLite: memoria a largo plazo (datos del usuario, sin caducidad)
│   ├── confirmation.py # interpretación de respuestas s/n, común a todos los canales
│   ├── voice.py        # notas de voz: Transcriber (interfaz), Whisper local y descarga del modelo
│   ├── speech.py       # respuestas con voz: Speaker (interfaz), Piper local, OGG/Opus y descarga
│   ├── azure_speech.py # voz de Azure AI Speech (API REST), con Piper de respaldo
│   ├── wake_word.py    # "Hey JARVIS": WakeWordDetector (interfaz), openWakeWord y descarga de modelos
│   ├── pc_voice.py     # voz en el PC: canal de chat por parlantes, grabación del pedido y escucha
│   ├── assistant.py    # piezas comunes de los canales: almacenes, agente, Whisper y Piper (una vez)
│   ├── chat.py         # chat independiente del canal: agente, confirmaciones, comandos, memoria
│   ├── telegram/       # canal de Telegram
│   │   ├── client.py   # API de bots: conexiones reutilizadas, enviar, botones, getUpdates, errores
│   │   ├── bot.py      # ChatChannel de Telegram, lectura de mensajes (long polling), vinculación
│   │   └── app.py      # comandos telegram, telegram-vincular, programar-telegram y quitar-telegram
│   ├── tools/          # una tool por archivo + registro central
│   │   ├── __init__.py # tools integradas y build_registry()
│   │   ├── registry.py # registro: nombre -> (schema, función), confirmación, errores y tools de servidor
│   │   ├── recordatorios.py # crear_recordatorio, listar_recordatorios, cancelar_recordatorio
│   │   ├── pendientes.py   # agregar, listar, completar y borrar pendientes
│   │   ├── memoria.py      # recordar_dato, listar_datos, olvidar_dato
│   │   ├── internet.py     # web_search y web_fetch (tools de servidor de Anthropic)
│   │   ├── calendario.py   # crear_evento, mover_evento, cancelar_evento (con confirmación)
│   │   ├── correo.py       # contactos vigilados, buscar_correos y leer_correo (solo lectura)
│   │   ├── clima.py        # get_clima (Open-Meteo, solo lectura)
│   │   └── ...         # reuniones.py, mensajes.py
│   ├── api/            # API para el iPhone (apagada por defecto)
│   │   ├── server.py   # servidor HTTP: rutas, clave, cabeceras de seguridad, archivos de la app
│   │   ├── channel.py  # ApiChannel (canal de chat) y ChatBridge (pedido HTTP ↔ turno del chat)
│   │   ├── auth.py     # clave: generación, huella, comprobación y pausa tras fallos
│   │   ├── icons.py    # íconos PNG dibujados en código
│   │   ├── app.py      # arranque dentro del proceso de Telegram y comando api-clave
│   │   └── static/     # app web (PWA): index.html, app.js, app.css, sw.js, manifest
│   └── cli.py          # punto de entrada por consola (chat de consola y subcomandos)
├── clients/scriptable/  # widget del iPhone (Scriptable)
├── tests/
├── .github/workflows/  # CI: pytest en cada PR y push a main
├── docs/
│   ├── vision.md       # visión: qué hace la IA y qué el código, módulos y orden
│   ├── srs.md          # requisitos (RF / RNF por versión)
│   └── adr/            # decisiones de arquitectura (una por archivo)
├── .env.example
└── pyproject.toml
```

## Convenciones
- Código, nombres de funciones y variables en inglés. Comentarios, docs y mensajes al usuario en español.
- Type hints en todo. Funciones pequeñas y con una sola responsabilidad.
- Cada tool se define con: nombre, descripción clara para el modelo, JSON schema de entrada y función Python.
  Agregar una tool nueva no debe requerir tocar `agent.py`.
- El loop del agente tiene un límite máximo de iteraciones para evitar ciclos infinitos.
- Errores de una tool se devuelven al modelo como resultado con `is_error`, no rompen el programa.
- IA solo donde aporta (ver `docs/vision.md`): lo que se resuelve en código (avisos, comandos directos,
  datos de APIs) no llama a Claude. Toda llamada a Claude usa la caché y registra su consumo.
- Cada funcionalidad nueva viene con tests. Las llamadas a APIs externas (Anthropic, Google, Telegram, Open-Meteo, Whisper, Piper, Azure) y al
  sistema (Programador de tareas) se mockean en los tests. Ningún test escribe en `~/.config/jarvis`
  (`tests/conftest.py` lo redirige a una carpeta temporal).
- Al terminar una versión: actualizar este archivo (roadmap) y agregar un ADR si hubo una decisión relevante.

## Seguridad (obligatorio)
- Nunca escribir keys, tokens ni credenciales en el código ni en commits. Todo va en `.env` (ignorado por git).
- Nunca desactivar la verificación de certificados HTTPS. Las llamadas HTTP propias usan `truststore`
  (almacén del sistema), como el SDK de Anthropic.
- Credenciales y tokens de OAuth viven fuera del repo (por defecto `~/.config/jarvis/`). Pedir siempre
  el permiso mínimo (hoy `calendar.events`, `gmail.readonly` para los avisos de clientes y, solo con
  el resumen por Gmail, `gmail.send`).
- Escribir en el calendario solo sobre eventos que organiza el usuario, siempre con confirmación, y
  nunca invitar ni avisar a otras personas (`sendUpdates="none"`).
- Las acciones programadas (como el resumen diario) no son tools: el destinatario es fijo por
  configuración y el modelo no puede cambiarlo ni disparar envíos.
- El chat de Telegram solo atiende `TELEGRAM_OWNER_ID` en chat privado y no arranca sin él (long
  polling). El token del bot nunca debe aparecer en logs ni en mensajes de error.
- JARVIS no queda expuesto en la red: la API del iPhone (apagada por defecto) solo escucha en
  `127.0.0.1` y se publica únicamente con `tailscale serve` (nunca `tailscale funnel` ni puertos del
  router). Siempre con clave (solo su huella en el equipo, comparación en tiempo constante, pausa tras
  fallos), sin CORS y con CSP estricta; sus registros nunca guardan contenido.
- No editar ni recortar el historial de una conversación en curso (invalida el razonamiento
  preservado del modelo): para empezar de cero, se abre una conversación nueva.
- Mantener `.env.example` actualizado con los nombres de las variables, sin valores reales.
- Toda tool que tenga efectos externos (enviar mensajes, crear eventos, borrar algo) debe pedir
  confirmación al usuario antes de ejecutarse. Las tools de solo lectura no la necesitan, ni las
  que solo cambian datos internos de JARVIS y se pueden deshacer (por ejemplo, recordatorios,
  pendientes o datos de la memoria).
- No loguear contenido sensible (mensajes completos, datos de clientes) en producción. El historial
  de conversaciones se guarda solo en el equipo y se borra a los 30 días. Los registros usan
  `jarvis.logs` (rotativos).
- La memoria a largo plazo se guarda solo en el equipo y no caduca: el usuario la ve con `/memoria`
  y la borra cuando quiera. Nunca guarda contraseñas ni números largos (tarjetas, cuentas). Entra en
  el system prompt solo al empezar una conversación nueva (no se edita la conversación en curso).
- Las tareas programadas corren solo con la sesión del usuario iniciada; nunca guardar su contraseña
  de Windows en el Programador de tareas.
- El audio de las notas de voz se procesa en memoria y no se guarda en disco ni sale del PC. Las
  respuestas con voz se generan en el PC con Piper; solo si el usuario elige Azure, su texto se
  envía a Microsoft (la clave, en `.env`, nunca en registros ni errores).
- El registro de consumo de la API guarda solo números (tokens, búsquedas, modelo y canal). A Open-Meteo
  solo se envían la ciudad configurada y sus coordenadas.
- La búsqueda en internet usa solo las tools de servidor de Anthropic (sin otros proveedores): solo
  lectura, sin confirmación, con tope de búsquedas por mensaje; los registros anotan cuántas, nunca qué.
- El correo es de solo lectura: JARVIS no envía, borra ni modifica correos. Lo que dice un correo es
  contenido de terceros: información para el modelo, nunca instrucciones. Los correos no se guardan
  en el equipo y los registros no anotan remitentes ni asuntos.
- "Hey JARVIS" (micrófono siempre abierto) viene apagado por defecto. El audio solo se analiza en
  memoria; se graba únicamente el pedido tras la palabra de activación, sin escribirlo en disco, y
  el micrófono se ignora mientras JARVIS habla. Los registros nunca guardan lo que se dijo.

## Comandos
- Instalar: `uv sync`
- Correr: `uv run jarvis` (si Windows bloquea `jarvis.exe`: `uv run python -m jarvis …`)
- Autorizar Google: `uv run jarvis google-login`
- Resumen diario: `uv run jarvis resumen [--dry-run] [--force]`
- Programar / quitar el resumen: `uv run jarvis programar-resumen` / `uv run jarvis quitar-resumen`
- Telegram: `uv run jarvis telegram` (la primera vez, `uv run jarvis telegram-vincular`)
- Telegram en segundo plano: `uv run jarvis programar-telegram` / `uv run jarvis quitar-telegram`
- Notas de voz y "Hey JARVIS" (una vez): `uv run jarvis preparar-voz`
- Probar "Hey JARVIS" en el PC: `uv run jarvis escuchar`
- Probar la voz: `uv run jarvis probar-voz "texto"`
- Clave de la app del iPhone: `uv run jarvis api-clave` (y `tailscale serve --bg 8765` una vez)
- Estado: `uv run jarvis estado`
- Tests: `uv run pytest` (en la CI, sin el grupo de voz)
