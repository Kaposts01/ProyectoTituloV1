# Flujo: link de inscripción de tarjeta (adaptador Payku)

**Objetivo:** que la [capa común de link seguro](../../../../Transversal/docs/transversal/workflows/link-seguro-inscripcion.md) pueda llevar a un socio de Payku al formulario donde inscribe su tarjeta, tanto en un **alta** como para un **socio existente**.
**Recursos:** Suscripción (`su…`) · Tarjetas (`surec…`) · **Postman:** carpeta `01 · Link de inscripción`
**Relacionados:** [alta-socio.md](alta-socio.md) · [update-card.md](update-card.md) · [suspend-subscription.md](suspend-subscription.md) · [cards.md](../cards.md)

## 1. Resumen

| | A. Alta | B. Socio existente |
| --- | --- | --- |
| Referencia | `su…` en `register` (de `payku_altas`) | `su…` en `active` o `suspended` |
| Link del proveedor | `url` de `POST /api/sususcription` ✅ | `url` de `POST /api/suinscriptionscards` ✅ |
| ¿Se puede volver a pedir? | ⚠️ No documentado si `suinscriptionscards` sirve para una suscripción en `register` (Q-29). Si no, hay que crear otra suscripción | Sí: cada llamada genera una `url` nueva |
| Vigencia | ⚠️ No documentada (Q-16) | ⚠️ No documentada (Q-16) |
| Retorno del socio | ⚠️ `url_success_payment` / `url_failed_payment` **del plan** (Q-28) | ⚠️ Igual (Q-28) |
| Confirmación | Webhook `url_notify_suscription` + `GET /api/sususcription/{id}` → `active` | Sin webhook documentado: comparar `active_cards[].identifier` |
| Host permitido | `des.payku.cl` (sandbox), `app.payku.cl` (producción) | Igual |
| Cobros al inscribir | $50 de validación ✅ | ⚠️ ¿$50 otra vez? (Q-15) · ✅ puede cobrar **meses atrasados** de inmediato |

## 2. Caso A · Alta

### `referenciaPara(socio, ALTA)`
El alta del socio en `payku_altas` con estado `PENDIENTE_ACTIVACION` ([alta-socio.md](alta-socio.md)).

### `obtenerUrl(ALTA, idAlta)`

```text
GET /api/sususcription/{su…}
├─ active → nada que hacer: marcar el link COMPLETADO
├─ register →
│    ¿La url guardada tiene menos de 24 h? (💡 margen prudente mientras no se resuelva Q-16)
│    ├─ Sí → devolverla
│    └─ No → POST /api/suinscriptionscards {suscription: su…}
│             ├─ status success → guardar y devolver la url nueva          (⚠️ Q-29)
│             └─ failed → DELETE /api/sususcription/{su…} y crear otra (alta-socio.md paso 4)
└─ otro (delete, cancel, finish) → crear una suscripción nueva (alta-socio.md pasos 2-4)
```

### `confirmar(ALTA, idAlta)`
Igual que el paso 6 del alta: `GET /api/sususcription/{su…}` → `active` = `INSCRITA`. Después, el alta sigue con el **primer aporte** ([alta-socio.md](alta-socio.md) paso 7).

## 3. Caso B · Socio existente

Reemplaza la parte de generación del link de [update-card.md](update-card.md): la `url` se pide **al hacer clic**, no al detectar el problema (su vigencia es desconocida).

### `referenciaPara(socio, CAMBIO)`
Su suscripción en `active` o `suspended`. `suspended` es el caso más importante: Payku la reactiva sola si el socio inscribe una tarjeta nueva ✅ ([suspend-subscription.md](suspend-subscription.md)).

### `obtenerUrl(CAMBIO, su…)`

```text
GET /api/sususcription/{su…}
├─ register / delete / cancel / finish → no aplica (revocar el link y avisar a operaciones)
└─ active / suspended →
     guardar la huella: lista de active_cards[].identifier + status actual
     ¿Pedimos una url para este link hace menos de 30 min? → reutilizarla (evita generar varias por doble clic)
     └─ No → POST /api/suinscriptionscards {suscription: su…} → url → guardar
```

