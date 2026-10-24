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
