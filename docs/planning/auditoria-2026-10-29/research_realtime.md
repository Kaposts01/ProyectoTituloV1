# Investigación: tiempo casi real (webhooks, SSE/WebSocket, reconciliación)

Fecha: 2026-10-29. Solo lectura. Fuentes: docs/integrations/{virtualpos,toku,payku}/resources/webhooks.md, payku/resources/events.md (es un recurso de "eventos de recaudación", NO webhooks), VirtualPOS_API_Documentacion.md, colecciones Postman de Downloads, `app/api/v1/routes/webhooks_*.py`, modelos `stg_*_webhook_event`, `scheduler.py` (SSE), docs/tasks.md (WH-01..03, TK-12, OPS-09, DEC-11/12, USR-06/12), audit_sync.md.

## 0. Aclaración de conceptos

Son dos tramos distintos y se resuelven por separado:
- (i) Proveedor -> nuestro backend: **webhook** (HTTP POST). Lo decide el proveedor; requiere URL pública HTTPS nuestra.
- (ii) Nuestro backend -> navegador: **SSE/WebSocket/polling**. Lo decidimos nosotros (OPS-09). No hace falta para recibir webhooks y no sirve de nada si el backend no se entera antes del cambio.
Cadena completa: proveedor -> webhook -> `webhook_events` -> refrescar ese recurso -> `status_change_events` -> notificación SSE al dashboard. Un WebSocket solo resuelve el último eslabón.

## 1. Qué ofrece cada proveedor

| Aspecto | VirtualPOS | Toku | Payku |
|---|---|---|---|
| ¿Hay webhooks? | Parcial: solo Payment, Suscription (callback de inscripción) y Payout | Sí, completos (48 eventos, `enabled_events`) | Parcial: 5 notificaciones (suscripción, cobro, pago único, anulación, payout) |
| Cobro pagado/rechazado | Payment: POST con `uuid` (pago web/checkout). **Cobros recurrentes (charge): NO existe webhook** | `transaction.success/failed`, `transaction.bulk_success/bulk_failed`, `transaction.status_update`, `invoice.paid` | `url_notify_payment` del plan: `status` pending/success/rejected/refunded; sin monto ni fecha |
| Suscripción creada | Callback único al terminar inscripción; contenido NO documentado | `subscription.created` | Estado `register`/`active` en `url_notify_suscription` |
| **Suscripción cancelada** | **NO**. `DELETE /v3/suscription` genera ACTIVA->CANCELADA sin aviso | **Parcial**: `subscription.deleted` (DELETE). No hay `subscription.cancelled` en docs (el set de caché lo incluye por defecto); estado de suscripción no recurrente sin ubicar (DEC-26 p.4); `subscription.updated` puede cubrir pausas (verificar) | Declarado: `status` incluye `cancel`/`delete`/`finish`/`suspended`, pero la doc **solo garantiza el aviso en la activación**; cancelación/suspensión NO confirmada |
| Pausa | No | `subscription.updated` (sin `updated_fields`) | `suspended` (no confirmado) |
| Medio de pago actualizado | No | `payment_method.updated/status_update/attached_products/deleted` (caída de medio) | No |
| Reintentos del proveedor | No documentados | 5 reintentos: inmediato, +1 min, +10, +30, +1 h (~1h41m); timeout 120 s; `disabled` descarta pendientes | No documentados (asumir cero) |
| Formato payload | POST con `uuid` (JSON o form, no documentado); payout JSON | JSON `{id: wheve_..., event_type, <recurso>}`; sin sobre `data` | JSON o form (no documentado); campos distintos por tipo |
| Firma | Payment/Suscription: **ninguna**. Payout: HMAC-SHA256 del body en header `Signature` (hex o base64 sin aclarar) | `Toku-Signature: t=..,s=..`, HMAC(`t.id`) con `whesec_`; **no cubre el body** | **Ninguna**; solo token secreto propio en query `?k=` |
| Configuración | `callback_url` (Base64) por cada Payment/Suscription creado (API); payout se acuerda con VP; **sin portal global** | API: `POST /webhook_endpoints` (upsert por URL, devuelve secret); también en Postman | `url_notify_suscription`/`url_notify_payment` en el **plan**; `urlnotify` por transacción; anulación en panel |
| Cubre "suscripción cancelada" | No | Solo `subscription.deleted` (+ posible `updated`) | No confirmado |
| Alternativa si falta | Polling dirigido de `GET /v3/suscription/{id}` y pagos; reporte Backoffice (SYNC-D-14) | Reconciliación diaria; reportes Toku para estado de suscripción (TK-19/20) | `GET /api/sususcription/{id}` con `logs.status[].change_date`; sync diario |

