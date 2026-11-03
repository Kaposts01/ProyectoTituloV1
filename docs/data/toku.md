# DATA-02 — Modelo de Datos Toku

> Sprint 1 — Auditoría de Datos. Fuente: `app/models/toku_channel.py`, `app/services/channel_consolidation.py`.

## Tablas de canal (`tk_*`)

| Tabla | Modelo SQLAlchemy | Clave de idempotencia | Descripción |
|---|---|---|---|
| `tk_customers` | `TokuCustomer` | `UNIQUE(external_id)` | Clientes Toku |
| `tk_subscriptions` | `TokuSubscription` | `UNIQUE(external_id)` | Suscripciones recurrentes |
| `tk_invoices` | `TokuInvoice` | `UNIQUE(external_id)` | Facturas/cobros programados |
| `tk_transactions` | `TokuTransaction` | `UNIQUE(external_id)` | Transacciones de pago |
| `tk_payments` | `TokuPayment` | `UNIQUE(external_id)` | Pagos registrados |
| `tk_payment_methods` | `TokuPaymentMethod` | `UNIQUE(external_id)` | Métodos de pago inscritos |

### tk_customers — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `external_id` | String(255) | ID del customer en Toku |
| `name` | String(255) | Nombre completo (no separado en first/last) |
| `government_id` | String(50) | **RUT** — señal de identidad cross-canal |
| `email` | String(320) | Indexado |
| `status` | String(50) | Estado del customer |

### tk_subscriptions — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `customer_id` | String(255) | FK lógica a `tk_customers.external_id` |
| `status` | String(50) | Estado de la suscripción |
| `anchor` | String(50) | Fecha de anclaje/inicio (usado como `suscription_date`) |
| `end_date` | String(50) | Fecha de término (usado como `canceled_at`) |
| `amount` | String(50) | Monto (string) |
| `currency_code` | String(10) | Código de moneda |

### tk_invoices — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `subscription_id` | String(255) | FK lógica a `tk_subscriptions.external_id` |
| `due_date` | String(50) | Fecha de vencimiento (→ `charge_date`) |
| `status` | String(50) | Estado de la factura |

### tk_transactions — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `payment_method_id` | String(255) | FK lógica a `tk_payment_methods.external_id` |
| `created_at_api` | String(50) | Fecha de la transacción |
| `status` | String(50) | Estado |

**Nota:** el `customer` y el vínculo a suscripción se extraen de `raw_payload` en la consolidación (no son columnas directas).

## Consolidación Toku → Tablas canónicas

| Tabla Toku | Tabla canónica | Mapeo clave |
|---|---|---|
| `tk_customers` | `clients` | `source="toku"`, `social_id=government_id`, `first_name=name`, `last_name=NULL` |
| `tk_subscriptions` | `subscriptions` | `source="toku"`, `client_external_id` desde `customer_id` o `raw_payload.customer` |
| `tk_invoices` | `charges` | `source="toku"`, `charge_date=due_date` |
| `tk_transactions` | `payments` | `source="toku"`, `charge_external_id` desde `raw_payload.payment_intents[].id_subscription` |
| `tk_payment_methods` | `payment_methods` | `source="toku"`, `client_external_id=customer_id` |

**Nota sobre transactions:** el vínculo a cobro (`charge_external_id`) se extrae del array `payment_intents` del payload crudo via `_toku_payment_subscription_id()`.

## Flujo de sincronización

```
Toku API
  → ingestion/connector (toku sync)
  → tk_customers / tk_subscriptions / tk_invoices / tk_transactions / tk_payment_methods
  → channel_consolidation.py (_consolidate_toku_*)
  → clients / subscriptions / charges / payments / payment_methods
```

## Brechas y limitaciones conocidas

