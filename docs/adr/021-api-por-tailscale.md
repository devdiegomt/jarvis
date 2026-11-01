# ADR 021: API propia para el iPhone, solo en el PC y publicada con Tailscale

- **Estado:** Aceptada
- **Fecha:** 2026-11-01
- **Versión:** v0.16

## Contexto

Desde el iPhone, JARVIS solo se usaba por Telegram. Una app web instalable (PWA), los Atajos de Siri
y un widget de pantalla de inicio necesitan llegar a JARVIS por HTTP. Hasta ahora JARVIS no abría
ningún puerto (RNF-04). Hacer una app nativa requiere una Mac, que todavía no hay.

## Decisión

1. **Un servidor HTTP propio** (`http.server` de la librería estándar, sin dependencias nuevas),
   dentro del proceso de Telegram en segundo plano y **apagado por defecto** (`JARVIS_API=si`).
2. **Solo escucha en `127.0.0.1`.** El código se niega a escuchar en otra dirección: ni la red de la
   casa lo ve.
3. **Publicación con `tailscale serve`**, que lo ofrece solo dentro de la red privada del usuario
   (sus dispositivos con su cuenta de Tailscale), con HTTPS y certificado válido. Nunca con
   `tailscale funnel`, que lo abriría a internet.
4. **Clave propia:**
   - `jarvis api-clave` la genera (32 bytes aleatorios) y la muestra una sola vez.
   - En el equipo queda solo su huella SHA-256, comparada en tiempo constante.
   - Tras 5 fallos en 10 minutos, la API se pausa 1 minuto.
   - Opcionalmente (`JARVIS_API_USUARIO`) se exige además la cuenta de Tailscale que `tailscale serve`
     informa en cada pedido.
5. **Misma lógica que Telegram.** Un canal más (`ApiChannel`) sobre `ChatService`, con sus tools,
   memoria, comandos y confirmaciones:
   - Cada pedido HTTP entrega su mensaje y espera la salida del chat hasta que el turno termina o
     queda una pregunta con botones.
   - La pregunta se responde con otro pedido (`/api/boton`, o "sí" / "no" escrito, para Siri).
6. **Rutas sin IA** (`/api/hoy` en datos, `/api/pendientes`, `/api/clima`, `/api/gasto`…) para el
   widget y la pestaña Hoy.
7. **La PWA** se sirve desde el mismo servidor (HTML, CSS y JS propios, sin CDNs) con una política de
   contenido estricta (CSP). Sin CORS: otro sitio web no puede usar la API. Los íconos se dibujan en
   código (sin archivos binarios en el repositorio).
8. **Registros:** método, ruta, código y tiempo; nunca el contenido ni la dirección de origen.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Escuchar en la red local (0.0.0.0) | Cualquiera en la misma wifi podría intentar entrar, y fuera de casa no sirve. |
| Abrir un puerto en el router o un túnel público | Expone JARVIS a internet; contradice la regla de no abrir puertos. |
| Servidor en la nube | Costo y datos fuera del equipo; se decidirá más adelante (ver `docs/vision.md`). |
| FastAPI u otro framework | Dependencias nuevas para unas pocas rutas que la librería estándar resuelve. |
| Telegram como única vía | No permite widget, Siri ni una pantalla propia. |
| App nativa de iOS | Requiere una Mac; queda para cuando la haya, sobre esta misma API. |

## Consecuencias

- El iPhone necesita la app de Tailscale con la VPN activa (puede quedar siempre encendida).
- El PC debe estar encendido con JARVIS en segundo plano, igual que para Telegram.
- La regla de seguridad cambia de "no abre puertos" a "solo escucha en el propio PC; acceso remoto
  únicamente por `tailscale serve`, con clave".
- Las notificaciones push en la PWA quedan para otra versión: los avisos siguen llegando por Telegram.
