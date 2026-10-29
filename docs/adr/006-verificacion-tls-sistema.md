# ADR 006: Verificar HTTPS con el almacén de certificados del sistema (truststore)

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Versión:** v0.5.1

## Contexto

Al probar la v0.5 en el PC del usuario (Windows), `jarvis telegram-vincular` falló con
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`. Algo en el equipo
(típicamente la protección web de un antivirus) intercepta las conexiones HTTPS y presenta su
propio certificado raíz, que el usuario tiene instalado en el almacén de certificados de Windows.

El navegador y el SDK de Anthropic funcionaban: el SDK usa `httpx2`, que verifica con
`truststore` (almacén del sistema). El cliente de Telegram usaba `urllib` con el contexto TLS por
defecto de Python, que no consultaba ese certificado.

## Decisión

1. Las llamadas HTTPS propias (hoy, el cliente de Telegram) usan
   `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`: el sistema operativo verifica el certificado,
   igual que el navegador y que el SDK de Anthropic.
2. `truststore` pasa a ser una dependencia explícita (antes llegaba solo de forma indirecta).
3. **La verificación nunca se desactiva.** Un certificado que el sistema no reconoce sigue siendo
   un error.
4. Los errores de red explican la causa (certificado no confiable, nombre no resuelto, tiempo
   agotado) sin incluir la URL, que contiene el token del bot. Un error de certificado no se
   reintenta: no se arregla solo.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Desactivar la verificación (`CERT_NONE`) | Permitiría a cualquiera en la red suplantar a Telegram y robar el token. Descartada siempre. |
| Pedir al usuario la ruta del certificado del antivirus (`SSL_CERT_FILE`) | Funciona, pero es manual, frágil y distinto en cada antivirus. |
| Pedir al usuario que desactive el análisis HTTPS del antivirus | Reduce su protección para todo el equipo. Queda solo como último recurso documentado (exclusión de `api.telegram.org`). |
| Usar `httpx2` (como el SDK) en lugar de `urllib` | Ya trae `truststore`, pero añade una dependencia directa para unas pocas llamadas. |

## Consecuencias

- JARVIS se comporta como el navegador: funciona en equipos con antivirus o proxy de empresa
  cuyo certificado está instalado en el sistema.
- Si un tercero no confiable intercepta la conexión, el error sigue apareciendo y ahora dice por qué.
- El README explica cómo ver quién emite el certificado (debería ser el antivirus del usuario).
