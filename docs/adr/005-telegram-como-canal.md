# ADR 005: Telegram como canal de chat y de avisos, en lugar de WhatsApp

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.5
- **Sustituye a:** [ADR 004](004-whatsapp-cloud-api-local.md)

## Contexto

La v0.4 implementó el chat por WhatsApp con la Cloud API de Meta (ADR 004). Al configurarlo,
el usuario chocó con la parte de Meta: crear la app exige un portafolio comercial, la cuenta
recibió un bloqueo temporal antiabuso y el asistente no permitía conectar el portafolio.
Además, el diseño necesitaba ngrok para recibir los avisos y no permitía enviar el resumen
diario sin plantillas aprobadas y de pago.

El canal es solo entre el usuario y JARVIS (no con clientes), así que no hace falta que sea
WhatsApp. El usuario prefiere Telegram y pidió quitar WhatsApp.

## Decisión

1. **Bot de Telegram** creado con @BotFather como canal de chat y de avisos.
2. **Long polling** (`getUpdates`) en lugar de webhook: JARVIS consulta a Telegram, así que no
   hay URL pública, ni ngrok, ni puertos abiertos. Los fallos de red se reintentan con espera
   creciente; un token inválido u otra instancia leyendo el mismo bot detienen el proceso con un
   mensaje claro.
3. **Solo la cuenta del usuario** (`TELEGRAM_OWNER_ID`) y solo en chat privado. El ID se obtiene
   con `jarvis telegram-vincular` y es obligatorio para arrancar el chat: un bot es público por
   nombre, así que sin este filtro cualquiera podría hablar con JARVIS.
4. **API de bots con la librería estándar** (`urllib`), sin SDK: pocas llamadas y sin
   dependencias nuevas (ADR 001). Los errores nunca incluyen la URL, porque contiene el token.
5. **Confirmaciones con botones** (*inline keyboard*): la pregunta lleva [Sí] [No]; al responder,
   se editan para mostrar el resultado. Se sigue aceptando "s/n" escrito. Los botones de preguntas
   antiguas responden "Esta pregunta ya expiró".
6. **Lógica del chat independiente del canal** (`chat.py`): comandos, confirmaciones, memoria y
   llamadas al agente. Telegram solo implementa enviar, "escribiendo…", preguntar y cerrar una
   confirmación. Se conserva todo lo decidido en el ADR 004 sobre el procesamiento en un único
   hilo, las conversaciones por inactividad, el historial que solo crece y la retención de 30 días.
7. **Resumen diario por Telegram** con `JARVIS_RESUMEN_CANAL=telegram|gmail`. Con Telegram,
   `google-login` ya no pide el permiso `gmail.send` (permiso mínimo). Gmail se mantiene como
   alternativa.
8. **Texto plano** en todos los mensajes: con formato (Markdown/HTML), un carácter suelto del
   modelo puede hacer que Telegram rechace el mensaje.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Seguir con WhatsApp (Meta) | Bloqueado por la verificación de Meta; necesita ngrok; los avisos iniciados por JARVIS requieren plantillas de pago. |
| Mantener el código de WhatsApp sin usar | El usuario prefirió quitarlo; queda en el historial de git y en el ADR 004 si se necesita. |
| Webhook de Telegram | Volvería a requerir una URL pública (ngrok) sin ventaja para un solo usuario. |
| Librería `python-telegram-bot` | Cómoda, pero añade una dependencia y su propio modelo asíncrono para unas pocas llamadas. |

## Consecuencias

**Positivas**

- Configuración en minutos, sin cuentas de empresa ni verificación.
- Ningún puerto expuesto en el PC del usuario.
- El resumen diario llega al celular gratis y sin plantillas.
- Un canal futuro (por ejemplo, Alexa) solo tiene que implementar `ChatChannel`.

**Negativas**

- Los mensajes con el bot pasan por los servidores de Telegram (los chats con bots no tienen
  cifrado de extremo a extremo), igual que pasaban por Meta con WhatsApp.
- El chat solo responde mientras `jarvis telegram` está corriendo en el PC.
- `telegram-vincular` toma el primer mensaje que llegue al bot: el usuario debe comprobar que el
  nombre mostrado es el suyo.
