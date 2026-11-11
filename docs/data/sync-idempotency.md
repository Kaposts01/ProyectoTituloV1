# SYNC-01 — Auditoría de Idempotencia y Trazabilidad

> Sprint 1 — Auditoría de Datos (cerrado 2026-10-25). Estado de brechas actualizado al 2026-10-25; **revisado contra `master` (`248d515`) el 2026-11-10 para el cierre de SYNC-01 en S6** (ver la sección «Cierre S6» al final). Fuente: `app/services/channel_consolidation.py`, modelos `vp.py`, `toku_channel.py`, `payku_channel.py`, `tch.py`, `core.py`, `crm.py`.

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
| TCH | Registrado por `app/services/tch_source_records.py` (SYNC-D-16) en cada carga, con las mismas claves de la consolidación | ✅ Desde SYNC-D-16 (actualizado 2026-11-10) |

La segunda pasada de vinculación usa `COALESCE` y no borra vínculos existentes. Desde SYNC-D-16 la carga TCH registra un `source_record` mínimo (sin datos personales) por fila de `tch_*` y la consolidación lo enlaza; el backfill de lo ya cargado es `etl_tch.backfill_source_records` (dry-run por defecto). El backfill de VP, Toku y Payku es `scripts/maintenance/backfill_source_record_ids.py` (dry-run por defecto, `--apply` escribe). **No verificado (2026-11-10): si alguno de los dos backfills se ejecutó en `crm` o `crm_sandbox`** (exige mirar filas).

**Impacto:** Para TCH no es posible rastrear un registro canónico a su `SourceRecord` (payload crudo auditado). El `raw_payload` en las tablas de canal suplanta esta función parcialmente, pero no está vinculado formalmente a `source_records`.

## Brechas de idempotencia identificadas

| ID | Severidad | Canal | Descripción | Estado (2026-10-25) |
|---|---|---|---|---|
| SYNC-GAP-01 | **Media** | VirtualPOS | `source=vp.platform` variable. Si el proveedor cambia el valor de `platform`, puede romper la idempotencia. | ✅ **Resuelto.** `platform` acotado a `virtualpos1` / `virtualpos2` (`_VP_PLATFORMS` en `channel_store.py`, validado en `channel_consolidation.py`; valores desconocidos se omiten con warning). |
| SYNC-GAP-02 | **Media** | TCH | `dedupe_key` calculado en ETL. Cambios en la lógica de construcción generan duplicados. | ✅ **Decidido** (DEC-04 resuelta por D13: clave ficha, período y cuota; TCH-PAR-03). Antes: caracterizado (2026-10-26). 9 tests en `tests/test_etl_tch.py`; script de auditoría de solo lectura `scripts/maintenance/audit_tch_duplicate_cuotas.sql`. Pregunta de negocio abierta: ¿un rechazo y un pago posterior de la misma cuota son dos cargos distintos? |
| SYNC-GAP-03 | **Alta** | Todos | `source_record_id=NULL` en todas las rutas de consolidación. Trazabilidad formal incompleta. | 🟢 **Resuelta en código** (2026-11-10): VP, Toku y Payku vinculados en la consolidación; TCH desde SYNC-D-16 (`tch_source_records.py`, `tests/test_sync_d16_tch.py`). Pendiente operativo: confirmar la ejecución de los backfills históricos. |
| SYNC-GAP-04 | **Baja** | Toku, Payku | Extracción de campos relacionales desde `raw_payload` sin columnas indexadas. Silent NULL en cambios de estructura. | 🟢 **Mitigado/monitoreado** (2026-10-26). 49 tests en `tests/test_sync_gap04_payload_shapes.py`; log agregado `_log_null_relations` en `channel_consolidation.py` (solo conteos, sin PII). Quirk fijado: `customer: ["c1"]` guarda el texto "['c1']". |
| SYNC-GAP-05 | **Media** | TCH | `upsert_centralized` usa `ON CONFLICT DO UPDATE` que reemplaza todos los campos no excluidos. Un rerun completo sobreescribe datos editados manualmente en canónicas. | 📝 **Documentado, no corregido.** Decisión: las tablas centralizadas son una copia derivada de los canales y se sobrescriben en cada corrida. No existe ruta de edición manual; `write_payku` solo copia lo ya escrito en Payku. Cualquier cambio manual en canónicas se pierde en el siguiente rerun. |

