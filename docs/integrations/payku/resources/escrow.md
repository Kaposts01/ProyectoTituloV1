# Transacción Escrow (`/api/escrow`)

Documentación oficial: https://docs.payku.com/cl/api/escrow/

"Permitirá a las cuentas **escrow autorizadas por payku** realizar la liquidación de transacciones." ✅ Requiere que Payku habilite la cuenta como escrow.

💡 Relevancia para TECHO: ninguna, salvo que la cuenta sea escrow.

**Autenticación:** `Bearer` (sin `Sign` en el ejemplo). ✅

---

## Autorizar liquidación

```http
POST /api/escrow
```

Body ✅:

```json
{ "transactions": ["trx3b4d77b43acd9a720", "trx3b4d77b43acd9a385"] }
```

Respuesta ✅:

```json
{
  "transactions": [
    { "status": "liquidate", "transaction_id": "trx3b4d77b43acd9a720", "amount": 15000, "availability_date": "2021-07-01", "deposit_date": "2021-07-06" },
    { "status": "pending", "transaction_id": "trx3b4d77b43bdd9a540", "amount": 20000, "availability_date": "2021-07-25", "deposit_date": "N/D" }
  ]
}
```

Estados: `not found`, `pending`, `liquidate`, `pending for deposit`, `paid`. ✅
`deposit_date` puede ser `"N/D"` (texto) cuando aún no hay fecha. ✅
