# Bloqueante BLQ-TK-01 — Checkout ENROLLMENT sin flow_name

> Creado: 2026-10-15. Tarea: BLQ-TK-01.
> Fuentes: alta-socio.md, link-inscripcion.md, enroll-payment-method.md, cambiar-monto.md, payment-methods.md, subscriptions.md.

---

## Descripcion del bloqueante

### Que es `flow_name`

`flow_name` es un parametro requerido en el body de `POST /cl/checkout-sessions` cuando el modo es `ENROLLMENT`. Identifica el **flujo de inscripcion de medio de pago** que Toku debe presentarle al socio: que metodos de pago estan disponibles (tarjeta via Transbank Oneclick, PAC, etc.), que pantallas se muestran y que logica de validacion se aplica.

Toku configura este flujo del lado del proveedor, por cuenta de comercio. No es un valor que el comercio pueda definir libremente; debe existir en la configuracion de la cuenta de Toku previamente.

### Por que lo necesita Toku

El Checkout `ENROLLMENT` en Toku es el mecanismo para que un socio inscriba su medio de pago automatico (tarjeta PAT via Transbank Oneclick o PAC). Sin `flow_name`, la llamada a `POST /cl/checkout-sessions` devuelve un error `4xx` ("Flujo de inscripcion no configurado", segun alta-socio.md § 7 PASO 5: `4xx` sobre `flow_name`). No se genera ninguna URL de checkout para el socio.

### Que pasa sin el (sintoma actual)

- `POST /cl/checkout-sessions` con `mode: ENROLLMENT` falla con `4xx`.
- No se genera una URL a la que redirigir al socio para inscribir su tarjeta o PAC.
- El socio no puede completar el proceso de inscripcion de medio de pago.
- La Subscription queda en estado `PAUSED` indefinidamente (sin medio de pago asociado) y debe ser borrada manualmente.

El error aplica tanto al alta de un socio nuevo (alta-socio.md) como a cualquier solicitud de cambio de medio de pago para un socio existente (link-inscripcion.md).

---

## Workflows afectados

| Workflow | Paso bloqueado | Consecuencia |
|---|---|---|
| **Alta de socio** (`alta-socio.md`) | Paso 5 — Crear Checkout Session de inscripcion | No se puede generar la URL de activacion para el socio. Los pasos 1 a 4 (upsert Customer, crear Subscription, pausar) funcionan. El alta queda en estado `PENDIENTE_INSCRIPCION` sin posibilidad de avanzar. |
| **Link de inscripcion — caso A: alta pendiente** (`link-inscripcion.md`) | `obtenerUrl(ALTA, ...)` — POST nueva sesion tras sesion expirada | Si la sesion original expiro y se intenta crear una nueva con `mode: ENROLLMENT`, falla igual. Solo se puede extender la sesion original via PATCH mientras este `OPEN`. |
| **Link de inscripcion — caso B: socio existente** (`link-inscripcion.md`) | `obtenerUrl(CAMBIO, ...)` — POST sesion de inscripcion sobre Subscription existente | No se puede enviar al socio un link para cambiar su tarjeta vencida o reemplazar un medio rechazado. |
| **Inscribir medio de pago — Camino A: Portal/Checkout** (`enroll-payment-method.md`) | Cualquier uso de Checkout con `mode: ENROLLMENT` | El camino A queda completamente bloqueado. El camino B (PAC por API via `POST /customer-collection-accounts`) no esta afectado y es la alternativa actual para aprendizaje. |
| **Flujo de recuperacion de tarjeta vencida / cobros rechazados** (implicito en varios workflows) | Generacion del link de re-inscripcion | Un socio cuya tarjeta vencio no puede inscribir una nueva hasta que se resuelva este bloqueante. |

**No afectado:** las operaciones que no usan Checkout `ENROLLMENT` funcionan normalmente: crear/editar Subscription (`PUT /subscriptions`), cambiar monto (`cambiar-monto.md`), consultar Subscriptions/Invoices/Payment Methods, inscribir PAC por API (camino B de `enroll-payment-method.md`) y webhooks.

---

## Alternativa documentada: Customer Portal

Mientras el bloqueante no este resuelto, existe una alternativa parcial documentada en `alta-socio.md` (nota al inicio del archivo).

### Que es el Customer Portal

