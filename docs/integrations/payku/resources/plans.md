# Planes (`/api/suplan`)

Documentación oficial:
- Obtener plan / Obtener planes: https://docs.payku.com/cl/api/subscriptions/
- Crear plan: https://docs.payku.com/cl/api/consumption-subscriptions/

**Autenticación:** `Authorization: Bearer` + `Sign` ✅

---

## Qué es un plan

El plan es el **"producto"** al que se suscribe un cliente. Payku menciona tres tipos ✅:

| Tipo | Cómo se cobra | Fuente |
|---|---|---|
| **Monto fijo** | Payku cobra automáticamente "a partir del mes siguiente de la fecha de suscripción". ✅ | Crear suscripción |
| **Consumo** | Nosotros generamos cada cobro con `POST /api/sutransaction`. ✅ | Crear suscripción / Suscripción de consumo |
| **Monto variable** | Al crear la suscripción se envía el `amount` a cobrar; moneda CLP. ✅ | Crear suscripción |

⚠️ **No confirmado en la documentación oficial de Payku:**
- Cómo se indica el **tipo** de plan al crearlo (el body de "Crear plan" no tiene ese campo).
- Dónde se definen el **monto** y la **periodicidad** de un plan de monto fijo (el plan no los expone en `GET`).
- 💡 Inferencia: los planes de monto fijo / variable se configuran en el **panel de Payku**, y la API solo los lee. "Crear plan" vía API aparece únicamente en la sección *Suscripción de consumo*.

---

## Crear plan

### Endpoint

```http
POST /api/suplan
```

### Documentación oficial
https://docs.payku.com/cl/api/consumption-subscriptions/ → "Crear plan"

### Propósito
Crear un plan con sus URL de notificación y de redirección. 💡 Documentado para planes de **consumo**.

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `name` | string | ✓ | Nombre. Máx. **20** caracteres. ✅ |
| `description` | string | | Máx. 1000. |
| `url_notify_suscription` | string | | URL donde se notifica el **estado de la suscripción**. Máx. 240. ✅ |
| `url_notify_payment` | string | | URL donde se notifica el **estado del pago**. Máx. 240. ✅ |
| `url_success_payment` | string | | Redirección del usuario si el pago es exitoso. Máx. 240. ✅ |
| `url_failed_payment` | string | | Redirección si el pago falla. Máx. 240. ✅ |

```json
{
  "name": "Test plan",
  "description": "Test Plan",
  "url_notify_suscription": "https://youwebsite.com/urlnotifysuscription",
  "url_notify_payment": "https://youwebsite.com/urlnotifypayment",
  "url_success_payment": "https://youwebsite.com/urlsuccesspayment",
  "url_failed_payment": "https://youwebsite.com/urlfailedpayment"
}
```

### Response (200)

```json
{ "status": "success", "id": "pl4293e97a87195bb9edcd" }
```

### Consideraciones
- ⚠️ No hay endpoint para **actualizar** ni **eliminar** un plan. Las URL de notificación quedan fijas al crear (o se cambian desde el panel 💡).
- 💡 Usa URL de notificación con un token secreto propio en el query string (p. ej. `…/payku/notify-payment?k=<secreto>`), porque Payku no firma las notificaciones (ver [webhooks.md](webhooks.md)).

---

## Obtener plan

### Endpoint

```http
GET /api/suplan/{identificadorPlan}
```

### Path parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `identificadorPlan` | string | ✓ | ID del plan. Máx. 20. ✅ |

### Response (200)

```json
{
  "status": "success",
  "plans": {
    "id": "pl4293e97a87195bb9edcd",
    "status": "active",
    "name": "Test plan",
    "code": "001",
    "description": "Test Plan",
    "url_notify_payment": "",
    "url_notify_suscription": "",
    "total_suscription": 0,
    "total_suscription_active": 0
  }
}
```

Nota: aunque es un solo plan, la clave se llama `plans` (en plural) y es un **objeto**. ✅

### Campos importantes

| Campo | Tipo | Descripción | Uso interno 💡 |
|---|---|---|---|
| `id` | string | ID del plan. | Clave del catálogo de planes. |
| `status` | string | Estado (`active`). | — |
| `code` | string | Código del plan. | Útil para mapear a nuestros "productos" (p. ej. "Socio mensual"). |
| `url_notify_payment` / `url_notify_suscription` | string | URL de notificación configuradas. | **Verificar** que apuntan a nuestro backend del ambiente correcto. |
| `total_suscription` / `total_suscription_active` | int | Totales. | Control de cuadratura: comparar con nuestro conteo. |

---

## Obtener planes

### Endpoint

```http
GET /api/suplan/plans
```

### Response (200)

```json
{ "status": "success", "plans": [ { "id": "pl4293e97a87195bb9edcd", "status": "active", "name": "Test plan", "code": "001", "description": "Test Plan", "url_notify_payment": "", "url_notify_suscription": "", "total_suscription": 0, "total_suscription_active": 0 } ] }
```

### Consideraciones
- No paginado (según la doc). ✅
- ⚠️ Es un GET **sin parámetros** → aplica la duda del `&` final en la firma (Q-01).
- 💡 Ejecútalo al inicio de cada sincronización para refrescar el catálogo y verificar las URL de notificación.

---

## Contradicción documentada: ¿dónde se configuran las URL de notificación?

| Fuente | Qué dice |
|---|---|
| Callbacks ("url Callback notificación suscripción / cobro") | "…la url de notificación … suministrada previamente **en la creación de la suscripción**". |
| "Crear suscripción" | El body **no** tiene campos de URL (solo `plan`, `client`, `amount`, `coupon`). |
| "Crear plan" / "Obtener plan" | El **plan** tiene `url_notify_suscription` y `url_notify_payment`. |

💡 **Conclusión de trabajo:** las URL se configuran **en el plan**. ⚠️ Validar en sandbox (Q-04).
