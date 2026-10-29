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
- **v0.3 (siguiente):** tarea programada que envía el resumen del día.
- v0.4: canal de WhatsApp.
- Futuro: Alexa, llamadas telefónicas, multiusuario.

## Stack
- Python 3.12
- SDK oficial de Anthropic (`anthropic`), con tool use manual (loop propio, no frameworks de agentes)
- Google Calendar API (`google-api-python-client`, `google-auth-oauthlib`), permiso de solo lectura
- Modelo configurable por variable de entorno `JARVIS_MODEL` (default: `claude-sonnet-5-5`)
- SQLite para persistencia local (más adelante Postgres)
- `python-dotenv` para configuración, `pytest` para tests
- Gestión de dependencias con `uv` y `pyproject.toml`

## Estructura
```
jarvis/
├── src/jarvis/
│   ├── agent.py        # loop del agente
│   ├── config.py       # carga de .env y settings
│   ├── prompts.py      # system prompt
│   ├── agenda/         # fuentes de calendario
│   │   ├── base.py     # Meeting, CalendarSource (interfaz) y errores
│   │   ├── sample.py   # datos de ejemplo
│   │   ├── google.py   # Google Calendar (lectura)
│   │   └── google_auth.py # OAuth de escritorio y token
│   ├── tools/          # una tool por archivo + registro central
│   │   ├── __init__.py # tools integradas y build_registry()
│   │   ├── registry.py # registro: nombre -> (schema, función), confirmación y errores
│   │   └── ...
│   ├── memory.py       # historial y persistencia (SQLite) — pendiente; en v0.1 el historial vive en Agent
│   └── cli.py          # punto de entrada por consola (chat y google-login)
├── tests/
├── .github/workflows/  # CI: pytest en cada PR y push a main
├── docs/
│   ├── srs.md          # requisitos
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
- Cada funcionalidad nueva viene con tests. Las llamadas a APIs externas (Anthropic, Google) se mockean en los tests.
- Al terminar una versión: actualizar este archivo (roadmap) y agregar un ADR si hubo una decisión relevante.

## Seguridad (obligatorio)
- Nunca escribir keys, tokens ni credenciales en el código ni en commits. Todo va en `.env` (ignorado por git).
- Credenciales y tokens de OAuth viven fuera del repo (por defecto `~/.config/jarvis/`). Pedir siempre
  el permiso mínimo (hoy `calendar.readonly`).
- Mantener `.env.example` actualizado con los nombres de las variables, sin valores reales.
- Toda tool que tenga efectos externos (enviar mensajes, crear eventos, borrar algo) debe pedir
  confirmación al usuario antes de ejecutarse. Las tools de solo lectura no la necesitan.
- No loguear contenido sensible (mensajes completos, datos de clientes) en producción.

## Comandos
- Instalar: `uv sync`
- Correr: `uv run jarvis`
- Autorizar Google Calendar: `uv run jarvis google-login`
- Tests: `uv run pytest`
