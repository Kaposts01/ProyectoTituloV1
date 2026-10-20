# VirtualPOS — Integración operacional

> Canal: VirtualPOS  
> Ultima revision: 2026-10-15  
> Documentacion oficial: https://virtualpos.readme.io/reference/getting-started-with-your-api  
> Referencia tecnica plana: [docs/integrations/virtualpos.md](../virtualpos.md)

---

## Flujos disponibles

| Flujo | Archivo | Descripcion breve |
|---|---|---|
| Alta de socio (cliente + plan + suscripcion) | [workflows/alta-socio.md](workflows/alta-socio.md) | Crea cliente, busca o crea plan fijo, crea suscripcion y emite link de tarjeta |
| Crear o encontrar un cliente (upsert) | [workflows/create-client.md](workflows/create-client.md) | Upsert por email o RUT; base64 en URLs |
| Cobro unico por Web Checkout | [workflows/web-checkout-payment.md](workflows/web-checkout-payment.md) | Payment + link de WebCheckout |
| Crear una suscripcion | [workflows/create-subscription.md](workflows/create-subscription.md) | POST /v3/suscription con plan fijo |
| Cobrar una suscripcion | [workflows/charge-subscription.md](workflows/charge-subscription.md) | Cargos, reintentos y cambio de tarjeta |
| Seguimiento de cobros recurrentes | [workflows/seguimiento-cobros.md](workflows/seguimiento-cobros.md) | Cuotas (Charge) vs transacciones (Payment), masivo y uno a uno |
| Cancelar una suscripcion | [workflows/cancel-subscription.md](workflows/cancel-subscription.md) | DELETE /v3/suscription |
| Gestionar pausa y cambios de suscripcion de monto fijo | [workflows/gestionar-suscripcion-monto-fijo.md](workflows/gestionar-suscripcion-monto-fijo.md) | Pausar, reanudar, cambiar frecuencia |
| Cambiar el monto del aporte | [workflows/cambiar-monto.md](workflows/cambiar-monto.md) | Suscripcion nueva sin cobrar dos veces el mismo mes |
| Editar datos del socio | [workflows/editar-socio.md](workflows/editar-socio.md) | Actualizar cliente y suscripcion |
| Enviar link de cambio de tarjeta | [workflows/cambio-tarjeta.md](workflows/cambio-tarjeta.md) | PUT /v3/suscription/{id}/changecard |
| Link seguro de inscripcion de tarjeta | [workflows/link-inscripcion.md](workflows/link-inscripcion.md) | Adaptador para alta pendiente y socio existente |
| Reintentar cobros rechazados segun motivo | [workflows/reintento-cobro-rechazado.md](workflows/reintento-cobro-rechazado.md) | GET /v3/charge/{id}/retry segun codigo de rechazo |
| Sincronizar VirtualPOS a base central | [workflows/sync-virtualpos.md](workflows/sync-virtualpos.md) | Job paginado: clientes, planes, suscripciones, cargos, pagos |
| Exportar todos los objetos de VirtualPOS | [workflows/exportar-objetos-completos.md](workflows/exportar-objetos-completos.md) | Volcado completo para historico |

## Recursos documentados

Los archivos en [resources/](resources/) cubren el contrato detallado de cada recurso de la API:

- [authentication.md](resources/authentication.md) — API key, firma JWT (HS256), ejemplos
- [clients.md](resources/clients.md) — Objeto Client (`cli_...`), endpoints y upsert
- [plans.md](resources/plans.md) — Planes MONTO_FIJO y MONTO_VARIABLE
- [subscriptions.md](resources/subscriptions.md) — Suscriptions PAT, estados y changecard
- [charges.md](resources/charges.md) — Cargos programados (`cid_...`), retry e idempotencia
- [payments.md](resources/payments.md) — Payments (`order.uuid`), Web Checkout y Rule Set
- [deposits.md](resources/deposits.md) — Abonos diarios: resumen, ventas y retenciones
- [payouts.md](resources/payouts.md) — Transferencias salientes (mTLS)
- [webhooks.md](resources/webhooks.md) — Callbacks de Payment, Suscription y Payout
- [errors.md](resources/errors.md) — Objeto Error (E-001..E-116) y Objeto Rechazo
- [pagination.md](resources/pagination.md) — page/limit, diferencias entre endpoints
- [sandbox.md](resources/sandbox.md) — Tarjetas y datos de prueba
- [discrepancies.md](resources/discrepancies.md) — Diferencias doc oficial vs borrador vs Postman
- [quick-checkout.md](resources/quick-checkout.md) — Formulario embebido

## Referencia tecnica plana

El archivo [docs/integrations/virtualpos.md](../virtualpos.md) contiene:
- Comportamiento observado de `charge_program`, relacion cargo-pago y cargos historicos incompletos
- Controles de escritura (`VIRTUALPOS_WRITES_ENABLED`)
- Estado de webhooks y TBDs de autenticidad

---

## Bloqueantes y pendientes activos

| Clave | Descripcion | Impacto |
|---|---|---|
| **V-1** | No confirmado que `GET /v3/suscriptions` devuelva `charge_program` completo (como el ejemplo oficial). Pendiente validacion en sandbox. | El job diario de seguimiento de cobros depende de este campo masivo |
| **V-2** | No confirmado que una cuota `pagado` o `rechazado` traiga `payment.order.uuid` en `GET /v3/charge/{id}`. | El puente cuota → transaccion requiere confirmacion |
| **V-3** | No confirmado que `GET /v3/payments` incluya transacciones de cuotas recurrentes (no solo pagos spot). | Afecta el paso 4 del job de seguimiento y cuadratura |
| **V-4** | Un reintento de cuota rechazada: no confirmado si reutiliza el mismo Payment o crea otro. | Define como se asocian intentos a la misma cuota |
| **charge_program** | Los cargos operativos se extraen de `charge_program` embebido en la suscripcion. Los cargos locales no conservan el Payment embebido ni la relacion verificable. Requiere enriquecimiento por detalle de proveedor para motivos de rechazo historicos. | Calidad de datos en seguimiento y recuperacion |
| **return_url en changecard** | `PUT /v3/suscription/{id}/changecard` no acepta `return_url`. El socio no vuelve a nuestra pagina; la confirmacion depende del job. Pendiente consulta a soporte. | UX del flujo de cambio de tarjeta |
| **Webhooks** | La autenticidad de los callbacks de VirtualPOS es TBD (sin firma documentada). No se implementara receptor hasta verificar. | No hay notificaciones en tiempo real verificables |