El Customer Portal se crea con `POST /v2/customer-portal-sessions` enviando `flow_name: "0"`. Es un flujo generico de inscripcion de medio de pago que Toku tiene preconfigurado para todas las cuentas sin requerir configuracion adicional.

### Que permite

- El socio puede acceder al portal de Toku y desde ahi inscribir su tarjeta o PAC.
- No requiere que Toku configure un `flow_name` especifico en nuestra cuenta.
- Genera una URL de portal que se puede enviar al socio.

### Que NO permite

- **No admite `ids_subscription`**: al crear la sesion de Customer Portal, no se puede indicar a que Subscription debe asociarse el medio de pago inscrito. El portal inscribe el medio de pago a nivel de Customer, no de Subscription especifica.
- **No admite `unique_external_id`**: no hay mecanismo de idempotencia por referencia de negocio. Un doble clic puede crear dos sesiones.
- **No es un Checkout de inscripcion controlado**: no se puede pasar `success_url` / `failure_url` especificas por request (las URL de retorno son las configuradas a nivel de cuenta, si las hay).

### Como confirmar la inscripcion

Dado que el Customer Portal no indica la Subscription de destino, la confirmacion debe hacerse por:
1. **Webhook `payment_method.created`** o **`payment_method.attached_products`**: cuando el socio inscribe un medio en el portal, Toku envia este webhook con el `payment_method.id` (`pm_...`) y el `customer.id` (`cus_...`).
2. El backend recibe el webhook, identifica al socio por `customer.id`, llama a `GET /payment-methods?id_customer={cus_id}` para confirmar que hay un `pm_` en estado `chargeable` o `pending_activation`, y luego ejecuta manualmente los pasos de asociacion y reactivacion (pasos 8 y 9 de alta-socio.md).
3. Como respaldo (polling): consultar `GET /payment-methods?id_customer={cus_id}` a los 15 min, 1 h y 24 h.

### Limitaciones respecto al Checkout ENROLLMENT

| Aspecto | Checkout ENROLLMENT (bloqueado) | Customer Portal (alternativa) |
|---|---|---|
| Asociacion automatica a Subscription | Si (via `ids_subscription`) | No: requiere paso manual de asociacion |
| URL de retorno personalizada | Si (`success_url`/`failure_url` por request) | No: URL fija de la cuenta |
| Idempotencia por referencia | Si (`unique_external_id`) | No documentada |
| Confirmacion via webhook | `payment_method.attached_products` | `payment_method.created` o `payment_method.attached_products` |
| Paso de asociacion manual | Opcional (puede ser automatico segun T-A4) | Siempre necesario |
| Flujos de pago disponibles | Configurable (`allowed_payment_options`) | El que tenga el portal por defecto |

### Cuando usar esta alternativa

Solo en escenario de prueba o aprendizaje, cuando no se puede esperar la resolucion del bloqueante. **No se recomienda para produccion** porque requiere un paso manual de asociacion, no tiene control de retorno al socio y puede generar confusion si el socio inscribe el medio en el portal sin completar el flujo de alta.

---

## Plan de accion para resolver BLQ-TK-01

### Paso 1: Contactar a Toku

**A quien contactar:** canal de soporte o el ejecutivo tecnico asignado a la cuenta de TECHO en Toku. Si no hay ejecutivo asignado, usar el correo de soporte tecnico documentado en authentication.md de Toku.

**Que preguntar exactamente (texto sugerido para el correo o ticket):**

> Hola,
>
> Estamos integrando el Checkout de Toku en modo `ENROLLMENT` para inscripcion de medios de pago de socios recurrentes. Al llamar a `POST /cl/checkout-sessions` con `mode: ENROLLMENT`, recibimos un error 4xx indicando que el flujo de inscripcion no esta configurado.
>
> Necesitamos que configuren en nuestra cuenta el `flow_name` para inscripcion de tarjeta via Transbank Oneclick, y si es posible tambien para PAC. El flujo deberia aceptar redireccion a nuestras URLs de exito y fracaso (`success_url` / `failure_url`).
>
> Por favor confirmar:
> 1. El valor exacto de `flow_name` que debemos usar en el request.
> 2. Si se requiere configuracion adicional de nuestra parte (URLs de retorno, allowed payment options, etc.).
> 3. En que dominio vive el Checkout de Toku para agregarla a nuestra lista de hosts permitidos.
> 4. Si el Checkout `ENROLLMENT` admite una Subscription en estado `PAUSED` en `ids_subscription`, o si la Subscription debe estar `ACTIVE` al crear la sesion.

