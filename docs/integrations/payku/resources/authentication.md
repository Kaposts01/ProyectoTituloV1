# Autenticación y firma (`Sign`)

Documentación oficial:
- Autenticación: https://docs.payku.com/cl/authentication/
- Seguridad (Bearer): https://docs.payku.com/cl/api-security/
- Firma: https://docs.payku.com/cl/signature/
- Acceso a la API: https://docs.payku.com/cl/api-access/
- Tarjetas de prueba: https://docs.payku.com/cl/test-cards/

---

## Términos clave

- **Token público:** credencial que va en el header `Authorization`. Identifica tu cuenta. ✅
- **Token privado:** clave secreta que **nunca viaja** en el request; solo se usa para calcular la firma. ✅
- **Firma (`Sign`):** huella digital (HMAC-SHA256) del request. Prueba que quien llama conoce el token privado y que los datos no se alteraron. ✅
- **HMAC-SHA256:** función que mezcla un mensaje con una clave secreta y produce un código de 64 caracteres hexadecimales.

🎨 **Analogía:** el token público es tu **nombre** en la recepción; la firma es un **sello lacrado** que solo tú puedes hacer con tu anillo (token privado). Payku tiene una copia del anillo y verifica que el sello corresponda exactamente a esa carta.

---

## 1. Dónde se obtienen los tokens

En la cuenta Payku → **Integración → Tokens integración y API**. ✅
Los requests no autenticados o incorrectos responden con un error de token inválido. ✅

---

## 2. Headers

| Header | Valor | Obligatorio |
|---|---|---|
| `Authorization` | `Bearer TOKEN_PUBLICO` | Siempre ✅ |
| `Sign` | Firma HMAC-SHA256 (ver § 3) | Ver tabla siguiente |
| `Content-Type` | `application/json` | En POST/PUT con body (aparece en todos los ejemplos) ✅ |
| `Accept` | `application/json, text/plain, */*` | Aparece en los ejemplos cURL ✅. Sin `application/json` podrías recibir `406 Not Acceptable` 💡 |

### ¿Qué endpoints requieren `Sign`?

La documentación oficial **no es del todo consistente**:

| Fuente oficial | Qué dice |
|---|---|
| Página **Firma** | "suscripciones, anulación y mall" ✅ |
| **Portada** de docs | "suscripciones, anulaciones, mall y pagos a terceros usan el header `Sign`" ✅ |
| Ejemplos **cURL** por endpoint | Incluyen `Sign` en: todo `su*` (suscripción y consumo), `nullification` (crear), `mall` (crear), `maclient` (actualizar), y **todos** los de `wallet` / `payout`. ✅ |

Tabla práctica resultante:

| Grupo | `Sign` |
|---|---|
| Suscripción (`/api/suclient`, `/api/sususcription*`, `/api/sutransaction`, `/api/suplan*`, tarjetas) | **Sí** ✅ |
| Anulación — crear (`POST /api/nullification`) | **Sí** ✅ |
| Anulación — obtener (`GET /api/nullification/{id}`) | No aparece en el ejemplo ⚠️ |
| Mall — crear (`POST /api/mall`) | **Sí** ✅ |
| Wallet / payout (todos) | **Sí** (según portada y ejemplos) ✅ |
| Marketplace — actualizar cliente (`PUT /api/maclient/{id}`) | Sí (según ejemplo) ⚠️ los demás endpoints de marketplace no lo muestran |
| Transacción, escrow, evento, conciliación, bancos, métodos de pago | No aparece en los ejemplos |

💡 **Recomendación:** nuestro cliente puede **enviar `Sign` en todos los requests** (es lo que hace nuestra colección Postman). ✅ **Medido en producción el 2026-11-14 (ficha d175):** Payku acepta un `Sign` de más en endpoints que no lo piden (`GET /api/transaction` responde igual con, sin y con una firma falsa).

**Medido en producción el 2026-11-14 (ficha d174, solo GET):** en los `GET` que exigen firma (`/api/suplan/plans`, `/api/suplan/{id}`), Payku exige que el header `Sign` **esté presente** (sin él responde 401), pero **no valida su valor**: pasan la firma sin `&` final, con `&` final y una firma falsa. Por eso no hace falta cambiar `auth.py` para las lecturas. La validación de la firma en **escrituras** (POST/PUT/DELETE) queda por confirmar en la primera escritura real (prueba de 1 CLP, ficha d213).

