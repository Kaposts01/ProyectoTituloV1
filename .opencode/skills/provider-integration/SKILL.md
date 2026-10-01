---
name: provider-integration
description: Design, review, document, or implement a SynkmetriX external provider connector while preserving provider-specific staging, idempotent source records, sanitized observability, safe retries, and the separation between connectors and Core. Use for VirtualPOS, Toku, Payku, TCH, webhooks, syncs, pagination, authentication, and provider contracts.
---

# Provider Integration

## Purpose

Define a consistent and safe pattern for SynkmetriX integrations with external providers. A connector obtains provider data and persists sanitized, traceable records in Raw/STG; separate ETL processes transform those records into the Core centralizado.

```text
PROVIDER
  -> CONNECTOR
  -> RAW / STG
  -> ETL / NORMALIZACION
  -> CORE CENTRALIZADO
```

This skill applies to API providers and file-based sources. TCH/Excel does not need an HTTP client, but still requires source traceability, idempotency, validation, and a separated ETL path.

## When To Use This Skill

Use this skill when a request involves:

- adding, reviewing, or changing a provider connector, synchronization, webhook, provider client, or provider contract;
- provider authentication, environment configuration, HTTP behavior, pagination, rate limits, retries, timeouts, checkpoints, or incremental reads;
- Raw/STG persistence, external identifiers, payload sanitation, sync observability, or source-specific mapping;
- enabling or reviewing a documented provider write through an approved internal flow.

## When Not To Use This Skill

Do not use this skill for:

- centralized identity, matching, deduplication, merge, or Core data-model design; use `data-modeling`;
- project state, ADR, blocker, or task maintenance without an integration change; use `project-memory`;
- user-request refinement; use `prompt-optimizer`;
- UI-only, reporting-only, or unrelated application changes.

## Sources Of Truth

Read only the context relevant to the provider and requested resource, in this order:

1. `AGENTS.md`, `docs/memory/PROJECT_STATE.md`, `docs/memory/CURRENT_SPRINT.md`, and `docs/memory/BLOCKERS.md`.
2. `docs/architecture/overview.md`, `data-flow.md`, `integrations.md`, and `security.md`.
3. `docs/data/centralized-model.md` when STG-to-Core mapping is affected.
4. `docs/integrations/<provider>.md` and verified official provider documentation.
5. Relevant accepted ADRs, including ADR-001 when the provider exposes person identifiers.
6. Existing provider client, sync service, and tests only to understand established behavior; do not treat implementation as a replacement for verified provider documentation.

Use Context7 only for current behavior of technical libraries used by the integration, such as an HTTP client, retry library, Pydantic, SQLAlchemy, or Alembic. Context7 does not replace official provider documentation.

## Layer Boundaries

The required flow is:

```text
Provider API or file
  -> Connector
  -> Raw / STG_PROVIDER
  -> ETL / Normalizacion
  -> Core centralizado
```

The connector owns provider interaction only: authentication, requests, pagination, rate limits, timeouts, safe retries, transport validation, extraction of provider identifiers and timestamps, and persistence to Raw/STG according to the active architecture.

The connector must not:

- write directly to Core;
- decide identidad centralizada, matching, deduplication, or merge;
- invent a shared status taxonomy or business rule;
- calculate predictive scores;
- destructively delete Core records;
- hide a provider-specific mapping inside Core logic.

Provider data reaches Core only through a separate, traceable ETL/normalization step. Do not change this boundary without an explicit accepted architectural decision.

## Configuration And Authentication

- Keep credentials exclusively in environment variables or deployment secret management. Use names such as `TOKU_API_KEY`, `PAYKU_API_KEY`, and `VIRTUALPOS_API_KEY`; never include values in code, documentation, errors, or logs.
- Keep provider URLs, timeouts, retry limits, credentials, and environment selection centralized in configuration. Do not scatter environment conditionals through provider methods.
- Distinguish `development`, `test`, `sandbox`, and `production` when the provider supports them. Prefer sandbox for development and validation of a new write.
- Never silently fall back from sandbox to production.
- Encapsulate provider HTTP calls in a provider-specific client. Do not distribute direct HTTP calls across routes, ETL, and UI modules.
- Do not invent endpoints, authentication headers, signatures, scopes, or environments. Mark unverified details as `TBD`.

## Connector Cycle

For each resource, define and validate this cycle:

1. Build the request with configured authentication and explicit environment.
2. Execute the provider request through the connector client.
3. Validate transport-level success and response shape enough to continue safely.
4. Sanitize and persist the response or records to Raw/STG.
5. Record source, resource, external identifier, fetch time, available provider timestamps, and relevant sync metadata.
6. Continue pagination according to the provider's verified contract.
7. Advance an incremental checkpoint only after the corresponding processing succeeds.
8. Finalize the sync outcome with sanitized observability data.
9. Run ETL later and separately; do not turn the connector into a Core materializer.

