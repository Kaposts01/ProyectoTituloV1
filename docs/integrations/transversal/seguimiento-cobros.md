# Flujo transversal: seguimiento de cobros recurrentes

> Comparacion del comportamiento entre VirtualPOS, Toku y Payku para el flujo de seguimiento mensual de cobros.
> Fuente: adaptadores por canal en `workflows/seguimiento-cobros.md` de cada canal.

---

## Modelo conceptual por canal

| Concepto TECHO | VirtualPOS | Toku | Payku |
|---|---|---|---|
| **Cuota** (deuda del mes) | `Charge` (`cid_...`) — creado por VirtualPOS al activarse la suscripcion, embebido en `charge_program[]` | `Invoice` (`in_...`) — creado por Toku automaticamente en suscripciones recurrentes, con `general_status` y `in_progress` | **No existe** como objeto. La cuota esperada la calculamos nosotros a partir del `payment_cycle_day` y el dia del ciclo observado en `paid[]` |
| **Transaccion** (cobro a la tarjeta) | `Payment` (`order.uuid`) — un intento de cobro o pago exitoso | `Transaction` — un movimiento de dinero (cobro, reversa, contracargo); tipo `PAYMENT` / `REVERSED` / `CHARGEBACK` | Elemento de `transactions[]` dentro de la suscripcion — identificado por `transaction` (numero), `authorization_code` y `order` |
| **Aplicacion pago → cuota** | `charge.payment.order.uuid` (requiere `GET /v3/charge/{id}` — no a nivel masivo) | `Payment Intent` (`payment_intents[]` dentro de la Transaction) — relacion N:M Transaction <-> Invoice | No hay clave comun documentada entre `paid[]` y `transactions[]` (Q-08) |
| **Motivo de rechazo** | `GET /v3/payment/{uuid}/attempts` → `rejected_object.code` (llamada por cuota — no masiva) | `response_code` + `original_response_message` en la Transaction (disponible en el listado masivo) | **No existe** por cobro. Solo `status` del ciclo en `paid[]` (estados Lista A no documentados en V3, Q-05) |
| **Liquidacion** | `Deposit` — abono diario: `GET /v3/deposit/{fecha}/sales` enlaza `suscription_charge.cid` con `uuid` | `id_payout` en la Transaction (NULL = cobrado pero aun no liquidado) | Conciliacion: `POST /api/conciliation` — enlace por `order` o `payment_key` (Q-06: no confirmado si incluye cobros de suscripcion) |

---

## Capacidad masiva vs uno a uno

| Necesidad | VirtualPOS | Toku | Payku |
|---|---|---|---|
| Todas las cuotas de suscripciones activas | Masivo: `charge_program[]` embebido en `GET /v3/suscriptions` (~50 llamadas para 5000 socios) — V-1 sin confirmar en sandbox | Masivo: `GET /invoices?due_date_from=&page_size=100` con cursor (20 req/s) | Masivo: `GET /api/sususcriptionv3` con `paid[]` hasta 4000 por pagina — sin filtro `due_date_to`; sin fechas trae solo hoy |
| Puente cuota → transaccion | Uno a uno: `GET /v3/charge/{id}` solo para cuotas que cambiaron (1 llamada por cuota modificada) — V-2 sin confirmar | Masivo: cada Transaction del listado trae `payment_intents[]` con `id_invoice` | No hay clave comun documentada (Q-08); hay que enlazar por (suscripcion, fecha, monto) como aproximacion |
| Todas las transacciones del periodo | Masivo: `GET /v3/payments?authorization_from=&authorization_to=` — V-3 sin confirmar si incluye recurrentes | Masivo: `GET /transactions?start_date=&end_date=` a **1 req/s** | Masivo: `GET /api/sususcription` (V1) con `transactions[]`; V3 con `paid[]` |
| Motivo del rechazo | Uno a uno: `GET /v3/payment/{uuid}/attempts` | Masivo: `response_code` en el listado de transacciones | No disponible: solo el `status` del ciclo |
| Liquidacion | Masivo: `GET /v3/deposit/{fecha}/sales` (1 llamada por dia) | En la Transaction: `id_payout`; listado de Payouts via `GET /transactions?id_payout=` (T-S3 sin confirmar) | `POST /api/conciliation` ventanas de 30 dias; enlace por `order` o `payment_key` (Q-06) |

---

## Job diario: pasos comparados

