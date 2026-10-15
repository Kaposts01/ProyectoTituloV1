# Revisión de workflows Toku — WFL-TK-01

Fecha: 2026-10-15.
Rama: `feature/hito5-workflows-operacionales`.
Revisado contra: `app/integrations/toku/client.py`, `app/services/toku_sync.py`, `app/services/write_toku.py`, `app/api/v1/routes/writes.py`, `app/models/toku_channel.py`, `app/core/config.py`, `app/services/read_only_provider_sync.py`, `scripts/sync_toku.py`.

---

## Tabla resumen

| # | Workflow | Estado | Discrepancias principales | Accion requerida |
|---|---|---|---|---|
| 1 | `alta-socio.md` | 🔴 Bloqueado | Tabla `toku_altas` inexistente; endpoint `POST /subscriptions/associate/payment-method` difiere del cliente; sin webhook receiver | Requiere BLQ-TK-01 + implementar tabla y workflow completo |
| 2 | `link-inscripcion.md` | 🔴 Bloqueado | Depende de `toku_altas` y de BLQ-TK-01; sin tablas `toku_cambios` ni lógica de link | Requiere BLQ-TK-01 + alta-socio implementado |
| 3 | `cambiar-monto.md` | ⚠️ Parcial | Solo actualiza una invoice individual; no hay flujo orquestado (sub + invoices en cobro + cola de corrección) | Implementar flujo completo como write orquestado |
| 4 | `cancel-subscription.md` | ⚠️ Parcial | Status `CANCELLED` en el modelo no es un estado Toku documentado; sin paso de anulación de invoices impagas antes del DELETE; `void_invoice` no expuesto como write | Corregir el literal; agregar paso de void; exponer `void_invoice` |
| 5 | `create-customer.md` | ⚠️ Parcial | `lookup_customer` en el cliente usa `mail` en lugar de `external_id`; sin lookup por `external_id` | Agregar método `lookup_customer_by_external_id` |
| 6 | `create-invoice.md` | ⚠️ Parcial | `void_invoice` disponible en cliente pero no expuesto en writes.py; `disable_automatic_payment` no incluido en el modelo de alta de invoice | Exponer `void_invoice` como write endpoint |
| 7 | `create-subscription.md` | ⚠️ Parcial | Sin endpoint de escritura `POST /toku/subscriptions` en writes.py; no hay verificación post-creación de `recurring.status == ACTIVE` | Agregar write endpoint de creación si el caso de uso lo requiere |
| 8 | `editar-socio.md` | ⚠️ Parcial | `TokuCustomerUpdate` acepta solo `name` y `mail`; faltan `phone_number` y `government_id`; sin validación de email duplicado; sin alerta de PAC al cambiar RUT | Ampliar el schema del write endpoint |
| 9 | `enroll-payment-method.md` | 🔴 Bloqueado | Sin endpoint `POST /customer-collection-accounts` en el cliente; endpoint `associate_to_subscription` usa ruta distinta a la documentada (`POST /payment-methods/{pm_id}/subscriptions` vs. `POST /subscriptions/associate/payment-method`); Checkout ENROLLMENT bloqueado | Requiere BLQ-TK-01 para camino A; verificar ruta de asociación con Toku |
| 10 | `reconcile-payment.md` | ⚠️ Parcial | Sin tabla separada `toku_payment_intents`; solo se guarda el primer payment intent (mencionado en el workflow como fallo conocido del sync anterior); sin `aplicacion_pago`; transacciones sin filtro de fecha en sync | Crear tabla `toku_payment_intents`; corregir el sync de transactions |
| 11 | `seguimiento-cobros.md` | ⚠️ Parcial | Sin `toku_payment_intents`; sin vista `v_toku_cuotas_mensuales`; sin cuadratura; transaction sync sin ventana de fecha; payment intents N:M no modelados | Igual que reconcile-payment + agregar vista y cuadratura |
| 12 | `sync-toku.md` | ⚠️ Parcial | Sin incremental por ventana de fecha; sin reconciliación semanal; sin `sync_checkpoints`; sin `stg_toku_payment_intents`; sin webhook receiver; estructura de módulos difiere de la propuesta | Implementar incremental + reconciliación + checkpoint + webhook receptor |

