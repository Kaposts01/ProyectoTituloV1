# Diferencias detectadas

> Revisión del 2026-10-12: doc oficial (virtualpos.readme.io) vs borrador `VirtualPOS_API_Documentacion.md` (2026-08-14) vs colección `VirtualPOS API.postman_collection.json` (2026-09-02).
> Regla: ante diferencias manda la **doc oficial**. Lo que la doc oficial contradice internamente queda marcado como **"verificar en sandbox"**.

## A. Doc oficial vs borrador (cambios en la doc oficial)

| # | Qué cambió | Dónde | Acción |
| --- | --- | --- | --- |
| A1 | Nuevo campo opcional **`rule_set_uuid`** | *Crear un objeto Payment* | ✅ Incorporado en [payments.md](payments.md#crear-un-objeto-payment) y Postman |
| A2 | Nueva página **Webcheckout Ruleset** (rule sets por monto, gestionados en el portal) | Información general | ✅ Incorporado en [payments.md](payments.md#webcheckout-ruleset) |
| A3 | Webhook y Ruleset ahora están en "Información general" del menú | Navegación | Solo organización |
| A4 | Slugs de URL distintos a los del índice del borrador (ej. `paginacion-para-el-listado-de-objetos`, `objeto-suscription-1`, `objeto-charge-1`) | Links | ✅ Links actualizados |

Sin cambios: los otros 34 endpoints, el catálogo de errores (111 códigos, E-001…E-116) y de rechazos (27 códigos).

## B. Colección Postman vs doc oficial (corregido en v2)

| # | Problema en la colección original | Corrección en v2 |
| --- | --- | --- |
| B1 | `PUT {{base_url}}/v3/client/:client_uuid}` — llave `}` sobrante en la URL y en el nombre de la variable | `/v3/client/{{client_uuid}}` |
| B2 | *Intentos de pago*: `payment_uuid = 2026-08-29` (una fecha) | `{{payment_uuid}}` |
| B3 | *Crear Payment* envía `payment_type_code` (es un campo **de respuesta**) | Eliminado; agregados `return_url`, `callback_url`, `rule_set_uuid` (deshabilitado) |
| B4 | *Autorizar Payment* envía `cardholder_name` (no documentado) y número con espacios | Eliminado; número sin espacios |
| B5 | *Reintentar Charge* usa `{{charge_id}}` y el resto `:charge_id` con IDs fijos | Todo con variables `{{...}}` que se llenan solas |
| B6 | Faltan `page`/`limit` y filtros en listados (Payments, Plans, Charges, Clients) | Agregados (deshabilitados por defecto) |
| B7 | Faltan los 4 endpoints de **Payout** | Carpeta *Payout* (requiere mTLS) |
| B8 | Bodies con comentarios `//` (JSON inválido para el script de firma) | Opciones movidas a la descripción |
| B9 | Datos personales reales (email, RUT, teléfono) dentro de la colección | Movidos a variables de entorno `test_*` |
| B10 | Firma: `headers.add` puede duplicar el header si ya existe | `headers.upsert` |
| B11 | Sin ejemplos de respuesta ni descripciones | Ejemplos oficiales 200/400 y descripción en cada request |
| B12 | Firma solo con `{api_key}` en todos los métodos | Modo configurable `vpos_sign_mode` = `api_key_only` (default, probado) o `body` (doc oficial) |

## C. Contradicciones dentro de la doc oficial (verificar en sandbox)

| # | Contradicción | Dónde | Cómo lo tratamos |
| --- | --- | --- | --- |
| C1 | Firma POST: "API KEY junto con los atributos requeridos" vs. en la práctica funciona solo `{api_key}` | Autenticación | Dos modos en Postman; backend: `body` con fallback |
| C2 | `gender_id` / `social_id_type`: tipo string con enum de texto, pero la descripción dice 1/2/4 | Crear Client | Enviar **números** (probado por ti) |
| C3 | `birth_date` "YYYY-MMDD" | Crear Client | Usar `YYYY-MM-DD` |
| C4 | `uuid` declarado como *query*, pero está en el path | Recuperar/Actualizar Client | Path |
| C5 | Body de Actualizar Client: ejemplo envuelto en `{"client": {...}}`, schema vacío | Actualizar Client | Postman v2 usa campos en la raíz (lo que tú usabas); probar la variante `client` |
| C6 | `payments` es objeto (no array) en el ejemplo de Listar Payments | Listar Payments | Parser acepta ambos |
| C7 | `automatic_renewal` (Crear Suscription) vs `renewal` (Recuperar/Listar) | Suscription | Normalizar |
| C8 | `social_id` "sin puntos ni guion" en Suscription; con guion en Payment y Client | Suscription | Respetar cada endpoint |
| C9 | `E-104`: `service_id` solo letras y espacios, pero el ejemplo usa `12312312-3` | Suscription | Verificar |
| C10 | `card_on_file`: request `LOCAL_ISSUER`/`NO_AUTHENTICATION`; respuesta `"F"` | Suscription | Guardar texto crudo |
| C11 | Frecuencias: objeto Plan lista Semestral/Anual; enum de Crear Plan no | Plan | Solo Diario/Semanal/Mensual |
| C12 | Ejemplo de Charge con `id_...` en Crear, `cid_...` en el resto | Charge | Tratar el ID como opaco |
| C13 | `rejected_object.code` vs `rejected_object.error_code` | Objeto Rechazo | Leer ambos |
| C14 | Paginación: "page=1 omite el primer resultado" | Paginación | Asumir base 1; verificar |
| C15 | Header `Authentication` en *Obtener saldo disponible* (Payout) | Payout | Usar `Authorization` |
| C16 | Firma con estructura `tef` para *consultar* payouts (GET sin body) | Payout | Probar `{api_key}` primero |
| C17 | `status` de payout `pending` (minúscula) en ejemplos vs `PENDING` en el objeto; `create_at` vs `created_at` en el webhook | Payout | Normalizar |
| C18 | Listar Clients: comillas tipográficas `“”` en el ejemplo (JSON inválido) | Clients | Errata del ejemplo |
| C19 | Ejemplos 400 vacíos (`{}`) en Plans, Suscriptions, Charges, Payouts | Varios | Esperar formato del Objeto Error |

## D. Vacíos de documentación (No confirmado en la documentación oficial de VirtualPOS)

- Webhook para cobros de Charges / estados de suscripción posteriores a la inscripción.
- Formato del body del webhook de Payment y del callback de Suscription; política de reintentos.
- Rate limits y códigos 5xx/429.
- Idempotencia de *Crear Payment* y *Crear Suscription*.
- Endpoints de reembolso/anulación de un Payment pagado; editar/eliminar Plan.
- Relación Client ↔ Suscription / Payment (no hay `client_uuid`).
- `page`/`limit` como parámetros en abonos (`sales`, `withholdings`).
- Filtros `charge_date_from`/`charge_date_to` en Listar Charges (solo aparecen en errores E-093…E-095).
- Contenido de `formData` y endpoint de backend del Quick Checkout.

- **Motivo de rechazo de un Charge:** el Objeto Charge no lo trae. Solo se obtiene vía `payment.order.uuid` → `GET /v3/payment/{uuid}/attempts`. Falta confirmar que un cargo rechazado incluye `payment.order.uuid` (el ejemplo de *Recuperar Charge* no trae `payment`).
- **Códigos del adquirente** en `authorization_attempts_cards[].response_code` (ej. `-2122` Klap) no tienen catálogo oficial.
- **Reintentos automáticos** ("hasta 3, configurable") y **cambio de tarjeta automático**: no se explica cómo funcionan ni cómo interactúan con `/retry`.
- **Link de cambio de tarjeta:** duración, envío al socio, callback al cambiar la tarjeta y efecto sobre los cargos rechazados: no documentados.
- **Edición de suscripción:** no existe un endpoint para editar `suscription.client` ni el `plan_id`. Tampoco se documenta si editar el Client se propaga a la suscripción (prueba en Postman: `03 · Editar socio` → ES-4).

> Cuando confirmes algo en sandbox, actualiza esta tabla y el archivo del recurso.
