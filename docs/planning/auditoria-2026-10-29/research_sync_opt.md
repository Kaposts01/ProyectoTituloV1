# Investigación SYNC-O: sincronización incremental por niveles, modo histórico reanudable y scheduler

Fecha: 2026-10-29. Solo lectura (sin edición de código, sin Alembic, sin pytest, sin llamadas a proveedores). Mediciones con SELECT agregados sobre `crm` (scripts `so_m1.py` a `so_m6.py` en el scratchpad, sin datos personales ni valores del `.env`). Fuentes: `handoff.md` (secs. 2-3), `AGENTS.md`, `audit_sync.md`, `parity_*.md`, código de `app/scheduler`, `app/services/*_sync.py`, `channel_consolidation.py`, `app/integrations/*/client.py`, docs de `docs/integrations/{virtualpos,toku,payku}`.

Familia de IDs: **SYNC-O-xx** (optimización). Se apoya en las SYNC-D-xx de `audit_sync.md` (D-06 lock, D-07 consolidación incremental, D-08 alertas, D-09 config, D-10 reintentos, D-11 histórico, D-12 completitud, D-18 worker, D-19 ETL Core).

---

## 1. Medición: dónde se va el tiempo

### 1.1 Qué hay registrado y qué no
- `etl_runs` (una fila por corrida global): inicio, fin, estado, `phase` (se borra al terminar), `records_upserted`. **No guarda duración por fase.**
- `sync_runs` (una fila por canal y corrida): inicio, fin, `records_processed`. Para VirtualPOS **su duración incluye la consolidación de VP y `reconcile_charge_recoveries`** (se ejecutan dentro de `sync_virtualpos`). Toku, Payku y TCH no consolidan dentro.
- **No hay desglose por recurso** (cliente/pago/suscripción/cargo; factura/transacción) ni por función de consolidación (solo `logger.info` en texto, y los logs en disco no cubren las corridas nocturnas). No hay registro de la fase ETL Core.
- Por lo tanto la fase "consolidación final" se obtiene por resta: `fin del etl_run - fin del último sync_run` (columna `tail`), y los tiempos internos se **estiman por volumen** (marcado como [EST]).

### 1.2 Corridas completas recientes (todas las ventanas de canal OK, p. ej. 19-25 oct)
Duración total típica 10.060-10.545 s (2,8 h). Por canal (promedios de `sync_runs` completadas en 45 días y corridas del 19-26 oct):

| Canal | Duración típica | Filas en canal | Registros realmente cambiados por noche (`records_processed`) | Observación |
|---|---|---|---|---|
| Toku | **5.650-6.090 s** (prom. 4.502 con las fallidas) | ~67 mil (50.505 transacciones en `source_records`, 6.503 facturas, 2.431 pagos, 546 clientes, 518 suscripciones, 525 medios) | 0-1.436 (típico < 250) | Sin filtro de fecha; `sleep(1)` entre páginas de transacciones |
| VirtualPOS2 | **1.760-2.036 s** | 6.184 clientes, 50.037 pagos, 6.870 suscripciones, 204.589 cargos | 124-2.927 (salvo 124.450 el 21-oct) | Incluye 1 consolidación completa de VP |
| VirtualPOS1 | **560-590 s** | 2.033 clientes, 22.976 pagos, 2.144 suscripciones, 33.326 cargos | 50-1.060 | Incluye 1 consolidación completa de VP |
| Payku | **345-371 s** (hoy falla en 0 s) | 4.033 clientes, 5.700 suscripciones, 35.990 transacciones | 62-109 | |
| Consolidación final + resto | **1.633-1.731 s** (`tail`) | `charges` 1.715.019 (1.472.231 son TCH), `core_payments` 1.583.475 | n/a | Reescribe TCH, VP (3.ª vez), Toku, Payku y `materialize_core_clients` |
| ETL Core (`core_*_etl`) | **no corre en la noche** | manual: VP 108 s para 6.654 reg.; TCH 80-102 s por archivo (125-161 mil reg.) | | Fuera del scheduler |

Corridas de 6.757 s y 7.061 s (27-28 oct) = Toku 5.930 s + VP1 590-740 s + `tail` ~240 s, porque **VP2 y Payku fallan en 0 s** por configuración (SYNC-D-09). Cuando se arreglen, vuelven a ~10.100 s. El reintento de las 07:00 UTC (04:00 Chile) dura ~180 s y solo repite los fallos deterministas.

**Hallazgo central:** el 99,5 % del trabajo es redundante. Cada noche se leen ~460 mil registros de API y se reescriben ~1,9 M filas canónicas para detectar 50-3.000 cambios reales (`records_processed` solo cuenta payloads cambiados gracias a la guarda `IS DISTINCT FROM` de `source_records`, pero ninguna otra capa tiene esa guarda).

### 1.3 Cotas e inferencias por volumen [EST]
- Consolidación: rendimiento observado ≈ 1.900.000 filas / 1.650 s ≈ **1.150 filas/s** (confirmado por TCH import: ~1.500 filas/s en el ETL de archivo). Entonces: TCH 1,47 M ≈ **1.280 s**; VP (≈ 330 mil filas: 238 mil cargos + 73 mil pagos + 9 mil subs + 8 mil clientes) ≈ **290 s por pasada**; Toku+Payku ≈ 80 s. Suma ≈ 1.650 (calza con el `tail`). VP2 y VP1 aportan cada uno ~290 s dentro de su duración.
- Llamadas a API VP2: 62 (clientes) + 500 (pagos) + 69 (suscripciones) + 1 (planes) ≈ 632 llamadas en ~1.530 s (1.820 s menos ~290 s de consolidación) = **~2,4 s por llamada**. VP1: 20 + 230 + 21 = 271 llamadas en ~280 s (~1 s/llamada). **Los pagos son ~79 % de las llamadas de VP.** El tiempo por tipo de página no está medido: las páginas de suscripciones llevan `charge_program` embebido y probablemente son más pesadas, así que los pagos son entre 50 y 80 % del tiempo de API de VP.
- Toku: transacciones = 505 páginas (50.505/100) a 1 req/s mínimo; el resto ≈ 105 páginas de cursor/página. Con 5.800 s totales, el costo por llamada resulta ~8-9 s (red + latencia de Toku). **Transacciones ≈ 4.700 s (≈ 80-85 % de Toku)**; cota inferior teórica 505 s si el costo por llamada fuera solo el sleep. Esto debe confirmarse con SYNC-O-01.
- Escrituras de staging: `_store_records` ejecuta **un `INSERT ... ON CONFLICT` por registro** (≈ 330 mil sentencias por noche solo en VP) y `upsert_channel` hace upsert por lotes sin guarda de cambios. Probable aporte relevante (hipótesis, no medida) de 300-900 s en VP.

