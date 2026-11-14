# Webhooks y notificaciones

> Fuentes: https://virtualpos.readme.io/reference/webhook · https://virtualpos.readme.io/reference/webhook-payout · Verificado: 2026-10-12; sección de eventos PAT, cuerpos de suscripción y cargos revisada el 2026-11-09

## 1. Resumen

| Notificación | Dónde se configura | Qué envía VirtualPOS | Firma | Qué debes hacer |
| --- | --- | --- | --- | --- |
| **Payment** (webhook) | `callback_url` (Base64) en *Crear Payment* / *Web Checkout* | `HTTP POST` con el `uuid` del Payment | **No documentada** | `GET /v3/payment/{uuid}` y actualizar |
| **Payment** (retorno del navegador) | `return_url` (Base64) | Redirección del navegador con `uuid` por `HTTP POST` | No | `GET /v3/payment/{uuid}` y mostrar resultado |
| **Suscription** (API) | `callback_url` (Base64) en *Crear Suscription* | Callback asíncrono al terminar la inscripción (activa o fallida). Cuerpo `{"uuid": "<suscripción>"}` | No documentada | `GET /v3/suscription/{id}` |
| **Suscription** (POS) | Portal Comercio → Webhooks → servicio PAT → evento `suscription_activated` | Cuerpo `{"status","code","suscription":{"uuid"}}` (`status`/`code` son de la notificación, no del negocio) | No documentada | `GET /v3/suscription/{suscription.uuid}` |
| **Payout** | Se acuerda con VirtualPOS (obligatorio) | `HTTPS POST` con el **objeto payout** en el body | **HMAC-SHA256 del body** en header `Signature` | Validar firma → actualizar |
| **Charge** (cobros PAT) | Portal Comercio → Webhooks → servicio PAT → eventos `charge_paid` / `charge_reject` | Detalle del cargo: `id`, `suscription_uuid`, `status`, y `payment` con datos del cliente y del pago (puede ser `null`) | No documentada | `GET /v3/charge/{id}`; no persistir el cuerpo |
| **Cambio de tarjeta** | Portal Comercio → servicio PAT → evento `card_change` | `{"uuid": "<suscripción>"}` | No documentada | `GET /v3/suscription/{uuid}` |

Eventos PAT configurables en el Portal Comercio (sección Webhooks: Agregar webhook → servicio PAT → evento → URL sin Base64): `suscription_activated`, `suscription_failed`, `charge_paid`, `charge_reject`, `card_change` (la doc conserva la grafía *suscription*). Varios cuerpos traen solo `uuid` y no el nombre del evento: la doc recomienda **una ruta por evento**. Algunos envíos PAT declaran `Content-Type: application/x-www-form-urlencoded`: el receptor debe aceptar JSON y form. La doc **no documenta firma ni IPs de origen** para estos eventos (solo Payout tiene HMAC). Las suscripciones creadas por API siguen usando su propio `callback_url`. Receptor del CRM: `app/api/v1/routes/webhooks_virtualpos.py` (rutas `payment`, `subscription`, `charge_paid`, `charge_reject`, `card_change`, `payout`; ver [docs/data/webhooks.md](../../../data/webhooks.md)).

## 2. Webhook de Payment

Según la doc oficial:

- La notificación **siempre** se envía, termine bien o no el flujo del navegador.
- Es un `HTTP POST` al `callback_url` con el parámetro **`uuid`**.
- Luego debes invocar **Recuperar Payment** y actualizar tu sistema.
- Debes guardar al menos **1 año**: uuid, fecha de autorización, monto, código de autorización, cantidad de cuotas, monto de cada cuota.
- Si falla, debes permitir reintentar el pago con **el mismo `uuid`**.

**No documentado** (diseña defensivamente):

- Formato del body: ¿JSON `{"uuid": "..."}` o form `uuid=...`? → acepta ambos.
- Reintentos de VirtualPOS si tu endpoint falla, y su timeout.
- Firma o IPs de origen.

### Implementación recomendada (Node/Express)

```js
app.post('/webhooks/virtualpos/payment',
  express.json(), express.urlencoded({ extended: false }),
  async (req, res) => {
    const uuid = req.body?.uuid || req.query?.uuid;
    if (!uuid || !/^[a-z0-9]{8,40}$/i.test(uuid)) return res.sendStatus(400);

    // 1) Responder rápido: encolar y devolver 200
    await queue.add('vpos-payment-refresh', { uuid }, { jobId: `pay:${uuid}:${Date.now()}` });
    res.sendStatus(200);
  });

// Worker
async function refreshPayment({ uuid }) {
  const p = await vpos.get(`/v3/payment/${uuid}`);   // fuente de verdad
  await db.raw_vpos_payments.insert({ uuid, payload: p, fetched_at: new Date() });  // staging
  await db.vpos_payments.upsert(normalizePayment(p));                               // idempotente
}
```