### Paso 2: Que configuracion pedir

- **`flow_name` para tarjeta:** un flujo de inscripcion que use Transbank Oneclick (gateway `transbank_oneclick`). Este es el metodo PAT activo documentado en el codigo (`allowed_payment_options: ["transbank_oneclick"]`).
- **`flow_name` para PAC** (opcional para una segunda fase): un flujo que use PAC via Toku (`toku_pac`) u otro proveedor compatible.
- **URL base del Checkout de Toku:** el dominio desde el que Toku sirve el formulario de inscripcion, para agregar a la lista de hosts permitidos de la capa comun de link seguro. Referencia: pregunta T-L2 en link-inscripcion.md § 7.
- **Comportamiento con Subscription en `PAUSED`:** confirmar si el Checkout `ENROLLMENT` acepta `ids_subscription` cuando la Subscription esta en estado `PAUSED`. Referencia: pregunta T-A3 en alta-socio.md § 9.

### Paso 3: Como verificar que quedo configurado

Una vez que Toku confirme el `flow_name`:

1. Intentar `POST /cl/checkout-sessions` con el `flow_name` indicado en el body:
   ```json
   {
     "mode": "ENROLLMENT",
     "flow_name": "<valor confirmado por Toku>",
     "billing_data": { "id_account": "{{account_id}}", "id_customer": "{{test_customer_id}}", "currency": "CLP" },
     "unique_external_id": "TEST-BLQ-TK-01-VERIFY",
     "skip_message_trigger": true
   }
   ```
2. Si la respuesta es HTTP 200/201 con un `id_checkout_session` y una URL, la configuracion esta activa.
3. Si sigue fallando con `4xx`, compartir el error exacto con Toku para que revisen la configuracion.

### Paso 4: Prueba de validacion despues de la configuracion

Una vez que el endpoint responde correctamente:

1. Ejecutar la carpeta `00 · Alta de socio (flujo)` de `Toku API.postman_collection.json` en produccion usando datos `TEST-` y `skip_message_trigger: true`.
2. En TA-5 (Crear Checkout Session), confirmar que la URL generada carga el formulario de Toku en el navegador.
3. Completar la inscripcion con datos de prueba y verificar que el webhook `payment_method.attached_products` llega al backend.
4. Verificar con `GET /payment-methods?id_customer={{test_customer_id}}` que el `pm_` quedo en estado `chargeable` o `pending_activation`.
5. Verificar que `subscription_ids` del `pm_` incluye la Subscription de prueba (o ejecutar el paso de asociacion manual si no).
6. Ejecutar la limpieza: TA-L1 (DELETE Subscription) y TA-L2 (DELETE Customer).
7. Documentar en este archivo bajo "Resultado de la validacion" la fecha, el `flow_name` confirmado y el resultado.

---

## Impacto en implementacion

Cuando se resuelva BLQ-TK-01, quedan desbloqueadas las siguientes tareas del CRM:

| Tarea | Estado actual | Estado tras resolver |
|---|---|---|
| Alta de socio nuevo por formulario web (Toku) | Bloqueada en Paso 5 | Desbloqueada: el flujo completo de alta-socio.md puede ejecutarse |
| Link de inscripcion para alta pendiente (caso A) | Limitado (solo extender sesion existente) | Desbloqueado: se puede crear nueva sesion tras expiracion |
| Link de inscripcion para socio con tarjeta vencida o rechazos (caso B) | Bloqueado | Desbloqueado: se puede enviar link de cambio de medio |
| Recuperacion automatica de socios con cobros rechazados | No implementable sin link | Implementable: el job de rechazos puede emitir links de re-inscripcion |
| Tests de integracion del Checkout ENROLLMENT | Solo pruebas parciales (Customer Portal) | Tests completos del flujo de inscripcion real |

---

## Resultado de la validacion

> Rellenar cuando se resuelva el bloqueante.

| Campo | Valor |
|---|---|
| Fecha de resolucion | — |
| `flow_name` confirmado por Toku | — |
| Dominio del Checkout (T-L2) | — |
| Admite Subscription en PAUSED (T-A3) | — |
| Asociacion automatica al `pm_` (T-A4) | — |
| Webhook de confirmacion (T-A6) | — |
| Validado en Postman (carpeta TA) | — |
