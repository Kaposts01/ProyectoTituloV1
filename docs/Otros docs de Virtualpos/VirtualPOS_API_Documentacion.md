# Documentación API VirtualPOS

> Documentación completa de la API de VirtualPOS, recopilada desde [virtualpos.readme.io](https://virtualpos.readme.io/reference/getting-started-with-your-api) para servir como referencia de implementación de todos los endpoints y métodos disponibles.

## Índice

- **1. Primeros Pasos**
  - getting-started-with-your-api
  - endpoints
  - datos-de-prueba-sandbox
  - autenticacion-y-firma
  - objeto-error
  - objeto-rechazo
  - paginacion
  - integracion
- **2. Web Checkout (Payment)**
  - objeto-payment
  - introduccion-webcheckout
  - crear-objeto-payment
  - obtener-link-webcheckout
  - recuperar-objeto-payment
  - cancelar-objeto-payment
  - logs-transaccional-payment
  - listar-objetos-payment
  - autorizar-objeto-payment
  - envio-payment-email-whatsapp-sms
  - recuperar-detalle-abono-deposito
  - listado-transacciones-autorizadas-abono
  - listado-retenciones-abono
  - intentos-de-pago-payment
  - webhook
- **3. Suscripciones**
  - introduccion-suscripciones
- **3.1 Plan**
  - objeto-plan
  - crear-plan
  - recuperar-plan
  - listar-plans
- **3.2 Suscription**
  - objeto-suscription
  - crear-suscription
  - recuperar-suscription
  - cancelar-suscription
  - listar-suscriptions
  - generar-link-cambio-tarjeta
- **3.3 Charge**
  - objeto-charge
  - crear-charge
  - crear-charge-online
  - recuperar-charge
  - cancelar-charge
  - reintentar-charge
  - cancelar-cargos-futuros
  - listar-charges
- **3.4 Client**
  - objeto-client
  - crear-client
  - recuperar-objeto-client
  - listar-objetos-client
  - actualizar-objeto-client
- **4. Payout**
  - introduccion-payout
  - seguridad-mtls
  - autenticacion-firma-payout
  - webhook-payout
  - objeto-payout
  - crear-instruccion-payout
  - obtener-saldo-disponible
  - consultar-estado-payout-por-id
  - consultar-estado-payout-por-merchant-id
  - lista-bancos-codigos-sbif
  - payout-error-detail
- **5. Quick Checkout**
  - que-es-quick-checkout
  - integracion-quick-checkout

---

# 1. Primeros Pasos

### Iniciando con la API de Virtualpos

Bienvenidos a la API de Virtualpos 👋

Virtualpos te proporciona un potente y completo conjunto de operaciones para integrar aplicaciones de negocio a soluciones de pagos spot y pagos recurrentes.

La API de Virtualpos es una API REST. Sólo devuelve respuestas JSON con códigos HTTP para indicar éxito o fracaso de cada operación.

Cada solicitud debe incluir los encabezados:

- Content-Type establecido en application/json
- Authorization, que corresponde a la API KEY del comercio
- Signature, firma del mensaje

El cuerpo de la solicitud debe ser JSON válido.

> 📘 Importante
>
> Antes de iniciar la integración revisa cuidadosamente cuál es la alternativa que mejor se adapta a los requerimientos de tu negocio. Si necesitas ayuda, escríbenos a <soporte@virtualpos.cl>

### Endpoints

Se deben utilizar los siguientes endpoint dependiendo del ambiente en el cual se requieren realizar las transacciones:

**Payments**

| Ambiente   | Endpoint                             |
| :--------- | :----------------------------------- |
| Sandbox    | <https://api.virtualpos-sandbox.com> |
| Producción | <https://api.virtualpos.cl>          |

**Payouts**

| Ambiente   | Endpoint                                    |
| :--------- | :------------------------------------------ |
| Sandbox    | <https://payout-api.virtualpos-sandbox.com> |
| Producción | <https://payout-api.virtualpos.cl>          |

### Datos de prueba Sandbox

Durante el proceso de integración con la API de Virtualpos podrás utilizar las siguientes tarjetas y datos de autenticación para utilizarlos en el flujo de autorización de una transacción.

| Tipo de tarjeta    | Detalle                                                   | Resultado                        |
| ------------------ | --------------------------------------------------------- | -------------------------------- |
| CREDITO VISA       | 4051 8856 0044 6623 CVV 123 cualquier fecha de expiración | Genera transacciones aprobadas.  |
| CREDITO AMEX       | 3700 0000 0002 032 CVV 1234 cualquier fecha de expiración | Genera transacciones aprobadas.  |
| CREDITO MASTERCARD | 5186 0595 5959 0568 CVV 123 cualquier fecha de expiración | Genera transacciones rechazadas. |
| DÉBITO             | 4051 8842 3993 7763                                       | Genera transacciones aprobadas.  |
| DÉBITO             | 5186 0085 4123 3829                                       | Genera transacciones rechazadas. |
| PREPAGO VISA       | 4051 8860 0005 6590 CVV 123 cualquier fecha de expiración | Genera transacciones aprobadas.  |
| PREPAGO MASTERCARD | 5186 1741 1062 9480 CVV 123 cualquier fecha de expiración | Genera transacciones rechazadas. |

**Autenticación simulador de banco**\
Cuando aparece un formulario de autenticación con RUT y clave, se debe usar el RUT 11.111.111-1 y la clave 123.

### Autenticación y firma

La API de VirtualPOS opera a través de una API KEY y SECRET KEY, este conjunto de llaves son únicas para cada cuenta y ambiente (sandbox o producción), y se debe recuperar desde el el portal opción Perfil > Configuración de cuenta> Integración.

La API KEY debe ser enviada en cada requerimiento en el encabezado **Authorization**.

Cada requerimiento debe ser firmado, y la firma debe ser incluida también en el encabezado **Signature**

La firma se genera utilizando la SECRET KEY y JSON Web Token (JWT). JWT es un estándar abierto (RFC 7519) que define una forma compacta y autónoma de transmitir información de forma segura entre las partes como un objeto JSON. Esta información se puede verificar y confiar porque está firmada digitalmente. Más información de este estándar lo puedes encontrar en <https://jwt.io/>

Para todas las peticiones se debe firmar utilizando la API KEY como parámetro del payload, junto con los atributos requeridos.

A continuación se muestra un ejemplo de firma con JWT en PHP utilizando método POST:

```Text PHP
$payload = array();
$payload['api_key'] = <MY_API_KEY>;
$payload['uuid'] = $uuid;


$jwt_signature = JWT::encode($payload, <MY_SECRET_KEY>);

$client = new Client([
                        'headers' => [
                          'Content-Type' => 'application/json' ,
                          'Authorization'=> <MY_API_KEY>,
                          'Signature' => $jwt_signature
                        ]
                     ]);

$response = $client->post( $endpoint , [
    'json' => [
        				'uuid' => $uuid
              ]
        ]);

$response_decode = json_decode($response->getBody()->getContents());

```

A continuación se muestra un ejemplo de firma con JWT en PHP utilizando método GET:

```Text PHP
$payload = array();
$payload['api_key'] = <MY_API_KEY>;


$jwt_signature = JWT::encode($payload, <MY_SECRET_KEY>);

$client = new Client([
                        'headers' => [
                          'Content-Type' => 'application/json' ,
                          'Authorization'=> <MY_API_KEY>,
                          'Signature' => $jwt_signature
                        ]
                     ]);

$response = $client->GET( $endpoint);

$response_decode = json_decode($response->getBody()->getContents());

```

### Objeto Error

El objeto **Error** esta conformado por los siguientes elementos:

| Elemento   | Descripción                                                   |
| :--------- | :------------------------------------------------------------ |
| error_code | Es el código asignado a un error en particular.               |
| message    | Mensaje con detalle del error ocurrido.                       |
| doc_url    | Url de documentación para saber mas sobre el error detectado. |

```Text JSON
{
"error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

#### Lista de códigos de errores:

| Error code | Mensaje                                                                                                          |
| :--------- | :--------------------------------------------------------------------------------------------------------------- |
| E-001      | Error en el parámetro Authorization.                                                                             |
| E-002      | Error en el parámetro Signature.                                                                                 |
| E-003      | Error en el parámetro amount.                                                                                    |
| E-004      | Error en el parámetro email.                                                                                     |
| E-005      | Error en el parámetro social_id.                                                                                 |
| E-006      | Error en el parámetro first_name.                                                                                |
| E-007      | Error en el parámetro last_name.                                                                                 |
| E-008      | Error en el parámetro phone.                                                                                     |
| E-009      | Error en el parámetro description.                                                                               |
| E-010      | Error en el parámetro amount, debe ser numérico.                                                                 |
| E-011      | Error en el parámetro amount, debe ser número entero mayor o igual a 1000.                                       |
| E-012      | Error en el parámetro email, no cumple con formato.                                                              |
| E-013      | Error, no existe el comercio asociado a la api key.                                                              |
| E-014      | La verificación de la firma es incorrecta.                                                                       |
| E-015      | Firma es incorrecta.                                                                                             |
| E-016      | Parámetros en la firma tienen errores.                                                                           |
| E-017      | Esta transacción no puede ser procesada, no es posible recuperar los datos del cliente.                          |
| E-018      | Error en el parámetro uuid.                                                                                      |
| E-019      | No es posible recuperar la orden, api-key incorrecta.                                                            |
| E-020      | Error, no existe transacción asociada a UUID: $uuid.                                                             |
| E-021      | No es posible recuperar la orden.                                                                                |
| E-022      | Error en el parámetro return_url.                                                                                |
| E-023      | Error en el parámetro callback_url.                                                                              |
| E-024      | Error en el parámetro payment_method, el valor informado no existe en el listado de medios de pago.              |
| E-025      | Error en el parámetro return_url, no es posible decodificar.                                                     |
| E-026      | Error en el parámetro url_confirmacion, no es posible decodificar.                                               |
| E-027      | Error en el parámetro payment_method, el valor informado no esta disponible como medio de pago para su comercio. |
| E-028      | No existe la orden con uuid : $uuid .                                                                            |
| E-029      | Ocurrió un error al iniciar la transacción Webpay.                                                               |
| E-030      | Ocurrió un error al iniciar la transacción Khipu.                                                                |
| E-031      | Ocurrió un error al iniciar la transacción MACH.                                                                 |
| E-032      | Ocurrió un error al iniciar la transacción Chek.                                                                 |
| E-033      | Ocurrió un error al iniciar la transacción ONEPAY.                                                               |
| E-034      | Ocurrió un error al iniciar la transacción REDPAY.                                                               |
| E-035      | Error en el parámetro payment_method_type.                                                                       |
| E-036      | Pago con status incompatible para ser autorizado.                                                                |
| E-037      | Error en el parámetro payment_method_type.                                                                       |
| E-038      | No es posible procesar el pago, contrato inactivo.                                                               |
| E-039      | El monto informado es mayor que el limite permitido.                                                             |
| E-040      | No se puede procesar la transacción.                                                                             |
| E-041      | Error, no existen transacciones asociadas al comercio.                                                           |
| E-042      | Pago con status incompatible para ser cancelado.                                                                 |
| E-043      | Error en el parámetro phone_number.                                                                              |
| E-044      | Error en el parámetro plan_id.                                                                                   |
| E-045      | No existe cuenta virtualPOS asociada a la api key.                                                               |
| E-046      | Solicitud rechazada, cuenta virtualPOS sin contrato PAT activo.                                                  |
| E-047      | No existe el plan asociado al uuid : $uuid                                                                       |
| E-048      | El programa de pagos no puede ser vacío.                                                                         |
| E-049      | El programa de pagos contiene errores.                                                                           |
| E-050      | Error en el parámetro suscription_id.                                                                            |
| E-051      | No existen suscripciones asociados al uuid.                                                                      |
| E-052      | No se encontró datos de la suscripción.                                                                          |
| E-053      | No se encontró información de la suscripción, para generar un link de cambio de tarjeta.                         |
| E-054      | Error en el parámetro charge_date.                                                                               |
| E-055      | Error en el parámetro amount(Decimal).                                                                           |
| E-056      | Error en el parámetro charge_id.                                                                                 |
| E-057      | No existe el cargo asociado al id informado : $cid                                                               |
| E-058      | No existe el plan asociado al charge_id: $charge_id                                                              |
| E-059      | No existe un cargo pendiente para el charge_id informado: $charge_id                                             |
| E-060      | No existe una suscripción ACTIVA para este charge_id: $charge_id                                                 |
| E-061      | Error en el parámetro name.                                                                                      |
| E-062      | Error en el parámetro currency.                                                                                  |
| E-063      | Error en el parámetro trial_days.                                                                                |
| E-064      | Error en el parámetro num_charges.                                                                               |
| E-065      | Error en el parámetro frequency_type.                                                                            |
| E-066      | No existen planes asociados al comercio.                                                                         |
| E-067      | No se encontró información para el id_plan: $plan_id                                                             |
| E-068      | Error en el parámetro channel.                                                                                   |
| E-069      | Channel no permitido.                                                                                            |
| E-070      | Error en el parámetro receiver.                                                                                  |
| E-071      | Error en el parámetro receiver, no cumple con formato para el channel email                                      |
| E-072      | Error en el parametro receiver, no cumple con formato para el channel whatsapp.                                  |
| E-073      | Error en el parametro receiver, no cumple con formato para el channel sms.                                       |
| E-074      | Channel no habilitado para el comercio.                                                                          |
| E-075      | Payment no enviado.                                                                                              |
| E-076      | Error en el parámetro charge_date: no es una fecha válida.                                                       |
| E-077      | Error en el parámetro unapproved_transaction_url, no es posible decodificar.                                     |
| E-078      | Error en el parámetro charge_date: la fecha debe ser igual o mayor al día de hoy.                                |
| E-079      | No se encontraron cargos pendientes asociados a la suscripcion.                                                  |
| E-080      | Fallido obtención de objeto cargo.                                                                               |
| E-081      | El cargo no cumple con las condiciones para realizar el reintento de cobro.                                      |
| E-082      | Error no existen cliente asociado al comercio.                                                                   |
| E-083      | Este cliente ya existe.                                                                                          |
| E-084      | Error en el parámetro social_id. No cumple con el formato.                                                       |
| E-085      | Error en el parámetro internal_code.                                                                             |
| E-086      | El internal_code ya ha sido utilizado para autorizar un cargo                                                    |
| E-087      | Ha superado el máximo de cargos mensuales permitidos.                                                            |
| E-088      | Proceso Finalizado, UF no esta configurada para hoy.                                                             |
| E-090      | Error en el parámetro page.                                                                                      |
| E-091      | Error en el parámetro limit.                                                                                     |
| E-092      | Error en el parámetro status.                                                                                    |
| E-093      | Error en el parámetro charge_date_from. Debe ser YYYY-MM-DD                                                      |
| E-094      | Error en el parámetro charge_date_to. Debe ser YYYY-MM-DD                                                        |
| E-095      | Error en el parámetro charge_date_to. Debe ser mayor o igual a charge_date_to                                    |
| E-096      | Error en el parámetro service_id.                                                                                |
| E-097      | Error en el parámetro renewal                                                                                    |
| E-098      | Error en el parámetro origin.                                                                                    |
| E-099      | Error en el parámetro alias.                                                                                     |
| E-100      | Error en el parámetro payment_description.                                                                       |
| E-101      | Error en el parámetro merchant_internal_code.                                                                    |
| E-102      | El campo first_name solo puede contener letras y espacios.                                                       |
| E-103      | El campo last_name solo puede contener letras y espacios.                                                        |
| E-104      | El campo service_id solo puede contener letras y espacios.                                                       |
| E-105      | El campo payment_description solo puede contener letras y espacios.                                              |
| E-106      | El campo activation_amount solo permite números enteros sin puntos ni comas.                                     |
| E-109      | formato de fecha invalido                                                                                        |
| E-110      | No existen movimientos para abono                                                                                |
| E-112      | El plan id $plan_id no está activo.                                                                              |
| E-113      | El plan id $plan_id no es de tipo MONTO_VARIABLE.                                                                |
| E-114      | El plan id $plan_id posee cargos de activación.                                                                  |
| E-116      | El plan id $plan_id posee divisa en UF.                                                                          |

### Objeto Rechazo

El objeto **rejected** esta conformado por los siguientes elementos:

| Elemento | Descripción                                                    |
| :------- | :------------------------------------------------------------- |
| code     | Es el código asignado a un rechazo de una orden en particular. |
| message  | Mensaje con detalle del motivo del rechazo.                    |
| doc_url  | Url de documentación para saber más sobre el error detectado.  |

```json
{
  "rejected_object": {
    "error_code": "-####",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-rechazo"
  }
}
```

### Lista de códigos de rechazos:

<br />

| Rejected code | Mensaje                                                                                                                                                                                                              |
| :------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| -1            | Transacción rechazada. Tarjeta inválida, error en números de tarjeta.                                                                                                                                                |
| -2            | Transacción rechazada. Error de conexión.                                                                                                                                                                            |
| -3            | Transacción rechazada por banco emisor, la transacción excede el monto máximo permitido.                                                                                                                             |
| -4            | Transacción rechazada. Tarjeta inválida, error en fecha de expiración.                                                                                                                                               |
| -5            | Error de autenticación del cliente en su banco emisor.                                                                                                                                                               |
| -6            | Rechazo general.                                                                                                                                                                                                     |
| -7            | Tarjeta está bloqueada. Pagador debe intentar con otro medio de pago.                                                                                                                                                |
| -8            | Tarjeta está expirada. Seleccionar otro medio de pago.                                                                                                                                                               |
| -9            | Tarjeta no soportada por adquirente. Pagador debe intentar con otro medio de pago.                                                                                                                                   |
| -10           | Problema general en la transacción.                                                                                                                                                                                  |
| -11           | El pagador excedió el límite de rechazos establecidos por la marca.                                                                                                                                                  |
| -1001         | El Comercio no tiene habilitado el método de pago Quick Checkout.                                                                                                                                                    |
| -1002         | Esta transacción se encuentra en estado distinto a **pendiente** por lo cual no es posible realizar su pago.                                                                                                         |
| -1003         | El Monto de la orden supera el máximo permitido para el comercio.                                                                                                                                                    |
| -1004         | Cliente intentó realizar el pago desde su navegador Web en modo incognito (privado), lo que podría poner en riesgo la seguridad del pago.                                                                            |
| -1005         | Es muy probable que esta transacción esté siendo ejecutada por un bot en lugar de una persona, por motivos de seguridad se rechaza el pago.                                                                          |
| -1006         | No fue posible determinar de forma certera el identificador del sistema del pagador(Confidence score).                                                                                                               |
| -1007         | Se ha intentado realizar el pago desde un país no permitido.                                                                                                                                                         |
| -1009         | La cuenta VirtualPos del comercio ha superado el monto máximo de ventas diarias.                                                                                                                                     |
| -1010         | La cuenta VirtualPos del comercio ha superado la cantidad máxima de transacciones autorizadas diariamente.                                                                                                           |
| -1011         | El cliente o dispositivo utilizado se encuentra restringido para realizar pagos.                                                                                                                                     |
| -1013         | El Comercio no tiene habilitado el pago con tarjetas extranjeras.                                                                                                                                                    |
| -1014         | La cuenta VirtualPos del comercio ha superado la cantidad máxima diaria de intentos fallidos de autorización.                                                                                                        |
| -1015         | La cuenta VirtualPos del comercio ha superado la cantidad máxima de transacciones autorizadas diariamente por una misma tarjeta.                                                                                     |
| -1016         | Transacción rechazada, el cliente ha intentado pagar con una tarjeta no habilitada para Quick Checkout.                                                                                                              |
| -1017         | No se pudo completar la validación de seguridad del pagador. Es posible que el pagador esté utilizando una herramienta para bloquear publicidad, VPN o modo incógnito. La cuenta comercio debe contactar al pagador. |
| -1018         | Transacción rechazada por botón volver.                                                                                                                                                                              |

### Paginación

El uso de paginación es fundamental para gestionar grandes conjuntos de datos al utilizar la API de **Virtualpos** . Al realizar una solicitud a la URL <https://api.virtualpos-sandbox.com/v3/payments>, puedes incluir los parámetros de paginación para limitar la cantidad de resultados devueltos y desplazarte a través de las páginas de resultados.

Ajusta los valores de "**limit**" y "**page**" según tus necesidades para controlar la cantidad de datos que deseas recuperar y la posición desde la cual deseas comenzar. Esto garantiza una eficiente gestión y recuperación de datos al interactuar con la API de **Virtualpos** en tus aplicaciones.

Ejemplo:

```
https://api.virtualpos-sandbox.com/v3/payments?limit=2&page=1
```

En el ejemplo anterior, al agregar los parámetros "limit=2" y "page=1" a la URL, se solicitarán un máximo de dos registros y se omitirán el primer resultado, lo que permitirá obtener la siguiente página de resultados.

En la respuesta, el servicio retornara el siguiente objeto con la informacion de la paginación.

```Text json
"pagination": {
        "limit": 3,
        "page": 1,
        "pages": 2,
        "total": 6
}
```

- limit: Número de registros que como máximo retornará cada request al servicio, el valor mínimo es 1 y el máximo es 100.
- page: Página solicitada en el request
- pages: Número total de páginas.
- total: Número total de registros.

Esto lo puedes implementar en las APIs de listado de objetos:

- [listar-objetos-payment](https://virtualpos.readme.io/reference/listar-objetos-payment)
- [listar-plans](https://virtualpos.readme.io/reference/listar-plans)
- [listar-suscriptions](https://virtualpos.readme.io/reference/listar-suscriptions)
- [listar-charges](https://virtualpos.readme.io/reference/listar-charges)

### Integración

Para facilitar la integración de la API de **Virtualpos**, hemos creado una colección de Postman que puedes utilizar como guia. La colección incluye una serie de solicitudes predefinidas que te permitirán interactuar con nuestras APIs. Para comenzar, asegúrate de tener instalado Postman en tu entorno de desarrollo.

A continuación, te indicamos los pasos que debes seguir para importar la colección Postman de Virtualpos.

**Importar la colección Postman**

1. Abrir la aplicación Postman
2. Ir a la caja de búsqueda situada en la parte superior, ingresar "Virtualpos Sandbox".
3. Seleccionar "Virtualpos Sandbox" desde el listado de opciones disponibles.
4. Una vez importada la colección, verás una lista de solicitudes disponibles en el panel izquierdo de Postman.
5. A continuación debes realizar un "Fork" del proyecto Postman, esto generará una copia local en tu workspace y te permitirá modificarlo.
6. Para utilizar la API de Virtualpos , asegúrate de establecer el entorno adecuado en Postman. Esto incluye establecer la variable de entorno "**api_key**" y "**secret_key**" de tu comercio, esto lo puedes encontrar en el portal de **Virtualpos** de ambiente de Sandbox <https://comercios.virtualpos-sandbox.com>.
7. **Importante** : Una vez modificada las variables de entorno, asegurate de guardar los cambios realizados presionando el boton **save** ubicado en la esquina superior derecha.
8. Ahora puedes comenzar a utilizar las solicitudes predefinidas en la colección de Postman. Cada solicitud está configurada con los parámetros necesarios y las cabeceras requeridas para interactuar con cada API.
9. Para probar una solicitud, simplemente selecciona la solicitud deseada en el panel izquierdo y haz clic en el botón "Enviar". Postman enviará la solicitud a la URL correspondiente y mostrará la respuesta de la API.

![](https://files.readme.io/a0c79eb-image.png)

_Paso 3_

![](https://files.readme.io/d723059-WhatsApp_Image_2023-06-19_at_5.01.25_PM.jpeg)

_Paso 6_

Utiliza esta colección de Postman como una guía para comprender y explorar la funcionalidad de la API de **Virtualpos**. Puedes personalizar las solicitudes, agregar autenticación y realizar pruebas exhaustivas para asegurarte de que tu integración con nuestra API sea exitosa.

---

# 2. Web Checkout (Payment)

### Objeto Payment

El objeto **Payment** representa un intento de pago, y contiene los atributos necesarios para procesar la transacción financiera. El objeto Payment puede tener los siguientes estados dependiendo de la etapa en la que se encuentre:

| Status       | Descripción                                                                                                  |
| :----------- | :----------------------------------------------------------------------------------------------------------- |
| pendiente    | Estado inicial, en espera de autorización financiera.                                                        |
| pagado       | Estado final, indica que ya tiene asociada una transacción financiera autorizada.                            |
| rechazado    | Estado final, transacción rechazada financieramente o cancelada por pagador.                                 |
| reintentando | Estado intermedio que indica que se intentará nuevamente la autorización financiera.                         |
| expirado     | Ha superado el tiempo máximo de espera del pago. Default 30 días.                                            |
| cancelado    | Estado final, solo se aplica a transacciones pendientes, al encontrarse en este estado no puede ser cobrada. |

```Text JSON
{
   "payment":{
      "client":{
         "email":"user@example.com",
         "first_name":"John",
         "last_name":"Doe",
         "social_id":"12345678-9",
         "phone":"56961934502"
      },
      "order":{
         "uuid":"083613a748190d26",
         "status":"pagado",
         "created_at":"2021-09-08 11:20:31",
         "card_number":1234,
         "authorized_at":"2021-09-08 11:21:31",
         "auth_code":"1234",
         "installment_amount":0,
         "installment_number":0,
         "payment_type_code":"VN",
         "amount":9990,
         "merchant_internal_code":"OC-1234",
         "merchant_internal_channel":"portal_pagos",
         "deposits":[
            {
               "description":"1/1",
               "installment":9900,
               "processing_flat_fee":0,
               "processing_fee":117,
               "payout_amount":9783,
               "payout_date":"2021-09-21"
            }
         ]
      }
   }
}
```

#### Atributo Payment Type Code

Este atributo representa el medio de pago utilizado para la autorización de la transacción.

| Nombre | Valor                     | Descripción                         |
| :----- | :------------------------ | :---------------------------------- |
| VD     | Débito                    | Venta débito                        |
| VN     | Crédito                   | Venta crédito sin cuotas            |
| VC     | Crédito                   | Venta crédito cuotas bancarias      |
| SI     | Crédito                   | Crédito 3 cuotas sin intereses      |
| NC     | Crédito                   | Venta cuotas sin intereses          |
| S2     | Crédito                   | Crédito 2 cuotas sin intereses      |
| VP     | Prepago                   | Venta prepago                       |
| TE     | Transferencia Electrónica | Transferencia electrónica de fondos |

### Introducción a Web Checkout

**Web checkout** proporciona una página web que contiene todos los medios de pagos contratados por el comercio, para que estos sean presentados al pagador. Es posible también dirigir automáticamente a un medio de pago al pagador, sin la necesidad de una selección previa.

A continuación se muestra un ejemplo del checkout:

![](https://files.readme.io/89abc88-image.png)

---

##### Breve explicación del modelo de integración

El comercio deberá crear un objeto **Payment** y luego obtener la URL del Webcheckout:

1. **Crear objeto Payment**, esta operación creará un objeto Payment estado “pendiente” en Virtualpos con toda la información necesaria para gestionar su autorización a través de los medios de pago disponibles (WebpayPlus, Onepay, Khipu, MACH, Chek, FPay, etc.). Transcurridos 30 días seguidos en estado “pendiente” la orden de recaudación pasará a estado “expirada”, impidiendo su pago.
2. **Obtener link de Webcheckout**. Una vez creado el objeto Payment, es necesario obtener el link del Web chekout. Es posible obtener el link para desplegar todos los medios de pago disponible, o bien obtener el link de redireccionamiento para un medio de pago en particular, Webpay por ejemplo.
3. **Redireccionamiento**: El redireccionamiento permite al pagador visualizar los medios de pago en su navegador Web (Checkout). Se mostrarán únicamente los medios de pago contratados por el establecimiento. El usuario pagador debe ser redirigido a la URL del Web Checkout de Virtualpos.
4. **Recibir y validar resultado de transacción**. Para pagos dirigidos al Web Checkout de Virtualpos, una vez resuelta la autorización financiera del pago, se redireccionará al usuario pagador a la página de resultado que el comercio informó al crear el objeto Payment, Virtualpos enviará el parámetro “uuid” a través del verbo HTTP/POST. Al momento de recepcionar esta notificación de redirección, el comercio deberá ejecutar la operación Recuperar objeto Payment utilizando el parámetro "uuid", para obtener el estado y resultado de la transacción.

![](https://files.readme.io/09a15bb-image.png)

### Crear un objeto Payment

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/": {
      "post": {
        "summary": "Crear un objeto Payment",
        "description": "",
        "operationId": "crear-un-objeto-payment",
        "parameters": [
          {
            "name": "Content-Type",
            "in": "header",
            "schema": {
              "type": "string",
              "default": "application/json"
            }
          },
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": [
                  "amount",
                  "email",
                  "social_id",
                  "first_name",
                  "last_name",
                  "phone",
                  "description"
                ],
                "properties": {
                  "amount": {
                    "type": "integer",
                    "description": "Monto de la transacción, total a pagar por el cliente.",
                    "format": "int32"
                  },
                  "email": {
                    "type": "string",
                    "description": "Correo electrónico del cliente."
                  },
                  "social_id": {
                    "type": "string",
                    "description": "Identificador social del cliente. Para Chile utilizar RUT"
                  },
                  "first_name": {
                    "type": "string",
                    "description": "Nombre del cliente pagador."
                  },
                  "last_name": {
                    "type": "string",
                    "description": "Apellido del cliente pagador"
                  },
                  "phone": {
                    "type": "string",
                    "description": "Teléfono, formato 569NNNNNNNN"
                  },
                  "description": {
                    "type": "string",
                    "description": "Breve descripción del pago"
                  },
                  "merchant_internal_code": {
                    "type": "string",
                    "description": "Identificador de su negocio que representa el pago, ejemplo: número de pedido, factura, etc."
                  },
                  "merchant_internal_channel": {
                    "type": "string",
                    "description": "Nombre del canal del pago utilizado por su negocio: Portal, App, etc."
                  },
                  "return_url": {
                    "type": "string",
                    "description": "URL de retorno al finalizar el pago, debe estar codificada en Base64"
                  },
                  "callback_url": {
                    "type": "string",
                    "description": "URL Webhook, debe estar codificada Base64"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"OK\",\n    \"code\": 200,\n    \"commerce\": {\n        \"commerce_id\": \"76123456-7\",\n        \"name\": \"Comercial Andes\"\n    },\n    \"payment\": {\n        \"client\": {\n            \"email\": \"user@example.com\",\n            \"first_name\": \"John\",\n            \"last_name\": \"Doe\",\n            \"social_id\": \"12345678-9\",\n            \"phone\": \"56961934502\"\n        },\n        \"order\": {\n            \"uuid\": \"57276136aad3ecad\",\n            \"status\": \"pendiente\",\n            \"created_at\": \"2023-01-30 23:48:48\",\n            \"card_number\": \"\",\n            \"authorized_at\": \"\",\n            \"auth_code\": \"\",\n            \"installment_amount\": \"\",\n            \"installment_number\": \"\",\n            \"payment_type_code\": \"\",\n            \"amount\":9990,\n            \"merchant_internal_code\": \"OC_TEST_1234\",\n            \"merchant_internal_channel\": \"portal_pagos\",\n            \"deposits\": []\n        }\n    },\n    \"url_redirect\": \"https://pay.virtualpos-sandbox.com/preview/57276136aad3ecad\"\n  \n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "57276136aad3ecad"
                            },
                            "status": {
                              "type": "string",
                              "example": "pendiente"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2023-01-30 23:48:48"
                            },
                            "card_number": {
                              "type": "string",
                              "example": ""
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": ""
                            },
                            "auth_code": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_amount": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_number": {
                              "type": "string",
                              "example": ""
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": ""
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC_TEST_1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {}
                              }
                            }
                          }
                        }
                      }
                    },
                    "url_redirect": {
                      "type": "string",
                      "example": "https://pay.virtualpos-sandbox.com/preview/57276136aad3ecad"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-###\",\n        \"message\": \"detalle del error\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:63fe661c43c8170073366362"
}
```

### Obtener link Web Checkout

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}/webcheckout": {
      "post": {
        "summary": "Obtener link Web Checkout",
        "description": "",
        "operationId": "obtener-link-webcheckout",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["return_url", "callback_url"],
                "properties": {
                  "return_url": {
                    "type": "string",
                    "description": "URL de retorno al finalizar el pago, debe estar codificada en Base64"
                  },
                  "callback_url": {
                    "type": "string",
                    "description": "URL Webhook, debe estar codificada Base64"
                  },
                  "payment_method": {
                    "type": "string",
                    "description": "Medio de pago para el cual se requiere incializar el Web Checkout",
                    "enum": [
                      "webpay",
                      "khipu",
                      "fintoc",
                      "mach",
                      "redpay",
                      "all"
                    ]
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"commerce\": {\n    \"commerce_id\": \"76123456-7\",\n    \"name\": \"Comercial Andes\"\n  },\n  \"payment\": {\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\"\n    },\n    \"order\": {\n      \"uuid\": \"57276136aad3ecad\",\n      \"status\": \"pendiente\",\n      \"created_at\": \"2023-01-30 23:48:48\",\n      \"card_number\": \"\",\n      \"authorized_at\": \"\",\n      \"auth_code\": \"\",\n      \"installment_amount\": \"\",\n      \"installment_number\": \"\",\n      \"payment_type_code\": \"\",\n      \"amount\": 9990,\n      \"merchant_internal_code\": \"OC_TEST_1234\",\n      \"merchant_internal_channel\": \"portal_pagos\",\n      \"deposits\": []\n    }\n  },\n  \"url_redirect\": \"https://pay.virtualpos-sandbox.com/preview/083613a748190d26\",\n  \"qr_encode\": \"aHR0cHM6Ly9wYXkudmlydHVhbHBvcy1zYW5kYm94LmNvbS9wcmV2aWV3LzA4MzYxM2E3NDgxOTBkMjY=\"\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "57276136aad3ecad"
                            },
                            "status": {
                              "type": "string",
                              "example": "pendiente"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2023-01-30 23:48:48"
                            },
                            "card_number": {
                              "type": "string",
                              "example": ""
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": ""
                            },
                            "auth_code": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_amount": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_number": {
                              "type": "string",
                              "example": ""
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": ""
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC_TEST_1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {}
                              }
                            }
                          }
                        }
                      }
                    },
                    "url_redirect": {
                      "type": "string",
                      "example": "https://pay.virtualpos-sandbox.com/preview/083613a748190d26"
                    },
                    "qr_encode": {
                      "type": "string",
                      "example": "aHR0cHM6Ly9wYXkudmlydHVhbHBvcy1zYW5kYm94LmNvbS9wcmV2aWV3LzA4MzYxM2E3NDgxOTBkMjY="
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"NOK\",\n  \"code\": 400,\n  \"error\": {\n    \"error_code\": \"E-###\",\n    \"message\": \"detalle del error\",\n    \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:63fe6ae63f5f17001871baea"
}
```

### Recuperar un objeto Payment

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}": {
      "get": {
        "summary": "Recuperar un objeto Payment",
        "description": "",
        "operationId": "recuperar-un-objeto-payment",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"commerce\": {\n    \"commerce_id\": \"76123456-7\",\n    \"name\": \"Comercial Andes\"\n  },\n  \"payment\": {\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\"\n    },\n    \"order\": {\n      \"uuid\": \"083613a748190d26\",\n      \"status\": \"pagado\",\n      \"created_at\": \"2021-09-08 11:20:31\",\n      \"card_number\": 1234,\n      \"authorized_at\": \"2021-09-08 11:21:31\",\n      \"auth_code\": \"1234\",\n      \"installment_amount\": 0,\n      \"installment_number\": 0,\n      \"payment_type_code\": \"VN\",\n      \"amount\": 9990,\n      \"merchant_internal_code\": \"OC-1234\",\n      \"merchant_internal_channel\": \"portal_pagos\",\n      \"deposits\": [\n        {\n          \"description\": \"1/1\",\n          \"installment\": 9900,\n          \"processing_flat_fee\": 0,\n          \"processing_fee\": 117,\n          \"payout_amount\": 9783,\n          \"payout_date\": \"2021-09-21\"\n        }\n      ]\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "083613a748190d26"
                            },
                            "status": {
                              "type": "string",
                              "example": "pagado"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2021-09-08 11:20:31"
                            },
                            "card_number": {
                              "type": "integer",
                              "example": 1234,
                              "default": 0
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": "2021-09-08 11:21:31"
                            },
                            "auth_code": {
                              "type": "string",
                              "example": "1234"
                            },
                            "installment_amount": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "installment_number": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": "VN"
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC-1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {
                                  "description": {
                                    "type": "string",
                                    "example": "1/1"
                                  },
                                  "installment": {
                                    "type": "integer",
                                    "example": 9900,
                                    "default": 0
                                  },
                                  "processing_flat_fee": {
                                    "type": "integer",
                                    "example": 0,
                                    "default": 0
                                  },
                                  "processing_fee": {
                                    "type": "integer",
                                    "example": 117,
                                    "default": 0
                                  },
                                  "payout_amount": {
                                    "type": "integer",
                                    "example": 9783,
                                    "default": 0
                                  },
                                  "payout_date": {
                                    "type": "string",
                                    "example": "2021-09-21"
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"NOK\",\n  \"code\": 400,\n  \"error\": {\n    \"error_code\": \"E-###\",\n    \"message\": \"detalle del error\",\n    \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:63fe6693cad0e3005e71e318"
}
```

