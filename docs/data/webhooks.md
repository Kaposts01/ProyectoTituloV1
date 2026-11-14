# Webhooks y tiempo casi real (RT-04 a RT-08, RT-05, RT-06, RT-07)

> Sprint 5. Código: `app/api/v1/routes/webhooks_{toku,virtualpos,payku}.py`, `app/services/webhook_intake.py`,
> `app/services/webhook_processor.py`, `app/services/targeted_reconcile.py`, `app/models/webhook_event.py`,
> migración `20261029_0049`. Investigación de origen: `research_realtime.md` de la sesión (proveedores, matriz canal × evento).
> **Estado: el código está listo y probado con fakes. No hay ningún webhook creado en ningún proveedor ni nada expuesto a internet.**

## Flujo

```
Proveedor --POST--> receptor (FastAPI) --> webhook_events (pending) --> procesador (job, cada minuto)
                                                                              |
                          status_change_events <-- consolidación de ESA suscripción <-- refresh_subscription (MGT-06, solo GET)
```

1. **Recepción** (`/api/v1/webhooks/toku`, `/virtualpos/{payment|subscription|charge_paid|charge_reject|card_change|payout}`, `/payku/{kind}`). El receptor solo valida y
   encola; no llama al proveedor ni consolida. Orden: rate limit → (secreto/token/firma) → tope de body → JSON (VirtualPOS acepta también `application/x-www-form-urlencoded`, que usan algunos envíos PAT) → `INSERT … ON CONFLICT DO NOTHING`
   en `webhook_events` → `200 {"status":"ok"}`. Los duplicados también responden 200.
2. **Cola** `webhook_events`: `status` = `pending | processing | done | failed | ignored`, `attempts`, `next_attempt_at`, `locked_at`,
   `last_error_code` (código fijo, nunca texto del proveedor), `received_at`, `processed_at`, `payload_masked` (sin datos personales),
   `dedupe_key` UNIQUE.
3. **Procesador** (`process_webhook_queue`, job cada minuto, detrás de `WEBHOOK_PROCESSOR_ENABLED`). Reclama un lote con
   `SELECT … FOR UPDATE SKIP LOCKED` y lo marca `processing` (dos workers nunca toman el mismo evento), decide la suscripción afectada por
   reglas de evento y llama a `refresh_subscription` **solo para esa suscripción**. Varios eventos de una misma suscripción en un lote comparten un solo refresh.
4. **`refresh_subscription`** relee por GET suscripción y cobros, actualiza canal + `source_records` + centralizadas de ese registro y
   alimenta `status_change_events` (altas, bajas, cambios de estado/monto) con un `run_id` propio de la operación. Es idempotente:
   reprocesar con el mismo estado remoto no genera eventos nuevos.
5. **Cierre**: `done`, `ignored` o reintento con backoff; al terminar eventos `done` se invalida la caché del dashboard.

**El contenido de un webhook nunca se aplica.** Solo sirve para saber qué recurso mirar; el dato real siempre se relee por API.

## Idempotencia (`dedupe_key`)

| Canal | Clave |
|---|---|
| Toku | `sha256("toku" \| id del evento)` (el id `wheve_…` es único por evento; los reintentos de Toku repiten el id) |
| VirtualPOS, Payku | `sha256(canal \| kind \| id del recurso \| status \| ventana de 5 min)` (no mandan id de evento: los reenvíos del mismo aviso dentro de 5 min colapsan en una fila; es seguro porque el procesador relee por API) |

No se agregó UNIQUE a `stg_vpos_webhook_events` ni `stg_payku_webhook_events`: no tienen id de evento y pueden tener duplicados previos
(un índice único podría fallar al aplicarse sobre `crm`). Los receptores **dejaron de escribir** las tres tablas `stg_*_webhook_events`; quedan como histórico
sin cambios (se pueden retirar en una migración futura cuando el usuario lo decida).

## Reglas por evento (RT-07)

