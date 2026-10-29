# Sprint Actual

## Dashboard general — DASH-02 (2026-10-20)

**Status: Completed**

Diseno basado en referencias del usuario, sin copiar cifras ni categorias sin fuente. KPI mensuales, cuatro graficos, meta de analisis opcional, rangos y tablas. 304 pruebas Python y 4 TypeScript pasan; validacion visual autenticada y conciliacion TCH. Sin cambios de esquema ni datos. [Definiciones y limites](../quality/dashboard-kpis-2026-10-20.md).

## Integridad de datos — DATA-01 (2026-10-20)

**Status: Completed**

Atributos compartidos preservados sin duplicar cada asociacion; migracion 0032 verificada y aplicada a crm local con respaldo. VirtualPOS evita elecciones arbitrarias por RUT y respeta IDs externos. 296 pruebas pasan; sin backfill ni cambios de vinculos existentes. Siguientes tareas: contrato de pagos Toku y cache por sesion. [Evidencia y limites](../quality/data-integrity-2026-10-20.md).

## Estabilizacion local — REL-01 (2026-10-20)

**Status: Completed** (primera entrega de confiabilidad)

Rama `codex/estabilizacion-synkmetrix`, sin push. Scripts Toku/VirtualPOS usan consolidacion vigente; rutas Core estaticas preceden a la dinamica. Fallos de canal o consolidacion producen estado failed con evidencia parcial preservada; el stream distingue errores intermedios del resultado final. Verificado con 283 pruebas en base aislada, Ruff y build frontend. No se han probado interacciones visuales ni proveedores reales. Siguientes tareas: integridad de atributos/identidades, contrato de pagos Toku y cache por sesion. El historial documental anterior se conserva como antecedente.

## Skills Codex por stack (2026-10-20)

**Status: Completed** (creacion, validacion estructural y evaluacion offline)

Se crearon nueve skills de repositorio en `.agents/skills/` para el stack vigente. `AGENTS.md` registra sus nombres y limites. Se ejecutaron 37 pruebas estructurales, 27 revisiones tecnicas offline y 12 casos de seleccion por metadatos, con resultados favorables dentro de ese alcance. No se certifica ejecucion de implementaciones ni activacion nativa en una sesion limpia; el informe registra los limites y un fallo global Ruff ajeno a los cambios. No cambia la arquitectura de aplicacion ni autoriza refactorizaciones, despliegues o operaciones de proveedor adicionales.

## Objetivo actual

**Status: Completed**

Establecer una arquitectura documental y un modelo conceptual suficientemente solidos antes de comenzar la implementacion tecnica.

## Alcance documental

- Vision, requisitos, arquitectura conceptual y modelo Core consolidados.
- La estrategia conceptual de identidad centralizada quedo definida en ADR-001; su implementacion tecnica permanece fuera de alcance.
- Liquidaciones y taxonomias transversales conservadas como `TBD`.
- Riesgos, bloqueos, decisiones aceptadas y deuda tecnica registrados.
- Documentos historicos contrastados con el estado observado sin cambiar componentes tecnicos.

## Fuera de alcance

- Implementar modelos, migraciones, endpoints, conectores o agentes; la creacion y validacion documental de las skills locales `data-modeling` y `provider-integration` esta autorizada para este sprint.
- Modificar backend, frontend, base de datos, Docker o integraciones.

## Siguiente fase: Core ETL

**Status: Completed** (rama `feature/core-centralizado`, pendiente de merge a `master`)

Se implementó el Core ETL completo para los cuatro canales:

- **Migraciones 0027 y 0028**: columna `status` en `core_subscriptions` y tabla `core_client_attributes` con constraint UNIQUE `(source, attribute_type, attribute_value)`.
- **ETL services** (`app/services/core_*_etl.py`): TCH, Toku, Payku y VirtualPOS — idempotentes, batch 500, conteo real via SELECT COUNT.
- **Endpoints REST**: `POST /etl/core/{provider}` y `POST /etl/core/all` (background tasks, traceable via `EtlRun`).
- **Tests**: 66 tests unitarios en `tests/test_core_etl_helpers.py` para helpers puros y estructura de modelos.
- **CI**: `ruff check` limpio; 3 fallos pre-existentes en pytest no relacionados con Core ETL.
- **Documentación**: `docs/integrations/toku.md` documenta el patrón de suscripciones eliminadas en origen (stub strategy, Option A vs B).

Decisión técnica destacada: Toku tiene 112 suscripciones eliminadas en el origen que dejan 564 facturas huérfanas. Se usa el patrón "stub" (`status='deleted_at_source'`) en lugar de flotar pagos con `charge_id=NULL`.

Las tareas operativas y del Core quedan registradas en [tasks.md](../tasks.md).

## Trabajo planificado de calidad operativa

**Status: Planned**

La auditoria `AUD-01` incorporo las tareas `SYNC-01`, `DB-02`, `DASH-01`, `FE-01` y `OPS-09` en [tasks.md](../tasks.md). `DB-02` confirmo la instancia efectiva y `DB-03` reconcilio la metadata Alembic y las estadisticas antes de migraciones. `DASH-01` está completada: la paridad se limita a datos fechados y estados verificables; Payku conserva su cobertura histórica no certificada. `FE-01` está en curso: las alertas, rutas de proveedor, ficha TCH por `numero_ficha` y estado de listado seguro en URL son reutilizables; `App.tsx` todavía concentra carga y exploradores. La evaluacion de WebSocket debe partir del SSE existente para progreso de sincronizaciones y no modifica el flujo de ingestion de proveedores sin una decision posterior.

## Mantenimiento estructural

**Status: Completed**

`STR-01` separo los artefactos locales de la raiz, los scripts operativos de mantenimiento/diagnostico y la documentacion vigente de los antecedentes historicos, sin alterar la arquitectura de aplicacion ni los comandos operativos documentados.

## Entrega sprint-5 (2026-10-29)

Integracion sobre master 4f06970 en rama independiente `sprint-5/estabilizacion-dashboard`, conservando la estabilizacion original. Conflictos resueltos; atributos pasan a revision nueva 20261029_0037 por colision de las dos 0032. 374 pruebas Python, 4 frontend, Ruff, build y metadata pasan en base aislada. Instalacion desde cero/CI backend bloqueados por error historico `op.Column` en 0035. Base operativa no modificada; su antigua revision local requiere reconciliacion antes de migrar. [Evidencia](../quality/sprint-5-delivery-2026-10-29.md).
