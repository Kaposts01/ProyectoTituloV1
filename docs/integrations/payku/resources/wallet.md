# Wallet (billetera Payku) y payouts

Documentación oficial: https://docs.payku.com/cl/api/wallet/

**Autenticación:** `Bearer` + `Sign` en todos (según portada y ejemplos). ✅

> ⚠️ **Dos de estos endpoints mueven dinero real** (`payout` y `withdraw`). No los ejecutes en producción para "probar". En sandbox, los payouts de **1000, 2000, 3000** se aprueban y los de **1500, 2500, 3500** se rechazan automáticamente. ✅

💡 Relevancia para TECHO: baja para la integración de socios. Útil si las liquidaciones de Payku quedan en la wallet (`destiny: wallet` en conciliación) y hay que retirarlas.

---

## Realizar pagos a terceros

```http
POST /api/wallet/payout
```

| Campo | Tipo | Req. | Descripción ✅ |
|---|---|---|---|
| `email` | string | ✓ | Máx. 50. |
| `phone` | string | | Máx. 20. |
| `subject` | string | ✓ | Máx. 200. |
| `currency` | string | ✓ | ISO (`CLP`). |
| `order` | string | ✓ | Máx. 50. |
| `amount` | integer | ✓ | Máx. 14 dígitos. |
| `accountbank_name` | string | ✓ | Titular. Máx. 180. |
| `accountbank_rut` | string | ✓ | RUT `111111111`. Máx. 15. |
| `accountbank_sbif` | string | ✓ | Código de banco (ver [catalogs.md](catalogs.md)). Máx. 4. |
| `accountbank_type` | string | ✓ | `1` Corriente, `2` Vista/Cuenta RUT, `3` Ahorro. |
| `accountbank_num` | string | ✓ | N° de cuenta. Para BancoEstado (`0012`) máx. 12 dígitos (evita que ingresen el n° de tarjeta). |
| `url_notify` | string | | Callback del resultado (ver [webhooks.md](webhooks.md#25-payout-)). |
| `additional_parameters` | object | | Incluye `order_ext`. |

Respuesta: `{"status": "success", "identifier_wallet": "wab5…", "identifier_payout": "mor33…"}`. `status`: `success` / `failed`.

---

## Retirar dinero de la wallet

```http
POST /api/wallet/withdraw
```

Body: `subject` ✓, `currency` ✓, `order` ✓ (máx. 80), `amount` ✓. Respuesta: `{"status": "success", "identifier_wallet": "…"}`. ✅

---

## Obtener saldo

```http
GET /api/wallet
```

Respuesta ✅: `status`, `current_id`, `amount_available`, `currency`, `filter{page, per_page, currency, id}`, `wallet_movements[]`.

## Obtener movimientos

```http
GET /api/wallet/list?page=1&per_page=100
```

Paginado, máx. **4000** por página. ✅ Misma forma que "Obtener saldo". Filtros: la doc dice "posee los siguientes filtros:" y no lista ninguno. ⚠️

## Obtener movimiento

```http
GET /api/wallet/{identificadorWallet}
```

## Obtener payout / payout V3

```http
GET /api/payout/{identificadorPayout}
GET /api/payoutv3/{identificadorPayout}
```

V3 agrega `reason_rejection` (ej. `"Error CCA 51. Cuenta Beneficiario no Existe, error_creditor_account_not_found"`). ✅ 💡 Usa V3.

Estados de payout: `pending`, `processing`, `success`, `banking_error`, `fraud_prevention` → [statuses.md § 10](statuses.md#10-wallet-y-payouts).

### Campos del movimiento ✅

| Campo | Descripción |
|---|---|
| `id` | ID del movimiento (`wa…`). |
| `order`, `subject` | Orden y descripción. |
| `created_at` | Fecha. |
| `income_expense` | `expense` (pago a tercero o retiro). |
| `status` | `current` (ejemplo). |
| `amount`, `actual_amount` | Monto del movimiento y saldo resultante (strings). |
| `origin_liquidation` | Liquidación de origen (💡 cruce con conciliación). |
| `payout{…}` | Datos de la cuenta destino. |
