# ADR 010: Respuestas con voz generadas en el PC con Piper

- **Estado:** Aceptada
- **Fecha:** 2026-10-30
- **Versión:** v0.8.1

## Contexto

Desde la v0.8, JARVIS entiende notas de voz. Para que hablar con él se sienta natural, también debe
poder contestar con voz, sin obligar a escuchar cuando el usuario prefiere leer.

## Decisión

1. **Voz local con Piper (`piper-tts`)**, en el mismo grupo opcional `voz` que Whisper. El texto de
   la respuesta no sale del PC; el audio se genera en memoria y se convierte a OGG/Opus con PyAV
   (el formato de las notas de voz de Telegram), sin escribir archivos.
2. **Voz configurable** (`JARVIS_PIPER_VOZ`, por defecto `es_MX-ald-medium`, español latino),
   descargada por `jarvis preparar-voz` junto con el modelo de Whisper, con `truststore` (ADR 006).
   Una descarga fallida no deja archivos a medias.
3. **Respuesta en espejo por defecto:** con voz cuando el usuario envió una nota de voz, por escrito
   cuando escribió. `/voz` permite elegir *si me hablas*, *siempre* o *nunca*, con botones; la
   preferencia se guarda en `jarvis.db` (tabla `preferences`).
4. **El texto llega siempre**, después de la nota de voz: se puede leer donde no se puede escuchar,
   y es la red de seguridad si la voz falla (un fallo de la voz nunca impide responder). Si falta
   instalar o descargar la voz, se explica una sola vez por arranque.
5. **Lo que se lee se adapta:** sin enlaces ni emojis y hasta unos 1000 caracteres, cortando en una
   frase; el resto queda por escrito.
6. **Interfaz `Speaker`** en `speech.py` y `JARVIS_RESPUESTA_VOZ` (`local` o `no`): un motor en la
   nube como ElevenLabs se añadiría como otra implementación, sin tocar el chat ni Telegram.
7. **Envío con `sendVoice`** (multipart/form-data) desde el cliente de Telegram propio; como el resto
   de las llamadas, sus errores nunca incluyen la URL con el token.

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| ElevenLabs u otra voz en la nube | Más natural, pero de pago y con el texto de las respuestas (agenda, recordatorios) saliendo del PC. Queda como opción futura detrás de `Speaker`. |
| Voces de Windows (SAPI) | Sin descargas, pero solo en Windows, con calidad dispar según el equipo y sin buena forma de generar OGG/Opus. |
| Responder siempre con voz | Molesto cuando el usuario escribe justamente porque no puede escuchar; queda como opción de `/voz`. |
| Solo voz, sin el texto | Si la voz falla o no se puede escuchar, la respuesta se perdería. |

## Consecuencias

- La voz se carga con la primera respuesta hablada y queda en memoria (unos 60 MB).
- La calidad depende de la voz elegida; suena correcta pero sintética. Probar otras voces es cambiar
  `JARVIS_PIPER_VOZ` y volver a ejecutar `preparar-voz`.
- La conversión a OGG/Opus reutiliza PyAV, que ya instalaba `faster-whisper`.
- **Licencia:** `piper-tts` es GPL-3.0 (incluye espeak-ng). Para uso personal no hay problema; si
  JARVIS se distribuye como producto, habrá que revisar esa obligación o cambiar de motor (la
  interfaz `Speaker` y el grupo opcional `voz` lo permiten sin tocar el resto).
