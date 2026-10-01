---
name: prompt-optimizer
description: Optimize a user request into a precise, actionable implementation brief before execution. Use automatically for every project request; show the result only for /prompt or when the user asks to see it.
---

# Prompt Optimizer

## Purpose

Internally turn informal, incomplete, or ambiguous user requests into an actionable brief without changing the user's intent.

## Method

1. Identify the requested outcome and preserve it exactly.
2. Inspect the minimum relevant project context: instructions, documentation, configuration, entrypoints, and affected code.
3. Refine the request with only verified context:
   - affected files, architecture, and existing conventions;
   - technical constraints, security, error handling, and compatibility risks;
   - acceptance criteria and proportionate validation commands;
   - likely side effects and the smallest necessary change.
   - current external library or API behavior from Context7 when the request depends on it.
4. Do not invent product requirements, APIs, data rules, or scope. Mark a necessary unknown as an assumption only when it is safely inferable; otherwise ask one focused clarification.
5. Execute the refined request, validate the result, and report the outcome concisely.

## Visibility

Keep the optimized brief internal by default. When the user writes `/prompt` or asks to see the optimized prompt, show these sections before execution:

```text
PROMPT ORIGINAL
PROMPT OPTIMIZADO
SUPUESTOS
CRITERIOS DE ACEPTACIÓN
```

## Guardrails

- Never expose secrets or add them to versioned files.
- Prefer existing components and minimal changes.
- Respect repository instructions and current task tracking.
- Use Context7 for up-to-date external library and API documentation when applicable, then reconcile it with the repository.
- Do not optimize by changing the requested goal.
