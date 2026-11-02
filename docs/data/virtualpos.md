# DATA-01 — Modelo de Datos VirtualPOS

> Sprint 1 — Auditoría de Datos. Fuente: `app/models/vp.py`, `app/services/channel_consolidation.py`.

## Tablas de canal (`vp_*`)

| Tabla | Modelo SQLAlchemy | Clave de idempotencia | Descripción |
|---|---|---|---|
| `vp_clients` | `VpClient` | `UNIQUE(platform, external_id)` | Clientes/socios del proveedor |
| `vp_plans` | `VpPlan` | `UNIQUE(platform, external_id)` | Planes de suscripción recurrente |
| `vp_subscriptions` | `VpSubscription` | `UNIQUE(platform, external_id)` + índice parcial activo/suscribiendo |
| `vp_charges` | `VpCharge` | `UNIQUE(platform, external_id)` | Cobros programados |
| `vp_payments` | `VpPayment` | `UNIQUE(platform, external_id)` | Pagos/intentos resultantes |

### vp_clients — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `external_id` | String(255) | ID del cliente en VirtualPOS |
| `platform` | String(50) | Cuenta VP de origen: `virtualpos1` o `virtualpos2` (ver GAP-VP-02) |
| `social_id` | String(50) | **RUT** — señal de identidad principal cross-canal |
| `email` | String(320) | Indexado |
| `status` | String(50) | Estado del cliente en el proveedor |
| `cards` | JSONB | Tarjetas registradas (array) |
| `raw_payload` | JSONB | Payload completo del proveedor |

### vp_subscriptions — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `client_external_id` | String(255) | FK lógica a `vp_clients.external_id` |
| `client_social_id` | String(50) | RUT del cliente (denormalizado) |
| `plan_external_id` | String(255) | FK lógica a `vp_plans.external_id` |
| `service_id` | String(255) | ID del servicio VP |
| `status` | String(50) | ACTIVA / SUSCRIBIENDO / CANCELADA / etc. |
| `suscription_date` | String(50) | Fecha de activación (string ISO) |

Índice parcial `uq_vp_sub_active_plan_client`: previene duplicados activos para el mismo cliente+plan. Ver migración `0036`.

### vp_charges — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `subscription_external_id` | String(255) | FK lógica al cobro padre |
| `charge_date` | String(50) | Fecha del cobro (string) |
| `status` | String(50) | Estado del cobro |

### vp_payments — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `charge_external_id` | String(255) | FK lógica al cobro. El listado `GET /payments` no lo trae: lo llenan solo cruces exactos (ver «Vínculo pago → cobro»). La sync no lo escribe (VP-PAR-06) |
| `payment_date` | String(50) | Fecha del pago (string) |
| `status` | String(50) | Estado del pago |

## Consolidación VP → Tablas canónicas (`crm.py`)

| Tabla VP | Tabla canónica | Mapeo clave |
|---|---|---|
| `vp_clients` | `clients` | `source=platform`, `external_id`, `social_id=social_id` |
| `vp_plans` | `plans` | `source=platform`, `external_id` |
| `vp_subscriptions` | `subscriptions` | `source=platform`, `external_id` |
| `vp_charges` | `charges` | `source=platform`, `external_id` |
| `vp_payments` | `payments` | `source=platform`, `external_id` |

La consolidación lee todos los registros de tablas `vp_*` y upserta en las tablas canónicas mediante `_upsert_centralized` con la constraint `(source, external_id)`.

## Flujo de sincronización

```
VirtualPOS API
  → ingestion/connector (virtualpos_sync.py)
  → vp_clients / vp_plans / vp_subscriptions / vp_charges / vp_payments
  → channel_consolidation.py (_consolidate_vp_*)
  → clients / plans / subscriptions / charges / payments
```

También existe `core_vp_etl.py` (Pipeline B) y `crm_materialization.py` (legacy). Ver `channel_consolidation.py` docstring para el estado de la transición.

## Mapeo reporte del portal → CRM (VP-PAR-14, auditoría del 2026-10-29)

Fuente: [`planning/auditoria-2026-10-29/parity_virtualpos.md`](../planning/auditoria-2026-10-29/parity_virtualpos.md) §3.
El importador de los reportes PAT y sus tablas `vp_report_*` están en [`vp-reports.md`](vp-reports.md). Leyenda: COL = columna
propia; RAW = solo en `raw_payload`; REP = tabla del reporte; NO = no existe.

**Cantidad (ventana 2025-02-24 a 2026-10-26):** paridad exacta. Los 86.541 `Id cargo` del portal están en `vp_charges` (0 faltantes,
0 sobrantes, mes por mes), con igual estado, fecha, monto y suscripción; las 9.005 suscripciones del reporte están en `vp_subscriptions`;
los 72.816 `UUID transacción` están en `vp_payments`. `vp_charges` además guarda la programación futura (`cancelado` hasta 2031): los KPIs
la excluyen con la regla de VP-PAR-10.

### Cobros (`TransaccionesPAT`)

