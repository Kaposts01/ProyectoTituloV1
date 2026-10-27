# Errores y rechazos

> Fuentes: https://virtualpos.readme.io/reference/objeto-error · https://virtualpos.readme.io/reference/objeto-rechazo · Verificado: 2026-10-12 (111 códigos de error, 27 de rechazo; coinciden con el borrador)

Hay **dos cosas distintas**:

| | Objeto **Error** | Objeto **Rechazo** |
| --- | --- | --- |
| Qué indica | La **request** está mal o no se pudo procesar | La request estaba bien, pero el **pago fue rechazado** (banco, antifraude, límites) |
| Dónde viene | `error` (respuestas `NOK`, HTTP 400) | `rejected_object` en el Payment (ej. *Intentos de pago*) |
| Formato del código | `E-###` | Número negativo `-#` / `-####` |
| ¿Reintentar igual? | No: corrige la request | A veces (ver tabla) |

## Objeto Error

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

| Elemento | Descripción |
| --- | --- |
| `error_code` | Código del error |
| `message` | Detalle del error (puede incluir valores, ej. el UUID) |
| `doc_url` | URL de documentación |

> **Observado en sandbox 2026-10-27** [CLAIM:VP-C27] (DRIFT): los errores de negocio llegan con **HTTP 200** y cuerpo `{"status":"NOK","code":400,"error":{"error_code":"E-0xx","message":"...","doc_url":"..."}}`, no con HTTP 400. Ejemplo: E-078 (fecha de cargo pasada). El cliente del CRM lo trata como error (`VirtualPOSAPIError`). Mismo patrón en [CLAIM:VP-C11] E-079 y [CLAIM:VP-C12] E-059 (ver [charges.md](charges.md)).

### Manejo recomendado en backend (**Recomendación**)

1. Detecta error por `status == "NOK"` **o** HTTP ≥ 400 (no solo por uno de los dos).
   - **Observado en sandbox 2026-10-27** [CLAIM:VP-C27]: en sandbox los errores de negocio llegan con HTTP 200 y `status: NOK`, así que la condición `status == "NOK"` es la que se dispara.
2. Decide por `error_code`, nunca por `message` (el texto puede cambiar).
3. Clasifica:
   - **No reintentar** (error de datos): validación de campos, `E-083` (cliente ya existe → buscar y continuar), `E-086` (internal_code ya usado → el cargo ya existe: trátalo como éxito idempotente).
   - **Observado en sandbox 2026-10-27** [CLAIM:VP-C07] (DRIFT): `internal_code` **no** es idempotente. Dos POST con el mismo código crearon dos cargos (HTTP 200, sin E-086). No asumir E-086 como garantía: el CRM debe deduplicar consultando los cargos de la suscripción antes de crear.
   - **Configuración/contrato** (alertar a una persona): `E-013`, `E-014`, `E-015`, `E-038`, `E-045`, `E-046`, `E-074`.
   - **"Vacío" que no es error** (registrar y seguir): `E-041`, `E-066`, `E-079`, `E-082`, `E-110`.
   - **Observado en sandbox 2026-10-27** [CLAIM:VP-C11] (DRIFT): E-079 llega como HTTP 200 con `status: NOK`. El cliente del CRM lo recibe como `VirtualPOSAPIError` (con `error_code` E-079) y los llamadores que esperan un "vacío" lo tratan como no-op: `cancel_future_charges` registra "sin cargos pendientes" y sigue (E-059 igual). Resuelto el 2026-10-27: la clasificación "registrar y seguir" se aplica en cada llamador, no en el cliente.
   - **Reintentable con backoff**: HTTP 5xx, timeouts, `E-029`…`E-034` (falló el inicio con el adquirente). Los 5xx y rate limits **no están documentados** por VirtualPOS. No confirmado en la documentación oficial de VirtualPOS.
4. Guarda `error_code` + `message` + request id propio en tus logs (sin el header `Signature`).

### Catálogo completo (agrupado por tema)

> Los códigos E-089, E-107, E-108, E-111 y E-115 no existen en la doc oficial.


#### Autenticación y firma

