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
- **Siguiente (por definir):** por ejemplo, avisos de mensajes de clientes desde otra fuente
  (Gmail, CRM) o servidor en la nube.
- Futuro: Alexa, llamadas telefónicas, multiusuario.

Los requisitos de cada versión están en `docs/srs.md` (actualizarlo al cerrar cada versión).

## Stack
- Python 3.12
- SDK oficial de Anthropic (`anthropic`), con tool use manual (loop propio, no frameworks de agentes)
- Google Calendar API y Gmail API (`google-api-python-client`, `google-auth-oauthlib`):
  `calendar.readonly` y, solo si el resumen va por Gmail, `gmail.send`
- Modelo configurable por variable de entorno `JARVIS_MODEL` (default: `claude-sonnet-5-5`)
- API de bots de Telegram vía `urllib` (long polling, sin webhook), con `truststore` para verificar
  HTTPS con el almacén de certificados del sistema
- SQLite para persistencia local (más adelante Postgres)
- `python-dotenv` para configuración, `pytest` para tests
- Gestión de dependencias con `uv` y `pyproject.toml`

## Estructura
```
jarvis/
├── src/jarvis/
│   ├── agent.py        # loop del agente
│   ├── config.py       # carga de .env y settings
│   ├── prompts.py      # system prompts (consola y chat)
│   ├── agenda/         # fuentes de calendario
│   │   ├── base.py     # Meeting, CalendarSource (interfaz) y errores
│   │   ├── sample.py   # datos de ejemplo
│   │   └── google.py   # Google Calendar (lectura)
│   ├── google_auth.py  # OAuth de escritorio con Google, token y permisos
│   ├── notify/         # canales de envío: Notifier (interfaz), consola, Gmail y Telegram
│   ├── summary.py      # resumen diario: comentario de Claude, agenda, envío y reintentos
│   ├── summary_cli.py  # comandos resumen, programar-resumen y quitar-resumen
│   ├── scheduler.py    # Programador de tareas de Windows: resumen y Telegram (y líneas de cron)
│   ├── status.py       # comando `jarvis estado`
│   ├── logs.py         # registros rotativos (solo resultados, nunca contenido)
│   ├── storage.py      # SQLite: registro de resúmenes enviados
│   ├── memory.py       # SQLite: conversaciones persistentes del chat, retención y duplicados
│   ├── confirmation.py # interpretación de respuestas s/n, común a todos los canales
│   ├── chat.py         # chat independiente del canal: agente, confirmaciones, comandos, memoria
│   ├── telegram/       # canal de Telegram
│   │   ├── client.py   # API de bots (urllib): enviar, botones, getUpdates, errores
│   │   ├── bot.py      # ChatChannel de Telegram, lectura de mensajes (long polling), vinculación
│   │   └── app.py      # comandos telegram, telegram-vincular, programar-telegram y quitar-telegram
│   ├── tools/          # una tool por archivo + registro central
│   │   ├── __init__.py # tools integradas y build_registry()
│   │   ├── registry.py # registro: nombre -> (schema, función), confirmación y errores
│   │   └── ...
│   └── cli.py          # punto de entrada por consola (chat de consola y subcomandos)
├── tests/
├── .github/workflows/  # CI: pytest en cada PR y push a main
├── docs/
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
- Cada funcionalidad nueva viene con tests. Las llamadas a APIs externas (Anthropic, Google, Telegram) y al
  sistema (Programador de tareas) se mockean en los tests.
- Al terminar una versión: actualizar este archivo (roadmap) y agregar un ADR si hubo una decisión relevante.

## Seguridad (obligatorio)
- Nunca escribir keys, tokens ni credenciales en el código ni en commits. Todo va en `.env` (ignorado por git).
- Nunca desactivar la verificación de certificados HTTPS. Las llamadas HTTP propias usan `truststore`
  (almacén del sistema), como el SDK de Anthropic.
- Credenciales y tokens de OAuth viven fuera del repo (por defecto `~/.config/jarvis/`). Pedir siempre
  el permiso mínimo (hoy `calendar.readonly` y, solo con el resumen por Gmail, `gmail.send`).
- Las acciones programadas (como el resumen diario) no son tools: el destinatario es fijo por
  configuración y el modelo no puede cambiarlo ni disparar envíos.
- El chat de Telegram solo atiende `TELEGRAM_OWNER_ID` en chat privado y no arranca sin él. JARVIS no
  abre puertos (long polling). El token del bot nunca debe aparecer en logs ni en mensajes de error.
- No editar ni recortar el historial de una conversación en curso (invalida el razonamiento
  preservado del modelo): para empezar de cero, se abre una conversación nueva.
- Mantener `.env.example` actualizado con los nombres de las variables, sin valores reales.
- Toda tool que tenga efectos externos (enviar mensajes, crear eventos, borrar algo) debe pedir
  confirmación al usuario antes de ejecutarse. Las tools de solo lectura no la necesitan.
- No loguear contenido sensible (mensajes completos, datos de clientes) en producción. El historial
  de conversaciones se guarda solo en el equipo y se borra a los 30 días. Los registros usan
  `jarvis.logs` (rotativos).
- Las tareas programadas corren solo con la sesión del usuario iniciada; nunca guardar su contraseña
  de Windows en el Programador de tareas.

## Comandos
- Instalar: `uv sync`
- Correr: `uv run jarvis`
- Autorizar Google: `uv run jarvis google-login`
- Resumen diario: `uv run jarvis resumen [--dry-run] [--force]`
- Programar / quitar el resumen: `uv run jarvis programar-resumen` / `uv run jarvis quitar-resumen`
- Telegram: `uv run jarvis telegram` (la primera vez, `uv run jarvis telegram-vincular`)
- Telegram en segundo plano: `uv run jarvis programar-telegram` / `uv run jarvis quitar-telegram`
- Estado: `uv run jarvis estado`
- Tests: `uv run pytest`