| Canal | Evento | Acción |
|---|---|---|
| Toku | `subscription.created`, `.updated`, `.cancelled` | refresh de la suscripción (`subscription.id`) |
| Toku | `subscription.deleted` | refresh; **se trata como baja**: si el proveedor ya no devuelve la suscripción (HTTP 404) se marca `deleted` y se registra el evento de cambio (idempotente). Un fallo transitorio no marca nada: se reintenta |
| Toku | `invoice.paid`, `.voided`, `.updated`, `.created` | suscripción de la factura (del payload o de `tk_invoices`) |
| Toku | `transaction.success`, `.failed`, `.status_update` | suscripción nombrada en el payload; si no, vía factura, o vía medio de pago → cliente → sus suscripciones |
| Toku | `payment_method.*` | todas las suscripciones del cliente dueño del medio de pago (máx. 10) |
| Toku | `transaction.bulk_*`, `invoice.bulk_*` | `ignored` (`BULK_EVENT`): los cubre la conciliación |
| Toku | cualquier otro (`customer.*`, …) | `ignored` (`UNKNOWN_EVENT`) |
| VirtualPOS | `payment` (`uuid`) | suscripción del pago/cobro local (`vp_payments` → `vp_charges`); define la plataforma (`virtualpos1/2`) |
| VirtualPOS | `subscription` (callback de inscripción `{uuid}` o cuerpo POS `{status,code,suscription:{uuid}}`) | esa suscripción si ya existe en `vp_subscriptions` |
| VirtualPOS | `charge_paid`, `charge_reject` (eventos PAT del Portal Comercio; cuerpo con `id` del cargo y `suscription_uuid`) | la suscripción si ya existe en `vp_subscriptions`, y/o la del cargo en `vp_charges`. Del cuerpo (trae cliente y pago) solo se guardan ids y estado |
| VirtualPOS | `card_change` (evento PAT, `{uuid}` de la suscripción) | esa suscripción si ya existe en `vp_subscriptions` |
| VirtualPOS | `payout` | `ignored` (`IGNORED_KIND`); se valida firma y se guarda, pero no dispara refresh |
| Payku | `subscription` | refresh de esa suscripción (no exige fila local: sirve para altas) |
| Payku | `payment`, `transaction`, `nullification` | suscripción del payload (`subscriptions.id`) o de `p_transactions` |
| Payku | `payout` | `ignored` (`IGNORED_KIND`) |

Sin recurso resoluble: `ignored` con `NO_RESOURCE` (p. ej. un pago VirtualPOS que aún no existe localmente: lo cubre la conciliación o la sync diaria).
Códigos fijos: `NO_RESOURCE`, `UNKNOWN_EVENT`, `BULK_EVENT`, `IGNORED_KIND`, `UNEXPECTED`, `STALE_PROCESSING` y los de `RefreshError`
(`PROVIDER_READ_FAILED`, `EMPTY_SUBSCRIPTION`, `LOCAL_WRITE_FAILED`, `CONSOLIDATION_FAILED`, `UNSUPPORTED_SOURCE`).

### Reintentos

Backoff exponencial `base × 2^(intentos−1)` con base `WEBHOOK_BACKOFF_BASE_SECONDS` (30 s) y tope 1 h: 30 s, 1, 2, 4 min y, al quinto intento fallido
(`WEBHOOK_MAX_ATTEMPTS`=5), `failed` con el código del último error. Un evento `processing` abandonado (proceso caído, `WEBHOOK_PROCESSING_STALE_MINUTES`=10)
vuelve a `pending`, o a `failed` (`STALE_PROCESSING`) si ya agotó los intentos. Un evento con varios objetivos queda `done` solo si todos salieron bien.
Reproceso manual y panel (RT-14): ver «Panel de salud y reproceso» más abajo.

## Panel de salud y reproceso (RT-14)

En **Administración → Sincronización** (sección «Salud de webhooks», ancla `#webhooks`), solo para el permiso **`webhooks.manage`** (de administración: soporte y ejecutivo
no lo heredan; sin migración, lo crea `seed_permissions` al correr `scripts/bootstrap_admin.py` o `scripts/maintenance/seed_roles.py`, y queda en el rol `admin`).

- `GET /api/v1/admin/webhooks/health`: por canal, conteos por estado, demora del pendiente más antiguo (`pending_lag_minutes`), último recibido, procesados en 24 h y su demora media/máxima; códigos de error de 24 h; si el procesador está encendido.
- `GET /api/v1/admin/webhooks/events?status=failed&source=&limit=`: lista sin payload ni ids de recurso (id interno, canal, tipo, estado, intentos, código, fechas).
- `POST /api/v1/admin/webhooks/requeue` (CSRF): `{"ids": [...]}` reencola `failed`/`ignored` por id; `{"all_failed": true, "source": "toku"}` reencola todos los `failed` (los `ignored` solo por id).
  El evento vuelve a `pending` con `attempts=0`. Es seguro: el procesador siempre relee al proveedor (`app/services/webhook_processor.requeue_events`).

