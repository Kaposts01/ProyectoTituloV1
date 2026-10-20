# Preguntas abiertas (validar en sandbox o con Payku)

Todo lo que la documentación oficial **no confirma** y que afecta a la integración. Cuando se resuelva una, anota la fecha, la evidencia (request/response) y actualiza el documento afectado.

Prioridad: 🔴 bloquea la implementación · 🟠 afecta la sincronización o los datos · 🟢 detalle.

| ID | Prioridad | Pregunta | Afecta a | Cómo validarla |
|---|---|---|---|---|
| Q-01 | 🔴 | En un request **sin parámetros** (p. ej. `GET /api/suplan/plans`, `GET /api/sususcription/{id}`), ¿la cadena firmada lleva `&` final (`%2Fapi%2Fsuplan%2Fplans&`) como en los ejemplos PHP/JS, o no (como nuestra colección)? | [authentication.md](authentication.md), [postman.md](postman.md) | Llamar `GET /api/suplan/plans` en sandbox con cada variante (`sign_trailing_ampersand=true/false`) y ver cuál no da 401. |
| Q-02 | 🟠 | ¿Payku acepta un header `Sign` en endpoints que no lo exigen (transacción, conciliación, catálogos)? | [authentication.md](authentication.md) | Llamar `GET /api/paymentmethods` con y sin `Sign`. |
| Q-03 | 🔴 | ¿Los **query params** (`page`, `per_page`, `date_init`, `active=true`) entran en la firma? ¿Un **email** en el path se firma con `@` o `%40`? | [authentication.md](authentication.md) | `GET /api/sususcriptionv3?date_init=…` firmando con y sin query params; `GET /api/suclient/{email}`. |
| Q-04 | 🟠 | ¿Las URL de notificación se configuran **solo en el plan** (`url_notify_suscription`, `url_notify_payment`) o también al crear la suscripción? | [plans.md](plans.md), [webhooks.md](webhooks.md) | Crear un plan con URL de un servicio de captura de requests (p. ej. webhook.site), suscribirse con tarjeta de prueba y observar. |
| Q-05 | 🟠 | ¿Qué valores de estado de cobro devuelve realmente cada endpoint (lista A vs B, `paid[].status` de V3, `last_status_current_payment` de V1)? | [statuses.md](statuses.md) | Generar cobros aprobados y rechazados en sandbox y comparar las respuestas de V1, V3, detalle y cliente. |
| Q-06 | 🔴 | ¿Los **cobros de suscripción** aparecen en `GET /api/transaction` y en **conciliación**? ¿Con qué `payment_key` / `order`? ¿Se pueden consultar con `GET /api/transaction/{transaction}`? | [data-model.md](data-model.md), [reconciliation.md](reconciliation.md), [sync-payku.md](workflows/sync-payku.md) | Tras un cobro de suscripción en sandbox, buscarlo en `/api/transaction` por fecha y probar `GET /api/transaction/<número>`. Para conciliación, quizás haya que preguntar a Payku. |
| Q-07 | 🟢 | `POST /api/sususcription`: ¿`amount` y `coupon` son opcionales? ¿Qué pasa si se envía `amount` a un plan de monto fijo? | [subscriptions.md](subscriptions.md) | Crear suscripciones con y sin esos campos. |
| Q-08 | 🟠 | ¿Cuál es la clave estable de un cobro? ¿`paid[].transactions[]` trae el número de transacción? ¿`paid_number` y `try_number` se repiten? | [subscription-charges.md](subscription-charges.md) | Observar V3 después de varios cobros y reintentos. |
| Q-09 | 🔴 | **Eliminar tarjeta**: ¿el campo es `card` o `suscription`? ¿el valor es el `identifier` de la tarjeta (`surec…`) o el ID de la suscripción? | [cards.md](cards.md), [postman.md](postman.md) | Inscribir dos tarjetas en sandbox y probar `{"card": "surec…"}`. |
| Q-10 | 🟢 | ¿El límite "máx. 20 caracteres" del path de cliente y suscripción es real? (los ejemplos tienen 22 y un email puede ser más largo). | [customers.md](customers.md) | `GET /api/suclient/<email largo>`. |
| Q-11 | 🔴 | ¿Sobre qué fecha filtran `date_init` / `date_end` en V3 (creación, `start`, último cobro)? ¿Son inclusivos? ¿Hay un rango máximo? | [pagination.md](pagination.md), [sync-payku.md](workflows/sync-payku.md) | Crear una suscripción hoy y consultar ventanas que la incluyan o excluyan; probar un rango de varios años. |
| Q-12 | 🟠 | Nombres de los parámetros de fecha y `per_page` máximo en `GET /api/suclient/customers` y `GET /api/sususcription` (V1). | [pagination.md](pagination.md) | Probar `date_init` / `date_end` y `per_page=100/500/4000`. |
| Q-13 | 🟠 | Tras `DELETE /api/sususcription/{id}`, ¿el estado queda `delete` o `cancel`? ¿Se envía webhook? ¿Se detiene un cobro en curso? | [cancel-subscription.md](workflows/cancel-subscription.md) | Eliminar una suscripción de prueba y consultar detalle y `logs`. |
| Q-14 | 🟠 | Webhooks: ¿`Content-Type`? ¿reintentos si respondemos error? ¿se notifican `suspended`, `cancel`, `finish`, cobros rechazados y cobros de consumo? ¿hay IPs fijas? | [webhooks.md](webhooks.md) | Capturar con un receptor de pruebas; responder 500 a propósito y ver si reintenta. Preguntar a soporte de Payku. |
| Q-15 | 🟢 | ¿El cargo de validación de **$50** se reembolsa? ¿Se repite al cambiar tarjeta? | [create-subscription.md](workflows/create-subscription.md), [cards.md](cards.md) | Revisar transacciones/conciliación en sandbox; preguntar a Payku. |
| Q-16 | 🟢 | ¿Cuánto dura vigente la `url` de activación / inscripción de tarjeta? | [create-subscription.md](workflows/create-subscription.md) | Abrir una URL después de 24 h, 72 h, etc. |
| Q-17 | 🟠 | ¿Cuántos reintentos hace Payku y con qué calendario antes de `maximum attempt limit` / `suspended`? | [suspend-subscription.md](workflows/suspend-subscription.md) | Preguntar a Payku (en sandbox el ciclo mensual es difícil de simular). |
| Q-18 | 🟠 | ¿Payku permite dos clientes con el mismo email? | [create-customer.md](workflows/create-customer.md) | Crear dos veces el mismo email en sandbox. |
| Q-19 | 🟢 | Rate limits (req/s, req/min) y existencia de `Retry-After`. | [errors.md](errors.md) | Preguntar a Payku; medir. |
| Q-20 | 🟢 | ¿Qué devuelve una página fuera de rango (vacía o repite la última)? | [pagination.md](pagination.md) | Pedir `page=9999`. |
| Q-21 | 🟢 | Zona horaria de las fechas sin zona (`YYYY-MM-DD HH:MM:SS`). | [data-model.md](data-model.md) | Crear un registro a una hora conocida y comparar. |
| Q-22 | 🟠 | ¿Dónde se ve el **monto** y la **periodicidad** de un plan o suscripción por API? | [plans.md](plans.md), [subscriptions.md](subscriptions.md) | Revisar el panel de Payku y las respuestas reales; preguntar a Payku. |
| Q-23 | 🟠 | ¿Cómo se ve `subcriptions` en `GET /api/suclient/{id}` si el cliente tiene **dos** suscripciones? ¿Y la forma real de cada elemento en `GET /api/suclient/customers`? | [customers.md](customers.md) | Suscribir el mismo cliente a dos planes en sandbox. |
| Q-24 | 🟢 | ¿Qué es `https://testing-apirest.payku.cl/` (aparece en la portada)? | [README.md](README.md) | Preguntar a Payku. |
| Q-25 | 🟢 | ¿Se puede forzar o acelerar un cobro recurrente en sandbox para probar reintentos? | [authentication.md](authentication.md#tarjetas-de-prueba-sandbox) | Preguntar a Payku. |
| Q-26 | 🟢 | ¿Qué significa exactamente `end` en una suscripción `active`? | [subscriptions.md](subscriptions.md) | Comparar con el panel de Payku. |
| Q-27 | 🔴 | En un plan de **monto variable**, ¿el primer cobro también es "a partir del mes siguiente" o se cobra al activar la suscripción? Si cobra al activar, el primer aporte por transacción única **duplicaría** el mes 1. | [alta-socio.md](workflows/alta-socio.md) | Suscribir un cliente al plan variable en sandbox con `amount`, inscribir la tarjeta y revisar `transactions[]` / V3 `paid[]` ese mismo día. Preguntar a Payku. |
| Q-28 | 🟠 | Al inscribir la tarjeta de una suscripción, ¿Payku redirige al socio a `url_success_payment` / `url_failed_payment` del plan? ¿Agrega algún parámetro (id de suscripción) a esa URL? | [alta-socio.md](workflows/alta-socio.md), [link-inscripcion.md](workflows/link-inscripcion.md), [plans.md](plans.md) | Crear un plan con esas URL apuntando a `webhook_base_url`, completar una inscripción y mirar la URL de llegada. |
| Q-29 | 🟠 | ¿`POST /api/suinscriptionscards` genera una `url` nueva para una suscripción todavía en `register` (alta no completada)? ¿La `url` anterior deja de servir? | [link-inscripcion.md](workflows/link-inscripcion.md) | Carpeta Postman `01 · Link de inscripción` › A · Alta pendiente › LA-2; luego abrir ambas `url`. |
| Q-30 | 🟢 | El objeto `client` dentro de `GET /api/sususcription/{id}`, ¿refleja los cambios hechos con *Actualizar cliente* o es una copia tomada al suscribir? | [editar-socio.md](workflows/editar-socio.md) | Carpeta Postman `02 · Editar socio` › EP-5. |
| Q-31 | 🟠 | El portal permite cambiar el monto de una suscripción (incluso de plan fijo). ¿Qué endpoint usa? ¿Payku puede habilitarlo o documentarlo para la API? | [cambiar-monto.md](workflows/cambiar-monto.md) | Preguntar a soporte de Payku. |
| Q-32 | 🟠 | Al cambiar el monto en el portal: ¿aplica al ciclo en curso o al siguiente? ¿Se refleja en `subcriptions.amount` de `GET /api/suclient/{id}` y en `paid[].amount_paid` de V3? | [cambiar-monto.md](workflows/cambiar-monto.md) | Cambiar el monto en el portal de sandbox y correr la carpeta Postman `03 · Cambiar monto` › A · Portal. |
| Q-33 | 🟠 | El `POST /api/transaction` del **primer aporte (M1)** del alta: ¿aparece en `GET /api/transaction` y en conciliación igual que cualquier pago único? ¿Tiene algún campo que lo distinga de los cobros recurrentes de la suscripción en los reportes? ¿Puede usarse `POST /api/sutransaction` (cobro de consumo) sobre una suscripción de **plan fijo** para cobrar el mes 1 sin Webpay? | [alta-socio.md](workflows/alta-socio.md), [reconciliation.md](reconciliation.md) | Completar un alta en sandbox (paso 7), buscar la transacción en `/api/transaction` y en conciliación, comparar con un cobro recurrente real. Preguntar a Payku sobre `sutransaction` en plan fijo. |

---

## Requests listos para validar

La colección `Payku API v2.postman_collection.json` trae la carpeta **🧪 Validación sandbox** con un request por pregunta: Q-01a/b, Q-02a/b, Q-03a/b/c/d (incluye Q-10), Q-06, Q-09a/b, Q-11a/b, Q-12a/b y Q-20. Instrucciones en [postman.md § 0](postman.md#0-colección-v2-corregida-2026-10-12). Q-04 y Q-14 se prueban con *Suscripción de consumo › Crear plan* (URL de notificación hacia `{{webhook_base_url}}`).

## Plan de validación sugerido (orden)

1. **Q-01, Q-03** (firma): sin esto no funciona nada en Python.
2. **Q-11, Q-12** (fechas y paginación): define la carga inicial.
3. **Q-06** (cobros ↔ transacciones ↔ conciliación): define el modelo de pagos.
4. **Q-04, Q-14** (webhooks): define el receptor.
5. **Q-09, Q-13** (tarjetas y baja): define los flujos de soporte.
6. El resto, a medida que avance la implementación.

## Preguntas para enviar a soporte de Payku

Q-06, Q-14, Q-15, Q-17, Q-19, Q-22, Q-24, Q-25, Q-27, Q-31, Q-33 (difíciles de responder solo con sandbox).