---

## 3. Algoritmo de la firma ✅

Paso a paso, tal como lo describe Payku:

1. Toma el **request path** (por ejemplo `/api/suclient`) y codifícalo en formato URL → `%2Fapi%2Fsuclient`.
2. Toma **todos los parámetros del request** y **ordénalos alfabéticamente por nombre (key)**.
3. **Descarta** los parámetros cuyo valor sea un **objeto o un arreglo** (por ejemplo `additional_parameters`).
4. Convierte cada uno en `key=valor`, con el valor codificado en formato URL (`example@domain.com` → `example%40domain.com`, espacio → `+`).
5. Únelos con `&`.
6. Concatena: `path_codificado + "&" + parámetros`.
7. Calcula **HMAC-SHA256** de esa cadena usando el **token privado** como clave. El resultado en hexadecimal es el valor del header `Sign`.

### Ejemplo oficial (verificado)

Datos:

```json
{
  "email": "johndoe@example.com",
  "name": "John Doe",
  "phone": "923122312",
  "address": "Moneda 101",
  "country": "Chile",
  "region": "Metropolitana",
  "city": "Santiago",
  "postal_code": "850000",
  "additional_parameters": { "parameter_1": "example", "parameter_2": "example 2" }
}
```

Cadena a firmar (`additional_parameters` queda fuera por ser objeto):

```text
%2Fapi%2Fsuclient&address=Moneda+101&city=Santiago&country=Chile&email=johndoe%40example.com&name=John+Doe&phone=923122312&postal_code=850000&region=Metropolitana
```

Token privado de ejemplo: `fe551abcef62fcf002dc598922e68f0a`

Resultado esperado (oficial): `c9c86202b1246f6ebeb080d08b3b99a22d36d0e8cffb7fd4e65af0fea4dd12bb`

✅ El código Python de abajo **reproduce exactamente** este hash (probado el 2026-10-12).

---

## 4. Implementación de referencia en Python

```python
"""Firma `Sign` de Payku (HMAC-SHA256). Compatible con el ejemplo PHP oficial."""
import hashlib
import hmac
from typing import Any, Mapping, Optional
from urllib.parse import quote_plus


def _php_urlencode(value: str) -> str:
    # PHP urlencode(): espacio -> '+'; todo lo no alfanumérico salvo - _ . se codifica.
    # quote_plus deja '~' sin codificar; PHP lo codifica como %7E.
    return quote_plus(value, safe="").replace("~", "%7E")


def _to_str(value: Any) -> str:
    # Igual que PHP al convertir escalares: true -> "1", false/null -> "".
    if value is True:
        return "1"
    if value is False or value is None:
        return ""
    return str(value)


def build_sign_string(request_path: str, params: Optional[Mapping[str, Any]] = None) -> str:
    """urlencode(path) & k1=v1 & k2=v2 ... (keys ordenadas, sin objetos ni arreglos)."""
    params = params or {}
    pairs = [
        f"{key}={_php_urlencode(_to_str(val))}"
        for key, val in sorted(params.items())
        if not isinstance(val, (dict, list, tuple))
    ]
    # Los ejemplos oficiales (PHP y JS) siempre concatenan '&' después del path,
    # incluso si no hay parámetros. Ver open-questions.md (Q-01).
    return _php_urlencode(request_path) + "&" + "&".join(pairs)


def sign(request_path: str, params: Optional[Mapping[str, Any]], private_token: str) -> str:
    message = build_sign_string(request_path, params)
    return hmac.new(private_token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
```

Uso:

```python
headers = {
    "Authorization": f"Bearer {settings.PAYKU_PUBLIC_TOKEN}",
    "Sign": sign("/api/suclient", body, settings.PAYKU_PRIVATE_TOKEN),
    "Content-Type": "application/json",
    "Accept": "application/json",
}
```

---

## 5. Casos borde de la firma (importantes)

