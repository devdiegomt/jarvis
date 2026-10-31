# JARVIS

[![Tests](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml/badge.svg)](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml)

Asistente personal con IA que ayuda a organizar el día: recuerda reuniones, avisa de
mensajes y ejecuta tareas simples. Construido con el SDK oficial de Anthropic y un loop
de agente propio (sin frameworks).

## Estado

**v0.10**: lee tu Google Calendar (solo lectura), chateas con JARVIS por Telegram (también en
segundo plano) escribiéndole o con notas de voz, y te responde también con voz; en el PC lo llamas
con "Hey JARVIS" y te contesta en voz alta. Te crea recordatorios, lleva tu lista de pendientes,
recuerda lo que le cuentas de ti entre conversaciones y te envía un resumen del día de lunes a
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

JARVIS solo pide permiso de **lectura** del calendario (`calendar.readonly`): no puede crear,
modificar ni borrar eventos. Si activas el resumen diario, pide además permiso para **enviar**
correos (`gmail.send`), sin acceso a leerlos ni borrarlos. La autorización se guarda en tu equipo,
fuera del repositorio.

### 1. Crear las credenciales en Google Cloud (una sola vez)

1. Entra a [Google Cloud Console](https://console.cloud.google.com/) y crea un proyecto nuevo
   (por ejemplo, `jarvis`).
2. Ve a **APIs y servicios → Biblioteca**, busca **Google Calendar API** y pulsa **Habilitar**.
   Si vas a recibir el resumen diario por Gmail, haz lo mismo con **Gmail API**.
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
3. Acepta los permisos que se piden (ver tus calendarios y, si el resumen va por Gmail,
   enviar correos). Deja todas las casillas marcadas.

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

- La voz se genera en tu PC con Piper: el texto de las respuestas no sale del equipo.
- Se leen hasta unos 1000 caracteres (sin enlaces ni emojis); el texto completo llega siempre por
  escrito. Si la voz falla, la respuesta llega igual por escrito.
- Para cambiar de voz, escucha las muestras en <https://rhasspy.github.io/piper-samples/>, pon su
  nombre en `.env` (por ejemplo `JARVIS_PIPER_VOZ=es_AR-daniela-high`) y vuelve a ejecutar
  `preparar-voz`.
- Para desactivarlas: `JARVIS_RESPUESTA_VOZ=no`.

### Privacidad y límites

- El audio nunca sale de tu PC ni se guarda en disco: se transcribe en memoria y se descarta.
  Lo transcrito queda en el historial del chat como cualquier mensaje (se borra a los 30 días).
- Notas de hasta 5 minutos. La primera nota tras arrancar JARVIS tarda unos segundos más, mientras
  carga el modelo.
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
  micrófono. El pedido termina cuando haces una pausa de un segundo (como máximo dura 15 s).
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

## Ver el estado

```bash
uv run jarvis estado
```

Resume la configuración (calendario, canal del resumen, Telegram, voz), cuántos recordatorios,
pendientes y datos de memoria hay, si las tareas programadas están activas y las últimas líneas de
los registros. Los registros solo contienen resultados, nunca el
texto de tus mensajes.

## Configuración

| Variable | Descripción | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic (obligatoria) | |
| `JARVIS_MODEL` | Modelo de Claude | `claude-sonnet-5-5` |
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
| `JARVIS_RESPUESTA_VOZ` | Respuestas con voz: `local` (Piper en el PC) o `no` (desactivadas) | `local` |
| `JARVIS_PIPER_VOZ` | Voz de Piper (`<idioma>-<nombre>-<calidad>`) | `es_MX-ald-medium` |
| `JARVIS_PALABRA_ACTIVACION` | "Hey JARVIS" en el PC, en segundo plano: `si` o `no` | `no` |
| `JARVIS_ACTIVACION_UMBRAL` | Sensibilidad de "Hey JARVIS" (0 a 1; más alto, menos activaciones por error) | `0.5` |

## Tests

```bash
uv run pytest
```

Los tests no llaman a ninguna API real (Anthropic, Google, Telegram, Whisper, Piper y el Programador
de tareas están simulados) y no necesitan el grupo de voz (`uv sync --no-group voz`). GitHub Actions los ejecuta en cada pull request y en cada push a `main`.

## Documentación

- Requisitos: [`docs/srs.md`](docs/srs.md)
- Decisiones de arquitectura: [`docs/adr/`](docs/adr/)