### Cancelar un objeto Payment

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}": {
      "delete": {
        "summary": "Cancelar un objeto Payment",
        "description": "",
        "operationId": "cancelar-un-objeto-payment",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"commerce\": {\n    \"commerce_id\": \"76123456-7\",\n    \"name\": \"Comercial Andes\"\n  },\n  \"payment\": {\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\"\n    },\n    \"order\": {\n      \"uuid\": \"03164889d86c9fe4\",\n      \"status\": \"cancelado\",\n      \"created_at\": \"2021-09-08 11:20:31\",\n      \"card_number\": \"\",\n      \"authorized_at\": \"\",\n      \"auth_code\": \"\",\n      \"installment_amount\": \"\",\n      \"installment_number\": \"\",\n      \"payment_type_code\": \"\",\n      \"amount\":9990,\n      \"merchant_internal_code\": \"OC-1234\",\n      \"merchant_internal_channel\": \"portal_pagos\",\n      \"deposits\": []\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "03164889d86c9fe4"
                            },
                            "status": {
                              "type": "string",
                              "example": "cancelado"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2021-09-08 11:20:31"
                            },
                            "card_number": {
                              "type": "string",
                              "example": ""
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": ""
                            },
                            "auth_code": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_amount": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_number": {
                              "type": "string",
                              "example": ""
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": ""
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC-1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {}
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"NOK\",\n  \"code\": 400,\n  \"error\": {\n    \"error_code\": \"E-###\",\n    \"message\": \"detalle del error\",\n    \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:63fe66f9522bbb006cfd131a"
}
```

### Obtener el logs transaccional de un objeto Payment

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}/logs": {
      "get": {
        "summary": "Obtener el logs transaccional de un objeto Payment",
        "description": "",
        "operationId": "obtener-el-logs-transaccional-de-un-objeto-payment",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"OK\",\n    \"code\": 200,\n    \"logs\": [\n        {\n            \"created\": \"2025-01-07 00:00:14\",\n            \"description\": \"Orden de pago creada desde Pago Automatico con tarjeta de credito PAT.\"\n        },\n        {\n            \"created\": \"2025-01-07 00:10:24\",\n            \"description\": \"Solicitando autorizacion del PAT.\"\n        },\n        {\n            \"created\": \"2025-01-07 00:10:27\",\n            \"description\": \"Transacción PAT autorizada.\"\n        },\n        {\n            \"created\": \"2025-01-07 00:10:59\",\n            \"description\": \"Comprobante de pago cliente enviado a johndoe@virtualpos.cl\"\n        }\n    ]\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "logs": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "created": {
                            "type": "string",
                            "example": "2025-01-07 00:00:14"
                          },
                          "description": {
                            "type": "string",
                            "example": "Orden de pago creada desde Pago Automatico con tarjeta de credito PAT."
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-020\",\n        \"message\": \"Error, no existe transacción asociada a UUID: ... .\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-020"
                        },
                        "message": {
                          "type": "string",
                          "example": "Error, no existe transacción asociada a UUID: ... ."
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
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
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:681830b3d52b260019c611e3"
}
```

### Listar objetos Payment