## Alertas de webhooks (RT-13)

Sobre el chequeo de alertas de SYNC-D-08 (`app/services/alerts.py`, ver `docs/data/alerts.md`), **apagadas** mientras no estén `ALERTS_ENABLED`, `ALERT_EMAIL_TO` y `ALERT_SMTP_HOST`:

- `webhook_failed`: eventos `failed` en 24 h (ya existía).
- `webhook_lag`: con `WEBHOOK_PROCESSOR_ENABLED=true`, un pendiente más viejo que `ALERT_WEBHOOK_LAG_MINUTES` (60).
- `webhook_silence:<canal>`: con `ALERT_WEBHOOK_SILENCE_HOURS` > 0 (0 por defecto = apagada), un canal que ya recibió webhooks lleva ese plazo sin recibir.

Solo conteos, canales y horas (nunca ids, payload ni texto del proveedor). Pendiente por decisión de negocio: alertar `subscription.deleted` o un cobro rechazado de un «socio importante» (falta definir quién lo es, el canal y los destinatarios).
Otros módulos agregan condiciones con `alerts.register_condition_provider(kind, evaluate, describe)`.

## Del webhook al navegador (D9, RT-11/RT-12)

Cadena completa: proveedor → webhook → `webhook_events` → procesador (`refresh_subscription`) → `status_change_events` → SSE → navegador. La sync diaria y la reconciliación dirigida alimentan la misma tabla,
así que el navegador se entera igual aunque el cambio no venga por webhook. Detalle en `docs/architecture/data-flow.md` («Tiempo real hacia la interfaz»).

## Reconciliación dirigida (RT-06, sin webhooks)

Cubre lo que los proveedores no avisan (VirtualPOS no tiene webhook de cobro recurrente ni de cancelación; Payku no confirma cancelación; y cualquier aviso perdido).
Job `reconcile_targeted`, **07:00, 10:00, 13:00, 16:00, 19:00 y 22:00** (D10), detrás de `TARGETED_RECONCILE_ENABLED` (apagada por defecto). Refresca con `refresh_subscription`
las suscripciones **vivas** (no canceladas/eliminadas) de VirtualPOS, Toku y Payku con:

- un cobro con fecha en los últimos 5 días (`TARGETED_RECONCILE_DUE_DAYS`) hasta hoy, o
- un cobro rechazado en los últimos 15 días (`TARGETED_RECONCILE_REJECTION_DAYS`), o
- un cobro pendiente ya vencido (fecha ≤ hoy; los pendientes futuros no cuentan: VirtualPOS los crea por adelantado).

Prioridad: rechazo, luego cobro reciente, luego pendiente. Tope `TARGETED_RECONCILE_MAX_PER_RUN` (200), pausa `TARGETED_RECONCILE_PAUSE_SECONDS` (1 s) entre peticiones,
y respeto del lock de `run_lock`: si hay una sincronización/ETL en curso no hace nada (se vuelve a comprobar cada 20 refrescos). Se corta tras 5 fallos seguidos (proveedor caído o limitando).
No escribe en `sync_runs` (un `source` nuevo aparecería como canal en los KPI); el resumen va al log y los cambios a `status_change_events`.

### Cola `refresh_queue` (SYNC-O-15)

`webhook_events` ya es, de hecho, la cola de los webhooks (dedupe por aviso, `SKIP LOCKED`, backoff, `failed`, reproceso RT-14); no se duplicó. Lo que faltaba: al agotar sus
intentos, la suscripción del evento quedaba sin relectura hasta la sync diaria. Ahora el procesador la encola en `refresh_queue` (`reason='webhook_failed'`; migración
`20261102_0063`) y cada pasada de la reconciliación dirigida refresca **primero** esas órdenes, dentro del mismo tope, y luego la ventana de riesgo sin repetirlas.
Una sola orden viva por suscripción (índice único parcial; encolar de nuevo no duplica), `done` no se reprocesa, un fallo vuelve a `pending` con backoff (30 min × 2^(n−1),
tope 6 h) y queda `failed` a los `REFRESH_QUEUE_MAX_ATTEMPTS` (5) intentos. Si la pasada se corta, las órdenes no alcanzadas vuelven a `pending` sin gastar intento; un
reclamo abandonado vence a los 30 min. Las razones `manual` y `post_write` existen para otros llamadores (`refresh_queue.enqueue_refresh`), pero aún nadie las usa.
Sigue pendiente la detección de «webhook perdido» (`missed_webhook`): depende de la decisión sobre qué eventos deben llegar por canal.