Notas: las suscripciones VP existentes fueron creadas sin `callback_url` útil (o con otro); el callback es por objeto, así que **no cubre el histórico** y solo lo recibirían inscripciones nuevas. Payku: `url_notify_*` está en el plan; cambiar el plan afecta a todas sus suscripciones (cuidado con la restricción de planes fijos).

## 2. Estado del backend

Implementado (WH-01..03, completadas):
- Rutas: `POST /api/v1/webhooks/toku`, `/webhooks/virtualpos/{payment|subscription|payout}`, `/webhooks/payku/{kind}` (5 kinds). Sin JWT, registradas en `main.py`.
- Tablas `stg_toku_webhook_events`, `stg_vpos_webhook_events`, `stg_payku_webhook_events` (migraciones 0029/0030).
- Toku: HMAC t+id, ventana 5 min, idempotencia por `toku_event_id` UNIQUE (IntegrityError -> ignora), 503 si no hay secreto (hoy `TOKU_WEBHOOK_SECRET` vacío -> rechaza todo). Payku: token `?k=` con `compare_digest`. VP: HMAC solo para payout.
- Reacción actual: solo `invalidate_dashboard_cache()` en BackgroundTask. `process_status` existe pero nadie procesa.

Falta:
1. **Procesador**: ningún worker lee `pending`, ni llama a la API del proveedor, ni actualiza canal/core. (TK-12 pendiente.) **`refresh_subscription` no existe** en el código; solo hay `client.get_subscription/get_payment` en los tres clientes. Hay que crear un "refresco puntual" (`refresh_one(source, kind, id)`): GET al proveedor -> `channel_store` upsert de ese registro -> consolidación solo de esa fila -> evento de cambio.
2. **Idempotencia**: Toku sí; VP y Payku **no tienen UNIQUE** (VP puede duplicar filas por reintento/retorno; falta clave `(kind,resource_id,payload_hash)` o `(kind,resource_id,status)` en Payku).
3. **Tabla unificada `webhook_events`** con cola (estados, `attempts`, `next_attempt_at`, `locked_at`) en vez de 3 tablas sin worker; o conservar las 3 y añadir columnas de cola.
4. **Tabla de cambios de estado** (`status_change_events`, SYNC-D-01/02): inexistente; el webhook debe alimentarla con `source_kind='webhook'` y `provider_event_at`.
5. Sin rate limit, sin lista de IPs, `source_ip` se toma de `x-forwarded-for` sin confiar en proxy (falsificable), payload guardado completo en JSONB (PII: Toku trae customer/payment_instrument; VP/Payku customer con RUT/teléfono) sin enmascarar.
6. Sin retención/purga de eventos; sin reproceso manual; sin métricas ("lag" entre `received_at` y `processed_at`).
7. **Reconciliación**: la sync diaria reescribe todo (1,9-2,8 h) y no detecta lo perdido; falta reconciliación dirigida (ver RT-06) y alertas (SYNC-D-08).
8. Exposición pública: **no existe**. El sistema corre en local (backend 8000, sandbox 8001). Los webhooks necesitan una URL pública HTTPS estable. Los túneles trycloudflare anteriores (26-29 oct) fueron un incidente (USR-06/12: URL cambiante, expusieron el frontend de producción solo con login).