### 1.4 Los 5 mayores consumidores de tiempo (corrida completa de ~10.100 s)

| # | Consumidor | Tiempo | % | Naturaleza |
|---|---|---|---|---|
| 1 | Toku: transacciones sin ventana (505 págs. a 1 req/s + latencia) | ~4.700 s [EST] | ~47 % | Lectura repetida de todo el histórico, 0-3 cambios reales/hora |
| 2 | Consolidación TCH (1,47 M filas) cada noche | ~1.280 s [EST] | ~13 % | TCH solo cambia al subir un Excel (30 archivos en total) |
| 3 | VP2 pagos (500 págs.) + clientes (62) sin filtros de fecha | ~1.000-1.300 s [EST] | ~12 % | API admite `created_from/authorization_from` (documentado; falta probar) |
| 4 | VP consolidada 3 veces (2 dentro de `sync_virtualpos` + 1 final) | ~870 s (2 sobrantes: ~580 s) [EST] | ~9 % (6 % evitable) | Duplicación pura |
| 5 | VP1 pagos/clientes + Payku (suscripciones/clientes completos) + Toku no-transacciones | ~280 + ~350 + ~900 s | ~15 % (combinado) | Lectura completa de recursos que casi no cambian |

Los cinco juntos explican ~85 % del tiempo y **ninguno requiere hablar con más APIs: es lectura/escritura repetida**.

---

## 2. Estrategia de sincronización incremental por canal

### 2.1 Qué ofrece cada API (documentado vs observado)

| Canal | Filtros disponibles (fuente) | Estado de verificación |
|---|---|---|
| VirtualPOS `/v3/payments` | `status`, `created_from/to`, `authorization_from/to`, `merchant_internal_code` (`payments.md` l.870-875; workflows `sync-virtualpos.md` y `seguimiento-cobros.md` proponen ventana D-2…D) | Documentado; **no verificado en sandbox** (el repo hoy trae todo, `REVIEW.md` l.226). Ojo: `charge_date_from/to` de `/suscription/{id}/charges` resultó **ignorado** (DRIFT VP-C26), así que hay que probar estos antes de depender de ellos |
| VirtualPOS `/v3/clients` | `status`, `type`, `created_from/to`; sin `updated_from` | Documentado, no verificado |
| VirtualPOS `/v3/suscriptions` | `status` (SUSCRIBIENDO, SUSCRIPCION_FALLIDA, ACTIVA, CANCELADA, FINALIZADA), `page`, `limit`. **Sin filtro de fecha, ni por cobro, ni updated** | Documentado, no verificado |
| VirtualPOS detalle | `GET /v3/suscription/{id}` (con `charge_program`), `GET /v3/suscription/{id}/charges?status=` (el filtro de fecha se ignora), `GET /v3/payment/{uuid}`, `.../attempts` | Existen en el cliente |
| Toku `/transactions` | `start_date`, `end_date` (fecha de transacción; formatos `YYYY-MM-DD[ HH:MM:SS]`), `status`, `types`, `id_invoice`, `id_customer`; 1 req/s; por página | Documentado; **el cliente no los usa** (`list_transactions` solo manda `page`/`page_size`) |
| Toku `/invoices` | `start_date/end_date` (**creación**), `due_date`, `due_date_from`, `subscription_id`, `general_status` (varios), cursor | Documentado; el cliente solo usa `subscription_id`+`general_status` en una ruta de escritura |
| Toku customers/subscriptions | `start_date/end_date` (creación); **sin `updated_at` ni filtro de modificación** | Documentado |
| Payku `/api/transaction`, `/sususcriptionv3` | `date_init/date_end` (sin fecha → solo hoy), `per_page` hasta 4000, estados (`?active=true`, `?success=true`) | Documentado; el cliente ya los admite pero `sync_payku` no los usa; qué fecha filtra (creación, cambio) **no confirmado** |
| Payku `/api/sususcription` (v1, la que usa el sync) | filtro de fecha sin nombre documentado; estado `?<estado>=true` | Parcial |

Ninguna de las tres APIs ofrece "cambiado desde X": hay que cubrir con **ventanas de fecha de negocio + solape + reconciliación periódica**.

### 2.2 Idea del usuario (refrescar cada suscripción según su día de cobro) frente a los datos

Medición sobre `vp_charges` / `vp_subscriptions` (hoy 2026-10-29; estados: VP1 1.331 ACTIVA, 546 CANCELADA, 267 SUSCRIPCION_FALLIDA; VP2 4.750 / 1.503 / 617):

| Conjunto | Suscripciones |
|---|---|
| Total VP | 9.014 |
| ACTIVA | 6.081 (67 %) |
| Con un cobro programado en [hoy-5, hoy] | **1.921** (21 % del total; 32 % de las activas) |
| Con un cobro en [hoy-7, hoy] | 2.475 (27 %) |
| Con cobro `rechazado` en los últimos 30 días (reintentos) | 2.366 |
| Con cobro `pendiente`/`procesando` y fecha <= hoy | 3 |
| Cobros en [hoy-5, hoy]: pagado / rechazado | 345 / 939 (la tasa de rechazo es alta) |
| Cobros "cancelado" con fecha futura (hijos de subs canceladas o programas) | 150.343 (63 % de `vp_charges`; infla cualquier relectura) |

