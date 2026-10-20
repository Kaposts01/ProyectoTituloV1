# Integración Toku — Índice

> Verificado contra la documentación oficial el **2026-10-12**.
> Las páginas de referencia de endpoints declaran el contrato `x-toku-api-version` **2026-10-08** (algunas páginas todavía muestran 2026-09-22 o 2026-09-07).
> Fuente principal: <https://docs.trytoku.com/docs/via-api-2> · Índice completo: <https://docs.trytoku.com/llms.txt>

## Cómo leer esta documentación

Cada afirmación lleva una de estas etiquetas:

| Etiqueta | Significado |
|---|---|
| **[Confirmado]** | Aparece explícitamente en la documentación oficial de Toku. |
| **[Inferencia]** | Deducción técnica razonable a partir de la doc, pero que Toku no dice textualmente. |
| **[Recomendación]** | Decisión de arquitectura o buena práctica nuestra. |
| **[No confirmado]** | No confirmado en la documentación oficial de Toku. Hay que probarlo o preguntarlo a Toku. |

Para no repetir lo mismo en cada endpoint, los headers de autenticación, los errores comunes y la paginación están en archivos transversales. Cada endpoint solo documenta lo que tiene de propio.

## Qué es Toku dentro del proyecto

Toku es la plataforma de **cobranza recurrente** de TECHO Chile. Guarda a los socios/donantes (*Customers*), sus planes de aporte (*Subscriptions*), las cuotas que se generan (*Invoices*), los medios de pago inscritos (*Payment Methods*, PAC/PAT) y los cobros realizados (*Transactions*).

En nuestra arquitectura, Toku es **fuente de datos**:

```text
Toku ──API / Webhooks──▶ STG_TOKU (raw) ──ETL──▶ BD_CENTRAL (modelo normalizado)
```

## Datos de conexión

| Dato | Valor | Estado |
|---|---|---|
| URL base | `https://api.trytoku.com` | [Confirmado] |
| Protocolo | Solo HTTPS, puerto 443 | [Confirmado] |
| Ambientes | **Uno solo: producción.** No hay sandbox documentado. | [Confirmado] |
| Autenticación | Header `x-api-key` (o bien OAuth M2M con `Authorization: Bearer`, que si se activa **deshabilita** la API key) | [Confirmado] |
| Formato | JSON (`Content-Type: application/json`) | [Confirmado] |

Detalle completo en [authentication.md](authentication.md).

## Recursos principales

| Recurso | Prefijo de ID | Qué representa | Documento |
|---|---|---|---|
| Account (cuenta de cobro) | `acc_` | Una cuenta de cobro de la organización. Una organización puede tener varias. | [authentication.md](authentication.md) |
| Customer | `cus_` | La persona que paga (socio/donante). | [customers.md](customers.md) |
| Subscription | `sub_` | Plan de pago / producto de un Customer. Puede ser recurrente o no. | [subscriptions.md](subscriptions.md) |
| Invoice | `in_` | Una deuda o cuota. Siempre pertenece a una Subscription. | [invoices.md](invoices.md) |
| Payment Method | `pm_` | Medio de pago automático inscrito (tarjeta, cuenta bancaria, Pix). | [payment-methods.md](payment-methods.md) |
| Customer Collection Account | (sin ID propio) | Cuenta bancaria registrada para cobrar por PAC. | [payment-methods.md](payment-methods.md) |
| Transaction | (sin prefijo documentado) | Un movimiento de dinero (cobro, reversa, contracargo). | [transactions.md](transactions.md) |
| Payment Intent | (sin prefijo documentado) | La parte de una Transaction aplicada a **una** Invoice. | [transactions.md](transactions.md) |
| Webhook Endpoint | `whe_` | URL nuestra que recibe eventos. | [webhooks.md](webhooks.md) |

> **No existe un recurso "Payment"** en la API pública de Toku. Lo que en otros proveedores se llama "pago" en Toku se modela con **Transaction + Payment Intent**. Por eso no hay un `payments.md`: su contenido está en [transactions.md](transactions.md).

## Mapa de relaciones (validado)

```text
ORGANIZATION
   └── ACCOUNT (acc_)  ·· cuenta de cobro
          │
CUSTOMER (cus_)
   ├── SUBSCRIPTION (sub_)            1:N   subscription.customer
   │      └── INVOICE (in_)           1:N   invoice.subscription (+ invoice.customer)
   │             └── PAYMENT INTENT   1:N   payment_intent.id_invoice
   │                    └── pertenece a una TRANSACTION (1 Transaction : N Payment Intents)
   ├── PAYMENT METHOD (pm_)           1:N   asociado al Customer
   │      └── ↔ SUBSCRIPTION          N:M   payment_method → subscription_ids[] / product_ids[]
   └── CUSTOMER COLLECTION ACCOUNT    1:N   (customer, subscription opcional)
```

Lo importante:

- **Una Transaction puede pagar varias Invoices**, y una Invoice puede recibir varios pagos (pagos parciales, reintentos). La relación Transaction ↔ Invoice es **N:M** y se resuelve a través de los **Payment Intents**. [Confirmado: glosario + schema de Transaction]
- El modelo conceptual inicial `CUSTOMER → SUBSCRIPTION → INVOICE → PAYMENT` es correcto en las tres primeras capas. La cuarta capa en Toku es `PAYMENT INTENT → TRANSACTION`.

Detalle de IDs, cardinalidades y qué guardar: [data-model.md](data-model.md).

## Índice de documentos