## Pagination And Incremental Sync

For every resource, explicitly determine and document:

- pagination type: page/limit, offset, cursor, next URL, or none;
- requested and maximum page size;
- termination signal and maximum-page guard;
- order and whether it is stable enough for incremental reads;
- full-sync behavior;
- incremental mechanism, if verified: `updated_since`, `created_since`, cursor, date range, increasing ID, or a documented combination;
- provider timestamps, their semantics, and their availability.

Never assume a list API returns all records, has `updated_at`, accepts date filters, or orders consistently. Record confirmed and observed behavior in `docs/integrations/<provider>.md`; use `TBD`, `Known limitation`, or `Hypothesis` when appropriate.

When an incremental strategy exists, evaluate a checkpoint concept containing provider, resource, last successful sync, cursor, and last external timestamp. Advance it only after all data covered by it has persisted successfully. A partial or failed sync must not advance the checkpoint.

## Raw, STG, And Idempotency

- Preserve the existing `source_records` upsert identity `(source, resource_type, external_id)` where applicable. Do not replace it without an ADR.
- Use the provider's verified external identifier. If it is absent or ambiguous, document the limitation before deriving a fallback identity.
- Preserve sanitized source payloads when reasonable, plus provider, resource type, external ID, fetch time, provider-created time, provider-updated time, and version or hash when useful and verified.
- Raw payloads support debugging, reprocesamiento, auditability, and mapping reconstruction. Never retain authentication data, PAN, CVV/CVC, security codes, or other unnecessary sensitive information.
- Reprocessing the same provider record must not silently duplicate it. Confirm idempotency with repeated-sync tests appropriate to the provider.
- STG keeps provider vocabulary and context. Mapping to Core requires an approved ETL mapping and remains traceable to its source record.

## Error Handling, Retries, And Rate Limits

Classify failures before choosing behavior:

- Transient: timeout, temporary network failure, HTTP 429, 502, or 503 may be retry candidates when provider documentation and idempotency allow it.
- Permanent: authentication or authorization failures, invalid requests, missing endpoints, and invalid resources must fail clearly without unbounded retries.
- Individual data error: assess whether a malformed record can be isolated without discarding valid records in the same page. The policy depends on the resource and must be documented.

Retries must have a limit, use backoff when appropriate, honor `Retry-After` when supplied, and log only sanitized context. GET is normally safer to retry, but an endpoint's semantics must still be verified. POST, PUT, PATCH, and DELETE require explicit side-effect and idempotency analysis; never assume they are retry-safe.

Review official provider rate limits. Respect documented limits and use throttling or backoff as needed. Never invent rate-limit values or run aggressive loops.

## Observability And API Logs

Each sync execution should make it possible to determine:

- provider and resource;
- start and finish time;
- records fetched, persisted, skipped, and failed when measurable;
- retries and primary sanitized error;
- pagination progress and last successful checkpoint when applicable;
- final result.

Operational logs and the conceptual `LOG_API` may retain provider, logical endpoint, HTTP method, status, duration, record count, result, sanitized error, and timestamp. Never log API keys, authorization headers, tokens, signatures, full sensitive payloads, or unnecessary personal data.

`sync_runs` must record every synchronization outcome without secrets or payment-card data. Do not expose raw provider failures directly to browser clients.

## Provider Contract Documentation

Maintain `docs/integrations/<provider>.md` for every integration. For each resource, document:

| Item | Required record |
| --- | --- |
| Provider | Provider name and environment scope. |
| Resource | Verified provider resource name. |
| Direction | `read`, `write`, or `webhook`. |
| Authentication | Verified type; no credential values. |
| Endpoint | Only when verified. |
| Pagination | Confirmed behavior, observed behavior, or `TBD`. |
| Incremental strategy | Confirmed behavior, observed behavior, or `TBD`. |
| External identifier | Verified field or `TBD`. |
| Relevant timestamps | Verified fields and meaning. |
| Status values | Real provider values only. |
| Known limitations | Limits, gaps, or unsupported history. |
| Mapping | STG-to-Core mapping only when approved. |

Use these labels precisely:

- `Confirmed`: verified against official documentation or reliable provider evidence.
- `Observed`: seen experimentally but not confirmed as a contract.
- `TBD`: unknown and not inferred.
- `Known limitation`: verified provider or platform constraint.
- `Hypothesis`: plausible explanation that requires validation.

Do not promote an observation or hypothesis to confirmed behavior without evidence.

## Reads, Writes, And Webhooks

### Reads

Provider reads use GET or an equivalent read-only operation and feed Raw/STG. They remain read-only and reproducible.

### Writes