## Coexistencia de rutas de consolidación

`channel_consolidation.py` es la ruta vigente. `crm_materialization.py` queda **desactivado, no borrado**:
- `virtualpos_sync.py` consolida mediante `consolidate_to_centralized`.
- `POST /etl/run` devuelve HTTP 410.
- `crm_materialization.py` tenía un `KeyError` con `payment_method`.

**Limitación resuelta** (verificado 2026-11-10): `virtualpos_sync.py` ya no usa `materialize_ids`; consolida con `consolidate_to_centralized` cuando `consolidate=True` y el orquestador lo hace una sola vez al final (SYNC-O). `crm_materialization.py` sigue en el repo, sin llamadas desde la sync.

**Acción pendiente:** decidir el borrado definitivo de `crm_materialization.py` tras verificar que su desactivación no afecta a ningún flujo. Ver `docs/decisions/` y Technical Debt.

## Orquestación de la sincronización (Sprint 5, SYNC-O-xx)

Resumen de cómo corre hoy `sync_all_channels` (job nocturno 02:00, reintento 04:00, botón de `/scheduler`):

1. **Un solo ejecutor.** `app/scheduler/run_lock.py` crea la fila `etl_runs` en `running` bajo `pg_advisory_xact_lock`; con otra corrida activa (nocturna, reintento, `/etl/full-sync`, `/etl/core/*` o importación TCH) responde 409 o se omite. Un `running` con más de `SYNC_RUN_STALE_HOURS` (6 por defecto) se marca `failed` (abandonado) y deja de bloquear. La limpieza de zombis del arranque de la API sigue existiendo (con varios workers puede marcar una corrida ajena: se resuelve con el worker separado, D11).
2. **VirtualPOS se consolida una vez.** `sync_virtualpos(consolidate=False)` solo carga staging; la consolidación `virtualpos` (ambas cuentas) corre una vez al final y `reconcile_charge_recoveries` después, solo para las cuentas con sync exitoso. Si la consolidación de VP falla, las cuentas quedan `failed` y en `channels_failed` (el reintento las toma).
3. **TCH solo tras una carga.** La importación de Excel escribe únicamente en `tch_*`; `clients`/`subscriptions`/`charges` de TCH los alimenta solo la consolidación. La corrida nocturna la omite si el registro de reportes (`tch_report_registry`) no tiene un reporte nuevo desde la última consolidación TCH exitosa (marca en `source_records`, `resource_type='consolidation_mark'`, foto del registro tomada antes de consolidar). Un pedido explícito del canal `tch` siempre consolida. `SYNC_TCH_CONSOLIDATE_ONLY_AFTER_LOAD=false` restaura la pasada diaria. Cualquier cambio manual a `tch_*` que no pase por la importación (p. ej. `backfill_tch_contact_data.py`) debe cerrarse con una corrida explícita del canal `tch`.
4. **ETL Core dentro del sync.** Tras consolidar, corren `run_vp_core_etl`, `run_toku_core_etl` y `run_payku_core_etl` solo para los canales que sincronizaron y consolidaron sin error. Un fallo deja el run `partial` ("ETL Core con error: canal"). Cada ETL Core exitoso (también los manuales `/etl/core/*`) deja una marca (`source_records`, `source='core_etl'`); `GET /sync-runs/health` marca `degraded` y expone `core_lag_hours` si el ETL Core va más de 24 h detrás del último sync exitoso del canal. `SYNC_CORE_ETL_ENABLED=false` lo apaga.

### Instrumentación por fase y recurso (SYNC-O-01, sin migración)

