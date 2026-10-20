# Flujo: link de inscripción de tarjeta (adaptador VirtualPOS)

**Objetivo:** que la [capa común de link seguro](../../../../Transversal/docs/transversal/workflows/link-seguro-inscripcion.md) pueda llevar a un socio de VirtualPOS al formulario donde inscribe su tarjeta, tanto en un **alta** como para un **socio existente**.
**Recursos:** Suscription · **Postman:** carpetas `00 · Alta de socio (flujo)` (caso A) y `01 · Cambio de tarjeta` (caso B)
**Relacionados:** [alta-socio.md](alta-socio.md) · [cambio-tarjeta.md](cambio-tarjeta.md) · [reintento-cobro-rechazado.md](reintento-cobro-rechazado.md)

## 1. Resumen

| | A. Alta | B. Socio existente |
| --- | --- | --- |
| Referencia | `suscription.id` en `SUSCRIBIENDO` (de `vpos_suscriptions`) | `suscription.id` en `ACTIVA` |
| Link del proveedor | `url_redirect` de `POST /v3/suscription` | `change_card_url` de `PUT /v3/suscription/{id}/changecard` |
| ¿Se puede volver a pedir? | **No:** la API no lo devuelve después. Hay que **guardarlo** al crear | Sí: cada `PUT` genera uno nuevo |
| Vigencia | Hasta que la suscripción pase a `FINALIZADA` (30 días por defecto) ✅ | `change_card_expiration_date` ✅ |
| Retorno del socio | `return_url` (Base64) fijado al crear la suscripción ✅ | ⚠️ No documentado: `changecard` no recibe `return_url` |
| Confirmación | `callback_url` + `GET /v3/suscription/{id}` → `ACTIVA` | Sin webhook: comparar la huella de `payment_method` |
| Host permitido | `pat.virtualpos.cl` | `pat.virtualpos.cl` |

## 2. Caso A · Alta

### `referenciaPara(socio, ALTA)`
La fila de `vpos_suscriptions` del socio en `SUSCRIBIENDO`, creada por [alta-socio.md](alta-socio.md) (paso 6).

### `obtenerUrl(ALTA, susId)`

```text
GET /v3/suscription/{susId}
├─ SUSCRIBIENDO → devolver el url_redirect GUARDADO al crearla
├─ ACTIVA → nada que hacer: marcar el link COMPLETADO
└─ SUSCRIPCION_FALLIDA / FINALIZADA → el link ya no sirve:
     crear una suscripción NUEVA (alta-socio.md, pasos 5 y 6, mismo plan y service_id)
     → guardar el nuevo id y url_redirect → actualizar la referencia del link → devolver la nueva URL
```

### `confirmar(susId)`
`GET /v3/suscription/{susId}` → `ACTIVA` = `INSCRITA` (además guarda `charge_program[]`, como en el alta). `SUSCRIPCION_FALLIDA` = `FALLIDA`.

### Retorno
VirtualPOS vuelve a la `return_url` que se fijó al **crear** la suscripción. Para que sirva también a los links de recuperación, el alta debe crearla apuntando a una página genérica: `https://socios.techo.org/inscripcion/retorno/virtualpos`. Esa página busca el alta por la sesión (A1) o por la cookie de la capa común (A2) y **siempre** confirma por API.

## 3. Caso B · Socio existente

Es el flujo de [cambio-tarjeta.md](cambio-tarjeta.md), con una diferencia: el link **no** se genera al detectar el problema, sino cuando el socio hace clic en nuestro link (paso 5 de la capa común). Así nunca recibe un `change_card_url` vencido.

### `referenciaPara(socio, CAMBIO)`
Su suscripción `ACTIVA` en VirtualPOS. Si tiene más de una, el link se emite para una sola (la del motivo: cargo rechazado o tarjeta por vencer).

### `obtenerUrl(CAMBIO, susId)`

```text
GET /v3/suscription/{susId}
├─ status ≠ ACTIVA → no aplica (revocar el link y avisar a operaciones)
└─ ACTIVA → guardar la huella actual: payment_method.bin + last4CardDigit + expiration_date + brand
   ¿Hay un change_card_url vigente en card_change_requests? (no expirado)
   ├─ Sí → reutilizarlo
   └─ No → PUT /v3/suscription/{susId}/changecard → change_card_url + change_card_expiration_date → guardar
```

