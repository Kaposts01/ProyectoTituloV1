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

### p_transactions — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `subscription_id` | String(255) | FK lógica a `p_subscriptions.external_id` |
| `status` | String(50) | Estado: `success`, `failed`, etc. |
| `created_at_api` | String(50) | Timestamp de la transacción |
| `amount` | String(50) | Monto de la transacción |

## Consolidación Payku → Tablas canónicas

| Tabla Payku | Tabla canónica | Mapeo clave |
|---|---|---|
| `p_clients` | `clients` | `source="payku"`, `social_id=rut`, `first_name=name`, `last_name=NULL` |
| `p_plans` | `plans` | `source="payku"`, `description=NULL`, `plan_type=NULL` |
| `p_subscriptions` | `subscriptions` | `source="payku"`, `client_social_id` desde `raw_payload.client.rut` |
| `p_transactions` | `payments` | `source="payku"`, `charge_external_id=subscription_id`, `client_external_id=NULL` |

### Lógica especial en suscripciones Payku

- **Monto faltante:** si `p_subscriptions.amount` es `NULL`, se rellena con el monto de la última transacción exitosa de esa suscripción (lookup previo sobre `p_transactions` filtrado por `status="success"`).
- **`canceled_at`:** se extrae del log de estados en `raw_payload.logs.status` buscando el `change_date` más reciente de la transición al estado actual. Si no hay log, se usa `raw_payload.end`.
- **Suscripciones activas:** status `active`, `register`, `suspended_awaits_change_plan` → `canceled_at=NULL`.

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
