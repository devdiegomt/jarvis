# ADR 011: Pendientes y memoria a largo plazo en SQLite, inyectada al empezar cada conversación

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.9

## Contexto

Una conversación de Telegram termina tras 6 horas de inactividad o con `/nuevo`, y el historial se
borra a los 30 días: JARVIS olvidaba todo lo que el usuario le había contado. Además, no tenía dónde
anotar cosas por hacer sin hora fija (los recordatorios necesitan una hora).

## Decisión

1. **Pendientes** (`tasks.py`, tabla `tasks`): texto y fecha límite opcional (fecha local, sin
   hora). Tools `agregar_pendiente`, `listar_pendientes`, `completar_pendiente` y
   `borrar_pendiente`, sin confirmación (datos internos y reversibles, como los recordatorios).
   El resumen diario muestra los que vencen ese día o están atrasados, y se los pasa a Claude para
   el comentario. Los hechos se borran a los 30 días; como mucho 200 abiertos.
2. **Memoria a largo plazo** (`long_term_memory.py`, tabla `memories`): frases cortas y autónomas
   sobre el usuario. Tools `recordar_dato`, `listar_datos` y `olvidar_dato`, sin confirmación.
3. **El modelo guarda por iniciativa propia y avisa** ("📝 Lo recordaré"): el system prompt y la
   descripción de la tool le piden guardar lo duradero (personas, preferencias, rutinas, trabajo) y
   no lo pasajero, ni contraseñas o datos bancarios. Como red de seguridad, `recordar_dato` rechaza
   secuencias de 12 o más dígitos (tarjetas, cuentas, documentos).
4. **Inyección en el system prompt al empezar cada conversación**, con el id de cada dato. Dentro
   de una conversación el system prompt no cambia (regla de historial append-only): lo que se
   guarda durante la charla el modelo ya lo tiene en el propio historial, y entra en el prompt de la
   siguiente conversación.
5. **Sin caducidad:** los datos se quedan hasta que el usuario los borra (`/memoria` los lista sin
   pasar por la IA; "olvida el 3" los borra). Tope de 200 datos de 300 caracteres (unos 60 000
   caracteres como máximo en el prompt); al llenarse, JARVIS pide borrar alguno.

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| Herramienta de memoria de Anthropic (`memory_20250818`, archivos en un directorio) | El modelo tendría que leer sus archivos al empezar cada tarea (más llamadas, más latencia y costo), y el registro de tools tendría que admitir tools sin schema propio. Con cientos de datos, inyectarlos es más simple y barato. |
| Búsqueda semántica (embeddings) | Innecesaria con este volumen; añadiría otro proveedor o un modelo local. Se podrá añadir detrás de `listar_datos` si la memoria crece. |
| Extraer recuerdos automáticamente al cerrar cada conversación | Otra llamada a la IA por conversación y menos control: el usuario no sabría qué se guardó. |
| Guardar solo cuando el usuario lo pide | Menos útil: el usuario tendría que acordarse de pedirlo. Avisar al guardar da el mismo control. |
| Que la memoria caduque a los 30 días, como el historial | Iría contra el propósito de una memoria a largo plazo. A cambio, el usuario la ve y la borra con `/memoria`. |

## Consecuencias

- Las respuestas mejoran con el tiempo sin que el usuario repita contexto.
- El prompt crece con la memoria; con el tope actual sigue siendo pequeño frente al contexto del modelo.
- La memoria guarda información personal sin caducidad: queda solo en el PC, nunca en los registros,
  y es visible y borrable por el usuario en todo momento.
- `jarvis.db` pasa a contener datos que conviene conservar al cambiar de equipo (copiar el archivo).
