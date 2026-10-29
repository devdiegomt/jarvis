# ADR 003: Resumen diario por Gmail, programado con el Programador de tareas

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.3

## Contexto

La v0.3 debe enviar al usuario, sin que abra el chat, un resumen de sus reuniones del día de
lunes a viernes a las 7:00. El usuario trabaja en Windows y quiere recibirlo por correo (Gmail).
La ejecución es desatendida: nadie está frente a la consola para confirmar nada.

## Decisión

1. **El envío es una acción fija del sistema, no una tool del agente.** El código decide cuándo
   enviar, qué datos usar y a quién: el destinatario sale de `JARVIS_RESUMEN_DESTINATARIO` y el
   modelo no puede cambiarlo. Por eso no pide confirmación en cada envío. El usuario lo autoriza
   una vez al configurarlo y al ejecutar `programar-resumen`. La regla de "confirmar toda tool con
   efectos externos" sigue intacta: el modelo no tiene en este modo ninguna tool.
2. **Una sola llamada a Claude, sin el loop del agente.** Las reuniones se leen en código y Claude
   solo redacta un comentario breve. La agenda (horas y títulos) se genera en código, así que no
   depende del modelo y no puede tener horas inventadas. Si la API falla, se rechaza o se corta la
   respuesta, el correo sale igual sin comentario.
3. **API de Gmail con el permiso `gmail.send`.** Solo permite enviar; no da acceso a leer ni borrar
   correos. Se pide solo si el resumen está configurado (permiso mínimo), reutilizando el login
   OAuth de la v0.2. Los permisos concedidos se guardan en el token; si falta alguno, JARVIS pide
   repetir `google-login` en lugar de fallar con un error poco claro.
4. **Programador de tareas de Windows** registrado por `jarvis programar-resumen` (XML importado
   con `schtasks`):
   - De lunes a viernes a la hora configurada, solo con la sesión del usuario iniciada
     (no se guarda la contraseña de Windows).
   - `pythonw` para que no aparezca ninguna ventana.
   - `StartWhenAvailable`: si el PC estaba apagado, la tarea corre al encenderlo.
   - Reintentos en el propio comando (hasta 3, cada 10 minutos) ante fallos temporales de red,
     porque el Programador de tareas no reintenta por código de salida. Los errores de
     autorización no se reintentan.
5. **SQLite para no duplicar envíos.** `jarvis.db` guarda el día y la hora de cada resumen
   enviado; nunca su contenido. El log de ejecuciones guarda solo el resultado.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Hacer del envío una tool del agente | Ejecución desatendida: no hay quien confirme, y el modelo podría elegir otro destinatario. |
| Usar el loop del agente con `get_reuniones` | Más llamadas y tokens para una tarea fija; resultado menos predecible. |
| SMTP con contraseña de aplicación | Esa contraseña da acceso completo a la cuenta de correo y vive en texto plano en `.env`. |
| Permiso `gmail.compose` o `gmail.modify` | Más amplios de lo necesario. |
| Proceso de JARVIS siempre encendido con su propio reloj | Consume recursos todo el día y hay que gestionar que arranque con Windows. |
| Servidor o función en la nube | Requiere infraestructura y guardar los tokens de Google fuera del equipo; se evaluará con el multiusuario. |
| Notificación de Windows | Solo se ve frente al PC; el usuario prefirió el correo. |

## Consecuencias

**Positivas**

- El resumen llega al celular sin infraestructura adicional.
- Fallos parciales (Claude caído) no impiden el envío; fallos de red se reintentan.
- `--dry-run` permite revisar el correo antes de activarlo.
- El canal de envío (`Notifier`) es intercambiable: WhatsApp (v0.4) será otra implementación.

**Negativas**

- Depende de que el PC esté encendido y con la sesión iniciada.
- Los títulos de eventos (que pueden escribir terceros) llegan al modelo. El riesgo es bajo:
  en este modo el modelo no tiene tools y su texto solo va al propio usuario.
- Mientras la app OAuth esté en modo *Prueba*, la autorización caduca a los 7 días (ver ADR 002);
  el resumen fallaría hasta repetir el login. Se recomienda publicar la app.