## Seguridad (RT-08)

- **Firma Toku**: HMAC-SHA256 de `"{t}.{event_id}"` con `whesec_…`, comparación en tiempo constante (`hmac.compare_digest`), ventana de 5 min. No cubre el body → no se confía en él.
  `TOKU_WEBHOOK_SECRET` vacío → 503 sin guardar nada.
- **VirtualPOS payment/subscription y Payku**: sin firma. Solo se guardan ids y estado (`minimal_payload`) y siempre se relee por API. Payku se autentica con `?k=` (comparación en tiempo constante). Payout de VirtualPOS conserva su HMAC.
- **Tope de body** `WEBHOOK_MAX_BODY_BYTES` (256 KB) → 413 antes de parsear o tocar la base (por `Content-Length` y leyendo en flujo).
- **Rate limit** en memoria, ventana de 60 s por (ruta, IP), `WEBHOOK_RATE_LIMIT_PER_MINUTE` (120) → 429. Se aplica antes de verificar firma (frena fuerza bruta). `X-Forwarded-For` se ignora salvo `WEBHOOK_TRUST_FORWARDED_FOR=true` (solo detrás de un proxy/túnel propio; si no, todos los visitantes del túnel cuentan como una IP). Es por proceso: con varios workers el límite efectivo se multiplica.
- **PII**: el payload pasa por `sanitize_payload` (credenciales) y `mask_pii` (claves de persona, correos, RUT y teléfonos dentro de textos; los objetos `customer`/`payer`… se reducen a su `id`) antes de insertar. `payload_masked` no tiene columnas de IP, headers ni cuerpo crudo.
- **Logs**: no se loguea payload ni cabeceras; solo ids de evento/recurso. El token `?k=` se redacta (`[redacted]`) en el access log de uvicorn (`app/core/log_redaction.py`). Aun así el token viaja en la URL: queda en logs de cualquier proxy/túnel intermedio; rotarlo si se sospecha filtración.
- Respuestas de error neutras (códigos 400/401/404/413/429/503, sin detalle del proveedor).

## Retención y purga sugerida

`webhook_events` crece con cada aviso (cientos de bytes por fila). Sugerido: conservar **30 días** los `done`/`ignored` y **90 días** los `failed` (necesarios para diagnóstico), y purgar manualmente
con una sentencia administrada por el usuario, por ejemplo:

```sql
DELETE FROM webhook_events WHERE status IN ('done','ignored') AND received_at < now() - interval '30 days';
DELETE FROM webhook_events WHERE status = 'failed'            AND received_at < now() - interval '90 days';
```

(No hay job de purga automático; se puede agregar si el volumen lo pide. Nunca purgar `pending`/`processing`.) Las tablas `stg_*_webhook_events` ya no reciben datos y pueden vaciarse o retirarse.

## Qué debe hacer el usuario para activarlo

Nada de esto lo hizo ni lo hará un agente sin confirmación en el chat.

1. **Aplicar la migración `20261029_0049`** (`alembic upgrade head`) en `crm` (y en `crm_sandbox` si se prueba allí). Solo crea la tabla `webhook_events` y dos índices; no modifica datos existentes. Haz respaldo antes como en cualquier migración.
2. **Definir `TOKU_WEBHOOK_SECRET`** en el `.env` real (nunca en el chat ni en Git). El valor `whesec_…` lo devuelve Toku al crear el endpoint (paso 3). Mientras esté vacío, el receptor de Toku responde 503.
3. **Crear el endpoint en Toku**: `POST /webhook_endpoints` (hay una petición en Postman, «Crear Webhook Endpoint») con la URL pública `https://<dominio fijo>/api/v1/webhooks/toku` y `enabled_events` acotados:
   `subscription.created`, `subscription.updated`, `subscription.deleted`, `transaction.success`, `transaction.failed`, `invoice.paid`, `invoice.voided`, `payment_method.status_update`, `payment_method.deleted`.
   Toku hace upsert por URL **y eventos**: con la misma URL y exactamente los mismos eventos actualiza; si comparte solo algunos responde 409; con eventos distintos crea otro endpoint con su propio `secret`. Una URL cambiante crea endpoints duplicados. Recomendado probar primero con la llave sandbox (ojo: comparte host con producción, DEC-26).
