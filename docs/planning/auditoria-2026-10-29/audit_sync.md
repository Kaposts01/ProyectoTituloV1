# Auditoría SYNC: sincronización diaria, detección de cambios y carga histórica

Fecha: 2026-10-29. Solo lectura. La base se consultó con SELECT agregados (sin datos personales ni valores del `.env`). Código revisado: `app/scheduler/*`, `app/services/{virtualpos,payku,toku,read_only_provider}_sync.py`, `channel_store.py`, `channel_consolidation.py`, `core_*_etl.py`, `app/integrations/*/client.py`, `api/v1/routes/{sync_runs,scheduler,etl,tch}.py`, `main.py`, `scripts/etl_tch.py`, `models/{core,sync_run,etl_run,source_record}.py`.

## 0. Hallazgos clave (lo más importante)

1. **No existe historial de transiciones de estado.** Cada capa se sobrescribe con `INSERT ... ON CONFLICT DO UPDATE` (canal `vp_*`/`tk_*`/`p_*` -> `charges`/`subscriptions`/`payments`). `source_record_observations` (diseñada para historial de payloads) está **vacía (0 filas) y nadie la escribe**. `source_records.last_seen_at` solo se actualiza cuando el payload cambia (cláusula `WHERE ... IS DISTINCT FROM`), así que no sirve para detectar bajas por desaparición.
2. **No hay resumen diario de cambios** (ni endpoint, ni tabla, ni job). `/sync-runs/health` solo dice si el canal sincronizó (ok/warn/error por antigüedad del último run), no qué cambió.
3. **La consolidación reescribe todo cada noche**: `consolidate_to_centralized(sources=None)` relee y hace upsert de TODAS las filas de los 4 canales (incluye ~1,47 M cargos TCH en trozos de 2000 con `OFFSET`), y cada `sync_virtualpos` ya consolida VP por su cuenta (VP se consolida 3 veces por corrida diaria). El run diario dura 1,9 a 2,8 h (p. ej. 6.757 s, 7.061 s, 10.174 s). Consecuencia directa: `updated_at` de las canónicas se mueve en todas las filas, por lo que **no se puede usar `updated_at` para detectar cambios**; hay que comparar valores explícitamente.
4. **La glosa/motivo de rechazo de VirtualPOS no se captura**: 0 de 23.891 cargos VP rechazados en `core_charges` tienen `latest_rejection_code`; `vp_payments.charge_external_id` es NULL en las 73.013 filas y el listado `/v3/payments` no trae `rejected_object` (0 filas). El detalle por intento solo existe en `get_payment_attempts` (por pago), usado únicamente en la ruta de escritura. TCH sí guarda `razon_rechazo` (63.130 filas, 11 valores distintos). Toku/Payku dependen de reportes (Toku, TK-19/20 pendientes) o del payload.
5. **El ETL Core (`core_*_etl`) NO está en el scheduler**: solo corre por `/etl/core/*` manual. `core_charges` de Toku está en 2026-10-21; VP se reconstruyó manualmente. Los pagos de Core se insertan con `ON CONFLICT DO NOTHING` (no reflejan cambios de estado de un pago).
6. **Estado operativo real (medido en `crm`)**: VirtualPOS2 y Payku llevan fallando desde 2026-10-27/28 por configuración (`VirtualPOS virtualpos2 is not configured`, `Illegal header value b'Bearer '`), 0 s de duración, y el reintento de las 04:00 fracasa igual (fallo determinista, no transitorio). Aun así el `etl_run` queda `completed` y nadie recibe alerta. De 99 `etl_runs`, 23 fallaron (12 por "Servidor reiniciado durante la sincronización"); en `sync_runs`, 35 fallos de toku/payku/vp con causas como DNS (`getaddrinfo`, 8), `ReadTimeout`/`ReadError` (5), `CardinalityViolation`.

## 1. Carga histórica reanudable por canal

Veredicto global: **no existe un modo histórico**. Solo hay una "sincronización completa" que siempre parte de la página 1 y repite todo el universo; no hay cursor persistido, ni ventanas de fecha, ni checkpoint. La idempotencia sí existe (upsert por `(platform|source, external_id)` y commit por página/lote), por lo que **re-ejecutar es seguro pero no es reanudable**: tras un fallo se reprocesa desde cero.

