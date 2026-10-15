# Inventario de estados de Payku

> Regla: **primero guardamos el valor original de Payku tal cual** (en staging), y **después** lo mapeamos a nuestro modelo normalizado. Nunca reemplazamos el valor original por nuestra interpretación.

Columnas:
- **Estado Payku:** valor literal (respetando mayúsculas, espacios y errores de tipeo de Payku).
- **Significado:** según la documentación oficial; si no hay descripción, se indica.
- **Acción interna (propuesta):** 💡 qué debería hacer nuestro backend. Es una propuesta nuestra, no de Payku.

---

## 1. Suscripción

Campo: `status` (V1, detalle, callback, dentro del cliente) · `estatus` (**V3**) ✅

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Suscripción | `register` | Creada; el cliente aún no completa la inscripción de tarjeta (respuesta de `POST /api/sususcription`). ✅ | Normalizado `PENDIENTE_ACTIVACION`. Recordar al socio si pasan X días sin activar. |
| Suscripción | `active` | Activa. Tras la activación Payku notifica `active`. ✅ | `ACTIVA`. Se esperan cobros. |
| Suscripción | `suspended` | Suspendida. Ocurre, entre otros casos, "por máximos intentos de cobros realizados". ✅ | `SUSPENDIDA`. Disparar flujo de cambio de tarjeta ([update-card.md](workflows/update-card.md)). |
| Suscripción | `cancel` | Sin descripción oficial. ⚠️ | `CANCELADA`. ⚠️ No sabemos quién la origina (¿cliente?, ¿comercio?). |
| Suscripción | `delete` | Sin descripción oficial. 💡 Probablemente el resultado de `DELETE /api/sususcription/{id}`. ⚠️ | `ELIMINADA`. Estado terminal. |
| Suscripción | `finish` | Sin descripción oficial. 💡 Probablemente fin por fecha `end` o por plan con término. ⚠️ | `FINALIZADA`. Estado terminal. |

Campo adicional en V1: `last_status_current_payment` (ejemplo: `pending`). ✅ existe — ⚠️ sus valores posibles no están documentados.

Historial de cambios: `logs.status[]` con `change_date`, `initial_status`, `final_status`. ✅ Muy útil para auditoría y sincronización.

---

## 2. Cobro de suscripción

⚠️ **La documentación tiene dos listas distintas de estados para el mismo concepto.** Hay que guardar ambas posibilidades.

### Lista A — `subcriptions.transactions[].status` dentro del **cliente** (`GET/PUT /api/suclient/{id}`, `GET /api/suclient/customers`) ✅

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Cobro | `pending` | Sin descripción. 💡 En proceso. | `PENDIENTE` |
| Cobro | `success` | Sin descripción. 💡 Cobrado. | `PAGADO` → registrar donación/pago. |
| Cobro | `retry` | Sin descripción. 💡 Falló y se reintentará. | `REINTENTANDO` |
| Cobro | `canceled by customer` | Sin descripción. 💡 Cancelado por el cliente. | `CANCELADO` (origen: cliente) |
| Cobro | `canceled by paymaster` | Sin descripción. 💡 Cancelado por el comercio (nosotros). Aparece también como `canceled by paymáster` (con tilde) en otra sección. ⚠️ | `CANCELADO` (origen: comercio). Normalizar ambos valores. |
| Cobro | `canceled by payku` | Sin descripción. 💡 Cancelado por Payku. | `CANCELADO` (origen: Payku) |
| Cobro | `maximum attempt limit` | Sin descripción. 💡 Se agotaron los reintentos. | `FALLIDO_DEFINITIVO`. Relacionado con suscripción `suspended`. |
| Cobro | `first payment rejected` | Sin descripción. 💡 Falló el primer cobro. | `RECHAZADO_PRIMER_COBRO`. Contactar al socio. |
| Cobro | `payment consumes failed` | Sin descripción. 💡 Falló un cobro de plan de consumo. | `FALLIDO` |