| ID | Tipo | Descripción |
|---|---|---|
| GAP-TK-01 | Identidad | `client_social_id` es `NULL` en las suscripciones consolidadas — Toku no expone RUT en la suscripción directamente. Cross-referencia vía `government_id` del customer. |
| GAP-TK-02 | Mapeo | `plan_external_id` → `NULL` en todas las suscripciones consolidadas. Toku no expone un ID de plan estándar. |
| GAP-TK-03 | Datos extraídos de payload | `customer` y `subscription` en transacciones se leen de `raw_payload`, no de columnas indexadas. Si el payload cambia de estructura, la extracción falla silenciosamente. |
| GAP-TK-04 | Nombre | Toku retorna un campo `name` único (no `first_name`/`last_name`). `last_name` es siempre `NULL` en `clients` para Toku. |
| GAP-TK-05 | **BLQ-TK-01** | `flow_name` para checkout ENROLLMENT no configurado por Toku. Bloquea alta de socios nuevos. Ver `docs/integrations/toku/BLOCKER-TK-A1.md`. Estado al 2026-10-24: **sin respuesta de Toku, bloqueado**. |
| GAP-TK-06 | Trazabilidad | `source_record_id` es `NULL` en la consolidación. |
| GAP-TK-07 | Fechas | `suscription_date` = `recurring.anchor` (próximo cobro) y `canceled_at`/`started_at`/`ended_at` vacíos. **Corregido con los reportes (TK-PAR-05)** cuando el reporte de Productos está cargado; sin reporte se conserva el comportamiento anterior. |
| GAP-TK-08 | Estado | La API no trae estado de cliente ni de suscripción (solo `ACTIVE`/`PAUSED` y algunos `NULL`) ni lista las eliminadas. Se resuelve con reportes y señales (TK-PAR-06/TK-20), detrás de `TOKU_REPORT_SIGNALS_ENABLED`. |

## Reportes descargados del Backoffice (TK-17 a TK-20, TK-PAR-05/06)

La API REST de Toku no entrega el estado de la suscripción ni del medio de pago, ni la fecha de alta real, ni lista las
suscripciones eliminadas. El Backoffice sí lo exporta, y se carga a mano (una vez por semana, DEC-21). Código:
`app/services/toku_report_parser.py` (lectura), `toku_report_import.py` (carga), `toku_report_lifecycle.py` y
`core_toku_etl.py` (fechas), `toku_report_signals.py` (señales); modelos en `app/models/toku_report.py` (migraciones 0039 a
0041). Procedimiento para el usuario: [`toku-reports-load.md`](toku-reports-load.md).

### Reglas de lectura
* El tipo de reporte se detecta por la **firma de columnas** (nombres sin tildes ni mayúsculas), no por título ni nombre de archivo.
  Encabezado en la fila 7 (filas 1 a 6: título, fecha de generación, tipo de fecha, ventana); si el encabezado está en la
  fila 1 la fecha de generación es «ahora» y se avisa `generated_at_fallback_now`. Columnas repetidas (p. ej. «Medio de pago»
  en inscripciones) se leen por posición. Columnas extra se ignoran y se informan por nombre.
* **Datos personales**: nombre, mail, celular, RUT, ID Externo, número de tarjeta, token, bin, cuenta y datos PAC **nunca se leen
  ni se guardan**. `ID Producto` (texto libre que contiene el RUT) solo se guarda como `product_key_hash`
  (HMAC-SHA256 con `TOKU_REPORT_HASH_PEPPER`) más el `sub_` resuelto. Sin pepper el importador se niega a cargar.
* Idempotencia: `tk_report_files(report_type, file_sha256)` único (mismo archivo = «ya cargado»). Cada columna solo se
  actualiza si el reporte es igual o más nuevo que el dato guardado (guarda de frescura); `deleted_at_source` nunca se «des-elimina».