| Canal | Paginación / ventana | Reanudable | Límites y rate limit | Cobertura histórica hoy | Brecha |
|---|---|---|---|---|---|
| VirtualPOS | `page`/`limit=100` (clientes, pagos, suscripciones). Cargos vienen embebidos en `charge_program` de cada suscripción (sin paginar por cargos). Filtros `charge_date_from/to` **ignorados por la API** (medido). Planes sin paginar | No. Reinicia en página 1; cada página sí hace commit (el trabajo previo persiste, el run queda `failed`). Sin guardar página/cursor | Sin manejo de 429/5xx: solo reintenta `ReadTimeout/ReadError/ConnectError` (2 reintentos, backoff 1/2 s). Rate limits en lotes grandes sin medir (handoff §9). Tamaño de corrida: vp2 ~49 min a 2,3 h | Pagos desde 2025-02-24 (vp1) y 2025-04-23 (vp2); 238 mil cargos. Cumple "desde 2025" | `/v3/payments` sin filtro de fecha conocido; pagos de suscripciones canceladas sin vínculo a cargo (0 con `charge_external_id`); glosa no capturada |
| Toku | Cursor (`next_cursor`) guardado **solo en memoria** del cliente (`_cursors`); 100 por página; `sleep(1)` entre páginas de `transaction` | No. Perder el proceso pierde el cursor | `_get` reintenta 429/503/ReadTimeout 2 veces (1 s, 2 s), sin `Retry-After`; `ReadError` no se reintenta. Fallos observados de DNS y timeout | Facturas desde 2024-08-21 y transacciones desde 2024-10-10. **No llega a 2020**: no hay filtro de fecha en el cliente; el endpoint `/reports/{entity}` existe pero está bloqueado (`POST` sin usar) | Para 2020-2024 la única vía son los reportes del Backoffice (TK-19 a TK-22 pendientes). No hay estado de suscripción/cliente por API (solo reportes) |
| Payku | `page`/`per_page=100`, tope `_MAX_PAGES=2000`; `list_subscriptions` y `list_transactions` aceptan `date_init/date_end` pero el sync **no los usa**. Transacciones embebidas en suscripciones (el endpoint de transacciones hace timeout en histórico, según docstring) | No. Sin ventana ni checkpoint | Solo reintenta errores de red; sin 429/5xx. Fallo `CardinalityViolation` (resuelto con dedupe) y `Bearer` vacío | Suscripciones desde 2020-08-04 y transacciones desde 2020-08-18 (35.969). Cumple "desde 2020" para lo embebido | No se puede detectar transacciones que no estén embebidas; existe `scripts/maintenance/backfill_payku_transactions.py` pero sin ventanas reanudables |
| TCH (Excel) | Un `.xlsx` por carga (`/tch/import-report`, 202, `EtlRun`); `scripts/etl_tch.py --folder` procesa archivos ordenados | **Sí, por archivo** (modo `incremental`, `dedupe_key` único, `ON CONFLICT DO UPDATE`). El modo `full` hace `_clear_tch_data` (destructivo) | Límite de 250 MB por archivo; una sola carga activa a la vez | 1.472.231 cargos de 2017-11-01 a 2026-09-30 (386.660 rechazadas, 999.131 aceptadas, 58.120 nulas) | SYNC-GAP-02: `dedupe_key` incluye `estado` => rechazo y pago posterior de la misma cuota son 2 filas (no una transición) hasta resolver DEC-04. TCH sin `source_record_id` |

Qué cubre bien: idempotencia de escritura, commit por página, sanitización de PII, `MAX_PAGES` como guarda contra bucles, reintentos de red. Qué no cubre: reanudación (cursor/ventana persistidos), ventanas de fecha en Toku, uso de `date_init/date_end` en Payku, 429/`Retry-After` en VP y Payku, y un estado de "progreso histórico" visible.

## 2. Historial de transiciones de estado

**Hoy solo se guarda el último estado.** Evidencia: `_upsert_centralized` y `upsert_channel` hacen upsert sobrescribiendo `status`/`amount`; `CoreCharge`/`CoreSubscription` tienen `source_status`/`status` y `latest_rejection_*` sin tablas de eventos; no existe ningún modelo `*_status_*` o `*_history` (búsqueda en `app/` y `alembic/`). Los únicos "historiales" son los de billing (`billing_change_request_events`, `vp_managed_charges`), que no cubren estados de proveedor, y `charge_recoveries` (seguimiento de reintentos). `source_record_observations` existe pero vacía.

