# ADR 004: Chat por WhatsApp con la Cloud API de Meta, servidor local y ngrok

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.4

## Contexto

La v0.4 añade WhatsApp como canal para chatear con JARVIS desde el celular, con el mismo agente
y las mismas tools que la consola. JARVIS sigue corriendo en el PC del usuario (Windows), donde
viven los tokens de Google. El usuario decidió empezar solo con el chat; el resumen diario sigue
por Gmail.

Restricciones de WhatsApp que condicionan el diseño:

- Las vías oficiales (Cloud API de Meta, o proveedores como Twilio) dan a JARVIS **su propio
  número**: no permiten leer los chats personales del usuario ni escribir desde su número.
- Los mensajes llegan por **webhook**: Meta necesita una URL pública HTTPS y espera respuesta
  en pocos segundos; si no la recibe, reenvía el aviso.
- Responder dentro de las 24 horas siguientes a un mensaje del usuario es gratis; iniciar la
  conversación (como un resumen a las 7:00) exige plantillas aprobadas y tiene costo.

## Decisión

1. **WhatsApp Cloud API de Meta**, sin intermediarios, con el número de prueba gratuito.
2. **Servidor local** (`jarvis whatsapp`), escuchando solo en `127.0.0.1`, expuesto con un
   **dominio fijo gratuito de ngrok**. JARVIS no gestiona ngrok: se arranca aparte.
3. **Servidor HTTP de la librería estándar** (`http.server`) y llamadas a la Graph API con
   `urllib`: un solo endpoint no justifica FastAPI ni un cliente HTTP adicional (en línea con el
   ADR 001: pocas dependencias).
4. **Respuesta inmediata a Meta y un único worker en segundo plano.** El webhook verifica la
   firma, descarta duplicados y encola; el worker procesa los mensajes de uno en uno y en orden.
   Así no hay carreras sobre el historial ni respuestas cruzadas.
5. **Seguridad del webhook:**
   - Firma `X-Hub-Signature-256` (HMAC-SHA256 con el App Secret) obligatoria; sin App Secret
     el servidor no arranca.
   - Solo se atiende el número del usuario (`WHATSAPP_OWNER_NUMBER`); el resto se ignora sin
     responder.
   - IDs de mensajes procesados en SQLite para ignorar reenvíos de Meta.
   - El log guarda IDs y resultados, nunca el texto; el log por defecto de `http.server`
     (que incluye rutas y parámetros) se silencia.
6. **Confirmaciones dentro del chat.** El registro de tools no cambia: el confirmador de este
   canal envía la pregunta y toma el siguiente mensaje del usuario como respuesta (s/n), con
   5 minutos de espera máxima (sin respuesta = no). Funciona porque el worker es único: mientras
   espera, es el mismo hilo el que lee la cola.
7. **Historial persistente por conversaciones** (`memory.py`, SQLite):
   - Conversación nueva tras 6 horas de inactividad o con `/nuevo`.
   - Dentro de una conversación el historial **solo crece** y el system prompt queda fijo; la
     fecha y hora actuales van al principio de cada mensaje del usuario. Recortar o editar
     turnos anteriores invalidaría los bloques de razonamiento que devuelve el modelo (y en
     cuentas recientes la API lo rechaza).
   - Retención de 30 días: las conversaciones más antiguas se borran automáticamente para no
     acumular datos de clientes indefinidamente.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Twilio | Sandbox algo más simple, pero cobra cada mensaje y es un intermediario más con acceso al contenido. |
| Librerías no oficiales (WhatsApp Web) | Violan los términos de WhatsApp; riesgo de bloqueo de la cuenta personal del usuario. |
| Servidor en la nube | Siempre disponible, pero obliga a llevar fuera del PC los tokens de Google y a mantener infraestructura. Se evaluará con el multiusuario. |
| Cloudflare Tunnel | Gratis y estable, pero un dominio fijo requiere tener un dominio propio; ngrok da uno gratis. |
| FastAPI + uvicorn | Más cómodo para muchas rutas; para un endpoint añade dependencias sin beneficio claro. |
| Procesar cada mensaje en su propio hilo | Respuestas fuera de orden y carreras al guardar el historial. |
| Recortar el historial a los últimos N mensajes | Edita turnos anteriores: invalida el razonamiento preservado del modelo. |

## Consecuencias

**Positivas**

- Mismo agente y mismas tools en consola y WhatsApp; las tools no saben por qué canal hablan.
- Costo cero en la práctica (solo respuestas a mensajes del usuario).
- Avisos falsificados, de otros números o duplicados no llegan al agente.

**Negativas**

- JARVIS solo responde con el PC encendido, `jarvis whatsapp` y ngrok corriendo. Los mensajes
  enviados mientras está apagado se procesan cuando vuelve (Meta los reintenta durante un tiempo).
- El número de prueba solo puede escribir a hasta 5 números verificados; un número propio para
  JARVIS requiere verificar el negocio en Meta.
- Si una respuesta de confirmación no llega, la acción se cancela a los 5 minutos.
- Solo texto: audio e imágenes quedan para más adelante.
