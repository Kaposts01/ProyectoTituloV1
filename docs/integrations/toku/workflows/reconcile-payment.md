# Flujo: conciliar pagos (Transaction ↔ Invoice ↔ banco)

## 1. Qué necesitamos hacer
Responder, para cada cuota: ¿se pagó?, ¿cuándo?, ¿con qué medio?, ¿en qué liquidación llegó la plata?

## 2. Endpoints
```http
GET /transactions?start_date=…&end_date=…&status=SUCCESS&page=N   # 1 req/s
GET /transactions?id_invoice=in_…                                   # pagos de una cuota
GET /transactions?id_payout=…                                       # qué compone una liquidación
GET /invoices/{in_id}                                               # estado de la cuota
```

## 3. Modelo
```text
Transaction (movimiento de dinero, transaction_date, id_payout)
   └── payment_intents[] (id_invoice, amount, status)
          └── Invoice (general_status, paid_amount)
```

## 4. Algoritmo [Recomendación]

```text
Para cada Transaction leída (API o webhook):
  upsert stg_toku_transactions(id, payload)
  para cada pi en payment_intents:
      upsert aplicacion_pago(pi.id, transaction_id, pi.id_invoice, pi.amount, pi.status)

Para cada Invoice:
  pagos_ok = Σ pi.amount de aplicacion_pago
             donde transaction.status = SUCCESS y transaction.type = PAYMENT
             (y pi.status ∉ {REFUNDED, CHARGEBACK, FAILED, …}  ← validar con datos reales)
  menos reversas (type REVERSED / CHARGEBACK que referencian la misma Invoice)
  comparar con invoice.paid_amount y invoice.general_status
  diferencias → tabla de alertas
```

| Situación | Interpretación |
|---|---|
| `general_status = paid` y existe una Transaction `SUCCESS` | Pago normal por Toku |
| `status = EXTERNALLY_PAID` y sin Transaction | Marcada como pagada fuera de Toku (`is_paid: true`) |
| Transaction `SUCCESS` pero la Invoice sigue `unpaid` | **Inconsistencia** → revisar (desfase de sync o pago aplicado a otra cuota) |
| `in_progress = true` por más de 3 días hábiles | **Alerta**: el cobro PAC/PAT quedó colgado |
| Transaction `SUCCESS` con `id_payout = null` | Cobrado pero aún no liquidado a TECHO |

## 5. Fechas
- **Fecha de pago efectiva** = `transaction.transaction_date` (UTC). No existe en la Invoice.
- Fecha de liquidación: por `id_payout` (endpoint *List Payouts*, <https://docs.trytoku.com/reference/list_payouts>; **no verificado aún**).
- Convertir a `America/Santiago` solo en la capa de presentación.

## 6. Consideraciones
- **Rate limit de 1 req/s**: una carga histórica grande toma tiempo (100 tx/s como máximo teórico). Hacer checkpoint por página.
- Una Transaction con varios Payment Intents debe generar **varias filas** en `aplicacion_pago`. El sync de Sheets actual toma solo el primero.
- Moneda: `transaction.currency` puede diferir de la moneda de la Invoice (por ejemplo, CLF). Usar `pi.amount`/`pi.currency` para la aplicación.
- Reversas y contracargos llegan como **Transactions nuevas** (`REVERSED`, `CHARGEBACK`), no como un cambio de la original. **[Inferencia]** a partir de los `type`.