Provider writes use POST, PUT, PATCH, or DELETE and carry higher risk. Before implementing a new write, verify official documentation, permission, sandbox availability, input validation, provider idempotency, impact, reconciliation, rollback or compensation, and test coverage.

Follow `AGENTS.md`, implemented `WR-*` task boundaries, internal API permissions, CSRF controls, and the provider-specific `*_WRITES_ENABLED=true` flag. Never call provider write endpoints from the browser. The documented tension around some internal POST operations is unresolved; this skill does not resolve it. Escalate a new or conflicting write pattern for an ADR rather than bypassing the active rules.

### Webhooks

Webhooks and periodic syncs are complementary: webhooks provide timely events, while syncs reconcile missed or changed data. When supported, validate authenticity or signature, retain event ID, timestamp, and sanitized payload, process idempotently, and retain enough context for repeatable processing. A webhook never removes the need for reconciliation unless an accepted decision explicitly says so.

## Workflow

1. Classify the request as read, write, webhook, contract review, or operational diagnosis.
2. Read the sources of truth and provider documentation relevant to the affected resource.
3. Identify confirmed facts, observed behavior, limitations, hypotheses, and `TBD` items. Do not infer undocumented endpoints or fields.
4. Define the connector boundary, Raw/STG destination, external identifier, sanitation needs, pagination, incremental strategy, idempotency, retries, and observability.
5. For mapping or Core implications, invoke `data-modeling`; do not decide them inside the connector design.
6. For writes, verify all safety gates and existing `WR-*` authorization before implementation.
7. Document the provider contract and limitations in `docs/integrations/<provider>.md` when real knowledge changes.
8. Implement only when the task explicitly authorizes it. Keep connector, staging, ETL, and Core changes separate and traceable.
9. Validate with focused tests, repeated-sync checks, sanitized logs, and a diff review. Use `project-memory` when the result changes durable project state.

## New Provider Checklist

Before implementing a provider, answer:

1. Provider: what platform is involved?
2. Purpose: what must be read or changed?
3. Resources: which provider resources are in scope?
4. Authentication: how is it verified?
5. Environment: development, test, sandbox, or production?
6. Base URL and endpoints: which are verified?
7. Pagination: what is the contract and termination condition?
8. Rate limit: what is documented?
9. Incremental sync: what mechanism is verified?
10. External IDs and timestamps: which fields are verified?
11. Status values: which real values are documented?
12. STG: where is the provider data persisted?
13. Idempotency: how does repeated processing avoid duplicates?
14. Retries and partial errors: which failures are safe to retry or isolate?
15. Security and logs: which data must be sanitized or omitted?
16. Webhooks: do they exist and how are they authenticated and reconciled?
17. Known limitations: what cannot be relied upon?
18. Mapping: what approved transformation, if any, proceeds from STG to Core?
19. Tests: which authentication, pagination, retry, idempotency, failure, and sanitation cases are required?

## Relationship With Other Skills

- `prompt-optimizer` refines the request, scope, and acceptance criteria before integration work.
- `provider-integration` governs provider interaction, Raw/STG ingestion, contracts, and operational safety.
- `data-modeling` governs STG/Core structures, centralized identity, mappings, and migration implications.
- `project-memory` records durable state, limitations, ADRs, and task status after verified changes.

Do not duplicate their responsibilities.

## Constraints

- Preserve `Fuentes -> Connectors -> STG / Raw -> ETL / Normalizacion -> Core centralizado -> API -> CRM / Reportes / Analytics`.
- Do not write directly from a connector to Core.
- Do not expose or retain secrets, credentials, payment-card data, PAN, CVV/CVC, or security codes.
- Do not invent provider contracts, rate limits, timestamps, external IDs, mappings, or status taxonomies.
- Do not make provider writes, modify a provider integration, create migrations, or add endpoints unless explicitly authorized.
- Do not turn identity signals into a provider-side matching or merge rule; follow ADR-001 and `data-modeling`.
- Use `modelo centralizado`, `datos centralizados`, `Core centralizado`, and `identidad centralizada`; do not introduce new conceptual names using `canonical`.

## Checklist Before Finishing

- [ ] Provider direction and resources are explicit.
- [ ] Authentication, environment, endpoints, pagination, incremental strategy, external IDs, timestamps, and statuses are verified or marked correctly.
- [ ] Raw/STG persistence is sanitized, traceable, and idempotent through the documented source identity.
- [ ] Connector and ETL/Core responsibilities remain separate.
- [ ] Retry, rate-limit, partial-failure, checkpoint, and observability behavior are safe and documented.
- [ ] Writes and webhooks meet their specific security and idempotency requirements.
- [ ] Provider documentation uses evidence labels without promoting hypotheses.
- [ ] No secrets, payment-card data, or unrelated code changes were introduced.
