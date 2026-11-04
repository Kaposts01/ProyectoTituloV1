# DATA-03 — Modelo de Datos Payku

> Sprint 1 — Auditoría de Datos. Fuente: `app/models/payku_channel.py`, `app/services/channel_consolidation.py`.

## Tablas de canal (`p_*`)

| Tabla | Modelo SQLAlchemy | Clave de idempotencia | Descripción |
|---|---|---|---|
| `p_clients` | `PaykuClient` | `UNIQUE(external_id)` | Clientes Payku |
| `p_plans` | `PaykuPlan` | `UNIQUE(external_id)` | Planes de suscripción |
| `p_subscriptions` | `PaykuSubscription` | `UNIQUE(external_id)` | Suscripciones recurrentes |
| `p_transactions` | `PaykuTransaction` | `UNIQUE(external_id)` | Transacciones de cobro |

### p_clients — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `external_id` | String(255) | ID del cliente en Payku |
| `name` | String(255) | Nombre completo (sin separar) |
| `rut` | String(20) | **RUT** — señal de identidad cross-canal, indexado |
| `email` | String(320) | Indexado |
| `phone` | String(50) | Teléfono |
| `status` | String(50) | Estado del cliente |

### p_plans — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `name` | String(255) | Nombre del plan |
| `code` | String(100) | Código interno Payku, indexado |
| `amount` | String(50) | Monto (string) |
| `total_suscription` | Integer | Total de suscripciones en el plan |
| `total_suscription_active` | Integer | Suscripciones activas en el plan |

### p_subscriptions — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `client_id` | String(255) | FK lógica a `p_clients.external_id` |
| `plan_id` | String(255) | FK lógica a `p_plans.external_id` |
| `status` | String(50) | Estado: `active`, `register`, `suspended_awaits_change_plan`, otros |
| `last_status_current_payment` | String(50) | Estado del último pago |
| `start_date` | String(50) | Fecha de inicio |
| `end_date` | String(50) | Fecha de término |
| `amount` | String(50) | Monto actual (puede ser NULL, se rellena con el monto de la última transacción exitosa) |
| `next_charge_date` | Date | PK-PAR-11 (migración 0065): próxima fecha de cobro; solo la trae el reporte de suscripciones (la API no) |

### p_transactions — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `subscription_id` | String(255) | FK lógica a `p_subscriptions.external_id` |
| `status` | String(50) | Estado: `success`, `failed`, etc. |
| `created_at_api` | String(50) | Timestamp de la transacción |
| `amount` | String(50) | Monto de la transacción |
| `commission`, `net_amount` | Numeric(14,2) | PK-PAR-11 (migración 0065): comisión y monto final (neto) del reporte; NULL si el voucher no está en un reporte cargado o se repite en él |
| `payment_method` | String(50) | PK-PAR-11: medio de pago del consolidado (o tipo de pago de `dataTransacciones`) |
| `installment_number` | Integer | PK-PAR-11: número de cuota de «Cobro: # n» (del reporte o del `description` del API); solo se completa si está vacío |

## Reportes descargados de Payku (PK-PAR-10, d115 opción b)

`app/services/payku_report_parser.py` y `payku_report_import.py` (sin ruta HTTP ni pantalla todavía). **No hay documentación oficial del formato** en `docs/integrations/payku/`: las firmas se diseñaron con los encabezados medidos en la auditoría del 2026-10-29 (`docs/planning/auditoria-2026-10-29/parity_payku.md`, sección 1) y el parser **valida los encabezados** al abrir (columnas faltantes → error con sus nombres; sin firma reconocible → «tipo no soportado»). Validar con un archivo real antes de cargar en `crm`.

| Hoja (por firma de columnas) | Columnas exigidas | Destino |
|---|---|---|
| `dataTransacciones` («Export») | Transacción, Fecha de Transacción, Monto, Comisión, Monto Final (+ Proveedor, Tipo de Pago, Orden, Concepto) | `p_report_transactions` (`source_layout = data_transacciones`) |
| consolidado «Transacciones» | Identificador/vaucher, Fecha, Monto, Comisión, Monto Final (+ Concepto, Orden, Liquidación, Medio de pago, Débito/Crédito) | `p_report_transactions` (`consolidado`) |
| consolidado «Liquidaciones» | Liquidación, Monto, Estatus, Fecha Depósito | `p_report_settlements` |
| `datasubscripciones` | Suscripción ID, Estatus, Próxima Fecha Cobro | proyecta `p_subscriptions.next_charge_date` |

«Monedero» y «Retiros» se ignoran. Datos personales (Nombre/Teléfono/Email Origen, Email, Nombre, Teléfono, 4 últimos dígitos, Orden Externa) nunca se leen; del Concepto solo se guarda si es cuota y su número. Clave de transacción `row_key` = sha256(voucher, orden, fecha, monto), porque en los años antiguos el voucher se repite. Idempotente por `p_report_files(report_type, file_sha256)`. La proyección a `p_transactions` solo usa vouchers únicos en el reporte. Fechas sin zona = hora de Chile; acepta `aaaa-mm-dd`, `dd/mm/aaaa` y `dd-mm-aaaa`.

