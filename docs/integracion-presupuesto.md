# Integración con la app de presupuesto

- **Estado:** propuesta, pendiente de decisiones del usuario (ver el final)
- **Fecha:** 2026-11-01
- **App:** https://presupuesto-page.vercel.app/ · repo `devdiegomt/presupuesto` (público)

El usuario quiere unificar JARVIS y su app de presupuesto. Este documento resume cómo es esa app (revisada en el
commit `c8a091f`), en qué se cruza con el módulo de dinero de JARVIS (v0.17) y el camino propuesto.

## Cómo es la app de presupuesto

- **Front-end:**
  - React 18, Vite, TypeScript y Tailwind 4.
  - PWA (`vite-plugin-pwa`) publicada en Vercel.
  - Pruebas con Vitest.
- **Datos locales primero:**
  - IndexedDB con Dexie.
  - Sincroniza con **Supabase** (`src/lib/sync.ts`, con sincronización automática).
- **Supabase:**
  - Una sola tabla `public.sync_records`: `(user_id, table_name, sync_id, data jsonb, updated_at, deleted_at)`.
  - Row Level Security: cada usuario solo ve lo suyo, y la `anon key` es pública por diseño.
  - Los nombres de tabla llevan prefijo: `presupuesto:movements`, `presupuesto:budgets`, etc. Ya está pensado para
    que varias apps compartan el proyecto.
  - Conflictos por last-write-wins sobre `updated_at`; los borrados son tombstones (`deleted_at`).
  - Ingreso con código por correo (`signInWithOtp` + `verifyOtp`).
- **Modelo (`src/db/types.ts`):**
  - `Account`: cuentas (Davivienda…), en COP o BRL.
  - `Tema` y `Subtema`: categorías en dos niveles.
  - `Movement`: tipos `gasto | ingreso | transferencia | ajuste | nota`.
    - Monto en `amountMinor` con signo: los gastos son negativos.
    - Lleva `accountId` y `subtemaId`, y el campo `month` en formato `YYYY-MM`.
  - `Budget`: presupuesto por mes y subtema, con id `"YYYY-MM|subtemaId"`.
  - `Reconciliation`: cuadres de saldo.
  - `MonthClosure`: cierres de mes.
- **Ids estables entre dispositivos:** slugs (`davivienda`), ULID o claves compuestas. Las unidades menores
  dependen de la moneda: COP×1 y BRL×100.

## Dónde se cruza con JARVIS

La app de presupuesto es **mucho más completa** en finanzas personales que el módulo de dinero de JARVIS (v0.17):
tiene cuentas, saldos, presupuestos por categoría, cuadres, cierres, dos monedas y sincronización entre
dispositivos. Tener dos registros de gastos separados sería duplicar y desincronizar.

| Tema | JARVIS hoy (v0.17) | Presupuesto |
|---|---|---|
| Gastos e ingresos | `money_moves` en SQLite local | `movements` (con cuenta y subtema) |
| Categorías | Texto libre | Tema → Subtema (catálogo) |
| Presupuestos | No hay | Por mes y subtema |
| Cuentas y saldos | No hay | Sí, con cuadres |
| Cobros a clientes | `receivables` con avisos | No hay |
| TRM | datos.gov.co | No hay (COP/BRL manuales) |
| Dónde vive | El PC (SQLite) | IndexedDB + Supabase |

## Arquitectura propuesta

**Presupuesto es la fuente de verdad de las finanzas; Supabase es la columna vertebral compartida; JARVIS es el
cerebro y la voz.**

```
   iPhone / navegador                    PC (JARVIS)
 ┌──────────────────────┐        ┌───────────────────────────────┐
 │ Presupuesto (PWA,    │        │ Telegram, voz, avisos, Claude │
 │ Vercel) — UI de      │        │ tools de dinero → cliente de  │
 │ finanzas             │        │ Supabase (sesión del usuario) │
 └─────────┬────────────┘        └──────────────┬────────────────┘
           │   sync_records (RLS por usuario)   │
           └──────────────► Supabase ◄──────────┘
```

