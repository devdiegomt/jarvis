# JARVIS

[![Tests](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml/badge.svg)](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml)

Asistente personal con IA que ayuda a organizar el día: recuerda reuniones, avisa de
mensajes y ejecuta tareas simples. Construido con el SDK oficial de Anthropic y un loop
de agente propio (sin frameworks).

## Estado

**v0.5**: lee tu Google Calendar (solo lectura), puedes chatear con JARVIS por Telegram y te envía
un resumen del día de lunes a viernes (por Telegram o Gmail). El envío de mensajes a terceros sigue
simulado.
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

Resume la configuración (calendario, canal del resumen, Telegram), si las tareas programadas están
activas y las últimas líneas de los registros. Los registros solo contienen resultados, nunca el
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

## Tests

```bash
uv run pytest
```

Los tests no llaman a ninguna API real (Anthropic, Google, Telegram y el Programador de tareas
están simulados). GitHub Actions los ejecuta en cada pull request y en cada push a `main`.

## Documentación

- Requisitos: [`docs/srs.md`](docs/srs.md)
- Decisiones de arquitectura: [`docs/adr/`](docs/adr/)
