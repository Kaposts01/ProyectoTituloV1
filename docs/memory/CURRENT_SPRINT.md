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

## Sprint Activo: Sprint 2 — Componentes + KPIs

**Estado:** En progreso  
**Objetivo:** Componentes compartidos (KpiCard, ChannelChart) y KPIs estándar por canal (VirtualPOS, Toku, Payku, TCH).  
**Duración:** 2 semanas (inicio 2026-10-25)

### Backlog del Sprint

| ID | Tarea | Estado | Responsable |
| --- | --- | --- | --- |
| FE-03 | Crear KpiCard.tsx y ChannelChart.tsx compartidos | Completada | — |
| KPI-01 | Estandarizar KPIs VirtualPOS/resumen | Parcial: falta verificación contra VP staging | — |
| KPI-02 | Estandarizar KPIs Toku/resumen | Completada | — |
| KPI-03 | Estandarizar KPIs Payku/resumen | Completada | — |
| KPI-04 | Estandarizar KPIs TCH/resumen | Completada | — |

### Definición de Done (Sprint 2)

- [x] `FE-03`: Componentes en `frontend/src/components/` (KpiCard, ChannelChart, ChannelKpiStrip) con data contracts explícitos; tipos y notas en `features/shared/kpis.ts`; vitest configurado; usados por al menos un canal
- [ ] `KPI-01–04`: KPIs estándar por canal con notas de fuente visibles (ver notas de sesión)

### Notas de sesión

- Sesión 2026-10-25 (en curso):
  - Componentes KpiCard, ChannelChart y ChannelKpiStrip en `frontend/src/components`; tipos y notas en `features/shared/kpis.ts`; vitest configurado.
  - Backend agrega `kpis.rejected_charges` en los 4 canales.
  - Payku: MRR calculado desde la última transacción `success` (sin cambio de cifras: 5.339.000). Nota visible: "Cobertura histórica no certificada · MRR desde última transacción success".
  - TCH: conserva "mandatos vigentes" y agrega `kpis.recaudo_mensual` ("recaudo aceptado del mes"). Nota visible: "Fuente: reportes Excel oficiales".
  - Toku: el churn filtra suscripciones chargeable.
- Sesión 2026-10-26:
  - TK-10 completada: filtro y orden global por estado secundario antes de paginar; 6 tests con offset>0 en `tests/test_staging_api.py` (Toku y VirtualPOS); no depende de flow_name.
  - SYNC-GAP-02 caracterizado: 9 tests en `tests/test_etl_tch.py` y script de auditoría de solo lectura `scripts/maintenance/audit_tch_duplicate_cuotas.sql`. Sigue abierto como decisión de negocio (¿rechazo y pago posterior de la misma cuota son dos cargos?).
  - SYNC-GAP-04 mitigado: 49 tests en `tests/test_sync_gap04_payload_shapes.py`; log agregado `_log_null_relations` (solo conteos, sin PII).
  - KPI-01..04: KPI-01 rótulo "Cargos rechazados"; nota Toku y nota Payku visibles; KPI-04 mezcla fuentes: recaudo mensual y transacciones desde `tch_recaudacion_mensual`, MRR/ARPU/churn/LTV desde `TchSuscripcion` (valores distintos, rotulados). KPI-01 queda pendiente de verificación contra VirtualPOS staging.
  - FE-03 completada (KpiCard, ChannelChart, ChannelKpiStrip).

---

## Sprint Cerrado: Sprint 1 — Auditoría de Datos

**Estado:** Completado  
**Cerrado:** 2026-10-25  
**Objetivo:** Documentar el modelo de datos real por canal (VirtualPOS, Toku, Payku, TCH) para que el equipo entienda qué se almacena, cómo se consolida y dónde hay brechas.  
**Duración:** 2 semanas (2026-10-24 → 2026-11-07; cerrado anticipadamente)

### Backlog del Sprint

