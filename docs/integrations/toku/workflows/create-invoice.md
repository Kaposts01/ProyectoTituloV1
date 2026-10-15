# Flujo: cargar una deuda (Invoice) manual

## 1. Qué necesitamos hacer
Cargar una cuota puntual (por ejemplo, una donación única comprometida o una cuota de un plan no recurrente).

## 2. Endpoints
```http
POST /invoices                    # upsert
GET  /invoices/{in_id}            # verificar
```

## 3. Recurso
Invoice (`in_…`). Ver [invoices.md](../invoices.md).

## 4. Parámetros
- `customer` (req.), `due_date` (req.).
- `subscription` **o** `product_id`. Con `product_id` nuevo, Toku crea una Subscription no recurrente.
- `invoice_external_id`: **siempre**, globalmente único (`CUOTA-{id}`).
- `amount` entero (CLP).
- En pruebas: `disable_automatic_payment: true`.

## 5. Request
```json
{
  "customer": "cus_…",
  "product_id": "TEST-DONACION-UNICA",
  "invoice_external_id": "TEST-CUOTA-000123",
  "due_date": "2026-11-05",
  "amount": 15000,
  "currency_code": "CLP",
  "receipt_type": "no_receipt",
  "expiration_action": "VOID",
  "disable_automatic_payment": true
}
```

## 6. Response
`201`/`200` con la Invoice (`status: "UNPAID"`).

## 7. Implementación backend
```text
1. POST /invoices (sin query params).
2. Guardar toku_invoice_id, y toku_subscription_id ← response.subscription.
3. Reintentos: seguros con el MISMO body (upsert por product_id + invoice_external_id).
```

## 8. Qué guardar
`toku_invoice_id`, `invoice_external_id`, `subscription`, `status`, `general_status`.

## 9. Consideraciones
- **Sin `invoice_external_id`, la clave es `product_id + due_date`**: dos cuotas del mismo producto el mismo día se sobrescriben.
- `expiration_action: "EXPIRE"` es legado; usar `VOID` o `DELETE`.
- `is_paid: true` registra un pago **externo** (estado `EXTERNALLY_PAID`), no un cobro.
- No modificar una Invoice con `in_progress: true`.
