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
| `platform` | String(50) | Nombre de la plataforma (ej. "virtualpos") |
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
| `charge_external_id` | String(255) | FK lógica al cobro |
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

## Brechas y limitaciones conocidas

| ID | Tipo | Descripción |
|---|---|---|
| GAP-VP-01 | Tipo de dato | `amount` almacenado como `String` en todas las tablas VP, no como `Numeric`. Conversión numérica ocurre aguas arriba si se necesita. |
| GAP-VP-02 | Identidad | `platform` toma el valor de `VpClient.platform` (variable por registro), no una constante "virtualpos". Puede haber valores distintos si la API retorna nombres de plataforma variables. |
| GAP-VP-03 | Trazabilidad | `source_record_id` se escribe como `NULL` en la consolidación (no hay vinculación a `source_records` en este flujo). |
| GAP-VP-04 | Datos históricos | Datos VirtualPOS históricos tienen limitaciones conocidas en cobertura. Ver Technical Debt. |
| GAP-VP-05 | Payku sin `plan_type` | No aplica a VP, pero el campo `plan_type` en `vp_plans` puede ser `NULL` si el proveedor no lo informa. |
