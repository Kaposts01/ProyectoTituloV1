# Payku — Integración operacional

> Canal: Payku  
> Ultima revision: 2026-10-15  
> Documentacion oficial: https://docs.payku.com/ (especificacion OpenAPI v2.1.01)  
> Referencia tecnica plana: [docs/integrations/payku.md](../payku.md)

---

## Flujos disponibles

| Flujo | Archivo | Descripcion breve |
|---|---|---|
| Alta de socio (cliente + plan + suscripcion + primer aporte) | [workflows/alta-socio.md](workflows/alta-socio.md) | Crea suclient, suscripcion a plan fijo o variable, link de tarjeta y primer aporte |
| Link seguro de inscripcion de tarjeta | [workflows/link-inscripcion.md](workflows/link-inscripcion.md) | Adaptador para alta pendiente (Q-29) y socio existente |
| Editar datos del socio | [workflows/editar-socio.md](workflows/editar-socio.md) | Actualizar nombre, email, telefono (el RUT no se puede por API) |
| Seguimiento de cobros recurrentes | [workflows/seguimiento-cobros.md](workflows/seguimiento-cobros.md) | Ciclos V3 (paid[]) vs cobros (transactions[]) y conciliacion; cuota esperada calculada por nosotros |
| Cambiar el monto del aporte | [workflows/cambiar-monto.md](workflows/cambiar-monto.md) | Via portal (normal) o suscripcion nueva por API (alternativa); sin PUT de monto |
| Crear un cliente de suscripcion | [workflows/create-customer.md](workflows/create-customer.md) | POST /api/suclient |
| Crear una suscripcion | [workflows/create-subscription.md](workflows/create-subscription.md) | POST /api/sususcription con plan fijo o variable |
| Consultar suscripciones | [workflows/get-subscriptions.md](workflows/get-subscriptions.md) | GET /api/sususcription (V1) y sususcriptionv3 (V3) |
| Cancelar una suscripcion | [workflows/cancel-subscription.md](workflows/cancel-subscription.md) | DELETE /api/sususcription/{id} |
| Suspender una suscripcion | [workflows/suspend-subscription.md](workflows/suspend-subscription.md) | Estado suspended: Payku lo gestiona (no hay endpoint propio) |
| Actualizar tarjeta | [workflows/update-card.md](workflows/update-card.md) | POST /api/suinscriptionscards; la nueva URL de inscripcion |
| Consultar transacciones | [workflows/get-transactions.md](workflows/get-transactions.md) | GET /api/transaction con ventanas de fecha |
| Sincronizar Payku a base central | [workflows/sync-payku.md](workflows/sync-payku.md) | Job paginado: suscripciones, ciclos V3 y transacciones embebidas |

## Recursos documentados

Los archivos en [resources/](resources/) cubren el contrato detallado de cada recurso de la API:

- [authentication.md](resources/authentication.md) — Bearer + firma Sign (HMAC-SHA256), tarjetas de prueba
- [customers.md](resources/customers.md) — Cliente de suscripcion (`cl...`)
- [plans.md](resources/plans.md) — Plan fijo, variable y de consumo
- [subscriptions.md](resources/subscriptions.md) — Suscripcion (`su...`), estados Lista A, V1 y V3
- [subscription-charges.md](resources/subscription-charges.md) — Cobros dentro de la suscripcion (`transactions[]`, `paid[]`)
- [cards.md](resources/cards.md) — Tarjetas inscritas (`surec...`)
- [transactions.md](resources/transactions.md) — Transaccion de pago unico (`trx...`)
- [consumption-subscriptions.md](resources/consumption-subscriptions.md) — Suscripciones de consumo a demanda
- [webhooks.md](resources/webhooks.md) — Callbacks de suscripcion y cobro (sin firma documentada)
- [errors.md](resources/errors.md) — HTTP 200 con `status: failed`, formatos de error
- [pagination.md](resources/pagination.md) — page/per_page, filtros de fecha, limites
- [statuses.md](resources/statuses.md) — Inventario de estados de Payku (Listas A y B)
- [data-model.md](resources/data-model.md) — Relaciones, identificadores, que va a STG
- [open-questions.md](resources/open-questions.md) — Todo lo pendiente de validar en sandbox
- [reconciliation.md](resources/reconciliation.md) — POST /api/conciliation (ventanas de 30 dias)
- [refunds.md](resources/refunds.md) — Anulaciones: DELETE /api/nullification
- [wallet.md](resources/wallet.md) — Billetera Payku: saldo, movimientos, pagos a terceros
- [marketplace.md](resources/marketplace.md) — Reparto entre comercios afiliados
- [mall.md](resources/mall.md) — Un solo pago repartido entre varias tiendas
- [events.md](resources/events.md) — Venta de eventos con reparto
- [escrow.md](resources/escrow.md) — Autorizacion de liquidacion de transacciones
- [catalogs.md](resources/catalogs.md) — Bancos y medios de pago
- [postman.md](resources/postman.md) — Revision de la coleccion vs doc oficial

## Referencia tecnica plana

El archivo [docs/integrations/payku.md](../payku.md) contiene:
- Comportamiento observado del sync (transacciones embebidas, cobertura historica no certificada)
- Identificador historico `transaction` cuando el payload no trae `id`
- Backfill desde source_records (`scripts/maintenance/backfill_payku_transactions.py`)
- Controles de escritura (`PAYKU_WRITES_ENABLED`)
- Estado de webhooks: sin firma documentada, receptor no implementado hasta verificar autenticidad

---

## Preguntas abiertas criticas

| Clave | Descripcion | Impacto |
|---|---|---|
| **Q-06** | No confirmado si los cobros de suscripcion aparecen en `/api/transaction` y en la conciliacion con la misma clave que en `paid[]`. | El seguimiento de cobros no puede enlazar ciclos con conciliacion de forma confiable |
| **Q-08** | La clave estable del cobro no esta documentada. `paid[].transactions[]` no esta especificado. No se sabe que clave une el ciclo V3 con el cobro del detalle (`transaction` numero). | El job de seguimiento no puede enlazar ciclo <-> cobro de forma determinista |
| **Q-27** | Plan variable: no se sabe si cobra al activarse la suscripcion nueva (afecta cambiar-monto camino B). | Riesgo de doble cobro o mes sin cobro al cambiar monto |
| **Q-29** | No confirmado si `POST /api/suinscriptionscards` genera una `url` nueva para una suscripcion en estado `register`. | El link de inscripcion para un alta pendiente depende de este comportamiento |
| **Webhooks** | Sin firma documentada. Los callbacks no se pueden autenticar; `verification_key` es del cobro, no del aviso. | Receptor de webhooks no implementado; seguimiento solo por job periodico |
| **Cobertura historica** | El sync no certifica completitud de transacciones historicas. Filtros de fecha pueden devolver cero registros. | Las metricas del dashboard describen la cobertura local, no el historial completo del proveedor |
