# Auditoría: Postman y notas internas vs documentación oficial

Fecha: 2026-10-12 · Archivo revisado: `Toku API.postman_collection.json` (7 carpetas, 41 requests) y `Toku_API_Documentacion.md`.

Leyenda de severidad: 🔴 rompe la request · 🟠 resultado incorrecto o riesgo · 🟡 limpieza / consistencia.

## 1. Colección Postman

### Carpeta "Payment Method" (la más afectada)

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| P1 | Obtener Payment Method | `GET /invoices?page_size=100` | `GET /payment-methods/{public_id_payment_method}` | 🔴 | Cambiar la URL a `{{base_url}}/payment-methods/:payment_method_id` |
| P2 | Eliminar Payment Method | `DELETE /invoices?page_size=100` | `DELETE /payment-methods?id_payment_method={id}[&force_status_change=false]` | 🔴 | ⚠️ Hoy apunta a `DELETE /invoices`. Corregir **antes** de volver a ejecutarla |
| P3 | Asociar Payment Method a Subscription | `POST /invoices?page_size=100` | `POST /subscriptions/associate/payment-method` | 🔴 | URL + body `{id_subscription, id_payment_method, payment_scope}` |
| P4 | Asociar Payment Methods a Subscriptions | `POST /invoices?page_size=100` | `POST /subscriptions/associate/payment-method/batch` | 🔴 | URL + body `{data:[…]}` (máx. 500) |
| P5 | Actualizar Payment Method | `PUT /payment-methods?page=1&page_size=100` | **No existe en la referencia pública** | 🟠 | Eliminar la request o moverla a la carpeta "_No documentado" |
| P6 | Editar un Payment Method | `PUT /invoices?page_size=100` | **No existe en la referencia pública** | 🔴 | Eliminar |
| P7 | Crear Payment Method | `POST /payment-methods` (body con `id_customer: 0`, `id_organization`) | **No existe en la referencia pública** (nota interna: `x-internal`, requiere IDs numéricos internos) | 🟠 | Mover a "_No documentado" con la advertencia "No confirmado en la documentación oficial de Toku" |
| P8 | Crear un Payment Method (ruta interna) | `POST /invoices?page_size=100` | Igual que P7 | 🔴 | Eliminar (duplicado de P7 y con la URL rota) |
| P9 | Obtener un Payment Method (ruta interna) | `GET /invoices?page_size=100` | Ruta obsoleta oficial: `GET /payment_method?id=` o `?external_id=` | 🔴 | Renombrarla a "Obtener Payment Method (obsoleto)" con la URL correcta, o eliminarla |
| P10 | Eliminar un Payment Method (ruta interna) | `DELETE /invoices?page_size=100` | Igual que P2 | 🔴 | Eliminar (duplicado; ⚠️ hoy borra invoices) |
| P11 | Inscribir cuentas CLABE por lote | `POST /payment-methods?page=1&page_size=100` | Endpoint **solo de México** (`bulk_inscriptions_public`) | 🟡 | Eliminar (no aplica a Chile) |
| P12 | Listar los Payment Methods de un Customer | `GET /payment-methods?page=1&page_size=100` | `GET /payment-methods?id_customer={cus}` | 🟠 | Agregar el query `id_customer={{customer_id}}` |
| P13 | Listar Payment Methods con datos del Customer | Igual a "Listar Payment Methods" | El listado **siempre** trae el Customer (forma agregada) | 🟡 | Eliminar el duplicado |

### Carpeta "Subscription"

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| S1 | Listar Subscriptions | `?page=1&page_size=100` | Cursor: `page_size` + `next_cursor` | 🟠 | Quitar `page`, agregar `next_cursor` (deshabilitado) |
| S2 | Editar Subscription | Body con `"amount": "6000"`, `"creation_lead_days": "10"`, `"is_recurring": "True"` | `number`, `integer`, `boolean` | 🔴 | `"amount": 6000`, `"creation_lead_days": 10`, `"is_recurring": true` |
| S3 | Crear Subscription | Solo `customer`, `product_id`, `amount`, `currency_code` | Correcto (crea una no recurrente) | 🟡 | Agregar un ejemplo recurrente con `frequency`/`interval`/`due_day` en la raíz |
| S4 | Path params | `:customer_id`, `:encrypted_subscription_id` | Coinciden con la doc | ✅ | — |

