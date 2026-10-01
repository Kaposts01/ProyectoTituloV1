# SynkmetriX

## 1. Purpose

SynkmetriX is a CRM for centralizing and managing member/donor information, subscriptions, charges, payments, and related data from multiple channels.

Current channels are VirtualPOS, Toku, Payku, and TCH through Excel reports. The implemented system supports data consultation, controlled operations, reporting, and traceable synchronization.

## 2. Source of Truth

Follow [AGENTS.md](AGENTS.md) for operational rules.

### Architecture and current state

- [PROJECT_STATE.md](docs/memory/PROJECT_STATE.md) records the current operational context.
- [Current sprint](docs/memory/CURRENT_SPRINT.md) records active work.
- [Architecture](docs/architecture/) describes the current documented architecture.

### Formal decisions

- [ADRs](docs/decisions/) record formal architectural decisions.
- Accepted ADRs prevail over historical documentation.

### Knowledge Base

- [knowledge/](knowledge/) provides navigation, synthesis, and relationships.
- It does not replace `docs/` as technical source of truth.

### Contradictions

When documentation conflicts, follow the source-of-truth order defined in [AGENTS.md](AGENTS.md). Do not define a different priority in this file.

Do not assume either code or documentation is correct automatically. Identify the contradiction, inspect current code, review ADRs and project state, and report it before making an architectural change.

## 3. Current Architecture

```text
External providers
  -> ingestion/connectors
  -> source_records/raw staging
  -> provider-specific tables
  -> consolidation
  -> centralized CRM entities
  -> FastAPI
  -> React/Vite
```

TCH follows an additional Excel-to-ETL-to-provider-table route. `channel_consolidation.py` and `crm_materialization.py` coexist during a transition; do not treat them as equivalent without reviewing context.

- [Architecture overview](docs/architecture/overview.md)
- [Data flow](docs/architecture/data-flow.md)
- [Database architecture](docs/architecture/database.md)

## 4. Core Data Principles

- PostgreSQL is the primary persistence source of truth.
- Preserve provider external IDs and the source data needed for traceability.
- Do not assume RUT, email, or phone is a universal cross-provider identity.
- Synchronizations must remain idempotent through `(source, resource_type, external_id)` where applicable.
- Keep provider data separate from the provider-independent centralized model.
- Schema changes require review of SQLAlchemy models and Alembic migrations.
- Do not make destructive data changes without explicit instructions.
- Do not expose unnecessary PII in logs or documentation.

Read [ADR-001](docs/decisions/ADR-001-identidad-centralizada-socios.md) before work involving identity, matching, deduplication, or merge behavior.

## 5. Provider Integration Rules

For VirtualPOS, Toku, Payku, or a future provider, inspect the existing connector and provider documentation first. Review authentication, pagination, retries, rate limits, idempotency, sanitization, staging, mappings, logging, tests, writes, and webhooks.

Do not assume two providers share a contract. Keep provider interaction in connectors and preserve the boundary between Raw/STG and centralized data.

- [Integration architecture](docs/architecture/integrations.md)
- [Provider documentation](docs/integrations/)

## 6. Writes to External Providers

- Provider writes are sensitive operations.
- Respect the existing `*_WRITES_ENABLED` flags and internal authorization controls.
- Do not perform destructive provider operations without explicit instruction.
- Preserve traceability through `write_runs` or the active equivalent.
- Never print credentials, tokens, secrets, or payment-card data.

## 7. Database Changes

For a structural change, consider:

1. SQLAlchemy model.
2. Alembic migration.
3. Existing data and backfill needs.
4. Rollback or recovery.
5. Tests.
6. Relevant documentation.

Do not edit historical migrations unless explicitly instructed and justified.

## 8. Security

- Never show API keys, secrets, passwords, or tokens.
- Do not version `.env`.
- Preserve JWT, HttpOnly cookies, CSRF, and RBAC controls.
- Sanitize external payloads before persistence or logging.
- Never store PAN, CVV/CVC, security codes, or unnecessary sensitive payment data.
- Do not weaken a security control to solve a functional problem.

## 9. Testing

Before considering work complete:

- Identify affected tests and run relevant validation when possible.
- Do not claim tests passed unless executed.
- Add tests when a change affects critical behavior.
- Prioritize integration, sync, ETL, auth, writes, and idempotency paths.
- Do not run tests that perform real external writes without explicit authorization.

## 10. Documentation Rules

When a change affects architecture, data model, integration, operations, security, or a significant technical decision, evaluate updates to:

- `docs/memory/PROJECT_STATE.md`
- `docs/architecture/`
- `docs/integrations/`
- `docs/data/`
- `docs/decisions/`
- `knowledge/`

Update only the relevant sources. Evaluate an ADR for a significant architectural decision.

## 11. AI Tooling

### Global instructions

- [AGENTS.md](AGENTS.md)

### OpenCode

- [Skills](.opencode/skills/)
- [Configuration](.opencode/opencode.json)
- Current Skills: `prompt-optimizer`, `project-memory`, `data-modeling`, and `provider-integration`.

### Claude

- Claude-specific settings are local and are not a project source of truth.
- No project agents are versioned for Claude.

### MCP

- Context7 is configured as a complementary documentation tool, not as a substitute for SynkmetriX architecture.

## 12. Skill Usage

### prompt-optimizer

Use for every user request.

### project-memory

Use for project state, contradictions, ADR work, and durable project continuity.

### data-modeling

Use for models, identity, SQLAlchemy, Alembic, consolidation, and relationships.

### provider-integration

Use for APIs, connectors, synchronization, staging, webhooks, and writes.

Do not copy the full content of Skill files into implementation work; consult the relevant Skill.

## 13. Historical Documentation

Some files describe prior architecture, Apps Script, local databases, closed plans, or superseded decisions. Do not treat a document as current merely because it exists. Contrast it with project state, ADRs, current code, and current architecture documentation.

## 14. Working Method

For important tasks: Understand, Inspect, Plan, Implement, Validate, Document.

Before modifying, identify relevant files, review existing decisions, and detect regression risk. After modifying, review the diff, validate the result, and report changes and remaining gaps. Avoid unrequested refactors.

## 15. Known Architectural Risks

- Centralized identity is partially implemented.
- TCH RUT uniqueness is in tension with ADR-001.
- Consolidation traceability is incomplete in some paths.
- Legacy materialization and new consolidation coexist.
- VirtualPOS and Payku historical data have known limitations.
- The cross-provider taxonomy is still partial.

See [Technical Debt](knowledge/08%20-%20Roadmap/Technical%20Debt.md) for detail.

## 16. Key References

- [AGENTS.md](AGENTS.md)
- [Project state](docs/memory/PROJECT_STATE.md)
- [Architecture](docs/architecture/)
- [ADRs](docs/decisions/)
- [Knowledge Home](knowledge/00%20-%20Home/SynkmetriX.md)
- [AI Architecture](knowledge/06%20-%20AI/AI%20Architecture.md)
- [Technical Debt](knowledge/08%20-%20Roadmap/Technical%20Debt.md)