`etl_runs` y `sync_runs` no tienen columnas JSON, así que cada corrida de `sync_all_channels` deja, además de sus filas:

- una línea de log estructurada (`logger sync.metrics`, `sync_metrics {json}`), y
- una fila en `source_records` con `source='sync_metrics'`, `resource_type='run'`, `external_id=<id del etl_run>` y este payload:

```json
{"run_id": "…", "notes": {"tch_consolidation": "omitida: …"},
 "phases": [
  {"phase": "sync", "resource": "toku", "seconds": 5821.4},
  {"phase": "sync_resource", "resource": "toku.transaction", "api_seconds": 4700.2, "upsert_seconds": 31.0, "pages": 505, "records": 50505},
  {"phase": "consolidate", "resource": "virtualpos.vp_charges", "seconds": 61.2, "records": 238000},
  {"phase": "consolidate_total", "resource": null, "seconds": 1650.0, "records": 1900000},
  {"phase": "core_etl", "resource": "toku", "seconds": 40.1, "records": 6503}]}
```

Consulta de ejemplo: `SELECT payload FROM source_records WHERE source='sync_metrics' AND resource_type='run' ORDER BY last_seen_at DESC LIMIT 5;`. Solo hay nombres de fase/recurso, duraciones y conteos (nada personal ni del proveedor). Un fallo al guardar las métricas nunca interrumpe la corrida. Si en el futuro se agrega una columna JSON a `etl_runs`, `RunMetrics.payload()` ya entrega el objeto listo.

## Cierre S6: contratos por canal (revisión del 2026-11-10)

Revisión de solo lectura contra `master` (`248d515`). No se consultaron filas de ninguna base. «No verificado» marca
lo que exige datos reales o una medición en el proveedor.

### Claves comunes a todos los canales de API

| Capa | Clave de idempotencia | Al repetir | Fuente |
|---|---|---|---|
| `source_records` | `UNIQUE (source, resource_type, external_id)` (`uq_source_record`) | `INSERT ... ON CONFLICT DO UPDATE ... WHERE <payload o sync_context distinto>` por lotes de 500: una fila sin cambios no se reescribe ni cuenta; dentro de un lote, un `external_id` repetido gana la última aparición | `app/services/source_record_store.py` (SYNC-O-10) |
| Tablas de canal (`vp_*`, `tk_*`, `p_*`) | `vp_*`: `(platform, external_id)`; `tk_*` y `p_*`: `external_id` | upsert con guarda `IS DISTINCT FROM`: `updated_at` solo se mueve con un cambio real; `last_seen_at` se actualiza aparte (lo usa la detección de bajas) | `app/services/channel_store.py` |
| Canónicas (`clients`, `subscriptions`, `charges`, `payments`, `payment_methods`) | `(source, external_id)` | `_upsert_centralized` con guarda `IS DISTINCT FROM` (SYNC-O-07): una segunda consolidación sin cambios escribe 0 filas y 0 eventos. Con la lectura diferencial (`_SINCE`, apagada por defecto: `CONSOLIDATION_DIFFERENTIAL_ENABLED=false`) solo se leen las filas de canal con `updated_at >= desde` | `app/services/channel_consolidation.py` |
| Core (`core_*`) | `(source, external_id)`; `external_identities` `(source, resource_type, external_id)`; `core_client_attributes` `(source, attribute_type, attribute_value)` | upsert del ETL Core; cada ETL exitoso deja la marca `source='core_etl'`. Resultado idempotente, pero en VP, Toku y Payku el upsert **no tiene guarda de cambios** (reescribe todo en cada corrida) y `core_payments` usa `DO NOTHING` (un cambio de estado o monto de un pago ya existente no llega a Core salvo los parches de rechazos y fechas); TCH sí usa `_upsert_changed` | `app/services/core_*_etl.py`, `core_etl_mark.py` |
| Marcas de lectura | `sync_cursors (source, resource, mode, window_start)` con `NULLS NOT DISTINCT` | una marca por modo; avanza solo si la corrida termina bien (misma transacción) | `app/services/sync_cursors.py` (SYNC-O-08) |
| Exclusión | una sola corrida a la vez (`pg_advisory_xact_lock` sobre `etl_runs`) | una segunda corrida recibe 409 o se omite; un `running` de más de `SYNC_RUN_STALE_HOURS` se da por abandonado | `app/scheduler/run_lock.py` |

