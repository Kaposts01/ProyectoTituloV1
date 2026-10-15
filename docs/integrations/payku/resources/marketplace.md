# Marketplace (`/api/maclient`, `/api/maaffiliation`)

Documentación oficial: https://docs.payku.com/cl/api/marketplace/

"Permite el registro de clientes, para posteriormente realizar la distribución según porcentaje asignado." ✅

💡 Relevancia para TECHO: baja. Sirve para repartir un pago entre varios comercios (p. ej. una plataforma que cobra por otros). **El "cliente" de marketplace no es el cliente de suscripción** (`/api/suclient`).

**Autenticación:** `Bearer`. Los ejemplos muestran `Sign` solo en "Actualizar cliente". ⚠️

---

## Clientes de marketplace

| Operación | Endpoint |
|---|---|
| Crear | `POST /api/maclient` |
| Obtener | `GET /api/maclient/{identificadorCliente}` |
| Actualizar | `PUT /api/maclient/{identificadorCliente}` |
| Eliminar | `DELETE /api/maclient/{identificadorCliente}` |

### Crear — body ✅

| Campo | Tipo | Req. | Descripción |
|---|---|---|---|
| `email` | string | ✓ | Máx. 50. |
| `name` | string | ✓ | Máx. 150. |
| `phone` | string | ✓ | Máx. 12. |
| `bank` | object | ✓ | `sbif` (código banco), `type` (1 Corriente, 2 Vista/RUT, 3 Ahorro), `num` (cuenta), `rut`. Todos ✓. |

Respuesta: `{id: "ma…", status: "register", name, phone, email, bank{…}, affiliations: 0, created_at, update_at}`.

### Actualizar — body ✅
`name`, `phone`, `bank{sbif, type, num, rut}` (todos opcionales). Respuesta incluye `affiliations_details[]`. ⚠️ El ejemplo de respuesta tiene `email: "923122312"` (error de copia).

### Eliminar ✅
Respuesta: `{"status": "suspended", "id": "ma…"}` → baja **lógica**.

---

## Afiliaciones

| Operación | Endpoint |
|---|---|
| Crear | `POST /api/maaffiliation` |
| Obtener | `GET /api/maaffiliation/{id}` |
| Eliminar | `DELETE /api/maaffiliation/{id}` |

### Crear — body ✅

| Campo | Tipo | Req. | Descripción |
|---|---|---|---|
| `name` | string | ✓ | Máx. 80. |
| `percentage` | string | ✓ | % para el usuario Payku (dueño de la cuenta). |
| `affiliation` | array | ✓ | `[["<id cliente ma…>", "<porcentaje>"], …]` |

Respuesta: `{id, status: "register", name, token, percentage, affiliations[{id, name, percentage}]}`. El **`token`** es el que se usa en el campo `marketplace` al crear una transacción. ✅

---

## Crear transacción marketplace

```http
POST /api/transaction
```

Igual que una transacción normal ([transactions.md](transactions.md)), más `marketplace` = `token` de la afiliación (máx. 70). Aquí `email`, `order` (**único**), `subject`, `amount` son obligatorios. ✅