El día de cobro se reparte en todo el mes (200-680 cobros diarios; pico 23-25 con 1.037-1.320). Conclusión técnica clave:

1. **La API de VP no permite pedir "solo estas suscripciones" en lote.** El listado trae 100 suscripciones con su `charge_program` por llamada; el detalle `GET /v3/suscription/{id}` es 1 llamada por suscripción. Refrescar las 1.921 "calientes" una por una = 1.921 llamadas, **más que las ~90 páginas** que cuesta listar las 9.014. Por lo tanto la selección por día de cobro **no ahorra llamadas de suscripciones en VP**; sí sirve como (a) cadencia (cuándo vale la pena releer), (b) prioridad para el detalle individual cuando el conjunto es pequeño (< ~50 suscripciones: pendientes/procesando, reintento tras webhook, tras una escritura) y (c) criterio de consolidación (qué filas reescribir).
2. Lo que sí tiene filtro en VP es el **estado** de suscripción (`status=ACTIVA`: 61 páginas en vez de 90, -32 %; `CANCELADA|SUSCRIPCION_FALLIDA|FINALIZADA` son fríos) y los **pagos por fecha** (el 79 % de las llamadas). Ahí está el ahorro real.
3. En Toku y Payku la lógica "por día de cobro" se aplica nativamente con `due_date_from` (facturas) y ventanas `start_date/date_init` (transacciones).

### 2.3 Política de 3 niveles

Definiciones (hora de Chile). N = ventana de reintentos = **5 días** (parametrizable por canal: `SYNC_HOT_WINDOW_DAYS`).

| Nivel | Cadencia | VirtualPOS | Toku | Payku | TCH |
|---|---|---|---|---|---|
| **Caliente** | cada 3 h, 07:00-22:00 (6 corridas) | Pagos con `created_from = authorization_from = hoy-2` (≈ 2.000 pagos/7 días -> ~3-6 págs. por cuenta). 3 veces al día (p. ej. 09:00, 14:00, 20:00) además: suscripciones `status=ACTIVA|SUSCRIBIENDO` (≈ 62 págs.) para ver el estado de los cobros del día y de los últimos N días. Detalle por suscripción solo para la cola de eventos (webhook, post-escritura, `pendiente/procesando`) | Transacciones `start_date = hoy-2` (≈ 2-3 págs.); facturas `due_date_from = hoy-N` (≈ 101 facturas = 2 págs.); facturas `general_status=unpaid` solo 1×/día (ver tibia) | Transacciones `/api/transaction` con `date_init = hoy-N` (≈ 80 tx/7 días -> 1 pág.) si el piloto de semántica de fecha lo confirma; si no, suscripciones con estado activo | nada |
| **Tibia** | diaria, 05:00 | Pagos 7 días (solape); clientes `created_from = hoy-2`; suscripciones `ACTIVA|SUSCRIBIENDO`; consolidación diferencial | Transacciones 3 días; facturas `unpaid|partially_paid` (4.070 abiertas ≈ 41 págs.) + `due_date_from=hoy-7`; clientes y suscripciones `start_date = última_corrida-1d` (altas); pagos de organización | Suscripciones con estado activo (440 + pendientes de definir con `statuses.md`), transacciones ventana 7 días, clientes nuevos (`date_init`) | Consolidar **solo si** hubo carga de Excel (marca sucia) |
| **Fría** | semanal (domingo 01:00-06:00, con tope y reanudable) | Suscripciones `CANCELADA|SUSCRIPCION_FALLIDA|FINALIZADA`; clientes completos; pagos 90 días; reconciliación de conteos | Relectura completa de customers/subscriptions/payment-methods/payments/facturas; transacciones últimos 60 días (releer `INITIALIZED` → final) | Relectura completa (suscripciones, clientes, planes) | verificación de huecos por archivo (hash) |
| **Mensual** | 1.º de mes | Certificación de cobertura (SYNC-D-12) y verificación de conteos por mes contra reportes del proveedor | idem | idem + ventanas de 30 días de `/api/transaction` (donaciones puntuales, PK-PAR-09) | idem |

Cadencia con webhooks: los webhooks son un acelerador, no una garantía (Toku descarta eventos tras ~1 h 41 min y deshabilita; VP/Payku guardan el aviso sin refrescar nada). Mientras los webhooks no estén probados en producción, la cadencia caliente es la que da "datos al día". Si luego los webhooks demuestran fiabilidad (medir `webhook recibido vs cambio detectado por la corrida caliente`), la caliente puede bajar a cada 6 h; la tibia y la fría **se mantienen siempre**.

### 2.4 ¿Tabla `next_refresh_at` / `refresh_tier` por suscripción? Solución más simple
**No para la v1.** Razones: (a) la granularidad de las APIs es la página/recurso, no la suscripción; (b) el nivel de cada suscripción se puede **calcular al vuelo** desde datos ya en la base, sin estado extra que quede obsoleto; (c) menos migraciones.

Predicado de "suscripción caliente" (vista SQL `v_refresh_hot_subscriptions`, sin tabla nueva), por plataforma:
- `status IN ('ACTIVA','SUSCRIBIENDO')` y existe un `vp_charges` con `charge_date::date BETWEEN hoy-N AND hoy`, **o** un cargo `pendiente|procesando|rechazado` con `charge_date >= hoy-N`, **o** `updated_at` de la suscripción dentro de las últimas 48 h.
- Tibia: `ACTIVA` restante. Fría: `CANCELADA|SUSCRIPCION_FALLIDA|FINALIZADA`.
Esta vista sirve para: elegir qué suscripciones consolidar, qué detalle individual pedir (si < ~50), mostrar "frescura" en la UI y medir el tamaño de cada nivel.