| Paso | VirtualPOS | Toku | Payku |
|---|---|---|---|
| 1. Cuotas (masivo) | `charge_program[]` de `GET /v3/suscriptions` → upsert `vpos_charges` | `GET /invoices?due_date_from=` → upsert `toku_invoices` | `GET /api/sususcriptionv3` por ventanas → upsert `payku_cycles` |
| 2. Transacciones (masivo) | `GET /v3/payments?authorization_from=` (ventana D-2 a D) → upsert `vpos_payments` | `GET /transactions?start_date=` (ventana D-2 a D) a 1 req/s → upsert `toku_transactions` + `toku_payment_intents` | `GET /api/sususcription` (V1) → upsert `payku_charges`; enlazar ciclo <-> cobro por (su, fecha, monto) — Q-08 |
| 3. Cuotas esperadas | Detectar cambios de estado en base local (pagado/rechazado/cancelado/atrasado) | Cuadratura: Σ Payment Intents SUCCESS vs `paid_amount`; inconsistencias, in_progress colgado, sin intento | Calcular cuota esperada (nuestra base) vs ciclos de `paid[]`; estado: PAGADA / EN REINTENTO / RECHAZADA / SIN INTENTO / POR COBRAR |
| 4. Motivos de rechazo | `GET /v3/payment/{uuid}/attempts` solo para cuotas rechazadas | `response_code` + `original_response_message` ya en la Transaction | No disponible; usar `status` del ciclo |
| 5. Liquidacion | `GET /v3/deposit/{D-1}/sales` → enlaza `cid` <-> `uuid` | Seguimiento de transacciones SUCCESS con `id_payout = null` por mas de N dias | `POST /api/conciliation` ultimos 30 dias; enlazar por `order` / `payment_key` — Q-06 |
| Tiempo real | `callback_url` → `GET /v3/suscription/{id}` (sin firma verificable) | Webhooks `invoice.paid` / `transaction.*` con HMAC-SHA256 → releer recurso por API | Callback `url_notify_payment` (sin firma documentada, sin monto) → `GET /api/sususcription/{id}` |

---

## Estados normalizados y equivalencias

| Estado normalizado | VirtualPOS (Charge) | Toku (Invoice `general_status`) | Payku (ciclo `paid[].status`) |
|---|---|---|---|
| Por cobrar / pendiente | `pendiente` | `unpaid`, `in_progress=false`, aun no vence | Sin ciclo y el dia no llego (+2 dias) |
| En cobro | `procesando` | `unpaid`, `in_progress=true` | `pending` / `retry` con try_number creciente |
| Pagado | `pagado` | `paid` | `success` con `amount_paid` = monto esperado |
| Rechazado | `rechazado` | `unpaid` tras vencer (con FAILED en Transaction) | `maximum attempt limit` → suscripcion `suspended` |
| Cancelado | `cancelado` | `void` | `canceled by customer` / `canceled by payku` |
| Devuelto | (no aplica a cuotas) | `paid` → reversa → `REVERSED` / `CHARGEBACK` | `refunded` / `refunded partial` |

---

## Alertas operativas recomendadas

| Alerta | VirtualPOS | Toku | Payku |
|---|---|---|---|
| Cuota atrasada sin cobrar | `pendiente` con `charge_date < hoy - 2` | `vencida`, `unpaid`, sin transaccion y sin `in_progress` | Sin ciclo y `dia_esperado + 2 < current_date` |
| Cuota pagada sin transaccion | `pagado` con `payment_uuid IS NULL` tras el paso 3 del job | `paid` con Σ Payment Intents SUCCESS = 0 | Ciclo `success` sin cobro enlazado (Q-08) |
| Cobro en curso colgado | `procesando` por mas de 3 dias habiles | `in_progress=true` por mas de 3 dias habiles | `retry` sin `success` por mas del calendario de reintentos (Q-17) |
| Doble cobro | Dos cuotas `pagado` del mismo socio en el mismo mes | Dos Payment Intents SUCCESS sobre la misma Invoice | Dos ciclos `success` del mismo `payment_cycle_day` |

---

## Pendientes criticos que afectan la capa comun

| Clave | Canal | Descripcion |
|---|---|---|
| V-1 | VirtualPOS | Confirmar que `charge_program` en el listado masivo es completo |
| V-2 | VirtualPOS | Confirmar que `GET /v3/charge/{id}` trae `payment.order.uuid` para cuotas pagadas y rechazadas |
| V-3 | VirtualPOS | Confirmar que `GET /v3/payments` incluye transacciones recurrentes (no solo pagos spot) |
| T-S1 | Toku | Confirmar si `start_date`/`end_date` de `GET /transactions` filtra por `transaction_date` o `initialization_date` |
| Q-06 | Payku | Confirmar si los cobros de suscripcion aparecen en la conciliacion |
| Q-08 | Payku | Confirmar la clave estable para enlazar ciclo V3 con cobro del detalle |

---

## Referencias por canal

- VirtualPOS: [workflows/seguimiento-cobros.md](../virtualpos/workflows/seguimiento-cobros.md)
- Toku: [workflows/seguimiento-cobros.md](../toku/workflows/seguimiento-cobros.md)
- Payku: [workflows/seguimiento-cobros.md](../payku/workflows/seguimiento-cobros.md)