### Modelo mínimo propuesto: `status_change_events`

Tabla única, append-only:

| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid PK | |
| `entity_type` | varchar(20) | `charge` \| `subscription` \| `payment` |
| `source` | varchar(50) | `virtualpos1/2`, `toku`, `payku`, `tch` |
| `external_id` | varchar(255) | clave canónica (`charges.external_id`, etc.) |
| `subscription_external_id` | varchar(255) null | para agrupar por suscripción |
| `event_kind` | varchar(20) | `created`, `status_changed`, `amount_changed`, `reason_changed`, `removed` |
| `field` | varchar(30) | `status`, `amount`, `rejection_code` |
| `from_value`, `to_value` | text null | `from` NULL en `created` |
| `amount` | numeric(18,2) null | monto vigente del cobro (contexto) |
| `provider_event_at` | timestamptz null | fecha del proveedor si existe (p. ej. `change_date` de logs de Payku, `payment_date`) |
| `detected_at` | timestamptz | `now()` de la corrida (fecha de detección) |
| `run_id` | uuid null | `etl_runs.id`/`sync_runs.id` de la corrida que lo detectó |
| `is_baseline` | bool | true en la primera carga o carga histórica: no cuenta como "novedad" del día |
| `dedupe_key` | char(64) UNIQUE | sha256(`entity_type|source|external_id|field|from|to|run_id`) |

Índices: `(detected_at DESC)`, `(entity_type, source, external_id, detected_at)`, `(event_kind, detected_at)`, parcial `WHERE is_baseline = false`.

Tabla auxiliar `rejection_reason_catalog` (`source`, `code`, `reason`, `first_seen_at`, `last_seen_at`, `occurrences`, UNIQUE `(source, code, reason)`) para "nuevas glosas": el evento `reason_changed` se emite cuando el insert es nuevo (`xmax = 0`/`RETURNING`).

### Dónde engancharlo (idempotente)

Recomendada (opción A): en `channel_consolidation._upsert_centralized`, justo antes del `INSERT ... ON CONFLICT`:
1. Para cada trozo, `SELECT external_id, status, amount FROM <model> WHERE source = :s AND external_id = ANY(:ids)` (una consulta indexada por la constraint `uq_*_source_external_id`).
2. Comparar en Python con las filas nuevas: no existe -> `created`; `status` distinto -> `status_changed`; `amount` distinto -> `amount_changed`.
3. `INSERT INTO status_change_events ... ON CONFLICT (dedupe_key) DO NOTHING` en el mismo SAVEPOINT que el upsert (ya existe `db.begin_nested()` por función). Si el upsert falla se revierten ambos.
4. Idempotencia: re-ejecutar la misma corrida no genera diferencias (la fila ya tiene el valor nuevo) y, si el mismo run se repite tras un fallo parcial, `dedupe_key` con `run_id` evita duplicados. Las vueltas A->B->A sí generan eventos distintos porque el `from/to` y el `run_id` difieren.
5. Parametrizar por modelo con una tupla `TRACKED = {Charge: ("status","amount"), Subscription: ("status","amount"), Payment: ("status",)}` y excluir `Client`/`Plan`/`PaymentMethod`.
6. Bajas: (a) `canceled_at`/`status` cancelado ya llega como `status_changed`; (b) desaparición de la API: añadir una columna `last_seen_sync_at` (o `seen_in_run_id`) a las tablas de canal (hoy `last_seen_at` solo cambia con el payload) y, al final de un sync **completo y exitoso** de ese recurso, emitir `removed` para lo no visto (con guarda de seguridad: no emitir si el run falló o si faltan >X %).
7. Primera carga/histórica: marcar `is_baseline = true` (flag del run) para que 6.000 suscripciones "nuevas" de una carga histórica no inunden el resumen diario. Como VirtualPOS reescribe todo cada noche, la primera consolidación tras desplegar generaría eventos masivos: debe hacerse con una corrida baseline explícita (`--baseline`) antes de activar.

Opción B (alternativa): trigger `AFTER INSERT OR UPDATE` en `charges`/`subscriptions`/`payments` con `WHEN (OLD.status IS DISTINCT FROM NEW.status OR OLD.amount IS DISTINCT FROM NEW.amount)`, tomando `run_id` de `SET LOCAL app.run_id`. Ventaja: captura también `core_*` y cualquier ruta futura sin tocar Python. Desventaja: lógica fuera del código, más difícil de testear con el resto de la suite y de versionar (el repo ya usa triggers solo para inmutabilidad de billing). Recomendación: A para el MVP, trigger solo si aparecen escritores adicionales.