Tablas mínimas que sí se necesitan (todas con migración que aplica el usuario):
1. `sync_cursors` (ver sec. 3): marcas de agua por (fuente, recurso, modo), incluida la marca "última consolidación" y la ventana histórica.
2. `refresh_queue` (opcional, solo para eventos): `(id, source, entity_type, external_id, reason[webhook|post_write|retry|manual], priority, not_before, attempts, state[pending|running|done|failed], created_at, finished_at)` con índice único parcial sobre `(source, entity_type, external_id) WHERE state IN ('pending','running')` para deduplicar. Se consume con detalle individual (`GET /v3/suscription/{id}`, `get_invoice`, `get_subscription`) y alimenta la consolidación diferencial.
3. Si más adelante el usuario quiere el modelo literal por suscripción: `subscription_refresh_state(source, external_id, refresh_tier, next_refresh_at, last_refreshed_at)`, calculado por un job desde la vista de arriba. Solo vale la pena cuando se consuma detalle individual masivo (hoy no conviene en VP; sí podría en Toku, donde `GET /invoices?subscription_id=` filtra por suscripción, pero con 499 activas el listado `unpaid` ya es más barato).

### 2.5 Consolidación por diferencias (sin triple pasada ni reescritura total)

Problema (verificado en código): `sync_virtualpos` llama `consolidate_to_centralized(db, ["virtualpos"])` al final de cada plataforma (consolida ambas cuentas), `sync_all_channels` vuelve a consolidar todo, y `_upsert_centralized`/`upsert_channel` hacen `ON CONFLICT DO UPDATE` sin guarda (cada fila se reescribe: WAL, bloat y tiempo).

Diseño por etapas:
1. **Una sola consolidación por corrida**: parámetro `consolidate: bool = True` en `sync_virtualpos`; el orquestador pasa `False` y consolida al final solo las fuentes con canal exitoso y con cambios (`records_processed > 0` o marca sucia). Ahorro ≈ 580 s. Sin migración.
2. **Guarda de cambio en los upserts**: `ON CONFLICT ... DO UPDATE ... WHERE (col1, col2, ...) IS DISTINCT FROM (excluded.col1, ...)` (o comparar un `payload_hash`). Reduce WAL/bloat y el costo de escritura; mantiene el `updated_at` útil para detectar cambios reales (hoy `updated_at` no se mueve en `charges` según medición, y D-02 de la auditoría necesita un valor fiable).
3. **Conjunto de cambios por marca de agua**: la tabla `source_records` ya registra `last_seen_at` **solo cuando el payload cambia** (la guarda existe). Con una marca `consolidated_through` en `sync_cursors` se consolidan únicamente los `external_id` con `last_seen_at > marca` (join por `(source, resource_type, external_id)`), con índice nuevo `(source, resource_type, last_seen_at)`. Alternativa sin índice: devolver los ids cambiados desde `_store_records` (ya los detecta con `RETURNING`) y pasarlos al consolidador; menos robusta ante fallos a mitad de corrida, por eso se prefiere la marca persistida.
4. **TCH**: nunca en la noche si no hubo carga (sec. 2.6).
5. La marca solo avanza tras una consolidación exitosa de esa fuente (idempotente y reanudable).

Esto además hace barata la consolidación en cada corrida caliente (segundos), requisito para "datos al día".

### 2.6 TCH: consolidar solo archivos nuevos
Datos: `tch_transacciones` 1.472.231 filas, **30 archivos distintos** (`archivo_origen`), los mayores 133-135 mil filas; el ETL de importación ya tarda 80-102 s por archivo y su `etl_run` registra ~125-161 mil registros (es decir, la importación ya deja los datos en las tablas TCH). La consolidación nocturna de 1,47 M filas (≈ 1.280 s) es redundante salvo que cambie el modelo de consolidación.
- **Medida mínima (S, sin migración):** el orquestador solo consolida TCH si existe un `etl_run` de importación TCH `completed` posterior a la última consolidación TCH exitosa (marca en `sync_cursors`, o mientras no exista la tabla: comparar `max(tch_transacciones.created_at)` con la última consolidación registrada en `etl_runs.channels_processed`).
- **Medida completa (M, migración):** tabla `tch_file_loads(file_sha256 PK, file_name, rows_loaded, loaded_at, consolidated_at NULL)`. La importación calcula el SHA-256 antes de procesar (rechaza/omite un archivo ya cargado, sin tocar `full`/`_clear_tch_data`), y la consolidación filtra `archivo_origen IN (archivos con consolidated_at NULL)` en vez de `OFFSET` sobre toda la tabla (el `offset(offset).limit(2000)` actual es O(n²) en el índice y es parte de los ~1.280 s). Ya hay una limitación conocida: `dedupe_key` incluye `estado` (SYNC-GAP-02/DEC-04), no la cambiamos aquí.

### 2.7 Resumen de reducción esperada (corrida diaria completa 10.100 s)

| Medida | Ahorro estimado | Quién |
|---|---|---|
| Toku: transacciones por ventana (+ resto con filtros) | -4.400 a -4.900 s | SYNC-O-02 |
| TCH solo tras carga | -1.280 s | SYNC-O-03 |
| VP: una sola consolidación | -580 s | SYNC-O-04 |
| VP: pagos y clientes por ventana | -900 a -1.300 s (si los filtros se respetan) | SYNC-O-05 |
| VP: suscripciones `ACTIVA` en caliente/tibia | -50 a -100 s por pasada, y la fría semanal | SYNC-O-05 |
| Payku: ventana + activas | -200 a -300 s | SYNC-O-06 |
| Consolidación diferencial (resto: VP, Toku, Payku) | -300 a -350 s, y deja el costo de una corrida caliente en segundos | SYNC-O-07 |
| Escritura por lotes en `_store_records` | hipótesis -300 a -900 s | SYNC-O-10 (tras medir) |

