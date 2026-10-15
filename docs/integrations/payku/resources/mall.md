# Mall (`/api/mall`)

Documentación oficial: https://docs.payku.com/cl/api/mall/

"Diseñado para empresas integradoras de distintas marcas … agrupar el pago de las compras realizadas en múltiples tiendas virtuales en una sola transacción." ✅

💡 Relevancia para TECHO: baja (podría servir si una sola compra en Mercadito se repartiera entre varias cuentas Payku).

**Autenticación:** `Bearer` + `Sign` (crear) ✅. El ejemplo de "obtener" no muestra `Sign`.

---

## Crear transacción Mall

```http
POST /api/mall
```

| Campo | Tipo | Req. | Descripción ✅ |
|---|---|---|---|
| `email` | string | ✓ | Máx. 50. |
| `payment` | integer | ✓ | Medio de pago (1 Webpay, 4 Etpay, 6 Pago46, 9 Mach, 19 Fintoc, 23 Tenpo, 26 Floid, 99 Todos). |
| `merchant` | array de arrays | ✓ | `[token público o ID afiliación marketplace, monto, descripción, id evento o null, orden individual]`. **No entra en la firma** (arreglo). |
| `order` | integer | ✓ | Orden del comercio, **única**. |
| `urlreturn` | string | ✓ | Máx. 200. |
| `urlnotify` | string | | Máx. 600. |

Respuesta ✅: `{status, id: "malld…", individual_orders[{merchant, amount, subject, event, identificador, individual_order}], url}`.

## Obtener transacción Mall

```http
GET /api/mall/{identificadorTransaccion}
```

Respuesta ✅: `status`, `id`, `created_at`, `amount`, `payment{media, verification_key, authorization_code, last_4_digits, card_type, currency}`, `merchant[{name, amount, subject}]`. 404 si no existe.

Estados: `pending`, `success`, `rejected`, `refunded partial`, `refunded`. ✅
