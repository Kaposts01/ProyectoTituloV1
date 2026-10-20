# Flujo: editar los datos de un socio (adaptador Toku)

**Objetivo:** aplicar en Toku los cambios de **nombre, email, teléfono y RUT** que ya se guardaron en nuestra base, sin tocar el `external_id` y sabiendo qué efectos tiene corregir el RUT.
**Recursos:** Customer (`cus_…`) · **Postman:** carpeta `02 · Editar socio`
**Relacionados:** [capa común editar-socio](../../../../Transversal/docs/transversal/workflows/editar-socio.md) · [customers.md](../customers.md) · [create-customer.md](create-customer.md)

> **Todo es producción.** Probar solo con un Customer `TEST-`.

## 1. Qué se puede editar

`PUT /customers/{encrypted_customer_id}`: actualización parcial, "solo modifica los campos presentes en el cuerpo; los omitidos se mantienen sin cambios" [Confirmado]. Ningún campo es obligatorio.

| Dato | Campo | ¿Editable? | Respaldo |
| --- | --- | --- | --- |
| Nombre | `name` (máx. 128) | ✅ | `UpdateCustomerPayload` [Confirmado] |
| Email | `mail` (máx. 128) | ✅ | `UpdateCustomerPayload` [Confirmado] |
| Teléfono | `phone_number` (máx. 16) | ✅ | `UpdateCustomerPayload` [Confirmado]. Formato `+569…` (si no, `TK30404`) |
| RUT | `government_id` (máx. 64) | ✅ | `UpdateCustomerPayload` [Confirmado]. ⚠️ Ver § 3 |
| ID externo | `external_id` | ❌ | El schema lo acepta, pero el catálogo de errores define `TK30411` ("no se puede actualizar") y nuestra prueba devolvió `409` [Confirmado] |
| Emails adicionales | `secondary_emails` | ✅ | Fuera del alcance: **no** agregar el email anterior (seguiría recibiendo cobranza) |

**La Subscription no guarda datos personales** [Confirmado: su schema no tiene nombre, email ni RUT]: todo vive en el Customer, así que no hay copias desincronizadas (a diferencia de VirtualPOS).

**Alternativa:** `POST /customers` con el **mismo** `external_id` también actualiza (upsert) [Confirmado]. Preferimos el `PUT` por `cus_…` porque no depende de cómo la organización arma el `external_id` (T-A7).

## 2. Flujo

```text
PASO 1 · Estado actual                           GET /customers/{cus_…}
↓  Diff entre nuestra base y Toku (name, mail, phone_number, government_id)
↓  └─ Sin diferencias → APLICADO
↓
PASO 2 · Si cambia el email: ¿lo usa otro Customer?
↓  GET /customers?mail={nuevo}
↓  ├─ Hay otro cus_ con ese mail → frenar: revisión de duplicados
↓  └─ No → seguir
↓  (Toku no documenta unicidad de mail; lo validamos nosotros para no mezclar socios)
↓
PASO 3 · Actualizar                              PUT /customers/{cus_…}   (solo los campos que cambian; NUNCA external_id)
↓  ├─ 200 → Customer actualizado
↓  ├─ 422 → TK30402 (RUT) / TK30404 (teléfono) / TK30405 (email) / TK30406 (email en lista negra)
↓  └─ 404 → el cus_ no existe en esta organización
↓
PASO 4 · Confirmar                               (la respuesta del PUT trae el Customer)
↓  Comparar name, mail, phone_number, government_id con lo enviado → APLICADO por campo
↓
PASO 5 · Si cambió el RUT                        GET /payment-methods?id_customer={cus_…}
↓  ¿Hay medios PAC (type: bank_account)? → tarea MANUAL: revisar el titular de la cuenta y el mandato
↓  ¿El external_id era el RUT anterior? → registrar: queda con el RUT anterior para siempre
↓
RESULTADO: {nombre, email, telefono, rut: APLICADO | ERROR} + tareas MANUAL si el RUT afecta un PAC
```

## 3. Corrección de RUT: efectos

| Efecto | Detalle | Qué hacer |
| --- | --- | --- |
| `external_id` | Si la organización usa el RUT como `external_id` (T-A7), queda con el RUT **anterior**: no se puede cambiar (TK30411) | Buscar siempre por `cus_…` (guardado en nuestra base), nunca por `external_id` ni por RUT |
| Upsert futuro | Un `POST /customers` con el RUT **nuevo** como `external_id` crearía **otro** Customer | En nuestro código, el upsert usa el `external_id` guardado, no lo recalcula desde el RUT |
| PAC | La Customer Collection Account tiene su propio `government_id` (titular; "por defecto, el del Customer") [Confirmado]. [No confirmado] si se actualiza al cambiar el Customer | Tarea manual: revisar con Toku si el mandato sigue válido |
| Documentos tributarios | Con `default_receipt_type: bill`, las boletas usan el RUT del Customer [Inferencia] | Desde el cambio salen con el RUT nuevo; las anteriores no cambian |