### Lista B — `transactions[].status` en **detalle de suscripción** (`GET /api/sususcription/{id}`), respuesta de `POST /api/sutransaction` y **callback de cobro** ✅

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Cobro | `pending` | Sin descripción. | `PENDIENTE` |
| Cobro | `success` | Sin descripción. | `PAGADO` |
| Cobro | `rejected` | Sin descripción. | `RECHAZADO` |
| Cobro | `refunded partial` | Sin descripción. 💡 Reembolso parcial. | `REEMBOLSADO_PARCIAL` |
| Cobro | `refunded` | Sin descripción. 💡 Reembolso total. | `REEMBOLSADO` |

### V3 — `paid[].status` (`GET /api/sususcriptionv3`)

Ejemplo: `success`. ✅ existe — ⚠️ **la lista de valores no está documentada.** 💡 Probablemente comparte valores con la Lista A o B.

> ⚠️ Pendiente (Q-05 en [open-questions.md](open-questions.md)): observar en sandbox qué valores devuelve realmente cada endpoint.

---

## 3. Cliente de suscripción

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Cliente | `active` | Ejemplo en crear, obtener y actualizar cliente. ✅ Lista de valores **no documentada**. ⚠️ | Guardar tal cual. |
| Respuesta de `DELETE /api/suclient/{id}` | `success` | Resultado de la operación (no es un estado del cliente). ✅ | ⚠️ No sabemos qué estado queda el cliente después. |

---

## 4. Plan

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Plan | `active` | Ejemplo en obtener plan. ✅ Lista **no documentada**. ⚠️ | Guardar tal cual. |

---

## 5. Tarjeta

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Respuesta de eliminar tarjeta | `Delete` (con **D mayúscula**) | Tarjeta eliminada. ✅ | Marcar tarjeta como eliminada. |
| Respuesta de afiliar tarjeta | `success` | Se generó la URL para inscribir una nueva tarjeta. ✅ | La tarjeta **aún no** está inscrita hasta que el cliente complete el formulario. 💡 |

---

## 6. Transacción (pago único, `/api/transaction`)

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Transacción | `register` | Sin descripción. ✅ 💡 Registrada. | `CREADA` |
| Transacción | `pending` | Respuesta al crear: orden creada, pagador aún no paga. ✅ | `PENDIENTE` |
| Transacción | `success` | Sin descripción. 💡 Pagada. | `PAGADA` |
| Transacción | `rejected` | Sin descripción. 💡 Rechazada. | `RECHAZADA` |
| `gateway_response.status` | `pending`, `success`, `rejected`, `refunded partial`, `refunded` | Estado según la pasarela. ✅ | Guardar aparte del `status` principal. |
| Callback `urlnotify` | `success` / `failed` | Resultado del pago notificado. ✅ | Confirmar con `GET /api/transaction/{id}`. |

---

## 7. Anulación (reembolso)

Campo `status_nullify` y `nullify.status`:

| Recurso | Estado Payku | Significado (oficial) | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Anulación | `pending` | "Registrado" (en crear) / "En proceso (faltan fondos)" (en obtener). ⚠️ La doc se contradice. | `SOLICITADA` |
| Anulación | `awaiting_funds` | En proceso, faltan fondos (parcial). ✅ | `ESPERANDO_FONDOS` |
| Anulación | `waiting_bank_details` | Aprobada, en espera de datos bancarios del cliente (solo débito y otros medios). ✅ | `ESPERANDO_DATOS_BANCARIOS` |
| Anulación | `complete` | Dinero recolectado. ✅ | `COMPLETA` |
| Anulación | `reverse_completed` | Anulación realizada. ✅ | `REEMBOLSADA` |
| Anulación | `reverse_deleted` | Solicitud eliminada por sistema / inhabilitada. ✅ | `ANULACION_CANCELADA` |
| Anulación (`type`) | `total` / `partial` | Total: dinero disponible y anulación ejecutada. Parcial: no están todos los fondos, queda a la espera. ✅ | Guardar. |
| Callback anulación | `complete` | Ejemplo del callback. ✅ | — |