Resultado esperado: **tibia diaria ≈ 12-25 min** (vs. 1,9-2,8 h; el rango depende de la latencia real de Toku y de que VP respete los filtros), **caliente ≈ 1-3 min** (solo ventanas) y **≈ 5-8 min** en las 3 corridas que releen suscripciones VP, **fría semanal ≈ 1,0-1,5 h** (en ventana nocturna de domingo, reanudable). Carga diaria total de API ≈ 20-35 min repartidos frente a 2,8 h monolíticas, y la información de pagos/cobros pasa de "hasta 24 h de atraso" a "≤ 3 h" en los canales que lo permiten. Los valores son [EST]; **SYNC-O-01 y las pruebas de contrato de la sec. 5 deben validarlos antes de comprometer cifras.**

---

## 3. Modo histórico reanudable y cobertura a certificar

### 3.1 Tabla `sync_cursors` (migración; la aplica el usuario)
```
sync_cursors
  id uuid PK
  source        varchar(30)   -- virtualpos1|virtualpos2|toku|payku|tch
  resource      varchar(40)   -- payment|client|subscription|transaction|invoice|...
  mode          varchar(12)   -- history|hot|warm|cold|consolidate
  window_start  date null     -- ventana histórica [window_start, window_end]
  window_end    date null
  cursor        text null     -- next_cursor (Toku), página (VP/Payku) o id
  page          int null
  status        varchar(12)   -- pending|running|done|failed|paused
  records_seen  int, requests_made int
  last_success_at timestamptz null   -- marca de agua / "verificado hasta"
  last_error    text null (sanitizado)
  locked_by varchar(60) null, locked_until timestamptz null   -- heartbeat / lease
  updated_at timestamptz
  UNIQUE (source, resource, mode, window_start)
```
Cada ventana es una fila: el histórico es la lista de ventanas pendientes (p. ej. Payku 2020-08 → hoy en trozos de 30 días con 1 día de solape; VP pagos 2025-02 → hoy por semana; Toku transacciones por mes). El mismo mecanismo guarda las marcas de agua de los modos caliente/tibia/fría y de la consolidación (`mode='consolidate'`, `last_success_at`).

### 3.2 CLI `scripts/sync_history.py`
```
python scripts/sync_history.py --channel payku|virtualpos1|virtualpos2|toku \
   [--resource transaction] --from 2020-08-01 --to 2026-10-29 \
   --window-days 30 --resume --max-requests 2000 --max-minutes 240 \
   --window-hours 01:00-06:00 --sleep 1.0 --dry-run --plan
```
Reglas: (1) `--plan` imprime las ventanas y el número estimado de llamadas sin tocar la API; (2) `--resume` retoma la primera ventana `pending|failed|running` con lease vencido; (3) topes `--max-requests`, `--max-minutes` y ventana horaria (se detiene limpio y deja `paused`); (4) un lock por (fuente, recurso) con `pg_try_advisory_lock` + lease; (5) commit y actualización de cursor por página (como hoy, pero persistido); (6) backoff con `Retry-After` en 429/5xx; (7) respeta los entornos: `APP_ENV` antes de importar `settings` (regla 3 del handoff) y el CLI se niega a correr en producción sin `--i-know-this-is-production` (regla de oro del usuario); (8) solo lectura al proveedor; (9) nada de `full`/borrado; (10) emite un `sync_runs` por ventana (sin secretos).

### 3.3 Cobertura a certificar por canal (qué hay hoy y qué falta)

| Canal | Objetivo del usuario | Evidencia hoy | Cómo certificar | Brecha |
|---|---|---|---|---|
| **Toku** | 2020 en adelante | API: facturas desde `due_date` 2024-08-21, transacciones desde 2024-10 (4 en 2024-10, 162 en 2024-11: rampa de lanzamiento). **Los reportes del Backoffice tienen el mismo inicio**: Productos creados desde 2024-08-13, Intentos desde 2024-10-10, Métodos de pago desde 2024-10-09, depósitos desde 2024-10-17 (`parity_toku.md`). El conteo mensual de intentos API vs reporte coincide de 2024-10 a 2026-07 | **Es muy probable que Toku no tenga datos anteriores a 2024-08**: el "tope" de la API no es una retención sino el inicio de operación en Toku (la operación previa a esa fecha está en Payku desde 2020-08 y TCH desde 2017). Certificar con: conteo mensual API vs reporte (ya hecho) + respuesta del soporte (pregunta DEC-26) + sondeo de `GET /transactions?start_date=2020-01-01&end_date=2024-09-30` (1 llamada por mes, esperando 0 filas) y `GET /invoices?start_date=2020-01-01&end_date=2024-08-20` | Decisión del usuario: aceptar "Toku desde 2024-08" como cobertura completa. No hace falta construir cargas históricas ni TK-21/22 para 2020-2024 salvo que el soporte de Toku diga lo contrario |
| **VirtualPOS** | desde 2025 | Pagos: VP1 desde 2025-02-24, VP2 desde 2025-04-23; 238 mil cargos | Conteo mensual de pagos y cargos vs el reporte descargado del Backoffice (`parity_virtualpos.md`: vínculo pago-cobro y glosa solo en reporte); verificar que el primer pago de cada cuenta coincide con el primero del reporte | Sin vínculo pago→cargo (`charge_external_id` NULL), glosa de rechazo; los pagos por ventana (`created_from`) también permitirán recorrer 2025 con topes |
| **Payku** | desde 2020 | Suscripciones desde 2020-08-04; transacciones desde 2020-08-18 (35.969); **74 meses coinciden en cantidad y monto** con el reporte (cuotas exitosas) | Ya certificado para éxitos (PK-PAR-08 deja el script de conciliación mensual); rechazos (8.595), pendientes (356) y suscripciones no activas no certificables con reportes | Donaciones puntuales (10.186 filas / $486 M) fuera del CRM: requiere `/api/transaction` en ventanas de 30 días (PK-PAR-09) y la decisión de negocio |
| **TCH** | 2017 → hoy | 30 archivos, 1.472.231 filas, 2017-11 a 2026-09 | Tabla `tch_file_loads` con hash + conteo por archivo; informe de meses sin archivo | La mayoría de las filas (1,2 M) tiene `fecha_cargo` NULL (el periodo va en otras columnas): certificar por `periodo` |