| Columna del reporte | Campo CRM | Estado |
|---|---|---|
| Id cargo | `vp_charges.external_id`, `core_charges.external_id` | COL, 100 % |
| Id suscripción | `vp_charges.subscription_external_id` | COL, 100 % |
| Estado del cargo, Fecha programada, Monto, Moneda | `vp_charges.status/charge_date/amount/currency`, `core_charges.*` | COL, 0 diferencias |
| UUID transacción | `vp_payments.external_id` (= `order.uuid`) | COL; vínculo al cobro: ver abajo |
| Código y glosa de autorización/error/rechazo | `payment_rejection_details.code/reason` (`capture_source = report_pat`) → `core_payments.rejection_*`, `core_charges.latest_rejection_*` | REP → COL (tabla única, D3) |
| Medio de pago (Débito/Crédito/Prepago), Final número tarjeta | `vp_report_payments.payment_medium/card_last4` | REP (el API no lo tiene por cobro) |
| Fecha de autorización, comisión, abono, fecha de abono | `vp_payments.raw_payload.order.*` y `vp_report_payments.*` | RAW / REP (VP-PAR-07 los promoverá a columnas) |
| Alias POS, Código de vendedor, Origen | `vp_subscriptions.raw_payload` / `vp_report_payments.pos_alias`, `seller_code_hash` (HMAC) | RAW / REP |
| Número de cargo (N de M) | `vp_report_payments.charge_number/charges_total` | REP |
| Nombre, apellido, correo, RUT | `vp_clients.*` | COL (el importador nunca los guarda) |

### Suscripciones (`SuscriptoresPAT`)

| Columna del reporte | Campo CRM | Estado |
|---|---|---|
| Id de suscripción | `vp_subscriptions.external_id` | COL, 9.005/9.005 |
| Estado, Fecha de suscripción, Fecha de cancelación | `vp_subscriptions.status/suscription_date/canceled_at`, `core_subscriptions.status/started_at/ended_at` | COL |
| Motivo de rechazo (suscripción fallida) | `vp_report_subscriptions.rejection_reason` | REP; VP-PAR-09 lo proyecta en lectura (`core_vp_etl.project_subscription_report_fields`); `core_subscriptions` no tiene columna (requiere migración) |
| Tipo, marca y últimos 4 de la tarjeta | API: `vp_subscriptions.raw_payload.payment_method` (70 %); reporte: `vp_report_subscriptions.card_*` | RAW / REP; la API manda y el reporte completa los ~1.784 que faltan (VP-PAR-09) |
| Contadores de cargos, próximo cargo, despacho | `vp_report_subscriptions.charges_*` / NO | REP / NO (vacíos en el portal) |

### Vínculo pago → cobro (VP-PAR-06)

`vp_payments.charge_external_id` y `core_payments.charge_id` se llenan **solo por cruces exactos del UUID del pago**, con `UPDATE`
idempotente donde el vínculo está vacío; nunca por RUT ni por fecha:

1. Reporte PAT: `UUID transacción` → `Id cargo` (1 a 1; un UUID en dos cobros no se vincula). Lo aplican el importador y, en cada
   corrida, el ETL Core (`core_vp_etl._link_payments_to_charges`), que así vincula también los `core_payments` creados después de la carga.
2. Glosas capturadas (`payment_rejection_details`, RJ-06/RJ-04).
3. Cobros cuyo payload trae `payment.order.uuid` (`/suscription/{id}/charges`, `/charge/{id}`; el `charge_program` del listado hoy no).

`extract_vp_payment` ya no escribe la columna, así que la sync nocturna no borra el vínculo. Los pagos posteriores al último reporte
cargado quedan sin vínculo hasta cargar un reporte nuevo (los rechazados lo reciben de la captura RJ-06).

### Códigos de rechazo (VP-PAR-03 / VP-PAR-05)

`app/services/vp_rejection_codes.py`: catálogo oficial (`-1` a `-11`, `-1001` a `-1018`) y, de los códigos del adquirente `-2xxx`, solo
`-2122` («Violación de seguridad», documentado en `integrations/virtualpos/resources/payments.md`). Los otros 11 `-2xxx` vistos en los
reportes (165 rechazos; p. ej. `-2119`, `-2121`, `-2133`, `-2150`, `-2152`) **no tienen glosa documentada**: se muestra la glosa que entrega
el proveedor. `rejection_format.format_rejection_with_code` muestra el motivo con el código («Tarjeta expirada (código -8)»).

## Brechas y limitaciones conocidas

| ID | Tipo | Descripción |
|---|---|---|
| GAP-VP-01 | Tipo de dato | `amount` almacenado como `String` en todas las tablas VP, no como `Numeric`. Conversión numérica ocurre aguas arriba si se necesita. |
| GAP-VP-02 | Identidad (resuelto) | `platform` solo puede tomar `virtualpos1` o `virtualpos2`, las dos cuentas VP. `_VP_PLATFORMS` en `app/services/channel_store.py` lo define y `channel_consolidation.py` lo valida; un valor desconocido se omite con warning. |
| GAP-VP-03 | Trazabilidad (parcial) | `source_record_id` se rellena en la consolidación mediante `_source_record_ids` / `_link_source_records`. El backfill de filas históricas (`scripts/maintenance/backfill_source_record_ids.py`) está escrito, pero no ejecutado. |
| GAP-VP-04 | Datos históricos | Datos VirtualPOS históricos tienen limitaciones conocidas en cobertura. Ver Technical Debt. |
| GAP-VP-05 | Payku sin `plan_type` | No aplica a VP, pero el campo `plan_type` en `vp_plans` puede ser `NULL` si el proveedor no lo informa. |