---

## 8. Conciliación

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Conciliación | `pending` | Sin descripción. ✅ | `POR_DEPOSITAR` |
| Conciliación | `paid_out` | Sin descripción. 💡 Depositada. | `DEPOSITADA` |
| Conciliación | `deteined` (sic, así lo escribe Payku) | Sin descripción. 💡 Retenida. | `RETENIDA` |
| Conciliación | `returned` | Sin descripción. 💡 Devuelta. | `DEVUELTA` |
| `destiny` | `wallet` (ejemplo) | Destino de la liquidación. ✅ | Guardar. |

---

## 9. Escrow

| Recurso | Estado Payku | Significado | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Transacción escrow | `not found` | ✅ (sin descripción) | — |
| Transacción escrow | `pending` | ✅ | — |
| Transacción escrow | `liquidate` | ✅ | — |
| Transacción escrow | `pending for deposit` | ✅ | — |
| Transacción escrow | `paid` | ✅ | — |

---

## 10. Wallet y payouts

| Recurso | Estado Payku | Significado (oficial) | Acción interna (propuesta) 💡 |
|---|---|---|---|
| Respuesta payout / withdraw | `success` / `failed` | Resultado de la solicitud. ✅ | — |
| Movimiento de wallet | `current` (ejemplo) | ✅ Lista no documentada. ⚠️ | — |
| Movimiento (`income_expense`) | `expense` (ejemplo) | "Pago a tercero o retiro a tu cuenta". 💡 También existiría `income`. ⚠️ | — |
| Payout | `pending` | Payout registrado. ✅ | — |
| Payout | `processing` | En proceso de pago. ✅ | — |
| Payout | `success` | Depositado exitosamente. ✅ | — |
| Payout | `banking_error` | Rechazado por el banco. ✅ | Revisar `reason_rejection` (V3). |
| Payout | `fraud_prevention` | Rechazado por compliance. ✅ | — |

---

## 11. Marketplace, mall y evento

| Recurso | Estado Payku | Significado | Nota |
|---|---|---|---|
| Cliente marketplace | `register` | Ejemplo al crear. ✅ | — |
| Cliente / afiliación marketplace (respuesta de DELETE) | `suspended` | El "eliminar" deja el registro suspendido. ✅ | 💡 Es una baja lógica. |
| Afiliación marketplace | `register` | Ejemplo. ✅ | La doc de `affiliations_details.status` repite la lista de escrow; parece un error de copia. ⚠️ |
| Transacción mall | `pending`, `success`, `rejected`, `refunded partial`, `refunded` | ✅ | — |
| Evento (respuesta) | `success` | ✅ | — |
| Beneficiario de evento | `pending` | Ejemplo. ✅ | — |

---

## 12. Mapping normalizado (borrador) 💡

Propuesta para `BD_CENTRAL`. Se ajusta cuando validemos en sandbox.

| Normalizado | Suscripción Payku | Cobro Payku |
|---|---|---|
| `PENDIENTE_ACTIVACION` | `register` | — |
| `ACTIVA` | `active` | — |
| `SUSPENDIDA` | `suspended` | — |
| `TERMINADA` | `finish`, `cancel`, `delete` (guardando el motivo original) | — |
| `PAGADO` | — | `success` |
| `PENDIENTE` | — | `pending` |
| `REINTENTANDO` | — | `retry` |
| `RECHAZADO` | — | `rejected`, `first payment rejected`, `payment consumes failed`, `maximum attempt limit` |
| `CANCELADO` | — | `canceled by customer`, `canceled by paymaster`, `canceled by paymáster`, `canceled by payku` |
| `REEMBOLSADO` | — | `refunded`, `refunded partial` (con flag `parcial`) |
| `DESCONOCIDO` | cualquier otro valor | cualquier otro valor → **alertar** |

💡 Todo valor no mapeado debe ir a `DESCONOCIDO` y generar una alerta, nunca romper el ETL.