### Columnas que se leen
| Reporte (`report_type`) | Columnas de la firma | Tabla | Clave natural |
|---|---|---|---|
| Productos (`productos`) | ID (`sub_`), Fecha de Creación, Fecha de Eliminación, ID Producto, Cliente, is_recurring, Monto, due_day, Medio de Pago, Procesador de Pago, Estado | `tk_report_products` | `subscription_external_id` |
| Medios de pago (`medios_pago`) | ID (`pm_`), Fecha de Creación, Fecha de Eliminación, ID Producto, Tipo de Tarjeta, Marca Tarjeta, Banco Emisor, Estado, Procesador de Pago, last_payment_intent_response_code y _original_response_message | `tk_report_payment_methods` | `(payment_method_external_id, product_key_hash)` |
| Intentos de pago (`intentos`) | ID, fechas de creación y eliminación, Cliente, Deuda, ID Producto, Fecha de Vencimiento, Monto, Estado, Código de Respuesta Toku, Procesador de Pago, Fecha de Transacción, ID Mandato (solo se guarda si existe); hoja «Códigos de Error Toku» (24 códigos) | `tk_report_attempts`, `tk_report_response_codes` | `attempt_external_id`; `code` |
| Deudas (`deudas`) | ID, fechas, ID Producto, Fecha de Vencimiento (dd/mm/aaaa), Monto, Pagado, Anulado, Cliente, Estado | `tk_report_debts` | `debt_external_id` |
| Inscripciones (`inscripciones`) | ID, fechas, Medio de pago, Estado transacción, Código de Respuesta (formato largo `TEPSP1001`), Estado Medio de Pago, Fecha/Estado Último Intento de Pago, id_subscription | `tk_report_inscriptions` | `inscription_external_id` |

Desde TK-PAR-07 y TK-PAR-09 (migración 0057) también se cargan Clientes (`clientes` → `tk_report_customers`: ID `cus_`,
fechas de creación y eliminación, «Silenciado hasta»), Pagos v2 (`pagos` → `tk_report_payments`: tipo de pago, cuotas) y
Liquidaciones (`liquidaciones` → `tk_report_settlements`: comisión, neto, fecha de depósito). **Sus firmas de columnas son
supuestas** (se escribieron sin abrir reportes reales): validar con los encabezados reales antes de cargar en `crm`.
No soportados (se rechazan con 422 sin leer filas): Facturación, Contracargos y el resto. El panel de administración (pestaña
de sincronización, permiso `toku.reports.import`) sube los archivos y avisa si el dato tiene más de 7 días (DEC-21;
`GET /api/v1/imports/toku-reports/status`). **`Estado` en Productos es el estado del medio de pago, no el de la suscripción**; el ciclo de vida sale
de `Fecha de Eliminación`. `last_payment_intent_response_code` viene vacío en todos los medios: el código de rechazo por
suscripción se obtiene del último intento fallido. Las fechas sin zona horaria son hora de Chile (`America/Santiago`).

### Precedencia entre reporte y API (DEC-23)
| Dato | Gana | Detalle |
|---|---|---|
| Estado de la suscripción | **Reporte** | Eliminada en el reporte → `core_subscriptions.status = 'deleted_at_source'`; viva con estado de la API vacío → `ACTIVE`; `ACTIVE`/`PAUSED` de la API se respetan (el reporte no conoce las pausas). Solo con `TOKU_REPORT_SIGNALS_ENABLED=true`. |
| Estado del medio de pago | **Reporte** | Fila de Medios de pago (con fecha de eliminación → `deleted`); si no hay, el `Estado` del producto. |
| Fecha de alta | **Reporte** | `core_subscriptions.started_at` y `subscriptions.suscription_date` = Fecha de Creación del producto (hora de Chile en la tabla centralizada). `recurring.anchor` de la API es el **próximo cobro**: solo queda como respaldo si la suscripción no está en el reporte. |
| Fecha de baja | **API** si trae `end_date`; si no, el reporte | `ended_at` y `canceled_at` = `end_date` de la API; si está vacío, Fecha de Eliminación. Nunca se pisa un valor ya existente. |
| Montos, facturas, pagos | **API** | El reporte no sobreescribe `tk_invoices`, `tk_payments` ni el monto de la suscripción (solo se usa su monto para crear las bajas que la API no lista). |

