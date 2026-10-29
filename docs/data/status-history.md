# Historial de cambios de estado y monto (SYNC-D-01 a SYNC-D-04)

> Sprint 5A. Fuente: `app/models/status_change.py`, `app/services/status_events.py`, `app/services/status_history.py`,
> `app/api/v1/routes/changes.py`, migración `20261029_0042`. Diseño de origen: `docs/planning/auditoria-2026-10-29/` (informe de sincronización, §2 y §3).

## Para qué sirve

Hasta ahora las tablas centralizadas (`charges`, `subscriptions`, `payments`) guardaban solo el último estado: no se sabía **qué cambió ayer**.
Cada consolidación compara el valor que llega con el que ya estaba y deja un **evento** si hubo diferencia. Con eso se responde: qué pasó de
«pendiente» a «pagado», qué suscripciones se dieron de alta o de baja, qué montos cambiaron y qué glosas de rechazo aparecieron por primera vez.

Los eventos **no guardan datos personales**: solo ids externos del proveedor, estados, montos, fechas y glosas de rechazo.

## Modelo

### `status_change_events` (append-only)

| Columna | Detalle |
|---|---|
| `id` | uuid |
| `entity_type` | `charge`, `subscription`, `payment` o `client` (hoy se vigilan los tres primeros) |
| `source` | `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch` |
| `external_id` | clave externa de la fila centralizada |
| `subscription_external_id` | para agrupar por suscripción (en una suscripción es su propio id) |
| `event_kind` | `created`, `status_changed`, `amount_changed`, `reason_changed`, `removed` |
| `field` | `record` (alta), `status`, `amount`, `rejection_reason` |
| `from_value`, `to_value` | texto; `from_value` es NULL en `created` y `to_value` lleva el estado inicial |
| `amount` | monto vigente (contexto), `numeric(18,2)` |
| `provider_event_at` | reservado para la fecha que informe el proveedor (hoy NULL) |
| `detected_at` | momento en que la consolidación lo detectó |
| `run_id` | `etl_runs.id` de la corrida (NULL si se consolidó fuera del orquestador) |
| `is_baseline` | true = línea base: **no cuenta como novedad** |
| `dedupe_key` | `sha256(entidad|fuente|id|tipo|campo|from|to|corrida)`, UNIQUE |

Índices: `(detected_at)`, `(entity_type, source, external_id)`, `(event_kind, detected_at)` y parcial `(detected_at) WHERE is_baseline = false`.
Un trigger de base impide `UPDATE` y `DELETE` (mismo patrón que `billing_change_request_events`); la retención se hace con `TRUNCATE` o una
partición/purga administrada por el usuario.

### `rejection_reason_catalog`

`(source, code, reason)` único, con `first_seen_at`, `last_seen_at` y `occurrences`. Una glosa nueva en el catálogo genera un evento `reason_changed`.
`occurrences` cuenta los cobros nuevos o recién cambiados que traían esa glosa (no se infla al reconsolidar sin cambios).

## Enganche (decisión D7: en el código, no en un trigger)

`channel_consolidation._upsert_centralized`, por trozo de 2.000 filas y **antes** del `INSERT ... ON CONFLICT DO UPDATE`:

1. `SELECT external_id, status, amount FROM <tabla> WHERE source = :s AND external_id IN (...)` (índice único `(source, external_id)`).
2. Diff en Python (`status_events.build_events`): fila nueva = `created`; estado distinto = `status_changed`; monto distinto = `amount_changed`
   (se compara numéricamente: `5000` y `5000.00` son iguales); sin diferencia = sin evento.
3. `INSERT INTO status_change_events ... ON CONFLICT (dedupe_key) DO NOTHING` dentro de un SAVEPOINT propio.

Vigilado: `charges` (estado y monto), `subscriptions` (estado y monto), `payments` (estado). `clients`, `plans` y `payment_methods` no generan eventos.

- **Idempotencia:** reconsolidar sin cambios no genera eventos; repetir la misma corrida (mismo `run_id`) no duplica por `dedupe_key`. Una vuelta
  A→B→A genera eventos distintos (cambian `from/to` y la corrida).
- **Corrida:** `consolidate_to_centralized(..., run_id=...)`; el orquestador nocturno (`sync_all`) pasa el id de su `etl_run`. Sin `run_id` se usa un token
  propio de la llamada (los eventos quedan con `run_id` NULL).
- **Glosas:** un consolidador puede poner `_rejection_code` y `_rejection_reason` en la fila de `charges`; `_upsert_centralized` las quita antes del
  `INSERT` y alimenta el catálogo. Hoy solo TCH las informa (`codigo_respuesta`, `razon_rechazo`). VirtualPOS, Toku y Payku quedan para SYNC-D-05 y el ETL Core
  (`core_charges.latest_rejection_*`).
- **Fallo del historial:** si la tabla de eventos falla (p. ej. migración sin aplicar) se registra un aviso y la consolidación continúa igual. Interruptor:
  `STATUS_EVENTS_ENABLED=false`.
- **`removed`:** el tipo existe en el esquema, pero todavía no se emite (requiere marcar «visto en la corrida» para detectar desapariciones; SYNC-D-07).
- **Costo medido** (volumen sintético de 20.000 cobros, base local de pruebas): consolidar sin cambios pasa de 4,1 s a 5,1 s (+24 %); un lote donde todo es nuevo
  o cambia de estado pasa de 4 s a 10 s (por insertar 20.000 eventos). En la noche normal cambia una fracción mínima de filas, así que el costo esperado es el del diff.
  Sobre 1,7 M de filas, el diff añade del orden de 1,5 minutos a una corrida de 2 horas.

