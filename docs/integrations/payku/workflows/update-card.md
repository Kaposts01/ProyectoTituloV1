# Flujo: cambiar o renovar la tarjeta de un socio

> **Para enviar el link al socio**, usa el [link seguro de inscripción](../../../../Transversal/docs/transversal/workflows/link-seguro-inscripcion.md) con el [adaptador de Payku](link-inscripcion.md) (caso B): la `url` se genera al hacer clic, después de verificar al socio. Este documento describe los endpoints de fondo.

## 1. Qué necesitamos hacer
Que un socio inscriba una tarjeta nueva (vencida, rechazos, suspensión) sin perder su suscripción.

## 2. Endpoints necesarios

| Paso | Endpoint |
|---|---|
| 1 | `POST /api/suinscriptionscards` → `url` para inscribir la tarjeta ✅ |
| 2 | (Socio completa la `url`) |
| 3 | `GET /api/sususcription/{id}` → ver `active_cards` y estado ✅ |
| 4 (opcional) | `POST /api/suscriptionsdeletecards` → quitar la tarjeta antigua ⚠️ |

## 3. Recurso involucrado
Tarjetas de la suscripción → [cards.md](../cards.md).

## 4. Parámetros necesarios
- Paso 1: `suscription` = ID de la suscripción.
- Paso 4: `identifier` de la tarjeta antigua (campo `card` ⚠️, ver Q-09).

## 5. Ejemplo de request

```json
POST /api/suinscriptionscards
{ "suscription": "sucaab7865dceaff49d8b3" }
```

## 6. Ejemplo de response

```json
{ "status": "success", "id": "sucaab7865dceaff49d8b3", "url": "https://des.payku.cl/gateway/registrosuscripcion?plan=true&token=246&validacion=d6b32" }
```

## 7. Cómo implementarlo en backend 💡
1. Generar la `url` bajo demanda (cuando el socio pulsa "Actualizar mi tarjeta"), no por adelantado (⚠️ vigencia desconocida).
2. Tras el retorno del socio (o en el próximo barrido), `GET /api/sususcription/{id}` y comparar `active_cards[].identifier` con lo guardado.
3. Si hay una tarjeta nueva y queremos dejar solo una, eliminar la antigua (⚠️ validar el body primero en sandbox).
4. Si estaba `suspended`, verificar en `logs.status[]` y `transactions[]` si Payku cobró los atrasados y la reactivó.

## 8. Qué datos guardar
`tarjeta_resumen` (identifier, últimos 4, tipo, fecha de registro, vigente), fecha de solicitud de cambio, resultado.

## 9. Consideraciones importantes
- ✅ Payku **puede cobrar ciclos atrasados de inmediato** al inscribir la tarjeta: informarlo al socio.
- ⚠️ No sabemos si se cobra otra validación de $50.
- ⚠️ No sabemos qué tarjeta usa Payku si hay varias activas (💡 la más reciente: `cards`).