**Bajas por desaparición (SYNC-D-13, `app/services/channel_removals.py`).** Solo para suscripciones de VP, Toku y
Payku. Apagada por defecto (`SYNC_REMOVAL_DETECTION_ENABLED`). Solo actúa tras una lectura **completa** y exitosa
(sin ventana, sin página tope, sin fallo): una corrida parcial nunca marca bajas. Si las desaparecidas superan
`SYNC_REMOVAL_MAX_RATIO` o `SYNC_REMOVAL_MAX_COUNT`, aborta sin escribir y deja la alerta `removal_aborted:<canal>`.
Marca `removed_at` y emite un evento `removed` por fila, de forma idempotente; si la fila reaparece, el upsert limpia
`removed_at`. No cambia `status` (decisión de negocio pendiente).

**Ventanas (SYNC-O-02/05, `app/services/sync_window.py`).** Apagadas por defecto (`SYNC_WINDOWED_READS_ENABLED`). Con la
bandera encendida, un recurso se lee por ventana solo si hay una lectura completa de menos de
`SYNC_WINDOW_FULL_REFRESH_DAYS` (7); la ventana parte en el último éxito menos `SYNC_WINDOW_OVERLAP_HOURS` (48 h). Si el
proveedor ignora el filtro (registros fuera de la ventana, o un total que no baja), se abandona la ventana y se lee
completo (`WindowFilterIgnored`).

**Reanudación.** La sync diaria **no** se reanuda a mitad. `channel_store.upsert_channel` hace `commit` por lote o
página, así que lo ya cargado en `vp_*`, `tk_*` y `p_*` **persiste** aunque la corrida falle después; el `ROLLBACK` del
final solo descarta lo pendiente. La corrida queda `failed` con mensaje saneado, las marcas de cursor no avanzan y no se
detectan bajas; el reintento de las 04:00 (`retry_failed.py`, toma `channels_failed` del último `etl_runs`, máximo 3
fallos por canal y día, no reintenta errores de configuración) relee desde la página 1 y el upsert lo hace inocuo.
**Una corrida que se cae entera** (proceso muerto, `running` abandonado) no llena `channels_failed` y por eso no se
reintenta a las 04:00: queda para la noche siguiente o un pedido manual. La carga histórica (`sync_history.py`,
`mode='history'`) sí se reanuda: cada ventana guarda su `page` y `--resume` sigue desde ahí; una ventana cuyo filtro de
fecha se ignora queda `failed` y detiene la ejecución.

### Por canal