## 4. Request

```json
PUT /customers/cus_ejC08yLqOWoFhVx4Fx42E3IR9X50tNx2
{ "name": "Ana Pérez Soto", "mail": "ana.nuevo@mail.com", "phone_number": "+56987654321" }
```

## 5. Implementación (Node, referencia)

```js
const CAMPOS = { nombre: 'name', email: 'mail', telefono: 'phone_number', rut: 'government_id' };

const editarSocioToku = {
  async actualizar(socio, cambios) {
    const cusId = socio.toku_customer_id;
    if (!cusId) return {};                                               // el socio no está en Toku
    const actual = await toku.get(`/customers/${cusId}`);
    const body = {};
    for (const [k, campo] of Object.entries(CAMPOS))
      if (cambios[k] !== undefined && actual[campo] !== cambios[k]) body[campo] = cambios[k];
    const resultado = Object.fromEntries(Object.keys(cambios).filter(k => CAMPOS[k]).map(k => [k, 'APLICADO']));
    if (!Object.keys(body).length) return resultado;

    if (body.mail) {
      const { items = [] } = await toku.get('/customers', { mail: body.mail, page_size: 5 });
      const otro = items.find(c => c.id !== cusId);
      if (otro) return Object.fromEntries(Object.keys(resultado).map(k => [k, 'ERROR']));   // revisión de duplicados
    }

    const nuevo = await toku.put(`/customers/${cusId}`, body);           // nunca external_id (TK30411)
    for (const [k, campo] of Object.entries(CAMPOS))
      if (k in resultado) resultado[k] = nuevo[campo] === cambios[k] ? 'APLICADO' : 'ERROR';

    if (body.government_id) {
      const { items = [] } = await toku.get('/payment-methods', { id_customer: cusId });
      if (items.some(i => i.payment_method.type === 'bank_account'))
        await tareas.crear('toku', socio.id, 'RUT corregido con PAC activo: revisar titular y mandato con Toku');
    }
    return resultado;
  },

  async verificar(socio) {
    const c = await toku.get(`/customers/${socio.toku_customer_id}`);
    return Object.fromEntries(Object.entries(CAMPOS).map(([k, campo]) => [k, c[campo] === socio[k]]));
  },
};
```

## 6. Errores

| Error | Causa | Qué hacer |
| --- | --- | --- |
| `TK30402` | `government_id` inválido | Validar el RUT (DV) antes de enviar |
| `TK30404` / `TK30408` | Teléfono inválido o país no soportado | Normalizar a `+569…` |
| `TK30405` | Email con sintaxis inválida | Validar antes |
| `TK30406` | Email en lista negra | Pedir otro email al socio |
| `TK20401` | Bloqueado por otra carga concurrente (lock optimista) | Reintentar con backoff exponencial (3 intentos, 1 s · 2 s · 4 s) |
| `TK30411` / `409` | Se envió `external_id` | Quitarlo del body |
| `404` | El `cus_` no existe en esta organización | Revisar el mapeo en nuestra base |
| `429` | Más de 20 req/s | Backoff (la propagación es asíncrona) |

## 7. Probarlo en Postman

Carpeta **`02 · Editar socio`** de `Toku API.postman_collection.json`, para **Run folder**. ⚠️ **Producción:** el `PUT` se cancela si el `external_id` del Customer no empieza con `TEST-`.

| Request | Qué hace | Siguiente |
| --- | --- | --- |
| ET-1 Obtener Customer | Lee `customer_id` y arma el body solo con lo que cambia (`edit_name`, `edit_mail`, `edit_phone`, `edit_rut`) | Sin cambios → FIN · Cambia email → ET-2 · Otro → ET-3 |
| ET-2 Verificar email libre | `GET /customers?mail=`: ¿lo usa otro Customer? | Libre → ET-3 · Ocupado → **FIN** |
| ET-3 Actualizar Customer | `PUT` con `edit_body` (sin `external_id`) | Cambió el RUT → ET-4 · FIN |
| ET-4 Medios de pago (si cambió el RUT) | Avisa si hay PAC que revisar | FIN |

**Variables de colección:** `customer_id` y los valores nuevos `edit_name`, `edit_mail`, `edit_phone`, `edit_rut` (vacío = no cambia). Los scripts llenan `edit_body`, `edit_before` y `edit_target_external_id`.
