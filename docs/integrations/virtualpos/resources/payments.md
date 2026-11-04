# Payments (Web Checkout)

> Fuente: https://virtualpos.readme.io/reference/objeto-payment · Verificado contra la doc oficial: 2026-10-12

Un **Payment** es una orden de pago *spot* (un cobro único). Es el objeto central de VirtualPOS: los cobros de las suscripciones (cargos PAT) también terminan generando un Payment.

**Modelo de integración (Web Checkout), según la doc oficial:**

1. **Crear Payment** → queda `pendiente` (expira a los 30 días).
2. **Obtener link Web Checkout** → todos los medios contratados o uno en particular.
3. **Redirigir** al pagador a `url_redirect`.
4. **Recibir y validar**: VirtualPOS redirige a tu `return_url` enviando `uuid` por HTTP POST, y además notifica tu `callback_url` (webhook). En ambos casos debes llamar a **Recuperar Payment** para conocer el resultado real.

Otras formas de cobrar un Payment ya creado: enviarlo por Email/WhatsApp/SMS, autorizarlo directo desde backend o renderizar el [Quick Checkout](quick-checkout.md).

## Endpoints de este recurso

| Método | Ruta | Operación |
| --- | --- | --- |
| `POST` | `/v3/payment/` | [Crear un objeto Payment](#crear-un-objeto-payment) |
| `POST` | `/v3/payment/{uuid}/webcheckout` | [Obtener link Web Checkout](#obtener-link-web-checkout) |
| `GET` | `/v3/payment/{uuid}` | [Recuperar un objeto Payment](#recuperar-un-objeto-payment) |
| `DELETE` | `/v3/payment/{uuid}` | [Cancelar un objeto Payment](#cancelar-un-objeto-payment) |
| `GET` | `/v3/payment/{uuid}/logs` | [Obtener el logs transaccional de un objeto Payment](#obtener-el-logs-transaccional-de-un-objeto-payment) |
| `GET` | `/v3/payments` | [Listar objetos Payment](#listar-objetos-payment) |
| `POST` | `/v3/payment/{uuid}/authorize` | [Autorizar un objeto Payment](#autorizar-un-objeto-payment) |
| `POST` | `/v3/payment/{uuid}/send` | [Envio de una solicitud de pago por Email, Whatsapp o SMS](#envio-de-una-solicitud-de-pago-por-email-whatsapp-o-sms) |
| `GET` | `/v3/payment/{uuid}/attempts` | [Obtener los intentos de pago un objeto Payment](#obtener-los-intentos-de-pago-un-objeto-payment) |

## Objeto Payment

| Status | Descripción |
| --- | --- |
| `pendiente` | Estado inicial, en espera de autorización financiera. |
| `pagado` | Estado final: tiene una transacción financiera autorizada. |
| `rechazado` | Estado final: rechazado financieramente o cancelado por el pagador. |
| `reintentando` | Estado intermedio: se intentará nuevamente la autorización. |
| `expirado` | Superó el tiempo máximo de espera (default 30 días). |
| `cancelado` | Estado final, solo desde `pendiente`; no puede cobrarse. |

> El filtro `status` de *Listar Payments* acepta además `suspendido`, `anulado` y `autorizando`, que no están descritos en esta tabla. `anulado` aparece en las retenciones del abono.

```json
{
  "payment": {
    "client": { "email": "user@example.com", "first_name": "John", "last_name": "Doe", "social_id": "12345678-9", "phone": "56961934502" },
    "order": {
      "uuid": "083613a748190d26",
      "status": "pagado",
      "created_at": "2021-09-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "2021-09-08 11:21:31",
      "auth_code": "1234",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "merchant_internal_code": "OC-1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": [
        { "description": "1/1", "installment": 9900, "processing_flat_fee": 0, "processing_fee": 117, "payout_amount": 9783, "payout_date": "2021-09-21" }
      ]
    }
  }
}
```

### `payment_type_code`

| Código | Tipo | Descripción |
| --- | --- | --- |
| `VD` | Débito | Venta débito |
| `VN` | Crédito | Venta crédito sin cuotas |
| `VC` | Crédito | Venta crédito cuotas bancarias |
| `SI` | Crédito | Crédito 3 cuotas sin intereses |
| `NC` | Crédito | Venta cuotas sin intereses |
| `S2` | Crédito | Crédito 2 cuotas sin intereses |
| `VP` | Prepago | Venta prepago |
| `TE` | Transferencia | Transferencia electrónica de fondos |

> **Tipos de datos inconsistentes:** cuando el pago está pendiente, `card_number`, `installment_amount`, etc. vienen como `""`; cuando está pagado vienen como número. Normaliza `"" → null`.

## Webcheckout Ruleset

> Fuente: https://virtualpos.readme.io/reference/webcheckout-ruleset · **Página nueva, no estaba en tu borrador.**

Un **Rule Set** controla qué medios de pago se muestran en el Web Checkout **según el monto** de la compra, en vez de mostrar todos los contratados. Se usa enviando `rule_set_uuid` al **Crear Payment**.

- Ejemplo de la doc: de $0 a $4.999 solo Webpay; desde $5.000, Webpay y MACH.
- Se busca el tramo (`min_amount`–`max_amount`) en que cae el monto; si no cae en ninguno, se usa el **medio por defecto** (cada rule set tiene exactamente uno).
- Los tramos no se pueden traslapar (sí pueden tocarse en el borde). Varios medios pueden compartir tramo.
- Se administra **en el portal** (Configuración → Rule Set para medios de pago del WEB Checkout), no por API: crear, editar, activar/desactivar, reordenar y eliminar (solo si nunca se usó en una orden real). Hasta 20 tramos por rule set. Solo usuarios root/admin.
- El portal puede proponer un rule set con IA a partir de los últimos 12 meses (ingreso neto, tasa de aprobación o menor comisión). Requiere ≥ 30 órdenes, máximo 5 propuestas por hora, y no se guarda solo.
- ID con formato `rs_<UUID>`.
- **No hay endpoints de API documentados para gestionar rule sets.**

---

## Crear un objeto Payment

> Fuente oficial: [Crear un objeto Payment](https://virtualpos.readme.io/reference/crear-un-objeto-payment)

### Endpoint

```http
POST /v3/payment/
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Crea una orden de pago (objeto **Payment**) en estado `pendiente`. Es el primer paso de cualquier cobro *spot* (Web Checkout, envío por Email/WhatsApp/SMS, autorización directa o Quick Checkout). Si pasa 30 días en `pendiente`, expira.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

No aplica.

### Query parameters

No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| amount | integer (int32) | Sí | Monto de la transacción, total a pagar por el cliente. |
| email | string | Sí | Correo electrónico del cliente. |
| social_id | string | Sí | Identificador social del cliente. Para Chile utilizar RUT |
| first_name | string | Sí | Nombre del cliente pagador. |
| last_name | string | Sí | Apellido del cliente pagador |
| phone | string | Sí | Teléfono, formato 569NNNNNNNN |
| description | string | Sí | Breve descripción del pago |
| merchant_internal_code | string | No | Identificador de su negocio que representa el pago, ejemplo: número de pedido, factura, etc. |
| merchant_internal_channel | string | No | Nombre del canal del pago utilizado por su negocio: Portal, App, etc. |
| return_url | string | No | URL de retorno al finalizar el pago, debe estar codificada en Base64 |
| callback_url | string | No | URL Webhook, debe estar codificada Base64 |
| rule_set_uuid | string | No | **Nuevo en la doc oficial (no estaba en el borrador).** ID del *Rule Set* que define qué medios de pago se muestran en el checkout según el monto. Formato `rs_<uuid>`. Ver [Webcheckout Ruleset](payments.md#webcheckout-ruleset). |

Ejemplo:

```json
{
  "amount": 9990,
  "email": "user@example.com",
  "social_id": "12345678-9",
  "first_name": "John",
  "last_name": "Doe",
  "phone": "56961934502",
  "description": "Donación mensual octubre",
  "merchant_internal_code": "OC-1234",
  "merchant_internal_channel": "portal_pagos",
  "return_url": "aHR0cHM6Ly93d3cubWlzaXRpby5jbC9yZXN1bHRhZG8=",
  "callback_url": "aHR0cHM6Ly9hcGkubWlzaXRpby5jbC93ZWJob29rcy92aXJ0dWFscG9z"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "57276136aad3ecad",
      "status": "pendiente",
      "created_at": "2023-01-30 23:48:48",
      "card_number": "",
      "authorized_at": "",
      "auth_code": "",
      "installment_amount": "",
      "installment_number": "",
      "payment_type_code": "",
      "amount": 9990,
      "merchant_internal_code": "OC_TEST_1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": []
    }
  },
  "url_redirect": "https://pay.virtualpos-sandbox.com/preview/57276136aad3ecad"
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `payment.order.uuid` | Identificador del pago. **Guárdalo**: lo necesitas para todas las operaciones siguientes y llega en el webhook. |
| `payment.order.status` | Siempre `pendiente` al crear. |
| `url_redirect` | URL del checkout de VirtualPOS a la que se puede redirigir al pagador. |
| `commerce` | Datos del comercio dueño de la API key. |

### Estados posibles

El Payment nace en `pendiente`. Ver la tabla completa de estados en [Objeto Payment](#objeto-payment).

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-001` | Error en el parámetro Authorization. |
| `E-002` | Error en el parámetro Signature. |
| `E-003` | Error en el parámetro amount. |
| `E-004` | Error en el parámetro email. |
| `E-005` | Error en el parámetro social_id. |
| `E-006` | Error en el parámetro first_name. |
| `E-007` | Error en el parámetro last_name. |
| `E-008` | Error en el parámetro phone. |
| `E-009` | Error en el parámetro description. |
| `E-010` | Error en el parámetro amount, debe ser numérico. |
| `E-011` | Error en el parámetro amount, debe ser número entero mayor o igual a 1000. |
| `E-012` | Error en el parámetro email, no cumple con formato. |
| `E-022` | Error en el parámetro return_url. |
| `E-023` | Error en el parámetro callback_url. |
| `E-025` | Error en el parámetro return_url, no es posible decodificar. |
| `E-038` | No es posible procesar el pago, contrato inactivo. |
| `E-039` | El monto informado es mayor que el limite permitido. |
| `E-101` | Error en el parámetro merchant_internal_code. |

### Consideraciones

- `return_url` y `callback_url` deben ir **codificadas en Base64** (no en texto plano).
- `amount` es entero. El error `E-011` indica que debe ser **≥ 1000** (CLP).
- `phone` va en formato `569NNNNNNNN` (sin `+`).
- `payment_type_code` **no** es un campo de entrada: es un atributo de la respuesta (medio de pago usado al autorizar). Tu colección anterior lo enviaba en el body.
- Usa `merchant_internal_code` como tu clave de idempotencia de negocio (ej. ID de la donación). VirtualPOS **no documenta idempotencia**: si reintentas un POST por timeout podrías crear dos Payments. Antes de reintentar, busca con `GET /v3/payments?merchant_internal_code=...`.

### Ejemplo práctico

Backend recibe una donación spot → crea el Payment → guarda `uuid` + `merchant_internal_code` en `vpos_payments` con estado `pendiente` → llama a *Obtener link Web Checkout* → redirige al donante a `url_redirect`.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/payment/
```

---

## Obtener link Web Checkout

> Fuente oficial: [Obtener link Web Checkout](https://virtualpos.readme.io/reference/obtener-link-webcheckout)

### Endpoint

```http
POST /v3/payment/{uuid}/webcheckout
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Genera la URL del Web Checkout para un Payment existente. Puede mostrar todos los medios contratados (`all`) o llevar directo a uno (`webpay`, `khipu`, `fintoc`, `mach`, `redpay`). También devuelve un QR (`qr_encode`) en Base64.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| return_url | string | Sí | URL de retorno al finalizar el pago, debe estar codificada en Base64 |
| callback_url | string | Sí | URL Webhook, debe estar codificada Base64 |
| payment_method | string | No | Medio de pago para el cual se requiere incializar el Web Checkout Valores: `webpay`, `khipu`, `fintoc`, `mach`, `redpay`, `all` |

Ejemplo:

```json
{
  "return_url": "aHR0cHM6Ly93d3cubWlzaXRpby5jbC9yZXN1bHRhZG8=",
  "callback_url": "aHR0cHM6Ly9hcGkubWlzaXRpby5jbC93ZWJob29rcy92aXJ0dWFscG9z",
  "payment_method": "all"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "57276136aad3ecad",
      "status": "pendiente",
      "created_at": "2023-01-30 23:48:48",
      "card_number": "",
      "authorized_at": "",
      "auth_code": "",
      "installment_amount": "",
      "installment_number": "",
      "payment_type_code": "",
      "amount": 9990,
      "merchant_internal_code": "OC_TEST_1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": []
    }
  },
  "url_redirect": "https://pay.virtualpos-sandbox.com/preview/083613a748190d26",
  "qr_encode": "aHR0cHM6Ly9wYXkudmlydHVhbHBvcy1zYW5kYm94LmNvbS9wcmV2aWV3LzA4MzYxM2E3NDgxOTBkMjY="
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `url_redirect` | URL a la que debes redirigir al pagador. |
| `qr_encode` | La misma URL codificada en Base64, útil para generar un QR. |
| `payment.order.status` | Sigue en `pendiente` hasta que el pagador termine. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-018` | Error en el parámetro uuid. |
| `E-020` | Error, no existe transacción asociada a UUID: $uuid. |
| `E-022` | Error en el parámetro return_url. |
| `E-023` | Error en el parámetro callback_url. |
| `E-024` | Error en el parámetro payment_method, el valor informado no existe en el listado de medios de pago. |
| `E-025` | Error en el parámetro return_url, no es posible decodificar. |
| `E-027` | Error en el parámetro payment_method, el valor informado no esta disponible como medio de pago para su comercio. |
| `E-028` | No existe la orden con uuid : $uuid . |
| `E-029` | Ocurrió un error al iniciar la transacción Webpay. |
| `E-030` | Ocurrió un error al iniciar la transacción Khipu. |
| `E-031` | Ocurrió un error al iniciar la transacción MACH. |
| `E-032` | Ocurrió un error al iniciar la transacción Chek. |
| `E-033` | Ocurrió un error al iniciar la transacción ONEPAY. |
| `E-034` | Ocurrió un error al iniciar la transacción REDPAY. |

### Consideraciones

- Aquí `return_url` y `callback_url` son **obligatorias** (en *Crear Payment* son opcionales).
- Solo se muestran los medios que el comercio tiene contratados; un medio no contratado da `E-027`.
- Al terminar, VirtualPOS redirige al pagador a `return_url` enviando `uuid` por **HTTP POST**. Nunca confíes en esa redirección: consulta siempre *Recuperar Payment*.

### Ejemplo práctico

Después de crear el Payment, llama a este endpoint con `payment_method: "all"` y responde a tu frontend con `url_redirect` (HTTP 302 o JSON para que el front redirija).

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/payment/{{payment_uuid}}/webcheckout
```

---

## Recuperar un objeto Payment

> Fuente oficial: [Recuperar un objeto Payment](https://virtualpos.readme.io/reference/recuperar-un-objeto-payment)

### Endpoint

```http
GET /v3/payment/{uuid}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Obtiene el estado y el detalle financiero de un Payment. Es **la fuente de verdad** del resultado: se llama después del webhook y después del retorno del navegador.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "083613a748190d26",
      "status": "pagado",
      "created_at": "2021-09-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "2021-09-08 11:21:31",
      "auth_code": "1234",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "merchant_internal_code": "OC-1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": [
        {
          "description": "1/1",
          "installment": 9900,
          "processing_flat_fee": 0,
          "processing_fee": 117,
          "payout_amount": 9783,
          "payout_date": "2021-09-21"
        }
      ]
    }
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `payment.order.status` | Estado actual (ver tabla de estados). |
| `payment.order.authorized_at / auth_code` | Fecha y código de autorización (vacíos si no está pagado). |
| `payment.order.payment_type_code` | Medio usado: `VD`, `VN`, `VC`, `SI`, `NC`, `S2`, `VP`, `TE`. |
| `payment.order.card_number` | Últimos 4 dígitos de la tarjeta. |
| `payment.order.installment_number / installment_amount` | Cuotas y monto por cuota. |
| `payment.order.deposits[]` | Plan de abonos: comisión (`processing_fee`), monto neto (`payout_amount`) y fecha de abono (`payout_date`) por cuota. |

### Estados posibles

`pendiente`, `pagado`, `rechazado`, `reintentando`, `expirado`, `cancelado` (ver [Objeto Payment](#objeto-payment)).

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-018` | Error en el parámetro uuid. |
| `E-019` | No es posible recuperar la orden, api-key incorrecta. |
| `E-020` | Error, no existe transacción asociada a UUID: $uuid. |
| `E-021` | No es posible recuperar la orden. |
| `E-028` | No existe la orden con uuid : $uuid . |

### Consideraciones

- Es obligatorio guardar por al menos 1 año: `uuid`, fecha de autorización, monto, código de autorización, cantidad de cuotas y monto de cada cuota (requisito de la doc del Webhook).
- Un pago puede pasar por `reintentando` antes de quedar `pagado` o `rechazado`: no lo trates como final.

### Ejemplo práctico

Tu handler del webhook recibe `uuid` → llama a este endpoint → hace *upsert* en `vpos_payments` → si el estado cambió a `pagado`, marca la donación como pagada.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/payment/{{payment_uuid}}
```

---

## Cancelar un objeto Payment

> Fuente oficial: [Cancelar un objeto Payment](https://virtualpos.readme.io/reference/cancelar-un-objeto-payment)

### Endpoint

```http
DELETE /v3/payment/{uuid}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Cancela un Payment que todavía está `pendiente`. Un Payment cancelado ya no se puede cobrar.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "03164889d86c9fe4",
      "status": "cancelado",
      "created_at": "2021-09-08 11:20:31",
      "card_number": "",
      "authorized_at": "",
      "auth_code": "",
      "installment_amount": "",
      "installment_number": "",
      "payment_type_code": "",
      "amount": 9990,
      "merchant_internal_code": "OC-1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": []
    }
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `payment.order.status` | Queda en `cancelado`. |

### Estados posibles

Solo aplica a `pendiente` → `cancelado`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-018` | Error en el parámetro uuid. |
| `E-020` | Error, no existe transacción asociada a UUID: $uuid. |
| `E-028` | No existe la orden con uuid : $uuid . |
| `E-042` | Pago con status incompatible para ser cancelado. |

### Consideraciones

- Si el Payment no está `pendiente`, responde `E-042` ("Pago con status incompatible para ser cancelado").
- No es una devolución: **no existe un endpoint de reembolso documentado** en la API de Payments. No confirmado en la documentación oficial de VirtualPOS.

### Ejemplo práctico

Un usuario abandona el carrito o cambia el monto: cancela el Payment anterior y crea uno nuevo.

Request en Postman (colección `VirtualPOS API v2`):

```http
DELETE {{base_url}}/v3/payment/{{payment_uuid}}
```

---

## Obtener el logs transaccional de un objeto Payment

> Fuente oficial: [Obtener el logs transaccional de un objeto Payment](https://virtualpos.readme.io/reference/obtener-el-logs-transaccional-de-un-objeto-payment)

### Endpoint

```http
GET /v3/payment/{uuid}/logs
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Devuelve la bitácora de eventos de un Payment (creación, solicitud de autorización, autorización, envío de comprobante, etc.).

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "logs": [
    {
      "created": "2025-01-07 00:00:14",
      "description": "Orden de pago creada desde Pago Automatico con tarjeta de credito PAT."
    },
    {
      "created": "2025-01-07 00:10:24",
      "description": "Solicitando autorizacion del PAT."
    },
    {
      "created": "2025-01-07 00:10:27",
      "description": "Transacción PAT autorizada."
    },
    {
      "created": "2025-01-07 00:10:59",
      "description": "Comprobante de pago cliente enviado a johndoe@virtualpos.cl"
    }
  ]
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-020",
    "message": "Error, no existe transacción asociada a UUID: ... .",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `logs[].created` | Fecha del evento. |
| `logs[].description` | Descripción en texto libre. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-020` | Error, no existe transacción asociada a UUID: $uuid. |

### Consideraciones

- Las descripciones son texto libre: úsalo para soporte/auditoría, **no** para lógica de negocio.
- El ejemplo muestra pagos generados por PAT (cargos de suscripción), útil para investigar cobros recurrentes.

### Ejemplo práctico

Pantalla de soporte interna: al abrir una donación, muestra la línea de tiempo del pago.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/payment/{{payment_uuid}}/logs
```

---

## Listar objetos Payment

> Fuente oficial: [Listar objetos Payment](https://virtualpos.readme.io/reference/listar-objetos-payment)

### Endpoint

```http
GET /v3/payments
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Lista los Payments del comercio con filtros por estado, código interno y rangos de fecha de creación/autorización. Soporta paginación.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

No aplica.

### Query parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| status | string | No | Estado del objeto payment Valores: `pendiente`, `pagado`, `suspendido`, `expirado`, `reintentando`, `rechazado`, `anulado`, `autorizando`, `cancelado` |
| merchant_internal_code | string | No | Identificador de su negocio que representa el pago, ejemplo: número de pedido, factura, etc. |
| authorization_from | string (date) | No | Límite inferior para la fecha de autorización del pago. |
| authorization_to | string (date) | No | Límite superior para la fecha de autorización del pago. |
| created_from | string (date) | No | Límite inferior para la fecha de creación del pago. |
| created_to | string (date) | No | Límite superior para la fecha de creación del pago. |
| page | integer | No | Página solicitada. Documentado en la página *Paginación*, no en la ficha del endpoint. |
| limit | integer | No | Registros por página. Mínimo 1, máximo 100 (según *Paginación*). |

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "pagination": {
    "limit": 1,
    "page": 1,
    "pages": 2,
    "total": 6
  },
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payments": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "083613a748190d26",
      "status": "pagado",
      "created_at": "2021-09-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "2021-09-08 11:21:31",
      "auth_code": "1234",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "merchant_internal_code": "OC-1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": [
        {
          "description": "1/1",
          "installment": 9900,
          "processing_flat_fee": 0,
          "processing_fee": 117,
          "payout_amount": 9783,
          "payout_date": "2021-09-21"
        }
      ]
    }
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `pagination` | `limit`, `page`, `pages`, `total`. |
| `payments` | Listado de pagos con `client` y `order`. ⚠️ En el ejemplo oficial aparece como **objeto** y no como array; trata ambos casos en tu parser. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-041` | Error, no existen transacciones asociadas al comercio. |
| `E-090` | Error en el parámetro page. |
| `E-091` | Error en el parámetro limit. |
| `E-092` | Error en el parámetro status. |

### Consideraciones

- **Observado en sandbox 2026-10-27** [CLAIM:VP-C08] (CONFIRMADO): `GET /v3/payments` devuelve los pagos como lista bajo la clave `payments`. Claves raíz observadas: `code`, `commerce`, `pagination`, `payments`, `status`. El sync del CRM leyó 5 registros.
- Los filtros de fecha son `format: date` en la OpenAPI (usa `YYYY-MM-DD`).
- El enum de `status` en este filtro incluye valores que no aparecen en la tabla del Objeto Payment: `suspendido`, `anulado`, `autorizando`.
- Base de la sincronización incremental: consulta por ventana de `created_from/created_to` y, aparte, por `authorization_from/authorization_to` para capturar pagos que se autorizaron después.

### Ejemplo práctico

Job nocturno: `GET /v3/payments?created_from=2026-10-11&created_to=2026-10-12&limit=100&page=1` hasta `page == pages`.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/payments
```

---

## Autorizar un objeto Payment

> Fuente oficial: [Autorizar un objeto Payment](https://virtualpos.readme.io/reference/autorizar-un-objeto-payment)

### Endpoint

```http
POST /v3/payment/{uuid}/authorize
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Autoriza un Payment desde tu servidor, sin pasar por el Web Checkout, usando una tarjeta (`CREDIT_CARD`) o un token (`TOKEN_CARD`).

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| payment_method_type | string | Sí | Tipo de medio de pago a utilizar para autorizar el objeto payment Valores: `CREDIT_CARD`, `TOKEN_CARD` |
| credit_card | object | No | Objeto que representa la tarjeta de crédito a utilizar para autorizar el Payment. |
| credit_card.card_number | string | Sí | Número de la tarjeta de crédito |
| credit_card.expiration_date | string | Sí | Fecha de expiración de la tarjeta de crédito, formato :AA/MM |
| credit_card.cvv | string | Sí | Código de seguridad de la tarjeta de crédito |
| token_card | string | No | Token a utilizar para autorizar el Payment. |
| installments_number | integer (int32) | No | Cantidad de cuotas en que se realizará el pago |

Ejemplo:

```json
{
  "payment_method_type": "CREDIT_CARD",
  "credit_card": {
    "card_number": "4051885600446623",
    "expiration_date": "28/12",
    "cvv": "123"
  },
  "installments_number": 1
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "083613a748190d26",
      "status": "pagado",
      "created_at": "2021-09-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "2021-09-08 11:21:31",
      "auth_code": "1234",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "merchant_internal_code": "OC-1234",
      "merchant_internal_channel": "portal_pagos",
      "response_code": 0,
      "deposits": [
        {
          "description": "1/1",
          "installment": 9900,
          "processing_flat_fee": 0,
          "processing_fee": 117,
          "payout_amount": 9783,
          "payout_date": "2021-09-21"
        }
      ]
    }
  }
}
```

**HTTP 201** (rechazado):

```json
{
  "status": "OK",
  "code": 201,
  "commerce": {
    "commerce_id": "76123456-7",
    "name": "Comercial Andes"
  },
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "order": {
      "uuid": "083613a748190d26",
      "status": "rechazado",
      "created_at": "2021-09-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "",
      "auth_code": "",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "merchant_internal_code": "OC-1234",
      "merchant_internal_channel": "portal_pagos",
      "deposits": []
    }
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `code` | `200` = aprobado (`status: pagado`); `201` = rechazado (`status: rechazado`). Ojo: ambos traen `status: "OK"` a nivel raíz. |
| `payment.order.response_code` | Código de respuesta de la autorización (aparece en el ejemplo 200). |
| `payment.order.auth_code` | Código de autorización. |

### Estados posibles

`pendiente` → `pagado` (HTTP 200) o `rechazado` (HTTP 201).

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-035` | Error en el parámetro payment_method_type. |
| `E-036` | Pago con status incompatible para ser autorizado. |
| `E-037` | Error en el parámetro payment_method_type. |
| `E-040` | No se puede procesar la transacción. |

Si la autorización es rechazada, el motivo viene en el [Objeto Rechazo](errors.md#objeto-rechazo) (`-1` … `-1018`).

### Consideraciones

- **Manejar datos de tarjeta en tu backend te pone dentro del alcance de PCI-DSS.** Para Techo, prefiere Web Checkout o Quick Checkout salvo que haya un motivo fuerte.
- `expiration_date` en formato `AA/MM` según la doc.
- `cardholder_name` (que tenía tu colección) **no está documentado**.
- No uses HTTP 200 como sinónimo de éxito: revisa `payment.order.status`.

### Ejemplo práctico

Cobro telefónico asistido por un operador con tarjeta tokenizada: `payment_method_type: TOKEN_CARD` + `token_card`.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/payment/{{payment_uuid}}/authorize
```

---

## Envio de una solicitud de pago por Email, Whatsapp o SMS

> Fuente oficial: [Envio de una solicitud de pago por Email, Whatsapp o SMS](https://virtualpos.readme.io/reference/envio-de-payment-por-email-whatsapp-sms)

### Endpoint

```http
POST /v3/payment/{uuid}/send
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Envía al pagador el link de pago de un Payment ya creado por EMAIL, WHATSAPP o SMS.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| channel | string | Sí | Canal de envío de la solicitud de pago (EMAIL, SMS o WHATSAPP) habilitado al comercio. Valores: `EMAIL`, `WHATSAPP`, `SMS` Default: `EMAIL` |
| receiver | string | Sí | Destinatario, este puede ser un correo electrónico válido o un numero de teléfono (12 caracteres incluido +56) |

Ejemplo:

```json
{
  "channel": "EMAIL",
  "receiver": "user@example.com"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "send_status": "enviado"
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `send_status` | `enviado` cuando el envío se realizó. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-068` | Error en el parámetro channel. |
| `E-069` | Channel no permitido. |
| `E-070` | Error en el parámetro receiver. |
| `E-071` | Error en el parámetro receiver, no cumple con formato para el channel email |
| `E-072` | Error en el parametro receiver, no cumple con formato para el channel whatsapp. |
| `E-073` | Error en el parametro receiver, no cumple con formato para el channel sms. |
| `E-074` | Channel no habilitado para el comercio. |
| `E-075` | Payment no enviado. |

### Consideraciones

- El canal debe estar habilitado para el comercio (`E-074`).
- Para WHATSAPP/SMS, `receiver` es un teléfono de 12 caracteres con `+56` (ej. `+56961934502`). Es distinto del formato `phone` de *Crear Payment* (`569...`).

### Ejemplo práctico

Campaña de recuperación: crea un Payment por donante con pago pendiente y envíale el link por WhatsApp.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/payment/{{payment_uuid}}/send
```

---

## Obtener los intentos de pago un objeto Payment

> Fuente oficial: [Obtener los intentos de pago un objeto Payment](https://virtualpos.readme.io/reference/obtener-los-intentos-de-pago-un-objeto-payment)

### Endpoint

```http
GET /v3/payment/{uuid}/attempts
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Devuelve el Payment con el historial de intentos de autorización con tarjeta (adquirente, código y motivo de cada intento).

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del objeto Payment (ej. `083613a748190d26`). Se obtiene en la respuesta de *Crear Payment* (`payment.order.uuid`). |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "commerce": {
    "commerce_id": "77488811-8",
    "name": "Virtualpos"
  },
  "payment": {
    "client": {
      "email": "JohnDoe@virtualpos.cl",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "11538111-1",
      "phone": "56981534402"
    },
    "order": {
      "uuid": "1700570969d8093d",
      "status": "pagado",
      "created_at": "2026-04-09 16:17:01",
      "card_number": "5843",
      "authorized_at": "2026-04-10 09:01:03",
      "auth_code": "236592",
      "installment_amount": "",
      "installment_number": "0",
      "payment_type_code": "VN",
      "amount": 100,
      "tip_amount": 0,
      "merchant_internal_code": "",
      "merchant_internal_channel": "",
      "deposits": [
        {
          "description": "1/1",
          "installment": 100,
          "tip_amount": 0,
          "processing_flat_fee": 0,
          "processing_fee": 3,
          "payout_amount": 97,
          "payout_date": "2026-04-15"
        }
      ],
      "bank": {},
      "payment_method": "PAT",
      "authorization_attempts_cards": [
        {
          "created_at": "2026-04-10 09:01:00",
          "response_code": "0",
          "acquirer": "transbank",
          "response_message": null,
          "response_description": "Operación exitosa",
          "authorization_type": "PAN"
        },
        {
          "created_at": "2026-04-09 16:18:15",
          "response_code": "-2122",
          "acquirer": "klap",
          "response_message": "VIOLACION DE SEGURIDAD",
          "response_description": "Violacion de seguridad",
          "authorization_type": "NETWORK_TOKEN"
        }
      ]
    }
  },
  "rejected_object": {
    "code": "0",
    "message": "Operación exitosa",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-rechazo"
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-020",
    "message": "Error, no existe transacción asociada a UUID: ... .",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `payment.order.authorization_attempts_cards[]` | Cada intento: `created_at`, `response_code`, `acquirer` (ej. `transbank`, `klap`), `response_message`, `response_description`, `authorization_type` (`PAN`, `NETWORK_TOKEN`). |
| `payment.order.payment_method` | Ej. `PAT` (pago automático con tarjeta). |
| `payment.order.tip_amount` | Propina (aparece en este ejemplo). |
| `rejected_object` | `code`, `message`, `doc_url` del último resultado (ver [Objeto Rechazo](errors.md#objeto-rechazo)). |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-020` | Error, no existe transacción asociada a UUID: $uuid. |

### Consideraciones

- Este ejemplo trae campos que **no** aparecen en el Objeto Payment general (`tip_amount`, `bank`, `payment_method`, `authorization_attempts_cards`). Haz tu parser tolerante a campos extra.
- Muy útil para diagnosticar por qué falla un cargo recurrente.

### Ejemplo práctico

Reporte de rechazos: para cada cargo rechazado, consulta los intentos y agrupa por `response_code`.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/payment/{{payment_uuid}}/attempts
```

---
