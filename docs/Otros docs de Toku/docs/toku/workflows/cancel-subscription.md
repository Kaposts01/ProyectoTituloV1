# Flujo: pausar, reanudar o dar de baja una Subscription

## 1. Qué necesitamos hacer
Detener los cobros de un socio, de forma temporal (pausa) o definitiva (baja), sin dejar cuotas "colgando".

## 2. Opciones

| Necesidad | Endpoint | Efecto [Confirmado] |
|---|---|---|
| **Pausa temporal** | `POST /subscriptions/{sub}/status` `{"status":"PAUSED"}` | No se generan nuevas Invoices. **Las ya generadas siguen** (y se pueden cobrar) |
| **Reanudar** | `POST /subscriptions/{sub}/status` `{"status":"ACTIVE"}` | Cobra desde el próximo ciclo con vencimiento ≥ hoy. **No cobra retroactivamente** los ciclos de la pausa |
| **Fin programado** | `PUT /subscriptions/{sub}` `{"end_date":"YYYY-MM-DD"}` | Genera deudas hasta esa fecha; luego **[Inferencia]** pasa a `FINISHED` |
| **Baja definitiva** | `DELETE /subscriptions/{sub}` | Detiene la generación de nuevas Invoices recurrentes |

## 3. Baja completa recomendada [Recomendación]

```text
1. GET /invoices?subscription_id={sub}&general_status=unpaid&general_status=partially_paid
2. Para cada Invoice impaga:
     si in_progress == true → NO tocar; esperar el resultado (24–48 h) y reintentar el flujo después
     si no → POST /invoices/{id}/void {"delete_invoice": false}
3. Decidir sobre la Subscription:
     - conservar el historial → POST /status PAUSED  (o end_date = hoy)
     - eliminar → DELETE /subscriptions/{sub}
4. (Opcional) Si el medio de pago no se usa en otras Subscriptions:
     DELETE /payment-methods?id_payment_method={pm}
5. Registrar en BD_CENTRAL: fecha_baja, motivo, usuario.
```

**Por qué anular las cuotas antes:** la doc solo garantiza que `DELETE` y `PAUSED` detienen las cuotas **nuevas**. **[No confirmado]** qué pasa con las impagas ya generadas. **[Inferencia]** Siguen vivas y se pueden cobrar si hay un medio de pago activo.

**[Recomendación]** Preferir `PAUSED` o `end_date` antes que `DELETE` para socios reales: conserva la trazabilidad, y `DELETE` no tiene vuelta atrás documentada.

## 4. Errores
- `409`: transición no permitida (por ejemplo, de `FINISHED` a `ACTIVE`).
- `TK30500`: conflicto lógico al eliminar (probablemente por Invoices en curso).
- `404`: el `sub_` no pertenece a la Account autenticada.

## 5. Webhooks
`subscription.updated` (pausa/reanudación), `subscription.deleted`, `invoice.voided`.
