# JARVIS

[![Tests](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml/badge.svg)](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml)

Asistente personal con IA que ayuda a organizar el día: recuerda reuniones, avisa de
mensajes y ejecuta tareas simples. Construido con el SDK oficial de Anthropic y un loop
de agente propio (sin frameworks).

## Estado

**v0.15**: comandos al instante sin gastar IA (`/hoy`, `/clima`, `/gasto`…), clima gratis con
Open-Meteo y medición de cuánto cuesta cada respuesta; te avisa de los correos de tus clientes,
antes de cada reunión y te da un vistazo a mañana por la noche; lee tu Google
Calendar y agenda, mueve o cancela tus eventos (siempre con tu
confirmación), chateas con JARVIS por Telegram (también en
segundo plano) escribiéndole o con notas de voz, y te responde también con voz; en el PC lo llamas
con "Hey JARVIS" y te contesta en voz alta. Te crea recordatorios, lleva tu lista de pendientes,
recuerda lo que le cuentas de ti entre conversaciones, busca en internet lo que cambia (noticias,
precios) y te envía un resumen del día de lunes a
viernes (por Telegram o Gmail). El envío de mensajes a
terceros sigue simulado.
Ver el roadmap completo en [`CLAUDE.md`](CLAUDE.md).

## Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Una API key de Anthropic
- (Opcional) Una cuenta de Google para leer tu calendario real
- (Opcional) Una cuenta de Telegram para chatear con JARVIS desde el celular

## Instalación

```bash
uv sync
cp .env.example .env   # y completa ANTHROPIC_API_KEY
```

> **Windows: "Una directiva de Control de aplicaciones bloqueó este archivo".** El Control
> inteligente de aplicaciones de Windows puede bloquear el lanzador `jarvis.exe` que crea `uv sync`
> (no está firmado). Usa el mismo comando a través de Python, que sí está firmado:
> `uv run python -m jarvis <comando>` (por ejemplo, `uv run python -m jarvis estado`). Las tareas
> programadas ya arrancan así. No hace falta desactivar esa protección.

## Uso

```bash
uv run jarvis
```

Escribe tu mensaje y JARVIS responde. Escribe `salir` para terminar.

Por defecto JARVIS usa reuniones de ejemplo (`JARVIS_CALENDAR=sample`). Para usar tu
calendario real, sigue los pasos de la siguiente sección.

## Conectar Google Calendar

JARVIS pide permiso para **ver y editar los eventos** del calendario (`calendar.events`): no
puede compartir ni borrar calendarios, y antes de agendar, mover o cancelar algo siempre te pide
confirmación. Para avisarte de tus clientes pide permiso para **leer** tus correos
(`gmail.readonly`), sin poder enviar, borrar ni modificar nada (`JARVIS_CORREO=no` lo omite). Si el
resumen diario va por Gmail, pide además permiso para **enviar** correos (`gmail.send`). La autorización se guarda en tu equipo,
fuera del repositorio.

### 1. Crear las credenciales en Google Cloud (una sola vez)