### Exposición pública segura (opciones)
| Opción | Pro | Contra |
|---|---|---|
| A. Túnel con dominio fijo (Cloudflare Tunnel nombrado o ngrok reservado) solo para `/api/v1/webhooks/*` | Rápido, sin hosting | PC del usuario debe estar encendido; hay que filtrar rutas en el túnel (path allowlist) para no exponer UI/API; URL estable obligatoria (Toku upsert por URL; VP callbacks quedan grabados por objeto) |
| B. Receptor mínimo separado en hosting barato (VPS/Railway/Cloud Run) que solo valida firma y guarda en cola/BD; el backend local lo drena por polling | Superficie mínima, siempre disponible, no expone nada interno; no pierde eventos con PC apagado | Hay que operar otra pieza y una cola/BD compartida; encaja con DEC-11 |
| C. Hosting definitivo del CRM (DEC-11) | Solución final | Bloqueada por DEC-11/12 |
Recomendación: B como puente si el hosting tarda; A solo con túnel nombrado + allowlist de `/api/v1/webhooks/*` + Cloudflare Access/WAF y nunca publicando frontend. Toku firma poco (id+t), así que no dependas de la firma: siempre releer por API.

## 3. Tiempo real hacia la interfaz (OPS-09)

Hoy: un SSE (`/scheduler/.../stream`, `StreamingResponse` text/event-stream + `event_bus` en memoria) solo para el progreso de una corrida. El scheduler corre dentro de la API (APScheduler en el lifespan).

| Criterio | SSE | WebSocket | Polling corto (15-30 s) |
|---|---|---|---|
| Dirección | Servidor->cliente (basta) | Bidireccional (no necesario) | Cliente->servidor |
| FastAPI | Ya usado; trivial | Soportado, más código (auth, heartbeat) | Cero infra |
| Auth (JWT) | `EventSource` no manda headers: usar `fetch`-stream o cookie/token corto en query | Token en handshake/primer mensaje | Normal |
| Reconexión | Automática + `Last-Event-ID` para recuperar | Manual | N/A |
| Proxys/túnel | Funciona sobre HTTP; atención al buffering | Puede fallar en algunos proxys | Siempre |
| Multi-worker | `event_bus` en memoria NO sirve con >1 worker: usar Postgres `LISTEN/NOTIFY` o tabla + `id` incremental | Igual | Sin problema |
| Costo | Bajo | Medio | Carga constante en BD (barata con `?since=`) |
Recomendación: **SSE alimentado por la tabla `status_change_events`** (cursor `id`/`Last-Event-ID`), con `LISTEN/NOTIFY` de Postgres como disparador y polling de respaldo cada 30-60 s en el frontend. Eventos mínimos `{entity, source, id, from, to, at}` sin PII; el cliente invalida cache de TanStack Query/refetch. WebSocket no aporta nada (no hay mensajes cliente->servidor). La persistencia en tabla resuelve el caso "navegador cerrado". Esto es el cierre natural de OPS-09 y reutiliza el SSE actual.
Aclaración para el usuario: nada de esto actualiza datos por sí solo; solo avisa al navegador de que ya cambió algo en nuestra BD.

## 4. Detección de cancelaciones sin webhooks

| Señal | Aplica a | Latencia | Costo API | Notas |
|---|---|---|---|---|
| Webhook `subscription.deleted`/`updated` | Toku | segundos | 0 + 1 GET | única fuente directa; verificar con evento real |
| Polling dirigido: `GET /v3/suscription/{id}` solo de suscripciones ACTIVAS con próximo cobro en las próximas 24-48 h o con cobros rechazados | VP | 1-6 h (configurable) | Bajo: cientos de GET, no 100k | Cancelaciones ocurren por UI de VP o API; la dirigida detecta antes del cobro |
| Polling dirigido `GET /api/sususcription/{id}` + `logs.status[].change_date` | Payku | 1-6 h | Bajo | `change_date` da la hora real del cambio |
| Cobros `cancelado` masivos en `charge_program` | VP | diaria (en sync) | 0 | Cuando se cancela, los cargos pendientes pasan a `cancelado`: señal fuerte tras cada sync |
| Próxima fecha de cobro nula / sin cargos pendientes en suscripción ACTIVA | VP/Payku | diaria | 0 | Heurística, falsos positivos al terminar plan |
| Desaparición en listados (SYNC-D-13) | Todos | diaria | 0 | Requiere `last_seen_sync_at`; guarda de seguridad por sync incompleto |
| Cambio de estado en sync diaria con diff (SYNC-D-02) | Todos | <=24 h | 0 | Base de toda la detección; el diff compara ya con valores previos |
| Reportes descargados | Toku (estado de suscripción), VP | semanal/manual | 0 | TK-19/20, SYNC-D-14 |
| Rechazos repetidos / `permanent_failed` | Toku, VP | diaria | 0 | Señal de baja inminente, no de cancelación |
Conclusión: la latencia sin webhooks baja de 24 h a 1-6 h con **polling dirigido por ventana de riesgo** (suscripciones con cobro próximo o recién rechazado), sin repetir la sync completa.

