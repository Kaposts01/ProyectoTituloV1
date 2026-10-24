# SYNC-01 — Auditoría de Idempotencia y Trazabilidad

> Sprint 1 — Auditoría de Datos. Fuente: `app/services/channel_consolidation.py`, modelos `vp.py`, `toku_channel.py`, `payku_channel.py`, `tch.py`, `core.py`, `crm.py`.

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

**Riesgo:** `source` en la consolidación VP usa `vp.platform` (campo variable del registro), no la constante `"virtualpos"`. Si el proveedor retorna valores distintos para `platform`, el mismo cliente puede tener múltiples entradas con `source` diferente.

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
| VirtualPOS | `NULL` en toda la consolidación | ⚠️ Sin trazabilidad a `source_records` |
| Toku | `NULL` en toda la consolidación | ⚠️ Sin trazabilidad a `source_records` |
| Payku | `NULL` en toda la consolidación | ⚠️ Sin trazabilidad a `source_records` |
| TCH | `NULL` en toda la consolidación | ⚠️ Sin trazabilidad a `source_records` |

**Impacto:** No es posible rastrear un registro canónico a su `SourceRecord` (payload crudo auditado). El `raw_payload` en las tablas de canal suplanta esta función parcialmente, pero no está vinculado formalmente a `source_records`.

## Brechas de idempotencia identificadas

| ID | Severidad | Canal | Descripción |
|---|---|---|---|
| SYNC-GAP-01 | **Media** | VirtualPOS | `source=vp.platform` variable. Si el proveedor cambia el valor de `platform`, puede romper la idempotencia. |
| SYNC-GAP-02 | **Media** | TCH | `dedupe_key` calculado en ETL. Cambios en la lógica de construcción generan duplicados. |
| SYNC-GAP-03 | **Alta** | Todos | `source_record_id=NULL` en todas las rutas de consolidación. Trazabilidad formal incompleta. |
| SYNC-GAP-04 | **Baja** | Toku, Payku | Extracción de campos relacionales desde `raw_payload` sin columnas indexadas. Silent NULL en cambios de estructura. |
| SYNC-GAP-05 | **Media** | TCH | `upsert_centralized` usa `ON CONFLICT DO UPDATE` que reemplaza todos los campos no excluidos. Un rerun completo sobreescribe datos editados manualmente en canónicas. |

## Coexistencia de rutas de consolidación

`channel_consolidation.py` y `crm_materialization.py` coexisten actualmente:
- `crm_materialization.py`: ruta legacy, usada en el flujo `virtualpos_sync` durante la transición.
- `channel_consolidation.py`: ruta nueva, usada en el scheduler y consolidación principal.

Ejecutar ambas sobre los mismos datos produce dos escrituras a las mismas tablas canónicas. Ambas son idempotentes, pero si difieren en la lógica de mapeo pueden producir estados distintos según cuál corra último.

**Acción pendiente:** completar la transición y eliminar `crm_materialization.py`. Ver `docs/decisions/` y Technical Debt.
