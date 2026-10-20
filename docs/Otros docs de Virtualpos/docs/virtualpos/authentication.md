# Autenticación y firma

> Fuente: https://virtualpos.readme.io/reference/autenticación-y-firma · Verificado: 2026-10-12

## 1. Conceptos clave

| Término | Qué es |
| --- | --- |
| **API KEY** | Identifica a tu comercio. Va **en texto plano** en el header `Authorization`. |
| **SECRET KEY** | Clave privada. **Nunca viaja**: solo se usa para firmar. |
| **JWT** | *JSON Web Token* (RFC 7519): `header.payload.firma`, en Base64URL. |
| **Signature** | Header con el JWT firmado con HS256 (HMAC-SHA256) usando la SECRET KEY. |

Analogía: la API KEY es tu nombre en la entrada; la Signature es tu firma en el libro de visitas, hecha con un lápiz (SECRET KEY) que solo tú tienes. VirtualPOS tiene una copia del lápiz y comprueba que la firma calce.

Las llaves son **distintas por ambiente** (sandbox ≠ producción) y se obtienen en el portal: **Perfil > Configuración de cuenta > Integración**. Las llaves de **Payout** son otras y las entrega VirtualPOS durante el proyecto de integración.

## 2. Headers obligatorios en cada request

```http
Content-Type: application/json
Authorization: <API_KEY>
Signature: <JWT>
```

## 3. Qué va en el payload del JWT

| Caso | Payload | Estado |
| --- | --- | --- |
| `GET` | `{"api_key": "<API_KEY>"}` | Confirmado (ejemplo PHP oficial) |
| `POST` | `{"api_key": "<API_KEY>", ...atributos requeridos}`. El ejemplo oficial firma `{api_key, uuid}` y envía `{uuid}` en el body. | Confirmado el principio; **la lista exacta de atributos por endpoint no está documentada** |
| `PUT` / `DELETE` | Sin ejemplo | No confirmado en la documentación oficial de VirtualPOS. Usar `{api_key}` (+ body si existe) |
| Payout (crear / consultar) | `{"api_key": "...", "tef": { ...instrucción... }}` | Confirmado en *Autenticación y firma – Payout* |

> **Lo que sabemos en la práctica (sandbox):** tu colección original firmaba **solo `{api_key}`** en todos los métodos y así se crearon clientes y planes. Eso sugiere que el servidor valida la firma y el `api_key` del payload, pero no exige los atributos del body.
>
> **Recomendación:** en el backend, firma `{api_key, ...body}` (lo que dice la doc). Si en algún endpoint eso falla con `E-014/E-015/E-016`, cae a `{api_key}` y regístralo en [discrepancies.md](discrepancies.md). La colección Postman v2 permite cambiar entre los dos modos con la variable `vpos_sign_mode`.

Errores típicos de firma:

| Código | Mensaje | Causa probable |
| --- | --- | --- |
| `E-001` | Error en el parámetro Authorization. | Falta el header o la API key está vacía |
| `E-002` | Error en el parámetro Signature. | Falta el header `Signature` |
| `E-013` / `E-045` | No existe el comercio / cuenta asociada a la api key | Llave de otro ambiente (sandbox vs producción) |
| `E-014` | La verificación de la firma es incorrecta. | SECRET KEY equivocada |
| `E-015` | Firma es incorrecta. | JWT mal formado (Base64 normal en vez de Base64URL, `=` sin quitar) |
| `E-016` | Parámetros en la firma tienen errores. | Payload sin `api_key` o con atributos que no calzan |

## 4. Implementaciones

### PHP (ejemplo oficial, POST)

```php
$payload = array();
$payload['api_key'] = <MY_API_KEY>;
$payload['uuid'] = $uuid;

$jwt_signature = JWT::encode($payload, <MY_SECRET_KEY>);

$client = new Client([
  'headers' => [
    'Content-Type'  => 'application/json',
    'Authorization' => <MY_API_KEY>,
    'Signature'     => $jwt_signature
  ]
]);

$response = $client->post($endpoint, ['json' => ['uuid' => $uuid]]);
```

### Node.js (backend recomendado)

```js
// npm i jsonwebtoken
const jwt = require('jsonwebtoken');

function vposHeaders(body = null) {
  const apiKey = process.env.VPOS_API_KEY;
  const secret = process.env.VPOS_SECRET_KEY;
  const payload = body ? { api_key: apiKey, ...body } : { api_key: apiKey };
  // noTimestamp: el ejemplo oficial no incluye "iat"; evita diferencias innecesarias
  const signature = jwt.sign(payload, secret, { algorithm: 'HS256', noTimestamp: true });
  return {
    'Content-Type': 'application/json',
    Authorization: apiKey,
    Signature: signature,
  };
}
```

### Python

```python
# pip install pyjwt requests
import os, jwt, requests

def vpos_headers(body: dict | None = None) -> dict:
    api_key = os.environ["VPOS_API_KEY"]
    payload = {"api_key": api_key, **(body or {})}
    signature = jwt.encode(payload, os.environ["VPOS_SECRET_KEY"], algorithm="HS256")
    return {"Content-Type": "application/json", "Authorization": api_key, "Signature": signature}
```

### Google Apps Script (para `virtualPOS_mejorado_v2.gs` y similares)

```js
function vposSignature_(payload) {
  const props = PropertiesService.getScriptProperties();       // llaves en Script Properties, nunca en el código
  const secret = props.getProperty('VPOS_SECRET_KEY');
  const b64url = (bytesOrStr) => Utilities.base64EncodeWebSafe(bytesOrStr).replace(/=+$/, '');
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body   = b64url(JSON.stringify(payload));
  const sig    = Utilities.computeHmacSha256Signature(header + '.' + body, secret);
  return header + '.' + body + '.' + b64url(sig);
}

function vposFetch_(method, path, body) {
  const props = PropertiesService.getScriptProperties();
  const apiKey = props.getProperty('VPOS_API_KEY');
  const base = props.getProperty('VPOS_BASE_URL');               // https://api.virtualpos.cl
  const payload = body ? Object.assign({ api_key: apiKey }, body) : { api_key: apiKey };
  const res = UrlFetchApp.fetch(base + path, {
    method: method,
    contentType: 'application/json',
    headers: { Authorization: apiKey, Signature: vposSignature_(payload) },
    payload: body ? JSON.stringify(body) : undefined,
    muteHttpExceptions: true,
  });
  return { code: res.getResponseCode(), json: JSON.parse(res.getContentText() || '{}') };
}
```

### Postman (colección v2)

El *pre-request script* de la colección lo hace solo: lee `api_key` y `secret_key` del entorno, resuelve las variables del body, firma con CryptoJS (`jsonwebtoken` no existe en Postman) y hace `upsert` de los headers `Authorization` y `Signature`.

## 5. Buenas prácticas

- **Recomendación:** las llaves van en variables de entorno / Secret Manager / Script Properties. Nunca en el repo, nunca en una hoja de cálculo, nunca pegadas en un chat.
- En Postman, marca `api_key` y `secret_key` como tipo **secret** y no exportes el entorno con valores.
- El JWT del ejemplo oficial **no lleva `exp` ni `iat`**: una firma robada sirve indefinidamente para el mismo payload. Protege tus logs: no registres el header `Signature`.
- Si una llave se expone: rótala en el portal de inmediato.