Glosas: enganchar en `core_vp_etl._enrich_charges_with_rejections` (hoy actualiza `latest_rejection_*` sin historia) y en el equivalente de Toku/Payku/TCH, emitiendo `reason_changed` y alimentando `rejection_reason_catalog`. Requiere antes resolver la captura de glosa VP (SYNC-D-05).

TCH: el estado "rechazada -> aceptada" de una cuota hoy es una fila nueva con otro `dedupe_key`; para que el historial refleje una transición hay que resolver DEC-04 (clave de cuota sin `estado`) o derivar el evento comparando por `(ficha, periodo, cuota)`.

## 3. Resumen diario "qué cambió ayer"

**No existe.** Lo más cercano: `GET /sync-runs/health` (salud por canal), `GET /sync-runs` (50 filas con `records_processed`, que mezcla inserciones y reescrituras: no es un conteo de cambios), `/scheduler/runs` y la caché del dashboard (`invalidate_dashboard_cache` por webhooks). Los webhooks de Toku/VP/Payku se guardan en `stg_*_webhook_event` solo como aviso y no alimentan cambios.

Diseño propuesto (sobre `status_change_events`):
- `GET /api/v1/changes/daily?date=YYYY-MM-DD&source=` (permiso `dashboard.view`) con: totales por `event_kind`; matriz de transiciones `from -> to` por entidad y canal (p. ej. `pagado<-pendiente`, `ACTIVA->CANCELADA`); suscripciones nuevas/bajas; cambios de monto (con delta); nuevas glosas (del catálogo con `first_seen_at` en el día); y un top de glosas por frecuencia. Fecha por día **en hora de Chile** (convención ya usada en `monto_vigente`).
- Opcional: tabla `daily_change_summary(day, source, entity_type, event_kind, from_value, to_value, n)` poblada por un job a las 06:00 America/Santiago (después de la sync y del reintento) para lecturas baratas y consistentes; el endpoint cae a `GROUP BY` sobre eventos si falta.
- Frontend: tarjeta "Qué cambió ayer" en el dashboard y página de detalle con drill-down a la ficha (reutilizando listados por canal). Debe excluir `is_baseline`.

## 4. Fallos, reintentos, alertas, tiempos, concurrencia, observabilidad

