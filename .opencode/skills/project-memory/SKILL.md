---
name: project-memory
description: Manage SynkmetriX persistent project memory in Markdown when a significant task changes project state, active work, blockers, reusable lessons, or architectural decisions. Use for memory updates, ADR evaluation, documentation contradictions, and compact project-state reviews.
---

# Project Memory

## Purpose

Maintain compact, durable, and trustworthy project memory for SynkmetriX. This skill records what a change means for the project; it does not reproduce Git diffs, conversations, prompts, or routine work.

`AGENTS.md` defines general project rules and takes priority over this skill. This skill defines how to manage persistent memory.

## When to use this skill

Use this skill when a task may change:

- real project state or architecture;
- active or prioritized work;
- a blocker, dependency, or integration limitation;
- a reusable technical lesson;
- a durable architectural decision or a relevant documentation contradiction.

Do not use it for trivial edits, routine commands, temporary files, or changes that have no durable project meaning.

## Memory sources

- `docs/memory/PROJECT_STATE.md`: current real state.
- `docs/memory/CURRENT_SPRINT.md`: active or prioritized work.
- `docs/memory/BLOCKERS.md`: conditions that block or constrain progress.
- `docs/memory/LESSONS_LEARNED.md`: reusable lessons.
- `docs/decisions/`: important architectural decisions and ADRs.
- `docs/tasks.md`: operational task record when applicable.

## Before a significant task

Apply progressive disclosure:

1. Read `PROJECT_STATE.md` and `CURRENT_SPRINT.md`.
2. Read `BLOCKERS.md` when known issues could affect the task.
3. Read relevant ADRs only when they apply.
4. Follow `AGENTS.md` to load architecture, data, or provider context only as needed.

Do not load all documentation indiscriminately.

## After a task

Update memory only when the real project state changed.

| File | Update when |
| --- | --- |
| `PROJECT_STATE.md` | A relevant capability, phase, accepted decision, architecture, dependency, integration state, or significant blocker changed. |
| `CURRENT_SPRINT.md` | Work starts, finishes, changes state or priority, or new work is necessary for the current objective. |
| `BLOCKERS.md` | A real blocker appears, resolves, changes impact, or an external dependency constrains progress. |
| `LESSONS_LEARNED.md` | A verified lesson can prevent repeated errors or be reused in later work. |
| `docs/tasks.md` | A task starts, changes scope, is blocked, or completes. |

Keep entries concise and current. Consolidate oversized state notes, move durable decision history to ADRs, and retain important history only when another project source preserves the detail.

## ADRs

Create an ADR only for a durable, significant decision, such as selecting PostgreSQL for Core, approving centralized identity or deduplication, changing staging architecture, selecting asynchronous tasks, defining webhooks, or establishing a cross-provider settlement pattern.

Do not create an ADR for typos, variable renames, trivial test repairs, or documentation-only changes that do not alter architecture.

An ADR must include:

- title;
- date;
- status: `Proposed`, `Accepted`, `Superseded`, or `Deprecated`;
- context;
- decision;
- reasons;
- consequences;
- alternatives considered, when relevant.

Link new ADRs from `docs/decisions/README.md`.

## Facts, proposals, and hypotheses

Use explicit status labels:

- `Accepted` or `Confirmed`: verified fact or accepted decision.
- `Proposed`: not yet accepted proposal.
- `TBD`: pending decision.
- `Known issue`: confirmed problem.
- `Hypothesis`: possible explanation requiring validation.

Never record a hypothesis as a fact. For example: `Hypothesis: possible pagination limit of 100 records; pending validation.`

## Contradictions

When documentation conflicts:

1. Apply the priority order in `AGENTS.md`.
2. Do not resolve it silently.
3. Record the inconsistency only if it is relevant and verified.
4. Create or request a decision only when the issue is durable and architectural.
5. Do not update memory with unresolved contradictory information as fact.

The known tension between some historical internal POST operations and historical write restrictions remains unresolved unless a higher-priority source or accepted decision changes it.

## What to retain

Retain accepted decisions, important `TBD` decisions, current architecture, component state, blockers, relevant technical debt, known limitations, repeatable problems, reusable solutions, meaningful next steps, and significant integration changes.

Do not retain complete conversations, prompts, chain of thought, model responses, extensive logs, routine commands, trivial corrections, temporary files, easily reconstructed Git details, or unverified thoughts presented as facts.

Git records what changed in code. Project memory records what that change means.

## Terminology and security

Use `modelo centralizado`, `identidad centralizada`, and `datos centralizados`. Do not introduce conceptual language using `canonical`; inherited technical names may remain only for compatibility as defined by `AGENTS.md`.

Never record API keys, passwords, access or refresh tokens, secrets, full card numbers, CVV, or unnecessary confidential data. When needed, record only an environment variable name, such as `VIRTUALPOS_API_KEY`, never its value.

## Examples

### Example 1: Update memory

Task result: STG_Toku was implemented and its tests passed.

- Add to `PROJECT_STATE.md`: `Toku: staging inicial implementado y validado.`
- Mark the corresponding task as completed in `CURRENT_SPRINT.md` when it is listed there.
- Update `docs/tasks.md` when it is the operational record.

### Example 2: Do not update memory

Task result: a typo in a code comment was corrected.

- Do not modify memory.

### Example 3: Create an ADR

Task result: after evaluating alternatives, the team accepts that CLIENTE has an internal UUID and external provider identities.

- Create an ADR with status `Accepted`.
- Link it from `docs/decisions/README.md`.
- Update `PROJECT_STATE.md` with the accepted decision.

### Example 4: Hypothesis

Task result: an API may limit responses to 100 records.

- Do not record it as a fact.
- If relevant, record: `Hypothesis: possible pagination limit of 100 records; pending validation.`

## Checklist before finishing

- [ ] Read only memory and documentation relevant to the task.
- [ ] Updated memory only for verified, durable state changes.
- [ ] Used correct status labels and did not promote hypotheses to facts.
- [ ] Considered an ADR only for a durable architectural decision.
- [ ] Kept entries concise and did not duplicate Git history or `docs/tasks.md`.
- [ ] Preserved centralized terminology and omitted secrets and payment-card data.
- [ ] Checked contradictions against `AGENTS.md` before recording conclusions.