### Carpeta "Invoices"

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| I1 | Crear Invoice | `POST /invoices?page_size=100` | Sin query params | 🟡 | Quitar `?page_size=100` |
| I3 | Anular Invoice | URL con un salto de línea al final (`/void\n`) | `POST /invoices/{encrypted_invoice_id}/void` | 🟠 | Limpiar la URL; renombrar `:invoice_id` → `:encrypted_invoice_id` |
| I4 | Anular Invoice | `POST` + `{"delete_invoice": false}` | Correcto | ✅ | (La nota interna que decía `PUT` estaba mal; ver N2) |
| I5 | Eliminar Invoice | `:invoice_id` | `:encrypted_invoice_id` | 🟡 | Homogeneizar nombre |
| I6 | Listar Invoices | Sin filtros de ejemplo | Hay 9 filtros | 🟡 | Agregar filtros deshabilitados: `customer_id`, `subscription_id`, `general_status`, `in_progress`, `due_date_from`, `start_date`, `end_date`, `next_cursor` |

### Carpeta "Customer"

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| C1 | Buscar Customer | `?mail=pruebas@futureflow.cl` | `mail`, `external_id` o `rfc` | 🟡 | Agregar `external_id` como opción principal |
| C2 | Editar Customer | Body con `rfc`, `fiscal_regime`, `tax_zip_code` (México) | Válidos, pero no aplican a Chile | 🟡 | Quitarlos del ejemplo; **nunca** incluir `external_id` (TK30411) |
| C3 | Crear Customer | Body con RUT, teléfono y mail **reales** | — | 🟠 | Reemplazarlos por datos ficticios o variables (`{{test_rut}}`…). La colección puede terminar en Git |
| C4 | Path param | `:customer_id` | `encrypted_customer_id` (`cus_…`) | 🟡 | Opcional: renombrar por consistencia con la doc |

### Carpeta "Transactions"

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| T1 | Listar Transactions | Solo `page`, `page_size` | 16 filtros | 🟡 | Agregar deshabilitados: `start_date`, `end_date`, `status`, `types`, `id_invoice`, `id_customer`, `id_payout` |
| T2 | — | Falta | `GET /transactions/{public_id_transaction}` | 🟡 | Agregar "Obtener Transaction" |

### Carpeta "Payment"

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| X1 | "Listar Customers Copy" | `GET /organization/payments` | **No existe en la referencia pública** | 🟠 | Eliminar la carpeta, o renombrarla y moverla a "_No documentado". El recurso "Payment" no existe: los pagos son Transactions |

### Carpeta "Checkout Session"

| # | Request | Hoy | Oficial | Sev. | Corrección |
|---|---|---|---|---|---|
| CS1 | Crear Checkout Session | `POST /cl/checkout-sessions` | **[No confirmado]**: la página oficial no mostró la ruta (el OpenAPI vino truncado) | 🟡 | Verificar en la UI de la doc. El body (`mode`, `billing_data`, `customer_data`) coincide con el schema |
| CS2 | Body | Contiene RUT y mail reales | — | 🟠 | Usar variables |

### Nivel colección

| # | Hallazgo | Sev. | Corrección |
|---|---|---|---|
| G1 | No hay variables de colección; los IDs están escritos a mano | 🟡 | Definir variables (ver §3) |
| G2 | El header `x-api-key` se repite en las 41 requests | 🟡 | Moverlo a **Auth de colección** (tipo API Key, header `x-api-key`, valor `{{api_key}}`) y quitarlo de cada request |
| G3 | No se envía `x-api-version` | 🟡 | Agregar el header de colección `x-api-version: {{api_version}}` (dejarlo **deshabilitado** hasta validar los mappers) |
| G4 | Header `Content-Type` en los GET/DELETE sin body | 🟡 | Inofensivo; se puede dejar |
| G5 | El environment se llama `Toku_Sandbox` pero apunta a producción | 🟠 | Renombrarlo a `Toku Producción` |
| G6 | Faltan endpoints importantes (§2) | 🟡 | Agregarlos |

## 2. Endpoints que faltan en Postman

| Carpeta | Request | Endpoint |
|---|---|---|
| Payment Methods | Listar Customer Collection Accounts | `GET /customer-collection-accounts?customer={{customer_id}}` |
| Payment Methods | Crear Customer Collection Account (PAC) | `POST /customer-collection-accounts` |
| Payment Methods | Eliminar Customer Collection Account | ver doc `delete_customer_collection_account_endpoint` |
| Transactions | Obtener Transaction | `GET /transactions/:transaction_id` |
| Webhooks | Listar Webhook Endpoints | `GET /webhook_endpoints` |
| Webhooks | Crear Webhook Endpoint | `POST /webhook_endpoints` |
| Webhooks | Editar Webhook Endpoint | `PUT /webhook_endpoints/:webhook_endpoint_id` |