| Código | Mensaje |
| --- | --- |
| `E-001` | Error en el parámetro Authorization. |
| `E-002` | Error en el parámetro Signature. |
| `E-013` | Error, no existe el comercio asociado a la api key. |
| `E-014` | La verificación de la firma es incorrecta. |
| `E-015` | Firma es incorrecta. |
| `E-016` | Parámetros en la firma tienen errores. |
| `E-019` | No es posible recuperar la orden, api-key incorrecta. |
| `E-045` | No existe cuenta virtualPOS asociada a la api key. |

#### Validación de datos del pagador/cliente

| Código | Mensaje |
| --- | --- |
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
| `E-043` | Error en el parámetro phone_number. |
| `E-084` | Error en el parámetro social_id. No cumple con el formato. |
| `E-102` | El campo first_name solo puede contener letras y espacios. |
| `E-103` | El campo last_name solo puede contener letras y espacios. |

#### Payment / Web Checkout

| Código | Mensaje |
| --- | --- |
| `E-017` | Esta transacción no puede ser procesada, no es posible recuperar los datos del cliente. |
| `E-018` | Error en el parámetro uuid. |
| `E-020` | Error, no existe transacción asociada a UUID: $uuid. |
| `E-021` | No es posible recuperar la orden. |
| `E-022` | Error en el parámetro return_url. |
| `E-023` | Error en el parámetro callback_url. |
| `E-024` | Error en el parámetro payment_method, el valor informado no existe en el listado de medios de pago. |
| `E-025` | Error en el parámetro return_url, no es posible decodificar. |
| `E-026` | Error en el parámetro url_confirmacion, no es posible decodificar. |
| `E-027` | Error en el parámetro payment_method, el valor informado no esta disponible como medio de pago para su comercio. |
| `E-028` | No existe la orden con uuid : $uuid . |
| `E-029` | Ocurrió un error al iniciar la transacción Webpay. |
| `E-030` | Ocurrió un error al iniciar la transacción Khipu. |
| `E-031` | Ocurrió un error al iniciar la transacción MACH. |
| `E-032` | Ocurrió un error al iniciar la transacción Chek. |
| `E-033` | Ocurrió un error al iniciar la transacción ONEPAY. |
| `E-034` | Ocurrió un error al iniciar la transacción REDPAY. |
| `E-035` | Error en el parámetro payment_method_type. |
| `E-036` | Pago con status incompatible para ser autorizado. |
| `E-037` | Error en el parámetro payment_method_type. |
| `E-038` | No es posible procesar el pago, contrato inactivo. |
| `E-039` | El monto informado es mayor que el limite permitido. |
| `E-040` | No se puede procesar la transacción. |
| `E-041` | Error, no existen transacciones asociadas al comercio. |
| `E-042` | Pago con status incompatible para ser cancelado. |
| `E-068` | Error en el parámetro channel. |
| `E-069` | Channel no permitido. |
| `E-070` | Error en el parámetro receiver. |
| `E-071` | Error en el parámetro receiver, no cumple con formato para el channel email |
| `E-072` | Error en el parametro receiver, no cumple con formato para el channel whatsapp. |
| `E-073` | Error en el parametro receiver, no cumple con formato para el channel sms. |
| `E-074` | Channel no habilitado para el comercio. |
| `E-075` | Payment no enviado. |
| `E-077` | Error en el parámetro unapproved_transaction_url, no es posible decodificar. |
| `E-101` | Error en el parámetro merchant_internal_code. |

#### Plan

| Código | Mensaje |
| --- | --- |
| `E-044` | Error en el parámetro plan_id. |
| `E-047` | No existe el plan asociado al uuid : $uuid |
| `E-061` | Error en el parámetro name. |
| `E-062` | Error en el parámetro currency. |
| `E-063` | Error en el parámetro trial_days. |
| `E-064` | Error en el parámetro num_charges. |
| `E-065` | Error en el parámetro frequency_type. |
| `E-066` | No existen planes asociados al comercio. |
| `E-067` | No se encontró información para el id_plan: $plan_id |
| `E-112` | El plan id $plan_id no está activo. |
| `E-113` | El plan id $plan_id no es de tipo MONTO_VARIABLE. |
| `E-114` | El plan id $plan_id posee cargos de activación. |
| `E-116` | El plan id $plan_id posee divisa en UF. |

