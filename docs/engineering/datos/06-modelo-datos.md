# Modelo de Datos — SynkmetriX

**Última actualización:** 2026-10-20
**Ítem cubierto:** 6 (modelo de datos — diagrama ER formal)

---

## Diagrama ER — Core Layer 3

Entidades centralizadas independientes de proveedor.

```mermaid
erDiagram
    core_clients {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
    }

    external_identities {
        uuid id PK
        uuid client_id FK
        varchar source
        varchar resource_type
        varchar external_id
        timestamptz linked_at
        varchar link_reason
        timestamptz created_at
    }

    core_client_attributes {
        uuid id PK
        uuid client_id FK
        varchar source
        varchar attribute_type
        text attribute_value
        timestamptz observed_at
        timestamptz created_at
    }

    core_subscriptions {
        uuid id PK
        uuid client_id FK
        varchar source
        varchar external_id
        varchar status
        numeric amount
        varchar currency
        timestamptz started_at
        timestamptz ended_at
        timestamptz created_at
        timestamptz updated_at
    }

    core_charges {
        uuid id PK
        uuid subscription_id FK
        varchar source
        varchar external_id
        varchar period_reference
        timestamptz due_at
        numeric amount
        varchar currency
        uuid latest_rejection_payment_id FK
        varchar latest_rejection_code
        text latest_rejection_reason
        timestamptz latest_rejection_at
        timestamptz created_at
        timestamptz updated_at
    }

    core_payments {
        uuid id PK
        uuid subscription_id FK
        uuid charge_id FK
        varchar source
        varchar external_id
        varchar source_status
        timestamptz occurred_at
        numeric amount
        varchar currency
        varchar rejection_code
        text rejection_reason
        timestamptz rejection_reported_at
        timestamptz created_at
        timestamptz updated_at
    }

    client_match_candidates {
        uuid id PK
        uuid client_id_a FK
        uuid client_id_b FK
        varchar match_level
        jsonb match_signals
        varchar status
        timestamptz reviewed_at
        varchar reviewed_by
        text notes
        timestamptz created_at
        timestamptz updated_at
    }

    core_clients ||--o{ external_identities : "tiene"
    core_clients ||--o{ core_client_attributes : "tiene"
    core_clients ||--o{ core_subscriptions : "tiene"
    core_clients ||--o{ client_match_candidates : "cliente_a"
    core_clients ||--o{ client_match_candidates : "cliente_b"
    core_subscriptions ||--o{ core_charges : "genera"
    core_subscriptions ||--o{ core_payments : "tiene"
    core_charges ||--o{ core_payments : "vincula"
    core_payments ||--o| core_charges : "último rechazo"
```

---

## Diagrama ER — Staging / Raw (por proveedor)

```mermaid
erDiagram
    source_records {
        uuid id PK
        varchar source
        varchar resource_type
        varchar external_id
        jsonb payload
        jsonb sync_context
        timestamptz first_seen_at
        timestamptz last_seen_at
    }

    source_record_observations {
        uuid id PK
        uuid source_record_id FK
        varchar payload_hash
        jsonb payload_sanitized
        timestamptz provider_observed_at
        timestamptz ingested_at
    }

    vp_clients {
        uuid id PK
        varchar platform
        varchar external_id
        varchar first_name
        varchar last_name
        varchar email
        varchar social_id
        jsonb cards
        jsonb raw_payload
    }

    vp_plans {
        uuid id PK
        varchar platform
        varchar external_id
        varchar name
        varchar amount
        varchar currency
    }

    vp_subscriptions {
        uuid id PK
        varchar platform
        varchar external_id
        varchar status
        varchar plan_external_id
        varchar client_external_id
    }

    vp_charges {
        uuid id PK
        varchar platform
        varchar external_id
        varchar status
        varchar subscription_external_id
    }

    vp_transactions {
        uuid id PK
        varchar platform
        varchar external_id
        varchar social_id
        varchar status
        numeric amount
    }

    t_subscriptions {
        uuid id PK
        varchar external_id
        varchar status
        varchar deleted_status
        numeric amount
    }

    t_transactions {
        uuid id PK
        varchar external_id
        varchar subscription_external_id
        varchar status
        numeric amount
    }

    p_subscriptions {
        uuid id PK
        varchar external_id
        varchar status
        numeric amount
    }

    p_transactions {
        uuid id PK
        varchar external_id
        varchar subscription_external_id
        varchar status
        numeric amount
    }

    tch_dues {
        uuid id PK
        varchar rut
        varchar nombre
        varchar periodo
        numeric monto
        varchar estado
    }

    tch_memberships {
        uuid id PK
        varchar rut
        varchar nombre
        varchar estado
    }

    source_records ||--o{ source_record_observations : "observaciones"
    vp_subscriptions }o--|| vp_plans : "plan"
    vp_subscriptions }o--|| vp_clients : "cliente"
    vp_charges }o--|| vp_subscriptions : "suscripción"
    t_transactions }o--|| t_subscriptions : "suscripción"
    p_transactions }o--|| p_subscriptions : "suscripción"
```