1. **JARVIS habla con Supabase como el usuario**, nunca con la `service_role` key, para que RLS siga protegiendo
   los datos.
   - Se vincula una vez con el mismo código por correo: `jarvis presupuesto-vincular`.
   - Guarda solo el refresh token en `~/.config/jarvis/` (permisos 600) y lo renueva solo.
   - Usa la API REST de Supabase (PostgREST) con `urllib` + `truststore`, sin dependencias nuevas.
2. **Escribir:** "gasté 25 mil en almuerzo" crea un `Movement` válido en `presupuesto:movements`.
   - Id ULID, `amountMinor` negativo para gastos y `month` calculado.
   - Cuenta y subtema elegidos del catálogo real (`presupuesto:accounts`, `presupuesto:subtemas`). Si no está
     claro, JARVIS pregunta.
   - La app lo recibe en su siguiente sincronización.
   - Se respeta el contrato de la app: `updated_at` en su columna, `data` sin `updatedAt` y borrados como tombstone.
3. **Leer:**
   - `/dinero` y las tools pasan a calcular, en código y en Python, el mes real contra el presupuesto por
     tema/subtema, y los saldos por cuenta.
   - Para eso se portan las reglas de `src/domain/monthly.ts`, `budgets.ts` y `balances.ts`, con pruebas que
     usen los mismos casos.
   - Avisos nuevos posibles: "vas en el 90 % del presupuesto de comida".
4. **Lo que es solo de JARVIS se queda en JARVIS** por ahora: cobros a clientes, TRM y avisos. Los cobros podrían
   pasar después a una tabla `presupuesto:receivables` (o `jarvis:receivables`) si se quieren ver en la app.
5. **Migración:** los movimientos que JARVIS haya guardado en `money_moves` se ofrecen para subir una vez a
   presupuesto (con revisión de cuenta y subtema). Después, las tools de gastos dejan de usar SQLite.

### Por qué así

- No se duplica la contabilidad. La app ya resuelve sincronización, conflictos y UI móvil, y JARVIS aporta el
  lenguaje natural y la voz, los avisos y la IA.
- El iPhone ya tiene una UI de finanzas en Vercel: la PWA de JARVIS (v0.16) no necesita reimplementarla.
- Supabase con RLS y sesión del usuario mantiene el principio de permiso mínimo.

### Riesgos a vigilar

- **Contrato de datos:** si la app cambia su esquema (por ejemplo, un `version(4)` de Dexie), JARVIS debe seguirlo.
  Mitigación: tests de contrato en ambos repos con fixtures JSON compartidos.
- **Reloj y last-write-wins:** JARVIS escribe con la hora del PC; un reloj desfasado puede perder ediciones.
- **Validez:** un movimiento con `subtemaId` inexistente rompería vistas de la app. JARVIS solo debe usar ids que
  existan en el catálogo.
- **Privacidad:** los gastos ya están en Supabase porque el usuario lo eligió. Calendario, correos y memoria de
  JARVIS **no** se suben.

## Plan por versiones (propuesta)

1. **v0.18, conexión:**
   - `presupuesto-vincular` (código por correo).
   - Cliente de Supabase en Python que lea catálogo, movimientos y presupuestos y escriba movimientos.
   - Tools de gastos sobre presupuesto; `/dinero` con presupuesto contra real.
   - Tests de contrato con fixtures sacados de la app.
2. **v0.18.1:** migración opcional de `money_moves` y alertas de presupuesto ("vas en el 90 %").
3. **Más adelante:**
   - Cobros visibles en la app.
   - Una sola PWA para el iPhone (presupuesto + chat con JARVIS).
   - Evaluar un monorepo si conviene.

## Decisiones pendientes del usuario

1. ¿Presupuesto es la fuente de verdad de gastos e ingresos? Recomendado: sí.
2. ¿JARVIS entra como el usuario con código por correo? Recomendado: sí, no con `service_role`.
3. ¿Los cobros a clientes se quedan en JARVIS por ahora? Recomendado: sí.
4. ¿Mantener dos repositorios, conectados por el contrato de Supabase? Recomendado por ahora: sí.
5. Para escribir en el repo de presupuesto (tests de contrato, cambios de esquema), hay que darle acceso de
   escritura a la sesión (`add_repo` con push). Por ahora solo se leyó.
