# SYNC-01 — Auditoría de Idempotencia y Trazabilidad

> Sprint 1 — Auditoría de Datos (cerrado 2026-10-25). Estado de brechas actualizado al 2026-10-25. Fuente: `app/services/channel_consolidation.py`, modelos `vp.py`, `toku_channel.py`, `payku_channel.py`, `tch.py`, `core.py`, `crm.py`.

## Mecanismo central de idempotencia

`channel_consolidation.py` usa `_upsert_centralized()` para todas las escrituras a tablas canónicas:

```python
stmt = insert(model).values(chunk)
updatable = {k: stmt.excluded[k] for k in chunk[0] if k not in ("id", "source", "external_id", "created_at")}
stmt = stmt.on_conflict_do_update(constraint=constraint, set_=updatable)
```

**Comportamiento:** `INSERT ... ON CONFLICT DO UPDATE` sobre la constraint `(source, external_id)`. Reemplaza todos los campos excepto `id`, `source`, `external_id` y `created_at`. La operación es idempotente para datos con el mismo par `(source, external_id)`.

## Idempotencia por canal

### VirtualPOS

| Nivel | Constraint | Estado |
|---|---|---|
| Tablas VP (`vp_*`) | `UNIQUE(platform, external_id)` | ✅ Idempotente |
| Tablas canónicas (`clients`, etc.) | `UNIQUE(source, external_id)` | ✅ Idempotente |
| Suscripciones activas | Índice parcial `uq_vp_sub_active_plan_client` (ACTIVA/SUSCRIBIENDO) | ✅ Antiduplicado activo |

**Riesgo resuelto (SYNC-GAP-01):** `source` en la consolidación VP usa `vp.platform`, que solo puede tomar `virtualpos1` o `virtualpos2` (las dos cuentas VP). `_VP_PLATFORMS` en `app/services/channel_store.py` define esos valores y `channel_consolidation.py` los valida; un valor desconocido se omite con warning. El diagnóstico previo ("platform variable" sin acotar) era impreciso.

### Toku

| Nivel | Constraint | Estado |
|---|---|---|
| Tablas Toku (`tk_*`) | `UNIQUE(external_id)` | ✅ Idempotente |
| Tablas canónicas | `UNIQUE(source, external_id)` con `source="toku"` fijo | ✅ Idempotente |

**Riesgo menor:** Vínculos (`customer`, `subscription`) extraídos de `raw_payload` en lugar de columnas indexadas. Si el payload cambia estructura, la extracción puede producir `NULL` sin error explícito.

### Payku

| Nivel | Constraint | Estado |
|---|---|---|
| Tablas Payku (`p_*`) | `UNIQUE(external_id)` | ✅ Idempotente |
| Tablas canónicas | `UNIQUE(source, external_id)` con `source="payku"` fijo | ✅ Idempotente |

**Riesgo menor:** `client_social_id` en suscripciones se extrae de `raw_payload.client.rut`. Si está ausente, queda `NULL` sin error.

### TCH

| Nivel | Constraint | Estado |
|---|---|---|
| `tch_clientes` | `UNIQUE(rut)` | ✅ Idempotente |
| `tch_suscripciones` | `UNIQUE(numero_ficha)` | ✅ Idempotente |
| `tch_transacciones` | `UNIQUE(dedupe_key)` | ✅ Idempotente |
| Tablas canónicas | `UNIQUE(source, external_id)` con `source="tch"` fijo | ✅ Idempotente |

**Riesgo:** `dedupe_key` se construye en el ETL de carga. Si la lógica cambia entre cargas, un mismo cargo puede ingresar con dos `dedupe_key` distintos → duplicados en `tch_transacciones` y en `charges`.

## Trazabilidad: source_record_id

| Canal | `source_record_id` en tablas canónicas | Estado |
|---|---|---|
| VirtualPOS | Vinculado mediante `_source_record_ids` / `_link_source_records` | ✅ Parcial: se rellena en consolidación |
| Toku | Vinculado mediante `_source_record_ids` / `_link_source_records` | ✅ Parcial: se rellena en consolidación |
| Payku | Vinculado mediante `_source_record_ids` / `_link_source_records` | ✅ Parcial: se rellena en consolidación |
| TCH | `NULL` | ⚠️ Sin trazabilidad a `source_records` |