---

## 4. Scheduler: dónde corre

Hoy: APScheduler en el proceso de la API (`main.py` lifespan) con `SQLAlchemyJobStore` en PostgreSQL, `max_instances=1` (solo vale dentro de un proceso), `misfire_grace_time=3600`, limpieza de zombis solo al arrancar. El backend local de producción se lanza con `--reload` (handoff sec. 3), que reinicia el proceso ante cualquier cambio de archivos. Evidencia: 12 de 99 `etl_runs` terminaron por "Servidor reiniciado".

| Opción | Cómo | Pros | Contras |
|---|---|---|---|
| A. Seguir en la API + advisory lock | `pg_try_advisory_lock(hash('sync:'||source))` en cada job, expiración de `running` abandonados | Cambio mínimo (S); arregla la duplicación con 2 workers (SYNC-D-06) | Un reinicio sigue matando la corrida; el hilo/event loop de la API comparte CPU con las peticiones de la UI; cargas largas bloquean el shutdown |
| **B. Worker separado (recomendada)** | Proceso propio `python -m app.scheduler.worker` (mismo código, mismo jobstore); la API arranca con `SCHEDULER_ENABLED=false` | Un reinicio de la API/`--reload` no toca la sync; permite múltiples workers de API; combinable con `sync_cursors` (el worker reanuda al arrancar); se puede escalar/aislar memoria; mismo `pg_advisory_lock` + lease como líder | Un servicio más que desplegar y vigilar (compose/servicio Windows/Railway); depende de DEC-11/DEC-12 (hosting); hay que mover las rutas "run now" a una tabla de órdenes (`sync_commands`) o seguir llamando al worker por BD |
| C. Cron externo del SO | Tarea programada de Windows o cron del host que ejecuta `scripts/sync_*.py --mode hot|warm|cold` | Sin proceso residente; aislamiento total; fácil de entender | Sin UI de estado en vivo (SSE) sin trabajo extra; el SO local debe estar encendido; cada ejecución arranca en frío; duplica scheduling con APScheduler (hay que apagar el de la API) |
| D. Cola (Celery/arq/RQ + Redis) | Tareas por recurso | Reintentos, concurrencia, prioridades | Redis/infraestructura nueva, demasiado para el volumen actual; AGENTS.md menciona Celery solo como tecnología consultable |

Recomendación: **A ya (SYNC-O-11, S) y B como destino (SYNC-O-12, L)**, con tres reglas comunes: lock advisory por (fuente, modo), `heartbeat`/lease en `sync_cursors` (un `running` sin latido > 10 min se marca `failed` y se reanuda), y que **el estado de reanudación lo dé `sync_cursors`**, no la memoria del proceso. Con B, el reinicio de la API deja de ser un riesgo; con A se mitiga solo el duplicado. El misfire de 3600 s se sustituye por "ejecutar al arrancar si la marca de agua está vencida" (la marca está en BD).

---

## 5. Pruebas de contrato antes de construir (solo sandbox, con el usuario)
1. VP `GET /v3/payments?created_from=...&created_to=...` y `authorization_from/to`: ¿respeta fechas? (el filtro de cargos fue ignorado). Medir también si cabe `limit` mayor y el rate limit (hoy solo se observaron 20 GET con pausa de 300 ms sin 429).
2. VP `GET /v3/suscriptions?status=ACTIVA`: ¿filtra? ¿incluye SUSCRIBIENDO por separado? ¿las páginas filtradas conservan `charge_program`?
3. VP `GET /v3/clients?created_from=...`.
4. Toku `GET /transactions?start_date&end_date`: ¿sobre `transaction_date` o `initialization_date`?, ¿cambian de `INITIALIZED` a final dentro de 48 h? (decide el solape); tiempo por página.
5. Payku `date_init/date_end` en `/api/transaction` y `/api/sususcription`: ¿sobre creación o último cambio?, ¿extremos inclusivos?, tamaño de ventana sin timeout (el docstring dice que el histórico hace timeout).
6. Toku `start_date=2020-01-01&end_date=2024-09-30` (esperado: vacío) para certificar el inicio de operación.
Cada prueba va como test de contrato con `CONTRACT_TESTS=1` y bandera de ambiente `sandbox`; Toku comparte host con producción (solo lectura).

---

## 6. Integración con webhooks (asumiendo que existirán)
- El webhook (`stg_*_webhook_event`) **no actualiza datos**: encola una orden en `refresh_queue` con `reason='webhook'` y el identificador del recurso; el worker hace el `GET` individual, hace upsert en canal y marca la fila sucia para la consolidación diferencial. Dedupe por clave única parcial. Respuesta 2xx inmediata al proveedor.
- La **reconciliación periódica no se reemplaza**: la corrida caliente (cada 3 h) sigue leyendo las ventanas; si encuentra cambios que no llegaron por webhook, registra una métrica `missed_webhook` por canal/recurso (diferencia entre lo detectado por ventana y lo que ya había llegado por evento). Esa métrica decide si se puede espaciar la caliente y alimenta SYNC-D-01/04 (resumen "qué cambió").
- Orden de precedencia: el dato más reciente por `last_seen_at` del canal; el evento no pisa un valor más nuevo (comparar `provider_event_at` cuando exista).
- Cada nivel expone `last_success_at` por (canal, recurso) en `/sync-runs/health` y en un indicador de frescura de la UI ("datos al día hace X min").

---

## 7. Tareas priorizadas

Esfuerzos: S ≤ 3 h, M = 4-10 h, L > 10 h. P0 = ya, sin migración y de alto retorno; P1 = núcleo de niveles; P2 = histórico, scheduler y webhooks; P3 = pulido. Reducción = sobre la corrida completa de ~10.100 s.