La regla literal de DEC-23 dice «cuando el reporte es más reciente que el último sync de API». Se implementó la lectura práctica
del usuario («el reporte gana para estado y medio de pago») sin comparar fechas contra el sync diario, porque un reporte semanal
casi nunca sería más nuevo que la API. Queda como supuesto a confirmar.

### Suscripciones eliminadas que la API no lista (TK-PAR-05)
`core_toku_etl.materialize_report_dates(db, dry_run=False)` crea en `core_subscriptions` un registro de baja (`status =
'deleted_at_source'`, la misma convención de los «stubs» de invoices huérfanas) por cada producto eliminado del reporte que no
existe en core, con su fecha de alta, de baja, el monto del reporte y el cliente si su identidad ya existe; sin datos
personales. Idempotente. Corre dentro de `run_toku_core_etl` y se puede invocar a mano con
`scripts/maintenance/toku_report_lifecycle.py` (dry-run por defecto). **No** se crean en la tabla centralizada `subscriptions`
(para no mover los KPI de MRR/ARPU hasta TK-13); sí se corrigen allí las fechas de las que ya existen.

### Señales de suscripción (TK-PAR-06 y TK-20)
`app/services/toku_report_signals.py` llena `core_subscription_signals` (una fila por suscripción core con fila en Productos)
cuando `TOKU_REPORT_SIGNALS_ENABLED=true` (**apagada por defecto**; el recuperador todavía no las lee, REC-04; los KPIs de
Toku sí, desde TK-13, ver más abajo).

| Señal | Regla |
|---|---|
| `lifecycle_status` | `deleted` si el producto tiene Fecha de Eliminación; si no, `active` |
| `is_chargeable` | estado del medio de pago = `chargeable` |
| `is_effectively_active` | `active` **y** cobrable (DEC-18) |
| `consecutive_failed_debts` | racha de **cuotas** impagas «en firme» (DEC-16), de la más nueva hacia atrás. Una cuota es una deuda; está en firme si no se pagó ni se anuló y (algún intento terminó con código **2070**, o el último intento fue hace `TOKU_REPORT_FIRM_UNPAID_DAYS` días o más —7 por defecto, supuesto a confirmar— respecto a la fecha del reporte, o nunca hubo intento y venció hace esos días). Las cuotas con reintentos aún posibles o en proceso ni cuentan ni cortan la racha; una cuota pagada la corta |
| `consecutive_failed_attempts` | intentos fallidos seguidos (solo informativo; 3 intentos de una cuota **no** son una racha de 3) |
| tarjeta bloqueada | último intento fallido con 1019, 1051 o 2043 (sin pago posterior), o medio `permanent_failed` |
| tarjeta vencida | último intento fallido con 1010, 2044 o 2063 |
| `is_recoverable` / `recoverable_reason` | suscripción `active` y (bloqueada → `blocked_card`, vencida → `expired_card`, racha ≥ 3 → `streak`; prioridad en ese orden). Un medio con falla temporal sin racha no es recuperable (DEC-25) |
| `last_response_code`, `last_response_severity`, `last_attempt_at` | del último intento fallido / último intento |
| `report_generated_at`, `computed_at` | fecha de generación del reporte y del cálculo |

### KPIs de Toku: «suscripción activa efectiva» (TK-13, DEC-18; regla vigente: d118, opción c)
MRR, ARPU, suscriptores activos y clientes activos de Toku usan una sola regla, `app/services/toku_active.py`, en los tres
lugares que los calculan: dashboard de Toku (`staging._toku_centralized_dashboard`), dashboard general de canales
(`staging._compute_general_dashboard`, columna Toku de `channels` y `subscriptions`) y resumen de la jefatura
(`dashboard_general._mrr_by_channel`).