La segunda pasada de vinculación usa `COALESCE` y no borra vínculos existentes. TCH sigue en `NULL` porque su carga no escribe en `source_records` (~150 mil filas; requiere una carga previa). El backfill para filas históricas es `scripts/maintenance/backfill_source_record_ids.py`: por defecto hace dry-run y `--apply` escribe. **Aún no se ha ejecutado.**

**Impacto:** Para TCH no es posible rastrear un registro canónico a su `SourceRecord` (payload crudo auditado). El `raw_payload` en las tablas de canal suplanta esta función parcialmente, pero no está vinculado formalmente a `source_records`.

## Brechas de idempotencia identificadas

| ID | Severidad | Canal | Descripción | Estado (2026-10-25) |
|---|---|---|---|---|
| SYNC-GAP-01 | **Media** | VirtualPOS | `source=vp.platform` variable. Si el proveedor cambia el valor de `platform`, puede romper la idempotencia. | ✅ **Resuelto.** `platform` acotado a `virtualpos1` / `virtualpos2` (`_VP_PLATFORMS` en `channel_store.py`, validado en `channel_consolidation.py`; valores desconocidos se omiten con warning). |
| SYNC-GAP-02 | **Media** | TCH | `dedupe_key` calculado en ETL. Cambios en la lógica de construcción generan duplicados. | 📝 **Caracterizado, decisión pendiente** (2026-10-26). 9 tests en `tests/test_etl_tch.py`; script de auditoría de solo lectura `scripts/maintenance/audit_tch_duplicate_cuotas.sql`. Pregunta de negocio abierta: ¿un rechazo y un pago posterior de la misma cuota son dos cargos distintos? |
| SYNC-GAP-03 | **Alta** | Todos | `source_record_id=NULL` en todas las rutas de consolidación. Trazabilidad formal incompleta. | 🟡 **Parcial.** VP, Toku y Payku vinculados; TCH sigue en `NULL`. Backfill escrito (`backfill_source_record_ids.py`), no ejecutado. |
| SYNC-GAP-04 | **Baja** | Toku, Payku | Extracción de campos relacionales desde `raw_payload` sin columnas indexadas. Silent NULL en cambios de estructura. | 🟢 **Mitigado/monitoreado** (2026-10-26). 49 tests en `tests/test_sync_gap04_payload_shapes.py`; log agregado `_log_null_relations` en `channel_consolidation.py` (solo conteos, sin PII). Quirk fijado: `customer: ["c1"]` guarda el texto "['c1']". |
| SYNC-GAP-05 | **Media** | TCH | `upsert_centralized` usa `ON CONFLICT DO UPDATE` que reemplaza todos los campos no excluidos. Un rerun completo sobreescribe datos editados manualmente en canónicas. | 📝 **Documentado, no corregido.** Decisión: las tablas centralizadas son una copia derivada de los canales y se sobrescriben en cada corrida. No existe ruta de edición manual; `write_payku` solo copia lo ya escrito en Payku. Cualquier cambio manual en canónicas se pierde en el siguiente rerun. |

## Coexistencia de rutas de consolidación

`channel_consolidation.py` es la ruta vigente. `crm_materialization.py` queda **desactivado, no borrado**:
- `virtualpos_sync.py` consolida mediante `consolidate_to_centralized`.
- `POST /etl/run` devuelve HTTP 410.
- `crm_materialization.py` tenía un `KeyError` con `payment_method`.

**Limitación pendiente:** en `virtualpos_sync.py` la consolidación sigue condicionada a `if materialize_ids`.

**Acción pendiente:** decidir el borrado definitivo de `crm_materialization.py` tras verificar que su desactivación no afecta a ningún flujo. Ver `docs/decisions/` y Technical Debt.
