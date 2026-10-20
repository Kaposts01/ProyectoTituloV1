# Anulaciones (reembolsos, `/api/nullification`)

Documentación oficial: https://docs.payku.com/cl/api/refunds/

---

## Crear anulación

### Endpoint

```http
POST /api/nullification
```

### Autenticación
`Bearer` + `Sign` ✅ (la anulación es uno de los tres grupos que la página de Firma nombra).

### Propósito
Solicitar la anulación (reembolso) de una transacción. 💡 Úsalo para devolver una donación cobrada por error. **Mueve dinero:** solo con aprobación humana.

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `id` | string | 💡 ✓ | ID de la transacción a anular. Máx. 40. ✅ |
| `amount` | int | 💡 ✓ | Monto. Máx. 14 dígitos. ✅ |
| `subject` | string | | Motivo. Máx. 200. ✅ |

```json
{ "id": "trxpr2a45s1dytg1", "amount": 25000, "subject": "anulación transacción" }
```

### Response (200)

```json
{
  "status": "success",
  "nullify": {
    "id": "trxpr2a45s1dytg1",
    "amount": 25000,
    "currency": "CLP",
    "type": "total",
    "status_nullify": "complete",
    "payment": { "gateway": "webpay", "payment_type": "VC" },
    "created_at": "2023-05-17T19:12:57.189Z",
    "updated_at": "2023-05-17T19:12:57.189Z"
  },
  "gateway_response": {
    "status": "Successfully registered request",
    "message": "The cancellation will be executed after the amount requested is deducted from your next settlement",
    "notify": "No availability in the wallet"
  }
}
```

### Campos importantes

| Campo | Descripción | Uso interno 💡 |
|---|---|---|
| `nullify.type` | `total` (dinero disponible, ejecutada) / `partial` (faltan fondos, en espera). ✅ | Seguimiento. |
| `nullify.status_nullify` | Ver [statuses.md § 7](statuses.md#7-anulación-reembolso). ✅ | Seguimiento. |
| `gateway_response.message` | Explica si se descuenta de la próxima liquidación. ✅ | Tesorería: impacta la conciliación. |
| `created_at` / `updated_at` | **ISO 8601 con `Z`** (distinto al resto). ✅ | Parsear aparte. |

### Consideraciones
- ⚠️ No está documentado si `amount` menor al total produce anulación parcial del monto, ni si se permiten varias anulaciones por transacción.
- ⚠️ No está documentado si sirve para **cobros de suscripción** (el `id` es de una transacción `trx…`).
- **Nunca reintentar automáticamente.**

---

## Obtener anulación

```http
GET /api/nullification/{identificador}
```

Mismo `id` de la transacción. Respuesta: objeto `nullify` (igual al de crear). 404 si no existe. ✅
El ejemplo cURL no incluye `Sign`. ⚠️

---

## Callback de anulación

Se configura en el panel de Payku (sección configuración). ✅ Payload y formato de fecha `DD-MM-YYYY`: ver [webhooks.md § 2.4](webhooks.md#24-anulación-).
