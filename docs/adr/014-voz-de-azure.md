# ADR 014: Voz de Azure AI Speech, con Piper de respaldo

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.10.2

## Contexto

Piper (ADR 010) funciona en el PC y es gratis, pero suena sintético. El usuario quería una voz más
natural, de preferencia gratuita. Se compararon ElevenLabs (plan gratuito de unos 10 000 caracteres al
mes), Google Cloud Text-to-Speech (requiere activar la facturación) y Azure AI Speech (plan gratuito
F0 con 0,5 millones de caracteres neuronales al mes, que se frena al llegar al límite, y voces con
acento colombiano). Se descartó usar el servicio de lectura de Microsoft Edge sin API oficial (R-4).

## Decisión

1. **Azure AI Speech como motor opcional** (`JARVIS_RESPUESTA_VOZ=azure`), detrás de la interfaz
   `Speaker` (`azure_speech.py`). Voz por defecto: Salomé (`es-CO-SalomeNeural`), configurable con
   `JARVIS_AZURE_VOZ`.
2. **API REST con `urllib` y `truststore`**, sin el SDK de Microsoft (pesado y con bibliotecas
   nativas). La clave va en una cabecera (no en la URL), viene de `.env` y nunca aparece en registros,
   errores ni en el `repr` de la configuración.
3. **Formato pedido según el destino:** OGG/Opus para las notas de voz de Telegram (sin convertir) y
   PCM de 24 kHz para los parlantes del PC.
4. **Piper de respaldo:** si Azure falla (red, clave, límite), responde Piper si está descargado; si
   tampoco puede, gana el error de Azure y la respuesta llega por escrito. Clave o región rechazadas
   y límite agotado son errores "no disponible", que el chat explica una vez.
5. **`jarvis probar-voz`** dice un texto por los parlantes con la voz configurada; con Azure no usa el
   respaldo, para que se vean sus errores al configurarlo.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| ElevenLabs | La voz más natural, pero su plan gratuito se agota en pocos días de uso. |
| Google Cloud Text-to-Speech | Generoso, pero exige activar la facturación y sus voces en español son sobre todo de España y EE. UU. |
| SDK de Azure (`azure-cognitiveservices-speech`) | Pesado, con bibliotecas nativas; la API REST basta para texto a voz. |
| Voz de "Leer en voz alta" de Edge (edge-tts) | Gratis, pero no es una vía oficial (R-4). |

## Consecuencias

- Con Azure, el texto de las respuestas habladas sale del PC hacia Microsoft (no la voz del usuario,
  que se sigue transcribiendo en el PC). Con Piper, nada cambia.
- Cada respuesta hablada depende de internet; sin red, el respaldo mantiene la voz.
- Agregar otra voz en la nube (por ejemplo, ElevenLabs) sería otra clase como `AzureSpeaker`.