| Canal | Clave de idempotencia | Repetir una corrida | Corrida parcial | Riesgos conocidos |
|---|---|---|---|---|
| **VirtualPOS** (`virtualpos1`, `virtualpos2`; `app/services/virtualpos_sync.py`) | `vp_*` `(platform, external_id)`; `source_records` con `source=<platform>`; canónicas `(source=platform, external_id)`; antiduplicado de suscripción activa `uq_vp_sub_active_plan_client` | inocuo (upserts con guarda). Suscripciones y planes se leen siempre completos; los cargos llegan **embebidos** en `charge_program` de cada suscripción; clientes y pagos admiten ventana (pagos por creación y por autorización) | lo cargado por página persiste; un fallo (incluido un NOK con HTTP 200) deja la cuenta `failed`, sin marcas de cursor ni bajas, y sin `reconcile_charge_recoveries`. `sync_all_channels` consolida los canales **pedidos** (no solo los exitosos), así que lo parcial llega a las canónicas; el ETL Core corre si al menos una cuenta terminó bien | **VP-C26 confirmado el 2026-11-10: el sandbox ignora los filtros de fecha de `/charges`.** La sync no depende de ese filtro: `list_charges` no manda fechas y la sync usa los cargos embebidos. Afecta a cualquier lectura futura de cargos por fecha y a la facturación gestionada (debe filtrar en el CRM). **No verificado en producción.** Una suscripción omitida por duplicado activo igual cuenta como vista (no genera baja falsa) |
| **Toku** (`app/services/toku_sync.py` sobre `read_only_provider_sync.py`) | `tk_*` `external_id`; `source_records` `source='toku'`; canónicas `(source='toku', external_id)`. Los reportes van a tablas `tk_report_*` propias que la sync no pisa (DEC-19) | inocuo. Solo las transacciones admiten ventana (solape de 48 h por DEC-03; la guarda mira `transaction_date` e `initialization_date`) | lo cargado por página persiste (igual que VP); un 404 en `payment` o `payment_method` (opcionales) deja la corrida `partial`, conserva lo leído y no avanza el cursor de ese recurso. Un error en los recursos esenciales o un 401/403 hace fallar todo. Lectura truncada de suscripciones = sin detección de bajas | DEC-03 abierta (qué fecha filtra la API). Vínculos sacados de `raw_payload` (SYNC-GAP-04, mitigado) |
| **Payku** (`app/services/payku_sync.py`) | `p_*` `external_id`; `source_records` `source='payku'`; canónicas `(source='payku', external_id)`; `p_report_transactions.row_key` (sha256 de voucher, orden, fecha y monto) | inocuo. Clientes, planes y suscripciones completos; las transacciones llegan **embebidas** en cada suscripción; las transacciones repetidas en un mismo lote se deduplican | lo cargado por página persiste (igual que VP); superar `_MAX_PAGES` lanza error (no hay lectura truncada que parezca completa). La carga histórica de transacciones por ventanas de 30 días (`date_init`/`date_end`) **solo agrega** las que no existen, para no pisar las embebidas | **Payku V1 sin fechas (d188): pendiente de medir.** La sync diaria no usa fechas en `/api/sususcription`; `list_subscriptions` y `list_transactions` aceptan `date_init`/`date_end`, pero no está medido si la API V1 las respeta ni si los registros traen fechas útiles. Hasta medirlo, la protección es la guarda de ventana ignorada de `sync_history`. Payku sigue sin sandbox |
| **TCH** (Excel; `scripts/etl_tch.py`, `POST /api/v1/tch/import-report`) | `tch_clientes.rut`, `tch_suscripciones.numero_ficha`, `tch_transacciones.dedupe_key` (ficha, período y cuota, D13); un reporte ya cargado se rechaza por `sha256` (`tch_report_registry`); `source_records` con las mismas claves (SYNC-D-16) | reimportar el mismo archivo se rechaza; una recarga completa reutiliza los mismos `source_records` (ids estables). La consolidación nocturna se omite si no hubo un reporte nuevo (marca `consolidation_mark`) | la importación incremental es una transacción con `ROLLBACK` si falla; la recarga completa solo hace `commit` si la conciliación sale bien | **Bajas implícitas**: una importación marca `ELIMINADA` toda ficha vigente o pendiente ausente de la cartera del reporte (`_apply_implicit_cancellations`), solo si el reporte no es anterior a lo ya cargado (`_is_latest_report`) y trae una hoja de vigentes legible. **Un reporte del último período con cartera incompleta marcaría bajas falsas** (no hay umbral como en SYNC-D-13). **Probable, no verificado:** en la subida web el período se calcula del nombre del archivo temporal (`synkmetrix-tch-*.xlsx`) y no del nombre original, lo que dejaría `reporte_periodo` vacío, haría que un reporte viejo pise el estado y que la subida web nunca aplique bajas implícitas. `dedupe_key` es nullable: filas antiguas sin clave usan `id::text` (cambia con cada recarga completa) y quedan sin `source_record` (no verificado si existen). SYNC-GAP-05 (las canónicas se sobrescriben) sigue documentada |

