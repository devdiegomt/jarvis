# JARVIS

[![Tests](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml/badge.svg)](https://github.com/devdiegomt/jarvis/actions/workflows/tests.yml)

Asistente personal con IA que ayuda a organizar el día: recuerda reuniones, avisa de
mensajes y ejecuta tareas simples. Construido con el SDK oficial de Anthropic y un loop
de agente propio (sin frameworks).

## Estado

**v0.2**: lee tu Google Calendar (solo lectura). El envío de mensajes sigue simulado.
Ver el roadmap completo en [`CLAUDE.md`](CLAUDE.md).

## Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Una API key de Anthropic
- (Opcional) Una cuenta de Google para leer tu calendario real

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

JARVIS solo pide permiso de **lectura** (`calendar.readonly`): no puede crear, modificar
ni borrar eventos. La autorización se guarda en tu equipo, fuera del repositorio.

### 1. Crear las credenciales en Google Cloud (una sola vez)

1. Entra a [Google Cloud Console](https://console.cloud.google.com/) y crea un proyecto nuevo
   (por ejemplo, `jarvis`).
2. Ve a **APIs y servicios → Biblioteca**, busca **Google Calendar API** y pulsa **Habilitar**.
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
3. Acepta el permiso de ver tus calendarios.

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

## Tests

```bash
uv run pytest
```

Los tests no llaman a ninguna API real (Anthropic y Google están simulados). GitHub Actions
los ejecuta en cada pull request y en cada push a `main`.

## Documentación

- Decisiones de arquitectura: [`docs/adr/`](docs/adr/)