0. **`PAUSED` y estado vacío no cuentan nunca** (d118, opción c, aprobada el 2026-11-02): ni con señal efectiva del
   reporte, porque el reporte no conoce las pausas y un estado vacío de la API no prueba que la suscripción esté viva.
1. Si la suscripción tiene fila en `core_subscription_signals` **y** `TOKU_REPORT_SIGNALS_ENABLED=true`, manda
   `is_effectively_active` (el reporte gana para eliminación y medio de pago, DEC-23). Con la bandera apagada no se leen
   señales viejas.
2. Si no: **no eliminada** (estado distinto de `cancelled`, `canceled`, `cancelada`, `deleted`, `ended` y
   `deleted_at_source`) **y** con un medio de pago `chargeable` de la API que la liste en `subscription_ids`.

Historia: antes de TK-13 se exigía `status = 'active'` y medio `chargeable` de la API, sin mirar el reporte; la primera
versión de TK-13 contaba `PAUSED` y el estado vacío como activas; d118 las excluye otra vez. Cifras con los datos
sintéticos de `tests/test_toku_effective_active.py` (siete suscripciones, una por caso; montos en CLP):

| Caso | Estado API | Medio API | Señal del reporte | Antes de TK-13 | TK-13 v1 | d118 (vigente) |
|---|---|---|---|---|---|---|
| a | `ACTIVE` | chargeable | — | cuenta | cuenta | cuenta |
| b | `PAUSED` | chargeable | — | no | cuenta | no |
| c | vacío | chargeable | — | no | cuenta | no |
| d | `ACTIVE` | inactive | — | no | no | no |
| e | `CANCELLED` | chargeable | — | no | no | no |
| f | `ACTIVE` | chargeable | no efectiva (eliminada en el reporte) | cuenta | no | no |
| g | `ACTIVE` | inactive | efectiva (cobrable en el reporte) | no | cuenta | cuenta |

| KPI | Antes de TK-13 | TK-13 v1 | d118 (vigente) |
|---|---|---|---|
| Suscripciones activas | 2 | 4 | 2 |
| MRR | 17.000 | 27.000 | 13.000 |
| ARPU (un cliente por suscripción) | 8.500 | 6.750 | 6.500 |

Con la bandera de señales apagada (manda la API) el mundo sintético da MRR 17.000 (a y f) con d118, frente a 31.000
(a, b, c y f) con TK-13 v1.

En los datos reales, según la medición agregada de la auditoría del 2026-10-29 (`parity_toku.md`), la API tenía 518
suscripciones: 499 `ACTIVE`, 12 `PAUSED` y 7 sin estado. d118 saca del universo elegible esas 19 (12 + 7) frente a TK-13
v1; cuántas de ellas tenían medio cobrable (y por tanto cuánto baja el MRR) no se midió contra `crm` ni `crm_sandbox` en
este lote: queda para la próxima medición con permiso del usuario.

Los códigos 1051, 2043 y 2044 vienen del catálogo oficial de Toku (DEC-24) y no están entre los 24 de la hoja de los reportes.
El corte de «hace N días» es la fecha de generación más reciente de los reportes cargados. Deudas e Intentos deben estar
cargados con fechas parecidas para que la racha sea fiable (sin Deudas, una cuota sin intentos no se ve).

### Ruta de subida
`POST /api/v1/imports/toku-reports` (multipart, campo `report`, `.xlsx`, máx. 100 MB, `X-CSRF-Token`; permiso `toku.reports.import`,
solo `admin`). Respuestas: `200` resumen de contadores; `409 already_loaded` (mismo sha256) o `load_in_progress`; `413 too_large`;
`422 invalid_format` (también tipo no soportado); `503 pepper_not_configured`; `500 import_failed` (con etiqueta técnica).
Cada intento queda en `write_runs` (`source = toku`, `operation = import_report`) con tipo, nombre, sha256 y contadores, sin
contenido. Aviso `stale_report` si el archivo es más viejo que el dato guardado (esas filas no se aplican). Aún no hay pantalla.
