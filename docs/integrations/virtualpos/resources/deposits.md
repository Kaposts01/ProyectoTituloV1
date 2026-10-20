# Deposits (Abonos)

> Fuente: https://virtualpos.readme.io/reference/recuperar-el-detalle-de-un-abono-o-deposito · Verificado: 2026-10-12

Los **abonos** son los depósitos que VirtualPOS hace a la cuenta bancaria del comercio. Sirven para **conciliar**: qué Payments (y qué cargos de suscripción) se depositaron cada día, con comisión y neto.

```text
ABONO = VENTAS − RETENCIONES − SERVICIOS
```

## Endpoints de este recurso

| Método | Ruta | Operación |
| --- | --- | --- |
| `GET` | `/v3/deposit/{date}` | [Recuperar el abono o deposito de un día](#recuperar-el-abono-o-deposito-de-un-día) |
| `GET` | `/v3/deposit/{date}/sales` | [Recuperar el listado de transacciones autorizadas incluidas en el abono del día](#recuperar-el-listado-de-transacciones-autorizadas-incluidas-en-el-abono-del-día) |
| `GET` | `/v3/deposit/{date}/withholdings` | [Recuperar el listado de las retenciones incluidas en el abono del día](#recuperar-el-listado-de-las-retenciones-incluidas-en-el-abono-del-día) |

## Objeto Abono (resumen del día)

| Nombre | Descripción | Tipo |
| --- | --- | --- |
| `deposit_date` | Fecha del depósito | Date |
| `total_deposit` | Monto total abonado | Int |
| `deposit_status` | Estado del abono: `VERIFIED` / `NOT VERIFIED` | String |
| `merchant.id` / `merchant.name` | RUT y nombre del comercio | String |
| `bank_account.*` | `bank_name`, `account_id`, `account_name`, `account_number`, `email` | String |
| `details.sales.*` | `quantity`, `total_amount` (antes de impuestos), `commission_and_taxes`, `net_total` | Int |
| `details.withholdings.*` | `quantity`, `total_amount`, `refund_commission_and_taxes`, `net_total` | Int |
| `details.services.*` | Cobro de servicios (equipos POS, reportes…): `total_amount`, `taxes`, `net_total` | Int |

---

## Recuperar el abono o deposito de un día

> Fuente oficial: [Recuperar el abono o deposito de un día](https://virtualpos.readme.io/reference/recuperar-el-detalle-de-un-abono-o-deposito)

### Endpoint

```http
GET /v3/deposit/{date}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Devuelve el resumen del abono (depósito) que VirtualPOS hace al comercio en una fecha: ventas, retenciones, cobros de servicios y total depositado. **ABONO = VENTAS − RETENCIONES − SERVICIOS.**

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
| date | string (YYYY-MM-DD) | Sí | Fecha del abono. El formato no está declarado en la ficha; los ejemplos usan `YYYY-MM-DD` y el error `E-109` indica "formato de fecha invalido". |

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
  "deposit_date": "2024-12-04",
  "total_deposit": 17495474,
  "deposit_status": "VERIFIED",
  "merchant": {
    "id": "123456798-0",
    "name": "ACME INC"
  },
  "bank_account": {
    "bank_name": "BANCO ESTADO",
    "account_id": "123456798-0",
    "account_name": "ACME INC",
    "account_number": "1234567890",
    "email": "contacto@acmeinc.cl"
  },
  "details": {
    "sales": {
      "quantity": 2817,
      "total_amount": 20867000,
      "commission_and_taxes": 680695,
      "net_total": 20186305
    },
    "withholdings": {
      "quantity": 0,
      "total_amount": 0,
      "refund_commission_and_taxes": 0,
      "net_total": 0
    },
    "services": {
      "total_amount": 2261202,
      "taxes": 429629,
      "net_total": 2690831
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
    "error_code": "E-109",
    "message": "formato de fecha invalido",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `total_deposit` | Monto total abonado ese día. |
| `deposit_status` | `VERIFIED` o `NOT VERIFIED`. |
| `details.sales` | `quantity`, `total_amount`, `commission_and_taxes`, `net_total`. |
| `details.withholdings` | Retenciones/anulaciones: `quantity`, `total_amount`, `refund_commission_and_taxes`, `net_total`. |
| `details.services` | Cobro de servicios (equipos POS, reportes, etc.): `total_amount`, `taxes`, `net_total`. |
| `bank_account` | Cuenta bancaria de destino. |

### Estados posibles

`deposit_status`: `VERIFIED` / `NOT VERIFIED`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-109` | formato de fecha invalido |
| `E-110` | No existen movimientos para abono |

### Consideraciones

- Si no hubo movimientos ese día responde `E-110` ("No existen movimientos para abono"): trátalo como "día sin abono", no como fallo.
- Contiene datos bancarios: no los expongas en dashboards abiertos.

### Ejemplo práctico

Conciliación diaria con finanzas: compara `total_deposit` con la cartola bancaria.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/deposit/{{deposit_date}}
```

---

## Recuperar el listado de transacciones autorizadas incluidas en el abono del día

> Fuente oficial: [Recuperar el listado de transacciones autorizadas incluidas en el abono del día](https://virtualpos.readme.io/reference/recuperar-el-listado-de-transacciones-autorizadas-incluidas-en-el-abono-del-día)

### Endpoint

```http
GET /v3/deposit/{date}/sales
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Detalle de cada venta (Payment autorizado) incluida en el abono de una fecha, con comisión y neto. Si la venta viene de una suscripción, trae el cargo asociado.

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
| date | string (YYYY-MM-DD) | Sí | Fecha del abono. El formato no está declarado en la ficha; los ejemplos usan `YYYY-MM-DD` y el error `E-109` indica "formato de fecha invalido". |

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
  "pagination": {
    "limit": 10,
    "page": 1,
    "pages": 1,
    "total": 2
  },
  "commerce": {
    "commerce_id": "76478131-7",
    "name": "Virtualpos"
  },
  "deposit": {
    "deposit_date": "2025-04-04",
    "sales": [
      {
        "uuid": "03167amfdjhs2dee0",
        "status": "pagado",
        "created_at": "2025-04-01 00:00:02",
        "authorized_at": "2025-04-01 00:10:09",
        "total_amount": 1990,
        "installment_amount": 1990,
        "installment": "1/1",
        "comission_and_taxes": 68,
        "net_amount": 1922,
        "merchant_internal_code": "",
        "merchant_internal_channel": "",
        "suscription_charge": {
          "cid": "cid_170653299283c074c1c86306.70585762",
          "charge_date": "2025-04-01",
          "internal_code": "",
          "suscription_id": "0b0c1ff181"
        }
      },
      {
        "uuid": "03167c07flojsda01a0d9a",
        "status": "pagado",
        "created_at": "2025-02-27 11:56:01",
        "authorized_at": "2025-02-27 12:14:36",
        "total_amount": 19990,
        "installment_amount": 6663,
        "installment": "02/3",
        "comission_and_taxes": 230,
        "net_amount": 6433,
        "merchant_internal_code": "cod Interno P3TL",
        "merchant_internal_channel": "",
        "suscription_charge": null
      }
    ]
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-110",
    "message": "No existen movimientos para abono",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `deposit.sales[].uuid` | UUID del Payment → une con `vpos_payments`. |
| `deposit.sales[].installment` | Cuota abonada, ej. `02/3`. |
| `deposit.sales[].comission_and_taxes / net_amount` | Comisión e IVA, y neto (ojo: `comission` con una sola *m*). |
| `deposit.sales[].suscription_charge` | `null` si es pago spot. Si es recurrente: `cid` (charge_id), `charge_date`, `internal_code`, `suscription_id`. **Es el puente Payment ↔ Charge ↔ Suscription.** |
| `pagination` | Objeto de paginación en la respuesta. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-109` | formato de fecha invalido |
| `E-110` | No existen movimientos para abono |

### Consideraciones

- La respuesta trae `pagination`, pero la ficha **no declara** parámetros `page`/`limit` de entrada. Prueba `?page=2&limit=100` en sandbox. No confirmado en la documentación oficial de VirtualPOS.
- Una venta en cuotas aparece en varios abonos (una vez por cuota).

### Ejemplo práctico

Llenar `vpos_deposit_lines` y, con `suscription_charge.cid`, saber qué cargo de qué suscripción generó cada peso abonado.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/deposit/{{deposit_date}}/sales
```

---

## Recuperar el listado de las retenciones incluidas en el abono del día

> Fuente oficial: [Recuperar el listado de las retenciones incluidas en el abono del día](https://virtualpos.readme.io/reference/recuperar-el-listado-de-las-retenciones-incluidas-en-el-abono-del-día)

### Endpoint

```http
GET /v3/deposit/{date}/withholdings
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Detalle de las retenciones (anulaciones/contracargos descontados) incluidas en el abono de una fecha.

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
| date | string (YYYY-MM-DD) | Sí | Fecha del abono. El formato no está declarado en la ficha; los ejemplos usan `YYYY-MM-DD` y el error `E-109` indica "formato de fecha invalido". |

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
  "pagination": {
    "limit": 10,
    "page": 1,
    "pages": 1,
    "total": 1
  },
  "commerce": {
    "commerce_id": "76478111-2",
    "name": "Virtualpos"
  },
  "deposit": {
    "deposit_date": "2025-01-01",
    "withholdings": [
      {
        "uuid": "03173899676ee469a04ac",
        "status": "anulado",
        "created_at": "2024-12-27 14:31:21",
        "authorized_at": "2024-12-27 14:32:39",
        "total_amount": 1221,
        "installment_amount": 1221,
        "installment": "1/1",
        "comission_and_taxes": 42,
        "net_amount": 1179,
        "merchant_internal_code": "",
        "merchant_internal_channel": "",
        "suscription_charge": null
      }
    ]
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-110",
    "message": "No existen movimientos para abono",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `deposit.withholdings[].uuid` | UUID del Payment retenido. |
| `deposit.withholdings[].status` | En el ejemplo: `anulado`. |
| `deposit.withholdings[].net_amount` | Monto neto descontado. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-109` | formato de fecha invalido |
| `E-110` | No existen movimientos para abono |

### Consideraciones

- Igual que *sales*: hay `pagination` en la respuesta pero no se documentan parámetros de entrada.
- Úsalo para revertir en tu base donaciones que figuraban como pagadas.

### Ejemplo práctico

Si un Payment aparece aquí, marca la donación como `anulada` y notifica al área de socios.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/deposit/{{deposit_date}}/withholdings
```

---