## 3. Variables propuestas

| Variable | Dónde | Tipo | Ejemplo |
|---|---|---|---|
| `base_url` | Environment | default | `https://api.trytoku.com` |
| `api_key` | Environment | **secret** (solo *current value*) | — |
| `api_version` | Environment | default | `2026-10-08` |
| `account_id` | Environment | default | `acc_…` |
| `customer_id` | Colección | default | `cus_…` |
| `customer_external_id` | Colección | default | `TEST-Client-001` |
| `subscription_id` | Colección | default | `sub_…` |
| `product_id` | Colección | default | `TEST-SOCIO-0001-MENSUAL` |
| `invoice_id` | Colección | default | `in_…` |
| `invoice_external_id` | Colección | default | `TEST-CUOTA-000123` |
| `payment_method_id` | Colección | default | `pm_…` |
| `transaction_id` | Colección | default | — |
| `webhook_endpoint_id` | Colección | default | `whe_…` |

**[Recomendación]** Agregar scripts de *Tests* en los POST de creación para capturar el ID automáticamente, por ejemplo en Crear Customer: `pm.collectionVariables.set("customer_id", pm.response.json().id);`.

## 4. Estructura propuesta

```text
Toku API
├── Customers                (7)
├── Subscriptions            (8)
├── Invoices                 (9)
├── Payment Methods          (asociar ×2, listar, obtener, eliminar)
│   └── Collection Accounts  (listar, crear, eliminar)
├── Transactions             (listar, obtener)
├── Webhooks                 (listar, crear, editar)
├── Checkout Sessions        (crear)
└── _No documentado          (POST /payment-methods, /organization/payments) ← solo referencia
```

## 5. Notas internas (memoria del proyecto / `.md`)

| # | Nota interna | Oficial | Acción |
|---|---|---|---|
| N1 | "Paso 3 — `POST /customers/{id}/collection-account`" | `POST /customer-collection-accounts` con `customer` en el body | Corregido en [enroll-payment-method.md](workflows/enroll-payment-method.md) |
| N2 | "`PUT /invoices/{id}/void` borra el registro salvo `delete_invoice: false`" | **`POST`** `/invoices/{id}/void`. El comportamiento de `delete_invoice` sí es correcto | Método corregido |
| N3 | "Paginación por cursor en Customers, Invoices y Subscriptions; numérica en Payment Methods y Transactions" | ✅ Correcto | — |
| N4 | "`external_id` inmutable en PUT → 409 (TK30411)" | ✅ Coincide con el catálogo (el schema del PUT igual lista `external_id`) | — |
| N5 | "Subscriptions idempotente por (Account, product_id)" | ✅ | — |
| N6 | "No existe sandbox" | ✅ Confirmado ("un único ambiente productivo") | — |
| N7 | `Toku_API_Documentacion.md`: "`TOKU_API_KEY_SANDBOX` habilita llamadas sandbox" | No hay sandbox documentado | Revisar `ApiCore.js`: esa property no debería apuntar a otra URL. Actualizar el `.md` |
| N8 | `Toku_API_Documentacion.md`: "versión de contrato 2026-07-23" | Las páginas hoy declaran **2026-10-08** | Actualizar; revalidar los mappers antes de fijar `x-api-version` |
| N9 | `Toku_API_Documentacion.md`: `Transaction.js` guarda solo `payment_intents[0]` | Una Transaction puede tener N intents | Pendiente técnico: ver [reconcile-payment.md](workflows/reconcile-payment.md) |
| N10 | "`skip_message_trigger: true` en producción" | Es un campo de **Checkout Session**, no de todos los endpoints | Aclarado en [authentication.md](authentication.md) |

## 6. ¿Qué hacer con `Toku_API_Documentacion.md`?

Es la referencia del **sync de Apps Script** (mappers, hojas y funciones). No se duplica con `docs/toku/`, que es la referencia de la **API**. **[Recomendación]** Mantenerlo, actualizar N7 y N8, y agregar al inicio un enlace a `docs/toku/README.md`.

## 7. Estado: aplicado (2026-10-12)