## Línea base (SYNC-D-03)

Si una tabla centralizada está vacía (instalación nueva) o se hace una carga histórica (p. ej. TCH completo), todas las filas serían «altas» del día. Para que no
inunden el resumen se marca la corrida como baseline:

- Parámetro: `consolidate_to_centralized(db, sources, run_id=..., baseline=True)`; o variable `STATUS_EVENTS_BASELINE=true` (el parámetro explícito manda).
- Comando manual, que ejecuta **el usuario**: `scripts/maintenance/consolidate_baseline.py`. Sin `--apply` es de solo lectura (muestra la base, conteos y eventos).
  Con `--apply` exige `--confirm-database <nombre exacto de la base actual>`. Consolidar **escribe** en las tablas centralizadas igual que la sincronización
  nocturna, por eso conviene respaldo previo y haber aplicado la migración `20261029_0042`.
- Los eventos baseline se guardan igual (sirven de historia) pero el endpoint diario los excluye.

Al desplegar sobre una base que ya tiene datos centralizados no hace falta baseline para las filas existentes: ya están y solo generan eventos las que cambien o lleguen
nuevas. Úsese baseline solo para cargas masivas de filas nuevas.

## Endpoint `GET /api/v1/changes/daily` (SYNC-D-04)

Permiso `dashboard.view`. Parámetros: `date` (`YYYY-MM-DD`, día calendario en hora de Chile; por defecto ayer), `source` (opcional), `entity_type` (opcional),
`limit` (1–500, por defecto 100; también topa las listas de glosas y el top de montos a 20) y `offset` (paginación de `transitions`). Excluye `is_baseline`.
Errores 422 con `detail={code, message}`. Contrato JSON:

```json
{
  "date": "2026-10-28",
  "timezone": "America/Santiago",
  "window": {"from": "2026-10-28T03:00:00+00:00", "to": "2026-10-29T03:00:00+00:00"},
  "filters": {"source": null, "entity_type": null},
  "totals": {"events": 16, "by_kind": {"amount_changed": 3, "created": 3, "reason_changed": 1, "removed": 1, "status_changed": 8}},
  "transitions": {
    "items": [{"entity_type": "charge", "source": "toku", "from": "UNPAID", "to": "PAID", "count": 3}],
    "total": 6, "limit": 100, "offset": 0
  },
  "created": [{"entity_type": "subscription", "source": "virtualpos1", "count": 2}],
  "subscriptions": {
    "altas": [{"entity_type": "subscription", "source": "virtualpos1", "count": 2}],
    "bajas": [{"source": "virtualpos1", "count": 1, "by_state": [{"state": "CANCELADA", "count": 1}]}]
  },
  "amount_changes": {
    "summary": [{"entity_type": "charge", "source": "toku", "count": 3, "increases": 1, "decreases": 1, "net_delta": 1000}],
    "top": [{"entity_type": "charge", "source": "toku", "external_id": "a1", "subscription_external_id": null, "from": "5000", "to": "7000", "delta": 2000}]
  },
  "new_reasons": {
    "items": [{"source": "tch", "reason": "Fondos insuficientes", "code": "51", "first_seen_at": "2026-10-28T15:00:00+00:00", "occurrences": 4}],
    "total": 1, "limit": 100
  }
}
```

Notas del contrato:
- `from`/`to` pueden ser `null`. `delta` y `net_delta` son `null`/ignorados cuando alguno de los dos valores no es numérico.
- **Bajas** = cambios de estado de suscripción hacia un estado de baja del canal (`BAJA_STATES` en `app/services/status_history.py`: VirtualPOS `cancelada`;
  Toku `cancelled`/`canceled`/`deleted`/`ended`; Payku `cancel`/`delete`/`suspended`, igual que el churn del dashboard; TCH `baja`) más los eventos `removed`. Una
  reactivación aparece en `transitions`, no en `bajas`. Ajustar esa tabla si aparecen otros estados.
- El día se calcula en `America/Santiago` (respeta el cambio de horario): `window` entrega los límites en UTC.
- Sin eventos el día devuelve ceros y listas vacías (no 404).

## Retención sugerida

Indefinida para `status_change_events` (cada fila pesa unos cientos de bytes; con cambios de decenas de miles al día son del orden de decenas de MB por mes). Si el
volumen molesta, conservar 24 meses y purgar con un `TRUNCATE`/partición por `detected_at` administrada por el usuario (el trigger impide `DELETE` fila a fila a propósito).
El catálogo de glosas no necesita purga.

## Pendientes relacionados

- SYNC-D-05: captura de glosa de VirtualPOS hecha en código (RJ-06, `docs/data/rejection-details.md`); emite `reason_changed` y alimenta el catálogo; detrás de `VP_REJECTION_CAPTURE_ENABLED` (apagada).
- SYNC-D-07: consolidación incremental y detección de desapariciones (`removed`).
- Frontend: tarjeta «Qué cambió ayer» sobre este contrato (lo hace otro frente).
- Tabla `daily_change_summary` y job de las 06:00: opcional, solo si el `GROUP BY` sobre eventos se vuelve lento.
