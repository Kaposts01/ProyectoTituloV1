# Payku — Documentación de integración (Chile)

> Índice principal de la integración con Payku.
> Fuente de verdad: documentación oficial de Payku para Chile (especificación OpenAPI **v2.1.01**).
> Última revisión contra la documentación oficial: **2026-10-12**.

---

## Cómo leer esta documentación

Usamos tres etiquetas para que siempre sepas qué tan seguro es un dato:

| Etiqueta | Significado |
|---|---|
| ✅ **Confirmado** | Aparece explícitamente en la documentación oficial de Payku. |
| ⚠️ **No confirmado en la documentación oficial de Payku.** | La documentación no lo dice, lo dice de forma ambigua o se contradice. Hay que validarlo en sandbox. |
| 💡 **Inferencia** | Conclusión técnica nuestra a partir de lo documentado. Útil para diseñar, pero no es contrato de Payku. |

Todo lo pendiente de validar está reunido en [open-questions.md](open-questions.md).

---

## 1. Qué es Payku dentro del proyecto

Payku es una pasarela de pagos chilena. Para nosotros es **una fuente más de datos de pagos** (junto a Toku y VirtualPOS). Nos interesa sobre todo su **API de Suscripciones**: clientes con tarjeta inscrita a los que Payku les cobra de forma recurrente según un plan.

Flujo de datos objetivo:

```text
Payku API  →  STG_PAYKU (raw)  →  ETL / normalización  →  BD_CENTRAL
```

---

## 2. Ambientes y URL base

| Ambiente | URL base | Uso |
|---|---|---|
| Producción | `https://app.payku.cl` | Transacciones reales ✅ |
| Sandbox | `https://des.payku.cl` | Pruebas sin afectar datos reales ✅ |

- Todos los endpoints cuelgan de `/api/...` (por ejemplo `https://des.payku.cl/api/sususcription`). ✅
- Los tokens se obtienen en la cuenta Payku → sección **Integración → Tokens integración y API**. ✅
- 💡 Los tokens de sandbox y producción son distintos (cada ambiente es una cuenta distinta). ⚠️ No confirmado.
- La portada de la documentación menciona también `https://testing-apirest.payku.cl/`, pero no explica para qué sirve. ⚠️ No confirmado.