### `confirmar(susId)`
`GET /v3/suscription/{susId}` y comparar la huella de `payment_method` con la guardada: distinta = `INSCRITA`. Después, **recuperar los cargos rechazados** ([cambio-tarjeta.md § paso 6](cambio-tarjeta.md#3-flujo)).

### Retorno
⚠️ `changecard` no acepta `return_url`, así que el socio **no vuelve** a nuestra página: ve la confirmación de VirtualPOS. La confirmación depende del job (diario, o cada hora durante las primeras 24 h después del clic). Pendiente: preguntar a soporte@virtualpos.cl si se puede configurar una URL de retorno para el cambio de tarjeta.

## 4. Endpoints

| Caso | Método | Endpoint | Para qué |
| --- | --- | --- | --- |
| A, B | `GET` | `/v3/suscription/{suscription_id}` | Estado y `payment_method` |
| A | `POST` | `/v3/suscription` | Nueva suscripción si la anterior falló o expiró |
| B | `PUT` | `/v3/suscription/{suscription_id}/changecard` | `change_card_url` |
| B | `GET` | `/v3/suscription/{suscription_id}/charges?status=rechazado` | Cargos para reintentar tras el cambio |

## 5. Implementación (Node, referencia)

```js
const huella = (pm) => [pm?.bin, pm?.last4CardDigit, pm?.expiration_date, pm?.brand].join('|');

const adaptadorVirtualpos = {
  async referenciaPara(socioId, caso) {
    if (caso === 'ALTA') return (await db.vposSuscriptions.findBySocio(socioId, ['SUSCRIBIENDO', 'SUSCRIPCION_FALLIDA', 'FINALIZADA']))?.id;
    return (await db.vposSuscriptions.findBySocio(socioId, ['ACTIVA']))?.id;
  },

  async obtenerUrl(caso, susId) {
    const { suscription: s } = await vpos.get(`/v3/suscription/${susId}`);
    if (caso === 'ALTA') {
      if (s.status === 'SUSCRIBIENDO') return (await db.vposSuscriptions.get(susId)).url_redirect;
      if (s.status === 'ACTIVA') throw new YaCompletado();
      // Verificar si ya existe una suscripción ACTIVA para este service_id antes de crear una nueva
      const activa = await db.vposSuscriptions.findBySocio(socioId, ['ACTIVA']);
      if (activa) throw new YaCompletado(); // La tarjeta ya fue inscrita en otra suscripción
      const nueva = await altaVpos.recrearSuscripcion(susId);          // alta-socio.md pasos 5-6
      return nueva.url_redirect;
    }
    if (s.status !== 'ACTIVA') throw new NoAplica(s.status);
    const vigente = await db.cardChanges.findVigente(susId);
    if (vigente) return vigente.url;
    const r = await vpos.put(`/v3/suscription/${susId}/changecard`);
    await db.cardChanges.insert({ suscription_id: susId, motivo: 'LINK_SEGURO', url: r.change_card_url,
      expires_on: r.change_card_expiration_date, huella_anterior: huella(s.payment_method), status: 'ENVIADO' });
    return r.change_card_url;
  },

  async confirmar(caso, susId) {
    const { suscription: s } = await vpos.get(`/v3/suscription/${susId}`);
    if (caso === 'ALTA') return { ACTIVA: 'INSCRITA', SUSCRIBIENDO: 'PENDIENTE' }[s.status] || 'FALLIDA';
    // findLatest (no findVigente): aunque el link haya expirado, si la huella cambió la tarjeta se inscribió correctamente
    const req = await db.cardChanges.findLatest(susId);
    return req && huella(s.payment_method) !== req.huella_anterior ? 'INSCRITA' : 'PENDIENTE';
  },
};
```

## 6. Errores

| Caso | Error / estado | Qué hacer |
| --- | --- | --- |
| A | No hay `url_redirect` guardado | Crear una suscripción nueva (no se puede recuperar el link por API) |
| A | `FINALIZADA` (30 días) | Suscripción nueva; la anterior queda como abandonada |
| B | `E-053` | La suscripción no existe o no permite cambio: revisar estado |
| B | `CANCELADA` / `FINALIZADA` | No aplica: revocar el link |
| A, B | Host distinto de `pat.virtualpos.cl` | La capa común bloquea y alerta |

## 7. Probarlo en Postman

| Caso | Carpeta | Requests |
| --- | --- | --- |
| A | `00 · Alta de socio (flujo)` | AS-6 genera el `url_redirect`; AS-7 confirma |
| B | `01 · Cambio de tarjeta` | CT-1 guarda la huella; CT-2 genera el `change_card_url`; CT-3 detecta el cambio; CT-4 y CT-5 recuperan los rechazados |

No hace falta una carpeta nueva: el link seguro es una capa de nuestro backend, y los requests al proveedor son los mismos.
