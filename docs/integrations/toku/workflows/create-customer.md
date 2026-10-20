# Flujo: crear (o actualizar) un Customer

## 1. Qué necesitamos hacer
Registrar a un socio en Toku, de forma idempotente, para poder colgarle planes, cuotas y medios de pago.

## 2. Endpoints
```http
GET  /customers/lookup?external_id={id}     # opcional: ¿ya existe?
POST /customers                             # upsert por external_id
```

## 3. Recurso involucrado
Customer (`cus_…`). Ver [customers.md](../customers.md).

## 4. Parámetros necesarios
- `external_id`: nuestro ID estable (ver [data-model.md](../data-model.md#uso-de-nuestros-propios-ids-como-referencia-recomendación)).
- `government_id`, `name`, `mail`, `phone_number` (formato `+569…`).
- `send_mail: false`, salvo que **queramos** disparar la invitación de inscripción.

## 5. Ejemplo de request
```bash
curl -X POST https://api.trytoku.com/customers \
  -H "x-api-key: $TOKU_API_KEY" -H "Content-Type: application/json" \
  -d '{"external_id":"TEST-SOCIO-0001","government_id":"11111111-1","name":"Socio TEST","mail":"pruebas@techo.org","phone_number":"+56900000000","default_receipt_type":"no_receipt","send_mail":false}'
```

## 6. Response
`201` (creado) o `200` (actualizado), con el Customer completo, incluido `id: "cus_…"`.

## 7. Implementación backend
```text
1. Validar el RUT y el formato del teléfono y el mail localmente (evita TK30402/4/5).
2. POST /customers (es upsert: no hace falta el lookup previo).
3. Guardar toku_customer_id ← response.id en BD_CENTRAL (UNIQUE).
4. Ante timeout o 5xx: reintentar el MISMO body (idempotente por external_id).
5. Ante 422: no reintentar; registrar error.code y avisar.
6. Ante TK20401 (bloqueado por otra carga): reintentar con backoff.
```

## 8. Qué guardar
`toku_customer_id`, `external_id`, `created_via_api_at` (fecha nuestra), y la respuesta en `stg_toku_customers`.

## 9. Consideraciones
- **No usar `PUT` para cambiar `external_id`** (TK30411).
- `metadata`: solo claves declaradas en la webapp.
- Pruebas: ver [authentication.md](../authentication.md#3-ambientes-confirmado).
- Errores: un `401` significa key mala; un `429` significa que vamos a más de 20 req/s.