---

## Secciones por workflow

### 1. alta-socio.md

**Estado: 🔴 Bloqueado (BLQ-TK-01)**

**Lo que el código provee:**
- `TokuClient.create_customer` y `create_subscription` están disponibles.
- `TokuClient.change_subscription_status` puede pausar la subscription.
- `TokuClient.create_checkout_session` puede crear la sesión de inscripción.
- `TokuClient.delete_subscription` puede borrar una subscription abandonada.
- Write endpoints `POST /toku/subscriptions/{id}/status` y `DELETE /toku/subscriptions/{id}` están expuestos.

**Lo que no existe:**
- Tabla `toku_altas` (estados CREANDO, PENDIENTE_INSCRIPCION, ACTIVA, ABANDONADA, ERROR).
- Lógica de antidoble cobro (lock por RUT + consulta de altas vivas).
- Flujo orquestado de los 9 pasos del workflow.
- Paso 5 (Checkout Session de inscripción): bloqueado por BLQ-TK-01 (`flow_name` no configurado).
- Paso 7-8: confirmación por webhook — el receptor HMAC-SHA256 no está implementado.
- Job de respaldo (consultas a los 15 min, 1 h, 24 h, 49 h).
- Tabla `socios` con campo `toku_customer_id`.

**Discrepancia de endpoint (crítica):** El workflow indica `POST /subscriptions/associate/payment-method` con body `{id_subscription, id_payment_method, payment_scope}`. El cliente tiene `associate_to_subscription(pm_id, data)` que llama a `POST /payment-methods/{pm_id}/subscriptions`. Son rutas distintas. Una de ellas puede ser incorrecta. Se debe verificar con Toku qué endpoint es el oficial para asociar un payment method a una subscription.

**Riesgo operativo:** Sin el workflow implementado, el alta de un socio nuevo requiere intervención manual en la API de Toku o via Postman. No hay trazabilidad interna de altas en progreso.

---

### 2. link-inscripcion.md

**Estado: 🔴 Bloqueado (BLQ-TK-01)**

**Lo que el código provee:**
- Métodos básicos del cliente para leer checkout sessions, subscriptions y payment methods están presentes (via GET).
- `create_checkout_session` puede crear nuevas sesiones.

**Lo que no existe:**
- Tabla `toku_altas` (prerequisito para el Caso A).
- Tabla `toku_cambios` (prerequisito para el Caso B).
- Ninguna lógica de link seguro de inscripción.
- `PATCH /cl/checkout-sessions/{id}` para extender el `expiration_datetime` — este método no existe en `TokuClient`.
- `GET /cl/checkout-sessions/{id}` — tampoco existe en el cliente (solo hay `create_checkout_session`).
- `DELETE /payment-methods?id_payment_method={pm}` vía write endpoint no está expuesto.

**Dependencias bloqueantes:** BLQ-TK-01 (`flow_name` de ENROLLMENT) bloquea todo el flujo de Checkout. El Caso B (socio existente) también requiere esta configuración.

**Riesgo operativo:** El flujo de reemplazo de medio de pago para socios existentes no tiene ningún camino automático implementado.

---

### 3. cambiar-monto.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- `TokuClient.update_subscription` (`PUT /subscriptions/{id}`) existe.
- `TokuClient.update_invoice` (`PUT /invoices/{id}`) existe.
- Write endpoint `PUT /toku/invoices/{invoice_id}` expuesto, acepta `amount` y `due_date`.
- Write endpoint para status de subscription existe (no para el PUT de monto).

**Lo que no existe:**
- No existe un write endpoint `PUT /toku/subscriptions/{id}` para cambiar el monto de la subscription.
- No existe un flujo orquestado que: (1) cambie el monto en la subscription, (2) identifique invoices `in_progress` a excluir, (3) corrija las demás invoices impagas en la cola.
- No se verifica que `recurring.amount` en la respuesta coincida con el nuevo monto.
- La paginación de invoices con cursor y filtro `in_progress` no está implementada en el sync actual.

