# Flujo: cancelar (dar de baja) una suscripción

## 1. Qué necesitamos hacer
Detener los cobros futuros de un socio que se da de baja.

## 2. Endpoint necesario

```http
DELETE /api/sususcription/{identificadorSuscripcion}
```

Es el **único** mecanismo documentado. ✅ No existe "cancelar" ni "pausar" por separado.

## 3. Recurso involucrado
Suscripción → [subscriptions.md](../subscriptions.md#eliminar-suscripción-cancelar).

## 4. Parámetros necesarios
ID de la suscripción (`su…`) en el path. `Sign` obligatorio.

## 5. Ejemplo de request

```bash
curl -X DELETE "https://des.payku.cl/api/sususcription/sucaab7865dceaff49d8b3" \
  -H "Authorization: Bearer $PAYKU_PUBLIC_TOKEN" \
  -H "Sign: <firma de /api/sususcription/sucaab7865dceaff49d8b3>" \
  -H "Accept: application/json"
```

## 6. Ejemplo de response

```json
{ "id": "sucaab7865dceaff49d8b3", "status": "success" }
```

## 7. Cómo implementarlo en backend 💡

1. Registrar la **solicitud de baja** en nuestra BD (quién, cuándo, motivo) **antes** de llamar a Payku.
2. `DELETE`. Si responde `status: success` → marcar `BAJA_SOLICITADA_OK`.
3. `GET /api/sususcription/{id}` para leer el estado final real (`delete` o `cancel` ⚠️) y guardarlo literal.
4. Revisar `transactions[]`: si hay un cobro `pending`/`retry` en curso, avisar a soporte (⚠️ no sabemos si se detiene).
5. **No** eliminar el cliente (conservar historial).
6. Timeout o 5xx: es seguro reintentar el `DELETE` (💡), pero confirma con `GET`.

## 8. Qué datos guardar
`suscripcion.estado_origen` (lo que diga el `GET` posterior), `fecha_baja`, `motivo_baja`, `solicitada_por`, request/response en `stg_payku_api_call_log`.

## 9. Consideraciones importantes
- **Irreversible** 💡: no hay endpoint de reactivación. Si el socio vuelve, se crea una **suscripción nueva** (y vuelve a pasar por la inscripción de tarjeta y la validación de $50 ✅).
- ⚠️ No sabemos si el `DELETE` genera webhook a `url_notify_suscription`.
- Si el socio pide "pausar", no hay equivalente por API: ver [suspend-subscription.md](suspend-subscription.md).