## 5. Seguridad

- Firma: Toku `t.id` + ventana 5 min (hecho); VP payout HMAC (hecho); VP payment/suscription y Payku sin firma -> **no confiar en el body**: usar solo el id y releer por API (diseño ya documentado).
- Secretos Payku en query string quedan en logs de proxy/túnel: rotar, preferir path con token + `Referrer-Policy`; filtrar `k` del logging de uvicorn (access log lo imprime).
- IPs: ningún proveedor publica rangos en la doc; no confiar en allowlist. Si se usa proxy/túnel, aplicar `X-Forwarded-For` solo desde proxy conocido (uvicorn `--forwarded-allow-ips`).
- Rate limit (p. ej. 60/min por IP y por kind), tope de tamaño de body (p. ej. 256 KB), y rechazo de `Content-Type` raros antes de tocar BD.
- No loguear payload ni headers (hoy se loguea solo ids: correcto); enmascarar PII del JSONB (customer, RUT, email, teléfono, instrumento) antes de persistir o guardar solo ids + `payload_hash`; purga a 30-90 días.
- Secretos fuera del repo: `TOKU_WEBHOOK_SECRET`, `PAYKU_WEBHOOK_SECRET`, `VIRTUALPOS_PAYOUT_WEBHOOK_SECRET` solo en `.env`/gestor; el secret de Toku (`whesec_`) se obtiene al crear el endpoint (el usuario lo copia; nunca en chat/commit). Rotación documentada.
- Endpoint sin JWT = superficie anónima: aislar en un router propio, idealmente en un puerto/host distinto del CRM.
- Anti-replay: Toku ventana de 5 min ya; guardar `event_id` evita duplicados.

## 6. Tareas priorizadas (familia RT)

Esfuerzo: S <=3 h, M 4-10 h, L >10 h de IA. Mig = requiere migración (la aplica el usuario).

