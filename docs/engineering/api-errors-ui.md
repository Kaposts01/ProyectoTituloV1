# Errores de la API en la interfaz

Desde la tanda D35 los errores de `writes.py`, `staging.py`, `security.py` y `scheduler.py` devuelven `detail` como objeto `{"code": "<código_en_inglés>", "message": "<texto en español>"}`. El backend devuelve códigos y el frontend los traduce. El catálogo de códigos del backend está en [`../data/error-codes.md`](../data/error-codes.md) (90 códigos con estado HTTP, ruta y causa). Regla del usuario: todo lo que ve el usuario va en español; los nombres del código, en inglés.

## 1. Orden de búsqueda del texto mostrado

`extractErrorDetail` (en `frontend/src/api.ts`) decide el texto de cada error HTTP. Para un `detail` objeto `{code, message}`:

1. **Catálogo por código**: `apiErrorText(code)` (`frontend/src/i18n/apiErrors.ts`) busca primero en el dominio `apiError` de `i18n/es.ts` y después en `cancellationError` (bajas). El texto es fijo, sin datos variables y sin eco de valores del proveedor.
2. **`detail.message`** del backend (texto fijo en español), solo si el código no está en el catálogo y el mensaje es un texto no vacío.
3. **Texto genérico del estado HTTP** (`httpErrorMessage`: 400, 401, 403, 404, 409, 422, 500, 502, 503) si no hay nada de lo anterior.

Los otros formatos de `detail` no cambian:

- `detail` texto: `translateApiDetail` (dominio `apiDetail` y patrones con datos variables); si no se conoce, el texto tal cual. Sigue vigente para los módulos del backend que aún devuelven texto (login, administración, etc.).
- `detail` lista (422 de FastAPI): campo y motivo traducidos por `validationMessage`.

`ApiError` conserva `status`, el `detail` crudo y `code` (`detail.code` o `null`). Para decidir por código, no por texto, se usa `apiErrorCodeIs(error, "invalid_rut")` (reemplaza a `apiDetailIs`, que comparaba el texto en inglés y se eliminó). Ejemplo: el formulario de clientes de VirtualPOS marca el campo RUT cuando el error es `invalid_rut`.

### Módulos con su propia tabla

`features/billing/billingErrors.ts` (`describeBillingError`) y `features/cancellations/cancellationErrors.ts` (`describeCancellationError`) interpretan sus propios errores por `detail.code` con sus tablas locales y tienen prioridad en sus pantallas (un mismo código, como `subscription_not_found`, puede decir algo distinto en cada contexto). El catálogo genérico solo atiende lo que esos módulos no interpretan.

### CSRF obsoleto

El rechazo de un token CSRF obsoleto llega como `{code: "invalid_csrf_token"}`. `withCsrfRetry` (`features/shared/csrfRetry.ts`) y `mutate` de `billingApi.ts` lo tratan como sesión desactualizada: refrescan el token y reintentan una vez; si vuelve a fallar, `stale_session`. Cualquier otro código estructurado (`not_approver`, `permission_denied`…) nunca se reintenta.

## 2. El catálogo `apiError`

- Vive en `frontend/src/i18n/es.ts`, dominio `apiError`. Las claves son el código normalizado por `label` (sin tildes, minúsculas, `_` y `-` como espacio): `invalid_rut` se guarda como `"invalid rut"`.
- Los textos son claros para el usuario, no técnicos, terminan en punto y no llevan marcadores de datos variables (`{...}`, `<...>`) ni identificadores con `_`. Los códigos cuyo mensaje del backend lleva datos (`channel_disabled`, `job_already_running`, `unknown_channel`, `toku_write_blocked`, `operation_conflict`, `invalid_operation`…) tienen un texto genérico; el detalle fino queda solo en el backend.
- Los códigos `*_requires_reconciliation` (503) indican que la operación se hizo en el proveedor pero quedó pendiente de conciliación en el CRM; el texto pide revisar el registro antes de reintentar.

### Guardián

`frontend/src/i18n/apiErrors.guard.test.ts` lee `docs/data/error-codes.md` y falla si:

- algún código del documento no está en `es.apiError`;
- algún código de `es.apiError` no está en el documento;
- un texto del catálogo tiene marcadores de datos variables, guion bajo o no termina en punto.

Además de los guardianes de identificadores, ortografía y de idioma de `label.test.ts` (palabras inglesas prohibidas) que ya recorren todos los dominios.

## 3. Cómo agregar un código nuevo

1. El backend agrega el código (`{"code": ..., "message": ...}`) y actualiza `docs/data/error-codes.md` (lo exige `tests/test_error_codes.py`).
2. Agrega la entrada en `es.apiError` (`frontend/src/i18n/es.ts`) con la clave normalizada (`"mi codigo nuevo"`) y el texto en español, fijo y sin datos del proveedor ni del usuario. Mantén el orden alfabético.
3. Ejecuta `npm test` en `frontend/`: el guardián confirma que el documento y el catálogo coinciden. Si solo falta la traducción, el usuario verá el `message` del backend como respaldo mientras tanto.
4. Si la pantalla debe reaccionar al código (marcar un campo, reintentar), usa `apiErrorCodeIs(error, "codigo")`; nunca compares el texto.
5. Si el módulo tiene su propia tabla (billing, bajas), agrega el código allí solo si el texto debe ser distinto en ese contexto.

## 4. Pruebas

- `src/api.test.ts`: `{code, message}` con código conocido, código desconocido con y sin mensaje, `detail` texto y lista 422 intactos, `apiErrorCodeIs`.
- `src/i18n/apiErrors.guard.test.ts`: sincronía con el documento.
- `src/test/apiErrors.integration.test.tsx`: formularios y diálogos de VirtualPOS (cliente, plan, suscripción, cargo, cancelación, reintento), Toku, Payku, la ficha de staging y el programador muestran el texto específico y no el genérico.
- `src/test/writes.characterization.test.tsx`: `invalid_rut` marca el campo RUT.
- Pruebas de CSRF en `cancellations.api.test.ts` y `billing.fixes.ui.test.tsx`.

## 5. Pendientes conocidos

- El dominio `apiDetail` de `es.ts` conserva traducciones de textos en inglés de los módulos de `writes`, `staging`, `security` y `scheduler` que ya no se envían; se pueden limpiar cuando se confirme que ningún otro módulo del backend los usa.
- El login (`LoginScreen`) y el perfil siguen leyendo `detail` texto porque `auth.py` no forma parte de la tanda D35.
