# Toku — Integración operacional

> Canal: Toku  
> Ultima revision: 2026-10-15  
> Documentacion oficial: https://docs.trytoku.com/docs/via-api-2  
> Referencia tecnica plana: [docs/integrations/toku.md](../toku.md)

---

## Flujos disponibles

| Flujo | Archivo | Descripcion breve |
|---|---|---|
| Alta de socio (Customer + Subscription pausada + Checkout de inscripcion) | [workflows/alta-socio.md](workflows/alta-socio.md) | **Bloqueado** hasta que Toku configure `flow_name` ENROLLMENT (T-A1) |
| Link seguro de inscripcion de medio de pago | [workflows/link-inscripcion.md](workflows/link-inscripcion.md) | Adaptador para alta pendiente y socio existente; mismo bloqueante T-A1 |
| Editar datos del socio | [workflows/editar-socio.md](workflows/editar-socio.md) | Actualizar nombre, email, telefono, RUT del Customer (nunca `external_id`) |
| Seguimiento de cobros recurrentes | [workflows/seguimiento-cobros.md](workflows/seguimiento-cobros.md) | Invoices <-> Transactions via Payment Intents, motivos de rechazo y liquidacion |
| Cambiar el monto del aporte | [workflows/cambiar-monto.md](workflows/cambiar-monto.md) | PUT /subscriptions + correcciones de Invoices no cobradas |
| Crear un Customer | [workflows/create-customer.md](workflows/create-customer.md) | POST /customers (upsert por external_id) |
| Crear una Subscription | [workflows/create-subscription.md](workflows/create-subscription.md) | POST /subscriptions (upsert por product_id) |
| Crear una Invoice | [workflows/create-invoice.md](workflows/create-invoice.md) | POST /invoices (upsert por product_id + due_date) |
| Inscribir un medio de pago | [workflows/enroll-payment-method.md](workflows/enroll-payment-method.md) | Checkout Session ENROLLMENT; asociar pm_ a suscripcion |
| Cancelar una Subscription | [workflows/cancel-subscription.md](workflows/cancel-subscription.md) | Pausar, reanudar o eliminar |
| Reconciliar un pago | [workflows/reconcile-payment.md](workflows/reconcile-payment.md) | Cuadrar Invoice con Transactions y Payment Intents |
| Sincronizar Toku a base central | [workflows/sync-toku.md](workflows/sync-toku.md) | Job paginado: Customers, Subscriptions, Invoices, Transactions |

## Recursos documentados

Los archivos en [resources/](resources/) cubren el contrato detallado de cada recurso de la API:

- [authentication.md](resources/authentication.md) — x-api-key, OAuth M2M, headers, versionamiento
- [customers.md](resources/customers.md) — Customer (`cus_...`), upsert por external_id
- [subscriptions.md](resources/subscriptions.md) — Subscription (`sub_...`), recurrente, estados
- [invoices.md](resources/invoices.md) — Invoice (`in_...`), general_status, in_progress
- [transactions.md](resources/transactions.md) — Transaction + Payment Intents (N:M con Invoices)
- [payment-methods.md](resources/payment-methods.md) — Payment Methods (`pm_...`), PAC, asociacion
- [webhooks.md](resources/webhooks.md) — HMAC-SHA256, evento id, reintentos, version
- [errors.md](resources/errors.md) — Codigos HTTP, codigos TKxxxxx, rate limits (1 req/s Transactions)
- [pagination.md](resources/pagination.md) — Cursor (Invoices) vs pagina (Transactions)
- [statuses.md](resources/statuses.md) — Inventario de estados de Toku
- [data-model.md](resources/data-model.md) — Relaciones, identificadores y mapping interno
- [postman-audit.md](resources/postman-audit.md) — Diferencias Postman vs doc oficial

## Referencia tecnica plana

El archivo [docs/integrations/toku.md](../toku.md) contiene:
- Comportamiento observado del sync y recursos disponibles
- Suscripciones eliminadas en el origen: estrategia de stubs `deleted_at_source` (112 suscripciones, 564 invoices PAID)
- Controles de escritura (`TOKU_WRITES_ENABLED`)
- Estado de webhooks: HMAC confirmado, receptor pendiente por falta de HTTPS y sandbox

---

## Bloqueantes y pendientes activos

| Clave | Descripcion | Impacto |
|---|---|---|
| **BLQ-TK-01 / T-A1** | Toku debe configurar el `flow_name` para el Checkout de inscripcion (ENROLLMENT). Sin esto, cualquier `POST /cl/checkout-sessions` con `mode: ENROLLMENT` devuelve `4xx`. | **Bloquea completamente** los flujos de alta y de cambio de tarjeta (link-inscripcion, alta-socio) |
| **T-A2** | Host real del Checkout de Toku desconocido hasta la primera sesion real. La lista de hosts permitidos de la capa comun no puede completarse antes. | Bloquea la validacion de origen del link en produccion |
| **T-S1** | Ambiguedad sobre si `start_date`/`end_date` de `GET /transactions` filtra por `transaction_date` o `initialization_date`. | Afecta la ventana del job diario de seguimiento |
| **Webhooks** | No hay sandbox documentado. La primera prueba usa HTTPS temporal. El tiempo de espera del proveedor y el tratamiento de respuestas `2xx != 200` son TBD. | Receptor de webhooks aun no implementado |
| **Suscripciones eliminadas** | El sync solo recupera suscripciones activas. Las 112 suscripciones eliminadas generan stubs `deleted_at_source`; sus campos (monto, fecha, cliente) quedan en NULL por no estar disponibles. | Impacto en reportes de recaudacion por suscripcion |
