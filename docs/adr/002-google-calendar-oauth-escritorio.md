# ADR 002: Google Calendar con OAuth de escritorio y permiso de solo lectura

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.2

## Contexto

En la v0.2, `get_reuniones` debe leer el calendario real del usuario en Google Calendar.
JARVIS es por ahora una aplicación de consola que corre en el equipo del usuario, con una
sola persona usándola. Hay que decidir cómo autenticarse con Google, qué permisos pedir y
cómo encaja la fuente real con los datos de ejemplo de la v0.1.

## Decisión

1. **OAuth 2.0 para aplicaciones de escritorio** (`InstalledAppFlow` de `google-auth-oauthlib`)
   con la **API de Google Calendar directa** (`google-api-python-client`).
2. **Solo permiso de lectura**: `https://www.googleapis.com/auth/calendar.readonly`.
   La v0.2 no necesita escribir; si una versión futura crea eventos, pedirá el permiso más amplio
   en ese momento y esa tool requerirá confirmación del usuario.
3. **Login como comando aparte** (`uv run jarvis google-login`). El chat nunca abre el navegador
   a mitad de una conversación: si la autorización falta o caducó, la tool devuelve un error
   (`is_error`) que indica ejecutar el login.
4. **Credenciales y token fuera del repositorio**, por defecto en `~/.config/jarvis/`. El token
   se guarda con permisos `600`. Además, el `.gitignore` excluye `credentials*.json` y `token*.json`.
5. **Fuente de calendario explícita** con `JARVIS_CALENDAR=sample|google`. Si se elige `google` y
   no hay autorización, JARVIS no arranca y explica qué hacer. No hay cambio silencioso a datos de
   ejemplo: el usuario podría creer que ve su agenda real cuando no es así.
6. **Solo el calendario principal** (`GOOGLE_CALENDAR_ID=primary`, configurable).
7. Las fuentes de calendario comparten la interfaz `CalendarSource` (`jarvis.agenda`). La tool
   recibe la fuente por parámetro, así los tests usan una fuente falsa y `agent.py` no cambia.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Cuenta de servicio | No puede acceder al calendario de una cuenta personal de Gmail sin compartirlo manualmente, y la delegación de dominio solo existe en Google Workspace. |
| API key | Solo da acceso a datos públicos; el calendario del usuario es privado. |
| Conector MCP de Google Calendar | Ataría JARVIS a un cliente de Claude concreto. JARVIS debe funcionar como aplicación propia (consola hoy; WhatsApp y tareas programadas después). |
| CalDAV | Protocolo genérico pero más complejo de configurar con Google, y peor documentado que la API oficial. |
| Permiso `calendar` completo desde ya | Viola el principio de mínimo privilegio; ninguna tool de la v0.2 escribe. |
| Abrir el navegador automáticamente desde el chat | Interrumpe la conversación y no funciona en entornos sin navegador (SSH, tareas programadas de la v0.3). |

## Consecuencias

**Positivas**

- Mínimo privilegio: aunque el token se filtrara, no permite modificar el calendario.
- Funciona con cualquier cuenta de Gmail, sin servidor propio.
- Los fallos de Google (red, token revocado, API desactivada) llegan al modelo como errores
  claros en español y la sesión sigue.
- Agregar otra fuente (Outlook, CalDAV) solo requiere implementar `CalendarSource`.

**Negativas**

- El usuario debe crear un proyecto en Google Cloud y descargar credenciales (pasos en el README).
- Mientras la app OAuth está en modo *Prueba*, Google caduca la autorización a los 7 días; hay que
  repetir el login o publicar la app (sigue siendo de uso personal, con aviso de app no verificada).
- El modo multiusuario del roadmap necesitará otro flujo (OAuth web con servidor); se decidirá en
  su propio ADR.
