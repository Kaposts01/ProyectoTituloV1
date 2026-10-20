# Conciliación (`/api/conciliation`)

Documentación oficial: https://docs.payku.com/cl/api/reconciliation/

---

## Términos clave

- **Liquidación:** el depósito que Payku hace al comercio agrupando varias transacciones.
- **Conciliación:** cuadrar lo que se cobró con lo que realmente llegó al banco (monto bruto − comisión = neto).

🎨 **Analogía:** cada transacción es una boleta; la conciliación es el **sobre del banco** que dice "estas 37 boletas, menos la comisión, se depositaron el día X".

---

## Obtener conciliaciones

### Endpoint

```http
POST /api/conciliation
```

(Es `POST` aunque solo lee datos. ✅)

### Autenticación
`Authorization: Bearer`. El ejemplo **no** incluye `Sign`. ✅

### Propósito
"Obtener las conciliaciones bancarias del dinero generado por su cuenta y depositado por payku en los días correspondientes a sus pagos." ✅
💡 Para nosotros: cuadratura contable de lo recaudado por Payku vs lo depositado; calcular comisiones reales.

### Request body

| Campo | Tipo | Requerido | Reglas ✅ |
|---|---|---|---|
| `date_init` | `YYYY-MM-DD` | ✓ | No mayor que hoy ni que `date_end`. |
| `date_end` | `YYYY-MM-DD` | ✓ | No mayor que hoy ni menor que `date_init`. |

**El rango no puede superar 30 días.** ✅

```json
{ "date_init": "2023-10-20", "date_end": "2023-10-21" }
```

### Response (200)

```json
{
  "conciliation": [
    {
      "id": "107999",
      "created_at": "2019-10-25 14:10:03",
      "amount_available": 98745,
      "amount_deposit": 0,
      "status": "pending",
      "destiny": "wallet",
      "currency": "CLP",
      "wallet": null,
      "transaction": [
        {
          "transaction_id": "rsyt68j4dhg6k8j54ut698dt6hj84",
          "payment_key": "pra934939d607922f9e",
          "order": "6544",
          "start": "2023-12-16 15:10:33",
          "end": "2023-12-16 15:10:36",
          "deposit_date": "2023-10-05",
          "amount": 250000,
          "fee": 15000,
          "amount_deposit": 235000,
          "media": "Webpay"
        }
      ]
    }
  ]
}
```

### Campos importantes

| Campo | Descripción | Uso interno 💡 |
|---|---|---|
| `id` | ID de la conciliación. ✅ | Clave de `liquidacion`. |
| `status` | `pending` / `paid_out` / `deteined` / `returned`. ✅ | Estado del depósito. |
| `destiny` / `wallet` | Destino (`wallet`) y billetera. ✅ | Saber si quedó en la wallet o fue al banco. |
| `amount_available` / `amount_deposit` | Disponible / depositado. ✅ | — |
| `transaction[].payment_key` | "Identificador del cobro". ✅ | **Llave de cruce** con transacciones. |
| `transaction[].order` | Nuestra orden. ✅ | Cruce alternativo. |
| `transaction[].fee` | Comisión. ✅ | Costo real por transacción. |
| `transaction[].amount_deposit` | Neto depositado. ✅ | — |
| `transaction[].deposit_date` | Fecha de depósito. ✅ | — |

### Paginación
No documentada. Se recorre por **ventanas de ≤ 30 días**. 💡 Carga histórica: ventanas sucesivas de 30 días hacia atrás.

### Consideraciones
- ⚠️ No está documentado si los **cobros de suscripción** aparecen aquí (y con qué `payment_key`/`order`). Es clave para cuadrar socios. (Q-06)
- ⚠️ `transaction_id` en conciliación es string alfanumérico; en otros lados es numérico.
- 💡 Corre esta consulta a diario sobre los últimos 30 días: el `status` de una liquidación cambia (`pending` → `paid_out`).
