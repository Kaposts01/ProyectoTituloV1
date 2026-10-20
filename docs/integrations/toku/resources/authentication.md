# Autenticación, headers, ambientes y versionamiento

Docs oficiales:
- <https://docs.trytoku.com/reference/autenticacion>
- <https://docs.trytoku.com/reference/conexion-y-ambientes>
- <https://docs.trytoku.com/reference/headers-y-convenciones>
- <https://docs.trytoku.com/reference/versionamiento>
- <https://docs.trytoku.com/docs/dónde-conseguir-mi-api-key>

## 1. Mecanismos de autenticación

### API Key (el que usamos hoy) [Confirmado]

- Identifica a la **Organización**.
- Se obtiene en el Backoffice: *Settings → Organization* (`https://app.trytoku.com/settings?tab=company`).
- Se envía en **cada** request:

```http
GET /invoices/in_K3a1P1_p_t5UHJHJXmpkQYmqXCHvXrNi HTTP/1.1
Host: api.trytoku.com
x-api-key: {{api_key}}
```

- Sin credencial válida → `401`. Esos requests **no** cuentan para el rate limit.

### OAuth M2M (opcional, hay que pedirlo) [Confirmado]

- OAuth 2.0 *client credentials*, con **Auth0** como proveedor.
- Se solicita a Toku y te entregan `client_id` y `client_secret`.
- El token se pide **a Auth0, no a Toku**:

```http
POST https://toku-prod.us.auth0.com/oauth/token
Content-Type: application/json

{
  "client_id": "...",
  "client_secret": "...",
  "audience": "https://toku-prod.us.auth0.com/api/v2/",
  "grant_type": "client_credentials"
}
```

- La respuesta trae `access_token` y `expires_in`. Se envía como `Authorization: Bearer <token>`. Hay que reutilizarlo hasta que venza; no pedir uno nuevo en cada llamada.
- La referencia también lista un endpoint de Toku, "Obtener Access Token M2M" (<https://docs.trytoku.com/reference/create_m2m_access_token>). **[No confirmado]** cuál de los dos caminos es el vigente para nuestra organización. Preguntar a Toku antes de migrar.

> ⚠️ **Activar OAuth deshabilita la API Key** de la organización. Las dos no conviven. Si algún día migramos, hay que cambiar **todas** las integraciones (Apps Script, Postman, backend) en la misma ventana. [Confirmado]

**[Recomendación]** Mantener API Key mientras exista un solo consumidor controlado. Evaluar OAuth cuando haya un backend productivo con varios procesos: las credenciales vencen solas y eso limita el daño si se filtra un token.

## 2. Headers

| Header | Requerido | Uso | Estado |
|---|---|---|---|
| `x-api-key` | Sí (si no hay OAuth) | API key de la organización | [Confirmado] |
| `Authorization` | Sí (solo con OAuth) | `Bearer <access_token>` | [Confirmado] |
| `Content-Type` | Sí en requests con body | `application/json` | [Confirmado] |
| `x-account-key` | No | Selecciona una **cuenta de cobro** (Account) cuando la organización tiene más de una. Si se omite, se usa la cuenta por defecto. Cada cuenta tiene su propia key, en *Ajustes → Cuentas de cobro*. | [Confirmado] |
| `x-api-version` | No | Fija el contrato de respuesta por fecha (`YYYY-MM-DD`) | [Confirmado] |
| `accept: application/json` | No documentado | Lo enviamos por costumbre; no hace daño | [No confirmado] como requisito |

## 3. Ambientes [Confirmado]

- **Un único ambiente productivo**: `https://api.trytoku.com`.
- **No existe sandbox documentado.** Cualquier `POST`, `PUT` o `DELETE` afecta datos reales y puede disparar comunicaciones reales a personas.

**[Recomendación]** Reglas para probar en producción:
1. Usar identificadores reconocibles: `external_id` y `product_id` que empiecen con `TEST-`.
2. Usar un Customer de prueba propio, con mail interno.
3. En Invoices de prueba, enviar `disable_automatic_payment: true` para que no se intente cobrar.
4. En Checkout Sessions, usar `skip_message_trigger: true`.
5. Limpiar después de probar: `DELETE` de invoice → subscription → customer.
6. Renombrar el environment de Postman `Toku_Sandbox` (el nombre es engañoso) a `Toku Producción`.

## 4. IPs (allowlist) [Confirmado]

Solo hace falta si nuestro firewall o el del hosting filtra por IP.

| Dirección | IPs |
|---|---|
| **Salida** hacia `api.trytoku.com` | `34.136.254.4`, `34.57.239.254` |
| **Entrada** de webhooks desde Toku | `104.154.245.89`, `34.172.19.54`, `34.31.115.250`, `35.226.213.73`, `34.171.79.203`, `34.67.45.238`, `35.202.151.97`, `136.113.249.93`, `34.31.185.0`, `34.68.121.33`, `34.63.217.155` |
| Proxies | `52.5.142.59`, `34.226.132.221`, `52.54.43.157` |
| Restricciones geográficas | `34.9.136.215`, `34.121.34.90` |

**[No confirmado]** si estas listas cambian ni cómo se avisa. **[Recomendación]** No usar la IP como única validación de webhooks: validar siempre la firma.

## 5. Versionamiento

### Lo que dice la doc [Confirmado]

- Algunos endpoints y webhooks tienen versiones por fecha. Cada versión devuelve siempre el mismo objeto.
- Se elige con el header `X-API-Version: YYYY-MM-DD`. Toku entrega la última versión publicada **antes o en** esa fecha.
- Las páginas de cada endpoint dicen: *"Si se omite, se deriva de la fecha de creación de la organización."*
- **Webhooks:** al suscribir un endpoint, este queda amarrado a la versión vigente en esa fecha (campo `webhook_version`). Las versiones posteriores no cambian lo que recibe.

### ⚠️ Inconsistencia en la doc oficial

| Fuente | Qué dice |
|---|---|
| Página *Versionamiento* | Lista solo `default` = V1, `2024-08-13` = V2 y `2025-01-14` = V3. |
| Páginas de endpoints | Declaran `x-toku-api-version` `2026-10-08` (o `2026-09-22`, `2026-09-07`, según la página), y versiones internas de DTO (`DTOInvoiceV4`, `DTOCustomerV2`, `DTOTransactionV10`, `DTOPaymentMethodV7`). |

**[Inferencia]** La página de versionamiento está desactualizada respecto del OpenAPI. Los DTO evolucionan por separado.

**[Recomendación]**
1. Hoy no enviamos `x-api-version`: recibimos la versión derivada de la fecha de creación de la organización.
2. Antes de fijarla: hacer un `GET` con y sin `x-api-version: 2026-10-08` en cada listado, comparar los campos y ajustar los mappers.
3. Después, **fijarla siempre** (en la variable `{{api_version}}` de Postman y en la config del backend), para que un cambio de Toku no rompa la integración en silencio.

## 6. Manejo seguro de credenciales [Recomendación]

- Apps Script: `PropertiesService` (Script Properties), nunca en el código.
- Backend: variables de entorno o un secret manager. Nunca en el repo; `.env` en `.gitignore`.
- Postman: variable `api_key` de tipo **secret** en el environment, con *current value* (no *initial value*) para que no se sincronice ni se exporte.
- Logs: nunca registrar el header completo. Si hace falta trazabilidad, solo los últimos 4 caracteres.
- Si una key se expone, rotarla de inmediato en el Backoffice.
