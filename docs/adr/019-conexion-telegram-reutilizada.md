# ADR 019: Conexiones HTTPS con Telegram reutilizadas

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.14.1

## Contexto

Cada llamada a la API de bots abría una conexión nueva con `urllib`: TCP más el saludo TLS, unos
0,3 a 0,8 s desde Colombia. Responder una nota de voz encadena unas cinco llamadas (escribiendo…,
getFile, descarga, texto y voz), así que se perdían 2 a 3 s solo en abrir conexiones. Telegram
admite conexiones persistentes (HTTP/1.1 keep-alive).

## Decisión

1. **`http.client` de la librería estándar** con un pool propio (`ConnectionPool`), sin dependencias
   nuevas. Las conexiones se verifican con `truststore`, como antes, y respetan el proxy del sistema
   (túnel `CONNECT`), como hacía `urllib`.
2. **Una conexión por hilo y servidor:** la espera de mensajes (long polling, hasta 30 s), el chat, los
   avisos y los recordatorios usan cada uno la suya, así ninguno espera a otro.
3. **Inactividad:** una conexión sin usar más de 30 s se renueva antes de enviar, porque el servidor
   puede haberla cerrado.
4. **Reintento único y seguro:** si al reutilizar una conexión Telegram ya la había cerrado
   (`RemoteDisconnected`, `BrokenPipe`, `ConnectionReset`), se repite el pedido una vez con una
   conexión nueva: Telegram no lo recibió, así que no se duplica nada. Un fallo en una conexión nueva
   o un tiempo agotado no se reintentan aquí (el pedido pudo llegar); siguen las reglas de siempre.
5. **Medición:** el registro anota el método y los segundos de cada llamada, y si la conexión era
   nueva o reutilizada; nunca el contenido ni el token. La espera de mensajes no se anota.
6. **Mismos errores para el usuario:** el token sigue sin aparecer en errores ni registros.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| `requests` o `httpx` | Dependencia nueva para algo que la librería estándar resuelve en unas 100 líneas. |
| Una sola conexión compartida con un candado | La espera de mensajes la ocuparía hasta 30 s y frenaría las respuestas. |
| Reintentar cualquier fallo de red | Tras un tiempo agotado Telegram pudo recibir el mensaje: se duplicaría. |
| Webhook en vez de long polling | Requiere abrir un puerto o un servidor público (RNF-04). |

## Consecuencias

- La primera llamada de cada respuesta paga el saludo; las siguientes no.
- El pool queda listo para otros servicios por HTTPS (por ejemplo, Azure) si hace falta.
