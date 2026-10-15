# Inventario de estados de Toku

Valores **originales** de Toku, sin traducir ni normalizar. La columna "Acción interna" es una **propuesta** [Recomendación]. El mapping definitivo a BD_CENTRAL se decide después.

Leyenda de significado: **[C]** confirmado en la doc · **[I]** inferencia · **[?]** la doc no lo define.

## Invoice — `status` (detallado)

Doc: <https://docs.trytoku.com/reference/invoice-object>

| Recurso | Estado Toku | Significado | Acción interna |
|---|---|---|---|
| Invoice | `UNPAID` | [I] Impaga, sin cobro en curso | Cuota pendiente |
| Invoice | `PAID` | [I] Pagada por completo vía Toku | Cuota pagada; buscar la Transaction |
| Invoice | `PARTIALLY_PAID` | [I] Pago parcial (`paid_amount < amount`) | Cuota con saldo |
| Invoice | `EXTERNALLY_PAID` | [I] Marcada como pagada fuera de Toku (`is_paid: true` vía API) | Cuota pagada, sin Transaction de Toku |
| Invoice | `UNPAID_PAYMENT_IN_PROGRESS` | [I] Impaga con un cobro en curso (por ejemplo, PAC enviado al banco) | **No modificar ni borrar** |
| Invoice | `PARTIALLY_PAID_PAYMENT_IN_PROGRESS` | [I] Parcial con un cobro en curso | No modificar |
| Invoice | `UNPAID_NON_BLOCKING_PAYMENT_IN_PROGRESS` | [?] Cobro en curso "no bloqueante" | [I] Tratarlo como en curso |
| Invoice | `PARTIALLY_PAID_NON_BLOCKING_PAYMENT_IN_PROGRESS` | [?] | Ídem |
| Invoice | `UNPAID_PARTIAL_PAYMENT_IN_PROGRESS` | [?] [I] Un pago parcial en curso | Ídem |
| Invoice | `PARTIALLY_PAID_PARTIAL_PAYMENT_IN_PROGRESS` | [?] | Ídem |
| Invoice | `VOID` | [C] Anulada; se trata como eliminada | Cuota anulada |
| Invoice | `DELETED` | [I] Eliminada | Cuota eliminada (soft delete local) |
| Invoice | `EXPIRED` | [C] **Deprecado**. Resultado de `expiration_action: EXPIRE` | Cuota vencida sin cobro |

> La doc oficial **no define** el significado de ningún valor de `status`. Los significados [I] se deducen del nombre y de `general_status`/`in_progress`. **Para lógica de negocio, usar `general_status` + `in_progress`**, que sí están definidos.

## Invoice — `general_status` [C]

| Recurso | Estado Toku | Significado | Acción interna |
|---|---|---|---|
| Invoice | `paid` | Pagada | PAGADA |
| Invoice | `partially_paid` | Pago parcial | PARCIAL |
| Invoice | `unpaid` | Impaga | PENDIENTE |
| Invoice | `void` | Anulada | ANULADA |
| Invoice | `expired` | Expirada | VENCIDA |

`in_progress` (boolean) [C]: hay un cobro en curso sin confirmar ni rechazar. **No cambia** `general_status`.

Estados "de negocio" de Toku para productos por día (PAC, etc.) [C, de la guía *Data out via API*]: *No pagada*, *En proceso de cobro*, *Pagada*. El cobro tarda **24–48 h hábiles** y el primer intento ocurre **48 h hábiles antes** del vencimiento.

## Subscription — `recurring.status` [C]

| Recurso | Estado Toku | Significado | Acción interna |
|---|---|---|---|
| Subscription | `ACTIVE` | [?] Recurrencia activa (la doc no lo define) | Plan activo |
| Subscription | `PAUSED` | [C] Pausada manualmente o porque llegó a `max_active_invoices` impagas | Plan pausado. **Distinguir el motivo**: contar las Invoices impagas |
| Subscription | `FINISHED` | [?] [I] Llegó a `end_date` | Plan terminado |
| Subscription | (sin `recurring`) | [C] No recurrente | Plan manual / puntual |

Transiciones permitidas vía API [C]: `ACTIVE ↔ PAUSED` (cualquier otra → `409`).

