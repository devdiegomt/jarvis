# ADR 009: Notas de voz transcritas en el PC con Whisper

- **Estado:** Aceptada
- **Fecha:** 2026-10-30
- **Versión:** v0.8

## Contexto

Hablarle a JARVIS debe ser tan fácil como escribirle: el usuario quiere mandarle notas de voz por
Telegram y, más adelante, llamarlo con la voz desde el PC ("Oye JARVIS"). La API de Claude no
acepta audio, así que hace falta transcribirlo antes de pasárselo al agente.

## Decisión

1. **Transcripción local con Whisper (`faster-whisper`)**, en CPU y con `int8`, idioma español.
   El audio se descarga de Telegram a memoria, se transcribe y se descarta: nunca se guarda en
   disco ni sale del PC. Lo transcrito se guarda en el historial como cualquier mensaje (30 días).
2. **Modelo configurable** (`JARVIS_WHISPER_MODELO`, por defecto `small`: buen equilibrio entre
   calidad en español y velocidad en un PC normal).
3. **Descarga explícita con `jarvis preparar-voz`**, a `~/.config/jarvis/voz/<modelo>`, verificando
   HTTPS con el almacén del sistema (`truststore`, como en el ADR 006). El proceso en segundo plano
   nunca descarga nada: si falta el modelo, responde cómo prepararlo. El modelo se carga con la
   primera nota de voz y queda en memoria.
4. **Dependencia opcional** en el grupo `voz` de `pyproject.toml`. `uv sync` lo instala por defecto
   (`default-groups`); la CI lo omite (`--no-group voz`) porque los tests simulan la transcripción.
   Sin el grupo, JARVIS funciona y solo explica cómo activar la voz.
5. **El chat muestra lo que entendió** ("🎙 Entendí: «…»") y pasa el texto al agente marcado como
   `(nota de voz)`, para que el modelo tenga en cuenta posibles errores de transcripción y pregunte
   si algo no cuadra. Las confirmaciones también se pueden responder con una nota de voz.
6. **Interfaz `Transcriber`** en `voice.py`, y `JARVIS_TRANSCRIPCION` (`local` o `no`) para elegir el
   motor: cambiar a uno en la nube más adelante no toca el chat ni Telegram.
7. **Límites:** notas de hasta 5 minutos (las más largas no se descargan) y archivos de hasta 20 MB
   (el límite de la API de bots). Los registros solo guardan la duración y el tiempo de transcripción.

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| Transcripción en la nube (OpenAI, Groq, Deepgram) | Otra API key y otro costo, y la voz del usuario sale del PC. Más rápida: queda como opción futura detrás de `Transcriber`. |
| `openai-whisper` (el original) | Necesita PyTorch (varios GB) y FFmpeg instalado aparte; `faster-whisper` es más liviano y más rápido en CPU. |
| Descargar el modelo automáticamente al llegar la primera nota | Una descarga de cientos de MB en segundo plano, sin consola para ver el progreso ni los errores de certificados. |
| Dependencia obligatoria | Haría la CI más lenta y obligaría a instalar varios cientos de MB a quien no quiera voz. |
| Responder también con voz | Se decidirá en la v0.8.1 (voz local frente a un servicio como ElevenLabs). |

## Consecuencias

- La primera nota de voz tras arrancar tarda unos segundos más (carga del modelo), y el modelo usa
  memoria mientras JARVIS corre (del orden de 1 GB con `small`).
- Transcribir ocupa el hilo del chat: mientras tanto, los demás mensajes esperan su turno.
- `faster-whisper` 1.2 no es compatible con `av` 19, por eso `av` está fijado por debajo de esa versión.
- La misma pieza servirá para "Oye JARVIS" en el PC, que también necesitará transcribir la voz.