| Aspecto | Estado actual | Riesgo |
|---|---|---|
| Programación | APScheduler en el **mismo proceso de la API** (`main.py` lifespan), jobstore en PostgreSQL, `coalesce=True`, `max_instances=1`, `misfire_grace_time=3600`, zona America/Santiago. Jobs: `sync_all_channels` 02:00; `billing_renewal_check` 03:00; `retry_failed_channels` 04:00; `billing_expire_requests` minuto 10 de cada hora; `billing_sweep_applying` cada 15 min. En sandbox solo con `SANDBOX_SCHEDULER_ENABLED` | Un reinicio de la API mata la sync en curso (12 `etl_runs` y 20+ `sync_runs` terminaron por "Servidor reiniciado"). Si el servidor está caído >1 h a las 02:00, la sync del día se pierde (misfire 3600 s) |
| Tiempos | Run diario 1,9-2,8 h (6.757 s a 10.174 s observados); dura más de 2 h porque consolida todo (TCH 1,47 M filas) y VP se consolida tres veces. Retry a las 04:00 Santiago (07:00 UTC) cae mientras la sync principal aún corre (inicia 05:00 UTC y termina ~07:00-07:50 UTC) => "run activo, omitiendo" o carrera | Ventana de datos obsoletos; sin deadline ni métrica de duración por canal (la fila de `sync_runs` sí guarda inicio/fin) |
| Fallos por canal | Cada canal en try/except; el fallo de uno no detiene a los demás; la consolidación corre igual. Run termina `completed` aun con canales fallidos (`channels_failed` lo marca; `error_message` resume) | El estado `completed` engaña; health usa `sync_runs` por fuente (correcto), pero el `EtlRun` no distingue parcial |
| Reintentos | (a) por request: 2 reintentos con backoff 2^n en timeouts/red (Toku además en 429/503); (b) por run: un único reintento a las 04:00 de los `channels_failed` del último run, que llama a `sync_all_channels(channels=...)` y **vuelve a consolidar todo** | Sin backoff/limitación ante 429 en VP/Payku; sin reintento si el fallo es de configuración (VP2 y Payku fallan idénticos cada día desde 10-27/28); no hay límite de reintentos ni escalamiento |
| Alertas | **No hay** (ni correo, ni Slack, ni webhook). Solo el indicador de salud del sidebar (ok <24 h, warn <72 h, error >=72 h o último run `failed` o `running` >72 h) con caché de 5 min | Un canal puede estar roto 3 días antes de pasar a `error` por antigüedad; el último `failed` sí pone `error` de inmediato, pero solo si alguien mira |
| Concurrencia | `sync_all_channels` revisa `EtlRun.status == 'running'` (SELECT sin lock => ventana TOCTOU), `/scheduler/jobs/{id}/run` también (409). `/etl/full-sync` y `/etl/core/*` **no verifican** runs activos. TCH `import_report` verifica. `max_instances=1` solo vale dentro de un proceso: con dos workers/instancias de uvicorn cada una agenda el job | Dos sync en paralelo pisándose (mismas tablas); un `running` abandonado bloquea la sync siguiente salvo reinicio (la limpieza de zombis solo ocurre en el arranque; billing sí usa expiración de 1 h) |
| Observabilidad | `sync_runs` por canal y `etl_runs` global; `records_processed` mezcla escrituras reales y reescrituras; logs de Python; SSE de progreso (`event_bus`) solo en memoria. `error_message` vacío en algunos fallos (7 de Payku, 1 de VP1) | Sin métricas (conteo de insertados/actualizados/sin cambio por recurso), sin id de correlación entre `sync_runs` y `etl_runs`, sin trazabilidad de qué cambió |
| Seguridad de datos | Sanitización y redacción de secretos/PAN en mensajes (`safe_error_message`), guardas de ambiente | Bien resuelto |

## 5. Fuentes que la API no cubre y cómo cubrirlas

| Hueco | Evidencia | Cobertura propuesta |
|---|---|---|
| Glosa/motivo de rechazo de VirtualPOS | 0/23.891 rechazos con código; listado de pagos sin `rejected_object`; vínculo pago->cargo vacío | (1) Fase inmediata: para pagos rechazados nuevos del día llamar `get_payment_attempts(payment_uuid)` con tope y espaciado (volumen diario bajo: decenas) y guardar `code/message` en una tabla de intentos; (2) fase histórica (~24 mil rechazos) con la misma llamada a ritmo controlado y reanudable por cursor de ID, tras **medir el rate limit en sandbox**; (3) alternativa: reporte descargado del Backoffice de VP (ver abajo) |
| Cobros de suscripciones canceladas (VirtualPOS) | Memoria del proyecto: la API devuelve 0 cobros para subs canceladas; medido hoy: las 2.049 subs CANCELADAS **sí** tienen cargos en `vp_charges` (pero `vp_payments` no se vincula a cargos: huérfanos `pay:`) | Reporte descargado de VP (pagos/cobros históricos por fecha) importado con el mismo patrón que Toku (`tk_report_*`): tabla `vp_report_*` + parser por firma de columnas + upsert idempotente con guarda de frescura, permiso propio y carga semanal por la UI. Reconciliar contra `vp_payments` por `payment_uuid`/orden y por (suscripción, fecha, monto) |
| Estado de suscripción/cliente y motivo (Toku) | La API no entrega estado de suscripción ni de cliente (handoff §7); `tk_subscriptions.status` solo tiene `ACTIVE`/`PAUSED`/nulo | Reportes de Toku (Deudas, Intentos, Productos, Inscripciones): TK-19 (ruta + panel) y TK-20 (señales a core); más reporte nuevo de Deudas (USR-09) |
| Histórico Toku 2020-2024 | Facturas desde 2024-08 y transacciones desde 2024-10 | Reportes descargados del Backoffice de Toku por rango de fechas; verificar con soporte si la API aplica retención (DEC-26) |
| Payku, transacciones fuera de las embebidas / glosas | Endpoint de transacciones con timeout en histórico; sandbox bloqueado | Usar `date_init/date_end` en ventanas semanales/mensuales reanudables (probar primero en una ventana pequeña), o reporte del Backoffice de Payku |
| TCH | Solo Excel | Carga semanal/diaria por la UI; definir si el Excel trae el estado de la cuota por periodo para derivar transiciones (DEC-04) |

