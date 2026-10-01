---
name: data-modeling
description: Design, review, or change SynkmetriX centralized data models while preserving provider-independent Core, staging traceability, idempotency, privacy, and unresolved identity decisions. Use for entities, relationships, identifiers, data migrations, and model reviews.
---

# Data Modeling

## Purpose

Guide consistent design and review of the SynkmetriX modelo centralizado. Prevent provider integrations from defining their own Core model or turning staging structures into Core structures.

## When To Use This Skill

Use this skill when a request involves:

- creating, changing, or reviewing a data entity, relationship, field, constraint, or migration;
- mapping provider data into STG or Core;
- identifiers, identity, cardinality, historical state, status normalization, money, timestamps, nullability, or traceability;
- data-model implications of reporting or analytics.

## When Not To Use This Skill

Do not use this skill for routine API, UI, connector, or operational changes without data-model impact. Do not use it to decide an unresolved architectural question without the required review and acceptance process.

## Sources Of Truth

Read, in this order, only the context relevant to the request:

1. `AGENTS.md`, `docs/memory/PROJECT_STATE.md`, and `docs/memory/CURRENT_SPRINT.md`.
2. `docs/data/centralized-model.md` and the affected entity note.
3. Relevant `docs/architecture/` and provider integration documentation.
4. Relevant accepted ADRs.

`docs/data/centralized-model.md` is **Status: Proposed**. Do not treat it as an approved physical schema. Identity centralizada, deduplication, the common status taxonomy, liquidations, data governance, and timezone policy remain `TBD` unless a higher-priority accepted decision says otherwise.

## Layer Boundaries

Keep the architectural flow intact:

```text
Fuente -> Connector -> STG / Raw -> ETL / Normalizacion -> Core centralizado -> API -> CRM / Reportes / Analytics
```

### Source Data

Provider-owned data and files. Their shapes, identifiers, and status vocabularies can differ.

### Staging / Raw

Maintain independent staging for each provider, such as `STG_VIRTUALPOS`, `STG_TOKU`, `STG_PAYKU`, and `STG_TCH` conceptually. Staging must preserve external identifiers, origin, ingestion timestamps, and sanitized raw payloads when reasonable. It must support traceability and reprocesamiento without destructive transformations.

Use the existing `source_records` idempotent key `(source, resource_type, external_id)` where applicable. Do not make a provider write directly to Core.

### Core Centralizado

Core represents SynkmetriX concepts, not a provider's resource schema. Current conceptual candidates are CLIENTE, SUSCRIPCION, COBRO_PROGRAMADO / CUOTA, PAGO / TRANSACCION, LIQUIDACION, PLAN, PLATAFORMA, and LOG_API. They are not a final physical schema.

### Derived And Analytics Data

Keep operational facts separate from derived metrics, scores, and predictive features. Evaluate analytics, feature-store, materialized-view, or scoring-layer alternatives before adding values such as `churn_probability`, `predicted_ltv`, or `recovery_score` to CLIENTE or SUSCRIPCION.

## Design Principles

### Provider Independence

Before adding an entity, determine whether the concept already exists, belongs in Core, belongs only in STG, is an attribute, is a relation, or is derived data. Never add provider-specific Core fields merely because one integration exposes them.

### Internal And External Identifiers

Prefer stable internal Core identifiers and retain provider IDs as external identifiers with provider context. The conceptual `ExternalIdentity(provider, external_id, cliente_id)` example is not approval to create a table or prescribe its implementation. Identity centralizada remains `TBD`.

Never assume RUT, email, or phone is mandatory, unique, a primary key, or sufficient evidence for a merge. Assess data quality, normalization, available identifiers, collisions, missing values, history, manual review, and merge reversibility first.

### Cardinality And Relationships

Document cardinality before defining physical constraints. Verify questions such as whether a person can have multiple subscriptions, a subscription can change provider, a payment can exist without a subscription, a payment can represent multiple attempts, a liquidation groups multiple payments, and a client has multiple external identifiers.

Conceptual examples such as CLIENTE `1:N` SUSCRIPCION and SUSCRIPCION `1:N` PAGO require verification against current documentation before becoming constraints.

### History And States

Do not destructively overwrite changes that have historical value. Evaluate each entity's need to retain state changes, evidence, and effective dates; do not impose event sourcing, history tables, or temporal tables without an approved decision.

STG retains the original provider state. Core may normalize it only with a documented, approved mapping and must retain the original provider state or equivalent traceability. The common taxonomy is `TBD`; do not invent mappings.

### Money, Time, And Nullability

For money, document currency, unit, precision, gross and net amounts, taxes, and fees when applicable. CLP may be current context but must not preclude other currencies without an accepted decision.

Differentiate provider event time, record creation and update time, ingestion time, synchronization time, payment effective date, and settlement date. Do not reuse one timestamp for different concepts. Timezone policy is `TBD` unless documented otherwise.