---

## Diagrama ER — Webhooks Staging

```mermaid
erDiagram
    stg_toku_webhook_events {
        uuid id PK
        varchar toku_event_id
        varchar event_type
        jsonb payload
        boolean signature_verified
        varchar source_ip
        timestamptz received_at
        timestamptz created_at
    }

    stg_vpos_webhook_events {
        uuid id PK
        varchar event_type
        jsonb payload
        boolean signature_verified
        varchar source_ip
        timestamptz received_at
        timestamptz created_at
    }

    stg_payku_webhook_events {
        uuid id PK
        varchar event_type
        jsonb payload
        text raw_body
        varchar source_ip
        timestamptz received_at
        timestamptz created_at
    }
```

---

## Diagrama ER — Operacional (auth, runs)

```mermaid
erDiagram
    users {
        uuid id PK
        varchar username
        varchar password_hash
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }

    roles {
        uuid id PK
        varchar name
        text description
    }

    permissions {
        uuid id PK
        varchar code
        varchar description
    }

    user_roles {
        uuid user_id FK
        uuid role_id FK
    }

    role_permissions {
        uuid role_id FK
        uuid permission_id FK
    }

    sync_runs {
        uuid id PK
        varchar source
        varchar status
        timestamptz started_at
        timestamptz finished_at
        int records_processed
        text error_message
    }

    etl_runs {
        uuid id PK
        varchar source
        varchar status
        timestamptz started_at
        timestamptz finished_at
        int records_processed
        text error_message
    }

    write_runs {
        uuid id PK
        varchar source
        varchar operation
        varchar status
        jsonb request_payload
        jsonb response_payload
        timestamptz created_at
        timestamptz finished_at
    }

    users ||--o{ user_roles : "tiene"
    roles ||--o{ user_roles : "asignado a"
    roles ||--o{ role_permissions : "tiene"
    permissions ||--o{ role_permissions : "asignado a"
```

---

## Invariantes y restricciones clave

| Tabla | Restricción | Propósito |
|-------|------------|-----------|
| `source_records` | UNIQUE `(source, resource_type, external_id)` | Idempotencia en ingesta |
| `external_identities` | UNIQUE `(source, resource_type, external_id)` | Una identidad externa por fuente |
| `core_subscriptions` | UNIQUE `(source, external_id)` | Idempotencia en ETL Core |
| `core_charges` | UNIQUE `(source, external_id)` | Idempotencia en ETL Core |
| `core_payments` | UNIQUE `(source, external_id)` | Idempotencia en ETL Core |
| `core_client_attributes` | UNIQUE `(source, attribute_type, attribute_value)` | Sin duplicados de atributos personales por fuente |
| `client_match_candidates` | UNIQUE `(client_id_a, client_id_b)` con `a < b` | Sin duplicados de pares; orden garantiza unicidad |
| `users` | UNIQUE `(username)` | Un usuario por nombre |
| `roles` | UNIQUE `(name)` | Un rol por nombre |
| `permissions` | UNIQUE `(code)` | Un permiso por código |

---

## Valores conocidos de campos clave

| Campo | Valores posibles | Fuente |
|-------|-----------------|--------|
| `source_records.source` | `virtualpos`, `toku`, `payku` | Connectors |
| `source_records.resource_type` | `subscription`, `charge`, `transaction`, `customer`, `plan` | Por proveedor |
| `core_client_attributes.attribute_type` | `rut`, `email`, `phone`, `name` | ETL Core |
| `client_match_candidates.match_level` | `B` (RUT), `C` (email) | ADR-001 |
| `client_match_candidates.status` | `pending`, `confirmed`, `rejected` | Revisión manual |
| `sync_runs.status` / `etl_runs.status` | `running`, `completed`, `failed` | Operacional |
| `write_runs.source` | `virtualpos`, `toku` | Write services |

---

*Documento generado como parte de la Fase 2 — Datos y comunicaciones.*