Decisión necesaria del usuario sobre VP: qué reporte descargable existe en el Backoffice (nombre, columnas, frecuencia máxima) y si puede entregarse un ejemplar **sin datos personales** (solo encabezados) para diseñar el parser.

## 6. Tabla de brecha (caso de uso vs. estado actual)

| Requisito del caso de uso | Estado | Brecha |
|---|---|---|
| Sync diaria de VP, Toku, Payku | Existe (02:00, 1,9-2,8 h) | VP2 y Payku fallando por configuración; sin alerta; run reescribe todo |
| TCH por carga de Excel | Existe (incremental por archivo) | Sin trazabilidad a `source_records`; SYNC-GAP-02 abierta |
| Cobros que cambiaron de estado | No | Sin tabla de eventos; estado sobrescrito |
| Suscripciones que cambiaron de estado y a cuál | No | Idem |
| Nuevas glosas/motivos de rechazo | No (VP: 0 capturadas) | Catálogo de glosas y captura VP/Toku/Payku |
| Nuevas suscripciones y bajas | Parcial (se ven en listados) | Sin evento de alta/baja; sin detección por desaparición |
| Cambios de monto | No | `monto_vigente` VP existe pero sin historial |
| "Qué cambió ayer" en el dashboard | No | Endpoint y tarjeta |
| Carga histórica idempotente | Idempotente sí | Sin modo histórico |
| Carga histórica reanudable | No | Sin cursor/ventanas persistidos |
| VP desde 2025; Payku desde 2020 | Cubierto en datos (2025-02/04; 2020-08) | Sin garantía de completitud ni verificación |
| Toku desde 2020 | **No** (desde 2024-08/10) | Reportes de Toku o ventanas |
| TCH desde 2017 | Cubierto (2017-11) | Sin verificación de huecos |
| Fallos/alertas/bloqueo | Parcial | Alertas, lock atómico, `/etl/*` sin guarda, reintentos acotados |

## 7. Tareas priorizadas (familia SYNC-D-xx)

Orden sugerido: P0 (hacerlo ya, bajo costo) -> P1 (núcleo de detección) -> P2 (histórico) -> P3 (ampliaciones). Esfuerzos: S <= 3 h, M = 4-10 h, L > 10 h de IA.

