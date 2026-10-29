# JARVIS — Asistente personal con IA

## Qué es
JARVIS es un asistente personal que me ayuda a organizar mi día: me recuerda reuniones,
me avisa de mensajes de clientes y ejecuta tareas simples por mí. Es un proyecto de
portafolio y un posible producto, así que el código debe ser limpio, documentado y testeado.

El proyecto crece por versiones pequeñas. Implementa SOLO la versión que se pida en cada sesión.

## Roadmap
- **v0.1 (actual):** loop del agente por consola con tools simuladas.
- v0.2: Google Calendar real (lectura).
- v0.3: tarea programada que envía el resumen del día.
- v0.4: canal de WhatsApp.
- Futuro: Alexa, llamadas telefónicas, multiusuario.

## Stack
- Python 3.12
- SDK oficial de Anthropic (`anthropic`), con tool use manual (loop propio, no frameworks de agentes)
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
│   ├── tools/          # una tool por archivo + registro central
│   │   ├── __init__.py # registro: nombre -> (schema, función)
│   │   └── ...
│   ├── memory.py       # historial y persistencia (SQLite)
│   └── cli.py          # punto de entrada por consola
├── tests/
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
- Cada funcionalidad nueva viene con tests. Las llamadas a la API de Anthropic se mockean en los tests.
- Al terminar una versión: actualizar este archivo (roadmap) y agregar un ADR si hubo una decisión relevante.

## Seguridad (obligatorio)
- Nunca escribir keys, tokens ni credenciales en el código ni en commits. Todo va en `.env` (ignorado por git).
- Mantener `.env.example` actualizado con los nombres de las variables, sin valores reales.
- Toda tool que tenga efectos externos (enviar mensajes, crear eventos, borrar algo) debe pedir
  confirmación al usuario antes de ejecutarse. Las tools de solo lectura no la necesitan.
- No loguear contenido sensible (mensajes completos, datos de clientes) en producción.

## Comandos
- Instalar: `uv sync`
- Correr: `uv run jarvis`
- Tests: `uv run pytest`
