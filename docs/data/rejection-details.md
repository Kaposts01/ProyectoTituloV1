# Glosa de rechazo por cobro y canal (RJ-12, RJ-06, RJ-15)

> Sprint 5A. Fuente: `app/models/rejection.py`, `app/services/vp_rejection_capture.py`, `app/services/core_vp_etl.py`,
> `app/services/toku_failed_payments.py`, migración `20261029_0043`. Investigación de origen: `docs/planning/auditoria-2026-10-29/`.

## Tabla `payment_rejection_details` (decisión D3: tabla única)

Lugar de **paso** para la glosa: los `raw_payload` de `vp_*`, `tk_*` y `p_*` se reemplazan en cada sync, así que la glosa capturada vive aquí y el ETL
Core la proyecta a `core_payments.rejection_*` y `core_charges.latest_rejection_*`. Sin datos personales.

| Columna | Detalle |
|---|---|
| `source` | `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch` |
| `charge_external_id`, `payment_external_id`, `subscription_external_id` | ids del proveedor; al menos uno de cobro/pago |
| `code`, `reason` | código y glosa tal como los informa el proveedor (`''` = **marcador**: consultado, sin glosa) |
| `acquirer_code` | código del adquirente (VirtualPOS `-2xxx`) cuando aplica |
| `doc_url`, `amount`, `rejected_at` | enlace de la documentación, monto normalizado, fecha del rechazo |
| `capture_source` | `api_charges`, `api_payment`, `report_pat`, `toku_projection` |
| `captured_at`, `checked_at` | cuándo se guardó y cuándo se consultó por última vez |

Unicidad `uq_prd_dedupe`: `(source, coalesce(charge_external_id,''), coalesce(payment_external_id,''), code)`. Índices por cobro, pago, suscripción y `checked_at`.

## Captura diaria de VirtualPOS (RJ-06)

Medido en producción: `GET /v3/suscription/{id}/charges?status=rechazado` trae por cobro `rejected_object {code,message,doc_url}` y `payment.order.uuid`
(`order.amount` es str en cobros e int en el detalle del pago). Una petición por suscripción da la glosa y el vínculo cobro→pago.

- Bandera `VP_REJECTION_CAPTURE_ENABLED` (**apagada por defecto**). Se ejecuta en `sync_all_channels` después de sincronizar VirtualPOS y **antes** de consolidar.
  Un fallo de la captura se registra en las métricas de la corrida y no cambia el estado del run.
- Candidatas: suscripciones con cobros `rechazado` locales sin detalle (o con solo un marcador de más de `VP_REJECTION_CAPTURE_RECHECK_DAYS`, 30 por defecto),
  las más recientes primero, hasta `VP_REJECTION_CAPTURE_MAX_SUBSCRIPTIONS` (500) por cuenta y por corrida.
- Pausa `VP_REJECTION_CAPTURE_PAUSE_SECONDS` (0,3 s) entre peticiones; backoff exponencial ante 429/5xx (respeta `Retry-After`, `VP_REJECTION_CAPTURE_MAX_RETRIES`=3).
  Un 429 persistente corta la corrida; un 5xx persistente falla solo esa suscripción; 10 fallos seguidos cortan la corrida.
- Commit por suscripción (un fallo parcial no pierde lo ya guardado). Cobros rechazados en local que la API no devuelve (p. ej. suscripción cancelada) reciben un marcador.
- `message` se guarda en UTF-8 (se repara el mojibake) y sin secuencias de 12 a 19 dígitos.
- Glosa nueva → fila en `rejection_reason_catalog` y evento `reason_changed` (`status_events.emit_reason_events`), con el `run_id` de la corrida.
- Vínculo pago→cobro: `UPDATE` explícito e idempotente de `vp_payments.charge_external_id` y `core_payments.charge_id` (solo donde están NULL). Desde VP-PAR-06 el sync
  nocturno ya no reescribe `vp_payments.charge_external_id` a NULL; el vínculo se rehace igual en cada corrida de captura y en el ETL Core
  (detalles, reporte PAT y cobros con `payment.order.uuid`), para los pagos que llegan después.
- ETL Core (`run_vp_core_etl`): `_enrich_charges_with_rejections` y `_enrich_payments_with_rejections` leen también `payment_rejection_details`. Si la tabla no existe
  (migración sin aplicar) se omite con un aviso.
- Histórico: lo cubrirá el importador de reportes PAT (RJ-04, decisión D6) con `capture_source = 'report_pat'`. Sin él, el backfill por API toma ~8 días a 500 suscripciones diarias (3.759 con rechazos).

## Intentos FAILED de Toku como `core_payments` (RJ-15, decisión D4)

Ver `app/services/toku_failed_payments.py`. Bandera `TOKU_MATERIALIZE_FAILED_PAYMENTS` (**apagada por defecto**), invocada desde `run_toku_core_etl`, y script manual
`scripts/maintenance/materialize_toku_failed_payments.py` (dry-run por defecto; `--apply` lo ejecuta el usuario).

- Cada `tk_transactions` FAILED con factura conocida genera un `core_payments` (`source='toku'`, `external_id` = id de la transacción, `source_status='FAILED'`,
  `rejection_*` desde la misma proyección de RJ-01, `charge_id`/`subscription_id` por la factura). `ON CONFLICT` actualiza **solo** filas propias (`source_status='FAILED'`).
- **Los KPIs no cambian:** ningún dashboard, `charge_stats` ni la recuperación lee `core_payments` (las tarjetas leen `charges`/`payments` centralizados y `source_records`).
  Un test fija esa garantía (cifras de Toku idénticas antes y después, y un guardián que falla si aparece un lector nuevo de `core_payments` sin revisar).
  Quien lea `core_payments` en el futuro debe excluir `source_status = 'FAILED'` para contar solo pagos efectivos.
