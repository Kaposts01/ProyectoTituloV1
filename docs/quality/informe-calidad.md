# Informe de calidad (MET-01)

Estado de las pruebas, la cobertura, el lint y la deuda conocida del CRM. Se actualiza en cada corte (S7 y entrega
final). Fecha de esta versión: 2026-11-10 (rama `feat/s7-metricas`, sobre `master` 248d515).

## 1. Suites de prueba

| Suite | Herramienta | Dónde | Archivos | Pruebas (2026-11-10) | Bloquea CI |
|---|---|---|---|---|---|
| Backend | pytest 8 + PostgreSQL `crm_test` | `tests/` | 182 `test_*.py` | 2769 pasan, 2 omitidas (4 min 54 s en local) | Sí |
| Frontend | vitest 5 + jsdom + Testing Library | `frontend/src/**/*.test.ts(x)` | 104 | 1407 pasan | Sí |
| Contrato VirtualPOS | pytest, marca `contract` | `tests_contract/` | — | Fuera de la CI (sandbox real, manual) | No |

- La suite de backend corre siempre contra su propia base `*_test` (`tests/conftest.py`, `tests/db_guard.py`); nunca
  contra `crm` ni `crm_sandbox`.
- Las pruebas de rendimiento de Toku y VirtualPOS se omiten salvo `TOKU_PERF_TEST=1` / `VP_PERF_TEST=1`.

## 2. Cobertura

Se mide en la CI desde MET-01 (`.github/workflows/ci.yml`), **solo como reporte, sin umbral** (no bloquea):

- Backend: `pytest --cov=app --cov=scripts` (pytest-cov 7, coverage 7). Total en el resumen del job y artefacto
  `coverage-backend` (`coverage.xml`, `coverage.md` con el detalle por archivo).
- Frontend: `npm run test:coverage` (vitest, proveedor v8; mide `src/**/*.{ts,tsx}` sin pruebas ni `main.tsx`).
  Tabla de líneas/sentencias/funciones/ramas en el resumen del job y artefacto `coverage-frontend`
  (`coverage-summary.json`, `lcov.info`).

| Ámbito | Líneas | Ramas | Funciones | Fuente |
|---|---|---|---|---|
| Backend (`app` + `scripts`) | _pendiente: primer resultado de CI_ | _pendiente_ | — | artefacto `coverage-backend` |
| Frontend (`src`) | _pendiente: primer resultado de CI_ | _pendiente_ | _pendiente_ | artefacto `coverage-frontend` |

No se midió en local: el entorno virtual del repo no tiene `pytest-cov` y `node_modules` local no tiene
`@vitest/coverage-v8` (no se instalan fuera de la CI por regla de trabajo). Con el primer resultado de la CI se fija una
línea base y se decide si se agrega un umbral (`--cov-fail-under` / `coverage.thresholds`) que no baje de ella.

## 3. Lint y tipos

| Herramienta | Comando | Resultado (2026-11-10) |
|---|---|---|
| ruff (backend) | `python -m ruff check app tests alembic scripts` | Limpio |
| oxlint (frontend) | `npm run lint` | 0 errores, 31 advertencias (sobre todo `react(set-state-in-effect)` y `react(refs)`, preexistentes) |
| TypeScript | `npm run build` (`tsc -b` + Vite) | Compila |

## 4. Guardianes

Pruebas que protegen reglas transversales (fallan si alguien rompe la regla, no una función):

- Frontend: `i18n/catalog.guard.test.tsx` (catálogo de textos), `i18n/identifiers.guard.test.ts` (sin
  identificadores técnicos en la interfaz), `i18n/spelling.guard.test.ts` (ortografía),
  `i18n/apiErrors.guard.test.ts` (códigos de error del backend traducidos; ver `docs/engineering/api-errors-ui.md`).
- Backend: `test_db_guard.py` (la suite nunca toca `crm`/`crm_sandbox`), `test_migration_guard.py`,
  `test_tch_schema_unchanged.py`, `test_api_contract_keys.py` y `test_api_contract_openapi.py` (contrato de la API con
  el frontend), `test_toku_write_guard*.py` (escrituras a Toku detrás de su bandera), `test_recovery_pii.py`
  (sin datos personales en recuperación), `test_operation_metrics.py` (métricas sin datos personales y solo lectura).
- Diagnósticos de solo lectura con guarda de base (`scripts/diagnostics/readonly_guard.py`): `parity_check.py`,
  `coverage_report.py`, `vp_parity_check.py`, `operation_metrics.py`.

## 5. Paridad por canal

`scripts/diagnostics/parity_check.py` (conteos por canal, mes y estado; `--vs-report` contra reportes importados) y
`coverage_report.py` (completitud histórica por mes). Los resultados de paridad del corte se agregan aquí cuando el
usuario autorice correrlos con `--read-only` sobre la base que corresponda.

## 6. Defectos, incidentes y deuda

- Incidentes y su corrección: `handoff.md` §14 (incidentes y tabla de errores y correcciones).
- Deuda técnica: `knowledge/08 - Roadmap/Technical Debt.md` y `docs/tasks.md` (deuda «Media» al 2026-11-07: tests que
  dependen del orden de ejecución en `test_sync_core_etl`, unos 100 literales de valores de TCH sin constantes, dominio
  `apiDetail` obsoleto en `frontend/src/i18n/es.ts`). La falta de cobertura medida en CI queda resuelta con MET-01.
- Métricas de operación y su limitación declarada: [metricas-operacion.md](metricas-operacion.md) (MET-02).

## 7. Cómo regenerar este informe

1. Backend: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q` → total de pruebas (pasan / omitidas).
2. Frontend (en `frontend/`): `npm test` → pruebas y archivos; `npm run lint` → advertencias; `npm run build`.
3. Lint backend: `python -m ruff check app tests alembic scripts`.
4. Cobertura: abrir la última corrida de la CI en `master` (pestaña *Summary*) o descargar los artefactos
   `coverage-backend` y `coverage-frontend`. En local, solo si el entorno ya tiene las dependencias de
   `requirements.lock` y `package-lock.json`: `python -m pytest --cov=app --cov=scripts --cov-report=term` y
   `npm run test:coverage`.
5. Duración de la CI: tiempo de los jobs `backend` y `frontend` en la misma corrida.
6. Operación: `scripts/diagnostics/operation_metrics.py --database <base> [--read-only] --format markdown`.