| ID | P | Descripción | Archivos | Esf. | Riesgo | Reducción esperada | Migración | Decisión del usuario |
|---|---|---|---|---|---|---|---|---|
| SYNC-O-01 | P0 | Instrumentación: cronometrar por recurso (clientes/pagos/suscripciones/cargos/facturas/transacciones), por función de consolidación y por fase ETL Core; guardar como JSON en una columna o tabla `sync_run_phases` y mostrar en `/sync-runs` | `app/services/{virtualpos,payku,read_only_provider}_sync.py`, `channel_consolidation.py`, `app/scheduler/jobs/sync_all.py`, `app/models/sync_run.py` | S | Bajo | 0 (habilita medir; valida el resto) | Opcional (`sync_run_phases` o columna JSONB); sin migración basta con log estructurado | Ninguna |
| SYNC-O-02 | P0 | Toku por ventana: `list_transactions(start_date, end_date)`, facturas `due_date_from` y `general_status`, clientes/suscripciones por `start_date`; modos `hot/warm/cold` en `sync_toku`; fría lee transacciones de 60 días y relectura completa semanal; `sleep(1)` solo en transacciones | `app/integrations/toku/client.py`, `app/services/toku_sync.py`, `read_only_provider_sync.py`, tests | M | Medio (la semántica de la fecha y los `INITIALIZED` obligan a solapar 48 h y a la relectura semanal) | -4.400 a -4.900 s (≈ -45 %) | No | Aprobar la prueba 4 de la sec. 5; solape (48 h) |
| SYNC-O-03 | P0 | TCH solo si hubo carga: el orquestador omite `tch` y su consolidación sin importación nueva; hacerlo configurable | `app/scheduler/jobs/sync_all.py`, `channel_consolidation.py` (`_consolidate_tch_*`) | S | Bajo | -1.280 s (≈ -13 %) | No (con `tch_file_loads`, ver O-08: sí) | Ninguna |
| SYNC-O-04 | P0 | Consolidar una sola vez: `sync_virtualpos(..., consolidate=False)` cuando lo llama el orquestador; consolidar solo fuentes con canal OK; no consolidar un canal fallido | `app/services/virtualpos_sync.py`, `app/scheduler/jobs/sync_all.py`, `retry_failed.py` | S | Bajo-medio (`reconcile_charge_recoveries` debe seguir corriendo tras la consolidación) | -580 s (≈ -6 %) | No | Ninguna |
| SYNC-O-05 | P1 | VP por ventana: pagos con `created_from`/`authorization_from`, clientes con `created_from`, suscripciones con `status=ACTIVA|SUSCRIBIENDO` en caliente/tibia y `CANCELADA|FALLIDA|FINALIZADA` en la fría; guardas si el filtro no se respeta (comparar `pagination.total`) | `app/integrations/virtualpos/client.py`, `app/services/virtualpos_sync.py` | M | Medio-alto (filtros no verificados; fallback automático a la lectura completa) | -900 a -1.400 s (≈ -10 a -14 %) | No | Aprobar pruebas 1-3 y topes de llamadas |
| SYNC-O-06 | P1 | Payku por ventana y por estado: usar `date_init/date_end` en transacciones y clientes, estados activos en tibia; completa en fría | `app/services/payku_sync.py`, `app/integrations/payku/client.py` | M | Medio (semántica de fecha no confirmada; timeouts históricos) | -200 a -300 s | No | Prueba 5; definir qué estados cuentan como "activos" (`register` 3.414, `suspended` 1.048) |
| SYNC-O-07 | P1 | Consolidación diferencial: marca de agua por fuente, filtro por `source_records.last_seen_at`, guarda `IS DISTINCT FROM` en `_upsert_centralized`/`upsert_channel`; la consolidación pasa a leer solo ids cambiados; pasa también a `charges` TCH por archivos nuevos | `app/services/channel_consolidation.py`, `channel_store.py`, `source_record.py` | L | Alto (cambia el modelo de sobrescritura SYNC-GAP-05; hay que probar idempotencia y una corrida de comparación completa vs diferencial) | -300 a -350 s y deja la corrida caliente en segundos | Índice `(source, resource_type, last_seen_at)` en `source_records` (migración) | Aceptar que las canónicas dejan de reescribirse completas (= SYNC-D-07) |
| SYNC-O-08 | P1 | `sync_cursors` + `tch_file_loads` (hash por archivo); marcas de agua y `last_success_at` por (fuente, recurso, modo); expuesto en `/sync-runs/health` | `app/models/sync_cursor.py`, `app/models/tch.py`, `scripts/etl_tch.py`, migración | M | Medio (migración en `crm` solo la aplica el usuario) | Habilita O-03 completo, O-07, O-09, O-13 | **Sí** (`sync_cursors`, `tch_file_loads`) | Retención de cursores; hash como bloqueo duro o solo aviso |
| SYNC-O-09 | P1 | Corredor por niveles: jobs `sync_hot` (cada 3 h, 07-22), `sync_warm` (05:00) y `sync_cold` (domingo 01:00); vista SQL `v_refresh_hot_subscriptions`; ventana N configurable por canal | `app/scheduler/engine.py`, `app/scheduler/jobs/sync_tiers.py` (nuevo), `app/core/config.py`, vista (migración) | M | Medio (cuidar el solape con billing y el reintento; lock por canal) | Pasa de 1 corrida de 2,8 h a corridas de 1-25 min; datos ≤ 3 h | Vista opcional (migración) | Cadencia caliente (3 h o 6 h), horas, N=5 |
| SYNC-O-10 | P2 | Escritura en lotes en `_store_records` (hoy 1 INSERT por registro) usando `executemany`/`unnest` con la misma guarda; medir antes con O-01 | `app/services/virtualpos_sync.py`, `read_only_provider_sync.py` | M | Medio | hipótesis -300 a -900 s (VP) | No | Ninguna |
| SYNC-O-11 | P0 | Lock atómico y expiración de `running` abandonados (advisory lock por fuente/modo; `/etl/*` y TCH import con guarda) = SYNC-D-06 | `sync_all.py`, `routes/etl.py`, `routes/scheduler.py` | S-M | Medio | Evita corridas duplicadas (2 workers) | No | Ninguna |
| SYNC-O-12 | P2 | Worker separado con líder por advisory lock, lease/heartbeat y reanudación al arrancar; API con `SCHEDULER_ENABLED=false`; tabla de órdenes para "ejecutar ahora" | `app/scheduler/worker.py` (nuevo), `app/main.py`, `compose.yaml`/despliegue, `routes/scheduler.py` | L | Medio (depende de DEC-11/12) | Elimina las corridas matadas por reinicio | Posible `sync_commands` (migración) | Elegir A/B/C/D (sec. 4) |
| SYNC-O-13 | P2 | Modo histórico: `scripts/sync_history.py` (--plan, --resume, topes, ventana horaria) sobre `sync_cursors`; ventanas Payku 30 días, VP pagos semanales, Toku transacciones mensuales | `scripts/sync_history.py`, `app/services/sync_history.py`, clientes de los tres canales | L | Alto (carga larga contra APIs reales: solo con el usuario presente; sandbox primero) | Cobertura, no tiempo (amplía SYNC-D-11) | Usa O-08 | Rangos, horario permitido, tope de peticiones por minuto de cada API (medir) |
| SYNC-O-14 | P2 | Certificación de cobertura: informe mensual por canal (conteos y montos vs reportes), sondeo Toku 2020-2024 y TCH por archivo/periodo; script de solo lectura = SYNC-D-12 + PK-PAR-08 | `scripts/diagnostics/`, `docs/integrations/*` | M | Bajo | n/a | No | Aceptar "Toku desde 2024-08" si el sondeo y el soporte lo confirman |
| SYNC-O-15 | P2 | `refresh_queue` + consumidor de webhooks (re-fetch individual, dedupe, `missed_webhook`) | `app/models/refresh_queue.py`, `app/services/webhook_refresh.py`, rutas de webhooks | L | Medio (depende de la otra investigación de webhooks) | Frescura casi inmediata en los eventos cubiertos | **Sí** (`refresh_queue`) | Qué eventos disparan refresco; cadencia caliente al activarlos |
| SYNC-O-16 | P2 | Programar el ETL Core tras la consolidación, solo para fuentes con cambios, y actualizar pagos existentes (hoy `DO NOTHING`) = SYNC-D-19 | `engine.py`, `core_*_etl.py` | M | Alto (incidente previo de `core_charges`) | Core al día sin pasadas manuales (+1-2 min por pasada) | No | Confirmar que Core pasa a ser fuente de lectura |
| SYNC-O-17 | P3 | Alertas, reintentos con `Retry-After`, estado `partial` y corrección de VP2/Payku (SYNC-D-08/09/10), prerequisitos de la política de niveles | ver SYNC-D-08/09/10 | M | Bajo | Evita corridas de 0 s que fallan en silencio | No | Canal y destinatarios de alertas |

