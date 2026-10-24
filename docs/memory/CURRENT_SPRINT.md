# Sprint Actual

## Marco de trabajo

Metodología: **Scrum adaptado** — sprints de 2 semanas, sesiones de Claude Code delimitadas por sprint.

**Flujo por sesión:**
1. Al iniciar, indicar el sprint activo: *"Trabajamos en Sprint N"*
2. Tomar las tareas del backlog de ese sprint en `docs/tasks.md`
3. Al cerrar, actualizar estado de tareas y registrar notas de avance
4. Al completar todas las tareas, cerrar el sprint y activar el siguiente

**Fuente de verdad del backlog:** `docs/tasks.md` → Hito 6, sección del sprint correspondiente.
**Artefacto visual:** https://claude.ai/artifact/RjnJYnghhrxA8AJb33kZjr

---

## Sprint Activo: Sprint 1 — Auditoría de Datos

**Estado:** Activo  
**Objetivo:** Documentar el modelo de datos real por canal (VirtualPOS, Toku, Payku, TCH) para que el equipo entienda qué se almacena, cómo se consolida y dónde hay brechas.  
**Duración:** 2 semanas (2026-10-24 → 2026-11-07)  

### Backlog del Sprint

| ID | Tarea | Estado | Responsable |
| --- | --- | --- | --- |
| DATA-01 | Documentar modelo de datos VirtualPOS (staging + tablas canónicas) | Pendiente | — |
| DATA-02 | Documentar modelo de datos Toku | Pendiente | — |
| DATA-03 | Documentar modelo de datos Payku | Pendiente | — |
| DATA-04 | Documentar modelo de datos TCH (ETL + tablas tch_*) | Pendiente | — |
| TK-10 | Investigar campo flow_name en Toku (BLQ-TK-01) | Pendiente | — |
| SYNC-01 | Auditar idempotencia y trazabilidad en consolidación | Pendiente | — |

### Definición de Done (Sprint 1)

- [ ] `DATA-01–04`: Cada canal tiene doc en `docs/data/` con tablas, campos clave, relaciones y brechas conocidas
- [ ] `TK-10`: Estado de BLQ-TK-01 documentado (resuelto o bloqueado esperando Toku)
- [ ] `SYNC-01`: Informe de idempotencia — rutas auditadas, gaps registrados en Technical Debt

### Notas de sesión

*(Registrar aquí avances, decisiones o bloqueos durante el sprint)*

---

## Sprint Cerrado: Sprint 0 — Onboarding & Fundación

**Estado:** Completado  
**Cerrado:** 2026-10-24  
**Objetivo:** Dejar el entorno operativo y App.tsx modularizado para que el nuevo desarrollador pueda trabajar en módulos aislados sin conflictos de merge.  

### Backlog del Sprint

| ID | Tarea | Estado |
| --- | --- | --- |
| OPS-07 | Levantar servicios y verificar BD consolidada | Completada |
| FE-02 | Completar modularización App.tsx en feature folders | Completada |

### Definición de Done (Sprint 0)

- [x] `OPS-07`: PostgreSQL saludable en `localhost:5433`; migraciones en `head` (0036); API `/health` OK; frontend build correcto
- [x] `FE-02`: App.tsx = 1 línea (re-export); 22 módulos extraídos a `features/{admin,auth,dashboard,shared,toku,virtualpos}/`; `npm run build` OK; 299/299 tests OK

### Notas de sesión

- Sesión 2026-10-24: OPS-07 completado incluyendo fix de migración 0035 (`op.Column` → `sa.Column`). FE-02 completado en dos fases: extracción de 22 módulos + AppCore.tsx para llevar App.tsx a 1 línea. `/review` limpio (no issues). Rama `sprint-0/onboarding` lista para merge.

---

## Hoja de Ruta de Sprints

| # | Sprint | Objetivo central | Tareas | Duración |
|---|--------|-----------------|--------|----------|
| 0 | **Onboarding & Fundación** ← *activo* | Entorno operativo + App.tsx modularizado | OPS-07, FE-02 | 2 sem |
| 1 | Auditoría de Datos | Documentar datos objeto por canal | DATA-01–04, TK-10, SYNC-01 | 2 sem |
| 2 | Componentes + KPIs | Componentes compartidos + KPIs estándar | FE-03, KPI-01–04 | 2 sem |
| 3 | Gráficos + Sidebar | Gráficos estandarizados + sidebar con salud | CHART-01–04, UI-20–21 | 2 sem |
| 4 | Recuperador VP | Mejoras al recuperador VirtualPOS | REC-03, WR-VP-05, PK-05 | 2 sem |
| 5 | Recuperador General | Recuperador multi-canal (Toku/Payku/TCH) | REC-04–06 | 3 sem |
| 6 | Infraestructura | Ambientes, respaldo y operaciones | ENV-01, BCK-01, OPS-09, VAL-VP-01, VAL-PK-01 | 2 sem |

**Desbloqueado externo:** BLQ-TK-01 (Toku flow_name) — no tiene sprint asignado; avanza cuando soporte Toku responda.

---

## Cómo cerrar un sprint

Al completar todas las tareas del sprint activo:

1. Marcar todas las tareas como `Completada` en `docs/tasks.md`
2. Actualizar `docs/memory/PROJECT_STATE.md` con los cambios del sprint
3. Copiar este archivo y activar el siguiente sprint (editar **Sprint Activo**)
4. Registrar la fecha de cierre y lecciones aprendidas en **Notas de sesión**