1. Entra a [Google Cloud Console](https://console.cloud.google.com/) y crea un proyecto nuevo
   (por ejemplo, `jarvis`).
2. Ve a **APIs y servicios → Biblioteca**, busca **Google Calendar API** y pulsa **Habilitar**.
   Haz lo mismo con **Gmail API** (para los avisos de correos de clientes y, si lo eliges, el
   resumen diario por Gmail).
3. Ve a **Google Auth Platform** (o **Pantalla de consentimiento de OAuth**) y pulsa **Comenzar**:
   - Nombre de la app: `JARVIS`; correo de asistencia: el tuyo.
   - Público: **Externo**.
   - Información de contacto: tu correo. Acepta las condiciones y crea.
4. En **Público → Usuarios de prueba**, agrega tu propia cuenta de Gmail.
5. En **Clientes → Crear cliente**:
   - Tipo de aplicación: **App de escritorio**; nombre: `JARVIS CLI`.
   - Pulsa **Crear** y luego **Descargar JSON**.
6. Mueve el archivo descargado a `~/.config/jarvis/credentials.json`:

   ```bash
   mkdir -p ~/.config/jarvis
   mv ~/Downloads/client_secret_*.json ~/.config/jarvis/credentials.json
   ```

   (Si prefieres otra ruta, defínela en `GOOGLE_CREDENTIALS_FILE`.)

> **Nunca subas este archivo al repositorio.** El `.gitignore` ya lo excluye.

### 2. Autorizar a JARVIS

```bash
uv run jarvis google-login
```

Se abrirá el navegador (si no, copia la URL que aparece en la terminal):

1. Elige tu cuenta de Google.
2. Verás el aviso *"Google no verificó esta app"*: es normal para una app personal.
   Pulsa **Continuar**.
3. Acepta los permisos que se piden (ver y editar tus eventos, leer tus correos para avisarte de
   tus clientes y, si el resumen va por Gmail, enviar correos). Deja todas las casillas marcadas.

El token se guarda en `~/.config/jarvis/token.json`.

### 3. Activar el calendario real

En tu `.env`:

```bash
JARVIS_CALENDAR=google
JARVIS_TIMEZONE=America/Bogota   # tu zona horaria IANA
```

Luego ejecuta `uv run jarvis` y pregunta, por ejemplo, *"¿Qué reuniones tengo hoy?"*.

### Problemas comunes

- **"Google rechazó la autorización"** después de unos días: mientras la app está en modo
  *Prueba*, Google hace que la autorización caduque a los 7 días. Vuelve a ejecutar
  `uv run jarvis google-login`. Para evitarlo, en **Google Auth Platform → Público** pulsa
  **Publicar app** (seguirá siendo de uso personal; solo verás el aviso de app no verificada).
- **"Google denegó el acceso al calendario"**: revisa que la Google Calendar API esté habilitada
  en el mismo proyecto donde creaste el cliente.
- **"No encontré el calendario"**: revisa `GOOGLE_CALENDAR_ID` (por defecto `primary`).

## Chatear con JARVIS por Telegram

JARVIS se conecta a un bot de Telegram tuyo y solo atiende **tu** cuenta. No necesita ngrok,
URL pública ni puertos abiertos: JARVIS consulta a Telegram si hay mensajes nuevos. Responde
mientras tu PC esté encendido con `uv run jarvis telegram` corriendo. Es gratis.

### 1. Crear el bot (una sola vez)

1. En Telegram, busca **@BotFather** (con la marca de verificación azul) y envíale `/newbot`.
2. Elige un nombre (por ejemplo, `JARVIS`) y un usuario que termine en `bot`
   (por ejemplo, `jarvis_tunombre_bot`).
3. BotFather te responde con un **token** (algo como `123456789:AAH…`). Cópialo en tu `.env`:

   ```bash
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   ```

> El token es un secreto: quien lo tenga controla tu bot. Solo va en tu `.env`. Si se filtra,
> envía `/revoke` a BotFather para generar otro.

### 2. Vincular tu cuenta (una sola vez)

```bash
uv run jarvis telegram-vincular
```

Abre tu bot en Telegram y envíale `/start`. La terminal mostrará tu ID; cópialo en tu `.env`:

```bash
TELEGRAM_OWNER_ID=987654321
```

Comprueba que el nombre que muestra la terminal sea el tuyo. JARVIS no arranca sin este ID,
así que nadie más puede usar tu bot.

### 3. Chatear

```bash
uv run jarvis telegram
```

- Escribe como en la consola: *"¿Qué tengo hoy?"*, *"¿Y el jueves?"*.
- Si JARVIS quiere hacer algo con efectos externos, te pregunta con botones **[✅ Sí] [❌ No]**
  (también puedes escribir `s` o `n`). Sin respuesta en 5 minutos, la acción se cancela.
- `/nuevo` empieza una conversación nueva y `/ayuda` muestra la ayuda. Tras 6 horas sin
  mensajes, la siguiente conversación empieza de cero.
- Por ahora solo entiende mensajes de texto.

El historial se guarda en tu equipo (`jarvis.db`) y las conversaciones de más de 30 días se borran
solas. El log (`~/.config/jarvis/logs/telegram.log`) registra solo IDs y resultados, nunca el texto,
y rota solo (unos 4 MB como máximo).

### 4. Que JARVIS esté siempre disponible (Windows)

Para no tener que dejar una terminal abierta:

```bash
uv run jarvis programar-telegram
```

JARVIS queda corriendo en segundo plano (sin ventanas) y arrancará solo cada vez que inicies sesión
en Windows. Si el PC se suspende, se reconecta al despertar; si se detiene por un error, Windows lo
reinicia hasta 3 veces. Solo funciona con tu sesión iniciada (no guarda tu contraseña de Windows).

- Para comprobar cómo va: `uv run jarvis estado`.
- Para detenerlo y quitar el arranque automático: `uv run jarvis quitar-telegram`.
- Mientras corre en segundo plano, no abras `uv run jarvis telegram` en una terminal: solo puede
  haber una copia por bot (la de segundo plano espera a que cierres la otra).
- En Mac o Linux, el comando muestra la línea de `cron` (`@reboot`) que debes añadir.

### Problemas comunes

- **JARVIS no responde**: ejecuta `uv run jarvis estado`. Muestra si la tarea en segundo plano está
  corriendo, cuándo se ejecutó por última vez y con qué resultado, y las últimas líneas del
  registro, donde aparece la causa si se detuvo.
- **"El token del bot no es válido"**: revisa `TELEGRAM_BOT_TOKEN` (cópialo completo, con el número
  y los dos puntos).
- **"Otra copia de JARVIS está usando este bot"**: solo puede haber un `jarvis telegram` corriendo
  por bot. Cierra la otra terminal.
- **JARVIS no responde y el log dice "usuario no autorizado"**: el ID de `TELEGRAM_OWNER_ID` no es
  el tuyo; repite `uv run jarvis telegram-vincular`.
- **"su certificado HTTPS no es de confianza en este equipo"**: algo intercepta las conexiones HTTPS
  (normalmente la protección web de un antivirus, o un proxy de empresa). JARVIS verifica con el
  almacén de certificados de Windows, igual que el navegador, así que si el certificado del
  antivirus está instalado en el sistema debería funcionar. Para comprobar quién intercepta, abre
  `https://api.telegram.org` en el navegador, pulsa el candado y mira **Emitido por**: debería ser
  tu antivirus. Si no reconoces al emisor, no sigas y revisa tu red. Si es tu antivirus y aun así
  falla, añade `api.telegram.org` a sus exclusiones de análisis HTTPS.

## Recordatorios

Pídeselos a JARVIS en lenguaje natural, por Telegram o en la consola:

- *"Recuérdame mañana a las 9 llamar a Laura"*
- *"Recuérdame en 2 horas tomar agua"*
- *"¿Qué recordatorios tengo?"* / *"Cancela el de llamar a Laura"*

A la hora indicada te llega un mensaje por Telegram con dos botones: **⏰ Posponer 10 min** y
**✅ Hecho**. Los avisa el proceso de Telegram, así que debe estar corriendo (en segundo plano con
`programar-telegram`, o con `uv run jarvis telegram`). Si el PC estaba apagado a esa hora, el aviso
llega al volver, marcado como atrasado.

Los recordatorios se guardan en tu equipo (`jarvis.db`); los ya enviados o cancelados se borran a
los 30 días. Crear o cancelar un recordatorio no pide confirmación: es interno a JARVIS y siempre
se puede deshacer. `uv run jarvis estado` muestra cuántos hay pendientes y la hora del próximo.

## Avisos

JARVIS te escribe por su cuenta, por Telegram:

- **Antes de cada reunión** (10 minutos antes, por defecto), con el horario, quiénes van, el lugar y
  el enlace de Meet, Zoom o Teams si lo tiene. Cada reunión se avisa una sola vez; si la mueves, te
  avisa a la hora nueva. No avisa de eventos de día completo ni tarde (si la reunión ya empezó,
  por ejemplo porque el PC estaba apagado).
- **Un vistazo a mañana**, de domingo a jueves a las 20:00: tus reuniones de mañana y los
  pendientes que vencen.

Se configuran en `.env`: `JARVIS_AVISO_REUNION=15` (minutos antes; `0` lo apaga) y
`JARVIS_VISTAZO_MANANA=21:00` (o `no`). Los envía JARVIS en segundo plano, así que el PC debe estar
encendido. `uv run python -m jarvis estado` muestra cuáles están activos.

## Correos de clientes

Dile a JARVIS de quién quieres enterarte: *"Avísame de los correos de laura@acme.com"* o *"Avísame
de todo lo que llegue de acme.com"* (un dominio entero). Cuando llegue un correo de ellos, te
escribe por Telegram con el remitente, el asunto y el comienzo del mensaje:

```
📧 Correo de Laura Gómez (laura@acme.com)
«Cambios a la propuesta»
Hola Diego, te adjunto la versión con los ajustes que hablamos…
```

- **`/clientes`** muestra la lista; *"Ya no me avises de acme.com"* quita a alguien.
- También puedes preguntarle por tus correos: *"¿Qué me escribió Laura esta semana?"*, *"Léeme el
  último correo de acme.com"*. Busca y lee solo cuando se lo pides.
- Revisa cada 2 minutos. Al agregar a alguien, te avisa de lo que llegue **desde ese momento** (no
  de correos viejos), y cada correo una sola vez.
- **Solo lectura:** JARVIS no puede enviar, borrar, archivar ni marcar como leído nada. Lo que dice
  un correo lo toma como información: si un correo le pide hacer algo, te lo cuenta en vez de hacerlo.
- Los correos no se guardan en tu equipo (solo la lista y qué correos ya te avisó), y los registros
  no anotan remitentes ni asuntos.
- **Si ya tenías JARVIS autorizado antes de la v0.14**, habilita la **Gmail API** en tu proyecto de
  Google Cloud (si no lo estaba) y ejecuta una vez `uv run python -m jarvis google-login` para
  aceptar el permiso de leer correos. Mientras tanto, `estado` muestra *"falta el permiso"*.

Se configuran en `.env`: `JARVIS_CORREO=no` los apaga y `JARVIS_CORREO_MINUTOS=5` cambia cada cuánto
revisa (de 1 a 60 minutos).

## Agendar en el calendario

Pídeselo como a una persona: *"Agéndame dentista el jueves a las 3"*, *"Mueve la reunión de
planificación a las 5"*, *"Cancela lo de mañana a las 9"*. Antes de cambiar algo, JARVIS te muestra
el detalle (y si choca con otra cosa) y espera tu **Sí / No**; por voz, te lo pregunta.

- Solo toca **eventos que organizas tú**: las invitaciones de otras personas no las mueve ni las
  cancela (respóndelas desde Google Calendar).
- Nunca invita a nadie ni envía avisos: los eventos que crea son solo para ti.
- Si un evento se repite, mover o cancelar afecta solo esa ocasión (te lo dice al confirmar).
- **Si ya tenías JARVIS autorizado antes de la v0.12**, el permiso era solo de lectura: ejecuta una
  vez `uv run python -m jarvis google-login` y acepta el nuevo permiso. Mientras tanto, sigue leyendo
  tu agenda, y `estado` muestra *"solo lectura"*.

## Búsqueda en internet

Pregúntale lo que cambia con el tiempo: *"¿A cómo está el dólar?"*,
*"¿Qué pasó con…?"*, *"¿A qué hora abre…?"*. JARVIS busca en internet cuando hace falta y, en
Telegram, termina la respuesta con sus **Fuentes** (enlaces). También puedes pegarle un enlace y
pedirle *"resúmeme esto"*.

- Para que los lugares sean los de tu zona, pon tu ciudad en `.env`: `JARVIS_CIUDAD=Zipaquirá` y
  `JARVIS_PAIS=CO`. El clima de tu ciudad no usa la búsqueda (ver [Clima](#clima)).
- Usa la búsqueda de Anthropic (la misma API de Claude): no hay que crear cuentas ni claves nuevas.
  Cada búsqueda cuesta aparte (unos 10 USD por cada 1000 búsquedas, más el texto leído), con un tope
  de 5 búsquedas por mensaje; el registro anota cuántas se hicieron, nunca qué se buscó.
- Solo busca cuando la información puede haber cambiado; lo de tu calendario, recordatorios,
  pendientes y memoria lo responde sin internet. Solo abre enlaces que aparecen en la conversación.
- Para desactivarla: `JARVIS_BUSQUEDA=no`.

## Clima

Con tu ciudad en `.env` (`JARVIS_CIUDAD=Zipaquirá`, `JARVIS_PAIS=CO`), JARVIS consulta el clima en
[Open-Meteo](https://open-meteo.com): gratis, sin cuenta ni clave, y sin gastar una búsqueda en
internet. Pregúntale *"¿Va a llover esta tarde?"* o usa `/clima`, y verás el clima también en `/hoy`,
en el resumen de la mañana y en el vistazo a mañana. A Open-Meteo solo se le envía el nombre de tu
ciudad (y sus coordenadas); el pronóstico se consulta como mucho cada media hora.

## Comandos al instante (sin IA)

Estos comandos de Telegram los responde JARVIS directamente, sin consultar a Claude: son
instantáneos y no gastan créditos.

| Comando | Qué muestra |
|---|---|
| `/hoy` | Tu día: clima, reuniones, recordatorios y pendientes que vencen |
| `/pendientes` | Todos tus pendientes, con su fecha |
| `/recordatorios` | Los recordatorios programados |
| `/clima` | Ahora y los próximos 3 días |
| `/gasto` | Cuánto has gastado en Claude hoy, en la semana y en el mes |

## Cuánto cuesta

Cada respuesta de Claude anota en tu equipo cuántos tokens usó (sin el texto) y su costo estimado con
los precios públicos de la API. Lo ves con `/gasto`, al final de `estado` y, por respuesta, en el
registro (*"Claude: 4.200 tokens de entrada (3.900 de caché), 180 de salida ≈ $0,0026"*). Es una
estimación: la factura real está en la consola de Anthropic.

JARVIS usa la caché de Anthropic: la parte que se repite en cada llamada (instrucciones, tools e
historial) cuesta el 10 % al leerla de la caché, que dura 5 minutos. Por eso los mensajes seguidos y
los que usan tools salen bastante más baratos.

## Pendientes y memoria

**Pendientes** son cosas por hacer sin hora fija; si necesitas un aviso a una hora, pide un
recordatorio.

- *"Anota que tengo que renovar el pasaporte antes del viernes"*
- *"¿Qué tengo pendiente?"* / *"Ya renové el pasaporte"* / *"Borra lo del banco, ya no hace falta"*

El resumen diario incluye los pendientes que vencen ese día o están atrasados. Los ya hechos se
borran a los 30 días.

**Memoria a largo plazo:** cuando le cuentas algo que seguirá siendo cierto (*"mi socia se llama
Laura y prefiere reuniones por la mañana"*), JARVIS lo anota por su cuenta, te avisa (*📝 Lo
recordaré*) y lo tiene presente en las próximas conversaciones, aunque empieces una nueva con /nuevo.

- **/memoria** muestra todo lo que recuerda, numerado.
- *"Olvida el 3"* o *"olvida lo de Laura"* lo borra; si algo cambió, díselo y lo corrige.
- Los datos se guardan solo en tu PC (`jarvis.db`) y no caducan: siguen ahí hasta que los borras.
  Por seguridad, no guarda números largos como tarjetas o cuentas.
- Hasta 200 datos; si se llena, te pedirá que borres alguno.

Crear, completar o borrar pendientes y datos no pide confirmación: es interno a JARVIS y se puede
deshacer. `uv run jarvis estado` muestra cuántos hay, sin mostrar su texto.

## Notas de voz

Mándale a tu bot una nota de voz como harías con una persona. JARVIS la transcribe en tu PC, te
muestra lo que entendió (*🎙 Entendí: «recuérdame a las 5 llamar a Laura»*) y te responde con una
nota de voz y por escrito. También puedes contestar "sí" o "no" con una nota de voz cuando te pide
una confirmación.

### Activarlas (una sola vez)

```bash
uv sync
uv run jarvis preparar-voz
```

- `uv sync` instala la transcripción ([faster-whisper](https://github.com/SYSTRAN/faster-whisper)) y
  la voz ([Piper](https://github.com/OHF-Voice/piper1-gpl)), las dos locales.
- `preparar-voz` descarga, una sola vez, el modelo de Whisper (`small`, unos 500 MB) y la voz de
  Piper (unos 60 MB) a `~/.config/jarvis/voz/`.

Si JARVIS ya corría en segundo plano, reinícialo para que use la versión nueva:
`uv run jarvis quitar-telegram` y luego `uv run jarvis programar-telegram`.
`uv run jarvis estado` muestra si las notas de voz y las respuestas con voz están activas.

### Respuestas con voz

Por defecto JARVIS responde **en espejo**: con voz (y el texto debajo) cuando le hablas, y solo por
escrito cuando le escribes. Con **/voz** eliges entre *Si me hablas*, *Siempre* o *Nunca*; tu
elección se guarda.

- Por defecto la voz se genera en tu PC con Piper: el texto de las respuestas no sale del equipo.
  Para una voz más natural, usa la de Azure (sección siguiente).
- Se leen hasta unos 1000 caracteres (sin enlaces ni emojis); el texto completo llega siempre por
  escrito. Si la voz falla, la respuesta llega igual por escrito.
- Para cambiar de voz, escucha las muestras en <https://rhasspy.github.io/piper-samples/>, pon su
  nombre en `.env` (por ejemplo `JARVIS_PIPER_VOZ=es_AR-daniela-high`) y vuelve a ejecutar
  `preparar-voz`.
- Para desactivarlas: `JARVIS_RESPUESTA_VOZ=no`.
- Para escuchar cómo suena la voz configurada, sin pasar por Telegram:
  `uv run python -m jarvis probar-voz "Hola, soy JARVIS"`.

### Voz de Azure (más natural)

Las voces neuronales de Microsoft (Azure AI Speech) suenan casi humanas, y hay voces con acento
colombiano: **Salomé** (`es-CO-SalomeNeural`, la predeterminada) y **Gonzalo**
(`es-CO-GonzaloNeural`). El plan gratuito incluye 0,5 millones de caracteres al mes, mucho más de lo
que suele usar JARVIS; al llegar al límite se frena (no cobra) y JARVIS responde con Piper.

**Privacidad:** con Azure, el texto de las respuestas habladas se envía a Microsoft para
convertirlo en voz (tu voz no: la transcripción sigue en el PC).

1. Crea una cuenta en <https://portal.azure.com> (Microsoft suele pedir una tarjeta solo para
   verificar tu identidad).
2. En el buscador de arriba escribe **Speech** y elige **Speech services** → **Crear**:
   - **Grupo de recursos:** crea uno nuevo, por ejemplo `jarvis`.
   - **Región:** la más cercana (por ejemplo, **East US**).
   - **Nombre:** cualquiera, por ejemplo `jarvis-voz`.
   - **Plan de tarifa:** **Free F0**.
   - Pulsa **Revisar y crear** → **Crear**, y luego **Ir al recurso**.
3. En el recurso, abre **Claves y punto de conexión** (*Keys and Endpoint*) y copia la **Clave 1**
   y la **Ubicación/Región** (por ejemplo `eastus`).
4. En tu `.env`:

   ```
   JARVIS_RESPUESTA_VOZ=azure
   AZURE_SPEECH_KEY=la-clave-que-copiaste
   AZURE_SPEECH_REGION=eastus
   JARVIS_AZURE_VOZ=es-CO-SalomeNeural
   ```

5. Pruébala: `uv run python -m jarvis probar-voz`. Si algo está mal (clave, región, voz), lo dice.
   Después reinicia JARVIS (`quitar-telegram` y `programar-telegram`).

Piper sigue de respaldo: si no hay internet o Azure falla, JARVIS responde con Piper (si lo
descargaste con `preparar-voz`), y si tampoco, por escrito. La clave nunca aparece en los registros.
Más voces en español: busca `es-` en la
[lista de voces de Azure](https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts).

### Privacidad y límites

- El audio nunca sale de tu PC ni se guarda en disco: se transcribe en memoria y se descarta.
  Lo transcrito queda en el historial del chat como cualquier mensaje (se borra a los 30 días).
- Notas de hasta 5 minutos. Whisper y Piper se cargan al arrancar JARVIS, así que la primera nota
  no espera de más (si la mandas justo al encender el PC, puede tardar unos segundos).
- Si las transcripciones fallan a menudo, prueba un modelo mayor en `.env`
  (`JARVIS_WHISPER_MODELO=medium` o `large-v3-turbo`, más precisos y más lentos) o uno menor si van
  lentas (`base`). Después de cambiarlo, vuelve a ejecutar `preparar-voz`.
- Para desactivar las notas de voz: `JARVIS_TRANSCRIPCION=no`.
- Si `preparar-voz` falla con un error de certificados, es el mismo caso del antivirus que se
  explica en la sección de Telegram (la descarga es desde `huggingface.co`).

## "Hey JARVIS" en el PC

Habla con JARVIS sin tocar el teléfono: di **"Hey JARVIS"** cerca del PC, espera el tono (o sigue
de corrido) y haz tu pedido: *"Hey JARVIS, ¿qué tengo hoy?"*, *"…recuérdame a las 5 llamar a
Laura"*, *"…anota renovar el pasaporte"*. Te responde en voz alta por los parlantes, con la misma
memoria, pendientes, recordatorios y calendario que en Telegram. Si una acción necesita tu
confirmación, te pregunta y respondes "sí" o "no".

### Activarlo

1. Descarga sus modelos (unos 4 MB; si ya ejecutaste `preparar-voz` antes, vuelve a hacerlo):

   ```bash
   uv run python -m jarvis preparar-voz
   ```

2. Pruébalo en primer plano. La consola muestra cuándo se activa, qué entendió y qué responde:

   ```bash
   uv run python -m jarvis escuchar
   ```

3. Si funciona bien, actívalo en segundo plano. Pon `JARVIS_PALABRA_ACTIVACION=si` en `.env` y
   reinicia JARVIS (`quitar-telegram` y luego `programar-telegram`).

Usa el micrófono y los parlantes predeterminados de Windows. Necesita las notas de voz y las
respuestas con voz activas (son las que vienen por defecto).

### Ajustes y problemas comunes

- **Se activa sin que lo llames**: sube `JARVIS_ACTIVACION_UMBRAL` (por ejemplo, `0.7`).
  **No se activa**: bájalo (por ejemplo, `0.3`) y di "Hey JARVIS" con claridad. La frase es en
  inglés porque el modelo viene entrenado así; más adelante se podrá entrenar uno para "Oye JARVIS".
- **"No te escuché"**: empieza a hablar en los 4 segundos siguientes al tono, o habla más cerca del
  micrófono. El pedido termina cuando haces una pausa corta (menos de un segundo; como máximo dura 15 s).
- **No arranca**: `uv run python -m jarvis estado` dice qué falta. Si Windows bloquea alguna
  biblioteca de audio ("Control de aplicaciones"), avísame con el mensaje exacto.
- Si JARVIS corre en segundo plano con la palabra de activación, `escuchar` también lo tendrá
  escuchando: para probar solo en primer plano, detén antes el de segundo plano.

### Privacidad

Viene **apagado**: el micrófono solo se usa si pones `JARVIS_PALABRA_ACTIVACION=si` (o mientras
corre `escuchar`). El audio se analiza en memoria en trozos de 80 ms solo para detectar la frase y se
descarta; solo se graba lo que dices después de "Hey JARVIS", también en memoria, para
transcribirlo en tu PC. Nada se guarda en disco ni sale del equipo (salvo el texto de tu pedido, que
va a Claude como cualquier mensaje). Windows muestra el ícono del micrófono en uso mientras escucha.

## Resumen diario

JARVIS puede enviarte cada mañana, de lunes a viernes, tus reuniones del día y un comentario breve
(choques de horario, huecos libres, qué preparar). Si la API de Anthropic falla, el resumen llega
igual con la agenda sin comentario. Puede llegar por **Telegram** (recomendado) o por **Gmail**.

### Por Telegram

1. Configura el bot (pasos 1 y 2 de la sección anterior).
2. En tu `.env`:

   ```bash
   JARVIS_RESUMEN_CANAL=telegram
   JARVIS_RESUMEN_HORA=07:00
   ```

   El resumen llega aunque `jarvis telegram` no esté corriendo.

### Por Gmail

1. Habilita la **Gmail API** en tu proyecto de Google Cloud (igual que la Calendar API).
2. En tu `.env`:

   ```bash
   JARVIS_RESUMEN_CANAL=gmail
   JARVIS_RESUMEN_DESTINATARIO=tu-correo@gmail.com
   JARVIS_RESUMEN_HORA=07:00
   ```

3. Vuelve a autorizar para añadir el permiso de envío (`gmail.send`, solo enviar):

   ```bash
   uv run jarvis google-login
   ```

### Probar y programar (ambos canales)

1. Prueba sin enviar nada (muestra el resumen en la consola):

   ```bash
   uv run jarvis resumen --dry-run
   ```

2. Envía uno de verdad:

   ```bash
   uv run jarvis resumen
   ```

   Solo se envía un resumen por día; usa `--force` para reenviarlo. En modo prueba (`--dry-run`),
   al final se indica por qué canal se enviaría.

3. Prográmalo (Windows). Si cambias de canal, vuelve a ejecutarlo:

   ```bash
   uv run jarvis programar-resumen
   ```

   La tarea aparece en el **Programador de tareas**, carpeta **JARVIS**. Corre en segundo plano,
   sin abrir ventanas, solo con tu sesión de Windows iniciada. Si el PC estaba apagado a esa hora,
   se ejecuta al encenderlo; si no hay internet, reintenta hasta 3 veces, cada 10 minutos.
   Para quitarla: `uv run jarvis quitar-resumen`. En Mac o Linux, el comando muestra la línea
   de `cron` que debes añadir.

Cada ejecución queda registrada (solo el resultado, nunca el contenido) en
`~/.config/jarvis/logs/resumen.log`.

## Si responde lento

Cada respuesta pasa por varias etapas: transcribir tu voz (Whisper), pensar la respuesta (Claude) y
generar la voz (Piper). El registro anota cuánto tarda cada una, sin el contenido: míralo al final de
`uv run python -m jarvis estado` (líneas como *"Nota de voz de 4 s transcrita en 1.8 s"* o
*"Respuesta de la IA en 3.2 s"*). Con `escuchar`, esos tiempos salen en la consola.

Las llamadas a Telegram también se anotan (*"Telegram sendMessage en 0.25 s (conexión
reutilizada)"*): JARVIS mantiene abierta la conexión y la reutiliza, así que solo la primera de cada
respuesta paga el saludo inicial. El registro completo está en `~/.config/jarvis/logs/telegram.log`.

- **La transcripción es lo más lento**: prueba un modelo menor, `JARVIS_WHISPER_MODELO=base` (más
  rápido, algo menos preciso), y vuelve a ejecutar `preparar-voz`.
- **La IA es lo más lento**: `JARVIS_ESFUERZO=low` (por defecto) es lo más rápido; si las
  respuestas te parecen flojas, prueba `medium`.

## Ver el estado

```bash
uv run jarvis estado
```

Resume la configuración (calendario, canal del resumen, Telegram, voz, clima), cuántos recordatorios,
pendientes y datos de memoria hay, el gasto estimado en Claude, si las tareas programadas están activas y las últimas líneas de
los registros. Los registros solo contienen resultados, nunca el
texto de tus mensajes.

## Configuración

| Variable | Descripción | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic (obligatoria) | |
| `JARVIS_MODEL` | Modelo de Claude | `claude-sonnet-5-5` |
| `JARVIS_AVISO_REUNION` | Minutos antes de cada reunión para avisarte (`0` = sin aviso) | `10` |
| `JARVIS_VISTAZO_MANANA` | Hora del vistazo a mañana, de domingo a jueves (`no` = sin vistazo) | `20:00` |
| `JARVIS_CORREO` | Avisos de correos de clientes y lectura de Gmail: `si` o `no` | `si` |
| `JARVIS_CORREO_MINUTOS` | Cada cuántos minutos revisa los correos (1 a 60) | `2` |
| `JARVIS_BUSQUEDA` | Búsqueda en internet y lectura de enlaces: `si` o `no` | `si` |
| `JARVIS_CIUDAD` / `JARVIS_PAIS` | Tu ciudad y país (código de dos letras), para el clima y las búsquedas locales | |
| `JARVIS_ESFUERZO` | Cuánto razona Claude en el chat y la voz: `low` (rápido), `medium`, `high`, `xhigh`, `max` | `low` |
| `JARVIS_TIMEZONE` | Zona horaria IANA | la del sistema |
| `JARVIS_CALENDAR` | `sample` o `google` | `sample` |
| `GOOGLE_CALENDAR_ID` | Calendario a leer | `primary` |
| `GOOGLE_CREDENTIALS_FILE` | Credenciales OAuth descargadas | `~/.config/jarvis/credentials.json` |
| `GOOGLE_TOKEN_FILE` | Token de autorización | `~/.config/jarvis/token.json` |
| `JARVIS_RESUMEN_CANAL` | Canal del resumen: `telegram` o `gmail` | `gmail` |
| `JARVIS_RESUMEN_DESTINATARIO` | Con Gmail: correo que recibe el resumen (vacío = desactivado) | |
| `JARVIS_RESUMEN_HORA` | Hora del resumen, de lunes a viernes | `07:00` |
| `JARVIS_DB_PATH` | Base de datos local (SQLite) | `~/.config/jarvis/jarvis.db` |
| `TELEGRAM_BOT_TOKEN` | Token del bot (de @BotFather) | |
| `TELEGRAM_OWNER_ID` | Tu ID de Telegram, el único que JARVIS atiende (`telegram-vincular`) | |
| `JARVIS_TRANSCRIPCION` | Notas de voz: `local` (Whisper en el PC) o `no` (desactivadas) | `local` |
| `JARVIS_WHISPER_MODELO` | Modelo de Whisper: `tiny`, `base`, `small`, `medium`, `large-v3-turbo`… | `small` |
| `JARVIS_RESPUESTA_VOZ` | Respuestas con voz: `local` (Piper en el PC), `azure` (voz de Microsoft) o `no` | `local` |
| `JARVIS_PIPER_VOZ` | Voz de Piper (`<idioma>-<nombre>-<calidad>`); con Azure, la de respaldo | `es_MX-ald-medium` |
| `AZURE_SPEECH_KEY` | Con `JARVIS_RESPUESTA_VOZ=azure`: clave del recurso Speech | |
| `AZURE_SPEECH_REGION` | Con Azure: región del recurso (por ejemplo `eastus`) | |
| `JARVIS_AZURE_VOZ` | Con Azure: nombre de la voz | `es-CO-SalomeNeural` |
| `JARVIS_PALABRA_ACTIVACION` | "Hey JARVIS" en el PC, en segundo plano: `si` o `no` | `no` |
| `JARVIS_ACTIVACION_UMBRAL` | Sensibilidad de "Hey JARVIS" (0 a 1; más alto, menos activaciones por error) | `0.5` |

## Tests

```bash
uv run pytest
```

Los tests no llaman a ninguna API real (Anthropic, Google, Telegram, Open-Meteo, Whisper, Piper y el
Programador de tareas están simulados) y no necesitan el grupo de voz (`uv sync --no-group voz`). GitHub Actions los ejecuta en cada pull request y en cada push a `main`.

## Documentación

- Visión y próximos pasos: [`docs/vision.md`](docs/vision.md)
- Requisitos: [`docs/srs.md`](docs/srs.md)
- Decisiones de arquitectura: [`docs/adr/`](docs/adr/)
