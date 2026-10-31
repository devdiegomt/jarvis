# ADR 020: IA solo donde aporta: caché, medición del gasto, clima y comandos sin IA

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.15

## Contexto

JARVIS crece en funciones y cada una puede gastar créditos de Claude. Había tres problemas:

- No se sabía cuánto costaba cada respuesta.
- En cada vuelta del loop se reenviaban completos el system prompt, las ~25 tools y el historial.
- Preguntas que no necesitan IA (el clima, la agenda de hoy) pasaban por Claude, y el clima además
  gastaba una búsqueda en internet y miles de tokens de resultados.

## Decisión

Principio: **la IA solo para entender lenguaje, decidir o redactar; datos, horas, cálculos y avisos,
en código.** Ver [`docs/vision.md`](../vision.md).

1. **Prompt caching automático:** `cache_control: {type: "ephemeral"}` en cada llamada del agente. La
   API guarda el prefijo (tools, system prompt e historial) y lo cobra al 10 % cuando se repite en los
   5 minutos siguientes. No cambia ni recorta el historial (el razonamiento preservado sigue válido).
2. **Medición:**
   - El agente suma `usage` de todas las llamadas de cada respuesta.
   - El chat (Telegram y voz del PC), la consola y el comentario del resumen lo anotan en
     `jarvis.db` (`api_usage`, solo números).
   - El costo se estima con los precios públicos de una tabla en `usage.py`, y las búsquedas a $10 por
     cada 1.000. Si un modelo no está en la tabla, se muestran solo los tokens.
   - Se ve con `/gasto`, en `estado` y, por respuesta, en el registro.
3. **Clima con Open-Meteo:** gratis, sin clave y con datos exactos.
   - Una tool `get_clima`, que el prompt hace preferir a `web_search`.
   - El mismo pronóstico arma, en código, las líneas de clima de `/hoy`, `/clima`, el resumen de la
     mañana y el vistazo a mañana.
   - La ciudad se ubica una vez por proceso y el pronóstico se guarda en memoria 30 minutos.
4. **Comandos directos:** `/hoy`, `/pendientes`, `/recordatorios`, `/clima` y `/gasto` se responden en
   código (`quick.py`), sin llamar a Claude. `ChatService` recibe un diccionario de comandos, así
   agregar uno no toca la lógica del chat.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Caché con breakpoints manuales | El automático cubre el caso (prefijo que crece) sin lógica propia. |
| Caché de 1 hora | La escritura cuesta el doble; los mensajes seguidos y el loop de tools ya caen en 5 minutos. |
| Leer el gasto real de la API de administración | Requiere una clave de administrador; la estimación local basta para decidir. |
| OpenWeatherMap u otro servicio de clima | Piden cuenta y clave; Open-Meteo no y tiene datos para Colombia. |
| Que Claude arme `/hoy` | Más lento y con costo, para un texto que es pura agenda. |
| Cambiar a un modelo más barato | Se decidirá con los números que ahora se miden. |

## Consecuencias

- El primer mensaje tras más de 5 minutos escribe la caché (cuesta 1,25 veces esa entrada); los
  siguientes la leen al 10 %. `/gasto` muestra qué parte de la entrada salió de la caché.
- Los precios están en el código: si Anthropic los cambia, hay que actualizar `PRICES`.
- Sin `JARVIS_CIUDAD` no hay clima (`/clima` explica cómo configurarlo).