#### Suscription

| Código | Mensaje |
| --- | --- |
| `E-046` | Solicitud rechazada, cuenta virtualPOS sin contrato PAT activo. |
| `E-048` | El programa de pagos no puede ser vacío. |
| `E-049` | El programa de pagos contiene errores. |
| `E-050` | Error en el parámetro suscription_id. |
| `E-051` | No existen suscripciones asociados al uuid. |
| `E-052` | No se encontró datos de la suscripción. |
| `E-053` | No se encontró información de la suscripción, para generar un link de cambio de tarjeta. |
| `E-096` | Error en el parámetro service_id. |
| `E-097` | Error en el parámetro renewal |
| `E-098` | Error en el parámetro origin. |
| `E-099` | Error en el parámetro alias. |
| `E-100` | Error en el parámetro payment_description. |
| `E-104` | El campo service_id solo puede contener letras y espacios. |
| `E-105` | El campo payment_description solo puede contener letras y espacios. |
| `E-106` | El campo activation_amount solo permite números enteros sin puntos ni comas. |

#### Charge

> **Observado en sandbox 2026-10-27** [CLAIM:VP-C07] [CLAIM:VP-C12]: E-058 ("No existe el plan asociado al charge_id") se obtuvo al borrar un cargo inexistente (HTTP 200, NOK; hallazgo adicional sin ID de afirmación en el informe). E-086 no se observó: un segundo POST con el mismo `internal_code` creó otro cargo.

| Código | Mensaje |
| --- | --- |
| `E-054` | Error en el parámetro charge_date. |
| `E-055` | Error en el parámetro amount(Decimal). |
| `E-056` | Error en el parámetro charge_id. |
| `E-057` | No existe el cargo asociado al id informado : $cid |
| `E-058` | No existe el plan asociado al charge_id: $charge_id |
| `E-059` | No existe un cargo pendiente para el charge_id informado: $charge_id |
| `E-060` | No existe una suscripción ACTIVA para este charge_id: $charge_id |
| `E-076` | Error en el parámetro charge_date: no es una fecha válida. |
| `E-078` | Error en el parámetro charge_date: la fecha debe ser igual o mayor al día de hoy. |
| `E-079` | No se encontraron cargos pendientes asociados a la suscripcion. |
| `E-080` | Fallido obtención de objeto cargo. |
| `E-081` | El cargo no cumple con las condiciones para realizar el reintento de cobro. |
| `E-085` | Error en el parámetro internal_code. |
| `E-086` | El internal_code ya ha sido utilizado para autorizar un cargo |
| `E-087` | Ha superado el máximo de cargos mensuales permitidos. |
| `E-088` | Proceso Finalizado, UF no esta configurada para hoy. |

#### Client

| Código | Mensaje |
| --- | --- |
| `E-082` | Error no existen cliente asociado al comercio. |
| `E-083` | Este cliente ya existe. |

#### Listados / paginación / filtros

> **Observado en sandbox 2026-10-27** [CLAIM:VP-C14] (DRIFT): `limit=101` y `page=0` no dieron E-091 ni E-090: HTTP 200 (con `limit=101` devolvió 25 registros). Comportamiento no documentado; no depender de él.

| Código | Mensaje |
| --- | --- |
| `E-090` | Error en el parámetro page. |
| `E-091` | Error en el parámetro limit. |
| `E-092` | Error en el parámetro status. |
| `E-093` | Error en el parámetro charge_date_from. Debe ser YYYY-MM-DD |
| `E-094` | Error en el parámetro charge_date_to. Debe ser YYYY-MM-DD |
| `E-095` | Error en el parámetro charge_date_to. Debe ser mayor o igual a charge_date_to |

#### Abonos

| Código | Mensaje |
| --- | --- |
| `E-109` | formato de fecha invalido |
| `E-110` | No existen movimientos para abono |


## Objeto Rechazo

```json
{
  "rejected_object": {
    "error_code": "-####",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-rechazo"
  }
}
```

> **Discrepancia oficial:** la tabla del objeto dice que el campo se llama `code`, el ejemplo del objeto usa `error_code`, y el ejemplo real de *Intentos de pago* usa `code` (con `"0"` = operación exitosa). Lee ambos: `rejected_object.code ?? rejected_object.error_code`.