### Tests que cubren cada contrato

| Contrato | Tests (`archivo::test`) |
|---|---|
| Upsert de `source_records` y vínculos | `tests/test_source_record_store.py::test_batch_counts_inserted_then_is_idempotent`; `tests/test_channel_seen_guard.py::test_unchanged_row_keeps_updated_at_but_is_marked_seen`; `tests/test_sync_gaps.py::test_consolidation_sets_source_record_id_and_second_pass_keeps_it`, `::test_upsert_without_match_does_not_erase_existing_link`, `::test_full_vp_sync_leaves_single_linked_version_per_row`, `::test_unknown_platform_is_rejected_on_store`, `::test_unknown_platform_is_skipped_on_consolidation` |
| Consolidación idempotente y diferencial | `tests/test_consolidation_differential.py::test_second_consolidation_without_changes_writes_zero_rows_and_zero_events`, `::test_identical_rows_are_not_rewritten`, `::test_status_change_events_regression_exactly_one_event_per_real_change`, `::test_differential_reads_only_changed_rows`, `::test_upsert_channel_moves_updated_at_only_on_real_change` |
| VirtualPOS | `tests/test_virtualpos_sync.py::test_sync_stages_all_pages_materializes_records_and_is_idempotent`, `::test_sync_records_sanitized_failure_without_persisting_test_data`; `tests/test_sync_vp_single_consolidation.py::test_orchestrator_nightly_consolidates_virtualpos_a_single_time`, `::test_virtualpos_consolidation_failure_keeps_the_accounts_retryable`, `::test_failed_account_is_not_reconciled`; `tests/test_virtualpos_charge_idempotency.py::test_reassign_two_times_is_idempotent` (escrituras) |
| Toku y Payku (lector genérico) | `tests/test_read_only_provider_sync.py::test_toku_sync_stages_all_available_pages_and_sanitizes_records`, `::test_payku_sync_stages_read_only_collections`; `tests/test_toku_optional_404.py::test_a_404_on_payments_skips_it_and_keeps_the_rest`; `tests/test_payku_batch_dedupe.py::test_duplicate_transactions_in_same_batch_are_deduped`; `tests/test_sync_gap04_payload_shapes.py` (49 tests de formas de payload) |
| TCH | `tests/test_tch_par03.py::test_reprocessing_the_same_report_is_idempotent`; `tests/test_tch_par13.py::test_second_tch_consolidation_reads_and_writes_nothing`; `tests/test_etl_tch.py::test_implicit_cancellation_only_applies_to_the_latest_report`, `::test_implicit_cancellation_never_runs_with_an_empty_last_report`, `::test_load_tch_rows_is_idempotent`, `::test_dedupe_key_exact_format`, `::test_dedupe_key_does_not_depend_on_status_nor_amount`; `tests/test_tch_import.py::test_tch_report_import_rejects_a_report_already_loaded_by_sha256`, `::test_tch_report_import_rejects_when_another_run_is_active`; `tests/test_sync_d16_tch.py::test_backfill_registers_every_tch_row_once_and_is_idempotent`, `::test_full_reload_reuses_the_same_source_records`; `tests/test_sync_tch_conditional.py::test_final_canonical_state_equals_the_unconditional_nightly_pass`, `::test_a_failed_tch_consolidation_is_not_marked` |
| Bajas por desaparición | `tests/test_channel_removals.py::test_partial_sync_never_marks`, `::test_complete_sync_marks_missing_and_is_idempotent`, `::test_threshold_exceeded_aborts_without_writing_and_alerts`, `::test_vp_removals_are_scoped_by_platform`, `::test_vp_row_skipped_by_active_duplicate_still_counts_as_seen`, `::test_generic_sync_truncated_read_is_partial` |
| Ventanas y filtro ignorado | `tests/test_sync_windowed_reads.py::test_flag_is_off_by_default`, `::test_window_starts_at_last_success_minus_the_overlap`, `::test_ignored_filter_falls_back_to_a_full_read`, `::test_vp_ignored_date_filter_falls_back_to_full`, `::test_vp_total_not_reduced_by_the_filter_falls_back_to_full`, `::test_full_reread_when_the_last_full_read_is_too_old` |
| Cursores y reanudación histórica | `tests/test_sync_cursors.py::test_record_success_is_one_row_per_mode_and_advances`; `tests/test_sync_history.py::test_save_plan_is_idempotent_and_keeps_progress`, `::test_request_cap_stops_and_resume_continues_from_saved_page`, `::test_ignored_date_filter_fails_the_window`, `::test_payku_history_never_overwrites_known_transactions` |
| Exclusión y fallos | `tests/test_sync_lock.py::test_two_concurrent_starts_only_one_wins`, `::test_a_stale_running_run_expires_and_a_fresh_one_blocks`, `::test_two_simultaneous_nightly_runs_execute_the_sync_once`; `tests/test_rev01_sync_reliability.py::test_scheduler_fatal_error_keeps_progress_and_never_stores_the_exception_text`; `tests/test_retry_failed.py::test_retries_failed_channels`, `::test_channels_over_the_daily_failure_cap_are_not_retried` |