| Caso | Qué dice la doc oficial | Riesgo | Qué hacemos |
|---|---|---|---|
| **GET sin parámetros** (p. ej. `GET /api/suplan/plans`) | Los ejemplos PHP y JS producen `%2Fapi%2Fsuplan%2Fplans&` (con `&` final). | Nuestra colección Postman firma **sin** `&` final. Uno de los dos está mal. | ⚠️ Validar en sandbox (Q-01). El cliente Python debe permitir cambiar esto con un flag. |
| **GET con path param** (`/api/sususcription/su123`) | No hay ejemplo. 💡 Se firma el path real, con el ID incluido. | Firmar la plantilla `{id}` en vez del ID real da error 401. | Firmar siempre el path ya resuelto. |
| **Query params** (`?page=1&per_page=100&active=true`) | "Todos los parámetros del request" ✅. No hay ejemplo con query params. | Si no se incluyen, o se incluyen con otro formato, la firma falla. | 💡 Incluirlos con el **mismo string exacto** que se envía en la URL (`"true"`, no `True`). Validar (Q-03). |
| Valor **`null`** en el body | PHP lo incluye como `key=` (vacío); el ejemplo JS lo **descarta**. | Las dos implementaciones oficiales no coinciden. | **Nunca enviar `null`**: omite el campo. |
| Valor **booleano** en el body | PHP: `true` → `1`. JS: `true` → `true`. | Diferencia entre ejemplos. | Evitar booleanos en bodies firmados; si hay que enviarlos, validar en sandbox. |
| Caracteres `' ( ) * ! ~` | PHP `urlencode` los codifica todos. `encodeURIComponent` (nuestro Postman) **no** codifica `' ( ) * !`. | Una dirección como `Av. O'Higgins 123` daría firma distinta en Postman. | El cliente Python usa la codificación de PHP. Ver [postman.md](postman.md). |
| Objetos y arreglos | Se excluyen ✅. | — | `additional_parameters`, `merchant`, `affiliation`, etc. no entran en la firma. |

---

## 6. Errores de autenticación

| HTTP | Respuesta | Causa |
|---|---|---|
| 401 | `{"type": "Unauthorized", "message_error": {"error": "waiting token public"}}` | Token público ausente o incorrecto ✅ |
| 401 | "Tu token es incorrecto o error de firma" ✅ | Firma inválida (ruta mal codificada, orden de parámetros, encoding, token privado equivocado). ⚠️ El formato exacto del JSON para error de firma no está documentado. |

Checklist ante un 401 con firma:
1. ¿Usaste el token **privado** del **mismo ambiente** (sandbox vs producción)?
2. ¿El path firmado es exactamente el path enviado (con ID real y sin barra final de más)?
3. ¿Ordenaste por key y excluiste objetos y arreglos?
4. ¿El body que firmaste es **exactamente** el que enviaste (mismos valores, mismos tipos)?
5. ¿Hay `null`, booleanos o caracteres especiales en los valores?

---

## 7. Seguridad de credenciales

- Guarda `PAYKU_PUBLIC_TOKEN` y `PAYKU_PRIVATE_TOKEN` en variables de entorno o en un gestor de secretos, **nunca** en el código ni en el repositorio.
- En Postman marca las variables de tokens como tipo **secret** y no compartas exportaciones del entorno con valores.
- No registres en logs el token privado ni la cadena firmada completa en producción (puede incluir datos personales como el email).
- Usa credenciales separadas para sandbox y producción, con nombres de variable distintos o entornos separados.

---

## 8. "Sandbox" del CRM y guardas duras de escritura (d165)

Estado: **pendiente de credenciales**. Las variables `PAYKU_SANDBOX_*` aún no están cargadas y el host de sandbox de Payku no está confirmado por soporte. Las guardas existen **antes** de habilitar cualquier escritura, con el mismo mecanismo que Toku ([`../../toku/resources/authentication.md`](../../toku/resources/authentication.md) § 3.1).

Con `APP_ENV=sandbox|qa`, `PaykuClient` llama a `assert_sandbox_write_allowed` (`app/integrations/payku/write_guard.py`) antes de cada POST/PUT/DELETE, **antes de tocar la red**. Producción no pasa por esta guarda: sus escrituras siguen gobernadas solo por `PAYKU_WRITES_ENABLED` (apagada), sin cambios. Las lecturas (GET) no se guardan.