**Discrepancia:** El workflow requiere consultar `GET /invoices?subscription_id=...&general_status=unpaid&in_progress=true/false` con paginación por cursor. El cliente tiene `list_invoices` con paginación por cursor (sin filtros), pero no expone un método con los filtros necesarios para este workflow.

**Riesgo operativo:** Si se hace un PUT de monto directo sin verificar invoices `in_progress`, se podría modificar una cuota que está siendo cobrada activamente, con riesgo de cobro duplicado.

---

### 4. cancel-subscription.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- `POST /toku/subscriptions/{id}/status` con valores PAUSED, ACTIVE, CANCELLED.
- `DELETE /toku/subscriptions/{id}` expuesto con write_run y traceabilidad.
- `TokuClient.void_invoice` existe en el cliente.

**Discrepancias:**

1. El modelo `TokuSubscriptionStatusChange` acepta el literal `"CANCELLED"`. La documentación de Toku (cancel-subscription.md) solo lista `PAUSED` y `ACTIVE` como transiciones válidas vía `POST /status`. `"CANCELLED"` probablemente devuelva un `409` ("transición no permitida") desde Toku. El estado de baja definitiva se logra con `DELETE /subscriptions/{id}`, no con un cambio de status.

2. El workflow de baja completa requiere: (a) obtener invoices impagas, (b) void de cada una que no esté `in_progress`, (c) luego DELETE o PAUSED de la subscription. Este flujo orquestado no existe. El write endpoint DELETE ejecuta directamente el DELETE sin verificar ni anular invoices pendientes.

3. `void_invoice` (`POST /invoices/{id}/void`) está en el cliente pero no está expuesto como write endpoint en `writes.py`.

**Riesgo operativo:** Borrar una subscription con invoices impagas puede dejar cuotas "colgando" — el comportamiento de Toku con invoices impagas después de un DELETE no está confirmado en el workflow (marcado como `[Inferencia]`). Hay riesgo de cobros no deseados si las invoices quedan activas.

---

### 5. create-customer.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- `TokuClient.create_customer` (`POST /customers`): upsert idempotente por `external_id`. Implementado.
- `TokuClient.update_customer` (`PUT /customers/{id}`): Implementado.
- `TokuClient.get_customer` (`GET /customers/{id}`): Implementado.
- Write endpoint `PUT /toku/customers/{customer_id}`: Implementado con write_runs.
- Write endpoint `DELETE /toku/customers/{customer_id}`: Implementado con write_runs.

**Discrepancia:** `lookup_customer(self, mail: str)` en el cliente llama a `GET /customers/lookup?mail={mail}`. El workflow `create-customer.md` muestra `GET /customers/lookup?external_id={id}`. No existe un método `lookup_customer_by_external_id` en el cliente. Son dos casos de uso distintos (lookup de deduplicación por mail vs. lookup para verificar existencia por external_id).

**Lo que no existe:**
- No hay write endpoint `POST /toku/customers` para crear un nuevo customer desde el CRM (solo está en el cliente como método, pero no expuesto como ruta de escritura autorizada con write_run).

**Riesgo bajo:** La creación de customers via POST es un upsert idempotente. El lookup por external_id se usa como paso opcional antes del upsert y no es crítico para el flujo actual de sync.

---

### 6. create-invoice.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- `TokuClient.create_invoice` (`POST /invoices`): Implementado.
- `TokuClient.get_invoice`, `update_invoice`, `delete_invoice`, `void_invoice`: Implementados en cliente.
- Write endpoint `PUT /toku/invoices/{invoice_id}` (update amount/due_date): Implementado.
- Write endpoint `DELETE /toku/invoices/{invoice_id}`: Implementado.

**Lo que no existe:**
- No hay write endpoint `POST /toku/invoices` para crear una invoice manual desde el CRM.
- `void_invoice` (`POST /invoices/{id}/void`) está en el cliente pero sin write endpoint expuesto. Es necesario para el flujo de baja de subscription.
- El campo `disable_automatic_payment: true` recomendado en pruebas no está validado ni considerado en ningún modelo de escritura.

