# ADR 007: JARVIS en segundo plano al iniciar sesión (Programador de tareas)

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.6

## Contexto

Desde la v0.5, el chat por Telegram solo responde mientras `jarvis telegram` está abierto en una
terminal. Si el usuario la cierra o reinicia el PC, JARVIS deja de responder. Se quiere que esté
siempre disponible mientras el PC esté encendido, sin ventanas abiertas, en Windows.

## Decisión

1. **Tarea del Programador de tareas con disparador de inicio de sesión** (`programar-telegram`):
   - Solo para la cuenta del usuario (`UserId` en el disparador) y solo con su sesión iniciada
     (`InteractiveToken`): no se guarda la contraseña de Windows.
   - `pythonw` para no abrir ventanas; 30 s de espera tras iniciar sesión para que haya red.
   - Sin límite de duración, sin detenerse con batería, y `IgnoreNew` para no lanzar dos copias.
   - Si el proceso termina con error, Windows lo reinicia hasta 3 veces, cada 5 minutos.
   - Al programarla también se inicia en el momento, sin esperar al próximo inicio de sesión.
2. **Modo `--programado` en `jarvis telegram`:**
   - Sin consola: todo queda en el registro (los errores de arranque incluidos).
   - Si no hay red al arrancar o al despertar el PC, reintenta con espera creciente en vez de salir.
   - Si otra copia lee el mismo bot (por ejemplo, una abierta a mano en una terminal), espera a que
     termine en vez de salir. Así la copia manual no "mata" la de segundo plano.
   - Los errores que no se arreglan reintentando (token inválido, certificado) terminan el proceso.
3. **Registros rotativos** (`RotatingFileHandler`, 1 MB × 4 archivos) para el chat y el resumen,
   porque un proceso que corre todo el día haría crecer el registro sin límite.
4. **`jarvis estado`**: configuración, estado de las tareas y últimas líneas de los registros. El
   estado se consulta con PowerShell (`Get-ScheduledTask`) porque devuelve valores en inglés en
   cualquier idioma de Windows; la salida de `schtasks /Query` viene traducida.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Servicio de Windows (o NSSM / WinSW) | Funciona sin iniciar sesión, pero requiere permisos de administrador, guardar credenciales o una herramienta externa, y complica el acceso al `.env` y a los tokens del usuario. Excesivo para uso personal. |
| Tarea con "ejecutar aunque el usuario no haya iniciado sesión" | Obliga a guardar la contraseña de Windows en el Programador de tareas. |
| Acceso directo en la carpeta Inicio | Abre una ventana visible y no reinicia el proceso si falla. |
| Bucle de reinicio dentro de JARVIS | Duplica lo que el Programador de tareas ya ofrece (reinicio, una sola instancia). |
| Servidor en la nube | Siempre disponible aunque el PC esté apagado, pero es otra versión del roadmap (tokens de Google fuera del PC, costo, despliegue). |

## Consecuencias

- JARVIS responde por Telegram mientras el PC esté encendido y con la sesión iniciada, sin
  terminales abiertas.
- Con el PC apagado o sin sesión, no responde; los mensajes enviados entretanto se procesan al
  volver (Telegram los guarda hasta 24 horas).
- El usuario puede diagnosticar problemas con `jarvis estado` sin buscar archivos de registro.
