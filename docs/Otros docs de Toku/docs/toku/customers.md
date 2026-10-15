# Customers

Objeto: <https://docs.trytoku.com/reference/customer-object>

## Qué es

El **Customer** es la persona que le paga a la organización: en TECHO, el socio o donante. Todo cuelga de él: Subscriptions, Invoices y Payment Methods. [Confirmado]

**Autenticación y errores comunes:** ver [authentication.md](authentication.md) y [errors.md](errors.md). Todos los endpoints de este archivo usan `x-api-key`, aceptan `x-account-key` y `x-api-version`, y tienen un límite de **20 req/s**.

## Objeto Customer [Confirmado]

| Campo | Tipo | Descripción | Uso interno |
|---|---|---|---|
| `id` | string (`cus_…`) | ID público de Toku. **Único campo requerido en la respuesta.** | PK en STG; FK en todo |
| `external_id` | string ≤128 | ID definido por la organización. Por defecto, la mayoría de las organizaciones usa el `government_id`. **Clave de idempotencia del upsert.** | Llave de cruce con BD_CENTRAL |
| `government_id` | string ≤64 | RUT (Chile) / CURP-RFC (MX) | PII: guardar normalizado |
| `name` | string ≤128 | Nombre | PII |
| `mail` | string ≤128 | Email | PII |
| `secondary_emails` | string[] | Emails adicionales | PII |
| `phone_number` | string ≤16 | Teléfono (lo usan para SMS/WhatsApp) | PII |
| `default_receipt_type` | enum | `bill` (boleta, por defecto), `invoice` (factura), `no_receipt` | |
| `default_agent` | string ≤128 | Email del agente que atiende al Customer | |
| `agent_phone_number` | string ≤16 | Teléfono del agente | |
| `pac_mandate_id` | string ≤64 | ID del mandato PAC | Útil para conciliar PAC |
| `metadata` | object string→string | Campos extra de la organización. **Las claves deben declararse antes en la webapp de Toku** (si no, `422`). | Guardar como JSON |
| `send_mail` | boolean (default `false`) | Si es `true` al crear, emite el webhook `invoice.no_payment_method` (la guía lo describe como el envío de la secuencia "Invitación inscripción medio de pago") | ⚠️ Dispara comunicaciones |
| `silenced_until` | date-time | Hasta cuándo el Customer está "silenciado" (sin comunicaciones). `null` = no silenciado | |
| `rfc`, `fiscal_regime`, `tax_zip_code` | string | Solo México (CFDI) | Ignorar en Chile |

Campos que **solo se aceptan en el request** (no vuelven en la respuesta): `admin_area`, `admin_code`, `city`, `detail`, `neighborhood`, `postal_code`, `street_name`, `street_number` (dirección). [Confirmado]

No hay `created_at` ni `updated_at` en el objeto. [Confirmado por ausencia en el schema] Esto impacta la sincronización incremental: ver [workflows/sync-toku.md](workflows/sync-toku.md).

---

## Listar Customers

### Endpoint
```http
GET /customers
```
Doc: <https://docs.trytoku.com/reference/get_customers>

### Propósito
Recorrer o buscar Customers. Es el endpoint para la **carga inicial** y la **reconciliación periódica** hacia STG_TOKU. Si ya tienes el `id`, usa `GET /customers/{id}`.

### Query parameters
| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `page_size` | integer | No | Por defecto 50, máx. 100 |
| `next_cursor` | string | No | Cursor de la respuesta anterior |
| `mail` | string | No | Filtra por email |
| `external_id` | string | No | Filtra por ID externo |
| `rfc` | string | No | México |
| `start_date` | date-time ISO 8601 | No | Creados desde (inclusive) |
| `end_date` | date-time ISO 8601 | No | Creados hasta (inclusive) |

Los filtros se combinan con AND. **Filtran por fecha de creación**, no de modificación.

### Response 200
```json
{
  "items": [ { "id": "cus_…", "external_id": "18579878K", "name": "…", "mail": "…" } ],
  "next_cursor": "…"
}
```

### Paginación
Por cursor. Ver [pagination.md](pagination.md).

---

## Crear Customer (upsert)

### Endpoint
```http
POST /customers
```
Doc: <https://docs.trytoku.com/reference/create_customer>

### Propósito
Crea un Customer, o **lo actualiza si ya existe uno con el mismo `external_id`**. Es el primer paso de cualquier alta. [Confirmado]

### Request body
Ningún campo está marcado como requerido en el schema, pero en la práctica hay que enviar `external_id` (si no, puede devolver `TK30400`) y los datos de contacto.

```json
{
  "external_id": "TEST-Client-001",
  "government_id": "11111111-1",
  "name": "Cliente TEST",
  "mail": "pruebas@techo.org",
  "phone_number": "+56900000000",
  "default_receipt_type": "no_receipt",
  "send_mail": false
}
```