| ID | Pri | Descripción | Archivos | Esf. | Riesgo | Mig | Decisiones del usuario |
|---|---|---|---|---|---|---|---|
| RT-01 | P0 | Decisión y cierre documental: SSE sobre `status_change_events` (cierra OPS-09) y modelo en 2 tramos | docs/tasks.md, docs/architecture | S | Bajo | No | Aprobar SSE |
| RT-02 | P0 | Decidir exposición pública: opción B (receptor mínimo) o A (túnel nombrado con allowlist) o esperar DEC-11 | docs, `ops` | S | Alto si se hace mal (incidente USR-06) | No | DEC-11 + qué opción; dominio |
| RT-03 | P1 | Crear webhook endpoint en Toku (portal/Postman `Crear Webhook Endpoint`) con eventos acotados: `subscription.created/updated/deleted`, `transaction.*`, `invoice.paid/voided`, `payment_method.status_update/deleted`; cargar `TOKU_WEBHOOK_SECRET` | `.env` (usuario), Postman | S | Medio (producción real) | No | El usuario ejecuta (TK-12); primero sandbox si DEC-26 lo permite |
| RT-04 | P1 | Cola `webhook_events` (unificar o extender las 3 tablas): `attempts`, `next_attempt_at`, `locked_at`, UNIQUE de idempotencia en VP/Payku (`kind+resource_id+payload_hash`), índice parcial `pending` | `app/models/webhook_event.py`, alembic, 3 rutas | M | Medio | **Sí** | Retención (sugerido 90 días) |
| RT-05 | P1 | Procesador asíncrono: worker (job APScheduler cada 10-30 s con `SELECT ... FOR UPDATE SKIP LOCKED`) que toma `pending`, hace `refresh_one` (GET puntual `get_subscription/get_payment/get_transaction`), upsert del canal, consolida solo ese registro, escribe `status_change_events` (depende de SYNC-D-01/02), marca `done/error` con backoff y dead-letter | `app/services/webhook_processor.py`, `app/scheduler/engine.py`, `app/services/channel_consolidation.py` (consolidación por id) | L | Alto (nuevo camino de escritura; usar guardas de ambiente) | No (si SYNC-D-01 ya) | Ninguna |
| RT-06 | P1 | Reconciliación dirigida obligatoria: job cada 1-6 h que refresca suscripciones activas con cobro en <48 h, con rechazos recientes o con webhook pendiente/error; y eventos `pending` huérfanos; con tope de peticiones y 429/Retry-After | `app/scheduler/jobs/reconcile_targeted.py`, clientes | M | Medio (rate limit VP sin medir) | No | Tope de peticiones/hora, ventana |
| RT-07 | P1 | Reglas de acción por tipo: Toku `subscription.deleted` -> refrescar y marcar cancelada con `source_kind='webhook'`; Payku `subscription` y `payment` -> GET puntual; VP `payment` -> `GET /v3/payment/{uuid}`; descartar `transaction.bulk_*` a refresco por lote | `webhook_processor.py` | M | Medio | No | Qué estados/eventos se consideran "cancelación" |
| RT-08 | P1 | Endurecer receptores: tope de body, rate limit (slowapi o middleware), `forwarded-allow-ips`, enmascarar PII del payload persistido, filtrar `?k=` de logs de acceso, cabecera de error neutra | `app/api/v1/routes/webhooks_*.py`, `app/core/security*`, `main.py` | M | Bajo | No | Ninguna |
| RT-09 | P1 | Callbacks en VP: añadir `callback_url` (Base64) al crear suscripciones/payments nuevos desde el CRM, y guardar el formato real recibido en sandbox (validar `VAL-VP-01`) | `app/integrations/virtualpos/client.py`, writes | M | Medio (solo nuevas; no cubre histórico) | No | Aprobar probar en sandbox VP |
| RT-10 | P1 | Payku: configurar `url_notify_suscription/payment` en planes (con `?k=`), verificar en sandbox si se notifican `cancel/suspended/rejected`; si no, depender de RT-06 | docs Payku, config de planes | S | Alto (planes fijos de VP/Payku, no modificar sin permiso) | No | Autorizar cambio de planes; Payku sandbox bloqueado |
| RT-11 | P2 | Endpoint SSE `GET /api/v1/events/stream` (JWT, `Last-Event-ID`, heartbeat, sin PII) sobre `status_change_events` + `LISTEN/NOTIFY`; reemplazar `event_bus` en memoria | `app/api/v1/routes/events.py`, `app/scheduler/event_bus.py` | M | Medio (multi-worker, proxys) | No | Ninguna |
| RT-12 | P2 | Frontend: hook `useChangeStream`, toast/badge "cambió el estado de X", invalidación de queries y fallback de polling 30-60 s | `frontend/src/features/*`, `lib/` | M | Bajo | No | Dónde mostrar (barra, dashboard, ficha) |
| RT-13 | P2 | Alertas: Slack/correo cuando llega `subscription.deleted`/cobro rechazado de un socio importante, o cuando el lag de webhooks supera X; y cuando no llegan webhooks en N horas (salud del canal) | `app/scheduler/alerts.py` (con SYNC-D-08) | M | Bajo | No | Canal y destinatarios |
| RT-14 | P2 | Panel de salud de webhooks: conteos por estado, lag, último evento por proveedor, reproceso manual | `app/api/v1/routes/webhooks_admin.py`, frontend admin | M | Bajo | No | Permiso |
| RT-15 | P2 | Receptor mínimo externo (opción B) que solo encola y es drenado por el backend local | repo/servicio aparte | L | Medio | No | DEC-11, proveedor de hosting |
| RT-16 | P3 | Tests: firmas, idempotencia, desorden, replay, evento desconocido, PII enmascarada, procesador con proveedor simulado; tests de contrato en sandbox | `tests/test_webhook_processor.py`, `tests_contract/` | M | Bajo | No | Ninguna |
| RT-17 | P3 | Documentar runbook: rotar secretos, recrear endpoint Toku, qué hacer si se pierde ventana de 1h41m (reconciliación manual) | `docs/operations/` | S | Bajo | No | Ninguna |