## Consolidación Payku → Tablas canónicas

| Tabla Payku | Tabla canónica | Mapeo clave |
|---|---|---|
| `p_clients` | `clients` | `source="payku"`, `social_id=rut`, `first_name=name`, `last_name=NULL` |
| `p_plans` | `plans` | `source="payku"`, `description=NULL`, `plan_type=NULL` |
| `p_subscriptions` | `subscriptions` | `source="payku"`, `client_social_id` desde `raw_payload.client.rut` |
| `p_transactions` | `payments` | `source="payku"`, `charge_external_id=subscription_id`, `client_external_id=NULL` |

### Lógica especial en suscripciones Payku

- **Monto faltante:** si `p_subscriptions.amount` es `NULL`, se rellena con el monto de la última transacción exitosa de esa suscripción (lookup previo sobre `p_transactions` filtrado por `status="success"`).
- **`canceled_at`:** se extrae del historial de estados `raw_payload.logs.status[]`, cuyas entradas son `{change_date, initial_status, final_status}` (la clave real es **`final_status`**): se toma el `change_date` más reciente de la entrada cuyo `final_status` coincide con el estado actual (sin distinguir mayúsculas). Si no hay esa transición, se usa `raw_payload.end`.
- **Suscripciones activas:** status `active`, `register`, `suspended_awaits_change_plan` → `canceled_at=NULL`.
- **`core_subscriptions.ended_at`** (ETL Core, PK-PAR-03): misma regla que `canceled_at` (log `final_status`/`change_date` y, sin esa transición, la columna `p_subscriptions.end_date`). Para los estados vigentes (`active`, `register`, `suspended_awaits_change_plan`) se sigue usando solo `end_date`, porque una transición hacia ellos es un alta y no un término. Cobertura medida el 2026-10-29: el log da fecha para `cancel` 116/116, `delete` 265/681 y `suspended` 579/1.048; unida con `end_date`, `delete` queda en 382/681 (299 suscripciones eliminadas no tienen fecha de término en ninguna fuente). Datos ya cargados: `core_subscriptions.ended_at` se corrige en la próxima ejecución del ETL Core (nocturno o `/etl/core/payku`).
- **`core_payments.occurred_at`** (PK-PAR-04): conserva la hora. `p_transactions.created_at_api` llega sin zona (`2023-09-30 19:58:35`) y se interpreta como hora de Chile (`America/Santiago`, con horario de verano); un texto con zona se respeta. Antes se truncaba a la fecha en UTC. Los pagos ya cargados se corrigen con un `UPDATE` explícito en la próxima ejecución del ETL Core (puede mover entre meses los cobros hechos de noche el último día del mes).
- **Motivo mínimo de rechazo** (PK-PAR-06 / RJ-10): el rechazo más reciente de cada suscripción toma su `last_status_current_payment` cuando es `maximum attempt limit`, `first payment rejected` o `payment consumes failed` (valor crudo en `core_payments.rejection_reason`, sin código; `rejection_format` muestra la etiqueta). No es la glosa del cobro (PK-PAR-05) y nunca pisa un motivo ya guardado.
- **Taxonomía común** (PK-PAR-07): `core_payku_etl.normalize_payku_status` mapea `register`→`pending_enrollment`, `active` y `suspended_awaits_change_plan`→`active`, `suspended`→`suspended`, `cancel`/`delete`/`finish`→`cancelled`; otro valor → `unknown` (aviso en el log). `core_subscriptions.status` sigue guardando el estado crudo: persistir el normalizado requiere decidir columna nueva (migración) o reemplazo. Una suscripción `register` sin monto toma el monto de su plan (`p_plans.amount`).

## Flujo de sincronización

```
Payku API
  → ingestion/connector (payku sync)
  → p_clients / p_plans / p_subscriptions / p_transactions
  → channel_consolidation.py (_consolidate_payku_*)
  → clients / plans / subscriptions / payments
```

**Nota:** Payku no tiene una tabla de `charges` separada. Las transacciones se consolidan directamente a `payments` con `charge_external_id=subscription_id` (la suscripción actúa como cobro padre).

## Brechas y limitaciones conocidas

| ID | Tipo | Descripción |
|---|---|---|
| GAP-PK-01 | Identidad | `client_social_id` en suscripciones consolidadas se extrae de `raw_payload.client.rut`. Si el payload no incluye el objeto `client`, queda `NULL`. |
| GAP-PK-02 | Mapeo | `plan_type` → `NULL` en todas las suscripciones. Payku no expone tipo de plan en la API. |
| GAP-PK-03 | Nombre | `last_name` siempre `NULL` en `clients` para Payku. |
| GAP-PK-04 | Cargo vs pago | No existe distinción `charge`/`payment` en Payku. Una transacción puede ser el cargo programado y el resultado del mismo. Esto dificulta la reconciliación con el modelo canónico. |
| GAP-PK-05 | Datos históricos | Cobertura histórica de Payku tiene limitaciones conocidas. Ver Technical Debt. |
| GAP-PK-06 | Trazabilidad | `source_record_id` es `NULL` en la consolidación. |
