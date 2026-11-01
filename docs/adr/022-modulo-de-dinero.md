# ADR 022: Módulo de dinero (gastos, ingresos, cobros y TRM) llevado en código

- **Estado:** Aceptada
- **Fecha:** 2026-11-01
- **Versión:** v0.17

## Contexto

El usuario trabaja con clientes y quiere llevar sus gastos, sus ingresos y lo que le deben sin abrir
una hoja de cálculo. Es el primer módulo de la visión ([`docs/vision.md`](../vision.md)) más allá del
día a día, y debe seguir el principio de usar la IA solo donde aporta.

## Decisión

1. **Claude entiende, el código cuenta.**
   - El modelo convierte "gasté 25 mil en almuerzo" en `registrar_movimiento(gasto, 25000, comida)`.
   - Totales, resúmenes por categoría, comparaciones con el mes anterior y conversiones de moneda se
     calculan en código.
   - Las tools devuelven cifras ya formateadas y el prompt pide repetirlas tal cual, sin sumar.
2. **Montos exactos:**
   - Se guardan como enteros en centavos (`Decimal` en el código, nunca `float`).
   - Formato colombiano: `$1.200.000`, o `$500,00 USD` para otras monedas.
   - Moneda por defecto `JARVIS_MONEDA` (COP). Lo que está en otra moneda no se mezcla en los totales.
3. **Datos internos, sin confirmación:** registrar, borrar, cobrar y marcar pagado cambian solo datos
   de JARVIS y se pueden deshacer, como los pendientes. Marcar un cobro como pagado registra además el
   ingreso, salvo que el usuario diga que ya lo anotó.
4. **Cuentas por cobrar con avisos en código:**
   - Aviso por Telegram el día que vence un cobro y cada 7 días mientras siga sin pagar, a la hora de
     `JARVIS_AVISO_COBROS` (09:00).
   - Usa el registro de avisos existente (clave con el id del cobro y la fecha, sin cliente ni monto).
   - Los cobros que vencen aparecen en `/hoy`, en el resumen de la mañana y en la app.
5. **TRM de datos.gov.co** (Superintendencia Financiera): gratis y sin clave.
   - Tool `get_trm` con la conversión calculada en código, preferida a buscar el dólar en internet.
   - Comando `/trm` y una línea en el resumen de la mañana. Se guarda en memoria 3 horas.
6. **Comandos sin IA:** `/dinero` (el mes por categoría, con balance y comparación) y `/cobros` (vencidos
   primero). El de costos de Claude sigue siendo `/gasto`.
7. **Exportar:** `jarvis exportar-dinero` escribe un CSV (UTF-8 con BOM, para que Excel muestre bien las
   tildes) del mes o del año.
8. **Privacidad:**
   - Todo queda en `jarvis.db`, en el equipo, sin conexión con bancos ni caducidad (son registros
     contables).
   - No se guardan números largos (tarjetas, cuentas, documentos); el detector es el mismo de la
     memoria, ahora en `sensitive.py`.
   - Los registros y `estado` solo muestran cantidades de movimientos y cobros.
9. **Tests sin red:** `jarvis.net.get_json` es la única salida a APIs públicas (Open-Meteo y
   datos.gov.co), y `conftest.py` la bloquea en todos los tests.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Que Claude sume y convierta | Los modelos pueden equivocarse en la aritmética; el código no. |
| Guardar montos como `float` | Errores de redondeo (0,1 + 0,2 ≠ 0,3) en algo que debe cuadrar al peso. |
| Conectar el banco | Requiere credenciales bancarias y proveedores de pago; fuera de alcance por seguridad. |
| Google Sheets como almacén | Otro permiso de Google y dependencia de la red; el CSV cubre la necesidad de llevarlo a una hoja. |
| Buscar el dólar con `web_search` | Cuesta por búsqueda y tokens; la TRM oficial es gratuita y exacta. |
| Llamar `/gastos` al resumen | Se confunde con `/gasto` (costo de Claude); por eso es `/dinero`. |

## Consecuencias

- Si el PC está apagado justo el día de un aviso semanal, ese aviso se salta; el siguiente llega a la
  semana (y `/cobros` siempre muestra el atraso).
- Presupuestos por categoría y facturación electrónica quedan para versiones futuras.