---

### 7. create-subscription.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- `TokuClient.create_subscription` (`POST /subscriptions`): Implementado.
- `TokuClient.lookup_subscription` (`GET /subscriptions/lookup?product_id=`): Implementado.
- `TokuClient.list_subscriptions_by_customer`: Implementado.
- Write endpoints para status change y DELETE de subscription: Implementados.

**Lo que no existe:**
- No hay write endpoint `POST /toku/subscriptions` para crear una subscription desde el CRM con write_run y trazabilidad.
- No hay validación post-creación de `is_recurring == true` y `recurring.status == "ACTIVE"`.
- No hay write endpoint `PUT /toku/subscriptions/{id}` para actualizar el monto de la subscription (necesario para cambiar-monto).

**Riesgo operativo:** La creación de subscriptions sin write_run no tiene trazabilidad interna si se usa el cliente directamente.

---

### 8. editar-socio.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- `TokuClient.update_customer` (`PUT /customers/{id}`): Implementado.
- Write endpoint `PUT /toku/customers/{customer_id}`: Implementado con write_runs.

**Discrepancias:**

1. El modelo `TokuCustomerUpdate` en `writes.py` solo acepta `name` y `mail`. El workflow especifica que `phone_number` y `government_id` también son editables (`PUT /customers/{id}`). No se pueden actualizar por el write endpoint actual.

2. No hay validación de email duplicado (`GET /customers?mail={nuevo}`) antes del update, como recomienda el workflow.

3. No hay paso adicional al cambiar `government_id`: el workflow requiere verificar medios PAC y crear una tarea manual si el customer tiene un `bank_account` activo.

4. El workflow recomienda `PUT /customers/{cus_…}` usando el `cus_` ID almacenado, no el `external_id`. El write endpoint usa `customer_id` como path param y busca por `Client.external_id == customer_id`. Hay un riesgo si el `external_id` almacenado en el CRM no coincide con el `cus_…` real de Toku (son cosas distintas: `external_id` es el nuestro; `id` es el `cus_…` de Toku).

**Riesgo operativo:** Cambios de teléfono o RUT de un socio no pueden propagarse a Toku mediante el write endpoint actual, requiriendo intervención directa en la API.

---

### 9. enroll-payment-method.md

**Estado: 🔴 Bloqueado (BLQ-TK-01)**

**Lo que el código provee:**
- `TokuClient.list_payment_methods`, `get_payment_method`, `delete_payment_method`: Implementados.
- `TokuClient.create_payment_method`: Implementado (no documentado claramente para qué caso).
- `TokuClient.batch_clabe_inscription`: Implementado (camino C - PAC lote).
- `TokuClient.associate_to_subscription`: Implementado, pero con ruta diferente.
- `TokuClient.create_checkout_session` para el camino A: Implementado pero bloqueado.

**Discrepancia de endpoint (crítica):**
- Workflow: `POST /subscriptions/associate/payment-method` con body `{id_subscription, id_payment_method, payment_scope}`
- Código: `POST /payment-methods/{pm_id}/subscriptions` via `associate_to_subscription(pm_id, data)`

Son rutas diferentes. El código usa el `pm_id` como path param, no como campo del body. Si la ruta correcta es la del workflow, el cliente actual llamaría a un endpoint inexistente o incorrecto. Esta discrepancia afecta a alta-socio, link-inscripcion y enroll-payment-method.

**Lo que no existe:**
- `POST /customer-collection-accounts` (camino B, PAC directo por API) no está en el cliente.
- `GET /customer-collection-accounts?customer=` no está en el cliente.
- No hay write endpoint en `writes.py` para inscribir un payment method ni para associarlo a una subscription.
- No hay `GET /cl/checkout-sessions/{id}` en el cliente (solo `create_checkout_session`).
- No hay `PATCH /cl/checkout-sessions/{id}` en el cliente.

