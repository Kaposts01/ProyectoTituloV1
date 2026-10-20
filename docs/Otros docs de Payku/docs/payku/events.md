# Eventos (`/api/event`)

Documentación oficial: https://docs.payku.com/cl/api/events/

"Permite la creación de eventos y posteriormente consultar su estado." ✅ Reparte lo vendido de un evento entre beneficiarios.

💡 Relevancia para TECHO: posible uso en eventos de recaudación (cenas, colectas con entradas). Baja prioridad.

**Autenticación:** `Bearer` (los ejemplos no muestran `Sign`). ✅

---

## Crear un evento

```http
POST /api/event
```

| Campo | Tipo | Req. | Descripción ✅ |
|---|---|---|---|
| `event` | string | ✓ | Identificador del evento (nuestro). Máx. 40. |
| `name` | string | ✓ | Máx. 400. |
| `date_event` | datetime | ✓ | Fecha del evento. |
| `date_closing_sales` | datetime | ✓ | Cierre de ventas, ≤ `date_event`. |
| `date_payment` | datetime | ✓ | Fecha de pago, **mayor** que `date_event`. |
| `url_event` | string | | Máx. 240. |
| `url_logo` | string | | Máx. 240. |
| `service_sale` | integer | | Monto del servicio de venta (para el dueño de la cuenta). |
| `affiliation` | array | | Beneficiarios. La tabla dice objetos `{email, percent}`; el ejemplo usa arreglos `["email", 50]`. ⚠️ |

Respuesta ✅: `{status: "success", id, event, date_event, date_payment, date_closing_sales, url_logo, url_event, distribution{affiliate, service_sale}, affiliation[{id, email, percent, status}]}`.

⚠️ En el ejemplo de body `date_payment` es igual a `date_event` (contradice la regla "debe ser mayor").

## Obtener evento

```http
GET /api/event/{identificadorEvento}
```

⚠️ El ejemplo cURL llama a `/api/event` sin el ID. Respuesta igual a la de crear, con `affiliations` (en plural).

💡 El `id` de evento se usa en `merchant[]` de [mall.md](mall.md).