**Antes de redirigir**, la pantalla de la capa común muestra el aviso: *"Al registrar tu tarjeta, Payku puede cobrar de inmediato los aportes pendientes."* ✅

### `confirmar(CAMBIO, su…)`

```text
GET /api/sususcription/{su…}
├─ hay un identifier en active_cards que no estaba en la huella → INSCRITA
│    ├─ status era suspended → ¿pasó a active? revisar logs.status[] y transactions[] (cobro de atrasados)
│    └─ (opcional) quitar la tarjeta anterior: POST /api/suscriptionsdeletecards  ⚠️ solo tras validar Q-09
└─ sin tarjeta nueva → PENDIENTE
```

💡 No quitar la tarjeta anterior hasta resolver Q-09 y saber qué tarjeta usa Payku cuando hay varias (💡 la más reciente, `cards`). Una tarjeta vieja de más no rompe nada; borrar la equivocada sí.

## 4. Retorno del socio

Payku redirige a las URL **del plan** (fijas para todos los socios del plan). Configurarlas en el panel como:

| Campo del plan | Valor |
| --- | --- |
| `url_success_payment` | `https://socios.techo.org/inscripcion/retorno/payku?r=ok` |
| `url_failed_payment` | `https://socios.techo.org/inscripcion/retorno/payku?r=error` |

La página identifica el link por la **sesión** de la capa común (o la cookie del alta, caso A1) y confirma por API. ⚠️ Validar Q-28: si Payku no usa esas URL al inscribir tarjeta, el socio se queda en la página de Payku y la confirmación depende del webhook y del job.

## 5. Endpoints

| Caso | Método | Endpoint | `Sign` | Para qué |
| --- | --- | --- | --- | --- |
| A, B | `GET` | `/api/sususcription/{id}` | ✅ | Estado, `active_cards`, `logs` |
| A, B | `POST` | `/api/suinscriptionscards` | ✅ | `url` para inscribir una tarjeta |
| A | `DELETE` | `/api/sususcription/{id}` | ✅ | Descartar un alta cuyo link ya no se puede renovar |
| B | `POST` | `/api/suscriptionsdeletecards` | ✅ | Quitar la tarjeta anterior (⚠️ Q-09) |

## 6. Implementación (Python, referencia)

```python
class AdaptadorPayku:
    def referencia_para(self, socio_id: str, caso: str) -> str | None:
        if caso == "ALTA":
            alta = repo.altas.find(socio_id=socio_id, estado="PENDIENTE_ACTIVACION")
            return alta.id_alta if alta else None
        sus = repo.suscripciones.find(socio_id=socio_id, status_in=("active", "suspended"))
        return sus.payku_subscription_id if sus else None

    def obtener_url(self, caso: str, ref: str, url_retorno: str) -> str:   # url_retorno: fija en el plan
        if caso == "ALTA":
            alta = repo.altas.get(ref)
            s = payku.get(f"/api/sususcription/{alta.subscription_id}")
            if s.get("status") == "active":
                raise YaCompletado()
            if s.get("status") == "register" and alta.activation_url_at > now() - timedelta(hours=24):
                return alta.activation_url
            if s.get("status") == "register":
                r = payku.post("/api/suinscriptionscards", {"suscription": alta.subscription_id})   # Q-29
                if r.get("status") == "success" and r.get("url"):
                    repo.altas.update(ref, activation_url=r["url"], activation_url_at=now())
                    return r["url"]
                payku.delete(f"/api/sususcription/{alta.subscription_id}")
            return alta_payku.recrear_suscripcion(ref)                       # alta-socio.md paso 4

        s = payku.get(f"/api/sususcription/{ref}")
        if s.get("status") not in ("active", "suspended"):
            raise NoAplica(s.get("status"))
        reciente = repo.card_links.reciente(ref, minutes=30)
        if reciente:
            return reciente.url
        r = payku.post("/api/suinscriptionscards", {"suscription": ref})
        if r.get("status") != "success" or not r.get("url"):
            raise ErrorPayku(r)
        repo.card_links.insert(subscription_id=ref, url=r["url"], status_antes=s["status"],
                               cards_antes=[c["identifier"] for c in s.get("active_cards") or []])
        return r["url"]

    def confirmar(self, caso: str, ref: str) -> str:
        if caso == "ALTA":
            return "INSCRITA" if alta_payku.confirmar_suscripcion(ref) == "ACTIVA" else "PENDIENTE"
        req = repo.card_links.ultimo(ref)
        s = payku.get(f"/api/sususcription/{ref}")
        nuevas = {c["identifier"] for c in s.get("active_cards") or []} - set(req.cards_antes)
        if not nuevas:
            return "PENDIENTE"
        repo.card_links.update(req.id, completado_at=now(), card_nueva=next(iter(nuevas)), status_despues=s["status"])
        return "INSCRITA"
```

