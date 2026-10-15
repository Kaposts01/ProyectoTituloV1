# Flujo: link de inscripción de medio de pago (adaptador Toku)

**Objetivo:** que la [capa común de link seguro](../../../../Transversal/docs/transversal/workflows/link-seguro-inscripcion.md) pueda llevar a un socio de Toku al **Checkout de Toku** para inscribir su tarjeta o PAC, tanto en un **alta** como para un **socio existente**.
**Recursos:** Checkout Session · Subscription · Payment Method · **Postman:** carpeta `01 · Link de inscripción`
**Relacionados:** [alta-socio.md](alta-socio.md) · [enroll-payment-method.md](enroll-payment-method.md) · [payment-methods.md](../payment-methods.md)

> **🔴 Bloqueante (el mismo del alta):** el Checkout `ENROLLMENT` necesita que Toku configure el flujo de inscripción (`flow_name`). Ver T-A1 en [alta-socio.md](alta-socio.md#9-pendientes-por-confirmar-con-toku).
> **Todo es producción:** probar solo con objetos `TEST-` y `skip_message_trigger: true`.

## 1. Resumen

| | A. Alta | B. Socio existente |
| --- | --- | --- |
| Referencia | `checkout_session_id` del alta (`toku_altas`, estado `PENDIENTE_INSCRIPCION`) | `sub_…` de la Subscription vigente |
| Link del proveedor | URL de la Checkout Session creada en el alta | URL de una Checkout Session **nueva** de inscripción para esa Subscription |
| ¿Se puede volver a pedir? | Sí: `GET /cl/checkout-sessions/{id}` devuelve la URL mientras esté `OPEN` [Inferencia] | Sí: `unique_external_id` por link la hace idempotente [Confirmado] |
| Vigencia | `expiration_datetime`; se puede **extender** con `PATCH` mientras esté abierta [Confirmado] | La fijamos igual al vencimiento de nuestro link |
| Retorno del socio | `redirection_data.success_url` / `failure_url` [Confirmado en el schema] | Igual, apuntando a nuestra página de retorno |
| Confirmación | Webhook `payment_method.*` + `GET /payment-methods?id_customer=` | Igual + reemplazo del medio anterior |
| Host permitido | ⚠️ Por definir con la primera sesión real (T-A2) | Igual |

**Ventaja de Toku:** la sesión acepta `success_url` y `failure_url` por request, así que el socio **sí vuelve** a nuestra página de retorno con la referencia del link (a diferencia del cambio de tarjeta de VirtualPOS y, posiblemente, de Payku).

## 2. Caso A · Alta

### `referenciaPara(socio, ALTA)`
El alta del socio en `toku_altas` con estado `PENDIENTE_INSCRIPCION` ([alta-socio.md](alta-socio.md)).

### `obtenerUrl(ALTA, idAlta, urlRetorno)`

```text
GET /cl/checkout-sessions/{checkout_session_id}
├─ COMPLETED → nada que hacer: confirmar el alta (alta-socio.md paso 7) y marcar el link COMPLETADO
├─ OPEN →
│    ¿expira antes que nuestro link? → PATCH /cl/checkout-sessions/{id} {expiration_datetime = vencimiento del link}
│    devolver la URL de la sesión
└─ EXPIRED →
     ¿la Subscription sigue en PAUSED (no se borró por abandono)?
     ├─ Sí → POST /cl/checkout-sessions nueva (unique_external_id = ALTA-{id_alta}-R{n}) → guardar → devolver URL
     └─ No → el alta se cerró: hace falta un alta nueva (alta-socio.md)
```

⚠️ **Coordinación con el alta:** el job del alta borra la Subscription pausada cuando la sesión expira ([alta-socio.md](alta-socio.md) paso 7). Si se emite un link de recuperación (A2), ese job debe **esperar** a que el link venza o se complete. Regla: no marcar el alta como `ABANDONADA` mientras tenga un link `EMITIDO`, `ABIERTO`, `VERIFICADO` o `REDIRIGIDO`.

### `confirmar(ALTA, idAlta)`
Es `confirmarAltaToku` de [alta-socio.md](alta-socio.md#5-implementación-backend-node-referencia): busca el `pm_`, lo asocia si hace falta y reactiva la Subscription.

## 3. Caso B · Socio existente

Reemplaza el "camino A" de [enroll-payment-method.md](enroll-payment-method.md#2-caminos-posibles) para socios que ya tienen una Subscription (tarjeta vencida, rechazos, PAC caído o cambio de medio).

### `referenciaPara(socio, CAMBIO)`
Su Subscription recurrente (por `product_id` → `GET /subscriptions/lookup?product_id=`). Aplica si `recurring.status` es `ACTIVE`, o `PAUSED` por llegar a `max_active_invoices` (cuotas impagas).

### `obtenerUrl(CAMBIO, sub_…, urlRetorno)`

```text
GET /subscriptions/{sub_…}                   → existe y es del socio (customer)
GET /payment-methods?id_customer={cus_…}     → guardar la huella: ids de los pm_ actuales y sus estados
POST /cl/checkout-sessions
   mode: ENROLLMENT, billing_data {id_account, id_customer, currency, ids_subscription: [sub_…]},
   redirection_data {success_url: urlRetorno, failure_url: urlRetorno + "&r=error"},
   unique_external_id: CAMBIO-{public_id del link},       ← idempotente: un doble clic devuelve la misma sesión
   expiration_datetime: vencimiento de nuestro link,
   skip_message_trigger: true                              ← el link lo enviamos nosotros
→ guardar id_checkout_session → devolver la URL
```

### `confirmar(CAMBIO, sub_…)`

```text
GET /cl/checkout-sessions/{id} → state
GET /payment-methods?id_customer={cus_…} → ¿hay un pm_ que no estaba en la huella, en chargeable o pending_activation?
├─ No → PENDIENTE (o FALLIDA si la sesión está EXPIRED)
└─ Sí →
     ¿el sub_ está en sus subscription_ids? → si no: POST /subscriptions/associate/payment-method
     ¿la Subscription estaba PAUSED por cuotas impagas (automática)?
       → verificar: GET /invoices?subscription_id=&general_status=unpaid (¿hay cuotas impagas?)
       → solo si las hay → POST /subscriptions/{sub_…}/status {ACTIVE}
       → si no las hay → la pausa fue manual; NO reactivar; registrar para revisión
     quitar el medio anterior: DELETE /payment-methods?id_payment_method={pm_viejo}
        ⚠️ solo cuando el nuevo esté chargeable (no pending_activation), tras confirmar T-L1,
        y solo si el pm_viejo no tiene otras Subscriptions activas (revisar subscription_ids)
     → INSCRITA
```

## 4. Endpoints

| Caso | Método | Endpoint | Para qué |
| --- | --- | --- | --- |
| A, B | `GET` | `/cl/checkout-sessions/{id}` | `state` y URL |
| A | `PATCH` | `/cl/checkout-sessions/{id}` | Extender `expiration_datetime` |
| A, B | `POST` | `/cl/checkout-sessions` | Sesión nueva (`mode: ENROLLMENT`) |
| B | `GET` | `/subscriptions/lookup?product_id=` | Subscription del socio |
| A, B | `GET` | `/payment-methods?id_customer=` | Medios de pago antes y después |
| A, B | `POST` | `/subscriptions/associate/payment-method` | Asociar el `pm_` nuevo |
| B | `POST` | `/subscriptions/{id}/status` | Reactivar si estaba pausada |
| B | `DELETE` | `/payment-methods?id_payment_method=` | Quitar el medio anterior (borrado lógico) |

## 5. Implementación (Node, referencia)

```js
const ESTADOS_OK = ['chargeable', 'pending_activation'];

const adaptadorToku = {
  async referenciaPara(socioId, caso) {
    if (caso === 'ALTA') return (await db.tokuAltas.findBySocio(socioId, 'PENDIENTE_INSCRIPCION'))?.id_alta;
    const s = await db.tokuSubscriptions.vigenteDelSocio(socioId);       // ACTIVE, o PAUSED por cuotas impagas
    return s?.subscription_id;
  },

  async obtenerUrl(caso, ref, urlRetorno, link) {
    if (caso === 'ALTA') {
      const alta = await db.tokuAltas.get(ref);
      const cs = await toku.get(`/cl/checkout-sessions/${alta.checkout_session_id}`);
      if (cs.state === 'COMPLETED') throw new YaCompletado();
      if (cs.state === 'OPEN') {
        if (new Date(cs.expiration_datetime) < link.expires_at)
          await toku.patch(`/cl/checkout-sessions/${alta.checkout_session_id}`, { expiration_datetime: link.expires_at.toISOString() });
        return cs.url;
      }
      return (await altaToku.nuevaSesion(alta, { expiresAt: link.expires_at })).url;   // EXPIRED, Subscription aún en pausa
    }

    const sub = await toku.get(`/subscriptions/${ref}`);
    const { items } = await toku.get('/payment-methods', { id_customer: sub.customer });
    const cs = await toku.post('/cl/checkout-sessions', {
      mode: 'ENROLLMENT', flow_name: process.env.TOKU_ENROLLMENT_FLOW,
      billing_data: { id_account: process.env.TOKU_ACCOUNT_ID, id_customer: sub.customer, currency: 'CLP', ids_subscription: [ref] },
      allowed_payment_options: ['transbank_oneclick'],   // solo PAT activo; agregar 'pac_inscription' cuando se habilite el PAC
      redirection_data: { success_url: urlRetorno, failure_url: `${urlRetorno}&r=error` },
      unique_external_id: `CAMBIO-${link.public_id}`,
      expiration_datetime: link.expires_at.toISOString(),
      skip_message_trigger: true,
    });
    await db.tokuCambios.upsert({ link_id: link.id, subscription_id: ref, customer_id: sub.customer,
      checkout_session_id: cs.id_checkout_session, pm_antes: items.map(i => i.payment_method.id),
      status_antes: sub.recurring?.status });
    return cs.url;
  },

  async confirmar(caso, ref) {
    if (caso === 'ALTA') return (await altaToku.confirmar(ref)) === 'ACTIVA' ? 'INSCRITA' : 'PENDIENTE';

    const c = await db.tokuCambios.ultimoPorSubscription(ref);
    const { items } = await toku.get('/payment-methods', { id_customer: c.customer_id });
    const nuevo = items.find(i => !c.pm_antes.includes(i.payment_method.id) && ESTADOS_OK.includes(i.payment_method.status));
    if (!nuevo) {
      const cs = await toku.get(`/cl/checkout-sessions/${c.checkout_session_id}`);
      return cs.state === 'EXPIRED' ? 'FALLIDA' : 'PENDIENTE';
    }
    if (!nuevo.subscription_ids.includes(ref)) {
      const r = await toku.post('/subscriptions/associate/payment-method',
        { id_subscription: ref, id_payment_method: nuevo.payment_method.id, payment_scope: 'SUBSCRIPTION' });
      if (!r.success) throw new Error(`Asociación rechazada: ${r.message}`);
    }
    // Reactivar solo si la pausa fue automática (max_active_invoices), no manual
    if (c.status_antes === 'PAUSED') {
      const { items: impagas } = await toku.get('/invoices',
        { subscription_id: ref, general_status: 'unpaid', page_size: 1 });
      if (impagas.length > 0)
        await toku.post(`/subscriptions/${ref}/status`, { status: 'ACTIVE' });
      else
        await db.log.warn('Subscription PAUSED sin cuotas impagas (pausa manual): no se reactiva', { sub: ref });
    }
    // Solo borrar el pm_ viejo si no tiene otras Subscriptions activas (ver T-L1)
    if (nuevo.payment_method.status === 'chargeable') {
      const { items: pmActuales } = await toku.get('/payment-methods', { id_customer: c.customer_id });
      for (const viejo of c.pm_antes) {
        const pmViejo = pmActuales.find(i => i.payment_method.id === viejo);
        if (!pmViejo) continue;
        const otrasActivas = (pmViejo.subscription_ids ?? []).filter(s => s !== ref);
        if (otrasActivas.length > 0) {
          await db.log.info('PM viejo tiene otras subs activas, no se elimina', { pm: viejo, otras: otrasActivas });
          continue;
        }
        await toku.delete('/payment-methods', { id_payment_method: viejo });
      }
    }
    await db.tokuCambios.update(c.id, { pm_nuevo: nuevo.payment_method.id, completado_at: new Date() });
    return 'INSCRITA';
  },
};
```

## 6. Errores

| Caso | Error / estado | Qué hacer |
| --- | --- | --- |
| A, B | `4xx` por `flow_name` | **Bloqueante** T-A1: escalar a Toku |
| A | Sesión `EXPIRED` y Subscription borrada | El alta se cerró: ofrecer un alta nueva |
| A | `PATCH` rechazado | Crear una sesión nueva con sufijo `-R{n}` |
| B | Subscription inexistente o de otro Customer | No aplica: revocar el link |
| B | `200` con `success: false` al asociar | Leer `message`; revisión manual |
| B | `400` al borrar el `pm_` viejo | No puede pasar a `deleted` desde su estado: dejarlo y registrar |
| B | `pm_` nuevo en `pending_activation` (PAC) | Normal: el banco tarda 24–48 h hábiles. No borrar el anterior todavía |
| A, B | `payment_method_inscription_intent.failed` | Mostrar error en el retorno y permitir reintentar con el mismo link |
| A, B | Host de la URL no está en la lista | La capa común bloquea y alerta (la lista se completa con T-A2) |

## 7. Pendientes por confirmar con Toku

| # | Pregunta | Por qué importa |
| --- | --- | --- |
| T-A1, T-A2, T-A4 | Ver [alta-socio.md § 9](alta-socio.md#9-pendientes-por-confirmar-con-toku) | Flujo de inscripción, ruta y campo de la URL, asociación automática |
| T-L1 | Cuando un Customer tiene dos medios de pago asociados a la misma Subscription, ¿cuál cobra Toku? ¿Se puede borrar el viejo apenas el nuevo queda `chargeable`? | Define cuándo quitar el medio anterior |
| T-L2 | ¿En qué dominio vive el Checkout? ¿Es fijo? | Lista de hosts permitidos de la capa común |
| T-L3 | Al reactivar una Subscription pausada por cuotas impagas, ¿Toku cobra esas cuotas con el medio nuevo? | Expectativa que le damos al socio |

## 8. Probarlo en Postman

Carpeta **`01 · Link de inscripción`** de `Toku API.postman_collection.json`, con dos subcarpetas que se corren por separado con **Run folder**. ⚠️ **Producción:** solo objetos `TEST-`.

| Subcarpeta | Request | Qué hace | Siguiente |
| --- | --- | --- | --- |
| A · Alta pendiente | LA-1 Estado de la sesión del alta | Lee `checkout_session_id` (del alta) | `OPEN` → LA-2 · `EXPIRED` → LA-3 · Otro → FIN |
| | LA-2 Extender sesión | `PATCH` de `expiration_datetime` a +72 h | FIN |
| | LA-3 Sesión nueva del alta | `ENROLLMENT` con `unique_external_id` `-R{n}` | FIN |
| B · Socio existente | LB-1 Buscar Subscription | `lookup` por `li_product_id` | LB-2 |
| | LB-2 Medios de pago actuales | Guarda los `pm_` actuales en `li_pm_before` | LB-3 |
| | LB-3 Crear sesión de inscripción | `ENROLLMENT` sobre la Subscription; URL en consola | LB-4 |
| | LB-4 Estado de la sesión | `COMPLETED` → LB-5 · Otro → FIN | |
| | LB-5 Detectar medio nuevo | Compara con `li_pm_before` | Asociado → FIN · No → LB-6 |
| | LB-6 Asociar medio nuevo | Asocia el `pm_` a la Subscription | FIN |
| | LB-7 Quitar medio anterior | **Solo a mano**, tras confirmar T-L1 | — |

**Variables de colección:** `li_product_id` (debe empezar con `TEST-`), `li_return_url`, y las que llenan los scripts: `li_subscription_id`, `li_customer_id`, `li_pm_before`, `li_pm_new`, `li_pm_old`, `li_cs_id`, `li_cs_url`, `li_cs_expiration`, `li_attempt`. La subcarpeta A usa las del alta (`checkout_session_id`, `customer_id`, `subscription_id`, `alta_*`).

**Paso manual (B):** tras LB-3, abre la URL de la consola, inscribe el medio de pago y envía **LB-4** a mano. LB-3 también muestra el host del Checkout para completar la lista permitida (T-L2).