| ID | Prioridad | Descripción | Archivos | Esf. | Riesgo | Decisiones del usuario |
|---|---|---|---|---|---|---|
| SYNC-D-01 | P1 | Tabla `status_change_events` + `rejection_reason_catalog` (modelos, migración, índices, `dedupe_key`). Sin migrar bases reales: lo aplica el usuario | `app/models/status_change.py`, `alembic/versions/*`, tests de migración | M | Medio (migración en `crm`: solo la aplica el usuario) | Retención de eventos (sugerido: indefinida) y si se incluye `payment` |
| SYNC-D-02 | P1 | Enganche idempotente en `_upsert_centralized`: diff previo por trozo, eventos `created/status_changed/amount_changed`, mismo SAVEPOINT, bandera `is_baseline`, tests (re-ejecución, A->B->A, fallo parcial) | `app/services/channel_consolidation.py`, `app/services/status_events.py` (nuevo), `tests/test_status_events.py` | L | Alto: toca el camino crítico de 1,7 M filas; riesgo de rendimiento (una SELECT extra por trozo) y de inundar eventos en la primera corrida | Confirmar opción A (Python) vs B (trigger); qué cambios de monto cuentan (cualquier delta o solo > umbral) |
| SYNC-D-03 | P1 | Corrida baseline: ejecutar la consolidación con `baseline=True` antes de activar eventos (sin generar novedades) y activar el flag en producción | `app/services/channel_consolidation.py`, script en `scripts/maintenance/` | S | Medio (escritura masiva; solo en `crm_sandbox` primero) | Autorización del usuario para producción |
| SYNC-D-04 | P1 | Endpoint `GET /api/v1/changes/daily` + (opcional) tabla `daily_change_summary` y job 06:00; tarjeta "Qué cambió ayer" y detalle en el dashboard | `app/api/v1/routes/changes.py`, `app/scheduler/engine.py`, `frontend/src/features/dashboard/*` | M | Bajo | Hora de corte (00:00-24:00 Chile) y qué canales/entidades se muestran por defecto |
| SYNC-D-05 | P1 | Captura de glosa VP: `get_payment_attempts` para pagos rechazados nuevos (diario, con tope y backoff) + backfill reanudable; vincular `core_charges.latest_rejection_*`; alimentar el catálogo | `app/services/virtualpos_sync.py`, `app/services/core_vp_etl.py`, `app/integrations/virtualpos/client.py` | L | Alto: rate limit no medido; riesgo de saturar la API | Medir rate limit en sandbox (prueba de contrato) y aprobar el tope diario |
| SYNC-D-06 | P0 | Lock atómico y un solo orquestador: `pg_try_advisory_lock` (o `INSERT` con índice único parcial `WHERE status='running'`) en `sync_all_channels`, `/etl/full-sync`, `/etl/core/*`, TCH import; expiración de `running` abandonados (como billing) | `app/scheduler/jobs/sync_all.py`, `app/api/v1/routes/etl.py`, `app/api/v1/routes/scheduler.py` | M | Medio | Ninguna |
| SYNC-D-07 | P0 | Dejar de consolidar de más: no consolidar VP dentro de `sync_virtualpos` cuando lo orquesta `sync_all`; consolidar solo canales con datos nuevos; consolidación incremental (solo filas cambiadas, p. ej. por `source_records`/`updated_at` de canal) y TCH solo tras una carga | `app/services/virtualpos_sync.py`, `app/scheduler/jobs/sync_all.py`, `app/services/channel_consolidation.py` | L | Alto (cambia el modelo de sobrescritura SYNC-GAP-05) | Aceptar que las canónicas dejan de reescribirse completas cada noche |
| SYNC-D-08 | P0 | Alertas: notificar (correo/Slack/webhook) cuando un canal falle, un run quede parcial, no haya run en 24 h o haya 2 fallos seguidos; usar `channels_failed` y `sync_runs` | `app/scheduler/alerts.py` (nuevo), `app/scheduler/jobs/sync_all.py` | M | Bajo (cuidar no enviar PII) | Canal de aviso y destinatarios |
| SYNC-D-09 | P0 | Corregir los fallos de configuración actuales de VP2 y Payku y distinguir error de configuración (no reintentar) de error transitorio; estado `partial` en `etl_runs` cuando hay canales fallidos | `app/scheduler/jobs/sync_all.py`, `app/scheduler/jobs/retry_failed.py`, `app/core/config.py` | S | Bajo | El usuario revisa sus variables de entorno (no se leyeron valores) |
| SYNC-D-10 | P1 | Reintentos más robustos: reintento de `retry_failed` desacoplado de la ventana (esperar a que termine la sync principal o mover a las 08:00), tope de intentos, backoff con `Retry-After` en VP y Payku, reintento de 5xx | `app/scheduler/engine.py`, `app/integrations/{virtualpos,payku,toku}/client.py` | M | Medio (GET con efectos: `retry_charge` sigue sin reintento) | Ninguna |
| SYNC-D-11 | P2 | Modo histórico reanudable: tabla `sync_cursors(source, resource, window_start, window_end, cursor, status, updated_at)`; VP por página/ID, Toku por `next_cursor` persistido, Payku por ventanas con `date_init/date_end`; comandos CLI `scripts/sync_history.py --channel --from --to --resume` | `app/models/sync_cursor.py`, `app/services/*_sync.py`, `scripts/sync_history.py` | L | Alto (carga larga contra APIs reales: solo con el usuario presente) | Rango por canal (VP 2025, Toku/Payku 2020), horario permitido y tope de peticiones |
| SYNC-D-12 | P2 | Verificación de completitud histórica: conteos por mes por canal vs. proveedor/Excel, informe de huecos (TCH 2017+, Payku 2020+, VP 2025+) | `scripts/diagnostics/`, `tests/` | M | Bajo | Fuente de verdad de los conteos (reportes del proveedor) |
| SYNC-D-13 | P2 | Detección de bajas por desaparición: columna `last_seen_sync_at`/`seen_in_run_id` en tablas de canal; evento `removed` solo tras sync completa y con umbral de seguridad | modelos `vp.py`/`toku_channel.py`/`payku_channel.py`, `channel_store.py`, migración | M | Medio (falsos positivos si una sync queda incompleta) | Qué hacer con registros que desaparecen (marcar baja o solo avisar) |
| SYNC-D-14 | P2 | Importador de reportes descargados para VirtualPOS (pagos y cobros de suscripciones canceladas, glosas) con el patrón de `toku_report_*` | `app/models/vp_report.py`, `app/services/vp_report_parser.py`, `.../vp_report_import.py`, ruta + panel | L | Medio (datos personales: solo hash/HMAC, nunca abrir el reporte real) | Qué reporte de VP existe, columnas, frecuencia, permiso y pepper |
| SYNC-D-15 | P2 | Cursor de Toku persistido y soporte de reportes para 2020-2024: reutilizar TK-19 a TK-22 | `app/integrations/toku/client.py`, `app/services/toku_report_import.py` | M | Medio | Confirmar con soporte de Toku la retención (DEC-26) |
| SYNC-D-16 | P3 | Unificar TCH: resolver DEC-04 (clave de cuota sin `estado`) para que rechazo -> pago sea una transición; `source_record_id` para TCH (backfill) | `scripts/etl_tch.py`, `app/models/tch.py`, migración | L | Alto (cambia `dedupe_key`, riesgo de duplicados) | **DEC-04** (decisión de negocio) |
| SYNC-D-17 | P3 | Observabilidad: columnas por recurso en `sync_runs` (inserted/updated/unchanged/duration), id de correlación `etl_run_id`, endpoint y panel de duración por fase, métricas | `app/models/sync_run.py`, `app/services/*_sync.py`, `sync_runs.py` | M | Bajo | Ninguna |
| SYNC-D-18 | P3 | Mover la sync fuera del proceso de la API (worker dedicado o job externo) para que un reinicio no la mate; reanudar al arrancar | `app/main.py`, `compose.yaml`, despliegue | L | Medio | Depende de DEC-11/DEC-12 (hosting) |
| SYNC-D-19 | P3 | Programar el ETL Core (`core_*_etl`) tras la consolidación y arreglar pagos `DO NOTHING` (actualizar estado de pago) | `app/scheduler/engine.py`, `app/services/core_*_etl.py` | M | Alto (ya hubo un incidente con core_charges) | Confirmar que Core pasa a ser fuente de lectura |

