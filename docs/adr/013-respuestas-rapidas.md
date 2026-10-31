# ADR 013: Respuestas más rápidas en el chat y la voz

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.10.1

## Contexto

El usuario notó demoras al hablar con JARVIS por notas de voz y con "Hey JARVIS". Cada respuesta
pasa por varias etapas: recibir el audio, transcribirlo (Whisper en CPU), pensar la respuesta
(Claude), generar la voz (Piper) y enviarla o reproducirla. JARVIS no fijaba el esfuerzo de Claude
(el modelo usaba su valor por defecto, alto), Whisper usaba su búsqueda exhaustiva (beam de 5) y
ambos modelos de voz se cargaban recién con el primer uso.

## Decisión

1. **Esfuerzo bajo de Claude por defecto** en el chat, la voz y la consola (`output_config.effort`,
   configurable con `JARVIS_ESFUERZO`). Para conversar y usar tools simples suele bastar y responde
   antes; el resumen diario no cambia.
2. **Whisper con búsqueda simple** (`beam_size=1`) y sin condicionar en texto anterior: mucho más
   rápido en CPU, con pérdida mínima en frases cortas.
3. **Precarga de Whisper y Piper al arrancar**, en un hilo aparte: la primera nota de voz o el
   primer "Hey JARVIS" ya no esperan la carga. Si la voz no está lista, no hace nada.
4. **Fin del pedido tras 0,7 s de silencio** (antes 1 s) en "Hey JARVIS".
5. **Tiempos en el registro** para cada etapa (transcripción, IA, voz), sin contenido, y en la
   consola con `escuchar`, para decidir con datos los siguientes pasos.

## Alternativas consideradas

| Alternativa | Por qué no (por ahora) |
|---|---|
| Transcripción en la nube (por ejemplo, Groq) | Muy rápida, pero la voz saldría del PC. Se decidirá con los tiempos medidos; `Transcriber` lo permite. |
| Un modelo de Claude más pequeño (Haiku) | Más rápido, pero peor con varias tools; antes conviene medir el efecto del esfuerzo bajo. |
| Respuesta en streaming, leyendo la voz frase a frase | Más compleja (voz, Telegram y confirmaciones); se evaluará si la IA sigue siendo la etapa lenta. |

## Consecuencias

- Las respuestas llegan antes; si alguna parece floja, `JARVIS_ESFUERZO=medium` sube la calidad.
- Con la voz activa, el proceso ocupa la memoria de Whisper y Piper desde el arranque (antes, desde
  el primer uso).
