# ADR 001: Loop de agente propio, sin framework de agentes

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.1

## Contexto

JARVIS necesita un agente que converse con el usuario, decida cuándo usar herramientas
(consultar reuniones, enviar mensajes) y encadene varias llamadas hasta resolver la petición.

Hay dos caminos:

1. Usar un framework de agentes (LangChain / LangGraph, LlamaIndex, CrewAI, el Claude Agent SDK,
   o el *tool runner* beta del propio SDK de Anthropic).
2. Escribir el loop a mano sobre la API de Messages del SDK oficial de Anthropic (`anthropic`).

Requisitos que pesan en la decisión:

- **Seguridad:** toda acción con efectos externos debe pedir confirmación antes de ejecutarse,
  y los errores de una tool deben volver al modelo como resultado (`is_error`) sin romper el programa.
  Necesitamos control exacto sobre dónde y cómo ocurre eso.
- **Proyecto de portafolio:** el código debe ser legible y demostrar que entendemos cómo funciona
  un agente por dentro.
- **Crecimiento por versiones:** vendrán Google Calendar, tareas programadas, WhatsApp, Alexa.
  Cada canal tiene su propia forma de pedir confirmación al usuario.

## Decisión

Implementamos un **loop propio** en `src/jarvis/agent.py` usando directamente
`client.messages.create` con tool use:

1. Se envía el historial y las definiciones de tools.
2. Si `stop_reason == "tool_use"`, se ejecutan todas las tools pedidas a través del registro
   (`jarvis.tools`) y se devuelven los `tool_result` en un único mensaje.
3. Se repite hasta obtener una respuesta final, con un máximo de **10 iteraciones** por mensaje.

Las tools viven en un registro central (`ToolRegistry`) independiente del loop: agregar una tool
nueva no requiere tocar `agent.py`. La confirmación de acciones con efectos externos se aplica
en el registro, y la función que pregunta al usuario se inyecta (hoy la consola; mañana WhatsApp).

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| LangChain / LangGraph | Muchas capas de abstracción y dependencias para un loop de ~50 líneas. Su API cambia con frecuencia y los errores son difíciles de rastrear a través de sus capas. |
| LlamaIndex / CrewAI | Orientados a RAG o a sistemas multiagente; JARVIS hoy es un solo agente con pocas tools. |
| Claude Agent SDK | Trae el harness de Claude Code con herramientas de archivos y bash; JARVIS no las necesita y ampliaría la superficie de riesgo. |
| Tool runner del SDK (`client.beta.messages.tool_runner`) | Es la opción más cercana y reduce código, pero es beta y oculta el loop. Para v0.1 preferimos tener el flujo explícito; se puede reevaluar más adelante. |

## Consecuencias

**Positivas**

- Control total sobre confirmaciones, manejo de errores, límite de iteraciones e historial.
- Una sola dependencia de IA (`anthropic`), fácil de actualizar.
- Fácil de testear: el cliente de Anthropic se inyecta y se reemplaza por uno falso en los tests.
- El código explica por sí mismo cómo funciona un agente, lo cual tiene valor de portafolio.

**Negativas**

- Somos responsables de mantener el loop al día con la API (nuevos `stop_reason`, bloques de
  contenido, etc.).
- Funciones que un framework da gratis (streaming, reintentos por tool, memoria, trazas)
  habrá que implementarlas cuando hagan falta.

**Revisión:** si el loop crece mucho o necesitamos varios agentes coordinados, reevaluaremos
el tool runner del SDK u otra herramienta en un nuevo ADR.