## 8. Orden de ejecución recomendado

1. P0 inmediato (sin migración): SYNC-D-09, SYNC-D-06, SYNC-D-08, SYNC-D-07.
2. Núcleo de detección: SYNC-D-01 -> SYNC-D-02 -> SYNC-D-03 -> SYNC-D-04 (primero en `crm_sandbox`; la migración en `crm` la aplica el usuario).
3. Glosas: SYNC-D-05 (tras medir el rate limit en sandbox).
4. Histórico: SYNC-D-11, SYNC-D-12, SYNC-D-15 y SYNC-D-14.
5. SYNC-D-10, SYNC-D-13, SYNC-D-16 a SYNC-D-19.

## 9. Decisiones que necesito del usuario

1. Opción A (diff en Python en la consolidación, recomendada) u opción B (trigger en PostgreSQL) para `status_change_events`.
2. Aceptar que la consolidación deje de reescribir todo cada noche (SYNC-D-07) y pase a ser incremental.
3. Canal y destinatarios de alertas (correo, Slack, webhook).
4. Rangos históricos exactos y ventana horaria permitida para cargas pesadas; tope de peticiones por minuto de cada API (medir en sandbox).
5. Reporte descargable de VirtualPOS: cuál usar y cómo compartir solo encabezados.
6. DEC-04 (TCH) para que rechazo -> pago sea una transición.
7. Qué hacer ante bajas por desaparición (marcar baja automática o solo avisar).
8. Hora de corte del resumen diario (hora de Chile) y retención de eventos.

## 10. Límites de esta auditoría

- No se ejecutó ninguna llamada a proveedores ni Alembic; no se leyó el `.env` (solo se infirió la causa de fallos de VP2/Payku por el texto del error registrado en `sync_runs`).
- Las duraciones salen de `sync_runs`/`etl_runs` de la base `crm` (agregados). La causa exacta de la diferencia en la duración entre canales no se desglosó por fase.
- La afirmación "la API devuelve 0 cobros para subs canceladas" (memoria del proyecto) no se pudo reproducir: en `vp_charges` las 2.049 suscripciones canceladas tienen cargos; el hueco medido es el vínculo pago->cargo y la glosa.
- Las tablas Core de Toku/Payku/TCH no se auditaron fila a fila.