---

### 10. reconcile-payment.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- Transactions y invoices se sincronizan a `source_records` y a `tk_transactions` / `tk_invoices`.
- El rate limit de 1 req/s para transactions está implementado en `read_only_provider_sync.py`.
- El payload completo (incluidos `payment_intents`) se guarda en `raw_payload` de `TokuTransaction`.

**Lo que no existe:**
- No hay tabla `toku_payment_intents` (ni `stg_toku_payment_intents`). Los payment intents N:M están enterrados dentro del `raw_payload` de la transaction.
- Sin tabla puente para `payment_intents`, la cuadratura `Σ pi.amount` descrita en el workflow no puede hacerse con SQL eficiente.
- El sync de transactions no filtra por `start_date`/`end_date`: siempre recorre todas las páginas desde el principio sin ventana de fecha.
- No hay tabla `aplicacion_pago`.
- El sync actual de Sheets (mencionado en el workflow como que guarda solo el primer payment intent) ya no existe, pero el problema persiste en la tabla `TokuPayment` del canal: tiene `invoice_id` como campo único, lo que impide modelar múltiples payment intents por transaction.

**Riesgo operativo:** El análisis de cuadratura (¿se pagó?, ¿cuánto?, ¿con qué medio?) requiere parsear JSONB anidado en lugar de hacer JOINs tabulares, lo que hace frágil cualquier reporte.

---

### 11. seguimiento-cobros.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- Invoices y transactions se sincronizan con sus payloads completos.
- `TokuInvoice` tiene `status`, `general_status` (como `status` en el campo del canal), `due_date`, `subscription_id`.
- `TokuTransaction` tiene `status`, `amount`, `transaction_date`.
- El campo `in_progress` de las invoices no se promueve a columna indexada en `tk_invoices`; está solo en `raw_payload`.

**Lo que no existe:**
- No hay tabla `toku_payment_intents`, sin la cual la cuadratura por cuota es imposible en SQL directo.
- No hay vista `v_toku_cuotas_mensuales`.
- No hay lógica de cuadratura (pagado_ok = Σ pi.amount de transacciones SUCCESS − reversas).
- El campo `in_progress` no está en la tabla de canal como columna promovida: no se puede filtrar eficientemente.
- El campo `general_status` no está como columna separada en `tk_invoices` (la tabla tiene `status` solamente, que corresponde al `status` de la invoice, no al `general_status`).
- Transactions no se sincronizan con ventana de fecha incremental.
- No hay lógica de alerta por `in_progress` colgado por más de 3 días.
- `id_payout` no se promueve a columna indexada en `tk_transactions`.

**Discrepancia en modelo de canal:** `TokuInvoice.status` no indica si mapea a `general_status` o `status` del payload de Toku. Son campos distintos (Toku tiene 13 valores de `status` detallados y un `general_status` con valores como `paid`, `unpaid`, `void`). El campo `general_status` es el indicador operativo clave y no está promovido.

---

### 12. sync-toku.md

**Estado: ⚠️ Parcial**

**Lo que el código provee:**
- Sync completo (full) de 6 recursos: customers, subscriptions, invoices, transactions, payment_methods, payments.
- Paginación cursor para customers/subscriptions/invoices; paginación por página para transactions/payment_methods.
- Rate limit de 1 req/s para transactions.
- Upsert idempotente en `source_records` por `(source, resource_type, external_id)`.
- Upsert en tablas de canal `tk_*`.
- `SyncRun` registrado con status, records_processed, error_message sanitizado (secretos redactados).
- Sanitización de campos sensibles (`card_number`, `cvv`, etc.) antes de persistir.
- `toku_read_retries` con backoff para 429/503/ReadTimeout en GETs.
- `toku_writes_enabled` flag global.

**Lo que no existe (vs. lo que propone el workflow):**

1. **Sin incremental**: el sync siempre hace full pagination desde la primera página. No usa ventanas de fecha (`start_date = última_corrida − 1 día`) para ningún recurso.