Tarjetas de prueba para sandbox: ver [authentication.md § Tarjetas de prueba](authentication.md#tarjetas-de-prueba-sandbox).

---

## 3. Autenticación (resumen)

| Header | Valor | Cuándo |
|---|---|---|
| `Authorization` | `Bearer <TOKEN_PUBLICO>` | **Siempre** ✅ |
| `Sign` | HMAC-SHA256 de la ruta + parámetros, con el `TOKEN_PRIVADO` | Suscripciones, anulaciones y mall ✅ (y según ejemplos: wallet y actualizar cliente marketplace) |
| `Content-Type` | `application/json` | En requests con body |

Detalle completo, algoritmo y código Python verificado: [authentication.md](authentication.md).

---

## 4. Recursos principales

Payku **no** está organizado como Toku ni VirtualPOS. Estos son sus recursos reales:

| Recurso Payku | Ruta | Qué es | Documento |
|---|---|---|---|
| Cliente de suscripción | `/api/suclient` | La persona que se suscribe (nuestro socio/donante). | [customers.md](customers.md) |
| Plan | `/api/suplan` | Producto recurrente (monto fijo, consumo o monto variable). Define las URL de notificación. | [plans.md](plans.md) |
| Suscripción | `/api/sususcription`, `/api/sususcriptionv3` | Vincula un **cliente** con un **plan** y una tarjeta. | [subscriptions.md](subscriptions.md) |
| Cobro de suscripción | `/api/sutransaction` + `transactions[]` / `paid[]` dentro de la suscripción | Cada cargo hecho a la tarjeta del suscriptor. | [subscription-charges.md](subscription-charges.md) |
| Tarjeta | `/api/suinscriptionscards`, `/api/suscriptionsdeletecards` | Tarjetas inscritas a una suscripción. | [cards.md](cards.md) |
| Transacción (pago único) | `/api/transaction` | Orden de pago única (Webpay, transferencia, etc.). | [transactions.md](transactions.md) |
| Notificaciones (callbacks) | URL del comercio | Payku avisa cambios de suscripción, cobros, pagos, anulaciones y payouts. | [webhooks.md](webhooks.md) |
| Suscripción de consumo | mismos endpoints `su*` | Variante para cobros únicos a demanda sobre tarjeta inscrita. | [consumption-subscriptions.md](consumption-subscriptions.md) |
| Anulación | `/api/nullification` | Reembolso total o parcial de una transacción. | [refunds.md](refunds.md) |
| Conciliación | `/api/conciliation` | Liquidaciones: qué se depositó, cuándo y con qué comisión. | [reconciliation.md](reconciliation.md) |
| Wallet | `/api/wallet`, `/api/payout` | Billetera Payku: saldo, movimientos, pagos a terceros, retiros. | [wallet.md](wallet.md) |
| Marketplace | `/api/maclient`, `/api/maaffiliation` | Reparto de pagos entre comercios afiliados. | [marketplace.md](marketplace.md) |
| Mall | `/api/mall` | Un solo pago repartido entre varias tiendas. | [mall.md](mall.md) |
| Evento | `/api/event` | Venta de eventos con reparto a beneficiarios. | [events.md](events.md) |
| Escrow | `/api/escrow` | Autorizar liquidación de transacciones (cuentas escrow). | [escrow.md](escrow.md) |
| Catálogos | `/api/banks`, `/api/paymentmethods` | Bancos y medios de pago. | [catalogs.md](catalogs.md) |

> **Sobre `payments.md`:** Payku **no** tiene un recurso "payment" propio. La información de pago vive (a) en el objeto `payment` dentro de una transacción ([transactions.md](transactions.md)), (b) en los cobros de una suscripción ([subscription-charges.md](subscription-charges.md)) y (c) en el catálogo de medios de pago ([catalogs.md](catalogs.md)). Por eso no creamos `payments.md`.

---

## 5. Mapa de relaciones

```text
PLAN (pl…)                                  ← define url_notify_suscription / url_notify_payment
  │ 1
  │
  │ N
SUSCRIPCIÓN (su…) ──── N:1 ──── CLIENTE (cl…)
  │   status: register | active | finish | delete | cancel | suspended
  │
  ├── TARJETAS (surec…)  active_cards[] / cards
  │
  └── COBROS  transactions[]  (V1)   /   paid[]  (V3, por ciclo con reintentos)
          transaction (número) + verification_key + order

TRANSACCIÓN DE PAGO ÚNICO (trx… / número)   ← independiente de suscripciones ⚠️
  └── payment { payment_key (pra…), transaction_key, media, deposit_date, … }

CONCILIACIÓN ─── transaction[] { transaction_id, payment_key, order, fee, amount_deposit }
```

Detalle de cada relación (qué ID conecta, cardinalidad, desde qué endpoint se obtiene): [data-model.md](data-model.md).

---

## 6. Índice de documentos

**Transversales**
- [authentication.md](authentication.md) — Bearer + firma `Sign`, código Python, tarjetas de prueba.
- [errors.md](errors.md) — Códigos HTTP, errores con HTTP 200, formatos de error, reintentos.
- [pagination.md](pagination.md) — `page` / `per_page`, límites, filtros de fecha y estado.
- [statuses.md](statuses.md) — Inventario de todos los estados de Payku.
- [data-model.md](data-model.md) — Relaciones, identificadores, qué va a STG y qué al modelo normalizado.

**Recursos**
- Suscripciones: [customers.md](customers.md) · [plans.md](plans.md) · [subscriptions.md](subscriptions.md) · [subscription-charges.md](subscription-charges.md) · [cards.md](cards.md) · [consumption-subscriptions.md](consumption-subscriptions.md)
- Pagos: [transactions.md](transactions.md) · [refunds.md](refunds.md) · [reconciliation.md](reconciliation.md) · [webhooks.md](webhooks.md)
- Otros productos: [wallet.md](wallet.md) · [marketplace.md](marketplace.md) · [mall.md](mall.md) · [events.md](events.md) · [escrow.md](escrow.md) · [catalogs.md](catalogs.md)

**Flujos** (`workflows/`)
- [alta-socio.md](workflows/alta-socio.md): alta completa desde el formulario web (cliente → plan fijo o variable → suscripción → primer aporte inmediato).
- [link-inscripcion.md](workflows/link-inscripcion.md): adaptador del link seguro para inscribir la tarjeta (alta pendiente y socio existente).
- [editar-socio.md](workflows/editar-socio.md): editar nombre, email y teléfono del cliente (el RUT no se puede por API).
- [seguimiento-cobros.md](workflows/seguimiento-cobros.md): seguimiento mensual de cobros (sin objeto cuota: cuota esperada vs ciclos V3, cobros y conciliación).
- [cambiar-monto.md](workflows/cambiar-monto.md): cambiar el monto del aporte (sin API: portal de Payku o suscripción nueva).
- [create-customer.md](workflows/create-customer.md)
- [create-subscription.md](workflows/create-subscription.md)
- [get-subscriptions.md](workflows/get-subscriptions.md)
- [cancel-subscription.md](workflows/cancel-subscription.md)
- [suspend-subscription.md](workflows/suspend-subscription.md)
- [update-card.md](workflows/update-card.md)
- [get-transactions.md](workflows/get-transactions.md)
- [sync-payku.md](workflows/sync-payku.md)

**Herramientas y control**
- [postman.md](postman.md) — Revisión de nuestra colección vs la documentación oficial.
- [open-questions.md](open-questions.md) — Todo lo que falta validar en sandbox.

---

## 7. Flujos principales (resumen)

1. **Alta de suscriptor:** crear cliente → crear suscripción a un plan → enviar al cliente a la `url` devuelta para inscribir tarjeta (cobro de validación de $50) → Payku notifica `active`. Ver [create-subscription.md](workflows/create-subscription.md). El alta completa desde el formulario web, con catálogo de planes y primer aporte inmediato, está en [alta-socio.md](workflows/alta-socio.md).
2. **Cobro recurrente (plan de monto fijo):** Payku cobra solo, a partir del mes siguiente, y notifica cada cobro a `url_notify_payment`. Ver [subscription-charges.md](subscription-charges.md).
3. **Cobro a demanda (plan de consumo):** nosotros llamamos `POST /api/sutransaction`. Ver [consumption-subscriptions.md](consumption-subscriptions.md).
4. **Cambio de tarjeta / recuperación:** `POST /api/suinscriptionscards` → nueva `url` de inscripción. Si la suscripción estaba suspendida por reintentos, Payku puede cobrar lo atrasado y reactivarla sola. Ver [update-card.md](workflows/update-card.md).
5. **Baja:** `DELETE /api/sususcription/{id}`. Ver [cancel-subscription.md](workflows/cancel-subscription.md).
6. **Sincronización:** webhooks + barrido periódico con `sususcriptionv3`. Ver [sync-payku.md](workflows/sync-payku.md).

---

## 8. Consideraciones importantes (léelas antes de programar)

1. **Un HTTP 200 no significa éxito.** Payku devuelve muchos errores con HTTP 200 y `"status": "failed"`. Siempre revisa el campo `status` del JSON. ✅ → [errors.md](errors.md)
2. **Sin filtros de fecha, los listados traen solo el día de hoy.** `date_init` / `date_end` toman la fecha actual por defecto. Una carga inicial sin fechas devuelve casi nada. ✅ → [pagination.md](pagination.md)
3. **No hay metadatos de paginación** (total, siguiente página). Se recorre hasta que una página venga vacía o incompleta. 💡 → [pagination.md](pagination.md)
4. **No existe un endpoint para suspender ni para reactivar** una suscripción. `suspended` lo pone Payku (p. ej. tras agotar reintentos). ✅/⚠️ → [suspend-subscription.md](workflows/suspend-subscription.md)
5. **Las notificaciones no traen firma documentada.** Trátalas como un aviso y confirma siempre consultando la API. 💡 → [webhooks.md](webhooks.md)
6. **Las URL de notificación se configuran en el plan**, no al crear la suscripción. Hay una contradicción en la documentación oficial. ⚠️ → [plans.md](plans.md)
7. **No hay idempotencia documentada.** Usa siempre un `order` propio y único y consulta antes de reintentar un POST. 💡 → [errors.md](errors.md)
8. **Los tipos de dato no son consistentes.** Montos que a veces son `string` y a veces `int`; `status` vs `estatus` entre V1 y V3. Normaliza en el ETL, no en staging. ✅ → [data-model.md](data-model.md)
9. **El body de "Eliminar tarjeta" está contradicho** en la documentación (`suscription` en la tabla vs `card` en el ejemplo). ⚠️ → [cards.md](cards.md)

---

## 9. Diferencias con Toku y VirtualPOS (para no confundir conceptos)

| Concepto | Payku | Toku | VirtualPOS |
|---|---|---|---|
| Quién paga | `suclient` (cliente de suscripción) | `customer` | cliente |
| Qué se cobra | `suscription` a un `plan` | `subscription` (por producto) | suscripción / cargo programado |
| Cada cobro | **cobro dentro de la suscripción** (`transactions[]` / `paid[]`), identificado por un número de transacción y `verification_key` | `invoice` (documento de cobro) + `payment`/`transaction` | cargo programado |
| Reintentos | Visibles en V3: `paid[].try_number` por ciclo | Por invoice | Por cargo |
| ID externo nuestro | No hay campo dedicado en la suscripción; en el cliente usamos `additional_parameters` 💡 | `external_id` (idempotente) | — |

💡 **Regla práctica:** un "cobro" de Payku se parece más a un *intento de pago de un ciclo* que a un *invoice* de Toku. Payku no tiene un documento de deuda separado: el ciclo (`payment_cycle_day`) y sus intentos (`try_number`) viven dentro de la suscripción (V3).

---

## 10. Documentación oficial

| Tema | Enlace |
|---|---|
| Portada | https://docs.payku.com/ |
| Introducción | https://docs.payku.com/cl/introduction/ |
| Autenticación | https://docs.payku.com/cl/authentication/ |
| Seguridad (Bearer) | https://docs.payku.com/cl/api-security/ |
| Firma | https://docs.payku.com/cl/signature/ |
| Errores | https://docs.payku.com/cl/errors/ |
| Acceso a la API | https://docs.payku.com/cl/api-access/ |
| Tarjetas de prueba | https://docs.payku.com/cl/test-cards/ |
| Transacción | https://docs.payku.com/cl/api/transaction/ |
| Escrow | https://docs.payku.com/cl/api/escrow/ |
| Anulación | https://docs.payku.com/cl/api/refunds/ |
| Marketplace | https://docs.payku.com/cl/api/marketplace/ |
| Mall | https://docs.payku.com/cl/api/mall/ |
| Evento | https://docs.payku.com/cl/api/events/ |
| Suscripción | https://docs.payku.com/cl/api/subscriptions/ |
| Suscripción de consumo | https://docs.payku.com/cl/api/consumption-subscriptions/ |
| Wallet | https://docs.payku.com/cl/api/wallet/ |
| Conciliación | https://docs.payku.com/cl/api/reconciliation/ |
| Bancos | https://docs.payku.com/cl/api/banks/ |
| Métodos de pago | https://docs.payku.com/cl/api/payment-methods/ |
| Documentación completa en un archivo (Markdown) | https://docs.payku.com/ai/payku-docs-es.md |
| Colección Postman oficial | https://docs.payku.com/postman/payku-cl-es.postman_collection.json |
| Entorno Postman oficial | https://docs.payku.com/postman/payku-environment.postman_environment.json |

> El archivo `Payku_API_Documentacion.md` de esta carpeta es una copia de `payku-docs-es.md` (misma versión **v2.1.01**). Si Payku publica una versión nueva, hay que volver a revisar estos documentos.