En esta revisión no se ejecutaron los tests (solo documentación); la última CI de `master` (PR #10) pasó con 2.759
pruebas de backend.

### Pendientes y no verificado

- **Bajas implícitas de TCH sin umbral**: protegerlas con una guarda como la de SYNC-D-13 (por ejemplo, abortar si
  desaparece más de un porcentaje de la cartera) o documentar que solo se importan reportes de cierre completos. Ningún
  test cubre un reporte con cartera incompleta.
- **Página vacía silenciosa (VP y Toku)**: el cliente VP decodifica en modo tolerante (un HTTP 200 que no es JSON se
  lee como `{}`, es decir, página vacía) y el lector genérico devuelve `[]` ante un envoltorio desconocido; la
  paginación termina antes, la corrida queda `completed` y, con la detección de bajas encendida, solo el umbral
  (comparación estricta `> 5 %` o `> 100`) evita marcar bajas falsas. Asumido en
  `tests/test_virtualpos_sync.py::test_empty_dict_response_completes_sync_as_empty_page`. Payku sí lanza error.
- **Payku `per_page`**: el máximo de la API V1 no está documentado (Q-12); si fuera menor que 100, `_has_more` cortaría
  tras la primera página y la lectura parecería completa.
- **Bajas solo en tablas de canal**: `removed_at` no llega a las canónicas y no se detectan desapariciones de cobros,
  pagos ni clientes.
- **`external_id` por hash**: si un registro llega sin `id`, el `external_id` es el sha256 del payload y un cambio de
  estado crearía una fila nueva en `source_records` (no verificado que ocurra con payloads reales).
- **Payku sin telemetría completa**: su `sync_runs` no lleva `etl_run_id` ni `resource_stats` y no escribe
  `sync_cursors`.
- **Sin test de bajas desde `sync_virtualpos` ni `sync_payku`**: los tests de SYNC-D-13 llaman la función directamente
  o pasan por el lector genérico de Toku.
- **Payku V1 (d188)**: medir si se respetan los filtros de fecha y si los registros traen fechas; depende del sandbox o
  de una lectura autorizada en producción.
- **VP-C26**: confirmado en el sandbox el 2026-11-10; no medido en producción. La sync no se ve afectada.
- **Backfills de `source_record_id`** (VP, Toku, Payku y TCH): no verificado si se ejecutaron en `crm` y `crm_sandbox`.
- **Bajas por desaparición y ventanas**: ambas vienen apagadas por defecto; no verificado qué valor tienen en producción.
- **`crm_materialization.py`**: sigue en el repo sin uso desde la sync; falta decidir su borrado.