2. **Sin checkpoint**: no existe tabla `sync_checkpoints`. Si el proceso se corta, la siguiente corrida reinicia desde la página 1.

3. **Sin reconciliación semanal**: no hay lógica de comparación por `payload_hash` para detectar cambios ni de marcado `deleted_in_source_at` para recursos desaparecidos.

4. **Sin `stg_toku_payment_intents`**: los payment intents no se extraen del payload de transactions a una tabla puente.

5. **Sin receptor de webhooks**: la firma HMAC-SHA256 documentada (`Toku-Signature`) no tiene código de verificación. No hay endpoint `/webhooks/toku` ni tabla `stg_toku_webhook_events`.

6. **Estructura de módulos diferente**: el workflow propone `app/integrations/toku/` con archivos separados por recurso (`customers.py`, `subscriptions.py`, `invoices.py`, etc.) y `app/sync/toku/` con `staging.py`, `jobs.py`, `normalize.py`. El código actual tiene todo en `app/services/toku_sync.py` y `app/integrations/toku/client.py` (monolítico).

7. **Sin retries en writes**: los métodos `_post`, `_put`, `_delete` del cliente no tienen lógica de retry. Solo los GETs tienen retries. El workflow recomienda retries con backoff para `429`, `5xx` y `TK20401`/`TK00600` también en upserts idempotentes.

8. **Sin `toku_account_key` en uso**: `toku_account_key` está en `settings` pero no se usa en el cliente (solo `toku_api_key`). El workflow menciona `id_account` para el Checkout Session.

9. **Transactions sin filtros de fecha**: `list_transactions` solo acepta `page` y `page_size`. El incremento por ventana descrito en el workflow (`start_date`/`end_date`) no está implementado.

---

## Impacto de BLQ-TK-01

BLQ-TK-01 describe que Toku no ha configurado el `flow_name` de inscripción en la cuenta. Esto bloquea todo uso del Checkout Session en modo `ENROLLMENT`.

Los workflows afectados directamente:

| Workflow | Bloqueo |
|---|---|
| `alta-socio.md` | Paso 5 (Checkout Session ENROLLMENT) completamente bloqueado. La alternativa documentada (Customer Portal) no soporta `ids_subscription` |
| `link-inscripcion.md` | Ambos casos (A y B) dependen del Checkout ENROLLMENT |
| `enroll-payment-method.md` | Camino A (inscripción por Checkout) bloqueado. Camino B (PAC por API) no está bloqueado por BLQ-TK-01 pero tampoco está implementado en el cliente |

Los workflows NO afectados por BLQ-TK-01:

| Workflow | Razon |
|---|---|
| `create-customer.md` | Solo usa `POST /customers` (sin Checkout) |
| `create-subscription.md` | Solo usa `POST /subscriptions` |
| `create-invoice.md` | Solo usa `POST /invoices` |
| `cancel-subscription.md` | Usa `POST /status` y `DELETE` |
| `cambiar-monto.md` | Usa `PUT /subscriptions` y `PUT /invoices` |
| `editar-socio.md` | Usa `PUT /customers/{id}` |
| `reconcile-payment.md` | Solo lee transactions e invoices |
| `seguimiento-cobros.md` | Solo lee invoices y transactions |
| `sync-toku.md` | Lectura; sin Checkout |

**Nota sobre la alternativa del Customer Portal:** El workflow alta-socio.md menciona que mientras esté bloqueado, se puede usar `POST /v2/customer-portal-sessions` con `flow_name: "0"`. Este endpoint no existe en el cliente actual.

---

## Pendientes T-x

Las siguientes preguntas abiertas se derivan directamente de los workflows y del contraste con el código. Se agrupan por tipo.

### Sobre endpoints y contratos de API