| ID | Tarea | Estado | Responsable |
| --- | --- | --- | --- |
| DATA-01 | Documentar modelo de datos VirtualPOS (staging + tablas canónicas) | Completada | — |
| DATA-02 | Documentar modelo de datos Toku | Completada | — |
| DATA-03 | Documentar modelo de datos Payku | Completada | — |
| DATA-04 | Documentar modelo de datos TCH (ETL + tablas tch_*) | Completada | — |
| TK-10 | Filtrar y ordenar estado secundario Toku (no depende de flow_name) | Completada | — |
| SYNC-01 | Auditar idempotencia y trazabilidad en consolidación | Completada | — |

### Definición de Done (Sprint 1)

- [x] `DATA-01–04`: Cada canal tiene doc en `docs/data/` con tablas, campos clave, relaciones y brechas conocidas
- [x] `TK-10`: Completada (2026-10-26). El código filtra y ordena antes de paginar y tiene tests con offset>0. BLQ-TK-01 es un bloqueo externo sin sprint asignado (ver Hoja de Ruta)
- [x] `SYNC-01`: Informe de idempotencia — 5 gaps documentados en `docs/data/sync-idempotency.md`

### Notas de sesión

- Sesión 2026-10-24: DATA-01–04 completos. Brechas principales: source_record_id=NULL en todos los canales (SYNC-GAP-03), VP con platform variable (SYNC-GAP-01), TCH con RUT como external_id en tensión con ADR-001 (GAP-TCH-01). TK-10: BLQ-TK-01 sigue sin respuesta de Toku. SYNC-01: mecanismo ON CONFLICT DO UPDATE idempotente en todas las rutas; riesgo principal es coexistencia de crm_materialization.py (legacy) + channel_consolidation.py.
- Sesión 2026-10-25 (cierre): SYNC-GAP-01 resuelto (`platform` acotado a `virtualpos1`/`virtualpos2`). SYNC-GAP-03 parcial: VP, Toku y Payku ya vinculan `source_record_id`; TCH sigue en NULL. SYNC-GAP-05 documentado como decisión (tablas centralizadas son copia derivada). `crm_materialization.py` desactivado, no borrado. ADR-001: nota sobre RUT como ID de proveedor en TCH.

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
| 0 | **Onboarding & Fundación** ✅ Completado | Entorno operativo + App.tsx modularizado | OPS-07, FE-02 | 2 sem |
| 1 | **Auditoría de Datos** ✅ Completado | Documentar datos objeto por canal | DATA-01–04, TK-10, SYNC-01 | 2 sem |
| 2 | **Componentes + KPIs** ← *activo: casi completo, falta verificación KPI-01 contra VP staging* | Componentes compartidos + KPIs estándar | FE-03, KPI-01–04 | 2 sem |
| 3 | Gráficos + Sidebar | Gráficos estandarizados + sidebar con salud | CHART-01–04, UI-20–21 | 2 sem |
| 4 | Recuperador VP | Mejoras al recuperador VirtualPOS | REC-03, WR-VP-05, PK-05 | 2 sem |
| 5 | Recuperador General | Recuperador multi-canal (Toku/Payku/TCH) | REC-04–06 | 3 sem |
| 6 | Infraestructura | Ambientes, respaldo y operaciones | ENV-01, BCK-01, OPS-09, VAL-VP-01, VAL-PK-01 | 2 sem |

**Bloqueo externo (sin sprint asignado):** BLQ-TK-01 (Toku `flow_name` para ENROLLMENT). Bloquea el alta de socios y el cambio de tarjeta en Toku. No bloquea los KPIs ni el estado secundario de Toku. Avanza cuando soporte de Toku responda.

---

## Cómo cerrar un sprint

Al completar todas las tareas del sprint activo:

1. Marcar todas las tareas como `Completada` en `docs/tasks.md`
2. Actualizar `docs/memory/PROJECT_STATE.md` con los cambios del sprint
3. Copiar este archivo y activar el siguiente sprint (editar **Sprint Activo**)
4. Registrar la fecha de cierre y lecciones aprendidas en **Notas de sesión**
