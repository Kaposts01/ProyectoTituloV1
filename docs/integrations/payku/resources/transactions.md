# Transacciones (pagos únicos, `/api/transaction`)

Documentación oficial: https://docs.payku.com/cl/api/transaction/

> Estas son órdenes de pago **únicas** (el pagador va a Webpay, transferencia, MACH, etc.). **No** son los cobros de suscripción (eso está en [subscription-charges.md](subscription-charges.md)). ⚠️ No está documentado si los cobros de suscripción también aparecen aquí.

**Autenticación:** `Authorization: Bearer TOKEN_PUBLICO`. Los ejemplos **no** incluyen `Sign`. ✅

---

## Crear transacción

### Endpoint

```http
POST /api/transaction
```

### Propósito
Crear una orden de pago. La respuesta trae la **URL** a la que se redirige al pagador y el **ID** de la transacción. Cuando el pagador paga, Payku notifica el resultado a `urlnotify`. ✅

💡 Para nosotros: donaciones **puntuales** (no recurrentes) o pagos de campañas.

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `email` | string | ✓ 💡 | Email del pagador. Máx. 100. |
| `order` | string | ✓ 💡 | Orden del comercio. Máx. 40. |
| `subject` | string | ✓ 💡 | Descripción. Máx. 2000. |
| `amount` | integer | ✓ 💡 | Monto. Máx. 14 dígitos. |
| `currency` | string | | Moneda (`CLP`). Máx. 6. |
| `payment` | integer | | Medio de pago; si se envía, se va directo a ese medio: `99` Todos, `1` Webpay, `4` Etpay, `6` Pago46, `9` Mach, `19` Fintoc, `23` Tenpo, `26` Floid, `100` Webpay plus 1–3 cuotas, `101` 4–6 cuotas, `102` 7–12 cuotas. ✅ |
| `expired` | string | | Expiración `YYYY-MM-DD HH:MM:SS`; > 5 min desde ahora (hora Santiago); exige `urlreturn`. ✅ |
| `urlreturn` | string | | Retorno del pagador (3 s después del resultado). Máx. 200. ✅ |
| `urlnotify` | string | | Callback del resultado. Máx. 600. ✅ |
| `additional_parameters` | object | | Obligatorio para `payment` 4, 19 y 26. Máx. 4000. ✅ |
| ↳ `order_ext` | string | | **Palabra reservada**: ID único del comercio para asociar la transacción. ✅ |
| ↳ `payer_rut` | string | | RUT del pagador; obligatorio para 4, 19, 26. ✅ |
| ↳ `payer_bank` | string | | Banco preseleccionado (de `GET /api/banks`). ✅ |

⚠️ En la sección *Transacción* la tabla **no marca** ningún campo como requerido; en *Crear transacción marketplace* sí: `email`, `order` (**único**), `subject`, `amount`. 💡 Trátalos como obligatorios.

### Response (200)

```json
{ "status": "pending", "id": "trx3b4d77b43acd9a720", "url": "https://BASE_URL/url_de_pago" }
```

### Callback `urlnotify` ✅

```json
{
  "transaction_id": "9916587765599311",
  "payment_key": "trx32cb779c0a777fc68",
  "transaction_key": "9916581777599311",
  "verification_key": "8b3e2202fb086a7de93777ae34d5e18c",
  "order": "199",
  "status": "success"
}
```

`status`: `success` o `failed`. Detalle en [webhooks.md](webhooks.md).

### Consideraciones
- 💡 `order` único y nuestro, y `additional_parameters.order_ext` con nuestro ID de donación.
- ⚠️ Idempotencia no documentada: si hay timeout, busca por fecha/estado antes de crear otra.

---

## Obtener múltiples transacciones

### Endpoint

```http
GET /api/transaction?date_init=2021-09-01&date_end=2021-09-15&success=true&page=1&per_page=1000
```

### Query parameters

| Campo | Tipo | Descripción |
|---|---|---|
| `date_init` | `YYYY-MM-DD` | Inicio; por defecto **hoy**. ✅ |
| `date_end` | `YYYY-MM-DD` | Fin; por defecto **hoy**. ✅ |
| `register` / `pending` / `success` / `rejected` | `true` | Filtro por estado (combinables). ✅ |
| `page` / `per_page` | int | Paginación; máximo **4000**. ✅ |

### Response (200)

```json
{
  "transaction": [
    {
      "id": "107999",
      "status": "success",
      "created_at": "2019-10-25 14:10:03",
      "email": "johndoe@example.com",
      "amount": 98745,
      "order": "1572023402",
      "subject": "Description",
      "payment": {
        "start": "2023-12-16 15:10:33",
        "end": "2023-12-16 15:10:36",
        "media": "Webpay",
        "transaction_id": 107999,
        "payment_key": "pra934939d607922f9e",
        "transaction_key": null,
        "deposit_date": "2023-10-05",
        "verification_key": "6669cbd982ef54c28f2f15fb9dc5262d",
        "authorization_code": "107742",
        "last_4_digits": "1233",
        "installments": 0,
        "card_type": "VN",
        "additional_parameters": { "identificador": "11.111.111-1", "banco": "Banco Estado", "numero_cuenta": "00126544977" },
        "currency": "CLP"
      },
      "nullify": { "status": "complete" },
      "gateway_response": { "status": "success", "message": "successful transaction" }
    }
  ]
}
```

⚠️ En el listado `id` es numérico como string (`"107999"`); al crear es `trx…`. No sabemos si son el mismo identificador.

---

## Obtener transacción

### Endpoint

```http
GET /api/transaction/{identificador}
```

### Path parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `identificador` | string | ✓ | ID de la transacción **o** identificador de cobro (`payment_key`, `transaction_key`). Máx. 30. ✅ |

### Response (200)
Igual que un elemento del listado, más `payment.additional_parameters.network.ip_address`. `amount` aquí es **string**. ✅

### Errores
404 → `{"status": "failed", "type": "Not Found", "id": "is not valid"}`. ✅

---

## Campos importantes

| Campo | Descripción | Uso interno 💡 |
|---|---|---|
| `status` | `register` / `pending` / `success` / `rejected`. ✅ | Estado principal. |
| `gateway_response.status` / `.message` | Resultado de la pasarela y motivo (ver [errors.md § 4](errors.md#4-mensajes-de-rechazo-de-pago-no-son-errores-de-api-)). ✅ | Motivo de rechazo. |
| `payment.media` | Medio usado (`Webpay`…). ✅ | Reporte por medio de pago. |
| `payment.payment_key` | "Identificador del cobro". ✅ | **Cruce con conciliación.** |
| `payment.deposit_date` | Fecha en que se depositará al comercio. ✅ | Tesorería. |
| `payment.authorization_code` | Autorización del emisor. ✅ | Soporte. |
| `payment.installments` / `card_type` | Cuotas y tipo (`VN`, `VD`…). ✅ | — |
| `nullify.status` | Estado de anulación, si la hay. ✅ | Ver [refunds.md](refunds.md). |

## Estados
→ [statuses.md § 6](statuses.md#6-transacción-pago-único-apitransaction)