| Regla | Detalle | Código de bloqueo |
|---|---|---|
| Llave 1 | `PAYKU_SANDBOX_WRITES_ENABLED=true` (.env) | `WRITES_DISABLED` |
| Host | `https`, puerto 443, sin credenciales en la URL, host en la lista de hosts de sandbox conocidos (`SANDBOX_HOSTS["payku_base_url"]`, hoy `des.payku.cl`) y nunca `app.payku.cl`. Un host nuevo exige cambio de código revisado | `HOST_NOT_ALLOWED` |
| Llave 2 | `PAYKU_SANDBOX_ALLOW_WRITES_ARMED=1`, **variable de proceso** (no se lee del `.env`) | `NOT_ARMED` |
| Lista blanca de endpoints | Solo `POST /api/suclient`, `PUT`/`DELETE /api/suclient/{id}`, `POST /api/suplan`, `POST /api/sususcription`, `DELETE /api/sususcription/{id}`. Todo lo demás se bloquea, en particular lo que mueve dinero (`transaction`, `sutransaction`, tarjetas, `wallet`/`payout`, `mall`, `nullification`, `escrow`, marketplace, `event`) y también `POST /api/conciliation` aunque sea una consulta | `ENDPOINT_NOT_ALLOWED` |
| Datos sintéticos al crear | `name` con prefijo `TEST-`; en clientes, `email` del dominio `example.test`. En `PUT /api/suclient/{id}`, si vienen `name`/`email` deben cumplir lo mismo | `PREFIX_REQUIRED`, `EMAIL_DOMAIN_REQUIRED`, `FIELD_MISSING` |
| Recursos existentes | El id del path (PUT/DELETE) y las referencias `client` y `plan` de `POST /api/sususcription` deben empezar por `TEST-` o estar en `PAYKU_SANDBOX_ALLOWED_IDS` (variable de proceso, separada por comas). Los ids que genera Payku (`cl…`, `su…`, `pl…`) no llevan `TEST-`: hay que listarlos | `ID_NOT_ALLOWED` |
| Tope | `PAYKU_SANDBOX_MAX_WRITES` (variable de proceso; default 25, máximo 500, `0` bloquea todo). Por proceso: se reinicia al reiniciar y se multiplica con N workers. Solo cuentan las escrituras que pasaron las demás guardas | `CAP_REACHED` |
| Forma | Body en lista, rutas con `..`, `?`, `#`, `%`, `\` o `//`, body que no es objeto | `BULK_BLOCKED`, `PATH_INVALID`, `BODY_INVALID` |
| Ambiente | Si la guarda recibe una configuración productiva, falla cerrado | `ENV_NOT_SANDBOX` |

- Un bloqueo devuelve HTTP 403 (`payku_write_blocked`, solo con el código) en `/writes/payku/*` y queda en `write_runs` con estado `blocked` y el mensaje completo (sin valores ni PII).
- Las variables de proceso no deben dejarse en `.env`. Con `APP_ENV=development/dev/local` (alias de producción) las variables `PAYKU_SANDBOX_*` se ignoran y estas guardas no corren.
- Pruebas: `tests/test_payku_write_guard.py` (sin red, transporte falso).

---

## Tarjetas de prueba (sandbox)

Documentación: https://docs.payku.com/cl/test-cards/ ✅

| Tipo | Número | Datos | Resultado |
|---|---|---|---|
| VISA | 4051 8856 0044 6623 | CVV 123, cualquier fecha | Aprobada |
| AMEX | 3700 0000 0002 032 | CVV 1234, cualquier fecha | Aprobada |
| MASTERCARD | 5186 0595 5959 0568 | CVV 123, cualquier fecha | **Rechazada** |
| Redcompra | 4051 8842 3993 7763 | — | Aprobada (débito/prepago) |
| Redcompra | 5186 0085 4123 3829 | — | **Rechazada** |
| Prepago VISA | 4051 8860 0005 6590 | CVV 123, cualquier fecha | Aprobada |
| Prepago MASTERCARD | 5186 1741 1062 9480 | CVV 123, cualquier fecha | **Rechazada** |

Si aparece el formulario de autenticación bancaria: RUT `11.111.111-1`, clave `123`. ✅

💡 Para probar el flujo de **reintentos y suspensión** de una suscripción, inscribe primero una tarjeta aprobada y luego reemplázala por una que rechace. ⚠️ No está documentado si en sandbox se puede acelerar el ciclo de cobro mensual.
