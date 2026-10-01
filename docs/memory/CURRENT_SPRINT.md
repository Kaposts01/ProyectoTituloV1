# Sprint Actual

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

## Siguiente fase

**Status: In progress**

El siguiente trabajo es planificar tecnicamente el Core centralizado desde el modelo conceptual aprobado. Antes de implementar modelos, migraciones o endpoints se debe definir el alcance tecnico, las entidades afectadas y la estrategia de migracion con la skill `data-modeling`.

Las tareas operativas existentes se conservan en [tasks.md](../tasks.md); esta nota no autoriza todavia trabajo de implementacion.

## Trabajo planificado de calidad operativa

**Status: Planned**

La auditoria `AUD-01` incorporo las tareas `SYNC-01`, `DB-02`, `DASH-01`, `FE-01` y `OPS-09` en [tasks.md](../tasks.md). `DB-02` confirmo la instancia efectiva y `DB-03` reconcilio la metadata Alembic y las estadisticas antes de migraciones. `DASH-01` está completada: la paridad se limita a datos fechados y estados verificables; Payku conserva su cobertura histórica no certificada. `FE-01` está en curso: las alertas son reutilizables, pero `App.tsx` todavía concentra navegación, carga y exploradores. La evaluacion de WebSocket debe partir del SSE existente para progreso de sincronizaciones y no modifica el flujo de ingestion de proveedores sin una decision posterior.