La columna "¿Reintentar?" es una **recomendación** nuestra, no de VirtualPOS.


| Código | Mensaje oficial | ¿Reintentar? |
| --- | --- | --- |
| `-1` | Transacción rechazada. Tarjeta inválida, error en números de tarjeta. | No (datos de tarjeta) |
| `-2` | Transacción rechazada. Error de conexión. | Sí, más tarde |
| `-3` | Transacción rechazada por banco emisor, la transacción excede el monto máximo permitido. | No con el mismo monto |
| `-4` | Transacción rechazada. Tarjeta inválida, error en fecha de expiración. | No (datos de tarjeta) |
| `-5` | Error de autenticación del cliente en su banco emisor. | Sí, si el pagador reintenta autenticación |
| `-6` | Rechazo general. | Quizás; preferir otro medio |
| `-7` | Tarjeta está bloqueada. Pagador debe intentar con otro medio de pago. | No; otro medio |
| `-8` | Tarjeta está expirada. Seleccionar otro medio de pago. | No; otro medio |
| `-9` | Tarjeta no soportada por adquirente. Pagador debe intentar con otro medio de pago. | No; otro medio |
| `-10` | Problema general en la transacción. | Sí, más tarde |
| `-11` | El pagador excedió el límite de rechazos establecidos por la marca. | No hoy |
| `-1001` | El Comercio no tiene habilitado el método de pago Quick Checkout. | Depende (antifraude/límites del comercio) |
| `-1002` | Esta transacción se encuentra en estado distinto a **pendiente** por lo cual no es posible realizar su pago. | Depende (antifraude/límites del comercio) |
| `-1003` | El Monto de la orden supera el máximo permitido para el comercio. | Depende (antifraude/límites del comercio) |
| `-1004` | Cliente intentó realizar el pago desde su navegador Web en modo incognito (privado), lo que podría poner en riesgo la seguridad del pago. | Depende (antifraude/límites del comercio) |
| `-1005` | Es muy probable que esta transacción esté siendo ejecutada por un bot en lugar de una persona, por motivos de seguridad se rechaza el pago. | Depende (antifraude/límites del comercio) |
| `-1006` | No fue posible determinar de forma certera el identificador del sistema del pagador(Confidence score). | Depende (antifraude/límites del comercio) |
| `-1007` | Se ha intentado realizar el pago desde un país no permitido. | Depende (antifraude/límites del comercio) |
| `-1009` | La cuenta VirtualPos del comercio ha superado el monto máximo de ventas diarias. | Depende (antifraude/límites del comercio) |
| `-1010` | La cuenta VirtualPos del comercio ha superado la cantidad máxima de transacciones autorizadas diariamente. | Depende (antifraude/límites del comercio) |
| `-1011` | El cliente o dispositivo utilizado se encuentra restringido para realizar pagos. | Depende (antifraude/límites del comercio) |
| `-1013` | El Comercio no tiene habilitado el pago con tarjetas extranjeras. | Depende (antifraude/límites del comercio) |
| `-1014` | La cuenta VirtualPos del comercio ha superado la cantidad máxima diaria de intentos fallidos de autorización. | Depende (antifraude/límites del comercio) |
| `-1015` | La cuenta VirtualPos del comercio ha superado la cantidad máxima de transacciones autorizadas diariamente por una misma tarjeta. | Depende (antifraude/límites del comercio) |
| `-1016` | Transacción rechazada, el cliente ha intentado pagar con una tarjeta no habilitada para Quick Checkout. | Depende (antifraude/límites del comercio) |
| `-1017` | No se pudo completar la validación de seguridad del pagador. Es posible que el pagador esté utilizando una herramienta para bloquear publicidad, VPN o modo incógnito. La cuenta comercio debe contactar al pagador. | Depende (antifraude/límites del comercio) |
| `-1018` | Transacción rechazada por botón volver. | Depende (antifraude/límites del comercio) |


## Errores de la API de Payout

Los códigos de Payout **reusan la numeración `E-###` con otro significado**. Están en [payouts.md](payouts.md#códigos-de-error-de-la-api-de-payout).
