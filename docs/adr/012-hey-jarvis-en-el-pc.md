# ADR 012: "Hey JARVIS" en el PC con openWakeWord, dentro del proceso en segundo plano

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.10

## Contexto

El usuario quiere llamar a JARVIS con la voz, como "Ok Google" u "Oye Siri", sin tomar el teléfono.
Desde la v0.8 y la v0.8.1, JARVIS ya transcribe (Whisper) y habla (Piper) en el PC; faltaba detectar
la palabra de activación y usar el micrófono y los parlantes.

## Decisión

1. **openWakeWord con su modelo "hey_jarvis"**, en el equipo con el motor ONNX (`onnxruntime`, que ya
   instalaba Whisper). Analiza bloques de 80 ms; el umbral es configurable
   (`JARVIS_ACTIVACION_UMBRAL`, 0.5 por defecto). La frase es "Hey JARVIS" (en inglés) porque es el
   modelo disponible ya entrenado. Verificado con audio sintetizado: 0,99 al decir la frase, 0,0 con
   otra frase.
2. **Modelos descargados por `preparar-voz`** (unos 4 MB, desde las releases de openWakeWord en
   GitHub) a `~/.config/jarvis/voz/activacion`, con `truststore` y escritura atómica. openWakeWord
   0.6.0 pide `tflite-runtime` en Linux (sin versión para Python 3.12): sus dependencias se declaran
   en `[[tool.uv.dependency-metadata]]` sin él.
3. **El pedido se graba hasta el silencio** (voz por energía frente al ruido de fondo medido; fin con
   ~1 s de silencio, máximo 15 s, 4 s para empezar a hablar) y se transcribe con el mismo Whisper.
   Se conserva lo dicho mientras suena el tono, para decir la frase y el pedido de corrido.
4. **Un canal de chat más** (`PcVoiceChannel`) sobre el `ChatService` existente: `send_text` habla
   por los parlantes y `send_with_buttons` pregunta "¿Sí o no?" en voz alta y escucha la respuesta
   sin palabra de activación (sin respuesta, se cancela). Así el PC reutiliza tools, confirmaciones,
   memoria, pendientes y recordatorios sin duplicar lógica. Conversaciones propias (canal `pc`) y un
   system prompt para respuestas habladas (cortas, sin listas ni emojis).
5. **Dentro del proceso en segundo plano de Telegram**, en un hilo, para cargar Whisper y Piper una
   sola vez (`assistant.py` construye las piezas comunes). **Apagado por defecto**
   (`JARVIS_PALABRA_ACTIVACION=si` para encenderlo) por ser un micrófono siempre abierto; si algo
   falta, el resto de JARVIS sigue y el motivo queda en el registro. `jarvis escuchar` lo prueba en
   primer plano mostrando cada paso.
6. **Sin eco:** mientras JARVIS habla (o suena el tono), el micrófono se ignora y luego se descarta
   lo acumulado, para que no se escuche a sí mismo.
7. **Interfaces** `WakeWordDetector` y `AudioDevice`: otro motor (un modelo propio "Oye JARVIS",
   Porcupine) o el audio de otro sistema se añaden sin tocar el chat.

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| Porcupine (Picovoice) con "Oye JARVIS" en español | Necesita cuenta y clave de acceso, es software cerrado y su plan gratuito tiene límites. Queda como opción detrás de `WakeWordDetector`. |
| Entrenar ya un modelo propio "Oye JARVIS" | Requiere un proceso de entrenamiento aparte (datos sintéticos, horas de cómputo); se hará cuando el flujo esté probado. |
| Un proceso aparte para el micrófono | Cargaría Whisper y Piper dos veces (más de 1 GB de memoria extra) y otra tarea programada. |
| Transcribir todo el audio y buscar la frase en el texto | Whisper consumiría CPU sin parar y el audio de todo el día pasaría por el transcriptor. |
| Encendido por defecto | Un micrófono siempre abierto debe ser una decisión explícita del usuario. |

## Consecuencias

- JARVIS puede usarse sin teléfono mientras el PC está encendido y con sesión iniciada.
- El modelo "hey_jarvis" está entrenado para el inglés: con acento español puede necesitar ajustar
  el umbral. Los modelos ya entrenados de openWakeWord son de uso no comercial (CC BY-NC-SA 4.0):
  para un producto habrá que entrenar uno propio o usar un motor con licencia comercial.
- No se probaron aquí micrófono ni parlantes reales; `escuchar` existe para probarlos en el PC.
- `numpy` pasa al grupo `dev` para que la CI pruebe la grabación y el canal sin el grupo `voz`.
