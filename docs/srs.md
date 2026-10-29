# Especificación de requisitos de software (SRS): JARVIS

- **Versión del documento:** 1.0 (cubre hasta la v0.4)
- **Fecha:** 2026-10-29
- **Estado:** vivo; se actualiza al cerrar cada versión

## 1. Introducción

### 1.1 Propósito

Este documento describe qué debe hacer JARVIS y con qué restricciones. Sirve de referencia para
implementar cada versión, para escribir sus tests y para quien revise el proyecto como portafolio.
Las decisiones de diseño (el *cómo*) están en los ADR de [`docs/adr/`](adr/).

### 1.2 Alcance

JARVIS es un asistente personal con IA que ayuda a una persona a organizar su día: consulta sus
reuniones, le envía un resumen diario y conversa con ella por consola y por WhatsApp. Se construye
en versiones pequeñas (ver el roadmap en [`CLAUDE.md`](../CLAUDE.md)).

### 1.3 Definiciones

| Término | Significado |
|---|---|
| Usuario | La persona dueña de JARVIS (por ahora, una sola). |
| Agente | El loop que conversa con Claude y ejecuta tools (ADR 001). |
| Tool | Función que el modelo puede pedir ejecutar (por ejemplo, `get_reuniones`). |
| Efecto externo | Acción que cambia algo fuera de JARVIS: enviar un mensaje, crear o borrar un evento. |
| Fuente de calendario | Origen de las reuniones: datos de ejemplo o Google Calendar. |
| Canal | Vía por la que el usuario habla con JARVIS o recibe avisos: consola, Gmail, WhatsApp. |
| Conversación | Secuencia de mensajes con historial compartido; en WhatsApp termina por inactividad o con `/nuevo`. |

## 2. Descripción general

### 2.1 Perspectiva

JARVIS es una aplicación Python que corre en el PC del usuario (Windows como plataforma principal).
Usa servicios externos: la API de Anthropic (modelo de lenguaje), Google Calendar y Gmail
(OAuth del propio usuario) y la WhatsApp Cloud API de Meta (con un número propio de JARVIS).

### 2.2 Usuarios

Un único usuario técnico-intermedio: sabe usar una terminal y seguir pasos de configuración en
Google Cloud y Meta for Developers, guiado por el README.

### 2.3 Restricciones

- **R-1.** Python 3.12, dependencias gestionadas con `uv`.
- **R-2.** SDK oficial de Anthropic con loop propio, sin frameworks de agentes (ADR 001).
- **R-3.** Modelo configurable por `JARVIS_MODEL`.
- **R-4.** Solo vías oficiales de cada servicio (sin automatizar WhatsApp Web ni similares).
- **R-5.** Sin servidores propios en la nube por ahora: todo corre en el PC del usuario.

### 2.4 Supuestos

- El PC está encendido y con sesión iniciada cuando se espera el resumen o una respuesta por WhatsApp.
- El usuario tiene una cuenta de Google y una de Meta for Developers.

## 3. Requisitos funcionales

### v0.1: agente por consola

- **RF-01.** El usuario conversa con JARVIS desde la consola (`uv run jarvis`); `salir` termina.
- **RF-02.** El historial se mantiene durante la sesión de consola.
- **RF-03.** El agente puede usar tools; como máximo 10 iteraciones de tool use por mensaje.
- **RF-04.** Las tools se registran en un registro central; agregar una no requiere modificar el agente.
- **RF-05.** Si una tool falla, el error vuelve al modelo como resultado (`is_error`) y la sesión sigue.
- **RF-06.** Toda tool con efectos externos pide confirmación (s/n) antes de ejecutarse.
- **RF-07.** `enviar_mensaje(destinatario, texto)` está simulada: muestra el mensaje y pide confirmación.

### v0.2: Google Calendar

- **RF-08.** `get_reuniones` devuelve las reuniones de una fecha o de un rango de hasta 14 días.
- **RF-09.** La fuente de calendario se elige con `JARVIS_CALENDAR=sample|google`; con `google`
  y sin autorización, JARVIS no arranca y explica qué hacer.
- **RF-10.** `uv run jarvis google-login` autoriza el acceso con OAuth de escritorio.
- **RF-11.** Las horas se muestran en la zona horaria del usuario (`JARVIS_TIMEZONE`); se
  distinguen eventos de día completo y se omiten los cancelados o rechazados.

### v0.3: resumen diario por Gmail

- **RF-12.** `uv run jarvis resumen` envía por Gmail un correo de texto con la agenda del día y un
  comentario breve generado por Claude.
- **RF-13.** Si Claude falla, el correo se envía igual, con la agenda y sin comentario.
- **RF-14.** No se envía más de un resumen por día, salvo con `--force`; `--dry-run` lo muestra
  sin enviarlo.
- **RF-15.** `programar-resumen` lo programa de lunes a viernes a `JARVIS_RESUMEN_HORA`;
  `quitar-resumen` lo elimina.