En esta API se puede implementar el uso de paginación para mas detalle haz click [aquí](https://virtualpos.readme.io/reference/paginacion-para-el-listado-de-objetos)

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payments": {
      "get": {
        "summary": "Listar objetos Payment",
        "description": "",
        "operationId": "listar-objetos-payment",
        "parameters": [
          {
            "name": "status",
            "in": "query",
            "description": "Estado del objeto payment",
            "schema": {
              "type": "string",
              "enum": [
                "pendiente",
                "pagado",
                "suspendido",
                "expirado",
                "reintentando",
                "rechazado",
                "anulado",
                "autorizando",
                "cancelado"
              ]
            }
          },
          {
            "name": "merchant_internal_code",
            "in": "query",
            "description": "Identificador de su negocio que representa el pago, ejemplo: número de pedido, factura, etc.",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "authorization_from",
            "in": "query",
            "description": "Límite inferior para la fecha de autorización del pago.",
            "schema": {
              "type": "string",
              "format": "date"
            }
          },
          {
            "name": "authorization_to",
            "in": "query",
            "description": "Límite superior para la fecha de autorización del pago.",
            "schema": {
              "type": "string",
              "format": "date"
            }
          },
          {
            "name": "created_from",
            "in": "query",
            "description": "Límite inferior para la fecha de creación del pago.",
            "schema": {
              "type": "string",
              "format": "date"
            }
          },
          {
            "name": "created_to",
            "in": "query",
            "description": "Límite superior para la fecha de creación del pago.",
            "schema": {
              "type": "string",
              "format": "date"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"pagination\": {\n     \"limit\": 1,\n     \"page\": 1,\n     \"pages\": 2,\n      \"total\": 6\n },\n  \"commerce\": {\n    \"commerce_id\": \"76123456-7\",\n    \"name\": \"Comercial Andes\"\n  },\n  \"payments\": {\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\"\n    },\n    \"order\": {\n      \"uuid\": \"083613a748190d26\",\n      \"status\": \"pagado\",\n      \"created_at\": \"2021-09-08 11:20:31\",\n      \"card_number\": 1234,\n      \"authorized_at\": \"2021-09-08 11:21:31\",\n      \"auth_code\": \"1234\",\n      \"installment_amount\": 0,\n      \"installment_number\": 0,\n      \"payment_type_code\": \"VN\",\n      \"amount\": 9990,\n      \"merchant_internal_code\": \"OC-1234\",\n      \"merchant_internal_channel\": \"portal_pagos\",\n      \"deposits\": [\n        {\n          \"description\": \"1/1\",\n          \"installment\": 9900,\n          \"processing_flat_fee\": 0,\n          \"processing_fee\": 117,\n          \"payout_amount\": 9783,\n          \"payout_date\": \"2021-09-21\"\n        }\n      ]\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "pagination": {
                      "type": "object",
                      "properties": {
                        "limit": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "page": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "pages": {
                          "type": "integer",
                          "example": 2,
                          "default": 0
                        },
                        "total": {
                          "type": "integer",
                          "example": 6,
                          "default": 0
                        }
                      }
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payments": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "083613a748190d26"
                            },
                            "status": {
                              "type": "string",
                              "example": "pagado"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2021-09-08 11:20:31"
                            },
                            "card_number": {
                              "type": "integer",
                              "example": 1234,
                              "default": 0
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": "2021-09-08 11:21:31"
                            },
                            "auth_code": {
                              "type": "string",
                              "example": "1234"
                            },
                            "installment_amount": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "installment_number": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": "VN"
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC-1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {
                                  "description": {
                                    "type": "string",
                                    "example": "1/1"
                                  },
                                  "installment": {
                                    "type": "integer",
                                    "example": 9900,
                                    "default": 0
                                  },
                                  "processing_flat_fee": {
                                    "type": "integer",
                                    "example": 0,
                                    "default": 0
                                  },
                                  "processing_fee": {
                                    "type": "integer",
                                    "example": 117,
                                    "default": 0
                                  },
                                  "payout_amount": {
                                    "type": "integer",
                                    "example": 9783,
                                    "default": 0
                                  },
                                  "payout_date": {
                                    "type": "string",
                                    "example": "2021-09-21"
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"NOK\",\n  \"code\": 400,\n  \"error\": {\n    \"error_code\": \"E-###\",\n    \"message\": \"detalle del error\",\n    \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:63fe67697b4697007abf37fe"
}
```

### Autorizar un objeto Payment

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}/authorize": {
      "post": {
        "summary": "Autorizar un objeto Payment",
        "description": "",
        "operationId": "autorizar-un-objeto-payment",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["payment_method_type"],
                "properties": {
                  "payment_method_type": {
                    "type": "string",
                    "description": "Tipo de medio de pago a utilizar para autorizar el objeto payment",
                    "enum": ["CREDIT_CARD", "TOKEN_CARD"]
                  },
                  "credit_card": {
                    "type": "object",
                    "description": "Objeto que representa la tarjeta de crédito a utilizar para autorizar el Payment.",
                    "required": ["card_number", "expiration_date", "cvv"],
                    "properties": {
                      "card_number": {
                        "type": "string",
                        "description": "Número de la tarjeta de crédito"
                      },
                      "expiration_date": {
                        "type": "string",
                        "description": "Fecha de expiración de la tarjeta de crédito, formato :AA/MM"
                      },
                      "cvv": {
                        "type": "string",
                        "description": "Código de seguridad de la tarjeta de crédito"
                      }
                    }
                  },
                  "token_card": {
                    "type": "string",
                    "description": "Token a utilizar para autorizar el Payment."
                  },
                  "installments_number": {
                    "type": "integer",
                    "description": "Cantidad de cuotas en que se realizará el pago",
                    "format": "int32"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"commerce\": {\n    \"commerce_id\": \"76123456-7\",\n    \"name\": \"Comercial Andes\"\n  },\n  \"payment\": {\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\"\n    },\n    \"order\": {\n      \"uuid\": \"083613a748190d26\",\n      \"status\": \"pagado\",\n      \"created_at\": \"2021-09-08 11:20:31\",\n      \"card_number\": 1234,\n      \"authorized_at\": \"2021-09-08 11:21:31\",\n      \"auth_code\": \"1234\",\n      \"installment_amount\": 0,\n      \"installment_number\": 0,\n      \"payment_type_code\": \"VN\",\n      \"amount\": 9990,\n      \"merchant_internal_code\": \"OC-1234\",\n      \"merchant_internal_channel\": \"portal_pagos\",\n      \"response_code\":0,\n      \"deposits\": [\n        {\n          \"description\": \"1/1\",\n          \"installment\": 9900,\n          \"processing_flat_fee\": 0,\n          \"processing_fee\": 117,\n          \"payout_amount\": 9783,\n          \"payout_date\": \"2021-09-21\"\n        }\n      ]\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "083613a748190d26"
                            },
                            "status": {
                              "type": "string",
                              "example": "pagado"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2021-09-08 11:20:31"
                            },
                            "card_number": {
                              "type": "integer",
                              "example": 1234,
                              "default": 0
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": "2021-09-08 11:21:31"
                            },
                            "auth_code": {
                              "type": "string",
                              "example": "1234"
                            },
                            "installment_amount": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "installment_number": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": "VN"
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC-1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "response_code": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {
                                  "description": {
                                    "type": "string",
                                    "example": "1/1"
                                  },
                                  "installment": {
                                    "type": "integer",
                                    "example": 9900,
                                    "default": 0
                                  },
                                  "processing_flat_fee": {
                                    "type": "integer",
                                    "example": 0,
                                    "default": 0
                                  },
                                  "processing_fee": {
                                    "type": "integer",
                                    "example": 117,
                                    "default": 0
                                  },
                                  "payout_amount": {
                                    "type": "integer",
                                    "example": 9783,
                                    "default": 0
                                  },
                                  "payout_date": {
                                    "type": "string",
                                    "example": "2021-09-21"
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "201": {
            "description": "201",
            "content": {
              "application/json": {
                "examples": {
                  "rejected": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 201,\n  \"commerce\": {\n    \"commerce_id\": \"76123456-7\",\n    \"name\": \"Comercial Andes\"\n  },\n  \"payment\": {\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\"\n    },\n    \"order\": {\n      \"uuid\": \"083613a748190d26\",\n      \"status\": \"rechazado\",\n      \"created_at\": \"2021-09-08 11:20:31\",\n      \"card_number\": 1234,\n      \"authorized_at\": \"\",\n      \"auth_code\": \"\",\n      \"installment_amount\": 0,\n      \"installment_number\": 0,\n      \"payment_type_code\": \"VN\",\n      \"amount\": 9990,\n      \"merchant_internal_code\": \"OC-1234\",\n      \"merchant_internal_channel\": \"portal_pagos\",\n      \"deposits\": []\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 201,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76123456-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Comercial Andes"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "083613a748190d26"
                            },
                            "status": {
                              "type": "string",
                              "example": "rechazado"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2021-09-08 11:20:31"
                            },
                            "card_number": {
                              "type": "integer",
                              "example": 1234,
                              "default": 0
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": ""
                            },
                            "auth_code": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_amount": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "installment_number": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": "VN"
                            },
                            "amount": {
                              "type": "integer",
                              "example": 9990,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": "OC-1234"
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": "portal_pagos"
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {}
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"NOK\",\n  \"code\": 400,\n  \"error\": {\n    \"error_code\": \"E-###\",\n    \"message\": \"detalle del error\",\n    \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n  }"
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:63ff42e6439f990040db2eac"
}
```

### Envio de una solicitud de pago por Email, Whatsapp o SMS

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}/send": {
      "post": {
        "summary": "Envio de una solicitud de pago por Email, Whatsapp o SMS",
        "description": "",
        "operationId": "envio-de-payment-por-email-whatsapp-sms",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["channel", "receiver"],
                "properties": {
                  "channel": {
                    "type": "string",
                    "description": "Canal de envío de la solicitud de pago (EMAIL, SMS o WHATSAPP) habilitado al comercio.",
                    "default": "EMAIL",
                    "enum": ["EMAIL", "WHATSAPP", "SMS"]
                  },
                  "receiver": {
                    "type": "string",
                    "description": "Destinatario, este puede ser un correo electrónico válido o un numero de teléfono (12 caracteres incluido +56)"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"send_status\": \"enviado\"\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "send_status": {
                      "type": "string",
                      "example": "enviado"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"NOK\",\n  \"code\": 400,\n  \"error\": {\n    \"error_code\": \"E-###\",\n    \"message\": \"detalle del error\",\n    \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6492098512cfda004b8a2a61"
}
```

### Recuperar el abono o deposito de un día

#### Descripción.

Este servicio permite obtener el detalle del deposito/abono efectuado por **Virtualpos** para una fecha determinada.

El calculo de abono se efectúa de la siguiente manera.

ABONO = VENTAS - RETENCIONES - SERVICIOS.

<br />

| Nombre                      | Descripcion                                                             | Tipo                              |
| :-------------------------- | :---------------------------------------------------------------------- | :-------------------------------- |
| deposit_date                | Fecha del depósito u abono                                              | Date                              |
| total_deposit               | Monto total abonado                                                     | Int                               |
| deposit_status              | Estado del abono                                                        | String: \[VERIFIED: NOT VERIFIED] |
| **_merchant_**              |                                                                         |                                   |
| id                          | Identificador del comercio (Rut)                                        | String                            |
| name                        | Nombre del comercio                                                     | String                            |
| **_bank_account_**          | Informacion de la cuenta bancaria donde se realizará el deposito/abono. |                                   |
| bank_name                   | Nombre del banco                                                        | String                            |
| account_id                  | Rut de la cuenta                                                        | String                            |
| account_name                | Nombre del comercio dueño de la cuenta                                  | String                            |
| account_number              | Número de la cuenta bancaria                                            | String                            |
| email                       | Email asociado a la cuenta bancaria                                     | String                            |
| **_sales_**                 | Ventas                                                                  |                                   |
| quantity                    | Número de ventas incluidas en el abono                                  | Int                               |
| total_amount                | Monto total de ventas antes de impuestos.                               | Int                               |
| commission_and_taxes        | Impuestos calculado sobre las ventas.                                   | Int                               |
| net_total                   | Monto total de abono.                                                   |                                   |
| **_withholdings_**          | Retenciones/Anulaciones                                                 |                                   |
| quantity                    | Número de retenciones consideradas para el calculo del abono            | Int                               |
| total_amount                | Monto total de retenciones antes de impuestos.                          | Int                               |
| refund_commission_and_taxes | Impuesto calculados sobre las retenciones                               | Int                               |
| net_total                   | Monto total de retención.                                               | Int                               |
| **_services_**              | Cobro de servicios (Equipos POS, Reportes, etc.).                       |                                   |
| total_amount                | Monto total por cobro de servicios.                                     | Int                               |
| taxes                       | Impuesto sobre el cobro de servicios                                    | Int                               |
| net_total                   | Monto a retener por concepto de cobro de servicios.                     | Int                               |

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/deposit/{date}": {
      "get": {
        "summary": "Recuperar el abono o deposito de un día",
        "description": "",
        "operationId": "recuperar-el-detalle-de-un-abono-o-deposito",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"deposit_date\": \"2024-12-04\",\n  \"total_deposit\": 17495474,\n  \"deposit_status\": \"VERIFIED\",\n  \"merchant\": {\n    \"id\": \"123456798-0\",\n    \"name\": \"ACME INC\"\n  },\n  \"bank_account\": {\n    \"bank_name\": \"BANCO ESTADO\",\n    \"account_id\": \"123456798-0\",\n    \"account_name\": \"ACME INC\",\n    \"account_number\": \"1234567890\",\n    \"email\": \"contacto@acmeinc.cl\"\n  },\n  \"details\": {\n    \"sales\": {\n      \"quantity\": 2817,\n      \"total_amount\": 20867000,\n      \"commission_and_taxes\": 680695,\n      \"net_total\": 20186305\n    },\n    \"withholdings\": {\n      \"quantity\": 0,\n      \"total_amount\": 0,\n      \"refund_commission_and_taxes\": 0,\n      \"net_total\": 0\n    },\n    \"services\": {\n      \"total_amount\": 2261202,\n      \"taxes\": 429629,\n      \"net_total\": 2690831\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "deposit_date": {
                      "type": "string",
                      "example": "2024-12-04"
                    },
                    "total_deposit": {
                      "type": "integer",
                      "example": 17495474,
                      "default": 0
                    },
                    "deposit_status": {
                      "type": "string",
                      "example": "VERIFIED"
                    },
                    "merchant": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "123456798-0"
                        },
                        "name": {
                          "type": "string",
                          "example": "ACME INC"
                        }
                      }
                    },
                    "bank_account": {
                      "type": "object",
                      "properties": {
                        "bank_name": {
                          "type": "string",
                          "example": "BANCO ESTADO"
                        },
                        "account_id": {
                          "type": "string",
                          "example": "123456798-0"
                        },
                        "account_name": {
                          "type": "string",
                          "example": "ACME INC"
                        },
                        "account_number": {
                          "type": "string",
                          "example": "1234567890"
                        },
                        "email": {
                          "type": "string",
                          "example": "contacto@acmeinc.cl"
                        }
                      }
                    },
                    "details": {
                      "type": "object",
                      "properties": {
                        "sales": {
                          "type": "object",
                          "properties": {
                            "quantity": {
                              "type": "integer",
                              "example": 2817,
                              "default": 0
                            },
                            "total_amount": {
                              "type": "integer",
                              "example": 20867000,
                              "default": 0
                            },
                            "commission_and_taxes": {
                              "type": "integer",
                              "example": 680695,
                              "default": 0
                            },
                            "net_total": {
                              "type": "integer",
                              "example": 20186305,
                              "default": 0
                            }
                          }
                        },
                        "withholdings": {
                          "type": "object",
                          "properties": {
                            "quantity": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "total_amount": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "refund_commission_and_taxes": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "net_total": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            }
                          }
                        },
                        "services": {
                          "type": "object",
                          "properties": {
                            "total_amount": {
                              "type": "integer",
                              "example": 2261202,
                              "default": 0
                            },
                            "taxes": {
                              "type": "integer",
                              "example": 429629,
                              "default": 0
                            },
                            "net_total": {
                              "type": "integer",
                              "example": 2690831,
                              "default": 0
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-109\",\n        \"message\": \"formato de fecha invalido\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-109"
                        },
                        "message": {
                          "type": "string",
                          "example": "formato de fecha invalido"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
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
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:678509e5d24632006d0b576f"
}
```

### Recuperar el listado de transacciones autorizadas incluidas en el abono del día

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/deposit/{date}/sales": {
      "get": {
        "summary": "Recuperar el listado de transacciones autorizadas incluidas en el abono del día",
        "description": "",
        "operationId": "recuperar-el-listado-de-transacciones-autorizadas-incluidas-en-el-abono-del-día",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"OK\",\n    \"code\": 200,\n    \"pagination\": {\n        \"limit\": 10,\n        \"page\": 1,\n        \"pages\": 1,\n        \"total\": 2\n    },\n    \"commerce\": {\n        \"commerce_id\": \"76478131-7\",\n        \"name\": \"Virtualpos\"\n    },\n    \"deposit\": {\n        \"deposit_date\": \"2025-04-04\",\n        \"sales\": [\n            {\n                \"uuid\": \"03167amfdjhs2dee0\",\n                \"status\": \"pagado\",\n                \"created_at\": \"2025-04-01 00:00:02\",\n                \"authorized_at\": \"2025-04-01 00:10:09\",\n                \"total_amount\": 1990,\n                \"installment_amount\": 1990,\n                \"installment\": \"1/1\",\n                \"comission_and_taxes\": 68,\n                \"net_amount\": 1922,\n                \"merchant_internal_code\": \"\",\n                \"merchant_internal_channel\": \"\",\n                \"suscription_charge\": {\n                    \"cid\": \"cid_170653299283c074c1c86306.70585762\",\n                    \"charge_date\": \"2025-04-01\",\n                    \"internal_code\": \"\",\n                    \"suscription_id\": \"0b0c1ff181\"\n                }\n            },\n            {\n                \"uuid\": \"03167c07flojsda01a0d9a\",\n                \"status\": \"pagado\",\n                \"created_at\": \"2025-02-27 11:56:01\",\n                \"authorized_at\": \"2025-02-27 12:14:36\",\n                \"total_amount\": 19990,\n                \"installment_amount\": 6663,\n                \"installment\": \"02/3\",\n                \"comission_and_taxes\": 230,\n                \"net_amount\": 6433,\n                \"merchant_internal_code\": \"cod Interno P3TL\",\n                \"merchant_internal_channel\": \"\",\n                \"suscription_charge\": null\n            }\n        ]\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "pagination": {
                      "type": "object",
                      "properties": {
                        "limit": {
                          "type": "integer",
                          "example": 10,
                          "default": 0
                        },
                        "page": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "pages": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "total": {
                          "type": "integer",
                          "example": 2,
                          "default": 0
                        }
                      }
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76478131-7"
                        },
                        "name": {
                          "type": "string",
                          "example": "Virtualpos"
                        }
                      }
                    },
                    "deposit": {
                      "type": "object",
                      "properties": {
                        "deposit_date": {
                          "type": "string",
                          "example": "2025-04-04"
                        },
                        "sales": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "uuid": {
                                "type": "string",
                                "example": "03167amfdjhs2dee0"
                              },
                              "status": {
                                "type": "string",
                                "example": "pagado"
                              },
                              "created_at": {
                                "type": "string",
                                "example": "2025-04-01 00:00:02"
                              },
                              "authorized_at": {
                                "type": "string",
                                "example": "2025-04-01 00:10:09"
                              },
                              "total_amount": {
                                "type": "integer",
                                "example": 1990,
                                "default": 0
                              },
                              "installment_amount": {
                                "type": "integer",
                                "example": 1990,
                                "default": 0
                              },
                              "installment": {
                                "type": "string",
                                "example": "1/1"
                              },
                              "comission_and_taxes": {
                                "type": "integer",
                                "example": 68,
                                "default": 0
                              },
                              "net_amount": {
                                "type": "integer",
                                "example": 1922,
                                "default": 0
                              },
                              "merchant_internal_code": {
                                "type": "string",
                                "example": ""
                              },
                              "merchant_internal_channel": {
                                "type": "string",
                                "example": ""
                              },
                              "suscription_charge": {
                                "type": "object",
                                "properties": {
                                  "cid": {
                                    "type": "string",
                                    "example": "cid_170653299283c074c1c86306.70585762"
                                  },
                                  "charge_date": {
                                    "type": "string",
                                    "example": "2025-04-01"
                                  },
                                  "internal_code": {
                                    "type": "string",
                                    "example": ""
                                  },
                                  "suscription_id": {
                                    "type": "string",
                                    "example": "0b0c1ff181"
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-110\",\n        \"message\": \"No existen movimientos para abono\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-110"
                        },
                        "message": {
                          "type": "string",
                          "example": "No existen movimientos para abono"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
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
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:67fd87d9285ec500530d76e0"
}
```

### Recuperar el listado de las retenciones incluidas en el abono del día

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/deposit/{date}/withholdings": {
      "get": {
        "summary": "Recuperar el listado de las retenciones incluidas en el abono del día",
        "description": "",
        "operationId": "recuperar-el-listado-de-las-retenciones-incluidas-en-el-abono-del-día",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"OK\",\n    \"code\": 200,\n    \"pagination\": {\n        \"limit\": 10,\n        \"page\": 1,\n        \"pages\": 1,\n        \"total\": 1\n    },\n    \"commerce\": {\n        \"commerce_id\": \"76478111-2\",\n        \"name\": \"Virtualpos\"\n    },\n    \"deposit\": {\n        \"deposit_date\": \"2025-01-01\",\n        \"withholdings\": [\n            {\n                \"uuid\": \"03173899676ee469a04ac\",\n                \"status\": \"anulado\",\n                \"created_at\": \"2024-12-27 14:31:21\",\n                \"authorized_at\": \"2024-12-27 14:32:39\",\n                \"total_amount\": 1221,\n                \"installment_amount\": 1221,\n                \"installment\": \"1/1\",\n                \"comission_and_taxes\": 42,\n                \"net_amount\": 1179,\n                \"merchant_internal_code\": \"\",\n                \"merchant_internal_channel\": \"\",\n                \"suscription_charge\": null\n            }\n        ]\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "pagination": {
                      "type": "object",
                      "properties": {
                        "limit": {
                          "type": "integer",
                          "example": 10,
                          "default": 0
                        },
                        "page": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "pages": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "total": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        }
                      }
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "76478111-2"
                        },
                        "name": {
                          "type": "string",
                          "example": "Virtualpos"
                        }
                      }
                    },
                    "deposit": {
                      "type": "object",
                      "properties": {
                        "deposit_date": {
                          "type": "string",
                          "example": "2025-01-01"
                        },
                        "withholdings": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "uuid": {
                                "type": "string",
                                "example": "03173899676ee469a04ac"
                              },
                              "status": {
                                "type": "string",
                                "example": "anulado"
                              },
                              "created_at": {
                                "type": "string",
                                "example": "2024-12-27 14:31:21"
                              },
                              "authorized_at": {
                                "type": "string",
                                "example": "2024-12-27 14:32:39"
                              },
                              "total_amount": {
                                "type": "integer",
                                "example": 1221,
                                "default": 0
                              },
                              "installment_amount": {
                                "type": "integer",
                                "example": 1221,
                                "default": 0
                              },
                              "installment": {
                                "type": "string",
                                "example": "1/1"
                              },
                              "comission_and_taxes": {
                                "type": "integer",
                                "example": 42,
                                "default": 0
                              },
                              "net_amount": {
                                "type": "integer",
                                "example": 1179,
                                "default": 0
                              },
                              "merchant_internal_code": {
                                "type": "string",
                                "example": ""
                              },
                              "merchant_internal_channel": {
                                "type": "string",
                                "example": ""
                              },
                              "suscription_charge": {}
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-110\",\n        \"message\": \"No existen movimientos para abono\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-110"
                        },
                        "message": {
                          "type": "string",
                          "example": "No existen movimientos para abono"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
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
                          "uuid": "03167677464ee469a04ac",
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
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:67fd89acda1003005dfe314d"
}
```

### Obtener los intentos de pago un objeto Payment

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/payment/{uuid}/attempts": {
      "get": {
        "summary": "Obtener los intentos de pago un objeto Payment",
        "description": "",
        "operationId": "obtener-los-intentos-de-pago-un-objeto-payment",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"OK\",\n    \"code\": 200,\n    \"commerce\": {\n        \"commerce_id\": \"77488811-8\",\n        \"name\": \"Virtualpos\"\n    },\n    \"payment\": {\n        \"client\": {\n            \"email\": \"JohnDoe@virtualpos.cl\",\n            \"first_name\": \"John\",\n            \"last_name\": \"Doe\",\n            \"social_id\": \"11538111-1\",\n            \"phone\": \"56981534402\"\n        },\n        \"order\": {\n            \"uuid\": \"1700570969d8093d\",\n            \"status\": \"pagado\",\n            \"created_at\": \"2026-04-09 16:17:01\",\n            \"card_number\": \"5843\",\n            \"authorized_at\": \"2026-04-10 09:01:03\",\n            \"auth_code\": \"236592\",\n            \"installment_amount\": \"\",\n            \"installment_number\": \"0\",\n            \"payment_type_code\": \"VN\",\n            \"amount\": 100,\n            \"tip_amount\": 0,\n            \"merchant_internal_code\": \"\",\n            \"merchant_internal_channel\": \"\",\n            \"deposits\": [\n                {\n                    \"description\": \"1/1\",\n                    \"installment\": 100,\n                    \"tip_amount\": 0,\n                    \"processing_flat_fee\": 0,\n                    \"processing_fee\": 3,\n                    \"payout_amount\": 97,\n                    \"payout_date\": \"2026-04-15\"\n                }\n            ],\n            \"bank\": {},\n            \"payment_method\": \"PAT\",\n            \"authorization_attempts_cards\": [\n                {\n                    \"created_at\": \"2026-04-10 09:01:00\",\n                    \"response_code\": \"0\",\n                    \"acquirer\": \"transbank\",\n                    \"response_message\": null,\n                    \"response_description\": \"Operación exitosa\",\n                    \"authorization_type\": \"PAN\"\n                },\n                {\n                    \"created_at\": \"2026-04-09 16:18:15\",\n                    \"response_code\": \"-2122\",\n                    \"acquirer\": \"klap\",\n                    \"response_message\": \"VIOLACION DE SEGURIDAD\",\n                    \"response_description\": \"Violacion de seguridad\",\n                    \"authorization_type\": \"NETWORK_TOKEN\"\n                }\n            ]\n        }\n    },\n    \"rejected_object\": {\n        \"code\": \"0\",\n        \"message\": \"Operación exitosa\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-rechazo\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "commerce": {
                      "type": "object",
                      "properties": {
                        "commerce_id": {
                          "type": "string",
                          "example": "77488811-8"
                        },
                        "name": {
                          "type": "string",
                          "example": "Virtualpos"
                        }
                      }
                    },
                    "payment": {
                      "type": "object",
                      "properties": {
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "JohnDoe@virtualpos.cl"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "11538111-1"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56981534402"
                            }
                          }
                        },
                        "order": {
                          "type": "object",
                          "properties": {
                            "uuid": {
                              "type": "string",
                              "example": "1700570969d8093d"
                            },
                            "status": {
                              "type": "string",
                              "example": "pagado"
                            },
                            "created_at": {
                              "type": "string",
                              "example": "2026-04-09 16:17:01"
                            },
                            "card_number": {
                              "type": "string",
                              "example": "5843"
                            },
                            "authorized_at": {
                              "type": "string",
                              "example": "2026-04-10 09:01:03"
                            },
                            "auth_code": {
                              "type": "string",
                              "example": "236592"
                            },
                            "installment_amount": {
                              "type": "string",
                              "example": ""
                            },
                            "installment_number": {
                              "type": "string",
                              "example": "0"
                            },
                            "payment_type_code": {
                              "type": "string",
                              "example": "VN"
                            },
                            "amount": {
                              "type": "integer",
                              "example": 100,
                              "default": 0
                            },
                            "tip_amount": {
                              "type": "integer",
                              "example": 0,
                              "default": 0
                            },
                            "merchant_internal_code": {
                              "type": "string",
                              "example": ""
                            },
                            "merchant_internal_channel": {
                              "type": "string",
                              "example": ""
                            },
                            "deposits": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {
                                  "description": {
                                    "type": "string",
                                    "example": "1/1"
                                  },
                                  "installment": {
                                    "type": "integer",
                                    "example": 100,
                                    "default": 0
                                  },
                                  "tip_amount": {
                                    "type": "integer",
                                    "example": 0,
                                    "default": 0
                                  },
                                  "processing_flat_fee": {
                                    "type": "integer",
                                    "example": 0,
                                    "default": 0
                                  },
                                  "processing_fee": {
                                    "type": "integer",
                                    "example": 3,
                                    "default": 0
                                  },
                                  "payout_amount": {
                                    "type": "integer",
                                    "example": 97,
                                    "default": 0
                                  },
                                  "payout_date": {
                                    "type": "string",
                                    "example": "2026-04-15"
                                  }
                                }
                              }
                            },
                            "bank": {
                              "type": "object",
                              "properties": {}
                            },
                            "payment_method": {
                              "type": "string",
                              "example": "PAT"
                            },
                            "authorization_attempts_cards": {
                              "type": "array",
                              "items": {
                                "type": "object",
                                "properties": {
                                  "created_at": {
                                    "type": "string",
                                    "example": "2026-04-10 09:01:00"
                                  },
                                  "response_code": {
                                    "type": "string",
                                    "example": "0"
                                  },
                                  "acquirer": {
                                    "type": "string",
                                    "example": "transbank"
                                  },
                                  "response_message": {},
                                  "response_description": {
                                    "type": "string",
                                    "example": "Operación exitosa"
                                  },
                                  "authorization_type": {
                                    "type": "string",
                                    "example": "PAN"
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    },
                    "rejected_object": {
                      "type": "object",
                      "properties": {
                        "code": {
                          "type": "string",
                          "example": "0"
                        },
                        "message": {
                          "type": "string",
                          "example": "Operación exitosa"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-rechazo"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-020\",\n        \"message\": \"Error, no existe transacción asociada a UUID: ... .\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-020"
                        },
                        "message": {
                          "type": "string",
                          "example": "Error, no existe transacción asociada a UUID: ... ."
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
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
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6a7c7aab0d42d212469477a1"
}
```

### Webhook

Con el objetivo de garantizar que el comercio reciba la respuesta por parte de Virtualpos, es posible incorporar durante la creación del objeto Payment, la url de un Webhook (parámetro callback_url) que deberá implementar el comercio para recibir una notificación asíncrona. Si el cliente pagador pierde conexión o cierra su navegador web, el resultado de la transacción podrá ser recuperado a través de la notificación enviada al webhook.

Esta notificación siempre se enviará independientemente de si el flujo de páginas en el navegador del cliente termina de forma exitosa o no. La notificación se realiza a través de una llamada HTTP/POST al **callback_url** con el parámetro **uuid** del objeto Payment, posterior a eso el comercio deberá consultar el estado de la transacción invocando el método "Recuperar objeto Payment", y si es necesario, actualizar el estado del pago en sus sistemas.

Es requisito almacenar por al menos 1 año la información del pago autorizado entregada en la consulta del estado (uuid de la transacción, fecha de autorización, monto, código de autorización, cantidad de cuotas, monto de cada cuota)

Dependiendo del resultado de la transacción, el comercio debe desplegar un mensaje al usuario pagador de éxito o fracaso. En caso de fracaso se debe permitir reintentar el pago a través del mismo “uuid” de transacción.

---

# 3. Suscripciones

### Introducción a Suscription

Bienvenido/a a nuestra plataforma de pagos recurrentes con tarjetas, donde hemos desarrollado una potente API diseñada para simplificar y automatizar el proceso de cobros periódicos. Nuestra API brinda a los comercios y emprendedores la capacidad de establecer y gestionar suscripciones, pagos recurrentes automatizados, permitiendo así ofrecer una experiencia de pago conveniente y sin interrupciones para sus clientes.

Con nuestra API de Pagos Recurrentes, usted podrá decir adiós a las preocupaciones de recordar fechas de vencimiento y enviar recordatorios de pago. Nuestro sistema se encargará de todo el proceso por usted, asegurando que los pagos se realicen de manera puntual y eficiente.

¿Qué beneficios ofrece nuestra API? En primer lugar, proporcionamos una integración sencilla y segura con su plataforma o sitio web existente. Nuestros endpoints y documentación detallada le guiarán en todo el proceso de implementación, permitiéndole empezar a aceptar pagos recurrentes en poco tiempo.

Además, nuestra API es compatible con múltiples medios de pagos, tarjetas de crédito, débito y prepago, lo que brinda flexibilidad a sus clientes para utilizar la opción de pago que les resulte más conveniente.

Asimismo, nuestra plataforma le permite administrar fácilmente suscripciones. Podrá crear planes personalizados, establecer intervalos de cobro, gestionar actualizaciones de tarjetas vencidas y realizar ajustes en los montos a cobrar, todo de forma rápida y sin complicaciones.

En resumen, nuestra API de Pagos Recurrentes con Tarjetas está diseñada para ayudarle a simplificar y optimizar el proceso de cobros periódicos, ahorrándole tiempo y esfuerzo. Estamos comprometidos con la seguridad y la confiabilidad, garantizando transacciones seguras y protección de datos para usted y sus clientes.

#### Características relevantes

Algunas de las características más relevantes de nuestra solución de pagos recurrentes son:

- Medios de pago disponibles: crédito, débito, prepago
- Moneda: Pesos y UF
- Activación 100% online, sin manipulación de tarjetas en su empresa
- Gestión de cambio de tarjeta (ondemand / automático)
- Gestión de reintentos de cobro (hasta 3, y configurable)
- Baja de suscripción la realiza su empresa, y opcionalmente el cliente.
- Tokenización de tarjeta con y sin autenticación del banco emisor
- Soporte de tarjetas emitidas en Chile y en extranjero.

#### Algunos conceptos y definiciones básicas antes de iniciar

| Concepto     | Descripción                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plan         | Un plan en una suscripción de pagos recurrentes es un conjunto predefinido de parámetros y condiciones que determinan los detalles de una suscripción. Un plan define los aspectos clave de una suscripción, como la frecuencia de cobro, el monto a cobrar, la duración del período de suscripción, moneda, precio, día del mes en que se realiza el cobro y cualquier otro detalle relacionado con los pagos recurrentes. En pocas palabras, un plan establece las reglas y los términos para el cobro periódico de una suscripción. Existen 3 tipos de planes que pueden ser definidos en Virtualpos: 1.- **Plan monto fijo y plazo fijo**: Corresponde a planes que tienen definido un monto fijo, por ejemplo $9.900 o 0,45 UF, y un plazo fijo dado por la cantidad de repeticiones, por ejemplo 12 cobros mensuales. 2.- **Plan de monto variable**: Corresponde a planes en los cuales no es posible predefinir un monto a cargar y en su lugar los montos deben ser informados por el comercio para generar los cargos periódicos. Por ejemplo: consumo de agua, luz, gas, seguros, etc. 3.- **Programa de pagos**: Corresponde a planes que definen una serie de cobros, en donde cada cobro podría tomar valores diferentes. Por ejemplo: primer cobro 15 UF, segundo cobro 10 UF... |
| Suscripción  | Una suscripción en cobros recurrentes se refiere a un acuerdo entre un comercio o proveedor de servicios y un cliente, en el cual se establece un período de tiempo durante el cual el cliente pagará de forma regular por un producto o servicio determinado. Para que esto sea posible el cliente (tarjetahabiente) debe proporcionar un medio de pago en el cual se realizarán los cargos.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Cargo        | El cargo corresponde al pago realizado por el cliente en una suscripción. Cómo mínimo el cargo define un monto, fecha programada para el cargo y una descripción.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Tokenización | La tokenización de tarjetas es un proceso de seguridad utilizado para proteger la información sensible de las tarjetas de crédito o débito. Consiste en reemplazar los datos reales de la tarjeta, como el número de tarjeta y la fecha de vencimiento, por un valor único generado llamado "token".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

---

# 3.1 Plan

### Objeto Plan

El objeto **plan** representa las condiciones que determinan los detalles de una suscripción. Un plan define los aspectos clave de una suscripción, como la frecuencia de cobro, el monto a cobrar, la duración del período de suscripción, moneda, precio, día del mes en que se realiza el cobro y cualquier otro detalle relacionado con los pagos recurrentes.

```json JSON
{
  "plan": {
    "id": "fd53ead26f78b56113312609b668411b",
    "name": "Seguro automotriz",
    "description": "Asegura tu vehiculo",
    "is_active": "T",
    "amount": 9990,
    "currency": "CLP",
    "trial_days": 0,
    "num_charges": 12,
    "frequency_type": "Mensual",
    "return_url": "https://www.misitio.com",
    "suscription_url": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258",
    "type": "MONTO_FIJO",
    "fixed_amount_day_charge": "05",
    "automatic_renewal": "T",
    "show_in_terminal": "F",
    "created_at": "2023-05-15 23:15:00",
    "shipping_address": "F"
  }
}
```

| Attribute                   | Type     | Description                                                                                                                                                     |
| --------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **id**                      | String   | Identificador único para el plan                                                                                                                                |
| **name**                    | String   | Nombre del plan                                                                                                                                                 |
| **description**             | String   | Descripción del plan                                                                                                                                            |
| **is_active**               | enum     | Flag de estado, T: activo y F: no activo                                                                                                                        |
| **amount**                  | float    | Monto o precio del plan                                                                                                                                         |
| **currency**                | enum     | Moneda (CLP, UF)                                                                                                                                                |
| **trial_days**              | Integer  | Días en que no se realizará cobro.                                                                                                                              |
| **num_charges**             | Integer  | Cantidad de cargos o cobros que srealizarán                                                                                                                     |
| **frequency_type**          | enum     | Frecuencia de cobro: Diario, Semanal, Mensual, Semestral, Anual                                                                                                 |
| **return_url**              | String   | URL de retorno cuando se realiza la suscripción vía formulario VirtualPOS.                                                                                      |
| **suscription_url**         | String   | URL de formulario de suscripción Virtualpos.                                                                                                                    |
| **type**                    | enum     | Tipo de plan: MONTO_FIJO, MONTO_VARIABLE, PROGRAMA_DE_PAGOS                                                                                                     |
| **fixed_amount_day_charge** | enum     | Fecha en que se realizará el cargo. Posibles valores 0,01,05,10,15,20,25,28,30. Valor 0 indica que el cargo se realizará en el mismo momento de la suscripción. |
| **show_in_terminal**        | enum     | Indica si el plan estará disponible o no para suscripción presencial desde equipos SmartPOS. T: True, F: False.                                                 |
| **automatic_renewal**       | enum     | Flag renovación automática al finalizar el periodo, T: renovará automáticamente y F: no realizará la activación automática.                                     |
| **created_at**              | datetime | Fecha de creación del plan.                                                                                                                                     |
| **shipping_address**        | enum     | Indica si el plan requiere de direcciones de despacho para sus suscriptores. T: True, F: False. Campo Opcional.                                                 |

### Crear un Plan

Permite crear un plan

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/plan": {
      "post": {
        "summary": "Crear un Plan",
        "description": "Permite crear un plan",
        "operationId": "crear-un-plan",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["name", "description", "currency"],
                "properties": {
                  "name": {
                    "type": "string",
                    "description": "Nombre del plan recurrente"
                  },
                  "description": {
                    "type": "string",
                    "description": "Descripción del plan recurrente"
                  },
                  "type": {
                    "type": "string",
                    "description": "Tipo de plan",
                    "enum": [
                      "MONTO_FIJO",
                      "MONTO_VARIABLE",
                      "PROGRAMA_DE_PAGOS"
                    ]
                  },
                  "currency": {
                    "type": "string",
                    "description": "Moneda utilizada",
                    "enum": ["CLP", "UF"]
                  },
                  "amount": {
                    "type": "number",
                    "description": "Monto fijo",
                    "format": "float"
                  },
                  "trial_days": {
                    "type": "integer",
                    "format": "int32"
                  },
                  "num_charges": {
                    "type": "integer",
                    "format": "int32"
                  },
                  "frequency_type": {
                    "type": "string",
                    "description": "Frecuencia de los cobros",
                    "enum": ["Diario", "Semanal", "Mensual"]
                  },
                  "fixed_amount_day_charge": {
                    "type": "string",
                    "enum": [
                      "0",
                      "01",
                      "05",
                      "10",
                      "15",
                      "20",
                      "25",
                      "28",
                      "30"
                    ]
                  },
                  "return_url": {
                    "type": "string",
                    "description": "URL de su aplicación a la cual se retornará una vez que se haya finalizado la suscripción. En esta URL se deberá ejecutar la consulta del resultado de suscripción, ya que por motivos de seguridad la respuesta no se entrega en forma directa a la URL de retorno"
                  },
                  "automatic_renewal": {
                    "type": "string",
                    "description": "Flag de renovación automática.",
                    "default": "F",
                    "enum": ["T", "F"]
                  },
                  "show_in_terminal": {
                    "type": "string",
                    "description": "Flag para visualización en SmartPOS",
                    "default": "F",
                    "enum": ["T", "F"]
                  },
                  "shipping_address": {
                    "type": "string",
                    "description": "Flag para indicar que requiere direcciones de despacho.",
                    "enum": ["\"T\"", "\"F\""]
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"plan\": {\n    \t\"id\": \"fd53ead26f78b56113312609b668411b\",\n    \t\"name\": \"Seguro automotriz\",\n    \t\"description\": \"Asegura tu vehiculo\",\n    \t\"is_active\": \"T\",\n      \"amount\": 9990,\n      \"currency\": \"CLP\",\n      \"trial_days\" : 0,\n      \"num_charges\" : 12,\n      \"frequency_type\" : \"Mensual\",\n      \"return_url\" : \"https://www.misitio.com\",\n      \"suscription_url\": \"https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258\",\n      \"type\" : \"MONTO_FIJO\",\n      \"fixed_amount_day_charge\" : \"05\",  \n      \"automatic_renewal\": \"T\",\n      \"show_in_terminal\" : \"F\",\n      \"created_at\" : \"2023-05-15 23:15:00\",\n      \"shipping_address\": \"F\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "plan": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "fd53ead26f78b56113312609b668411b"
                        },
                        "name": {
                          "type": "string",
                          "example": "Seguro automotriz"
                        },
                        "description": {
                          "type": "string",
                          "example": "Asegura tu vehiculo"
                        },
                        "is_active": {
                          "type": "string",
                          "example": "T"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9990,
                          "default": 0
                        },
                        "currency": {
                          "type": "string",
                          "example": "CLP"
                        },
                        "trial_days": {
                          "type": "integer",
                          "example": 0,
                          "default": 0
                        },
                        "num_charges": {
                          "type": "integer",
                          "example": 12,
                          "default": 0
                        },
                        "frequency_type": {
                          "type": "string",
                          "example": "Mensual"
                        },
                        "return_url": {
                          "type": "string",
                          "example": "https://www.misitio.com"
                        },
                        "suscription_url": {
                          "type": "string",
                          "example": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258"
                        },
                        "type": {
                          "type": "string",
                          "example": "MONTO_FIJO"
                        },
                        "fixed_amount_day_charge": {
                          "type": "string",
                          "example": "05"
                        },
                        "automatic_renewal": {
                          "type": "string",
                          "example": "T"
                        },
                        "show_in_terminal": {
                          "type": "string",
                          "example": "F"
                        },
                        "created_at": {
                          "type": "string",
                          "example": "2023-05-15 23:15:00"
                        },
                        "shipping_address": {
                          "type": "string",
                          "example": "F"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0a205491040043ef1fb4"
}
```

### Recuperar un Plan

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/plan/{plan_id}": {
      "get": {
        "summary": "Recuperar un Plan",
        "description": "",
        "operationId": "recuperar-un-plan",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{  \n  \"status\": \"OK\",\n  \"code\": 200,\n  \"plan\": {  \n    \"id\": \"fd53ead26f78b56113312609b668411b\",  \n    \"name\": \"Seguro automotriz\",  \n    \"description\": \"Asegura tu vehiculo\",  \n    \"is_active\": \"T\",  \n    \"amount\": 9990,  \n    \"currency\": \"CLP\",  \n    \"trial_days\": 0,  \n    \"num_charges\": 12,  \n    \"frequency_type\": \"Mensual\",  \n    \"return_url\": \"https://www.misitio.com\",  \n    \"suscription_url\": \"https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258\",\n    \"type\": \"MONTO_FIJO\",  \n    \"fixed_amount_day_charge\": \"05\",  \n    \"automatic_renewal\": \"T\",  \n    \"show_in_terminal\": \"F\",  \n    \"created_at\": \"2023-05-15 23:15:00\",\n     \"shipping_address\": \"F\"\n  }  \n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "plan": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "fd53ead26f78b56113312609b668411b"
                        },
                        "name": {
                          "type": "string",
                          "example": "Seguro automotriz"
                        },
                        "description": {
                          "type": "string",
                          "example": "Asegura tu vehiculo"
                        },
                        "is_active": {
                          "type": "string",
                          "example": "T"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9990,
                          "default": 0
                        },
                        "currency": {
                          "type": "string",
                          "example": "CLP"
                        },
                        "trial_days": {
                          "type": "integer",
                          "example": 0,
                          "default": 0
                        },
                        "num_charges": {
                          "type": "integer",
                          "example": 12,
                          "default": 0
                        },
                        "frequency_type": {
                          "type": "string",
                          "example": "Mensual"
                        },
                        "return_url": {
                          "type": "string",
                          "example": "https://www.misitio.com"
                        },
                        "suscription_url": {
                          "type": "string",
                          "example": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258"
                        },
                        "type": {
                          "type": "string",
                          "example": "MONTO_FIJO"
                        },
                        "fixed_amount_day_charge": {
                          "type": "string",
                          "example": "05"
                        },
                        "automatic_renewal": {
                          "type": "string",
                          "example": "T"
                        },
                        "show_in_terminal": {
                          "type": "string",
                          "example": "F"
                        },
                        "created_at": {
                          "type": "string",
                          "example": "2023-05-15 23:15:00"
                        },
                        "shipping_address": {
                          "type": "string",
                          "example": "F"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0b50cf8ba500571a3517"
}
```

### Listar plans

En esta API se puede implementar el uso de paginación para mas detalle haz click [aquí](https://virtualpos.readme.io/reference/paginacion-para-el-listado-de-objetos)

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/plans": {
      "get": {
        "summary": "Listar plans",
        "description": "",
        "operationId": "listar-plans",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"pagination\": {\n     \"limit\": 1,\n     \"page\": 1,\n     \"pages\": 2,\n     \"total\": 6\n },\n  \"plans\": [\n    {\n      \"id\": \"fd53ead26f78b56113312609b668411b\",\n      \"name\": \"Seguro automotriz\",\n      \"description\": \"Asegura tu vehiculo\",\n      \"is_active\": \"T\",\n      \"amount\": 9990,\n      \"currency\": \"CLP\",\n      \"trial_days\": 0,\n      \"num_charges\": 12,\n      \"frequency_type\": \"Mensual\",\n      \"return_url\": \"https://www.misitio.com\",\n      \"suscription_url\": \"https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258\",\n      \"type\": \"MONTO_FIJO\",\n      \"fixed_amount_day_charge\": \"05\",\n      \"automatic_renewal\": \"T\",\n      \"show_in_terminal\": \"F\",\n      \"created_at\": \"2023-05-15 23:15:00\",\n      \"shipping_address\": \"F\"\n    },\n    {\n      \"id\": \"fx53ead26f78b5s113325679b66884573f\",\n      \"name\": \"Seguro de vida\",\n      \"description\": \"Protege a tu familia\",\n      \"is_active\": \"T\",\n      \"amount\": 2.4,\n      \"currency\": \"UF\",\n      \"trial_days\": 0,\n      \"num_charges\": 12,\n      \"frequency_type\": \"Mensual\",\n      \"return_url\": \"https://www.misitio.com\",\n      \"suscription_url\": \"https://pat.virtualpos.cl/suscripcion/acme-corp/56b2b726a23ff92487984ba17b0b86784\",\n      \"type\": \"MONTO_FIJO\",\n      \"fixed_amount_day_charge\": \"05\",\n      \"automatic_renewal\": \"F\",\n      \"show_in_terminal\": \"T\",\n      \"created_at\": \"2023-05-25 13:55:00\",\n      \"shipping_address\": \"T\"\n    }\n  ]\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "pagination": {
                      "type": "object",
                      "properties": {
                        "limit": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "page": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "pages": {
                          "type": "integer",
                          "example": 2,
                          "default": 0
                        },
                        "total": {
                          "type": "integer",
                          "example": 6,
                          "default": 0
                        }
                      }
                    },
                    "plans": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "type": "string",
                            "example": "fd53ead26f78b56113312609b668411b"
                          },
                          "name": {
                            "type": "string",
                            "example": "Seguro automotriz"
                          },
                          "description": {
                            "type": "string",
                            "example": "Asegura tu vehiculo"
                          },
                          "is_active": {
                            "type": "string",
                            "example": "T"
                          },
                          "amount": {
                            "type": "integer",
                            "example": 9990,
                            "default": 0
                          },
                          "currency": {
                            "type": "string",
                            "example": "CLP"
                          },
                          "trial_days": {
                            "type": "integer",
                            "example": 0,
                            "default": 0
                          },
                          "num_charges": {
                            "type": "integer",
                            "example": 12,
                            "default": 0
                          },
                          "frequency_type": {
                            "type": "string",
                            "example": "Mensual"
                          },
                          "return_url": {
                            "type": "string",
                            "example": "https://www.misitio.com"
                          },
                          "suscription_url": {
                            "type": "string",
                            "example": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258"
                          },
                          "type": {
                            "type": "string",
                            "example": "MONTO_FIJO"
                          },
                          "fixed_amount_day_charge": {
                            "type": "string",
                            "example": "05"
                          },
                          "automatic_renewal": {
                            "type": "string",
                            "example": "T"
                          },
                          "show_in_terminal": {
                            "type": "string",
                            "example": "F"
                          },
                          "created_at": {
                            "type": "string",
                            "example": "2023-05-15 23:15:00"
                          },
                          "shipping_address": {
                            "type": "string",
                            "example": "F"
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0bd07f2ed5000a4ba636"
}
```

---

# 3.2 Suscription

### Objeto Suscription

El objeto **Suscription** representa el acuerdo entre el comercio y el cliente cuando se realiza la adherencia a un plan, y contiene los atributos necesarios para generar la recurrencia de los cobros, entre ellos el medio de pago .

El objeto **Suscription** puede tener los siguientes estados dependiendo de la etapa en la que se encuentre:

| STATUS              | DESCRIPTION                                                                                                         |
| :------------------ | :------------------------------------------------------------------------------------------------------------------ |
| SUSCRIBIENDO        | Estado inicial, en espera de que el cliente termine el flujo de suscripción.                                        |
| SUSCRIPCION_FALLIDA | Estado final, indica que finalizó el flujo de suscripción sin que el cliente pudiera inscribir un medio de pago.    |
| ACTIVA              | Estado final, finalizó el flujo de suscripción de forma exitosa, el cliente inscribió un medio de pago válido.      |
| CANCELADA           | Estado final, indica que la suscripción fue detenida y no se procesaran los cargos futuros que estaban programados. |
| FINALIZADA          | Ha superado el tiempo máximo de espera del intento de suscripción. Default 30 días.                                 |

Atributos del objeto **Suscription**:

| Attribute             | Type         | Description                                                                                                                                                                                                               |
| --------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **id**                | string       | Código único que representa la suscripción a un plan en Virtualpos. Se recomienda almacenar para posteriormente consultar el resultado.                                                                                   |
| **status**            | enum         | Estado de la suscripción. El listado de valores posibles es el siguiente (ver tabla STATUS) : <li>**SUSCRIBIENDO**</li><li>**ACTIVA**</li><li> **SUSCRIPCION_FALLIDA**</li><li>**CANCELADA**</li> <li>**FINALIZADA**</li> |
| **plan_id**           | string       | Identificador del plan del comercio.                                                                                                                                                                                      |
| **plan_name**         | string       | Nombre del plan del comercio.                                                                                                                                                                                             |
| **suscription_date**  | date         | Fecha de creación de la suscripción Formato: yyyy-mm-dd hh:mm:ss                                                                                                                                                          |
| **payment_method**    | object       | Medio de pago asociado a la suscripción.                                                                                                                                                                                  |
| **currency**          | enum         | Moneda utilizada para efectuar los cobros. Valores posibles : <li>**CLP**</li> <li>**UF**</li>                                                                                                                            |
| **amount**            | numeric      | Monto utilizado para programar los cobros recurrentes.                                                                                                                                                                    |
| **automatic_renewal** | enum         | Indicador de renovación automática de la suscripción. Valores posibles : <li>**F**</li><li>**T**</li>                                                                                                                     |
| **channel**           | string       | Canal utilizado por el comercio para iniciar el proceso de suscripción.                                                                                                                                                   |
| **service_id**        | string       | Parámetro informado por el comercio para asociarlo a la suscripción.                                                                                                                                                      |
| **charge_program**    | object array | Listado de objetos con la programación de los cobros.                                                                                                                                                                     |
| **client**            | object       | Cliente asociado a la suscripción                                                                                                                                                                                         |

**Objeto payment_method**

| Attribute           | Type    | Description                                                                                                                                                                 |
| ------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **bin**             | integer | Numero de identificación del emisor del medio de pago.                                                                                                                      |
| **issuer**          | string  | Nombre del emisor del medio de pago.                                                                                                                                        |
| **last4CardDigit**  | integer | 4 últimos dígitos del medio de pago.                                                                                                                                        |
| **brand**           | string  | Marca del medio de pago, ejemplo: **Visa**, **Mastercard**, **Amex**.                                                                                                       |
| **expiration_date** | string  | Fecha de expiración del método de pago                                                                                                                                      |
| **card_on_file**    | enum    | Parámetro que indica si el método de pago es tokenizado y almacenado en la bóveda de Virtualpos. Valores posibles : <li>**LOCAL_ISSUER**</li><li>**NO_AUTHENTICATION**</li> |

**Objeto charge_program**

| Attribute   | Type    | Description                                                                                                                                                                       |
| ----------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| id          | string  | Identificador unico del cobro.                                                                                                                                                    |
| charge_date | date    | Fecha de la programación del cobro, formato : yyyy-mm-dd                                                                                                                          |
| amount      | numeric | Monto del cobro.                                                                                                                                                                  |
| status      | enum    | Estado del cobro. El listado de valores posibles es el siguiente : <li>**pendiente**</li><li>**pagado**</li><li> **cancelado**</li><li>**procesando**</li> <li>**rechazado**</li> |
| description | string  | Descripción del cobro, ejemplo: **Cargo 1 de 12**                                                                                                                                 |

**objeto client**

| Attribute  | Type   | Description                                                  |
| :--------- | :----- | :----------------------------------------------------------- |
| email      | email  | Correo del cliente asociado a la suscripción                 |
| first_name | string | Nombre del cliente.                                          |
| last_name  | string | Apellido del cliente.                                        |
| social_id  | string | Rut del cliente.                                             |
| phone      | string | Telefono del cliente.                                        |
| gender     | object | Objeto con la información relacionada al género del cliente. |
| birth_date | date   | Fecha de nacimiento del cliente.                             |

**objeto address**

| Attribute                 | Type    | Description                                                    |
| :------------------------ | :------ | :------------------------------------------------------------- |
| id                        | numeric | Identificador único de la dirección.                           |
| address_name              | string  | Nombre de la dirección registrada.                             |
| street_name               | string  | Nombre de la Avenida/Calle/Pasaje.                             |
| street_number             | string  | Identifiacación de la Avenida/Calle/Pasaje.                    |
| dpto_number               | string  | Identificación del Departamento o Bloque                       |
| additional_information    | string  | Información adicional, relacionada a la dirección de despacho. |
| additional_commerce_notes | string  | Notas adicionales, tomadas por el comercio.                    |
| comuna_id                 | numeric | Identificador único de la comuna.                              |
| comuna_name               | string  | Nombre de la comuna.                                           |
| region_id                 | numeric | Identificador único de la región.                              |
| region_name               | string  | Nombre de la región                                            |

### Crear una Suscription

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/suscription": {
      "post": {
        "summary": "Crear una Suscription",
        "description": "",
        "operationId": "crear-una-suscription",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": [
                  "email",
                  "social_id",
                  "first_name",
                  "last_name",
                  "phone_number",
                  "plan_id",
                  "return_url",
                  "callback_url"
                ],
                "properties": {
                  "email": {
                    "type": "string",
                    "description": "Correo electrónico del cliente"
                  },
                  "social_id": {
                    "type": "string",
                    "description": "Rut del cliente, Tipo: Rut válido sin puntos ni guion"
                  },
                  "first_name": {
                    "type": "string",
                    "description": "Nombre del cliente"
                  },
                  "last_name": {
                    "type": "string",
                    "description": "Apellido del cliente"
                  },
                  "phone_number": {
                    "type": "string",
                    "description": "Número teléfonico del cliente"
                  },
                  "plan_id": {
                    "type": "string",
                    "description": "Identificador del plan a suscribir"
                  },
                  "service_id": {
                    "type": "string",
                    "description": "Identificador del comercio, útil para realizar trazabilidad."
                  },
                  "channel": {
                    "type": "string",
                    "description": "Identificador del canal utilizado por el comercio para generar la suscripción, útil para realizar trazabilidad."
                  },
                  "automatic_renewal": {
                    "type": "string",
                    "description": "Parámetro que indica si la suscripción se debe renovar al finalizar la programación de los cobros, aplica para suscripciones de monto fijo y programa de cobros.",
                    "default": "F",
                    "enum": ["F", "T"]
                  },
                  "card_on_file": {
                    "type": "string",
                    "description": "Parámetro que indica si el método de pago es tokenizado y almacenado en la bóveda de VirtualPOS . Valores posibles :",
                    "default": "LOCAL_ISSUER",
                    "enum": ["LOCAL_ISSUER", "NO_AUTHENTICATION"]
                  },
                  "charges_program": {
                    "type": "array",
                    "description": "Parámetro obligatorio para planes del tipo “PROGRAMA DE PAGOS”, El formato del parámetro debe ser un array JSON con un listado de objetos con la fecha del cargo (charge_date) y el monto (amount). El parámetro charges_program debe ser codificada en Base64.",
                    "items": {
                      "properties": {
                        "amount": {
                          "type": "number",
                          "description": "Monto del cobro que se desea programar",
                          "format": "float"
                        },
                        "charge_date": {
                          "type": "string",
                          "description": "Fecha que se desea realizar el cargo, Tipo: date yyyy-mm-dd, ejemplo: 2021-09-30"
                        },
                        "description": {
                          "type": "string",
                          "description": "Detalle descriptivo asociado al cargo que se realizará"
                        },
                        "internal_code": {
                          "type": "string",
                          "description": "Identificador del comercio, útil para identificar y dar trazabilidad al cobro."
                        }
                      },
                      "required": ["amount", "charge_date", "description"],
                      "type": "object"
                    }
                  },
                  "return_url": {
                    "type": "string",
                    "description": "URL a la cual será redirigido el suscriptor una vez finalizado el flujo de suscripción. La URL debe ser codificada en Base64"
                  },
                  "callback_url": {
                    "type": "string",
                    "description": "URL a la cual se realizará un callback Asincrono una vez que se haya finalizado el proceso de inscripción en VirtualPOS. Debe estar codificada Base64"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\t\"status\": \"OK\",\n  \"code\": 200,\n  \"url_redirect\" : \"https://pat.virtualpos.cl/suscripcion-integrada/3a4d77f2e4\",  \n  \"suscription\":{\n      \"status\":\"ACTIVA\",\n      \"id\":\"3a4d77f2e4\",\n      \"plan_id\":\"fd53ead26f78b56113312609b668411b\",\n      \"plan_name\":\"Plan mensual\",\n      \"suscription_date\":\"2021-09-08 11:20:31\",\n      \"payment_method\":{\n         \"bin\":\"405188\",\n         \"issuer\":\"Banco de Chile\",\n         \"last4CardDigit\":\"6623\",\n         \"brand\":\"VISA\",\n         \"expiration_date\":\"12/27\",\n         \"card_on_file\":\"F\"\n      },\n      \"currency\":\"CLP\",\n      \"amount\":9990,\n      \"automatic_renewal\":\"F\",\n      \"channel\":\"WEB\",\n      \"service_id\":\"12312312-3\",\n      \"charge_program\":[\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832273\",\n            \"charge_date\":\"2023-05-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pagado\",\n            \"description\":\"Cargo 1 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832274\",\n            \"charge_date\":\"2023-06-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 2 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832275\",\n            \"charge_date\":\"2023-07-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 3 de 3\"\n         }\n      ],\n      \"client\":{\n         \"email\":\"user@example.com\",\n         \"first_name\":\"John\",\n         \"last_name\":\"Doe\",\n         \"social_id\":\"12345678-9\",\n         \"phone\":\"56961934502\",\n          \"gender\": {\n             \"id\": 1,\n              \"name\": \"Masculino\"\n          },\n          \"birth_date\": \"1992-10-20\"\n      }\n   }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "url_redirect": {
                      "type": "string",
                      "example": "https://pat.virtualpos.cl/suscripcion-integrada/3a4d77f2e4"
                    },
                    "suscription": {
                      "type": "object",
                      "properties": {
                        "status": {
                          "type": "string",
                          "example": "ACTIVA"
                        },
                        "id": {
                          "type": "string",
                          "example": "3a4d77f2e4"
                        },
                        "plan_id": {
                          "type": "string",
                          "example": "fd53ead26f78b56113312609b668411b"
                        },
                        "plan_name": {
                          "type": "string",
                          "example": "Plan mensual"
                        },
                        "suscription_date": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        },
                        "payment_method": {
                          "type": "object",
                          "properties": {
                            "bin": {
                              "type": "string",
                              "example": "405188"
                            },
                            "issuer": {
                              "type": "string",
                              "example": "Banco de Chile"
                            },
                            "last4CardDigit": {
                              "type": "string",
                              "example": "6623"
                            },
                            "brand": {
                              "type": "string",
                              "example": "VISA"
                            },
                            "expiration_date": {
                              "type": "string",
                              "example": "12/27"
                            },
                            "card_on_file": {
                              "type": "string",
                              "example": "F"
                            }
                          }
                        },
                        "currency": {
                          "type": "string",
                          "example": "CLP"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9990,
                          "default": 0
                        },
                        "automatic_renewal": {
                          "type": "string",
                          "example": "F"
                        },
                        "channel": {
                          "type": "string",
                          "example": "WEB"
                        },
                        "service_id": {
                          "type": "string",
                          "example": "12312312-3"
                        },
                        "charge_program": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "id": {
                                "type": "string",
                                "example": "cid_2566645567e51ef2b7.76832273"
                              },
                              "charge_date": {
                                "type": "string",
                                "example": "2023-05-01"
                              },
                              "amount": {
                                "type": "string",
                                "example": "6990"
                              },
                              "status": {
                                "type": "string",
                                "example": "pagado"
                              },
                              "description": {
                                "type": "string",
                                "example": "Cargo 1 de 3"
                              }
                            }
                          }
                        },
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            },
                            "gender": {
                              "type": "object",
                              "properties": {
                                "id": {
                                  "type": "integer",
                                  "example": 1,
                                  "default": 0
                                },
                                "name": {
                                  "type": "string",
                                  "example": "Masculino"
                                }
                              }
                            },
                            "birth_date": {
                              "type": "string",
                              "example": "1992-10-20"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0d979d9e140047a6232b"
}
```

### Recuperar una Suscription

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/suscription/{suscription_id}": {
      "get": {
        "summary": "Recuperar una Suscription",
        "description": "",
        "operationId": "recuperar-una-suscription",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\t\"status\": \"OK\",\n  \"code\": 200,\n  \"suscription\":{\n      \"status\":\"ACTIVA\",\n      \"id\":\"3a4d77f2e4\",\n      \"plan_id\":\"fd53ead26f78b56113312609b668411b\",\n      \"plan_name\":\"Plan mensual\",\n      \"suscription_date\":\"2021-09-08 11:20:31\",\n      \"payment_method\":{\n         \"bin\":\"405188\",\n         \"issuer\":\"Banco de Chile\",\n         \"last4CardDigit\":\"6623\",\n         \"brand\":\"VISA\",\n         \"expiration_date\":\"12/27\",\n         \"card_on_file\":\"F\"\n      },\n      \"currency\":\"CLP\",\n      \"amount\":9990,\n      \"renewal\":\"F\",\n      \"channel\":\"WEB\",\n      \"service_id\":\"12312312-3\",\n      \"charge_program\":[\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832273\",\n            \"charge_date\":\"2023-05-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pagado\",\n            \"description\":\"Cargo 1 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832274\",\n            \"charge_date\":\"2023-06-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 2 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832275\",\n            \"charge_date\":\"2023-07-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 3 de 3\"\n         }\n      ],\n      \"client\":{\n         \"email\":\"user@example.com\",\n         \"first_name\":\"John\",\n         \"last_name\":\"Doe\",\n         \"social_id\":\"12345678-9\",\n         \"phone\":\"56961934502\",\n          \"gender\": {\n             \"id\": 1,\n              \"name\": \"Masculino\"\n          },\n          \"birth_date\": \"1992-10-20\"\n      }\n   }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription": {
                      "type": "object",
                      "properties": {
                        "status": {
                          "type": "string",
                          "example": "ACTIVA"
                        },
                        "id": {
                          "type": "string",
                          "example": "3a4d77f2e4"
                        },
                        "plan_id": {
                          "type": "string",
                          "example": "fd53ead26f78b56113312609b668411b"
                        },
                        "plan_name": {
                          "type": "string",
                          "example": "Plan mensual"
                        },
                        "suscription_date": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        },
                        "payment_method": {
                          "type": "object",
                          "properties": {
                            "bin": {
                              "type": "string",
                              "example": "405188"
                            },
                            "issuer": {
                              "type": "string",
                              "example": "Banco de Chile"
                            },
                            "last4CardDigit": {
                              "type": "string",
                              "example": "6623"
                            },
                            "brand": {
                              "type": "string",
                              "example": "VISA"
                            },
                            "expiration_date": {
                              "type": "string",
                              "example": "12/27"
                            },
                            "card_on_file": {
                              "type": "string",
                              "example": "F"
                            }
                          }
                        },
                        "currency": {
                          "type": "string",
                          "example": "CLP"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9990,
                          "default": 0
                        },
                        "renewal": {
                          "type": "string",
                          "example": "F"
                        },
                        "channel": {
                          "type": "string",
                          "example": "WEB"
                        },
                        "service_id": {
                          "type": "string",
                          "example": "12312312-3"
                        },
                        "charge_program": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "id": {
                                "type": "string",
                                "example": "cid_2566645567e51ef2b7.76832273"
                              },
                              "charge_date": {
                                "type": "string",
                                "example": "2023-05-01"
                              },
                              "amount": {
                                "type": "string",
                                "example": "6990"
                              },
                              "status": {
                                "type": "string",
                                "example": "pagado"
                              },
                              "description": {
                                "type": "string",
                                "example": "Cargo 1 de 3"
                              }
                            }
                          }
                        },
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            },
                            "gender": {
                              "type": "object",
                              "properties": {
                                "id": {
                                  "type": "integer",
                                  "example": 1,
                                  "default": 0
                                },
                                "name": {
                                  "type": "string",
                                  "example": "Masculino"
                                }
                              }
                            },
                            "birth_date": {
                              "type": "string",
                              "example": "1992-10-20"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
                    "status": "OK",
                    "code": 200,
                    "suscription": {
                      "status": "ACTIVA",
                      "id": "3a4d77f2e4",
                      "plan_id": "fd53ead26f78b56113312609b668411b",
                      "plan_name": "Plan mensual",
                      "suscription_date": "2021-09-08 11:20:31",
                      "payment_method": {
                        "bin": "405188",
                        "issuer": "Banco de Chile",
                        "last4CardDigit": "6623",
                        "brand": "VISA",
                        "expiration_date": "12/27",
                        "card_on_file": "F"
                      },
                      "currency": "CLP",
                      "amount": 9990,
                      "renewal": "F",
                      "channel": "WEB",
                      "service_id": "12312312-3",
                      "charge_program": [
                        {
                          "id": "cid_2566645567e51ef2b7.76832273",
                          "charge_date": "2023-05-01",
                          "amount": "6990",
                          "status": "pagado",
                          "description": "Cargo 1 de 3"
                        },
                        {
                          "id": "cid_2566645567e51ef2b7.76832274",
                          "charge_date": "2023-06-01",
                          "amount": "6990",
                          "status": "pendiente",
                          "description": "Cargo 2 de 3"
                        },
                        {
                          "id": "cid_2566645567e51ef2b7.76832275",
                          "charge_date": "2023-07-01",
                          "amount": "6990",
                          "status": "pendiente",
                          "description": "Cargo 3 de 3"
                        }
                      ],
                      "client": {
                        "email": "user@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "social_id": "12345678-9",
                        "phone": "56961934502"
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0dd9855768000b9ffc2d"
}
```

### Cancelar una Suscription

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/suscription/{suscription_id}": {
      "delete": {
        "summary": "Cancelar una Suscription",
        "description": "",
        "operationId": "cancelar-una-suscription",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\t\"status\": \"OK\",\n  \"code\": 200,\n  \"suscription\":{\n      \"status\":\"CANCELADA\",\n      \"id\":\"3a4d77f2e4\",\n      \"plan_id\":\"fd53ead26f78b56113312609b668411b\",\n      \"plan_name\":\"Plan mensual\",\n      \"suscription_date\":\"2021-09-08 11:20:31\",\n      \"payment_method\":{\n         \"bin\":\"405188\",\n         \"issuer\":\"Banco de Chile\",\n         \"last4CardDigit\":\"6623\",\n         \"brand\":\"VISA\",\n         \"expiration_date\":\"12/27\",\n         \"card_on_file\":\"F\"\n      },\n      \"currency\":\"CLP\",\n      \"amount\":9990,\n      \"renewal\":\"F\",\n      \"channel\":\"WEB\",\n      \"service_id\":\"12312312-3\",\n      \"charge_program\":[\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832273\",\n            \"charge_date\":\"2023-05-01\",\n            \"amount\":\"6990\",\n            \"status\":\"cancelado\",\n            \"description\":\"Cargo 1 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832274\",\n            \"charge_date\":\"2023-06-01\",\n            \"amount\":\"6990\",\n            \"status\":\"cancelado\",\n            \"description\":\"Cargo 2 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832275\",\n            \"charge_date\":\"2023-07-01\",\n            \"amount\":\"6990\",\n            \"status\":\"cancelado\",\n            \"description\":\"Cargo 3 de 3\"\n         }\n      ],\n      \"client\":{\n         \"email\":\"user@example.com\",\n         \"first_name\":\"John\",\n         \"last_name\":\"Doe\",\n         \"social_id\":\"12345678-9\",\n         \"phone\":\"56961934502\",\n          \"gender\": {\n             \"id\": 1,\n              \"name\": \"Masculino\"\n          },\n          \"birth_date\": \"1992-10-20\"\n      }\n   }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription": {
                      "type": "object",
                      "properties": {
                        "status": {
                          "type": "string",
                          "example": "CANCELADA"
                        },
                        "id": {
                          "type": "string",
                          "example": "3a4d77f2e4"
                        },
                        "plan_id": {
                          "type": "string",
                          "example": "fd53ead26f78b56113312609b668411b"
                        },
                        "plan_name": {
                          "type": "string",
                          "example": "Plan mensual"
                        },
                        "suscription_date": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        },
                        "payment_method": {
                          "type": "object",
                          "properties": {
                            "bin": {
                              "type": "string",
                              "example": "405188"
                            },
                            "issuer": {
                              "type": "string",
                              "example": "Banco de Chile"
                            },
                            "last4CardDigit": {
                              "type": "string",
                              "example": "6623"
                            },
                            "brand": {
                              "type": "string",
                              "example": "VISA"
                            },
                            "expiration_date": {
                              "type": "string",
                              "example": "12/27"
                            },
                            "card_on_file": {
                              "type": "string",
                              "example": "F"
                            }
                          }
                        },
                        "currency": {
                          "type": "string",
                          "example": "CLP"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9990,
                          "default": 0
                        },
                        "renewal": {
                          "type": "string",
                          "example": "F"
                        },
                        "channel": {
                          "type": "string",
                          "example": "WEB"
                        },
                        "service_id": {
                          "type": "string",
                          "example": "12312312-3"
                        },
                        "charge_program": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "id": {
                                "type": "string",
                                "example": "cid_2566645567e51ef2b7.76832273"
                              },
                              "charge_date": {
                                "type": "string",
                                "example": "2023-05-01"
                              },
                              "amount": {
                                "type": "string",
                                "example": "6990"
                              },
                              "status": {
                                "type": "string",
                                "example": "cancelado"
                              },
                              "description": {
                                "type": "string",
                                "example": "Cargo 1 de 3"
                              }
                            }
                          }
                        },
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            },
                            "gender": {
                              "type": "object",
                              "properties": {
                                "id": {
                                  "type": "integer",
                                  "example": 1,
                                  "default": 0
                                },
                                "name": {
                                  "type": "string",
                                  "example": "Masculino"
                                }
                              }
                            },
                            "birth_date": {
                              "type": "string",
                              "example": "1992-10-20"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
                    "status": "OK",
                    "code": 200,
                    "created_at": "2021-09-08 11:20:31",
                    "suscription": {
                      "status": "CANCELADA",
                      "id": "3a4d77f2e4",
                      "plan_id": "fd53ead26f78b56113312609b668411b",
                      "plan_name": "Plan mensual",
                      "suscription_date": "2021-09-08 11:20:31",
                      "payment_method": {
                        "bin": "405188",
                        "issuer": "Banco de Chile",
                        "last4CardDigit": "6623",
                        "brand": "VISA",
                        "expiration_date": "12/27",
                        "card_on_file": "F"
                      },
                      "currency": "CLP",
                      "amount": 9990,
                      "renewal": "F",
                      "channel": "WEB",
                      "service_id": "12312312-3",
                      "charge_program": [
                        {
                          "id": "cid_2566645567e51ef2b7.76832273",
                          "charge_date": "2023-05-01",
                          "amount": "6990",
                          "status": "cancelado",
                          "description": "Cargo 1 de 3"
                        },
                        {
                          "id": "cid_2566645567e51ef2b7.76832274",
                          "charge_date": "2023-06-01",
                          "amount": "6990",
                          "status": "cancelado",
                          "description": "Cargo 2 de 3"
                        },
                        {
                          "id": "cid_2566645567e51ef2b7.76832275",
                          "charge_date": "2023-07-01",
                          "amount": "6990",
                          "status": "cancelado",
                          "description": "Cargo 3 de 3"
                        }
                      ],
                      "client": {
                        "email": "user@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "social_id": "12345678-9",
                        "phone": "56961934502"
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0dfe647bc500605e335f"
}
```

### Listar Suscriptions

En esta API se puede implementar el uso de paginación para mas detalle haz click [aquí](https://virtualpos.readme.io/reference/paginacion-para-el-listado-de-objetos)

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/suscriptions": {
      "get": {
        "summary": "Listar Suscriptions",
        "description": "",
        "operationId": "listar-suscriptions",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "status",
            "in": "query",
            "description": "Estado del objeto suscription",
            "schema": {
              "type": "string",
              "enum": [
                "SUSCRIBIENDO",
                "SUSCRIPCION_FALLIDA",
                "ACTIVA",
                "CANCELADA",
                "FINALIZADA"
              ]
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\t\"status\": \"OK\",\n  \"code\": 200,\n  \"pagination\": {\n     \"limit\": 1,\n     \"page\": 1,\n     \"pages\": 2,\n     \"total\": 6\n \t},\n  \"suscriptions\":[{\n      \"status\":\"ACTIVA\",\n      \"id\":\"3a4d77f2e4\",\n      \"plan_id\":\"fd53ead26f78b56113312609b668411b\",\n      \"plan_name\":\"Plan mensual\",\n      \"suscription_date\":\"2021-09-08 11:20:31\",\n      \"payment_method\":{\n         \"bin\":\"405188\",\n         \"issuer\":\"Banco de Chile\",\n         \"last4CardDigit\":\"6623\",\n         \"brand\":\"VISA\",\n         \"expiration_date\":\"12/27\",\n         \"card_on_file\":\"F\"\n      },\n      \"currency\":\"CLP\",\n      \"amount\":9990,\n      \"renewal\":\"F\",\n      \"channel\":\"WEB\",\n      \"service_id\":\"12312312-3\",\n      \"charge_program\":[\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832273\",\n            \"charge_date\":\"2023-05-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pagado\",\n            \"description\":\"Cargo 1 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832274\",\n            \"charge_date\":\"2023-06-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 2 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832275\",\n            \"charge_date\":\"2023-07-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 3 de 3\"\n         }\n      ],\n      \"client\":{\n         \"email\":\"user@example.com\",\n         \"first_name\":\"John\",\n         \"last_name\":\"Doe\",\n         \"social_id\":\"12345678-9\",\n         \"phone\":\"56961934502\"\n      }\n   },\n   {\n      \"status\":\"ACTIVA\",\n      \"id\":\"3a4d77f3ws\",\n      \"plan_id\":\"fd53ead26f78b56113312609b668411b\",\n      \"plan_name\":\"Plan mensual\",\n      \"suscription_date\":\"2021-10-09 11:20:31\",\n      \"payment_method\":{\n         \"bin\":\"405188\",\n         \"issuer\":\"Banco de Chile\",\n         \"last4CardDigit\":\"6623\",\n         \"brand\":\"VISA\",\n         \"expiration_date\":\"12/27\",\n         \"card_on_file\":\"F\"\n      },\n      \"currency\":\"CLP\",\n      \"amount\":9990,\n      \"renewal\":\"F\",\n      \"channel\":\"WEB\",\n      \"service_id\":\"12312312-3\",\n      \"charge_program\":[\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832273\",\n            \"charge_date\":\"2023-05-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pagado\",\n            \"description\":\"Cargo 1 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832274\",\n            \"charge_date\":\"2023-06-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 2 de 3\"\n         },\n         {\n            \"id\":\"cid_2566645567e51ef2b7.76832275\",\n            \"charge_date\":\"2023-07-01\",\n            \"amount\":\"6990\",\n            \"status\":\"pendiente\",\n            \"description\":\"Cargo 3 de 3\"\n         }\n      ],\n      \"client\":{\n         \"email\":\"user@example.com\",\n         \"first_name\":\"John\",\n         \"last_name\":\"Doe\",\n         \"social_id\":\"12345678-9\",\n         \"phone\":\"56961934502\",\n         \"gender\": {\n             \"id\": 1,\n              \"name\": \"Masculino\"\n          },\n          \"birth_date\": \"1992-10-20\"\n      }\n   }\n ]                \n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "pagination": {
                      "type": "object",
                      "properties": {
                        "limit": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "page": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "pages": {
                          "type": "integer",
                          "example": 2,
                          "default": 0
                        },
                        "total": {
                          "type": "integer",
                          "example": 6,
                          "default": 0
                        }
                      }
                    },
                    "suscriptions": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "status": {
                            "type": "string",
                            "example": "ACTIVA"
                          },
                          "id": {
                            "type": "string",
                            "example": "3a4d77f2e4"
                          },
                          "plan_id": {
                            "type": "string",
                            "example": "fd53ead26f78b56113312609b668411b"
                          },
                          "plan_name": {
                            "type": "string",
                            "example": "Plan mensual"
                          },
                          "suscription_date": {
                            "type": "string",
                            "example": "2021-09-08 11:20:31"
                          },
                          "payment_method": {
                            "type": "object",
                            "properties": {
                              "bin": {
                                "type": "string",
                                "example": "405188"
                              },
                              "issuer": {
                                "type": "string",
                                "example": "Banco de Chile"
                              },
                              "last4CardDigit": {
                                "type": "string",
                                "example": "6623"
                              },
                              "brand": {
                                "type": "string",
                                "example": "VISA"
                              },
                              "expiration_date": {
                                "type": "string",
                                "example": "12/27"
                              },
                              "card_on_file": {
                                "type": "string",
                                "example": "F"
                              }
                            }
                          },
                          "currency": {
                            "type": "string",
                            "example": "CLP"
                          },
                          "amount": {
                            "type": "integer",
                            "example": 9990,
                            "default": 0
                          },
                          "renewal": {
                            "type": "string",
                            "example": "F"
                          },
                          "channel": {
                            "type": "string",
                            "example": "WEB"
                          },
                          "service_id": {
                            "type": "string",
                            "example": "12312312-3"
                          },
                          "charge_program": {
                            "type": "array",
                            "items": {
                              "type": "object",
                              "properties": {
                                "id": {
                                  "type": "string",
                                  "example": "cid_2566645567e51ef2b7.76832273"
                                },
                                "charge_date": {
                                  "type": "string",
                                  "example": "2023-05-01"
                                },
                                "amount": {
                                  "type": "string",
                                  "example": "6990"
                                },
                                "status": {
                                  "type": "string",
                                  "example": "pagado"
                                },
                                "description": {
                                  "type": "string",
                                  "example": "Cargo 1 de 3"
                                }
                              }
                            }
                          },
                          "client": {
                            "type": "object",
                            "properties": {
                              "email": {
                                "type": "string",
                                "example": "user@example.com"
                              },
                              "first_name": {
                                "type": "string",
                                "example": "John"
                              },
                              "last_name": {
                                "type": "string",
                                "example": "Doe"
                              },
                              "social_id": {
                                "type": "string",
                                "example": "12345678-9"
                              },
                              "phone": {
                                "type": "string",
                                "example": "56961934502"
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0e4cf1301e00375581b3"
}
```

### Generar link de cambio de tarjeta

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/suscription/{suscription_id}/changecard": {
      "put": {
        "summary": "Generar link de cambio de tarjeta",
        "description": "",
        "operationId": "generar-link-de-cambio-de-tarjeta",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"change_card_url\": \"https://pat.virtualpos.cl/card-change/3a4d77f2e4\",\n  \"change_card_expiration_date\" : \"2023-10-01\",\n  \"suscription\": {\n    \"status\": \"ACTIVA\",\n    \"id\": \"3a4d77f2e4\",\n    \"plan_id\": \"fd53ead26f78b56113312609b668411b\",\n    \"plan_name\": \"Plan mensual\",\n    \"suscription_date\": \"2023-03-08 11:20:31\",\n    \"payment_method\": {\n      \"bin\": \"405188\",\n      \"issuer\": \"Banco de Chile\",\n      \"last4CardDigit\": \"6623\",\n      \"brand\": \"VISA\",\n      \"expiration_date\": \"12/27\",\n      \"card_on_file\": \"F\"\n    },\n    \"currency\": \"CLP\",\n    \"amount\": 9990,\n    \"renewal\": \"F\",\n    \"channel\": \"WEB\",\n    \"service_id\": \"12312312-3\",\n    \"charge_program\": [\n      {\n        \"id\": \"cid_2566645567e51ef2b7.76832273\",\n        \"charge_date\": \"2023-05-01\",\n        \"amount\": \"6990\",\n        \"status\": \"rechazado\",\n        \"description\": \"Cargo 1 de 3\"\n      },\n      {\n        \"id\": \"cid_2566645567e51ef2b7.76832274\",\n        \"charge_date\": \"2023-06-01\",\n        \"amount\": \"6990\",\n        \"status\": \"rechazado\",\n        \"description\": \"Cargo 2 de 3\"\n      },\n      {\n        \"id\": \"cid_2566645567e51ef2b7.76832275\",\n        \"charge_date\": \"2023-07-01\",\n        \"amount\": \"6990\",\n        \"status\": \"rechazado\",\n        \"description\": \"Cargo 3 de 3\"\n      }\n    ],\n    \"client\": {\n      \"email\": \"user@example.com\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"social_id\": \"12345678-9\",\n      \"phone\": \"56961934502\",\n       \"gender\": {\n         \"id\": 1,\n          \"name\": \"Masculino\"\n       },\n       \"birth_date\": \"1992-10-20\"\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "change_card_url": {
                      "type": "string",
                      "example": "https://pat.virtualpos.cl/card-change/3a4d77f2e4"
                    },
                    "change_card_expiration_date": {
                      "type": "string",
                      "example": "2023-10-01"
                    },
                    "suscription": {
                      "type": "object",
                      "properties": {
                        "status": {
                          "type": "string",
                          "example": "ACTIVA"
                        },
                        "id": {
                          "type": "string",
                          "example": "3a4d77f2e4"
                        },
                        "plan_id": {
                          "type": "string",
                          "example": "fd53ead26f78b56113312609b668411b"
                        },
                        "plan_name": {
                          "type": "string",
                          "example": "Plan mensual"
                        },
                        "suscription_date": {
                          "type": "string",
                          "example": "2023-03-08 11:20:31"
                        },
                        "payment_method": {
                          "type": "object",
                          "properties": {
                            "bin": {
                              "type": "string",
                              "example": "405188"
                            },
                            "issuer": {
                              "type": "string",
                              "example": "Banco de Chile"
                            },
                            "last4CardDigit": {
                              "type": "string",
                              "example": "6623"
                            },
                            "brand": {
                              "type": "string",
                              "example": "VISA"
                            },
                            "expiration_date": {
                              "type": "string",
                              "example": "12/27"
                            },
                            "card_on_file": {
                              "type": "string",
                              "example": "F"
                            }
                          }
                        },
                        "currency": {
                          "type": "string",
                          "example": "CLP"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9990,
                          "default": 0
                        },
                        "renewal": {
                          "type": "string",
                          "example": "F"
                        },
                        "channel": {
                          "type": "string",
                          "example": "WEB"
                        },
                        "service_id": {
                          "type": "string",
                          "example": "12312312-3"
                        },
                        "charge_program": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "id": {
                                "type": "string",
                                "example": "cid_2566645567e51ef2b7.76832273"
                              },
                              "charge_date": {
                                "type": "string",
                                "example": "2023-05-01"
                              },
                              "amount": {
                                "type": "string",
                                "example": "6990"
                              },
                              "status": {
                                "type": "string",
                                "example": "rechazado"
                              },
                              "description": {
                                "type": "string",
                                "example": "Cargo 1 de 3"
                              }
                            }
                          }
                        },
                        "client": {
                          "type": "object",
                          "properties": {
                            "email": {
                              "type": "string",
                              "example": "user@example.com"
                            },
                            "first_name": {
                              "type": "string",
                              "example": "John"
                            },
                            "last_name": {
                              "type": "string",
                              "example": "Doe"
                            },
                            "social_id": {
                              "type": "string",
                              "example": "12345678-9"
                            },
                            "phone": {
                              "type": "string",
                              "example": "56961934502"
                            },
                            "gender": {
                              "type": "object",
                              "properties": {
                                "id": {
                                  "type": "integer",
                                  "example": 1,
                                  "default": 0
                                },
                                "name": {
                                  "type": "string",
                                  "example": "Masculino"
                                }
                              }
                            },
                            "birth_date": {
                              "type": "string",
                              "example": "1992-10-20"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
                    "status": "OK",
                    "code": 200,
                    "created_at": "2023-03-08 11:20:31",
                    "change_card_url": "https://pat.virtualpos.cl/card-change/3a4d77f2e4",
                    "change_card_expiration_date": "2023-10-01",
                    "suscription": {
                      "status": "ACTIVA",
                      "uuid": "3a4d77f2e4",
                      "plan_id": "fd53ead26f78b56113312609b668411b",
                      "plan_name": "Plan mensual",
                      "suscription_date": "2023-03-08 11:20:31",
                      "payment_method": {
                        "bin": "405188",
                        "issuer": "Banco de Chile",
                        "last4CardDigit": "6623",
                        "brand": "VISA",
                        "expiration_date": "12/27",
                        "card_on_file": "F"
                      },
                      "currency": "CLP",
                      "amount": 9990,
                      "renewal": "F",
                      "channel": "WEB",
                      "service_id": "12312312-3",
                      "charge_program": [
                        {
                          "id": "cid_2566645567e51ef2b7.76832273",
                          "charge_date": "2023-05-01",
                          "amount": "6990",
                          "status": "rechazado",
                          "description": "Cargo 1 de 3"
                        },
                        {
                          "id": "cid_2566645567e51ef2b7.76832274",
                          "charge_date": "2023-06-01",
                          "amount": "6990",
                          "status": "rechazado",
                          "description": "Cargo 2 de 3"
                        },
                        {
                          "id": "cid_2566645567e51ef2b7.76832275",
                          "charge_date": "2023-07-01",
                          "amount": "6990",
                          "status": "rechazado",
                          "description": "Cargo 3 de 3"
                        }
                      ],
                      "client": {
                        "email": "user@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "social_id": "12345678-9",
                        "phone": "56961934502"
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0e7db8615d003408d4bf"
}
```

---

# 3.3 Charge

### Objeto Charge

El objeto **cargo** corresponde a el pago realizado por el cliente en una suscripción. Cómo mínimo el cargo define un monto, fecha programada para el cargo y una descripción.

```json JSON
{
  "id": "cid_2566645567e51ef2b7.76832273",
  "charge_date": "2023-05-08",
  "amount": 9900,
  "status": "pagado",
  "description": "Cargo 1 de 3",
  "created_at": "2021-09-08 11:20:31",
  "payment": {
    "client": {
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "social_id": "12345678-9",
      "phone": "56961934502"
    },
    "commerce": {
      "commerce_id": "76123456-7",
      "name": "ACME CORP"
    },
    "order": {
      "uuid": "083613a748190d26",
      "status": "pagado",
      "created_at": "2023-05-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "2021-08-08 11:21:31",
      "auth_code": "1234",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "deposits": [
        {
          "description": "1/1",
          "installment": 9900,
          "processing_flat_fee": 0,
          "processing_fee": 117,
          "payout_amount": 9783,
          "payout_date": "2023-03-11"
        }
      ]
    }
  }
}
```

### Crear un Charge

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/charge": {
      "post": {
        "summary": "Crear un Charge",
        "description": "",
        "operationId": "crear-un-charge",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": [
                  "charge_date",
                  "amount",
                  "description",
                  "suscription_id"
                ],
                "properties": {
                  "charge_date": {
                    "type": "string",
                    "description": "Fecha en que se realizará el cargo.",
                    "format": "date"
                  },
                  "amount": {
                    "type": "number",
                    "description": "Monto a cargar",
                    "format": "float"
                  },
                  "description": {
                    "type": "string",
                    "description": "Descripción asociada al cargo."
                  },
                  "suscription_id": {
                    "type": "string",
                    "description": "Identificador de la suscripción"
                  },
                  "internal_code": {
                    "type": "string",
                    "description": "Identificador del servicio."
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"suscription_id\": \"3a4d77f2e4\",  \n  \"charge\":\n      {\n        \"id\": \"id_2566645567e51ef2b7.76832273\",\n        \"charge_date\": \"2023-05-08\",\n        \"amount\": 9900,\n        \"status\": \"pendiente\",\n        \"description\": \"Cargo 1 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription_id": {
                      "type": "string",
                      "example": "3a4d77f2e4"
                    },
                    "charge": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "id_2566645567e51ef2b7.76832273"
                        },
                        "charge_date": {
                          "type": "string",
                          "example": "2023-05-08"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9900,
                          "default": 0
                        },
                        "status": {
                          "type": "string",
                          "example": "pendiente"
                        },
                        "description": {
                          "type": "string",
                          "example": "Cargo 1 de 3"
                        },
                        "created_at": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0f2dcf8ba500571a6cba"
}
```

### Crear un Charge Online

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/charge/online": {
      "post": {
        "summary": "Crear un Charge Online",
        "description": "",
        "operationId": "crear-un-charge-online",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["amount", "description", "suscription_id"],
                "properties": {
                  "amount": {
                    "type": "number",
                    "description": "Monto a cargar",
                    "format": "float"
                  },
                  "description": {
                    "type": "string",
                    "description": "Descripción asociada al cargo."
                  },
                  "suscription_id": {
                    "type": "string",
                    "description": "Identificador de la suscripción"
                  },
                  "internal_code": {
                    "type": "string",
                    "description": "Identificador del servicio."
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"suscription_id\": \"3a4d77f2e4\",  \n  \"charge\":\n      {\n        \"id\": \"id_2566645567e51ef2b7.76832273\",\n        \"charge_date\": \"2023-05-08\",\n        \"amount\": 9900,\n        \"status\": \"pendiente\",\n        \"description\": \"Cargo 1 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription_id": {
                      "type": "string",
                      "example": "3a4d77f2e4"
                    },
                    "charge": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "id_2566645567e51ef2b7.76832273"
                        },
                        "charge_date": {
                          "type": "string",
                          "example": "2023-05-08"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9900,
                          "default": 0
                        },
                        "status": {
                          "type": "string",
                          "example": "pendiente"
                        },
                        "description": {
                          "type": "string",
                          "example": "Cargo 1 de 3"
                        },
                        "created_at": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6a0327b2f514cd4a513dacbb"
}
```

### Recuperar Charge

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/charge/{charge_id}": {
      "get": {
        "summary": "Recuperar Charge",
        "description": "",
        "operationId": "recuperar-charge",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"suscription_id\": \"3a4d77f2e4\",\n  \"charge\":\n      {\n        \"id\": \"cid_2566645567e51ef2b7.76832273\",\n        \"charge_date\": \"2023-05-08\",\n        \"amount\": 9900,\n        \"status\": \"pendiente\",\n        \"description\": \"Cargo 1 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription_id": {
                      "type": "string",
                      "example": "3a4d77f2e4"
                    },
                    "charge": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "cid_2566645567e51ef2b7.76832273"
                        },
                        "charge_date": {
                          "type": "string",
                          "example": "2023-05-08"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9900,
                          "default": 0
                        },
                        "status": {
                          "type": "string",
                          "example": "pendiente"
                        },
                        "description": {
                          "type": "string",
                          "example": "Cargo 1 de 3"
                        },
                        "created_at": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0f4962c7c5001ae12247"
}
```

### Cancelar Charge

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/charge/{charge_id}": {
      "delete": {
        "summary": "Cancelar Charge",
        "description": "",
        "operationId": "cancelar-charge",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"suscription_id\": \"3a4d77f2e4\",\n  \"charge\":\n      {\n        \"id\": \"cid_2566645567e51ef2b7.76832273\",\n        \"charge_date\": \"2023-05-08\",\n        \"amount\": 9900,\n        \"status\": \"cancelado\",\n        \"description\": \"Cargo 1 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription_id": {
                      "type": "string",
                      "example": "3a4d77f2e4"
                    },
                    "charge": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "string",
                          "example": "cid_2566645567e51ef2b7.76832273"
                        },
                        "charge_date": {
                          "type": "string",
                          "example": "2023-05-08"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 9900,
                          "default": 0
                        },
                        "status": {
                          "type": "string",
                          "example": "cancelado"
                        },
                        "description": {
                          "type": "string",
                          "example": "Cargo 1 de 3"
                        },
                        "created_at": {
                          "type": "string",
                          "example": "2021-09-08 11:20:31"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0f90317da40057e5024b"
}
```

### Reintentar Charge

Reintenta la autorización de un cobro en estado rechazado. El proceso consiste en realizar un intento de autorización diario durante tres días consecutivos. Si la transacción no es autorizada en ninguno de estos tres intentos, se considera definitivamente rechazada.

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/charge/{charge_id}/retry": {
      "get": {
        "summary": "Reintentar Charge",
        "description": "Reintenta la autorización de un cobro en estado rechazado. El proceso consiste en realizar un intento de autorización diario durante tres días consecutivos. Si la transacción no es autorizada en ninguno de estos tres intentos, se considera definitivamente rechazada.",
        "operationId": "reintentar-charge",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"OK\",\n    \"code\": 200,\n    \"message\": \"Se realiza el reintento de cobro del cargo cid_28836166df68afb3400.8234682 satisfactoriamente\"\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "message": {
                      "type": "string",
                      "example": "Se realiza el reintento de cobro del cargo cid_28836166df68afb3400.8234682 satisfactoriamente"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-081\",\n        \"message\": \"El cargo no cumple con las condiciones para realizar el reintento de cobro.\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-081"
                        },
                        "message": {
                          "type": "string",
                          "example": "El cargo no cumple con las condiciones para realizar el reintento de cobro."
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:680f90bd317a0b0012fd8595"
}
```

### Cancelar Cargos Futuros

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/charges/{suscription_id}": {
      "delete": {
        "summary": "Cancelar Cargos Futuros",
        "description": "",
        "operationId": "cancelar-cargos-futuros",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"suscription_id\": \"3a4d77f2e4\",\n  \"cancel_charges\":[{\n            \"id\": \"cid_277465401c94d7c204.11701242\",\n            \"charge_date\": \"2023-10-30\",\n            \"amount\": 9,\n            \"status\": \"cancelado\",\n            \"description\": \"Cargo 1 de 12\",\n            \"created_at\": \"2023-10-30 18:13:56\",\n            \"internal_code\": \"\"\n        },\n        {\n            \"id\": \"cid_277465401c94d97597.84080436\",\n            \"charge_date\": \"2023-11-30\",\n            \"amount\": 9,\n            \"status\": \"cancelado\",\n            \"description\": \"Cargo 2 de 12\",\n            \"created_at\": \"2023-10-30 18:13:56\",\n            \"internal_code\": \"\"\n        }\n  ]\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "suscription_id": {
                      "type": "string",
                      "example": "3a4d77f2e4"
                    },
                    "cancel_charges": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "type": "string",
                            "example": "cid_277465401c94d7c204.11701242"
                          },
                          "charge_date": {
                            "type": "string",
                            "example": "2023-10-30"
                          },
                          "amount": {
                            "type": "integer",
                            "example": 9,
                            "default": 0
                          },
                          "status": {
                            "type": "string",
                            "example": "cancelado"
                          },
                          "description": {
                            "type": "string",
                            "example": "Cargo 1 de 12"
                          },
                          "created_at": {
                            "type": "string",
                            "example": "2023-10-30 18:13:56"
                          },
                          "internal_code": {
                            "type": "string",
                            "example": ""
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:66fdaa0f6ea95c00118452fd"
}
```

### Listar Charges

En esta API se puede implementar el uso de paginación para mas detalle haz click [aquí](https://virtualpos.readme.io/reference/paginacion-para-el-listado-de-objetos)

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/suscription/{suscription_id}/charges": {
      "get": {
        "summary": "Listar Charges",
        "description": "",
        "operationId": "listar-charges",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "Clave de la API proporcionada en back-office virtualPOS.",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "La firma de los parámetros efectuada con su secret_key",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "status",
            "in": "query",
            "description": "Estado del objeto charge",
            "schema": {
              "type": "string",
              "enum": [
                "pendiente",
                "pagado",
                "cancelado",
                "procesando",
                "rechazado"
              ]
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"status\": \"OK\",\n  \"code\": 200,\n  \"pagination\": {\n     \"limit\": 1,\n     \"page\": 1,\n     \"pages\": 2,\n     \"total\": 6\n \t},\n  \"suscription_id\": \"3a4d77f2e4\",  \n  \"charges\":\n  [\n  \t{\n        \"id\": \"cid_2566645567e51ef2b7.76832273\",\n        \"charge_date\": \"2023-05-08\",\n        \"amount\": 9900,\n        \"status\": \"pendiente\",\n        \"description\": \"Cargo 1 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      },\n      {\n        \"id\": \"cid_7273457723bb3.94487839\",\n        \"charge_date\": \"2023-06-08\",\n        \"amount\": 9900,\n        \"status\": \"pendiente\",\n        \"description\": \"Cargo 2 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      },\n        {\n        \"id\": \"cid_99383327567e51ef2b8.83782272\",\n        \"charge_date\": \"2023-07-08\",\n        \"amount\": 9900,\n        \"status\": \"pendiente\",\n        \"description\": \"Cargo 3 de 3\",\n        \"created_at\": \"2021-09-08 11:20:31\"\n      }\n    ]\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "OK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 200,
                      "default": 0
                    },
                    "pagination": {
                      "type": "object",
                      "properties": {
                        "limit": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "page": {
                          "type": "integer",
                          "example": 1,
                          "default": 0
                        },
                        "pages": {
                          "type": "integer",
                          "example": 2,
                          "default": 0
                        },
                        "total": {
                          "type": "integer",
                          "example": 6,
                          "default": 0
                        }
                      }
                    },
                    "suscription_id": {
                      "type": "string",
                      "example": "3a4d77f2e4"
                    },
                    "charges": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "type": "string",
                            "example": "cid_2566645567e51ef2b7.76832273"
                          },
                          "charge_date": {
                            "type": "string",
                            "example": "2023-05-08"
                          },
                          "amount": {
                            "type": "integer",
                            "example": 9900,
                            "default": 0
                          },
                          "status": {
                            "type": "string",
                            "example": "pendiente"
                          },
                          "description": {
                            "type": "string",
                            "example": "Cargo 1 de 3"
                          },
                          "created_at": {
                            "type": "string",
                            "example": "2021-09-08 11:20:31"
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:646d0fb46425b30020986678"
}
```

---

# 3.4 Client

### Objeto Client

El objeto **Client** representa al cliente final asociado a pagos y suscripciones de un comercio (owner).\
Contiene los datos de identificación y contacto necesarios para gestionar pagos, cobros recurrentes y comunicaciones.

```json
{
  "client": {
    "uuid": "cli_0316825ee546f8d9",
    "type": "PERSONA",
    "first_name": "John",
    "last_name": "Doe",
    "social_id_type": 1,
    "social_id": "18271783-1",
    "email": "john@doe.cl",
    "phone_number": "912345678",
    "status": "ACTIVO",
    "gender_id": "Masculino",
    "birth_date": "1989-12-01",
    "created": "2025-05-15 09:38:28"
  }
}
```

| Atributo         | Tipo                | Requerido           | Descripción                                                                                                     |
| ---------------- | ------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------- |
| `uuid`           | string              | Solo respuesta      | Identificador único del cliente. Formato interno `cli_<alfanumérico>`.                                          |
| `status`         | enum                | Opcional (`ACTIVO`) | Estado del cliente dentro del comercio. Valores: `ACTIVO`, `BLOQUEADO`.                                         |
| `type`           | enum                | **Sí**              | Tipo de cliente. Valores: `PERSONA`, `EMPRESA`.                                                                 |
| `first_name`     | string              | **Sí**              | Nombre del cliente. Para `EMPRESA`, corresponde a la razón social.                                              |
| `last_name`      | string              | Condicional         | Requerido cuando `type = PERSONA`. Para `EMPRESA` puede enviarse vacío.                                         |
| `email`          | string              | **Sí**              | Correo electrónico del cliente. Debe tener formato válido y es único por comercio.                              |
| `phone_number`   | string              | No                  | Teléfono de contacto. Campo opcional.                                                                           |
| `social_id_type` | enum                | No                  | Tipo de documento de identificación. Valores: `1` para `RUT`,`2` para `DNI`. Si es `RUT`, se valida el formato. |
| `social_id`      | string              | No                  | Identificador del documento (RUT o DNI). Debe ser único por comercio.                                           |
| `birth_date`     | date (`YYYY-MM-DD`) | No                  | Fecha de nacimiento del cliente.                                                                                |
| `gender_id`      | enum/string         | No                  | Género del cliente. Valores esperados: `1` para `Masculino`, `2` para `Femenino`, `4` para `Otro`.              |
| `created`        | datetime            | Solo respuesta      | Fecha de creación del registro.                                                                                 |

### Crear un Client

Permite crear un nuevo cliente asociado al comercio autenticado.

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/client": {
      "post": {
        "summary": "Crear un Client",
        "description": "Permite crear un nuevo cliente asociado al comercio autenticado.",
        "operationId": "crear-un-client",
        "parameters": [
          {
            "name": "Content-Type",
            "in": "header",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["type", "first_name", "email"],
                "properties": {
                  "type": {
                    "type": "string",
                    "description": "PERSONA o EMPRESA",
                    "enum": ["'PERSONA'", "'EMPRESA'"]
                  },
                  "social_id": {
                    "type": "string",
                    "description": "Número de documento asociado a social_id_type. Debe ser único."
                  },
                  "first_name": {
                    "type": "string",
                    "description": "Nombre del cliente (o razón social si es type = EMPRESA)"
                  },
                  "last_name": {
                    "type": "string",
                    "description": "Obligatorio cuando es type = PERSONA. Opcional para EMPRESA"
                  },
                  "email": {
                    "type": "string",
                    "description": "Email del cliente. Debe ser único y con formato válido"
                  },
                  "phone_number": {
                    "type": "string",
                    "description": "Teléfono del cliente."
                  },
                  "social_id_type": {
                    "type": "string",
                    "description": "1 si es RUT o 2 si es DNI. Si es RUT se valida el formato."
                  },
                  "birth_date": {
                    "type": "string",
                    "description": "Fecha de nacimiento YYYY-MMDD",
                    "format": "date"
                  },
                  "gender_id": {
                    "type": "string",
                    "description": "1 para Masculino, 2 Femenino o 4 para Otro",
                    "enum": ["'Masculino'", "'Femenino'", "'Otro'"]
                  },
                  "private_note": {
                    "type": "string",
                    "description": "Nota interna del comercio."
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"client\": {\n    \"uuid\": \"cli_00183af742e91dc3\",\n    \"status\": \"ACTIVO\",\n    \"type\": \"PERSONA\",\n    \"first_name\": \"John\",\n    \"last_name\": \"Doe\",\n    \"email\": \"user@example.com\",\n    \"phone_number\": \"56961934502\",\n    \"social_id_type\": \"RUT\",\n    \"social_id\": \"12345678-9\",\n    \"birth_date\": \"1990-01-01\",\n    \"gender_id\": \"Masculino\",\n    \"private_note\": \"Cliente recurrente de suscripciones de seguros.\",\n    \"created\": \"2025-01-08 11:20:31\",\n    \"updated\": \"2025-01-08 11:20:31\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "client": {
                      "type": "object",
                      "properties": {
                        "uuid": {
                          "type": "string",
                          "example": "cli_00183af742e91dc3"
                        },
                        "status": {
                          "type": "string",
                          "example": "ACTIVO"
                        },
                        "type": {
                          "type": "string",
                          "example": "PERSONA"
                        },
                        "first_name": {
                          "type": "string",
                          "example": "John"
                        },
                        "last_name": {
                          "type": "string",
                          "example": "Doe"
                        },
                        "email": {
                          "type": "string",
                          "example": "user@example.com"
                        },
                        "phone_number": {
                          "type": "string",
                          "example": "56961934502"
                        },
                        "social_id_type": {
                          "type": "string",
                          "example": "RUT"
                        },
                        "social_id": {
                          "type": "string",
                          "example": "12345678-9"
                        },
                        "birth_date": {
                          "type": "string",
                          "example": "1990-01-01"
                        },
                        "gender_id": {
                          "type": "string",
                          "example": "Masculino"
                        },
                        "private_note": {
                          "type": "string",
                          "example": "Cliente recurrente de suscripciones de seguros."
                        },
                        "created": {
                          "type": "string",
                          "example": "2025-01-08 11:20:31"
                        },
                        "updated": {
                          "type": "string",
                          "example": "2025-01-08 11:20:31"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-###\",\n        \"message\": \"detalle del error\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6914a5db68d5615329d900b5"
}
```

### Recuperar un objeto Client

Permite recuperar la información de un cliente específico mediante su **uuid**.

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/client/{uuid}": {
      "get": {
        "summary": "Recuperar un objeto Client",
        "description": "Permite recuperar la información de un cliente específico mediante su **uuid**.",
        "operationId": "recuperar-un-objeto-client",
        "parameters": [
          {
            "name": "Content-Type",
            "in": "header",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "uuid",
            "in": "query",
            "description": "Identificador único del cliente.",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"client\": {\n    \"uuid\": \"cli_00183af742e91dc3\",\n    \"status\": \"ACTIVO\",\n    \"type\": \"PERSONA\",\n    \"first_name\": \"John\",\n    \"last_name\": \"Doe\",\n    \"email\": \"user@example.com\",\n    \"phone_number\": \"56961934502\",\n    \"social_id_type\": \"RUT\",\n    \"social_id\": \"12345678-9\",\n    \"birth_date\": \"1990-01-01\",\n    \"gender_id\": \"Masculino\",\n    \"private_note\": \"Cliente recurrente de suscripciones de seguros.\",\n    \"created\": \"2025-01-08 11:20:31\",\n    \"updated\": \"2025-01-10 09:15:00\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "client": {
                      "type": "object",
                      "properties": {
                        "uuid": {
                          "type": "string",
                          "example": "cli_00183af742e91dc3"
                        },
                        "status": {
                          "type": "string",
                          "example": "ACTIVO"
                        },
                        "type": {
                          "type": "string",
                          "example": "PERSONA"
                        },
                        "first_name": {
                          "type": "string",
                          "example": "John"
                        },
                        "last_name": {
                          "type": "string",
                          "example": "Doe"
                        },
                        "email": {
                          "type": "string",
                          "example": "user@example.com"
                        },
                        "phone_number": {
                          "type": "string",
                          "example": "56961934502"
                        },
                        "social_id_type": {
                          "type": "string",
                          "example": "RUT"
                        },
                        "social_id": {
                          "type": "string",
                          "example": "12345678-9"
                        },
                        "birth_date": {
                          "type": "string",
                          "example": "1990-01-01"
                        },
                        "gender_id": {
                          "type": "string",
                          "example": "Masculino"
                        },
                        "private_note": {
                          "type": "string",
                          "example": "Cliente recurrente de suscripciones de seguros."
                        },
                        "created": {
                          "type": "string",
                          "example": "2025-01-08 11:20:31"
                        },
                        "updated": {
                          "type": "string",
                          "example": "2025-01-10 09:15:00"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-###\",\n        \"message\": \"detalle del error\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6914d80d4e9c00566120db12"
}
```

### Listar objetos Client

Permite recuperar la información de varios clientes mediante parámetros

El orden por defecto es **created** descendente (clientes más recientes primero).

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/clients": {
      "get": {
        "summary": "Listar objetos Client",
        "description": "Permite recuperar la información de varios clientes mediante parámetros",
        "operationId": "listar-objetos-client",
        "parameters": [
          {
            "name": "Content-Type",
            "in": "header",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "page",
            "in": "query",
            "description": "Página a recuperar.",
            "schema": {
              "type": "integer",
              "format": "int32",
              "default": 1
            }
          },
          {
            "name": "limit",
            "in": "query",
            "description": "Cantidad de registros por página.",
            "schema": {
              "type": "integer",
              "format": "int32",
              "default": 100
            }
          },
          {
            "name": "status",
            "in": "query",
            "description": "Filtra por estado del cliente: ACTIVO, BLOQUEADO.",
            "schema": {
              "type": "string",
              "enum": ["'ACTIVO'", "'BLOQUEADO'"],
              "default": "all"
            }
          },
          {
            "name": "type",
            "in": "query",
            "description": "Filtra por tipo de cliente: PERSONA, EMPRESA.",
            "schema": {
              "type": "string",
              "enum": ["'PERSONA'", "'EMPRESA'"]
            }
          },
          {
            "name": "social_id",
            "in": "query",
            "description": "Filtra por documento.",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "email",
            "in": "query",
            "description": "Fitra por email.",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "created_from",
            "in": "query",
            "description": "Filtra clientes creados desde esta fecha (inclusive).",
            "schema": {
              "type": "string",
              "format": "date"
            }
          },
          {
            "name": "created_to",
            "in": "query",
            "description": "Filtra clientes creados hasta esta fecha (inclusive).",
            "schema": {
              "type": "string",
              "format": "date"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"clients\": [\n    {\n      \"uuid\": \"cli_00183af742e91dc3\",\n      \"status\": \"ACTIVO\",\n      \"type\": \"PERSONA\",\n      \"first_name\": \"John\",\n      \"last_name\": \"Doe\",\n      \"email\": \"user@example.com\",\n      \"phone_number\": \"56961934502\",\n      \"social_id_type\": \"RUT\",\n      \"social_id\": \"12345678-9\",\n      \"birth_date\": \"1990-01-01\",\n      \"gender_id\": \"Masculino\",\n      \"created\": \"2025-01-08 11:20:31\",\n      \"updated\": \"2025-01-10 09:15:00\"\n    },\n    {\n      \"uuid\": \"cli_00183af742e91dc4\",\n      \"status\": \"BLOQUEADO\",\n      \"type\": \"EMPRESA\",\n      \"first_name\": \"Acme S.A.\",\n      \"last_name\": \"\",\n      \"email\": \"user2@example.com\",\n      \"phone_number\": \"56223456789\",\n      \"social_id_type\": \"RUT\",\n      \"social_id\": \"76432154-2\",\n      \"birth_date\": “”,\n      \"gender_id\": “”,\n      \"created\": \"2025-01-01 09:00:00\",\n      \"updated\": \"2025-01-05 10:00:00\"\n    }\n  ],\n  \"page\": 1,\n  \"limit\": 100,\n  \"total\": 2\n}\n"
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-###\",\n        \"message\": \"detalle del error\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6914d9d4b1799a276dd0de9a"
}
```

### Actualizar un objeto Client

Permite actualizar los datos de un cliente existente. Solo se actualizan los campos enviados en el body; los demás se mantienen.

##### Reglas de actualización

- No se pueden modificar: `uuid`, `created`.
- `updated` es gestionado automáticamente por el sistema.
- Se aplican las mismas reglas de validación que en **Crear un objeto Client** para cualquier campo enviado:
  - Formato de email.
  - Unicidad de `email` y `social_id`.
  - Reglas condicionales de `last_name`, etc.

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "VirtualPOS",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://api.virtualpos.cl"
    }
  ],
  "security": [{}],
  "paths": {
    "/v3/client/{uuid}": {
      "put": {
        "summary": "Actualizar un objeto Client",
        "description": "Permite actualizar los datos de un cliente existente. Solo se actualizan los campos enviados en el body; los demás se mantienen.",
        "operationId": "actualizar-un-objeto-client",
        "parameters": [
          {
            "name": "Content-Type",
            "in": "header",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "uuid",
            "in": "query",
            "description": "Identificador único del cliente a actualizar.",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"client\": {\n    \"uuid\": \"cli_00183af742e91dc3\",\n    \"status\": \"BLOQUEADO\",\n    \"type\": \"PERSONA\",\n    \"first_name\": \"John\",\n    \"last_name\": \"Doe\",\n    \"email\": \"user@example.com\",\n    \"phone_number\": \"56977777777\",\n    \"social_id_type\": \"RUT\",\n    \"social_id\": \"12345678-9\",\n    \"birth_date\": \"1990-01-01\",\n    \"gender_id\": \"Masculino\",\n    \"private_note\": \"Cliente bloqueado por mora.\",\n    \"created\": \"2025-01-08 11:20:31\",\n    \"updated\": \"2025-01-15 10:30:00\"\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "client": {
                      "type": "object",
                      "properties": {
                        "uuid": {
                          "type": "string",
                          "example": "cli_00183af742e91dc3"
                        },
                        "status": {
                          "type": "string",
                          "example": "BLOQUEADO"
                        },
                        "type": {
                          "type": "string",
                          "example": "PERSONA"
                        },
                        "first_name": {
                          "type": "string",
                          "example": "John"
                        },
                        "last_name": {
                          "type": "string",
                          "example": "Doe"
                        },
                        "email": {
                          "type": "string",
                          "example": "user@example.com"
                        },
                        "phone_number": {
                          "type": "string",
                          "example": "56977777777"
                        },
                        "social_id_type": {
                          "type": "string",
                          "example": "RUT"
                        },
                        "social_id": {
                          "type": "string",
                          "example": "12345678-9"
                        },
                        "birth_date": {
                          "type": "string",
                          "example": "1990-01-01"
                        },
                        "gender_id": {
                          "type": "string",
                          "example": "Masculino"
                        },
                        "private_note": {
                          "type": "string",
                          "example": "Cliente bloqueado por mora."
                        },
                        "created": {
                          "type": "string",
                          "example": "2025-01-08 11:20:31"
                        },
                        "updated": {
                          "type": "string",
                          "example": "2025-01-15 10:30:00"
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n    \"status\": \"NOK\",\n    \"code\": 400,\n    \"error\": {\n        \"error_code\": \"E-###\",\n        \"message\": \"detalle del error\",\n        \"doc_url\": \"https://virtualpos.readme.io/reference/objeto-error\"\n    }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": {
                      "type": "string",
                      "example": "NOK"
                    },
                    "code": {
                      "type": "integer",
                      "example": 400,
                      "default": 0
                    },
                    "error": {
                      "type": "object",
                      "properties": {
                        "error_code": {
                          "type": "string",
                          "example": "E-###"
                        },
                        "message": {
                          "type": "string",
                          "example": "detalle del error"
                        },
                        "doc_url": {
                          "type": "string",
                          "example": "https://virtualpos.readme.io/reference/objeto-error"
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "deprecated": false,
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {},
              "examples": {
                "Request Example": {
                  "value": {
                    "client": {
                      "status": "BLOQUEADO",
                      "phone_number": "56977777777",
                      "private_note": "Cliente bloqueado por mora.",
                      "email": "user@example.com"
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "63d857da7710f60012144a5b:6914db96f9a228b3db3db167"
}
```

---

# 4. Payout

### Introducción a Payout

Nuestro servicio de **payout**, permite distribuir fondos de manera eficiente y segura en el formato de "transferencia electrónica de fondos" para pagos a proveedores, empleados, devoluciones, reembolsos, etc. El proceso de **payout** implica la transferencia de fondos desde una cuenta corriente a múltiples destinatarios.

### Seguridad

Para utilizar el servicio Payout de Virtualpos, cada comercio debe implementar los siguientes mecanismos de seguridad:

- Firma de mensajes con el estándar JWT
- Firma de mensaje con mTLS
- Informar el set de direcciones IPs desde donde se harán los requerimientos de Payout.

### Autenticación y firma

La API de Payout de Virtualpos opera a través de una API KEY y SECRET KEY, este conjunto de llaves son únicas para cada cuenta y ambiente (Sandbox o producción), y serán entregadas durante la ejecución del proyecto de integración.

La API KEY debe ser enviada en cada requerimiento en el encabezado **Authorization**.

Cada requerimiento debe ser firmado, y la firma debe ser incluida también en el encabezado (header del mensaje HTTP) **Signature**

La firma se genera utilizando la SECRET KEY y JSON Web Token (JWT). JWT es un estándar abierto (RFC 7519) que define una forma compacta y autónoma de transmitir información de forma segura entre las partes como un objeto JSON. Esta información se puede verificar y confiar porque está firmada digitalmente. Más información de este estándar lo puedes encontrar en <https://jwt.io/>

Para los métodos de:

1. Crear una nueva instrucción de payout
2. Consultar estado de payout por id
3. Consultar estado de payout por merchant id

El Signature debe estar construido como un diccionario JSON con la siguiente estructura:

```json
{
  "api_key": "yourApiKey",
  "tef": {
    "merchant_id": "tef-XXXXX-XX",
    "message": "Devolución de compra OC XXX",
    "amount": 12500,
    "recipient": {
      "rut": "1111111-1",
      "name": "John Doe",
      "email": "johndoe@virtualpos.cl"
    },
    "bank": {
      "sbif_code": "111",
      "account_number": "11111111"
    }
  }
}
```

Asegúrese de proporcionar valores válidos y precisos para cada clave dentro del diccionario.

##### Descripción de las claves

- **api_key:** Su clave única de API para la autenticación.
  - **tef:** Un objeto que contiene detalles específicos de la transacción.
    - **merchant_id:** Identificación única del comerciante.
    - **message:** Mensaje descriptivo asociado con la transacción.
    - **amount:** Monto de la transacción.
    - **recipient:** Detalles del destinatario.
      - **rut:** RUT del destinatario, este debe ser ingresado sin puntos.
      - **name:** Nombre del destinatario.
      - **email:** Correo electrónico del destinatario.
    - **bank:** Detalles bancarios.
      - **sbif_code:** Código SBIF del banco.
      - **account_number:** Número de cuenta bancaria.

Un ejemplo del Signature correctamente estructurado se presenta arriba. Asegúrese de seguir esta estructura al construir su propia firma digital para cada solicitud a la API

### Webhook

Para completar el flujo de payout, es obligación por parte del comercio implementar un **WEBHOOK** donde Virtualpos notificará cada una de las **transferencias de fondo** procesadas, con esta información el comercio procederá a actualizar sus sistemas.

La notificación será efectuada por medio de un request HTTPS/POST e informando un objeto payout en el cuerpo del request.

Importante: El mensaje incorpora la firma en el atributo **Signature** en el **header**, la cual debe ser validada para cada transacción. El webhook utiliza una firma hash de tipo hmac cifrada en sha256, el cuerpo del mensaje se debe utilizar para cifrarse con la clave secreta.

```json
{
  "status": "OK",
  "code": 200,
  "payout": {
    "id": "po_59653837fa4c43d",
    "status": "PROCESSING",
    "create_at": "2023-10-24 06:10:42",
    "update_at": "2023-10-24 09:10:46",
    "tef": {
      "merchant_id": "tef-12801-64",
      "message": "Devoluci\u00f3n de compra OC 873",
      "amount": 12500,
      "recipient": {
        "rut": "18123328-1",
        "name": "John Doe",
        "email": "johndoe@virtualpos.cl"
      },
      "bank": {
        "sbif_code": "037",
        "account_number": "786345987"
      }
    }
  }
}
```

### Objeto Payout

El objeto **Payout** representa una solicitud de transferencia electrónica de fondos, y contiene los atributos para procesar la transacción y su resultado. El objeto Payout puede tener los siguientes estados dependiendo de la etapa en la que se encuentre:

| Status     | Descripción                                                                                                                                        |
| :--------- | :------------------------------------------------------------------------------------------------------------------------------------------------- |
| PENDING    | Estado inicial, se ha creado un requerimiento y este se encuentra en espera del procesamiento de la transferencia electrónica de fondos.           |
| PROCESSING | Estado transitorio, indica que el requerimiento está siendo procesado, con espera de resultados: COMPLETED o FAILED.                               |
| COMPLETED  | Estado final, la transferencia electrónica de fondos se realizó correctamente.                                                                     |
| FAILED     | Estado final, no se pudo realizar la transferencia electrónica de fondos, este estado se complementa con un código que indica el motivo del error. |

```json json
{
  "id": "po_406538224cd1628",
  "status": "PENDING",
  "created_at": "2023-10-12 10:50:11",
  "updated_at": "2023-10-12 11:10:50",
  "tef": {
    "merchant_id": "tef-12801-01",
    "message": "Devolución de compra OC 873",
    "amount": 12500,
    "recipient": {
      "rut": "18123328-1",
      "name": "John Doe",
      "email": "johndoe@virtualpos.cl"
    },
    "bank": {
      "sbif_code": "037",
      "account_number": "786345987"
    }
  }
}
```

### Crear una nueva instrucción de payout

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Payout API",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://payout-api.virtualpos.cl"
    }
  ],
  "components": {
    "securitySchemes": {
      "sec0": {
        "type": "apiKey",
        "in": "query",
        "name": "api_key"
      }
    }
  },
  "security": [
    {
      "sec0": []
    }
  ],
  "paths": {
    "/v3/payout": {
      "post": {
        "summary": "Crear una nueva instrucción de payout",
        "description": "",
        "operationId": "crear-una-nueva-instrucción-de-payout",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Content-Type",
            "in": "header",
            "schema": {
              "type": "string",
              "default": "application/json"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["RAW_BODY"],
                "properties": {
                  "RAW_BODY": {
                    "type": "object",
                    "properties": {}
                  }
                }
              },
              "examples": {
                "Request Example": {
                  "value": {
                    "merchant_id": "tef-12801-01",
                    "message": "Devolución de compra OC 873",
                    "amount": 12500,
                    "recipient": {
                      "rut": "18123328-1",
                      "name": "John Doe",
                      "email": "johndoe@virtualpos.cl"
                    },
                    "bank": {
                      "sbif_code": "037",
                      "account_number": "786345987"
                    }
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"id\": \"po_406538224cd1628\",\n  \"status\": \"pending\",\n  \"created_at\": \"2023-10-12 10:50:11\",\n  \"updated_at\": \"2023-10-12 11:10:50\",\n  \"tef\": {\n    \"merchant_id\": \"tef-12801-01\",\n    \"message\": \"Devolución de compra OC 873\",\n    \"amount\": 12500,\n    \"recipient\": {\n      \"rut\": \"18123328-1\",\n      \"name\": \"John Doe\",\n      \"email\": \"johndoe@virtualpos.cl\"\n    },\n    \"bank\": {\n      \"sbif_code\": \"037\",\n      \"account_number\": \"786345987\"\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "po_406538224cd1628"
                    },
                    "status": {
                      "type": "string",
                      "example": "pending"
                    },
                    "created_at": {
                      "type": "string",
                      "example": "2023-10-12 10:50:11"
                    },
                    "updated_at": {
                      "type": "string",
                      "example": "2023-10-12 11:10:50"
                    },
                    "tef": {
                      "type": "object",
                      "properties": {
                        "merchant_id": {
                          "type": "string",
                          "example": "tef-12801-01"
                        },
                        "message": {
                          "type": "string",
                          "example": "Devolución de compra OC 873"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 12500,
                          "default": 0
                        },
                        "recipient": {
                          "type": "object",
                          "properties": {
                            "rut": {
                              "type": "string",
                              "example": "18123328-1"
                            },
                            "name": {
                              "type": "string",
                              "example": "John Doe"
                            },
                            "email": {
                              "type": "string",
                              "example": "johndoe@virtualpos.cl"
                            }
                          }
                        },
                        "bank": {
                          "type": "object",
                          "properties": {
                            "sbif_code": {
                              "type": "string",
                              "example": "037"
                            },
                            "account_number": {
                              "type": "string",
                              "example": "786345987"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "658c8a4d903c4b0010293746:652942be9fe9ad002e9c1751"
}
```

### Obtener saldo disponible

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Payout API",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://payout-api.virtualpos.cl"
    }
  ],
  "components": {
    "securitySchemes": {
      "sec0": {
        "type": "apiKey",
        "in": "query",
        "name": "api_key"
      }
    }
  },
  "security": [
    {
      "sec0": []
    }
  ],
  "paths": {
    "/v3/payout/account/balance": {
      "get": {
        "summary": "Obtener saldo disponible",
        "description": "",
        "operationId": "obtener-saldo-disponible",
        "parameters": [
          {
            "name": "Authentication",
            "in": "header",
            "description": "API KEY del comercio",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"balance\": 1000000\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "balance": {
                      "type": "integer",
                      "example": 1000000,
                      "default": 0
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "658c8a4d903c4b0010293746:6529437c75ae49005d475583"
}
```

### Consultar estado de payout por id

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Payout API",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://payout-api.virtualpos.cl"
    }
  ],
  "components": {
    "securitySchemes": {
      "sec0": {
        "type": "apiKey",
        "in": "query",
        "name": "api_key"
      }
    }
  },
  "security": [
    {
      "sec0": []
    }
  ],
  "paths": {
    "/v3/payout/{payout_id}": {
      "get": {
        "summary": "Consultar estado de payout por id",
        "description": "",
        "operationId": "consultar-estado-de-payout",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"id\": \"po_406538224cd1628\",\n  \"status\": \"pending\",\n  \"errorType\": \"\",\n  \"created_at\": \"2023-10-12 10:50:11\",\n  \"updated_at\": \"2023-10-12 11:10:50\",\n  \"tef\": {\n    \"merchant_id\": \"tef-12801-01\",\n    \"message\": \"Devolución de compra OC 873\",\n    \"amount\": 12500,\n    \"recipient\": {\n      \"rut\": \"18123328-1\",\n      \"name\": \"John Doe\",\n      \"email\": \"johndoe@virtualpos.cl\"\n    },\n    \"bank\": {\n      \"sbif_code\": \"037\",\n      \"account_number\": \"786345987\"\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "po_406538224cd1628"
                    },
                    "status": {
                      "type": "string",
                      "example": "pending"
                    },
                    "errorType": {
                      "type": "string",
                      "example": ""
                    },
                    "created_at": {
                      "type": "string",
                      "example": "2023-10-12 10:50:11"
                    },
                    "updated_at": {
                      "type": "string",
                      "example": "2023-10-12 11:10:50"
                    },
                    "tef": {
                      "type": "object",
                      "properties": {
                        "merchant_id": {
                          "type": "string",
                          "example": "tef-12801-01"
                        },
                        "message": {
                          "type": "string",
                          "example": "Devolución de compra OC 873"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 12500,
                          "default": 0
                        },
                        "recipient": {
                          "type": "object",
                          "properties": {
                            "rut": {
                              "type": "string",
                              "example": "18123328-1"
                            },
                            "name": {
                              "type": "string",
                              "example": "John Doe"
                            },
                            "email": {
                              "type": "string",
                              "example": "johndoe@virtualpos.cl"
                            }
                          }
                        },
                        "bank": {
                          "type": "object",
                          "properties": {
                            "sbif_code": {
                              "type": "string",
                              "example": "037"
                            },
                            "account_number": {
                              "type": "string",
                              "example": "786345987"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "658c8a4d903c4b0010293746:652943ffc7bd96001e92c208"
}
```

### Consultar estado de payout por merchant id

### OpenAPI definition

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Payout API",
    "version": "3.0"
  },
  "servers": [
    {
      "url": "https://payout-api.virtualpos.cl"
    }
  ],
  "components": {
    "securitySchemes": {
      "sec0": {
        "type": "apiKey",
        "in": "query",
        "name": "api_key"
      }
    }
  },
  "security": [
    {
      "sec0": []
    }
  ],
  "paths": {
    "/v3/payout/merchant/{merchant_id}": {
      "get": {
        "summary": "Consultar estado de payout por merchant id",
        "description": "",
        "operationId": "consultar-estado-de-payout-por-id-copy",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API KEY del comercio",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "Signature",
            "in": "header",
            "description": "Firma del mensaje",
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"id\": \"po_406538224cd1628\",\n  \"status\": \"pending\",\n  \"errorType\": \"\",\n  \"created_at\": \"2023-10-12 10:50:11\",\n  \"updated_at\": \"2023-10-12 11:10:50\",\n  \"tef\": {\n    \"merchant_id\": \"tef-12801-01\",\n    \"message\": \"Devolución de compra OC 873\",\n    \"amount\": 12500,\n    \"recipient\": {\n      \"rut\": \"18123328-1\",\n      \"name\": \"John Doe\",\n      \"email\": \"johndoe@virtualpos.cl\"\n    },\n    \"bank\": {\n      \"sbif_code\": \"037\",\n      \"account_number\": \"786345987\"\n    }\n  }\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "po_406538224cd1628"
                    },
                    "status": {
                      "type": "string",
                      "example": "pending"
                    },
                    "errorType": {
                      "type": "string",
                      "example": ""
                    },
                    "created_at": {
                      "type": "string",
                      "example": "2023-10-12 10:50:11"
                    },
                    "updated_at": {
                      "type": "string",
                      "example": "2023-10-12 11:10:50"
                    },
                    "tef": {
                      "type": "object",
                      "properties": {
                        "merchant_id": {
                          "type": "string",
                          "example": "tef-12801-01"
                        },
                        "message": {
                          "type": "string",
                          "example": "Devolución de compra OC 873"
                        },
                        "amount": {
                          "type": "integer",
                          "example": 12500,
                          "default": 0
                        },
                        "recipient": {
                          "type": "object",
                          "properties": {
                            "rut": {
                              "type": "string",
                              "example": "18123328-1"
                            },
                            "name": {
                              "type": "string",
                              "example": "John Doe"
                            },
                            "email": {
                              "type": "string",
                              "example": "johndoe@virtualpos.cl"
                            }
                          }
                        },
                        "bank": {
                          "type": "object",
                          "properties": {
                            "sbif_code": {
                              "type": "string",
                              "example": "037"
                            },
                            "account_number": {
                              "type": "string",
                              "example": "786345987"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true,
  "_id": "658c8a4d903c4b0010293746:65770159822ef206fe845456"
}
```

### Lista de bancos con códigos SBIF

| Código SBIF | Banco                                 |
| :---------- | :------------------------------------ |
| 001         | Banco de Chile                        |
| 009         | Banco Internacional                   |
| 012         | Banco del Estado                      |
| 014         | Scotiabank, BancoDesarrollo           |
| 016         | Banco BCI / Mach, TBanc, Banco Nova   |
| 028         | Banco BICE                            |
| 031         | Banco HSBC                            |
| 037         | Banco Santander, Banefe               |
| 039         | Banco Itaú Corpbanca, Banco Corpbanca |
| 049         | Banco Security                        |
| 051         | Banco Falabella                       |
| 053         | Banco Ripley                          |
| 055         | Banco Consorcio                       |
| 504         | Scotiabank Azul BBVA                  |
| 672         | Coopeuch                              |
| 729         | Prepago Los Héroes                    |
| 730         | Tenpo                                 |
| 732         | Prepago Los Andes                     |
| 738         | Global 66                             |
| 875         | MercadoPago                           |

### Errores

El objeto **Error** esta conformado por los siguientes elementos:

| Elemento   | Descripción                                                   |
| :--------- | :------------------------------------------------------------ |
| error_code | Es el código asignado a un error en particular.               |
| message    | Mensaje con detalle del error ocurrido.                       |
| doc_url    | Url de documentación para saber mas sobre el error detectado. |

```Text json
{
"error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/payout-error-detail"
  }
}
```

#### Lista de códigos de errores:

| Error code | Mensaje                                                                                                        |
| :--------- | :------------------------------------------------------------------------------------------------------------- |
| E-001      | Error en el parámetro Authorization.                                                                           |
| E-002      | Error en el parámetro Signature.                                                                               |
| E-003      | Error en el parámetro merchant_id.                                                                             |
| E-004      | Error en el parámetro message.                                                                                 |
| E-005      | Error en el parámetro amount.                                                                                  |
| E-006      | Error en el parámetro rut.                                                                                     |
| E-007      | Error en el parámetro name.                                                                                    |
| E-008      | Error en el parámetro email.                                                                                   |
| E-009      | Error en el parámetro sbif_code.                                                                               |
| E-010      | Error en el parámetro account_number.                                                                          |
| E-011      | Error en el parámetro amount, debe ser numérico.                                                               |
| E-012      | Error en el parámetro amount, debe ser número entero mayor o igual a.                                          |
| E-013      | Error en el parámetro amount, debe ser número entero menor o igual a.                                          |
| E-014      | Error en el parámetro email, no cumple con formato.                                                            |
| E-015      | Error, no existe el comercio asociado a la api key.                                                            |
| E-016      | La verificación de la firma es incorrecta.                                                                     |
| E-017      | Firma es incorrecta.                                                                                           |
| E-018      | Parámetros en la firma tienen errores.                                                                         |
| E-019      | merchant_id duplicado.                                                                                         |
| E-020      | Error, Ha sobrepasado el número máximo de transacciones permitidas para 1 dia.                                 |
| E-021      | Error, Ha sobrepasado el monto máximo de transacciones permitidas para 1 dia.                                  |
| E-022      | Error al generar la TEF.                                                                                       |
| E-022-001  | Error al generar la TEF - El monto solicitado para realizar la transferencia supera el monto máximo permitido. |
| E-022-002  | Error al generar la TEF - El código de banco, no se encuentra registrado o permitido para operar.              |
| E-022-003  | Error al generar la TEF - El RUT ingresado no tiene un formato válido.                                         |
| E-022-004  | Error al generar la TEF - Saldo insuficiente para realizar la transferencia.                                   |
| E-022-005  | Error al generar la TEF - La cuenta bancaria proporcionada es inválida.                                        |
| E-023      | Error en el parámetro payout_id.                                                                               |
| E-024      | Error al obtener el estatus de la TEF.                                                                         |
| E-025      | Error al obtener la TEF.                                                                                       |
| E-026      | No existe payout                                                                                               |
| E-027      | Error al obtener el balance.                                                                                   |

#### Listado de tipos de errores por transacciones fallidas

| Error Type                            | Descripción                                                                                                                                |
| :------------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------- |
| ERROR_ACCOUNT_INCORRECT               | La cuenta proporcionada no es válida o no existe.                                                                                          |
| ERROR_ACCOUNT_NOT_ACCEPT_TRANSFERS    | La cuenta especificada no acepta transferencias.                                                                                           |
| ERROR_ACCOUNT_CLOSED                  | La cuenta se encuentra cerrada o inactiva.                                                                                                 |
| ERROR_AMOUNT_INCORRECT                | El monto especificado es incorrecto o inválido                                                                                             |
| ERROR_BENEFICIARY_DOCUMENT_ID_INVALID | El documento de identificación del beneficiario no es válido.                                                                              |
| ERROR_INVALID_REQUEST_BODY            | Indica un problema con el contenido de la solicitud, como un formato incorrecto o datos faltantes.                                         |
| NETWORK_SERVICE_UNAVAILABLE           | Servicio de red no disponible. No se puede completar la operación debido a problemas de conectividad.                                      |
| INSUFFICIENT_USER_BALANCE             | Saldo insuficiente en la cuenta del usuario para realizar la transacción.                                                                  |
| ERROR_OTHER                           | Otro error no clasificado. Puede ser necesario revisar los detalles adicionales para obtener más información sobre el problema específico. |

---

# 5. Quick Checkout

### Qué es Quick Checkout

Quick Checkout es un nuevo producto actualmente en desarrollo por Virtualpos que ofrece una experiencia de checkout completa, a través de módulos UI y frontend en formato plug\&play para mejorar la experiencia de usuario y aumentar la conversión de ventas.

Este ofrece la ventaja de que cada módulo de pago puede ser habilitado y configurado por el comercio, lo que implica alta flexibilidad de métodos de pago para los clientes pagadores.

Además resuelve la autorización del pago directamente en el sitio web del comercio, sin redirect del pagador, lo cual mejora la experiencia y permite el pago sin fricción, eliminando posibles puntos de fallo en el proceso de pago.

### Integración

Para configurar la integración de Quick Checkout y tener un pago receptivo, optimizado y configurable, proporcionamos en los pasos a continuación el proceso de configuración inicial común para Quick Checkout.

Para integrarlo en su sitio web, primeramente debe contar con el servicio contratado y una api key, la cual permitirá el renderizado del formulario.

Una vez que cuente con lo anterior mencionado, debe realizar lo siguiente.

### Incluir la biblioteca de Virtualpos - Quick Checkout

Utilice nuestro script oficial para acceder a las funcionalidades del producto de forma segura desde tu frontend.

Ambiente Sandbox:

```html
<script src="https://quick-checkout.virtualpos-sandbox.com/virtualpos-quick-checkout.js"></script>
```

<br />

Ambiente Producción:

```html
<script src="https://quick-checkout.virtualpos.cl/virtualpos-quick-checkout.js"></script>
```

#

### Configurar el Quick Checkout

Crea la configuración de inicio del Quick Checkout.

```json
const settings = {
  initialization: {
    amount: 1000,
    api_key: 'your_api_key',
    order_id: 'order_uuid',
    clientInformation: {
      fullName: '',
      socialId: '',
      email: '',
    }
  },
  customization: {
    paymentMethods: {
      creditCard: {
        available: "yes",
        installments: "1,2,3,4,5"
      },
      debitCard: {
        available: "yes"
      },
      prePaidCard: {
        available: "yes"
      },
    },
  },
  callbacks: {
    onSubmit: ({ selectedPaymentMethod, formData }) => {
      // callback de llamada al hacer clic en el botón de envío de datos
      return new Promise((resolve, reject) => {
        fetch("/api/process-payment", {
          method: "POST",
          body: formData,
        })
        .then((response) => response.json())
        .then((data) => {
          resolve()
        })
        .catch((error) => {
          // manejar la respuesta de error al intentar procesar el pago
          reject()
        });
      });
    },
    onError: (error) => {
      // callback manejar la respuesta de error para todos los casos de Quick Checkout
    },
  },
}
window.initPaymentController(settings)
```

> 🚧 Nota importante
>
> Se debe considerar que para renderizar el formulario, primeramente se debió haber creado una orden a través de nuestro webservice, para mayor información haga clic [aquí](https://virtualpos.readme.io/reference/crear-un-objeto-payment). Caso contrario, no se podrá renderizar el formulario.

### Renderizar el QuickCheckout

Una vez creadas las configuraciones, ingrese el código a continuación para renderizar el producto.

```html
<div id="vpos_payment_form"></div>
```

El resultado de renderizar el medio de pago debería parecerse a la imagen de abajo.

![](https://files.readme.io/a2305dc-image.png)