## Transaction — `status` [C]

| Recurso | Estado Toku | Significado | Acción interna |
|---|---|---|---|
| Transaction | `INITIALIZED` | El cobro aún no se resuelve | Pago pendiente; reconsultar |
| Transaction | `SUCCESS` | Cobro capturado | Pago confirmado |
| Transaction | `FAILED` | Rechazado por el procesador | Rechazo; ver `response_code` |
| Transaction | `FAILED_INIT` | Deprecado | Tratar como FAILED |
| Transaction | `ABORTED` | Descartado antes de intentarse o vencido sin resolver | Sin efecto |
| Transaction | `CAPTURE_PENDING` | Autorización esperando captura | Pendiente |

## Transaction — `type` [C]

| Estado Toku | Significado | Acción interna |
|---|---|---|
| `PAYMENT` | Cobro al cliente | Ingreso |
| `EXTERNAL_PAYMENT` | Pago fuera de Toku registrado para conciliar | Ingreso externo |
| `REVERSED` | Reversa de un pago | Egreso / anulación |
| `CHARGEBACK` | Contracargo del banco del cliente | Egreso / disputa |
| `INSCRIPTION` | Inscripción de un medio de pago | No es dinero: excluir de ingresos |
| `ONETIME`, `INSCRIPTION_REVERSED`, `CARD_ON_FILE_PAYMENT`, `CARDLESS_PAYMENT`, `PATPASS_PAYMENT`, `VOID`, `CHARGEBACK_REVERSAL` | [?] Sin descripción | Guardar crudo; revisar caso a caso |

## Payment Intent

`status` [C: valores] / [?: significado]:

`FAILED`, `EXPIRED`, `DELETED`, `AUTHORIZED`, `CHARGEBACK`, `INITIALIZED`, `PAC_PENDING`, `PAC_CREATED`, `CONSTRAINTS_VIOLATED`, `REFUNDED`, `ABORTED`, `INITIALIZED_NON_BLOCKING`, `REFUND_INITIALIZED`, `REFUND_FAILED`.

La doc no define ninguno. **[I]** `AUTHORIZED` ≈ aplicado con éxito; `PAC_PENDING`/`PAC_CREATED` = flujo PAC en curso; `REFUNDED`/`CHARGEBACK` = revertido. **Validar con datos reales** antes de usarlos en lógica.

## Payment Method

`status` [C: valores]:

| Recurso | Estado Toku | Significado | Acción interna |
|---|---|---|---|
| Payment Method | `initialized` | [?] Inscripción iniciada | Pendiente |
| Payment Method | `pending_activation` | [?] Esperando activación (por ejemplo, mandato PAC) | Pendiente |
| Payment Method | `chargeable` | [I] Se puede cobrar | **Medio activo** |
| Payment Method | `manually_chargeable` | [?] Cobrable solo manualmente | Activo con restricción |
| Payment Method | `temporary_failed` | [I] Falla temporal | Alerta suave |
| Payment Method | `permanent_failed` | [I] Falla permanente | Pedir un nuevo medio |
| Payment Method | `inscription_failed` | [I] La inscripción falló | Pedir reintento |
| Payment Method | `three_ds_required` | [C] **Heredado, ya no se usa** | — |
| Payment Method | `finished` | [?] | Inactivo |
| Payment Method | `cancelled` | [?] | Inactivo |
| Payment Method | `pending_deletion` | [?] | Inactivo |
| Payment Method | `deleted` | [C] Borrado lógico (excluido del listado) | Inactivo |
| Payment Method | `permanent_deletion_in_progress` | [?] | Inactivo |
| Payment Method | `permanently_deleted` | [?] | Inactivo |

## Otros

| Recurso | Campo | Valores |
|---|---|---|
| Webhook Endpoint | `status` | `enabled`, `disabled` |
| Checkout Session | `state` | `OPEN`, `COMPLETED`, `EXPIRED` |
| Invoice refund | `refund_data.refund_status` | `success`, `failed` |
| Payment Method / Transaction | `response_code` (prefijo) | `SU`, `TE`, `PE`, `UE` (ver [errors.md](errors.md)) |
