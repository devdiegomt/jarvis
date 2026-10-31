# ADR 018: Avisos de correos de clientes con Gmail de solo lectura

- **Estado:** Aceptada
- **Fecha:** 2026-10-31
- **Versión:** v0.14

## Contexto

Uno de los objetivos de JARVIS desde el principio es avisar de los mensajes de clientes. Los clientes
escriben por correo, y revisar la bandeja a cada rato distrae. JARVIS ya tiene un hilo que envía
avisos por Telegram (ADR 017) y una autorización con Google (ADR 002 y 016).

## Decisión

1. **Permiso `gmail.readonly`**, el mínimo para leer: JARVIS no puede enviar, borrar, archivar ni
   marcar como leído nada. Se pide en `google-login` (con `JARVIS_CORREO=si`, el valor por defecto) y
   convive con `calendar.events` y, si el resumen va por Gmail, `gmail.send`.
2. **Lista de contactos vigilados** en `jarvis.db` (`watched_senders`): direcciones (`laura@acme.com`)
   o dominios enteros (`@acme.com`), con la fecha en que se agregó cada uno. Se maneja hablando con
   JARVIS (`vigilar_contacto`, `dejar_de_vigilar`, `listar_contactos_vigilados`) y se ve con
   `/clientes`. Son datos internos y se pueden deshacer: no piden confirmación (como los pendientes).
3. **Revisión cada 2 minutos** (`JARVIS_CORREO_MINUTOS`) desde el hilo de avisos del proceso de
   Telegram, con una sola búsqueda (`from:(…) -in:sent -in:chats after:…`) que solo pide los
   encabezados (`format=metadata`): remitente, asunto y el fragmento que da Gmail.
4. **Aviso armado en código**, sin IA: "📧 Correo de Laura (laura@acme.com)", el asunto y hasta 200
   caracteres del fragmento. Instantáneo y sin costo.
5. **Sin avisos viejos ni repetidos:** la primera revisión anota la hora de inicio y solo se avisa de
   correos llegados después de esa hora y después de que se agregó el contacto; tras mucho tiempo
   apagado, solo de las últimas 24 horas. Cada correo se anota por su ID en `sent_notices` (sin
   asunto ni remitente) y se avisa una sola vez, aunque JARVIS se reinicie.
6. **Buscar y leer a pedido:** `buscar_correos` (hasta 10 resultados, 1 a 90 días) y `leer_correo`
   (texto plano, o el HTML sin etiquetas, recortado a 6000 caracteres). El modelo los usa solo cuando
   el usuario pregunta por sus correos.
7. **El correo es contenido de terceros:** llega al modelo envuelto en `<correo>` y con una nota que
   dice que es información, no instrucciones; el system prompt lo repite. Un correo que pide agendar,
   pagar o guardar datos se le cuenta al usuario, no se ejecuta. Además, toda acción con efectos
   externos sigue pidiendo confirmación.
8. **Sin el permiso** (una autorización anterior a la v0.14), los avisos de correo se pausan con una
   sola línea en el registro y `estado` explica que falta ejecutar `google-login`; el resto sigue igual.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| `gmail.modify` o `gmail.compose` | Más permiso del necesario; responder correos queda para cuando se decida, con confirmación. |
| Notificaciones push de Gmail (Pub/Sub) | Requieren un servidor público y Google Cloud Pub/Sub; JARVIS no abre puertos (RNF-04). |
| Avisar de todo correo nuevo | Demasiado ruido; el valor está en los clientes, que el usuario elige. |
| Que Claude decida qué correo es importante | Lento, con costo por correo y menos predecible que una lista explícita. |
| La lista en `.env` | Hay que editar un archivo y reiniciar; hablando con JARVIS es más natural y se ve con `/clientes`. |

## Consecuencias

- Un correo de un cliente se avisa unos 2 minutos después de llegar, con el PC encendido.
- El fragmento del aviso pasa por Telegram, como los demás mensajes del chat.
- Quien ya autorizó a Google antes debe ejecutar `google-login` otra vez y aceptar el permiso nuevo.
- Contestar correos o avisar de otras fuentes (WhatsApp, Slack) queda para versiones futuras.
