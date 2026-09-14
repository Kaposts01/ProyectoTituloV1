# CRM Suscripciones

## Local workflow

- Use the local Python environment: `\.venv\Scripts\Activate.ps1`.
- Start the project database with `docker compose up -d postgres`; it is exposed at `localhost:5433`, not `5432`.
- Apply schema changes with `alembic upgrade head` before running the API or sync script.
- Run the API with `uvicorn app.main:app --reload`; Swagger is at `http://127.0.0.1:8000/docs`.
- Run a manual VirtualPOS sync from the repository root with `python scripts\sync_virtualpos.py`.
- Verify changes with `python -m pytest` and `ruff check app tests alembic scripts`. A focused test is `python -m pytest tests/test_virtualpos_auth.py`.

## Data and integrations

- Provider reads remain read-only. Provider writes are permitted only through the internal API for an implemented `WR-*` task and when its provider-specific `*_WRITES_ENABLED=true` setting is configured locally. Never call provider write endpoints directly from the browser.
- Keep write operations limited to the documented PUT/DELETE flows. Do not create payments, authorize payments, retry charges, create payment links, or perform wallet/payout operations unless a separately approved task explicitly adds them.
- `app/services/virtualpos_sync.py` writes raw provider responses to `source_records`; preserve its `(source, resource_type, external_id)` upsert behavior so repeated syncs stay idempotent.
- `sync_runs` records every sync outcome. Keep errors free of credentials and payment-card data.
- Add new SQLAlchemy models to Alembic metadata imports in `alembic/env.py`, then add an Alembic migration under `alembic/versions/`.

## Configuration and repository hygiene

- `.env` holds `DATABASE_URL` and VirtualPOS Sandbox credentials. It is intentionally ignored; only `.env.example` may be committed. Never log, document, or return those values.
- Update `docs/tasks.md` whenever a task starts, changes scope, is blocked, or completes.
- `postman/` is an uncommitted nested Git repository. Do not remove its `.git` directory or use `git add .` expecting it to be included without explicit approval.

## Prompt Optimization

- Before executing every user request, interpret its intent, inspect the relevant project context, and internally refine it with the `prompt-optimizer` skill.
- Apply this flow automatically: interpret intent, consult project context, optimize the request, define acceptance criteria, execute, validate, and respond.
- Preserve the user's objective. Add only context supported by the repository or explicitly stated by the user; do not invent material requirements or make unnecessary changes.
- Do not ask whether to optimize and do not require special commands. Proceed when the repository provides enough information; ask only when a critical decision cannot be inferred.
- Show `PROMPT ORIGINAL`, `PROMPT OPTIMIZADO`, `SUPUESTOS`, and `CRITERIOS DE ACEPTACIÓN` before execution only when the user writes `/prompt` or asks to see the optimized prompt.

## Context7

- Use Context7 automatically when a task needs current library or external API documentation, code generation, setup, or configuration guidance; do not require the user to request it explicitly.
- Resolve the library identifier first, then query only the documentation relevant to the task and version in use.
- Treat Context7 output as external reference material: reconcile it with this repository's code and constraints before making changes.