- **RF-16.** El destinatario es fijo por configuración; el modelo no puede cambiarlo.

### v0.4: chat por WhatsApp

- **RF-17.** `uv run jarvis whatsapp` arranca un servidor que recibe los mensajes de WhatsApp y
  responde con el mismo agente y las mismas tools que la consola.
- **RF-18.** Solo se atienden mensajes del número del usuario (`WHATSAPP_OWNER_NUMBER`).
- **RF-19.** Las confirmaciones se piden en el chat; el siguiente mensaje del usuario es la
  respuesta; sin respuesta en 5 minutos, la acción se cancela.
- **RF-20.** El historial de WhatsApp persiste entre reinicios; una conversación nueva empieza
  tras 6 horas de inactividad o con `/nuevo`. `/ayuda` lista los comandos.
- **RF-21.** Los mensajes que no son texto reciben una respuesta indicando que solo se entiende texto.
- **RF-22.** Las respuestas de más de 4096 caracteres se dividen en varios mensajes.

## 4. Requisitos no funcionales

### 4.1 Seguridad

- **RNF-01.** Ninguna credencial (API keys, tokens, secretos) está en el código ni en el repositorio:
  van en `.env` o en `~/.config/jarvis/`, ignorados por git. `.env.example` lista los nombres sin valores.
- **RNF-02.** Permiso mínimo en cada servicio: `calendar.readonly`; `gmail.send` solo si el resumen
  está configurado.
- **RNF-03.** Los tokens OAuth se guardan con permisos de archivo solo para el usuario.
- **RNF-04.** El webhook de WhatsApp verifica la firma de Meta (`X-Hub-Signature-256`) y rechaza
  avisos sin firma válida; el servidor escucha solo en `127.0.0.1`.
- **RNF-05.** Las acciones programadas no son tools: el modelo no puede dispararlas ni cambiar su destino.

### 4.2 Privacidad

- **RNF-06.** Los logs no contienen el contenido de mensajes, correos ni reuniones: solo resultados,
  IDs y tipos de error.
- **RNF-07.** El historial de WhatsApp se guarda solo en el equipo del usuario y se borra a los 30 días.
- **RNF-08.** No se guarda el contenido de los resúmenes enviados, solo la fecha y hora del envío.

### 4.3 Fiabilidad

- **RNF-09.** Un fallo de un servicio externo no rompe el programa: se informa al usuario con un
  mensaje claro en español.
- **RNF-10.** El resumen programado reintenta hasta 3 veces ante fallos temporales; los errores de
  autorización no se reintentan.
- **RNF-11.** Los avisos duplicados de Meta no producen respuestas duplicadas.

### 4.4 Calidad y mantenibilidad

- **RNF-12.** Código, funciones y variables en inglés; comentarios, docs y mensajes al usuario en español.
- **RNF-13.** Type hints en todo; funciones pequeñas con una sola responsabilidad.
- **RNF-14.** Cada funcionalidad viene con tests; las APIs externas y el sistema operativo se mockean.
- **RNF-15.** Los tests corren en GitHub Actions en cada pull request y en cada push a `main`.
- **RNF-16.** Cada decisión de arquitectura relevante se documenta en un ADR.

### 4.5 Plataforma

- **RNF-17.** Windows es la plataforma principal; la programación del resumen usa el Programador
  de tareas. En Mac y Linux, el resto funciona y se indica la línea de `cron` equivalente.

## 5. Fuera de alcance (por ahora)

- Leer los chats personales de WhatsApp del usuario o escribir desde su número (no lo permiten las
  vías oficiales).
- Enviar mensajes reales a terceros: `enviar_mensaje` sigue simulada.
- Crear, modificar o borrar eventos del calendario.
- Mensajes de voz, imágenes o archivos por WhatsApp.
- Resumen diario por WhatsApp (requiere plantillas aprobadas por Meta).
- Varios usuarios, servidor en la nube, Alexa y llamadas telefónicas (ver roadmap).

## 6. Trazabilidad

| Requisito | Dónde se implementa | Tests principales |
|---|---|---|
| RF-01 a RF-07 | `agent.py`, `tools/`, `cli.py` | `test_agent.py`, `test_tools.py`, `test_cli.py` |
| RF-08 a RF-11 | `agenda/`, `google_auth.py`, `tools/reuniones.py` | `test_google_calendar.py`, `test_google_auth.py`, `test_tools.py` |
| RF-12 a RF-16 | `summary.py`, `summary_cli.py`, `notify/`, `scheduler.py`, `storage.py` | `test_summary.py`, `test_gmail.py`, `test_scheduler.py`, `test_storage.py` |
| RF-17 a RF-22 | `whatsapp/`, `memory.py`, `confirmation.py` | `test_whatsapp_*.py`, `test_memory.py`, `test_confirmation.py` |
| RNF-01 a RNF-08 | `config.py`, `google_auth.py`, `whatsapp/webhook.py`, logs | `test_config.py`, `test_google_auth.py`, `test_whatsapp_webhook.py` |