La colección se regeneró completa a partir de esta auditoría. El original quedó respaldado en `Toku API.postman_collection.backup-2026-10-12.json`.

- 49 requests en 8 carpetas: Customers, Subscriptions, Invoices, Payment Methods (+ Collection Accounts, + PAC por lote), Transactions, Webhooks, Checkout Sessions y `_No documentado`.
- Auth de colección (`x-api-key` = `{{api_key}}`). `x-api-version` y `x-account-key` van deshabilitados en cada request.
- Todos los query params documentados (los opcionales, deshabilitados) y todos los campos de body (los opcionales, comentados con `//`).
- Scripts de Tests que capturan `customer_id`, `subscription_id`, `invoice_id`, `payment_method_id`, `transaction_id`, `webhook_endpoint_id` y `checkout_session_id`.
- Se eliminaron los datos personales reales de los bodies.
- Se agregó `Toku API.postman_environment.json` (Toku Producción, con `api_key` vacía de tipo secret).
- Rutas de Checkout Session: actualizar y expirar están confirmadas (`/{country_code}/checkout-sessions/{id}`); crear y obtener se **infieren** de ese patrón.

## 8. Carpeta "00 · Alta de socio (flujo)" (2026-10-12)

Se agregó al inicio de la colección una carpeta de 11 requests (TA-1…TA-9 encadenados para el Collection Runner, más TA-L1 y TA-L2 de limpieza manual) que implementa [workflows/alta-socio.md](workflows/alta-socio.md). Nuevas variables de colección `alta_*` y `checkout_url`. El resto de la colección no cambió; respaldo previo en `Toku API.postman_collection.backup-pre-alta-socio.json`.

- **Protección de producción:** los requests que escriben (TA-1, TA-3, TA-L1, TA-L2) se cancelan si `alta_external_id` o `alta_product_id` no empiezan con `TEST-`.
- **Bloqueante:** TA-5 necesita `alta_flow_name`, que Toku debe configurar.

## 9. Carpeta "01 · Link de inscripción" (2026-10-12)

Se agregó después de la carpeta de alta, con dos subcarpetas que implementan [workflows/link-inscripcion.md](workflows/link-inscripcion.md): **A · Alta pendiente** (LA-1…LA-3: reutilizar, extender o recrear la Checkout Session) y **B · Socio existente** (LB-1…LB-6 encadenados, LB-7 manual). Nuevas variables de colección `li_*`. Respaldo previo en `Toku API.postman_collection.backup-pre-link-inscripcion.json`.

- Las escrituras se cancelan si `alta_product_id` o `li_product_id` no empiezan con `TEST-`.
- LB-3 imprime el host del Checkout para completar la lista permitida de la capa común (T-L2).

## 10. Carpeta "02 · Editar socio" (2026-10-12)

Se agregó después de "01 · Link de inscripción": 4 requests (ET-1…ET-4) que implementan [workflows/editar-socio.md](workflows/editar-socio.md). Nuevas variables de colección `edit_*`. Respaldo previo en `Toku API.postman_collection.backup-pre-editar-socio.json`.

- ET-3 (`PUT /customers/{id}`) se cancela si el `external_id` del Customer no empieza con `TEST-` o si el body incluye `external_id` (TK30411).

## 11. Carpeta "03 · Cambiar monto" (2026-10-12)

Se agregó después de "02 · Editar socio": 5 requests (CT-1…CT-5) que implementan [workflows/cambiar-monto.md](workflows/cambiar-monto.md): `PUT` del `amount` de la Subscription y corrección de las cuotas no pagadas que no estén en cobro. Nuevas variables de colección `cm_*`. Respaldo previo en `Toku API.postman_collection.backup-pre-cambiar-monto.json`.

- CT-2 y CT-4 (los `PUT`) se cancelan si `cm_product_id` no empieza con `TEST-`.

## 12. Carpeta "04 · Seguimiento de cobros" (2026-10-12)

Se agregó después de "03 · Cambiar monto": 5 requests de solo lectura (ST-1…ST-5) que implementan [workflows/seguimiento-cobros.md](workflows/seguimiento-cobros.md): cuotas con cursor, transacciones con sus Payment Intents, cuadratura de una cuota y transacciones de su liquidación. Los requests a `/transactions` esperan 1,1 s (límite de 1 req/s). Nuevas variables de colección `st_*`. Respaldo previo en `Toku API.postman_collection.backup-pre-seguimiento-cobros.json`.
