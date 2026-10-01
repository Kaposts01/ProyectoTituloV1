# Development Instructions

## 1. Project

SynkmetriX is a CRM that centralizes donor, member, and subscription information from payment platforms. It supports visualization, controlled management, reporting, and later predictive analysis.

## 2. Source of truth

Use this order of priority:

1. `AGENTS.md` for operational rules.
2. `docs/memory/PROJECT_STATE.md` for current state.
3. `docs/memory/CURRENT_SPRINT.md` for active work.
4. `docs/architecture/` for current architecture.
5. `docs/data/centralized-model.md` for the conceptual centralized model.
6. `docs/integrations/` for provider contracts and behavior.
7. `docs/decisions/` for accepted architectural decisions.
8. Other historical documents in `docs/` as background only.

Do not treat prior plans, proposals, or obsolete diagrams as current architecture. On conflict, prioritize `PROJECT_STATE.md`, then current architecture, then accepted decisions. Report unresolved ambiguity; never silently invent a resolution.

## 3. Mandatory context

Before a significant task, read `docs/memory/PROJECT_STATE.md` and `docs/memory/CURRENT_SPRINT.md`. Read only additional context relevant to the task:

- Architecture: `docs/architecture/`.
- Data: `docs/data/centralized-model.md` and the affected entity note.
- Integration: `docs/integrations/<provider>.md`.
- Architectural decision: `docs/decisions/`.

Do not load unnecessary documentation.

## 4. Architecture rules

Keep this flow intact:

`Fuentes -> Connectors -> STG / Raw -> ETL / Normalizacion -> PostgreSQL Core centralizado -> API -> CRM / Reportes / Analytics`

- PostgreSQL is the central source of truth.
- Each provider keeps independent staging; providers never write directly to Core.
- Preserve Raw data when reasonable, keep transformations traceable, and retain external provider identifiers.
- Integrations must be reproducible. Preserve the `source_records` upsert key `(source, resource_type, external_id)` so repeated syncs remain idempotent.
- The Core model must not depend on a provider-specific structure.
- Applied migrations are immutable: add a new migration instead of destructively changing one. When adding a SQLAlchemy model, add it to Alembic metadata imports in `alembic/env.py` and create a migration under `alembic/versions/`.
- Do not assume RUT, email, or phone is unique. Centralized identity and deduplication remain `TBD` until an approved decision exists.

## 5. Terminology

Use `modelo centralizado`, `identidad centralizada`, and `datos centralizados` in conceptual language. Avoid `modelo canónico`, `identidad canónica`, and `datos canónicos`.

Inherited technical names containing `canonical` may remain temporarily for compatibility. Do not introduce new technical names using `canonical`.

## 6. Skills

Available project skills: `prompt-optimizer`, `project-memory`, `data-modeling`, and `provider-integration`.

- It is mandatory before every user request: interpret intent, inspect relevant context, define acceptance criteria, execute, validate, and respond.
- Keep its result internal unless the user sends `/prompt` or asks to see it.
- Load specialized skills only when their scope applies; do not duplicate a skill's full instructions here.
- Future skills such as `etl-engineering`, `testing-qa`, and `documentation` are not available until created.

## 7. Context7

Use Context7 for current documentation of technologies, libraries, frameworks, SDKs, APIs, setup, or configuration when needed, including PostgreSQL, React, Next, Pandas, Pydantic, Django, Django REST Framework, and Celery.

Resolve the library ID first and query only the relevant topic. Context7 is not the source of truth for SynkmetriX; reconcile it with repository code and documentation.

## 8. Workflow

Before code changes: understand the task, read relevant memory, identify affected files, review architecture constraints, consult Context7 when current technology behavior matters, and identify risks.

During changes: make minimal and traceable changes, avoid unrequested refactors, do not alter out-of-scope components, and preserve compatibility when required.

Local workflow: use `\.venv\Scripts\Activate.ps1`; start PostgreSQL with `docker compose up -d postgres` on `localhost:5433`; run `alembic upgrade head` before the API or sync scripts; run the API with `uvicorn app.main:app --reload`; run VirtualPOS sync with `python scripts\sync_virtualpos.py` from the repository root.

After changes: run relevant tests and static checks, review the diff, check for secrets, update documentation only when the real state changed, and register newly found technical debt when relevant.

## 9. Memory

- `PROJECT_STATE.md` represents real current state.
- `CURRENT_SPRINT.md` represents active work.
- `BLOCKERS.md` records conditions that prevent or constrain progress.
- `LESSONS_LEARNED.md` records reusable learning.

Do not store full conversations or lengthy reasoning. Update `docs/tasks.md` when a task starts, changes scope, is blocked, or completes. Update memory when actual state, active work, blockers, lessons, or technical debt change. A future `project-memory` skill may formalize these rules.

## 10. Completion criteria

Do not mark a task complete merely because code was written. Confirm, when applicable: implementation, relevant tests, static validation, known errors, documentation changes, security review, diff review, and no out-of-scope changes. Explicitly report anything that could not be validated.

Use `python -m pytest` and `ruff check app tests alembic scripts` for applicable Python changes; install reproducible Python dependencies with `python -m pip install -r requirements.lock`. `python -m pytest tests/test_virtualpos_auth.py` is a focused authentication check.

## 11. Safety

- Keep secrets, tokens, and API keys in `.env` or deployment secret management, never in Git, logs, documentation, or responses. Only `.env.example` may be committed.
- Sanitize logs and stored provider data: never retain or expose payment-card data, credentials, PAN, CVV/CVC, or security codes. Validate inputs and enforce permissions for mutable operations.
- Provider reads remain read-only. Provider writes are permitted only through implemented internal API `WR-*` tasks with the matching local `*_WRITES_ENABLED=true` flag. Never call provider write endpoints from the browser.
- Restrict writes to documented PUT/DELETE flows. Do not create payments, authorize payments, retry charges, create payment links, or perform wallet or payout operations unless a separately approved task explicitly adds them.
- `sync_runs` must record every synchronization outcome without secrets or payment-card data.
- `postman/` is an uncommitted nested Git repository. Do not remove its `.git` directory or use `git add .` expecting it to be included without explicit approval.
