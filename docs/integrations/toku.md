# Toku

Toku aporta clientes, suscripciones, metodos de pago, deudas y transacciones. Usa una clave de API solo en el backend; los sincronizadores aplican limites y reintentos para respuestas temporales.

Las operaciones mutables implementadas requieren `TOKU_WRITES_ENABLED=true`, permisos y proteccion CSRF. El navegador no llama a Toku directamente.

El dashboard usa las deudas para su actividad y las transacciones para resultados de pago. La comparación con suscripciones activas usa exclusivamente transacciones fechadas del canal, no facturas.

## Estructura operacional

La documentacion operacional detallada esta organizada en [docs/integrations/toku/README.md](toku/README.md).

Incluye 12 flujos paso a paso y 12 documentos de recursos (contratos de API, autenticacion, paginacion, errores, data model, webhooks).

### Bloqueante critico

| Clave | Descripcion | Impacto |
|---|---|---|
| **BLQ-TK-01 / T-A1** | Toku debe configurar el `flow_name` para el Checkout de inscripcion (ENROLLMENT). Sin esto, cualquier `POST /cl/checkout-sessions` con `mode: ENROLLMENT` devuelve `4xx`. | Bloquea completamente los flujos de alta y de cambio de tarjeta (alta-socio, link-inscripcion, enroll-payment-method) |

## Suscripciones eliminadas en el origen

El sync de Toku solo recupera suscripciones activas desde la API. Las suscripciones que fueron canceladas o eliminadas antes o entre ciclos de sincronización no aparecen en `tk_subscriptions`, pero sus invoices y pagos sí existen en el sistema del proveedor y se sincronizan a `tk_invoices` y `tk_payments`.

**Magnitud observada (2026-10-07):** 112 suscripciones distintas ausentes del staging generan 564 invoices `PAID` (todos con pago exitoso), cubriendo el rango 2024-10-09 a 2026-07-09.

**Opciones evaluadas para la materialización Core:**

- **Opción B (descartada):** Aceptar el gap. Materializar los 564 pagos con `charge_id=NULL` y `subscription_id=NULL`. Simple, pero deja pagos PAID sin trazabilidad financiera hacia ninguna suscripción ni cargo, lo que distorsiona cualquier reporte de recaudación por suscripción.

- **Opción A (elegida):** Crear un `CoreSubscription` stub por cada suscripción ausente con `status='deleted_at_source'` y `client_id=NULL`. Los campos de monto, fecha y cliente quedan en NULL porque no están disponibles. Esto permite mantener la cadena `payment→charge→subscription` y garantiza que los 564 pagos PAID aparezcan correctamente en reportes de recaudación. Los stubs pueden enriquecerse si en el futuro el sync se extiende para capturar suscripciones históricas canceladas mediante la API de Toku.

El ETL Core implementa esta estrategia en `app/services/core_toku_etl.py` (`_materialize_stub_subscriptions`).

## Recursos opcionales y 404 (L7-CIERRE)

`payment` (`/organization/payments`) y `payment_method` son recursos secundarios: si su endpoint responde 404 (el sandbox responde 404 en `/organization/payments`), el recurso queda omitido (`resource_stats.<recurso>.skipped = true`, `reason = http_404`, y un aviso en el log sin datos personales), la sync sigue con los demás y el `sync_runs` queda `partial` con lo leído guardado; la corrida global (`etl_runs`) también queda `partial` y el canal no se reintenta. Clientes, suscripciones, facturas y transacciones son esenciales: su 404, cualquier 401/403 y los demás errores siguen haciendo fallar la sync. El texto del aviso no contiene marcadores de configuración o credencial, así que no dispara la alerta de primer fallo (d139a); además esa alerta solo mira corridas `failed`.

**Sandbox (CRM-14B, 2026-11-13).** Fuera de producción (`APP_ENV=sandbox` o `qa`) la sync **no pide** `/organization/payments`: el endpoint no figura en la referencia pública de Toku (`resources/postman-audit.md`, X1) y la organización que ven las llaves `TOKU_SANDBOX_*` responde 404 siempre. El recurso queda en `resource_stats.payment` como `{"skipped": true, "reason": "not_available_in_sandbox", "records": 0, "pages": 0}` y la corrida termina `completed` (antes, `failed` sin L7-CIERRE y `partial` con él). Código: `SANDBOX_EXCLUDED_RESOURCES` en `app/services/toku_sync.py` y el parámetro `excluded_resources` de `sync_read_only_provider`. En producción no cambia nada: se sigue pidiendo y un 404 lo deja `partial`. Prueba: `tests/test_toku_sandbox_payments_excluded.py`.

## Webhooks

**Confirmed:** Toku permite crear endpoints HTTPS mediante `POST /webhook_endpoints`, autenticado con `x-api-key`. El endpoint recibe un identificador de entrega `id`, `event_type` y la carga del evento. La autenticidad se valida con `Toku-Signature`: HMAC-SHA256 de `<timestamp>.<event id>` usando el secreto entregado al crear el endpoint. Los eventos relevantes incluyen `invoice.paid`, `subscription.*`, `transaction.*` y `payment_method.*`. La forma del payload debe fijarse con `webhook_version`.

**Confirmed:** ante una entrega fallida Toku documenta reintentos inmediatos, a 1, 10 y 30 minutos, y a 1 hora. La sincronización periódica se mantiene como reconciliación de eventos perdidos o modificados.

**Known limitation:** Toku documenta un único ambiente productivo; no hay sandbox documentado para validar el receptor. La primera prueba operativa usará una URL HTTPS pública temporal y no almacenará secretos en la URL.

**TBD:** tiempo de espera del proveedor, tratamiento de respuestas `2xx` distintas de `200`, retención o reenvío de eventos y política exacta de entregas.

Fuentes oficiales: [Webhooks](https://docs.trytoku.com/docs/webhooks), [crear endpoint](https://docs.trytoku.com/reference/create_webhook_endpoint), [objeto y eventos](https://docs.trytoku.com/reference/webhook-endpoint-object), [versionamiento](https://docs.trytoku.com/reference/versionamiento) y [ambientes](https://docs.trytoku.com/reference/conexion-y-ambientes).