Por qué así:

- **Sin firma = cualquiera puede llamar tu webhook.** No es un riesgo grave *porque nunca confías en el body*: solo usas el `uuid` para consultar a VirtualPOS con tus credenciales. Un `uuid` falso dará `E-020`.
- **Idempotencia:** el mismo `uuid` puede llegar varias veces (webhook + retorno + reintentos). El `upsert` por `uuid` lo hace inofensivo.
- **Responder rápido** evita timeouts y reintentos.

## 3. Callback de Suscription

La doc (revisada 2026-11-09) documenta el cuerpo: `{"uuid": "<suscripción>"}` para suscripciones creadas por API (se envía tanto si queda activa como si falla), y `{"status": "OK", "code": 200, "suscription": {"uuid": "..."}}` para suscripciones creadas en POS (evento PAT `suscription_activated`). El cuerpo no trae el estado de negocio: hay que consultar *Recuperar una Suscription*. Reintentos: No confirmado en la documentación oficial de VirtualPOS.

**Recomendación:** misma estrategia que Payment. Acepta JSON o form, extrae el identificador (`uuid` o `suscription.uuid`) y relee por API. Sin firma, no se persiste el cuerpo: solo el id. Como respaldo, al crear la suscripción guarda el `id` y programa una consulta a los 15 minutos / 1 hora / 24 horas mientras siga `SUSCRIBIENDO`.

## 4. Webhook de Payout

Confirmado en la doc:

- Obligatorio implementarlo.
- `HTTPS POST` con el objeto payout en el body.
- Header **`Signature`**: HMAC-SHA256 del **body** usando la clave secreta. **Debe validarse en cada notificación.**

```json
{
  "status": "OK",
  "code": 200,
  "payout": {
    "id": "po_59653837fa4c43d",
    "status": "PROCESSING",
    "create_at": "2023-10-24 06:10:42",
    "update_at": "2023-10-24 09:10:46",
    "tef": {
      "merchant_id": "tef-12801-64",
      "message": "Devolución de compra OC 873",
      "amount": 12500,
      "recipient": { "rut": "18123328-1", "name": "John Doe", "email": "johndoe@virtualpos.cl" },
      "bank": { "sbif_code": "037", "account_number": "786345987" }
    }
  }
}
```

> Ojo: en el webhook los campos son `create_at` / `update_at` (sin *d*), y en el objeto Payout son `created_at` / `updated_at`.

No documentado: si el HMAC va en hex o Base64. → compara contra ambos.

```js
const crypto = require('crypto');

app.post('/webhooks/virtualpos/payout', express.raw({ type: '*/*' }), (req, res) => {
  const raw = req.body;                                       // Buffer: firma sobre el body EXACTO
  const received = String(req.get('Signature') || '');
  const mac = crypto.createHmac('sha256', process.env.VPOS_PAYOUT_SECRET).update(raw).digest();
  const ok = [mac.toString('hex'), mac.toString('base64')].some(sig =>
    sig.length === received.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(received)));
  if (!ok) return res.sendStatus(401);

  const { payout } = JSON.parse(raw.toString('utf8'));
  queue.add('vpos-payout-update', payout, { jobId: `po:${payout.id}:${payout.status}` });
  res.sendStatus(200);
});
```

- Valida sobre el **body crudo** (no re-serialices el JSON: cambia espacios/escapes y rompe el HMAC).
- `timingSafeEqual` evita ataques de tiempo.
- Respaldo: si un payout lleva mucho en `PENDING`/`PROCESSING`, consulta `GET /v3/payout/merchant/{merchant_id}`.

## 5. Checklist de webhooks

- [ ] HTTPS público con certificado válido.
- [ ] `callback_url` y `return_url` codificadas en **Base64** al enviarlas.
- [ ] Responde `200` en < 2 s; procesa en cola.
- [ ] Re-consulta el recurso (Payment/Suscription/Charge); nunca confíes en el body (salvo Payout con HMAC válido).
- [ ] `upsert` idempotente por ID.
- [ ] No guardes el body de los canales sin firma: los eventos de cargo traen datos del cliente y del pago. Guarda solo ids y estado.
- [ ] Polling de respaldo por si el webhook no llega o el evento PAT no está configurado en el Portal Comercio.
