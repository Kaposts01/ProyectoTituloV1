# Flujo: crear un plan recurrente (Subscription)

## 1. Qué necesitamos hacer
Crear el compromiso mensual de un socio para que Toku genere sus cuotas automáticamente.

## 2. Endpoints
```http
POST /subscriptions                         # upsert por (Account, product_id)
GET  /subscriptions/{sub_id}                # verificar el objeto recurring
```

## 3. Recurso
Subscription (`sub_…`). Ver [subscriptions.md](../subscriptions.md).

## 4. Parámetros
| Campo | Valor sugerido |
|---|---|
| `customer` | `cus_…` (del flujo create-customer) |
| `product_id` | `SOCIO-{id_socio}-{id_compromiso}` (determinístico) |
| `amount` | Entero en CLP |
| `is_recurring` | `true` (**booleano**) |
| `frequency` | `"monthly"` |
| `interval` | `1` (**entero**) |
| `due_day` | `1`–`28` [Recomendación: evitar 29–31 para no depender del ajuste de fin de mes] |
| `creation_lead_days` | Por ejemplo `5`. **[Recomendación]** Con PAC, el primer intento de cobro ocurre 48 h hábiles antes del vencimiento, así que la Invoice debe existir antes de eso |
| `max_active_invoices` | Por ejemplo `3`. Al llegar al máximo se pausa sola |

## 5. Request
```json
{
  "customer": "cus_…",
  "product_id": "TEST-SOCIO-0001-MENSUAL",
  "amount": 10000,
  "currency_code": "CLP",
  "is_recurring": true,
  "frequency": "monthly",
  "interval": 1,
  "due_day": 5,
  "creation_lead_days": 5,
  "max_active_invoices": 3
}
```

## 6. Response
`201`/`200` con `recurring: { status: "ACTIVE", anchor, frequency, interval, due_day, … }`.

## 7. Implementación backend
```text
1. Asegurar que el Customer exista (toku_customer_id).
2. POST /subscriptions con tipos correctos (bool/int, nunca strings).
3. Validar en la respuesta: is_recurring == true y recurring.status == "ACTIVE".
4. Guardar toku_subscription_id.
5. Siguiente paso: inscribir y asociar un medio de pago → enroll-payment-method.md.
   Sin medio de pago, las cuotas se generan pero no se cobran automáticamente.
```

## 8. Qué guardar
`toku_subscription_id`, `product_id`, los parámetros de recurrencia devueltos (`anchor` incluido) y el payload en STG.

## 9. Consideraciones
- **Error frecuente:** mandar `"is_recurring": "True"` o `"interval": "1"` (strings) → `422`. Bug presente en la request "Editar Subscription" de Postman.
- **Error frecuente:** anidar la recurrencia en `"recurring": {…}` en el request. Va en la raíz.
- Cambiar el `customer` de un `product_id` existente → `TK30501`.
- **[No confirmado]** Si Toku genera la primera Invoice al crear la Subscription o recién `creation_lead_days` antes del primer vencimiento. Verificarlo con `GET /invoices?subscription_id=` después de crearla.