| ID | Pregunta | Origen | Bloqueo |
|---|---|---|---|
| T-A1 | ¿Puede Toku configurar el flujo de inscripción (`flow_name`) para tarjeta (`transbank_oneclick`) y PAC en la cuenta de producción? | alta-socio.md § 9 | Bloquea alta-socio, link-inscripcion, enroll-payment-method |
| T-A2 | ¿La ruta de creación del Checkout Session es `POST /cl/checkout-sessions`? ¿El campo con la URL del checkout es `url`? | alta-socio.md § 4 | Bloquea prueba del paso 5 del alta |
| T-A4 | ¿El Checkout ENROLLMENT asocia automáticamente el `pm_` a las `ids_subscription` pasadas? ¿O siempre hay que llamar a `POST /subscriptions/associate/payment-method`? | alta-socio.md § 9 | Define si el paso 8 del alta es necesario |
| T-A7 | ¿El `external_id` de la organización en Toku es el RUT del socio (`customer_external_id_parameter`)? | alta-socio.md § 9, create-customer.md | Define clave de upsert de customers |
| T-ASSOC | ¿Cuál es el endpoint correcto para asociar un payment method a una subscription: `POST /subscriptions/associate/payment-method` (como dice el workflow) o `POST /payment-methods/{pm_id}/subscriptions` (como está codificado)? | enroll-payment-method.md, alta-socio.md | Crítico: el cliente puede estar llamando al endpoint incorrecto |
| T-L1 | Cuando un Customer tiene dos medios asociados a la misma Subscription, ¿cuál usa Toku para cobrar? ¿Se puede eliminar el viejo en cuanto el nuevo queda `chargeable`? | link-inscripcion.md § 7 | Define cuándo hacer DELETE del pm viejo |
| T-L2 | ¿En qué dominio vive el Checkout de Toku? ¿Es fijo o por cuenta? | link-inscripcion.md § 7 | Lista de hosts permitidos |
| T-L3 | Al reactivar una Subscription pausada por cuotas impagas, ¿Toku intenta cobrar esas cuotas con el medio nuevo? | link-inscripcion.md § 7 | Expectativa al socio |

### Sobre el comportamiento de transactions

| ID | Pregunta | Origen | Impacto |
|---|---|---|---|
| T-S1 | ¿`start_date`/`end_date` de `GET /transactions` filtran por `transaction_date` o por `initialization_date`? | seguimiento-cobros.md § 7 | Define ventana usable para incremental |
| T-S2 | ¿Qué valores tiene `payment_intent.status` y cuáles cuentan como pago efectivo vs. reversa? | seguimiento-cobros.md § 7 | Define la fórmula de cuadratura |
| T-S3 | ¿Existe el endpoint *List Payouts*? ¿Cuál es su ruta y formato? | reconcile-payment.md § 5, seguimiento-cobros.md § 7 | Seguimiento de liquidaciones |
| T-S4 | ¿Cuál es el calendario de reintentos de Toku y cómo decrece `remaining_collection_attempts`? | seguimiento-cobros.md § 7 | Alerta de cobros colgados y flujo de recuperación |

### Sobre cambio de monto

| ID | Pregunta | Origen | Impacto |
|---|---|---|---|
| T-M1 | ¿Cambiar `amount` en la Subscription afecta un mandato PAC con tope de monto? | cambiar-monto.md § 6 | Riesgo de invalidar el mandato PAC |
| T-M2 | ¿Un `PUT /invoices` sobre una cuota ya enviada al banco (PAC) sin `in_progress` puede generar cobro por el monto anterior? | cambiar-monto.md § 6 | Riesgo de cobro duplicado |

### Sobre otras pendientes del alta

| ID | Pregunta | Origen | Impacto |
|---|---|---|---|
| T-A3 | ¿El Checkout ENROLLMENT acepta una Subscription en estado `PAUSED`? | alta-socio.md § 9 | Define si la Subscription se puede pausar antes de la sesión |
| T-A5 | ¿Toku genera la primera Invoice al crear la Subscription o recién `creation_lead_days` antes del primer vencimiento? | alta-socio.md § 9, create-subscription.md § 9 | Define si el paso 4b puede encontrar cuotas al pausar |
| T-A6 | ¿Qué webhook llega al terminar la inscripción: `payment_method.attached_products`, `payment_method.attached` o ambos? | alta-socio.md § 9 | Define el disparador de confirmación del alta |
