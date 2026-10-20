# Flujo transversal: link seguro de inscripcion de tarjeta

> Comparacion del comportamiento entre VirtualPOS, Toku y Payku para el flujo de link seguro de inscripcion de medio de pago.
> Fuente: adaptadores por canal en `workflows/link-inscripcion.md` de cada canal.

---

## Resumen por canal

### Caso A: alta pendiente

| Dimension | VirtualPOS | Toku | Payku |
|---|---|---|---|
| Referencia | `suscription.id` en estado `SUSCRIBIENDO` | `checkout_session_id` en `toku_altas` con estado `PENDIENTE_INSCRIPCION` | `su...` en estado `register` en `payku_altas` |
| Link del proveedor | `url_redirect` de `POST /v3/suscription` (guardado al crear; **no recuperable por API**) | URL de la Checkout Session creada en el alta (recuperable por `GET /cl/checkout-sessions/{id}` mientras este `OPEN`) | `url` de `POST /api/sususcription` (recuperable via `suinscriptionscards` con Q-29 sin confirmar) |
| Renovacion del link | **No:** si la sesion expiro o fallo, hay que crear una suscripcion nueva | Si: extender con `PATCH` si esta `OPEN`; crear sesion nueva con `-R{n}` si esta `EXPIRED` y la Subscription sigue pausada | Parcial: se puede llamar a `suinscriptionscards` sobre la suscripcion en `register` (Q-29 sin confirmar) |
| Vigencia | Hasta que la suscripcion pase a `FINALIZADA` (30 dias por defecto) | `expiration_datetime`; se puede extender mientras este `OPEN` | No documentada (Q-16) |
| Retorno del socio | `return_url` (Base64) fijado al crear la suscripcion; apunta a pagina generica que confirma por API | `success_url` / `failure_url` por request en la sesion | URL del plan (`url_success_payment` / `url_failed_payment`); la pagina identifica el link por sesion o cookie (Q-28) |
| Confirmacion | Callback + `GET /v3/suscription/{id}` → `ACTIVA` | Webhook `payment_method.*` + `GET /payment-methods?id_customer=` | Webhook `url_notify_suscription` + `GET /api/sususcription/{id}` → `active` |
| Bloqueante | Ninguno activo para este caso | **BLQ-TK-01:** Toku debe configurar `flow_name` ENROLLMENT; sin esto el POST de sesion da `4xx` | Q-29: no confirmado si `suinscriptionscards` sirve para una suscripcion en `register` |

### Caso B: socio existente (cambio de tarjeta)

| Dimension | VirtualPOS | Toku | Payku |
|---|---|---|---|
| Referencia | Suscripcion `ACTIVA` (la del motivo: cargo rechazado o tarjeta por vencer) | Subscription vigente (`ACTIVE` o `PAUSED` por cuotas impagas), lookup por `product_id` | Suscripcion en `active` o `suspended` |
| Link del proveedor | `change_card_url` de `PUT /v3/suscription/{id}/changecard`; reutilizar si hay uno vigente en `card_change_requests` | Nueva Checkout Session con `mode: ENROLLMENT`, `unique_external_id: CAMBIO-{public_id}` (idempotente por doble clic) | `url` de `POST /api/suinscriptionscards`; reutilizar si fue pedida hace menos de 30 min |
| Renovacion del link | Si: cada `PUT` genera uno nuevo | Si: `unique_external_id` hace el POST idempotente mientras la sesion este abierta | Si: cada llamada genera una nueva URL |
| Vigencia | `change_card_expiration_date` | `expiration_datetime` de la sesion; se puede extender | No documentada (Q-16) |
| Retorno del socio | **No disponible:** `changecard` no acepta `return_url`; confirmacion depende del job | `success_url` / `failure_url` por request; el socio **si vuelve** a nuestra pagina | URL del plan (Q-28); el socio puede quedarse en la pagina de Payku |
| Confirmacion | Comparar huella de `payment_method` (bin, last4, expiracion, marca) antes y despues | Detectar `pm_` nuevo en `payment-methods` que no estaba en la huella, en `chargeable` o `pending_activation` | Detectar un `identifier` nuevo en `active_cards[]` que no estaba en la huella |
| Post-confirmacion | Recuperar los cargos rechazados asociados a la suscripcion | Asociar el `pm_` nuevo si no lo esta; reactivar la Subscription si estaba pausada por cuotas impagas; borrar el `pm_` viejo solo cuando el nuevo sea `chargeable` y no tenga otras Subs activas | El socio paga meses atrasados de inmediato si la suscripcion estaba `suspended`; no borrar tarjeta vieja hasta resolver Q-09 |
| Bloqueante | Pendiente confirmar con soporte si se puede configurar `return_url` para `changecard` | **BLQ-TK-01** (mismo del alta; todo ENROLLMENT lo requiere) | Q-09 (body del endpoint de eliminar tarjeta), Q-15 ($50 al cambiar tarjeta) |

---

## Diferencias criticas para la capa comun

| Aspecto | Diferencia entre canales |
|---|---|
| Retorno del socio | Toku es el unico canal que **garantiza** que el socio vuelve a nuestra pagina con referencia del link, tanto en alta como en cambio. VirtualPOS no retorna en el cambio de tarjeta; Payku depende de la configuracion del plan (Q-28). |
| Renovacion del link | VirtualPOS no permite recuperar la URL original; hay que guardarla al crearla. Toku puede extender o recrear la sesion. Payku tiene comportamiento no confirmado para alta pendiente (Q-29). |
| Vigencia | Solo VirtualPOS y Toku tienen vigencia documentada. Para Payku es TBD. La capa comun debe asumir un margen prudente (~24 h para Payku). |
| Confirmacion | Los tres canales requieren una llamada de verificacion por API (no solo el webhook). Ningun webhook reemplaza la consulta al recurso. |
| Bloqueante de Toku | BLQ-TK-01 bloquea **todos** los flujos ENROLLMENT de Toku (alta y cambio de tarjeta). La capa comun no puede activarse para Toku hasta que Toku configure `flow_name`. |
| Host del Checkout | VirtualPOS usa `pat.virtualpos.cl`; Payku usa `des.payku.cl` o `app.payku.cl`. El host de Toku es TBD hasta la primera sesion real (T-A2). La capa comun debe validar el host antes de redirigir. |

---

## Referencias por canal

- VirtualPOS: [workflows/link-inscripcion.md](../virtualpos/workflows/link-inscripcion.md)
- Toku: [workflows/link-inscripcion.md](../toku/workflows/link-inscripcion.md)
- Payku: [workflows/link-inscripcion.md](../payku/workflows/link-inscripcion.md)