### Response
| Código | Cuándo |
|---|---|
| `201` | Creado |
| `200` | Ya existía (mismo `external_id`) y se actualizó. ⚠️ El `200` está en la descripción, pero el schema OpenAPI solo declara `201`. |

Body: el Customer (`CreateOrUpdateCustomerResponse`).

### Consideraciones
- **Idempotente por `external_id`.** Reintentar con el mismo body es seguro. [Confirmado]
- **Los campos que no se envían no se tocan.** [Confirmado]
- `send_mail: true` dispara comunicaciones reales. En pruebas, siempre `false`.
- **[Recomendación]** Usar como `external_id` el ID del socio en BD_CENTRAL o el RUT normalizado, según lo que tenga configurado la organización en Toku (`customer_external_id_parameter`, ver `TK30401`). **[No confirmado]** cuál es la configuración actual de TECHO: verificarlo con un `GET /customers?page_size=5` mirando si `external_id == government_id`.

---

## Buscar Customer por identificadores externos

### Endpoint
```http
GET /customers/lookup?external_id={external_id}
```
Doc: <https://docs.trytoku.com/reference/lookup_customer>

### Propósito
Encontrar **un** Customer cuando tenemos nuestro ID o su mail, pero no el `cus_`. Ideal para cruzar BD_CENTRAL → Toku.

### Query parameters
| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `external_id` | string | Al menos uno | ID externo |
| `mail` | string | Al menos uno | Email |
| `rfc` | string | Al menos uno | México |

La combinación debe identificar **exactamente un** Customer.

### Response
`200` con el Customer, o `404` si no existe.

**[No confirmado]** Qué responde si varios Customers comparten el mismo `mail`. Preferir `external_id`.

---

## Obtener Customer

### Endpoint
```http
GET /customers/{encrypted_customer_id}
```
Doc: <https://docs.trytoku.com/reference/get_customer>

| Path param | Tipo | Requerido | Descripción |
|---|---|---|---|
| `encrypted_customer_id` | string | Sí | `cus_…` |

`404` si no existe o es de otra organización. El objeto Customer dice que se puede referenciar por `external_id`, pero **este endpoint solo documenta el `cus_`**. Para buscar por `external_id`, usa `/customers/lookup`.

---

## Editar Customer

### Endpoint
```http
PUT /customers/{encrypted_customer_id}
```
Doc: <https://docs.trytoku.com/reference/edit_customer>

### Propósito
Actualización parcial: solo cambian los campos enviados. Devuelve `200` con el Customer.

### Consideraciones
- ⚠️ **`external_id` es inmutable.** El schema del body lo acepta, pero el catálogo de errores define `TK30411` ("El `external_id` del Customer no se puede actualizar") y en nuestras pruebas devolvió `409`. **No enviarlo en el PUT.** [Confirmado: catálogo + prueba propia]
- `metadata`: las claves deben existir en la webapp (si no, `422`).
- **[Inferencia]** Para cambios de datos de contacto, `POST /customers` con el mismo `external_id` logra lo mismo, y es más simple de reintentar.

---

## Eliminar Customer

### Endpoint
```http
DELETE /customers/{encrypted_customer_id}
```
Doc: <https://docs.trytoku.com/reference/delete_customer>

`204` sin body. `404` si no existe. **[No confirmado]** El efecto en cascada sobre sus Subscriptions, Invoices y Payment Methods; `TK30407` indica que puede haber conflictos lógicos. **[Recomendación]** Usarlo solo para limpiar datos de prueba, nunca en socios reales.

---

## Listar Invoices de un Customer

### Endpoint
```http
GET /customers/{customer_encrypted_id}/invoices
```
Doc: <https://docs.trytoku.com/reference/list_customer_invoices>

### Propósito
Ver el historial de cobros de **un** Customer (por ejemplo, para la atención al socio). Devuelve un **array sin paginar** de Invoices, dentro de la Account autenticada.

**No confundir** con `GET /invoices/customer/{id}` (ver [invoices.md](invoices.md)), que es casi igual pero responde `404` cuando el Customer no tiene Invoices. Para sincronizar, Toku recomienda `GET /invoices?customer_id=`.

---

## Webhooks relacionados
`customer.created`, `customer.updated`, `customer.deleted`. Ver [webhooks.md](webhooks.md).

## Qué guardar en BD [Recomendación]
- STG: el JSON completo + `id` + `external_id` + `fetched_at` + `source` (`api`/`webhook`) + hash del payload.
- Normalizado: `toku_customer_id` (UNIQUE), `external_id`, el RUT normalizado y los datos de contacto según la política de PII.