**Transversales**
- [authentication.md](authentication.md): autenticación, headers, ambientes, IPs, versionamiento.
- [pagination.md](pagination.md): los dos tipos de paginación y qué endpoint usa cada uno.
- [errors.md](errors.md): formato de error, códigos HTTP, códigos `TKxxxxx`, códigos de cobro y límites de tasa.
- [statuses.md](statuses.md): inventario de todos los estados de Toku.
- [data-model.md](data-model.md): relaciones, identificadores y mapping a nuestro modelo interno.

**Recursos**
- [customers.md](customers.md)
- [subscriptions.md](subscriptions.md)
- [invoices.md](invoices.md)
- [transactions.md](transactions.md) (Transactions y Payment Intents)
- [payment-methods.md](payment-methods.md) (Payment Methods, asociación a Subscriptions y Customer Collection Accounts)
- [webhooks.md](webhooks.md)

**Flujos**
- [workflows/alta-socio.md](workflows/alta-socio.md): alta completa desde el formulario web (Customer → Subscription en pausa → Checkout de inscripción → reactivación). **Bloqueado** hasta que Toku configure el flujo de inscripción.
- [workflows/link-inscripcion.md](workflows/link-inscripcion.md): adaptador del link seguro para inscribir el medio de pago (alta pendiente y socio existente). Mismo bloqueante que el alta.
- [workflows/editar-socio.md](workflows/editar-socio.md): editar nombre, email, teléfono y RUT del Customer (nunca `external_id`).
- [workflows/seguimiento-cobros.md](workflows/seguimiento-cobros.md): seguimiento mensual de cobros (Invoices ↔ Transactions vía Payment Intents, motivos de rechazo y liquidación).
- [workflows/cambiar-monto.md](workflows/cambiar-monto.md): cambiar el monto del aporte por API (Subscription + cuotas no cobradas).
- [workflows/create-customer.md](workflows/create-customer.md)
- [workflows/create-subscription.md](workflows/create-subscription.md)
- [workflows/create-invoice.md](workflows/create-invoice.md)
- [workflows/enroll-payment-method.md](workflows/enroll-payment-method.md): inscribir un medio de pago y asociarlo a una suscripción.
- [workflows/cancel-subscription.md](workflows/cancel-subscription.md): pausar, reanudar o eliminar.
- [workflows/reconcile-payment.md](workflows/reconcile-payment.md)
- [workflows/sync-toku.md](workflows/sync-toku.md): sincronización Toku → STG_TOKU → BD_CENTRAL.

**Mantenimiento**
- [postman-audit.md](postman-audit.md): diferencias entre la colección Postman, las notas internas y la doc oficial, con correcciones.

## Flujos principales

| Necesito… | Flujo |
|---|---|
| Dar de alta a un socio desde el formulario web | [workflows/alta-socio.md](workflows/alta-socio.md) |
| Registrar un socio | `POST /customers` (upsert por `external_id`) |
| Crear su plan mensual | `POST /subscriptions` con `is_recurring: true` (upsert por `product_id`) |
| Cargar una deuda puntual | `POST /invoices` (upsert por `product_id` + `due_date` o `product_id` + `invoice_external_id`) |
| Inscribir PAC por API | `POST /customer-collection-accounts` |
| Asociar medio de pago a un plan | `POST /subscriptions/associate/payment-method` |
| Saber si una cuota está pagada | `general_status` + `in_progress` de la Invoice, o el webhook `invoice.paid` |
| Traer todos los cobros | `GET /transactions` (paginado por página, **1 req/s**) |
| Enterarme en tiempo real | Webhooks (`invoice.paid`, `transaction.success`, `transaction.bulk_success`, …) |

## Consideraciones importantes

1. **Todo es producción.** No hay sandbox. Usar `product_id` y `external_id` con prefijo `TEST-` y limpiarlos con `DELETE` después de probar. [Confirmado + Recomendación]
2. **Los upserts son idempotentes por clave de negocio, no por header.** Customer por `external_id`; Subscription por `(Account, product_id)`; Invoice por `product_id + due_date` o `product_id + invoice_external_id`. [Confirmado]
3. **Límites de tasa:** 20 req/s en Customers, Subscriptions e Invoices; **1 req/s en Transactions**. Payment Methods no publica un número. [Confirmado]
4. **No hay filtro `updated_at`** en los listados: los filtros `start_date`/`end_date` filtran por **fecha de creación** (en Transactions, por fecha de transacción). La sincronización incremental de cambios depende de webhooks más una reconciliación periódica. [Confirmado + Inferencia]
5. **La firma de webhooks solo cubre `{timestamp}.{id}`, no el body.** Recomendamos volver a consultar el recurso por API antes de actualizar BD_CENTRAL. Ver [webhooks.md](webhooks.md). [Confirmado + Recomendación]
6. **`x-api-version`:** si no se envía, Toku deriva la versión de la fecha de creación de la organización. Conviene fijarla explícitamente, pero solo después de validar los mappers. [Confirmado + Recomendación]
7. **Datos sensibles:** Payment Methods y Collection Accounts traen números de cuenta completos, RUT y tokens. Ver la sección de seguridad en [data-model.md](data-model.md).

## Enlaces oficiales

- Introducción: <https://docs.trytoku.com/reference/introduccion>
- Autenticación: <https://docs.trytoku.com/reference/autenticacion>
- Conexión y ambientes: <https://docs.trytoku.com/reference/conexion-y-ambientes>
- Headers y convenciones: <https://docs.trytoku.com/reference/headers-y-convenciones>
- Errores: <https://docs.trytoku.com/reference/errores-y-codigos-de-respuesta>
- Límites de tasa: <https://docs.trytoku.com/reference/rate-limits>
- Versionamiento: <https://docs.trytoku.com/reference/versionamiento>
- Webhooks (guía): <https://docs.trytoku.com/docs/webhooks>
- Glosario: <https://docs.trytoku.com/docs/glosario>