4. **Exponer SOLO `/api/v1/webhooks/*`** con el túnel nombrado de dominio fijo (D8), con lista de rutas permitidas (nada de frontend ni del resto de la API; el incidente de los túneles `trycloudflare` expuso el frontend). Activar `WEBHOOK_TRUST_FORWARDED_FOR=true` solo si el proxy es propio y arranca uvicorn con `--forwarded-allow-ips` acorde. Requiere confirmación previa en el chat.
5. **Encender las banderas** en el `.env` y reiniciar el backend (no se recarga solo): `WEBHOOK_PROCESSOR_ENABLED=true` y, cuando se quiera la reconciliación, `TARGETED_RECONCILE_ENABLED=true`. Con ambas apagadas, la cola solo acumula y el scheduler no hace nada.
6. (Opcional) VirtualPOS: `callback_url` por objeto al crear pagos/suscripciones nuevas (RT-09); Payku: `url_notify_suscription/payment` en el plan con `?k=` (RT-10; planes fijos, requiere autorización). Ninguno está hecho.
7. Verificar: enviar un evento de prueba desde Toku, ver la fila en `webhook_events` (`pending` → `done`) y el evento en `status_change_events` si cambió el estado.

## Riesgos y límites conocidos

- **Pérdida de ventana de Toku**: Toku reintenta ~1 h 41 min; con el PC apagado o el túnel caído más tiempo se pierden avisos. La reconciliación dirigida y la sync diaria los recuperan (hasta 3 h / 24 h de latencia).
- **PC del usuario como servidor**: túnel y backend dependen de que la máquina esté encendida (D8 es un puente hasta migrar a hosting, DEC-11).
- **Firma Toku sin cuerpo**: un atacante que capture una firma válida podría reutilizarla 5 min con otro cuerpo. Mitigado porque el cuerpo nunca se aplica (solo ids) y todo se relee por API.
- **VirtualPOS y Payku sin firma**: cualquiera que conozca la URL (y el token en Payku) puede encolar avisos; el costo es limitado por rate limit, tope de body, `dedupe_key` y el tope de lote del procesador, pero cada aviso válido origina una lectura al proveedor. Vigilar el rate limit de VirtualPOS (sin medir).
- **Rate limit en memoria**: por proceso y se pierde al reiniciar. Detrás de un túnel sin `WEBHOOK_TRUST_FORWARDED_FOR` todos comparten un solo contador.
- **Escritura de producción**: el procesador usa `refresh_subscription`, que escribe en canal y centralizadas (no en el proveedor). Con `APP_ENV=development` (equivale a producción) escribirá en `crm` al encender la bandera: probar antes en `crm_sandbox`.
- **Concurrencia con la sync nocturna**: el procesador no espera al lock de `etl_runs` (si no, los avisos se retrasarían hasta 2 h); los upserts son idempotentes y por fila, pero un refresco puntual durante la consolidación completa puede generar un evento de cambio atribuido a la corrida que llegue primero. Solo la reconciliación dirigida respeta el lock.
- **Pagos de VirtualPOS**: el webhook `payment` solo resuelve si el pago/cobro ya existe localmente; un pago de una inscripción nueva queda `ignored` (`NO_RESOURCE`) hasta la siguiente sync o el callback `subscription`.
- **Cache del dashboard**: antes la invalidaba el receptor al llegar el aviso (antes de tener el dato nuevo); ahora la invalida el procesador al terminar un evento `done`.
- **Baja de Toku**: si Toku no responde 404 tras `subscription.deleted` (p. ej. devuelve la suscripción con otro estado), el estado sale del propio refresh; si responde 404 se marca `deleted`. Falta confirmar con un evento real el comportamiento exacto (DEC-26 p. 5).
- **Tareas relacionadas**: RT-11/RT-12 (SSE y avisos en el navegador), RT-13 (alertas) y RT-14 (panel y reproceso) quedaron hechas en código (lote L2-RT). Siguen pendientes el hosting definitivo (DEC-11) y las alertas de «socio importante» (decisión de negocio).
- **Runbook** de operación (rotar secretos, recrear el endpoint de Toku, ventana perdida, reproceso): `docs/operations/webhooks-runbook.md`.