## 7. Errores

| Caso | Error / estado | Qué hacer |
| --- | --- | --- |
| Todos | HTTP 200 con `status: failed` | Es un error ✅: revisar siempre `status` |
| A | `suinscriptionscards` falla en `register` (Q-29) | Borrar la suscripción y crear otra |
| A | La `url` guardada ya no abre (Q-16) | Mismo camino: pedir una nueva |
| B | Suscripción `delete` / `cancel` / `finish` | No aplica: revocar el link; el socio necesita un alta nueva |
| B | Sin tarjeta nueva tras 72 h | El link vence; recordatorio o link nuevo (máx. 2) → gestión manual |
| B | `suspended` sigue así después de la tarjeta nueva | Revisar `transactions[]`: el cobro de atrasados pudo ser rechazado |
| A, B | Host distinto de `des.payku.cl` / `app.payku.cl` | La capa común bloquea y alerta |

## 8. Preguntas abiertas que afectan este flujo

Q-09 (body de eliminar tarjeta), Q-15 ($50 al cambiar tarjeta), Q-16 (vigencia de la `url`), Q-28 (retorno a las URL del plan) y **Q-29** (¿`suinscriptionscards` genera una `url` nueva para una suscripción en `register`?). Ver [open-questions.md](../open-questions.md).

## 9. Probarlo en Postman

Carpeta **`01 · Link de inscripción`** de `Payku API v2.postman_collection.json` (sandbox), con dos subcarpetas que se corren por separado con **Run folder**:

| Subcarpeta | Request | Qué hace | Siguiente |
| --- | --- | --- | --- |
| A · Alta pendiente | LA-1 Estado de la suscripción del alta | Muestra el estado de `subscription_id` y la `activation_url` guardada | `register` → LA-2 · Otro → FIN |
| | LA-2 Renovar link del alta (Q-29) | Prueba `suinscriptionscards` sobre la suscripción en `register` | FIN |
| B · Socio existente | LB-1 Validar suscripción | `active`/`suspended` → guarda las tarjetas actuales en `li_cards_before` | LB-2 |
| | LB-2 Generar link de tarjeta | `suinscriptionscards` → `url` en consola | LB-3 |
| | LB-3 Detectar tarjeta nueva | Compara `active_cards` con `li_cards_before` | FIN |
| | LB-4 Eliminar tarjeta anterior | **Solo a mano**, después de validar Q-09 | — |

**Variables de entorno:** la subcarpeta A usa `subscription_id` y `activation_url` del alta; la B usa `li_subscription_id` (si está vacía, toma `subscription_id`). Los scripts llenan `li_cards_before`, `li_status_before`, `li_url`, `li_card_new` y `li_card_old`.

**Paso manual (B):** tras LB-2, abre la `url`, inscribe otra tarjeta de prueba y envía **LB-3** a mano. LB-2 también verifica que el host esté en la lista permitida.
