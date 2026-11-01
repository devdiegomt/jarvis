# Visión de JARVIS

JARVIS quiere ser el lugar donde se reúne todo lo que le interesa a su usuario: su día, su trabajo,
su dinero y la información que sigue, con avisos a tiempo y sin tener que abrir diez aplicaciones.
Este documento fija hacia dónde va y con qué criterios. El detalle de cada versión está en el
roadmap de [`CLAUDE.md`](../CLAUDE.md) y en [`srs.md`](srs.md).

## Principio: la IA solo donde aporta

Claude cuesta por uso. Se usa para lo que solo un modelo de lenguaje hace bien; el resto va en código,
que es instantáneo, exacto y gratis.

| En código (sin IA) | Con IA (Claude) |
|---|---|
| Avisos (reuniones, correos, recordatorios) y el vistazo a mañana | Entender pedidos en lenguaje natural ("muéveme lo de mañana a las 5") |
| Comandos directos (`/hoy`, `/pendientes`, `/clima`, `/gasto`) | Decidir qué hacer ante un pedido ambiguo |
| Datos de APIs: Calendar, Gmail, clima (Open-Meteo), TRM, festivos | Resumir un correo largo o redactar una respuesta |
| Transcribir (Whisper) y hablar (Piper) en el PC | Búsquedas abiertas en internet |
| La agenda del resumen diario | El comentario del resumen diario |

Reglas que acompañan al principio:

- **Medir antes de optimizar.** Cada respuesta anota tokens y costo (`/gasto`, v0.15).
- **Caché siempre.** Lo que se repite en cada llamada se lee de la caché de prompts.
- **Una API gratuita antes que una búsqueda.** Si un dato tiene una fuente estructurada (el clima),
  se usa esa fuente con una tool, no `web_search`.

## Módulos

| Módulo | Qué hace | Estado |
|---|---|---|
| Día | Agenda, avisos antes de reuniones, recordatorios, pendientes, resumen y vistazo a mañana | Hecho |
| Clientes | Avisos de correos de clientes; buscar y leer correos | Hecho (v0.14) |
| Información | Clima (hecho), noticias por RSS y precios que el usuario sigue, con avisos | Parcial |
| Dinero | Gastos e ingresos por chat, TRM, cobros a clientes con avisos, CSV | Hecho (v0.17) |
| Movilidad | Pico y placa, tiempo de viaje a la próxima reunión ("sal ya") | Futuro |
| Trabajo | Notificaciones de GitHub, estado de proyectos por cliente | Futuro |
| Hogar y salud | Hábitos, citas médicas, domótica | Futuro |

## El iPhone (sin Mac por ahora)

Una app nativa de iOS (con widgets de WidgetKit) necesita Xcode, que solo corre en una Mac. Una
MacBook Air M1 o mejor con 16 GB basta. Instalarla en el iPhone más de 7 días requiere la cuenta de
desarrollador de Apple (99 USD al año). Mientras tanto, sin Mac:

- **PWA:** una página instalable desde Safari ("Agregar a inicio"); desde iOS 16.4 recibe
  notificaciones push.
- **Atajos de Siri:** "Oye Siri, JARVIS…" llama a la API de JARVIS.
- **Widget con Scriptable:** una app gratuita que hace widgets en JavaScript. El widget mostraría la
  próxima reunión y los pendientes, sin gastar IA.
- **Telegram** ya funciona en el iPhone.

Todo eso requiere que JARVIS sea **accesible desde el celular** sin exponerlo a internet. Desde la
v0.16 la API solo escucha en el PC y se publica con **Tailscale** (una red privada entre el PC y el
iPhone), con una clave propia. Ver [ADR 021](adr/021-api-por-tailscale.md).

## Orden propuesto

1. **v0.15:** gastar menos y medir (caché, `/gasto`, clima con Open-Meteo, comandos sin IA). Hecha.
2. **v0.16:** acceso desde el iPhone: API propia de JARVIS, solo por Tailscale y con clave. Encima, la
   PWA, los Atajos de Siri y el widget de Scriptable. Hecha; se probará en el iPhone en diciembre.
3. **v0.17:** módulo de Dinero (gastos, ingresos, cobros y TRM). Hecha. Después, Movilidad o presupuestos.
4. **Con la Mac:** app nativa con widgets, sobre la misma API.
5. **Más adelante:** alojamiento en un servidor (si el PC encendido deja de bastar), Alexa, llamadas
   telefónicas y multiusuario.
