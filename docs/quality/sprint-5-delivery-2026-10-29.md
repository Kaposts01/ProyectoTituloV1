# Entrega sprint-5 — 2026-10-29

## Diagnostico

La rama `sprint-5/estabilizacion-dashboard` se publico apuntando a `4f06970`, igual que `origin/master`. El squash desde `codex/estabilizacion-synkmetrix` quedo sin commit con conflictos en `docs/tasks.md` y `tests/test_client_match_detector.py`. Por eso GitHub no mostraba el avance propio.

## Integracion

- Conservadas las tareas de ambos historiales y la fixture transaccional con savepoints; no se ocultan fallos PostgreSQL como skips.
- Conservada la migracion publicada `20261020_0032_core_charges_source_status.py`. El cambio de atributos de la rama local se entrega como nueva revision `20261029_0037`, posterior a `20261021_0036`; la prueba de migracion referencia esta nueva revision.
- La antigua revision local de atributos permanece en la rama de estabilizacion. Una base que haya aplicado esa otra 0032 necesita reconciliacion explicita antes de actualizar: no basta con ejecutar upgrade ni cambiar el stamp. No se modifico la base operativa.
- Import de prueba VirtualPOS ordenado con Ruff.
- La prueba Payku conserva la prioridad de logs y se actualiza al fallback `end` para cancelaciones sin logs, comportamiento ya incorporado y documentado en master (a3791c3). Se conserva la asercion de que una suscripcion activa no adquiere fecha de cancelacion.

## Bloqueo previo de migraciones

Una base nueva falla en `20261021_0035_etl_runs_channels_failed.py`: usa `op.Column` en lugar del constructor SQLAlchemy. Esa revision ya publicada se conserva por la regla de migraciones historicas inmutables. No se certifica `alembic upgrade head` desde cero ni CI completo.

Para validar esta integracion se creo una base descartable nueva: upgrade hasta 0034, aplicacion manual del DDL exacto de 0035 (`channels_failed VARCHAR[]`) solo alli y stamp 0035; luego upgrade normal 0036 -> 0037. Upgrade final y `alembic check` pasan. Este procedimiento de prueba no es una instruccion para la base operativa.

## Validacion

- Ruff: pasa.
- Frontend: lint sin errores (advertencias React existentes), 4 pruebas pasan y build pasa con advertencia de bundle superior a 500 kB.
- Suite Python: 374 pruebas pasan en PostgreSQL aislado; advertencia de deprecacion Starlette/httpx.
- Entrega: un commit consolidado en `sprint-5/estabilizacion-dashboard`; master permanece intacta. La sincronizacion remota se verifica tras el push con `git ls-remote`.
