# Tarjetas de suscripción

Documentación oficial: https://docs.payku.com/cl/api/subscriptions/ ("Afiliar tarjeta", "Eliminar tarjeta") y https://docs.payku.com/cl/api/consumption-subscriptions/ ("Eliminar tarjeta")

**Autenticación:** `Bearer` + `Sign` ✅

> Nunca manejamos números de tarjeta. El cliente los ingresa en el formulario de Payku (la `url` que devuelve la API). Nosotros solo vemos `identifier`, últimos 4 dígitos y tipo.

---

## Dónde aparecen las tarjetas

| Endpoint | Campo | Forma | Trae `identifier` |
|---|---|---|---|
| `GET /api/suclient/{id}` | `active_cards` | arreglo | ✅ |
| `GET /api/suclient/{id}` | `subcriptions.cards` | arreglo | ❌ |
| `GET /api/sususcription/{id}` | `active_cards` | arreglo | ✅ |
| `GET /api/sususcription/{id}` | `cards` | objeto | ❌ |
| `GET /api/sususcription` (V1) | `cards` | objeto | ❌ |
| `GET /api/sususcriptionv3` | `active_cards` | **objeto** | ❌ |

Campos: `last_4_digits` (viene enmascarado: `XXXXXXXXXXXX6622`), `identifier` (`surec…`), `card_type` (`Visa`, `MasterCard`), `register` (fecha de inscripción). ✅

---

## Afiliar tarjeta (inscribir / renovar)

### Endpoint

```http
POST /api/suinscriptionscards
```

### Propósito
- Genera una **URL** para que el cliente inscriba una **nueva tarjeta** en una suscripción existente. ✅
- Caso de uso oficial: renovación de tarjeta (vencida, perdida, rechazos). ✅
- **Importante (✅ textual):** "Inmediatamente a la actualización de la tarjeta asociada a la suscripción, el sistema podrá realizar los **cargos atrasados** correspondientes según configuración del plan suscrito. Es decir, si la suscripción se encuentra en estatus **suspendido por máximos intentos** de cobros realizados, y el cliente registra una nueva tarjeta, el sistema podrá revisar los pagos pendientes, hacer el cargo correspondiente, y **activar automáticamente** la suscripción."

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `suscription` | string | ✓ | ID de la suscripción. Máx. 60. ✅ |

```json
{ "suscription": "sucaab7865dceaff49d8b3" }
```

### Response (200)

```json
{
  "status": "success",
  "id": "sucaab7865dceaff49d8b3",
  "url": "https://BASE_URL/gateway/registrosuscripcion?plan=true&token=246&validacion=d6b32"
}
```

### Consideraciones
- `status: success` solo significa que se generó la URL; la tarjeta queda inscrita cuando el cliente completa el formulario. 💡
- ⚠️ No está documentado si se vuelve a cobrar la validación de $50.
- ⚠️ No está documentado si la tarjeta anterior se desactiva sola.
- 💡 Avísale al socio que se pueden cobrar **meses atrasados** al inscribir la tarjeta (evita reclamos).
- Flujo completo: [workflows/update-card.md](workflows/update-card.md).

---

## Eliminar tarjeta

### Endpoint

```http
POST /api/suscriptionsdeletecards
```

(Es `POST`, no `DELETE`. ✅)

### Request body — ⚠️ contradicción en la documentación oficial

| Fuente oficial | Campo |
|---|---|
| Tabla de parámetros | `suscription` (string, requerido), descrito como "**ID de la tarjeta** asociada", ej. `surec804a8ed60c0a8cb8839` |
| Ejemplo cURL / JSON | `card` con el mismo valor `surec…` |
| Error 400 documentado | `{"status":"failed","type":"card","message_error":"is not valid"}` → habla de `card` |

```json
{ "card": "surec804a8ed60c0a8cb8839" }
```

💡 **Conclusión de trabajo:** el valor es el **`identifier` de la tarjeta** (no el ID de la suscripción) y el nombre del campo más probable es **`card`**. ⚠️ Validar en sandbox (Q-09).

⚠️ **Nuestra colección Postman** envía `{"suscription": "<ID de suscripción>"}` → probablemente incorrecto en **nombre y valor**. Ver [postman.md](postman.md).

### Response (200)

```json
{ "status": "Delete", "card": "surec804a8ed60c0a8cb8839" }
```

### Errores

| HTTP | Respuesta | Causa |
|---|---|---|
| 400 | `{"status": "failed", "type": "card", "message_error": "is not valid"}` | Identificador de tarjeta inválido. ✅ |

### Consideraciones
- ⚠️ No está documentado qué pasa si se elimina la **única** tarjeta de una suscripción activa (💡 los cobros fallarán y la suscripción terminará `suspended`).
- 💡 No elimines tarjetas como forma de "pausar" una suscripción.
