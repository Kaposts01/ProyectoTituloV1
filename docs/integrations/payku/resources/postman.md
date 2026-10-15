# Revisión de la colección Postman vs documentación oficial

Archivo revisado: `Payku API.postman_collection.json` (carpeta `Payku`), revisión del **2026-10-12**.
Referencia: documentación oficial v2.1.01 y colección oficial https://docs.payku.com/postman/payku-cl-es.postman_collection.json

---

## 0. Colección v2 corregida (2026-10-12)

Archivo: **`Payku API v2.postman_collection.json`** (en la carpeta `Payku`, junto al original, que **no se modificó**).
Entorno: [postman/payku.postman_environment.example.json](postman/payku.postman_environment.example.json).

### Qué cambia

| Cambio | Detalle |
|---|---|
| Firma | Script de colección nuevo (§ 3.3). Se eliminaron los 8 scripts viejos y todos los headers `Sign`/`Authorization` sueltos. |
| Protección de producción | En `app.payku.cl` solo pasan los GET (y `POST /api/conciliation`). Para escribir hay que poner `allow_prod_writes = yes`. |
| Variables | IDs fijos → `{{client_id}}`, `{{subscription_id}}`, `{{plan_id}}`, `{{card_id}}`, `{{transaction_id}}`… |
| Encadenamiento | Tests que guardan IDs: Crear cliente → `client_id`; Crear suscripción → `subscription_id` + `activation_url`; Obtener suscripción/cliente → `card_id`; Obtener planes → lista URL de notificación y fija `plan_id` si está vacío. |
| Listados | `date_init`, `date_end`, `page`, `per_page` y filtros de estado (deshabilitados). |
| Bodies | Eliminar tarjeta → `{"card": "{{card_id}}"}`; retiro de wallet → 1000; consumo sin `marketplace`/`card` de ejemplo; plan de consumo con URL de notificación hacia `{{webhook_base_url}}`. |
| Test genérico | Falla si HTTP ≥ 400 o `status: "failed"`. |
| 🧪 Validación sandbox | 16 requests, uno por pregunta abierta: Q-01a/b, Q-02a/b, Q-03a/b/c/d, Q-06, Q-09a/b, Q-11a/b, Q-12a/b, Q-20. |
| 🔔 Webhooks (simulación) | 6 payloads documentados hacia nuestro receptor (`{{webhook_base_url}}`), sin auth ni firma. |
| 00 · Alta de socio (flujo) | 8 requests encadenados (PA-1…PA-8) para el Collection Runner: cliente → plan fijo o variable → antidoble cobro → suscripción → primer aporte. Variables `alta_*` en el entorno. Ver [alta-socio.md](workflows/alta-socio.md#10-probarlo-en-postman). Agregado el 2026-10-12; respaldo previo en `Payku API v2.postman_collection.backup-pre-alta-socio.json`. |

| 01 · Link de inscripción | 6 requests en dos subcarpetas: **A · Alta pendiente** (LA-1, LA-2: valida Q-29) y **B · Socio existente** (LB-1…LB-3 encadenados, LB-4 manual). Variables `li_*` en el entorno. Ver [link-inscripcion.md](workflows/link-inscripcion.md#9-probarlo-en-postman). Respaldo previo en `Payku API v2.postman_collection.backup-pre-link-inscripcion.json`. |

| 02 · Editar socio | 5 requests (EP-1…EP-5) para el Collection Runner: edición por ID solo de lo que cambia, verificación de email libre y prueba de Q-30. Variables `edit_*` en el entorno. Ver [editar-socio.md](workflows/editar-socio.md#7-probarlo-en-postman). Respaldo previo en `Payku API v2.postman_collection.backup-pre-editar-socio.json`. |

| 03 · Cambiar monto | 7 requests en dos subcarpetas: **A · Portal** (CA-1, CA-2: verifica el cambio hecho en el portal, Q-32) y **B · Suscripción nueva** (CB-1…CB-5, valida Q-13). Variables `cm_*` en el entorno. Ver [cambiar-monto.md](workflows/cambiar-monto.md#8-probarlo-en-postman). Respaldo previo en `Payku API v2.postman_collection.backup-pre-cambiar-monto.json`. |

| 04 · Seguimiento de cobros | 4 requests de solo lectura (SP-1…SP-4): ciclos V3, cobros de una suscripción, pagos únicos y conciliación; valida Q-06 y Q-08. Variables `sp_*` en el entorno. Ver [seguimiento-cobros.md](workflows/seguimiento-cobros.md#9-probarlo-en-postman). Respaldo previo en `Payku API v2.postman_collection.backup-pre-seguimiento-cobros.json`. |

Total: **101 requests** (49 de la API + 8 del flujo de alta + 6 del link de inscripción + 5 de editar socio + 7 de cambiar monto + 4 de seguimiento + 16 de validación + 6 de webhooks).

### Cómo se verificó
- El script de firma, ejecutado fuera de Postman, reproduce el hash oficial `c9c86202…dd12bb`.
- Se corrió la colección completa con **Newman 6.2.1** contra un servidor simulado local que recalcula la firma: 71/71 requests ejecutados, 213/213 aserciones OK; las firmas coinciden en todos los requests firmados, los headers `X-Sign-*` no llegan al servidor y los webhooks salen sin `Authorization` ni `Sign`.
- Con `url_api` de producción, los POST de Wallet se cancelaron antes de salir; los GET sí se enviaron.
- ⚠️ Nada de esto prueba que **Payku** acepte la firma: eso es lo que resuelven las requests de la carpeta 🧪 en sandbox.

### Cómo usarla (orden sugerido en sandbox)
1. Importa la colección v2 y el entorno; completa los tokens de **sandbox**.
2. Corre **Q-01a** y **Q-01b** → ajusta `sign_trailing_ampersand` según cuál no dé 401.
3. Corre **Q-03a** y **Q-03b** → confirma si los query params van en la firma.
4. Suscripción › Obtener planes → Crear cliente → Crear suscripción → abre `activation_url` y paga con la VISA de prueba `4051 8856 0044 6623`.
5. Obtener suscripción (guarda `card_id`) → resto de la carpeta 🧪.
6. Anota cada resultado en [open-questions.md](open-questions.md).

---

## 1. Resumen

| Aspecto | Estado |
|---|---|
| Cobertura de endpoints | ✅ **49 de 49** endpoints de la documentación de Chile (más los 2 callbacks, que no son requests). |
| Organización por carpetas | ✅ Igual a la documentación oficial (Transacción, Escrow, Anulación, Marketplace, Mall, Evento, Suscripción, Suscripción de consumo, Wallet, Conciliación, Bancos, Métodos de pago). |
| Firma `Sign` a nivel colección | ✅ Bien encaminada (path dinámico + body + query), con diferencias de detalle (§ 3). |
| Scripts antiguos a nivel request | ❌ 8 requests tienen un script viejo que usa otra variable y rutas fijas (§ 3.1). |
| Variables de entorno | ⚠️ Nombres inconsistentes entre la descripción y los scripts; no hay archivo de entorno en la carpeta (§ 4). |
| IDs y paginación | ⚠️ IDs fijos en bodies y paths; listados sin `page`/`per_page`/fechas (§ 5). |
| Riesgo operativo | ❌ Requests que mueven dinero sin protección (§ 6). |

---

## 2. Diferencias con la documentación oficial (por request)

| # | Request | Problema | Qué dice la doc oficial | Corrección propuesta |
|---|---|---|---|---|
| P-01 | **Suscripción › Eliminar tarjeta** | Body `{"suscription": "su90d0d247ad328fcf461a"}` = **ID de suscripción**. | La tabla dice `suscription` = "ID de la **tarjeta**"; el ejemplo usa `{"card": "surec…"}`. ⚠️ contradicción en la doc. | Usar `{"card": "{{card_id}}"}` con un `identifier` `surec…`, y validar en sandbox (Q-09). |
| P-02 | **Suscripción de consumo › Eliminar tarjeta** | Body `{"suscription": "surec…"}`. | Ídem. | Ídem. |
| P-03 | **Suscripción › Obtener cliente** | Path `identificadorcliente = su90d0d247ad328fcf461a` (parece **ID de suscripción**). | Debe ser ID de cliente (`cl…`) o email. ✅ | `{{client_id}}`. |
| P-04 | **Suscripción › Obtener suscripciones** | Header `Authorization: Bearer {{token_publico}}` duplicado (ya lo pone la colección). | — | Quitar el header del request. |
| P-05 | Varios (`Obtener clientes`, `Crear suscripción`, `Obtener suscripciones V3`) | Header `Sign: {{sign}}`; el resto usa `Sign: {{firma}}`. Ambos los sobrescribe el script de colección. | — | Quitar el header `Sign` de **todos** los requests (lo pone el script). |
| P-06 | Listados (`Obtener múltiples transacciones`, `Obtener clientes`, `Obtener suscripciones`, `Obtener suscripciones V3`, `Obtener movimientos`) | Sin query params. **Sin fechas, Payku devuelve solo hoy.** ✅ | `page`, `per_page`, `date_init`, `date_end`, filtros de estado. ✅ | Agregar los params (deshabilitados los opcionales) con variables `{{date_init}}`, `{{date_end}}`. |
| P-07 | **Suscripción › Crear suscripción** | Sin `amount` / `coupon`. | Opcionales/condicionales (oneOf) ✅. | Agregar deshabilitados con descripción. |
| P-08 | **Suscripción de consumo › Crear transacción** | Incluye `marketplace` y `card` de ejemplo (`ma0690…`, `surea041…`). | Son opcionales ✅. Enviar valores falsos puede provocar error. | Dejar deshabilitados o con variables. |
| P-09 | **Wallet › Retirar dinero de mi wallet** | Body con `amount: 1865536` y `order: "30 Agosto test"`. | — | ⚠️ Ver § 6. Reemplazar por valores de prueba de sandbox. |
| P-10 | **Conciliación** | `date_init 2026-08-01` → `date_end 2026-08-30` (29 días). | Máx. 30 días ✅. | OK. Usar variables. |
| P-11 | Collection `test` event | Script vacío. | — | Agregar test genérico de `status: failed` (§ 7). |

---

## 3. Firma (`Sign`)

### 3.1 Scripts antiguos a nivel request ❌

Estos 8 requests tienen un **pre-request script propio**, además del de la colección:

| Request | Ruta fija que firma | Problema |
|---|---|---|
| Anulación › Crear anulación | `/api/nullification` | Usa `pm.environment.get("token_priv")` |
| Marketplace › Actualizar cliente | `/api/maclient/{identificadorCliente}` | Firma la **plantilla** literal, no el ID real |
| Mall › Crear transacción Mall | `/api/mall` | `token_priv` |
| Suscripción de consumo › Crear cliente | `/api/suclient/` | **Barra final** → firma distinta |
| Suscripción de consumo › Crear plan | `/api/suplan/` | Barra final |
| Suscripción de consumo › Crear suscripción | `/api/sususcription/` | Barra final |
| Suscripción de consumo › Crear transacción | `/api/sutransaction/` | Barra final |
| Suscripción de consumo › Eliminar tarjeta | `/api/suscriptionsdeletecards/` | Barra final |

Por qué es un problema:
- El script de colección corre **antes** y ya pone el header `Sign` correcto. Estos scripts solo guardan `firma` en el entorno, así que **su valor no se usa**.
- Pero usan la variable **`token_priv`**. Si tu entorno solo tiene `token_privado`, `CryptoJS.HmacSHA256(..., undefined)` lanza un error de script en cada ejecución. En una prueba con Newman (el motor de Postman) el request **igual se envió** después del error, así que el efecto real es ruido y confusión más que un bloqueo. ⚠️ En la app de Postman el comportamiento puede variar según la versión.
- **Corrección:** borrar los 8 scripts a nivel request. La colección ya cubre todo.

### 3.2 Script de colección: diferencias con el algoritmo oficial

| Punto | Colección | Oficial | Impacto | Propuesta |
|---|---|---|---|---|
| Codificación de valores | `encodeURIComponent(v).replace(/%20/g, "+")` | PHP `urlencode` / JS `URLSearchParams` | `encodeURIComponent` **no** codifica `' ( ) * !`. Con `"Av. O'Higgins"` la firma no coincide. | **v2:** codificación idéntica a PHP `urlencode` (también `! ' ( ) * ~`), igual que el cliente Python. |
| `&` tras el path sin parámetros | `[requestPath].concat(pairs).join("&")` → **sin** `&` final | PHP y JS oficiales → **con** `&` final (`path + "&" + ""`) | Afecta a todos los **GET sin parámetros** (`/api/suplan/plans`, `/api/wallet`, detalle por ID…). | ⚠️ Probar ambas variantes en sandbox (Q-01) y dejar la que funcione. |
| Valores `null` | Se **excluyen** | PHP los incluye como `key=`; JS los excluye | Diferente según implementación. | No enviar `null` en bodies. |
| Booleanos | `"true"` | PHP `1` | Solo si se envían booleanos. | Evitar. |
| Query params | Se incluyen | "Todos los parámetros del request" ✅ (sin ejemplo) | ⚠️ Q-03 | Mantener; validar. |
| `Sign` en todos los requests | Sí | Solo algunos grupos lo exigen ✅ | ⚠️ Q-02 (¿Payku rechaza un `Sign` de más?) | Mantener si funciona. |

### 3.3 Script de colección de la v2

Es el pre-request de `Payku API v2.postman_collection.json`:

```javascript
// === Payku — firma Sign + protección de producción (nivel COLECCIÓN) ===
// Documentación: docs/payku/authentication.md y docs/payku/postman.md
// Authorization: Bearer lo pone el helper de auth de la colección ({{token_publico}}).

const envGet = (k) => pm.environment.get(k);
const publicToken = envGet("token_publico");
const privateToken = envGet("token_privado");
if (!publicToken || !privateToken) {
  throw new Error("Faltan token_publico / token_privado en el entorno activo (" + pm.environment.name + ").");
}

const resolvedPath = pm.variables.replaceIn(pm.request.url.getPath()); // path real con IDs resueltos

// --- 1) Protección de producción -------------------------------------------
// En app.payku.cl solo se permiten lecturas, salvo allow_prod_writes = "yes".
const READ_ONLY_POSTS = ["/api/conciliation"]; // POST que solo lee datos
const targetHost = String(pm.variables.replaceIn(pm.request.url.getHost() || ""));
const isProd = targetHost.indexOf("app.payku.cl") !== -1; // host real del request (no bloquea webhooks simulados)
const isWrite = pm.request.method !== "GET" && READ_ONLY_POSTS.indexOf(resolvedPath) === -1;
const blocked = isProd && isWrite && envGet("allow_prod_writes") !== "yes";
if (blocked) {
  const msg = "Bloqueado: " + pm.request.method + " " + resolvedPath +
    " en PRODUCCIÓN. Usa el entorno sandbox o define allow_prod_writes = yes si es intencional.";
  // Un error en el script NO siempre impide el envío, así que además:
  // (1) se cancela el request si la versión de Postman lo permite, y
  // (2) se redirige a un host inexistente para que nada llegue a Payku.
  if (pm.execution && typeof pm.execution.skipRequest === "function") pm.execution.skipRequest();
  pm.request.url.update("http://bloqueado-produccion.invalid" + resolvedPath);
  pm.request.headers.remove("Sign");
  console.error(msg);
  throw new Error(msg);
}

// --- 2) Headers de control (solo para pruebas; se quitan antes de enviar) ----
//   X-Sign-Mode: none            -> no enviar Sign
//   X-Sign-Trailing: true|false  -> fuerza '&' final cuando no hay parámetros (Q-01)
//   X-Sign-Query: include|exclude -> incluir o no los query params en la firma (Q-03)
const ctl = (name) => {
  const v = pm.request.headers.get(name);
  return (v === undefined || v === null) ? null : String(pm.variables.replaceIn(v)).trim().toLowerCase();
};
const signMode = ctl("X-Sign-Mode");
const trailingCtl = ctl("X-Sign-Trailing");
const queryCtl = ctl("X-Sign-Query");
["X-Sign-Mode", "X-Sign-Trailing", "X-Sign-Query"].forEach((h) => pm.request.headers.remove(h));

// --- 3) Firma ---------------------------------------------------------------
// Codificación igual a PHP urlencode(): espacio -> '+', y también ! ' ( ) * ~
const phpUrlencode = (s) => encodeURIComponent(s)
  .replace(/!/g, "%21").replace(/'/g, "%27").replace(/\(/g, "%28")
  .replace(/\)/g, "%29").replace(/\*/g, "%2A").replace(/~/g, "%7E")
  .replace(/%20/g, "+");

if (signMode === "none") {
  pm.request.headers.remove("Sign");
  console.log("Payku: Sign omitido (X-Sign-Mode: none)");
} else {
  const trailing = (trailingCtl !== null ? trailingCtl : String(envGet("sign_trailing_ampersand") || "true")) !== "false";
  const includeQuery = queryCtl !== "exclude";

  let data = {};
  const body = pm.request.body;
  if (body && body.mode === "raw" && body.raw && body.raw.trim()) {
    try {
      data = JSON.parse(pm.variables.replaceIn(body.raw)) || {};
    } catch (e) {
      throw new Error("Body JSON inválido (no se puede firmar): " + e.message);
    }
  }
  if (includeQuery) {
    pm.request.url.query.each((p) => {
      if (p && p.key && !p.disabled) data[p.key] = pm.variables.replaceIn(p.value == null ? "" : String(p.value));
    });
  }

  // Orden alfabético por key; se excluyen objetos, arreglos y null (ver authentication.md § 5)
  const params = Object.keys(data).sort()
    .filter((k) => data[k] !== null && data[k] !== undefined && typeof data[k] !== "object")
    .map((k) => k + "=" + phpUrlencode(String(data[k])))
    .join("&");

  const concat = (params || trailing) ? phpUrlencode(resolvedPath) + "&" + params : phpUrlencode(resolvedPath);
  const sign = CryptoJS.HmacSHA256(concat, privateToken).toString();
  pm.request.headers.upsert({ key: "Sign", value: sign });
  console.log("Payku sign string:", concat);
}
```

Cambios respecto del script original:
- Resuelve `{{variables}}` del path, body y query **antes** de firmar (`pm.variables.replaceIn`). El original firmaba el texto `{{client_id}}` literal.
- Codificación igual a PHP `urlencode` (verificado: produce exactamente el hash del ejemplo oficial y la misma cadena que el cliente Python con `Av. O'Higgins 123 (dpto*2)!~`).
- `&` final configurable con `sign_trailing_ampersand` (Q-01).
- Headers de control `X-Sign-*` para las pruebas de la carpeta 🧪 (se quitan antes de enviar).
- Protección de producción: además de lanzar el error, **cancela** el request (`pm.execution.skipRequest()`) y, si la versión de Postman no lo soporta, lo redirige a un host inexistente para que nada llegue a Payku.
- `Authorization` queda solo en el helper Bearer de la colección.

---

## 4. Variables y entorno

| Hallazgo | Detalle |
|---|---|
| Nombres inconsistentes | La descripción de la colección pide `token_pub` y `token_priv`; el script de colección usa `token_publico` y `token_privado`; los scripts viejos, `token_priv`. |
| Mensaje de error | El script dice "Selecciona 'Payku Prod'". Para explorar endpoints que escriben, conviene un entorno **sandbox**. |
| Archivo de entorno | No está en la carpeta. |
| Variables de colección | No hay. |

Propuesta: un entorno por ambiente, con estas variables (plantilla en [postman/payku.postman_environment.example.json](postman/payku.postman_environment.example.json)):

| Variable | Ejemplo | Tipo |
|---|---|---|
| `url_api` | `https://des.payku.cl` / `https://app.payku.cl` | default |
| `token_publico` | — | **secret** |
| `token_privado` | — | **secret** |
| `sign_trailing_ampersand` | `true` | default |
| `client_id` | `cl…` | default |
| `client_email` | `socio@ejemplo.cl` | default |
| `plan_id` | `pl…` | default |
| `subscription_id` | `su…` | default |
| `card_id` | `surec…` | default |
| `transaction_id` | `trx…` | default |
| `payment_key` | `pra…` | default |
| `date_init` / `date_end` | `2026-10-01` / `2026-10-12` | default |
| `page` / `per_page` | `1` / `100` | default |

Las variables `api_key`, `token` y `customer_id` del prompt inicial **no corresponden** a Payku: Payku usa token público + token privado, y el cliente es `client`.

💡 Tests para encadenar requests (guardan IDs automáticamente):

```javascript
// En "Crear cliente" (Tests):
const r = pm.response.json();
if (r.id) pm.environment.set("client_id", r.id);

// En "Crear suscripción" (Tests):
const s = pm.response.json();
if (s.id) pm.environment.set("subscription_id", s.id);
if (s.url) console.log("URL de activación:", s.url);
```

---

## 5. IDs fijos a reemplazar por variables

| Request | Valor fijo | Variable |
|---|---|---|
| Transacción › Obtener transacción | `9917880991566424` | `{{transaction_id}}` |
| Suscripción › Obtener cliente | `su90d0d247ad328fcf461a` (tipo incorrecto) | `{{client_id}}` |
| Suscripción › Actualizar / Eliminar cliente | `cl5de9cad41f19ca870aae` | `{{client_id}}` |
| Suscripción › Crear suscripción | `pl3a1dfc47627b10f85fe3`, `cl740609ded25f37220526` | `{{plan_id}}`, `{{client_id}}` |
| Suscripción › Obtener suscripción | `sucb89f30eccb1bf28c8ed` | `{{subscription_id}}` |
| Suscripción › Eliminar suscripción | `su20728a82f8a9434b8b27` | `{{subscription_id}}` |
| Suscripción › Crear transacción / Afiliar tarjeta | `su90d0d247ad328fcf461a` | `{{subscription_id}}` |
| Suscripción › Obtener plan | `pl3a1dfc47627b10f85fe3` | `{{plan_id}}` |
| Wallet › Obtener movimiento | `wa97e71a278b197c1a` | `{{wallet_movement_id}}` |

Importante: si usas variables en el **body**, el script de firma debe resolverlas antes de firmar (el script propuesto en § 3.3 lo hace).

---

## 6. Riesgo operativo ❌

Estos requests **mueven dinero o borran datos** en producción con un solo clic:

| Request | Efecto |
|---|---|
| Wallet › Realizar pagos a terceros | Transfiere dinero a una cuenta bancaria. |
| Wallet › Retirar dinero de mi wallet | Retira el saldo (body actual: **$1.865.536**). |
| Anulación › Crear anulación | Reembolsa una transacción. |
| Suscripción › Crear transacción (`sutransaction`) | Cobra a la tarjeta de un socio. |
| Suscripción › Eliminar suscripción / Eliminar cliente / Eliminar tarjeta | Baja irreversible. |

Propuesta:
1. Moverlos a una carpeta **"⚠️ Dinero real / destructivo"**.
2. Agregar en esa carpeta un pre-request que bloquee si `url_api` es producción, salvo que exista una variable `allow_prod_writes = "yes"`:

```javascript
if ((pm.environment.get("url_api") || "").includes("app.payku.cl") && pm.environment.get("allow_prod_writes") !== "yes") {
  throw new Error("Bloqueado: operación de escritura en PRODUCCIÓN. Define allow_prod_writes=yes si es intencional.");
}
```

3. Explorar estos endpoints **solo en sandbox** (`des.payku.cl`).

---

## 7. Test genérico a nivel colección (propuesto)

```javascript
pm.test("HTTP sin error", () => pm.expect(pm.response.code).to.be.below(400));
let body;
try { body = pm.response.json(); } catch (e) { body = null; }
pm.test("Respuesta JSON", () => pm.expect(body).to.not.equal(null));
if (body && !Array.isArray(body)) {
  pm.test("Payku no devolvió status=failed", () => pm.expect(body.status).to.not.equal("failed"));
}
```

---

## 8. Endpoints faltantes

Ninguno: los 49 endpoints de Chile están. Lo que **sí** conviene agregar:
- Carpeta **"Webhooks (simulación)"** con requests `POST` hacia nuestro receptor (local o de pruebas) usando los payloads de [webhooks.md](webhooks.md), para probar el backend sin esperar a Payku.
- Variantes de listados con fechas y filtros de estado (ej. "V3 – activas últimos 30 días").
