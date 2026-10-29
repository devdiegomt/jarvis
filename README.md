# JARVIS

[![Tests](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml/badge.svg)](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml)

Asistente personal con IA que ayuda a organizar el día: recuerda reuniones, avisa de
mensajes y ejecuta tareas simples. Construido con el SDK oficial de Anthropic y un loop
de agente propio (sin frameworks).

## Estado

**v0.4**: lee tu Google Calendar (solo lectura), te envía por Gmail un resumen del día de lunes
a viernes y puedes chatear con JARVIS por WhatsApp. El envío de mensajes a terceros sigue simulado.
Ver el roadmap completo en [`CLAUDE.md`](CLAUDE.md).

## Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Una API key de Anthropic
- (Opcional) Una cuenta de Google para leer tu calendario real
- (Opcional) Una cuenta de Meta for Developers y [ngrok](https://ngrok.com/) para WhatsApp

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
   Si vas a usar el resumen diario, haz lo mismo con **Gmail API**.
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
3. Acepta los permisos que se piden (ver tus calendarios y, si configuraste el resumen,
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

## Resumen diario por correo

JARVIS puede enviarte cada mañana, de lunes a viernes, un correo con tus reuniones del día y un
comentario breve (choques de horario, huecos libres, qué preparar). Si la API de Anthropic falla,
el correo llega igual con la agenda sin comentario.

1. Habilita la **Gmail API** en tu proyecto de Google Cloud (igual que la Calendar API).
2. En tu `.env`:

   ```bash
   JARVIS_RESUMEN_DESTINATARIO=tu-correo@gmail.com
   JARVIS_RESUMEN_HORA=07:00
   ```

3. Vuelve a autorizar para añadir el permiso de envío:

   ```bash
   uv run jarvis google-login
   ```

4. Prueba sin enviar nada (muestra el correo en la consola):

   ```bash
   uv run jarvis resumen --dry-run
   ```

5. Envía uno de verdad:

   ```bash
   uv run jarvis resumen
   ```

   Solo se envía un resumen por día; usa `--force` para reenviarlo.

6. Prográmalo (Windows):

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

## Chatear con JARVIS por WhatsApp

JARVIS tiene su propio número de WhatsApp (el número de prueba gratuito de Meta) y solo atiende
**tu** número. Funciona mientras tu PC esté encendido con `uv run jarvis whatsapp` y ngrok
corriendo. Responder a tus mensajes es gratis (Meta no cobra las respuestas dentro de las 24 horas
siguientes a tu mensaje).

```
Tu WhatsApp → Meta → ngrok (URL fija) → tu PC: uv run jarvis whatsapp → respuesta
```

### 1. Crear la app en Meta (una sola vez)

1. Entra a [Meta for Developers](https://developers.facebook.com/), ve a **Mis apps → Crear app**
   y elige el caso de uso **Conectar con clientes a través de WhatsApp**. Vincúlala a un
   portafolio comercial (se crea en el mismo asistente si no tienes uno).
2. En **WhatsApp → Configuración de la API** verás el **número de prueba** de Meta:
   - Copia el **Identificador del número de teléfono** en `WHATSAPP_PHONE_NUMBER_ID`.
   - En **Para**, agrega tu número personal y verifícalo con el código que te llega por WhatsApp.
3. Copia la **clave secreta de la app** (**Configuración de la app → Básica**) en
   `WHATSAPP_APP_SECRET`.
4. Crea un **token permanente** (el que aparece en la pantalla de la API caduca en 24 horas):
   1. En [Configuración del negocio](https://business.facebook.com/settings) ve a
      **Usuarios → Usuarios del sistema → Agregar** (rol *Administrador*).
   2. **Asignar activos**: tu app y tu cuenta de WhatsApp, con control total.
   3. **Generar token**: elige tu app, caducidad **Nunca** y los permisos
      `whatsapp_business_messaging` y `whatsapp_business_management`.
   4. Copia el token en `WHATSAPP_ACCESS_TOKEN`.
5. Inventa un texto aleatorio para `WHATSAPP_VERIFY_TOKEN`, por ejemplo con:

   ```bash
   uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

6. Pon tu número con código de país, solo dígitos, en `WHATSAPP_OWNER_NUMBER`
   (por ejemplo `573001234567`).

> El token, la clave secreta y el token de verificación son secretos: solo van en tu `.env`.

### 2. Preparar ngrok (una sola vez)

1. Crea una cuenta en [ngrok](https://ngrok.com/) e instálalo (en Windows: `winget install ngrok.ngrok`).
2. Configura tu authtoken (lo ves en el panel de ngrok):

   ```bash
   ngrok config add-authtoken TU_AUTHTOKEN
   ```

3. En el panel de ngrok, ve a **Domains** y reserva tu **dominio fijo gratuito**
   (algo como `tu-nombre.ngrok-free.app`).

### 3. Arrancar JARVIS y conectar el webhook

1. En una terminal:

   ```bash
   uv run jarvis whatsapp
   ```

2. En otra terminal (con tu dominio):

   ```bash
   ngrok http --url=tu-nombre.ngrok-free.app 8000
   ```

3. En Meta, **WhatsApp → Configuración → Webhook → Editar**:
   - URL de devolución de llamada: `https://tu-nombre.ngrok-free.app/webhook`
   - Token de verificación: el mismo de `WHATSAPP_VERIFY_TOKEN`
   - Pulsa **Verificar y guardar** (JARVIS y ngrok deben estar corriendo).
4. En **Campos del webhook**, suscríbete a **messages**.
5. Desde tu WhatsApp, escribe "hola" al número de prueba de Meta. ¡JARVIS responde!

### Cómo se usa

- Escribe como en la consola: *"¿Qué tengo hoy?"*, *"¿Y el jueves?"*.
- Si JARVIS quiere hacer algo con efectos externos, te pide confirmación y tu siguiente mensaje
  (`s` o `n`) es la respuesta. Sin respuesta en 5 minutos, la acción se cancela.
- `/nuevo` empieza una conversación nueva; `/ayuda` muestra los comandos. Tras 6 horas sin
  mensajes, la siguiente conversación empieza de cero.
- Por ahora solo entiende mensajes de texto.

El historial se guarda en tu equipo (`jarvis.db`) y las conversaciones de más de 30 días se borran
solas. El log (`~/.config/jarvis/logs/whatsapp.log`) registra solo IDs y resultados, nunca el texto.

### Problemas comunes

- **JARVIS no responde y el log dice "número no autorizado"**: revisa `WHATSAPP_OWNER_NUMBER`.
  El log muestra los 4 últimos dígitos del número que escribió. En algunos países (como México o
  Argentina) WhatsApp añade un dígito tras el código de país (`521…`, `549…`): prueba con ese
  formato o con el número tal como aparece en la lista **Para** de Meta.
- **"Tu número no está en la lista de destinatarios permitidos"**: agrégalo en **Para**
  (paso 1.2).
- **"El token de WhatsApp no es válido o caducó"**: usa el token permanente (paso 1.4).
- **Meta no verifica el webhook**: comprueba que `uv run jarvis whatsapp` y ngrok estén corriendo
  y que el token de verificación coincida.

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
| `JARVIS_RESUMEN_DESTINATARIO` | Correo que recibe el resumen diario (vacío = desactivado) | |
| `JARVIS_RESUMEN_HORA` | Hora del resumen, de lunes a viernes | `07:00` |
| `JARVIS_DB_PATH` | Base de datos local (SQLite) | `~/.config/jarvis/jarvis.db` |
| `WHATSAPP_ACCESS_TOKEN` | Token permanente de la WhatsApp Cloud API | |
| `WHATSAPP_PHONE_NUMBER_ID` | Identificador del número de JARVIS en Meta | |
| `WHATSAPP_APP_SECRET` | Clave secreta de la app (verifica la firma de los avisos) | |
| `WHATSAPP_VERIFY_TOKEN` | Texto que inventas para verificar el webhook | |
| `WHATSAPP_OWNER_NUMBER` | Tu número (el único que JARVIS atiende) | |
| `WHATSAPP_PORT` | Puerto local del servidor | `8000` |
| `WHATSAPP_API_VERSION` | Versión de la Graph API | `v25.0` |

## Tests

```bash
uv run pytest
```

Los tests no llaman a ninguna API real (Anthropic, Google, Meta y el Programador de tareas están
simulados). GitHub Actions los ejecuta en cada pull request y en cada push a `main`.

## Documentación

- Requisitos: [`docs/srs.md`](docs/srs.md)
- Decisiones de arquitectura: [`docs/adr/`](docs/adr/)