Before making a field `NOT NULL`, confirm every provider and historical record can provide it, whether it can legitimately be absent, whether it is derived, and whether the requirement is only for the frontend.

### Deduplication, Traceability, And Idempotency

Keep normalization, matching, deduplication, and merge separate. Never perform an irreversible merge solely from probabilistic matching. The policy requires an accepted decision.

Every Core fact should be explainable through provider, STG record, external ID, and ingestion date where feasible. Design ingestion and normalization for controlled upserts and reprocesamiento so processing the same source record twice does not silently duplicate data.

### Privacy

Apply data minimization. For each personal attribute, assess purpose, necessity, source, permissions, retention, exposure, and analytical use. Never preserve credentials, payment-card data, PAN, CVV/CVC, or other unnecessary sensitive information.

## Mandatory Checklist

Before proposing a relevant data-model change, answer:

1. **Entidad:** What concept is being modeled?
2. **Capa:** Does it belong to RAW, STG, CORE, or ANALYTICS?
3. **Fuente:** Which system provides it?
4. **Identificador:** What identifies the record?
5. **Identificadores externos:** Which provider IDs must remain?
6. **Cardinalidad:** How does it relate to other entities?
7. **Nullability:** Which fields can be absent?
8. **Historial:** Which changes need retention?
9. **Estados:** Are original and normalized statuses both preserved?
10. **Tiempo:** Which timestamps are needed?
11. **Dinero:** Are there amounts, currency, precision, taxes, or fees?
12. **Deduplicacion:** Can the same logical entity be represented twice?
13. **Trazabilidad:** Can the origin STG record be identified?
14. **Idempotencia:** What happens when the same data is processed twice?
15. **Migracion:** What is the impact on existing data and applied migrations?
16. **Privacidad:** Is every stored attribute necessary?
17. **Reporteria:** Which query need justifies this structure?

## Workflow

1. Read project state, the centralized model, the affected entity note, and relevant integration documentation.
2. Classify the request by layer and complete the mandatory checklist.
3. Identify accepted facts, `TBD` decisions, risks, and undocumented assumptions.
4. Propose the smallest provider-independent model change and compare it with the active architecture.
5. Assess migration, backfill, idempotency, traceability, privacy, and reporting impacts.
6. Request or create an ADR only when the proposal makes a durable architectural decision.
7. Use `project-memory` after an important accepted data decision to update durable project knowledge and `centralized-model.md` when appropriate.
8. Implement only when the task explicitly authorizes implementation. Applied migrations are immutable; add a new migration rather than changing one already applied.

## Context7

Use Context7 only to verify current behavior of PostgreSQL, SQLAlchemy, Alembic, Django ORM, Django REST Framework, or other relevant libraries when that behavior affects the requested design or implementation. Context7 does not decide SynkmetriX architecture.

## Examples

### A. Bad: Provider Columns In Core

Adding `virtualpos_subscription_id`, `toku_subscription_id`, and `payku_subscription_id` directly to SUSCRIPCION couples Core to current providers and requires a schema change for every new integration.

### B. Better: Extensible External Identity

Keep an internal subscription identity and design an extensible provider-scoped external-identifier relationship. The exact implementation still requires an accepted architectural decision; do not automatically create an `ExternalIdentity` table.

### C. Bad: Email As CLIENTE Primary Key

Email can be absent, changed, shared, malformed, or assigned to different people. It cannot be assumed to be an immutable global identity.

### D. Correct: Preserve Original State

`STG_TOKU` retains Toku's original status. ETL translates it only through an approved central status mapping and keeps the original value or equivalent traceability.

### E. Analytics Separation

Do not add `churn_probability` to CLIENTE merely because a predictive model is planned. Evaluate an isolated analytics, feature-store, materialized-view, or scoring layer first.

## Relationship With Other Skills

`data-modeling` decides how to design data layers and structures. `project-memory` decides which verified knowledge must persist in project memory, tasks, and ADRs. `prompt-optimizer` refines the user request and acceptance criteria before work begins. Do not duplicate their responsibilities.

## Constraints

- Do not implement a final identity, matching, deduplication, merge, status, settlement, or timezone policy while it is `TBD`.
- Use the centralized terminology required by `AGENTS.md`.
- Do not create provider-specific structures in Core, destructive transformations, unsafe merges, or unsupported constraints.
- Do not expose or retain secrets, credentials, or payment-card data.
- Do not create models, migrations, tables, or SQL unless the task explicitly authorizes implementation.

## Checklist Before Finishing

- [ ] The layer classification and mandatory checklist are complete.
- [ ] Provider-specific structures remain in STG, not Core.
- [ ] External IDs, traceability, and idempotency are preserved.
- [ ] `TBD` decisions remain explicit and no mapping or merge was invented.
- [ ] Historical, nullability, money, time, privacy, migration, and reporting impacts were assessed.
- [ ] Any durable accepted decision was routed through `project-memory` and an ADR when appropriate.