### Orden recomendado
1. Hoy, sin migración: SYNC-O-17 (arreglar VP2/Payku), SYNC-O-11, SYNC-O-03, SYNC-O-04, SYNC-O-01.
2. Probar contrato en sandbox (sec. 5) y construir SYNC-O-02, SYNC-O-05, SYNC-O-06: se llega a ~25-35 min diarios sin migraciones.
3. Con migración aplicada por el usuario: SYNC-O-08 → SYNC-O-07 → SYNC-O-09 (niveles caliente/tibia/fría).
4. Scheduler y histórico: SYNC-O-12, SYNC-O-13, SYNC-O-14, SYNC-O-15, SYNC-O-16, SYNC-O-10.

## 8. Decisiones que necesito del usuario
1. **Toku 2020**: aceptar que Toku empieza en 2024-08 (la evidencia de API y reportes coincide) y cerrar la cobertura con el sondeo + pregunta al soporte (DEC-26); alternativa: pedir al soporte una exportación anterior.
2. Cadencia caliente: cada 3 h (recomendada) o 6 h; horas de operación (07-22) y N de ventana de reintentos (5 días recomendado).
3. Suscripciones VP en caliente: 3 veces al día (recomendada) o en cada corrida caliente (más fresco, +150-300 s por corrida).
4. Aprobar las pruebas de contrato de la sec. 5 (solo sandbox; Toku es solo lectura contra el host compartido) y el tope de llamadas por minuto de cada API.
5. Scheduler: A (lock en la API), B (worker, recomendada) o C (cron del SO); depende de DEC-11/12 (hosting).
6. Aceptar la consolidación diferencial (las canónicas ya no se reescriben cada noche) y la migración de `sync_cursors`/`tch_file_loads`/índice de `source_records`, que aplica el usuario.
7. Hash por archivo TCH: bloquear duplicados o solo avisar; DEC-04 sigue pendiente.
8. Qué estados de Payku cuentan como activos (`register`, `suspended`) para la tibia.
9. Ventana nocturna permitida para la fría y el histórico.

## 9. Límites de este informe
- No se llamó a ningún proveedor ni se ejecutó Alembic/pytest; no se leyeron valores del `.env`. Todas las cifras de duración salen de `sync_runs`/`etl_runs` de `crm`; las marcadas [EST] son inferencias por volumen y deben validarse con SYNC-O-01.
- Los filtros de fecha de VP (pagos, clientes), el filtro `status` de suscripciones, la semántica de `start_date` de Toku y de `date_init` de Payku están documentados pero **no verificados**; el único filtro de VP probado (cargos) fue ignorado por la API.
- La causa de que Toku tarde ~8-9 s por llamada no está medida (podría ser latencia del proveedor, el `sleep(1)` y el procesamiento por página).
- Se asume que la importación TCH ya deja los datos disponibles sin la consolidación nocturna; debe confirmarse comparando `charges` vs `tch_transacciones` tras una carga antes de apagar la pasada (O-03).
