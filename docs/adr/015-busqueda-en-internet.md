# ADR 015: Búsqueda en internet con las tools de servidor de Anthropic

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.11

## Contexto

JARVIS solo sabía lo que traía el modelo, el calendario y sus propios datos. El usuario quiere
preguntar por lo que cambia (clima, noticias, precios, horarios) y que le resuma enlaces.

## Decisión

1. **Tools de servidor de Anthropic** `web_search_20260209` y `web_fetch_20260209` (con filtrado
   dinámico), declaradas en la misma petición a Claude. No hay otro proveedor ni otra clave.
2. **Sin tocar el loop del agente:** el registro de tools admite tools de servidor
   (`register_server_tool`), que se envían junto a las propias. El agente ya reenviaba el contenido
   completo de cada respuesta (incluidos `server_tool_use` y sus resultados) y continuaba en
   `pause_turn`, como pide la API.
3. **Límites:** como mucho 5 búsquedas y 3 lecturas de enlaces por mensaje (unos 20 000 tokens por
   página). Son de solo lectura: no piden confirmación. `JARVIS_BUSQUEDA=no` las desactiva.
4. **Ubicación del usuario** (`JARVIS_CIUDAD`, `JARVIS_PAIS`) en el system prompt, para que el modelo
   busque el clima y los lugares de su zona. No se envía en `user_location` de la tool: la API rechaza
   la petición entera con países que no admite (v0.11.2: "Country code CO is not supported").
5. **Fuentes:** el agente recoge las citas de la respuesta (título y URL, sin duplicados, hasta 3).
   En Telegram se añaden al final como "Fuentes:"; por voz no se leen (el system prompt pide decir de
   dónde sale el dato). El texto citado llega partido en varios bloques: se une sin separador y se
   omite lo que el modelo dijo antes de buscar.
6. **Cuándo buscar:** el system prompt pide buscar solo información actual o dudosa, nunca lo que
   está en el calendario, los recordatorios, los pendientes o la memoria, y no inventar enlaces.
7. **Registro:** cuántas búsquedas hizo cada respuesta (se pagan aparte), nunca qué se buscó.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Buscador propio (Brave Search, Tavily, Serper) como tool de cliente | Otra cuenta y clave, otro proveedor recibiendo las consultas, y código propio para leer y resumir páginas. |
| Leer páginas con `urllib` desde el PC | Habría que limpiar HTML, respetar límites y defenderse de contenido malicioso; `web_fetch` ya lo hace con citas. |
| Buscar siempre | Más lento y más caro; la mayoría de los mensajes no lo necesitan. |

## Consecuencias

- Las consultas pasan por Anthropic, que ya recibía la conversación: ningún servicio nuevo recibe
  datos del usuario.
- Cada búsqueda cuesta aparte (unos 10 USD por cada 1000, más los tokens leídos); el tope por
  mensaje y el registro permiten vigilarlo.
- El contenido de las páginas puede traer instrucciones maliciosas: las acciones con efectos
  externos siguen pidiendo confirmación al usuario, y el system prompt pide tratar lo leído como
  información, sin guardar memoria ni crear recordatorios o pendientes porque lo diga una página.