Orden recomendado: RT-01/02 (decisión) -> SYNC-D-01/02 (tabla de cambios, prerrequisito) -> RT-04 -> RT-05/07 -> RT-08 -> RT-03 (primero Toku, único con cobertura real) -> RT-06 -> RT-11/12 -> resto.
Camino rápido de valor sin webhooks: SYNC-D-02 + RT-06 (polling dirigido) + RT-11/12 entregan "casi tiempo real" (1-6 h) sin exponer nada a Internet.

## 7. Matriz canal x evento x mecanismo

Leyenda: W = webhook confiable; W? = webhook declarado pero no confirmado; P = polling dirigido (RT-06); S = sync diaria con diff; R = reporte; - = sin cobertura directa. Latencia entre paréntesis.

| Evento | VirtualPOS | Toku | Payku |
|---|---|---|---|
| Cobro pagado (recurrente) | P/S (1-6 h/24 h) | W `transaction.success`, `bulk_success`, `invoice.paid` (seg.) | W `payment` success (seg.), + GET |
| Cobro rechazado | P/S; glosa por `get_payment_attempts` (SYNC-D-05) | W `transaction.failed/bulk_failed` (seg.) | W? `payment` rejected (seg.); no se sabe si cubre reintentos |
| Pago web/checkout (Payment) | W `payment` uuid (seg.), sin firma | W `transaction.*` | W `transaction` urlnotify |
| Suscripción creada/activada | W? callback inscripción (formato desconocido) + P | W `subscription.created` | W `subscription` (active) |
| Suscripción cancelada | **P/S + cargos `cancelado`** (1-6 h/24 h); sin webhook | W `subscription.deleted` (seg.) + S | W? (`cancel`/`delete` no confirmado) + P |
| Suscripción pausada/suspendida | P/S | W? `subscription.updated` | W? `suspended`; `logs.status` en P |
| Medio de pago actualizado/caído | P/S (cambio de tarjeta flujo propio) | W `payment_method.*` | - (S) |
| Reintentos de cobro | P/S | W (`transaction.status_update`) | W? / P |
| Monto cambiado | S (`monto_vigente`) | W `subscription.updated`/`invoice.updated` | S |
| Reversa/anulación | P | W `transaction.refund`, `chargeback.status_update` | W `nullification` |
| Payout | W firmado (obligatorio) | - | W `payout` |
| Cobertura histórica/perdidos | S + R (SYNC-D-14) | S + R (TK-19/20) | S |

## 8. Decisiones pendientes del usuario
1. Aprobar SSE (OPS-09) y que el tramo proveedor->backend sea webhook + reconciliación.
2. Exposición pública (RT-02): opción A/B/C y dominio; sin túneles temporales.
3. DEC-11/DEC-12 (hosting y quién valida) condiciona RT-15.
4. Crear webhook en Toku y cargar secreto (RT-03); confirmar con soporte Toku (DEC-26 p.5) 2xx, retención y eventos de cancelación.
5. Autorizar pruebas en sandbox VP de `callback_url` y medir rate limit; Payku sandbox bloqueado.
6. Migración de RT-04 y la de SYNC-D-01 las aplica el usuario (en `crm_sandbox` el orquestador, DEC-28).
7. Qué se considera "cancelación" y quién recibe alertas.
