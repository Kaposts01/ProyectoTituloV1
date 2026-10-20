# Flujo: cambiar el monto del aporte (adaptador Payku)

**Objetivo:** cambiar el monto de la suscripción de un socio en Payku, con vigencia desde la **próxima cuota no cobrada**. La API no lo permite, así que el camino normal es el **portal de Payku** y la alternativa es una **suscripción nueva** por API.
**Recursos:** Cliente (`cl…`) · Suscripción (`su…`) · Plan (`pl…`) · **Postman:** carpeta `03 · Cambiar monto`
**Relacionados:** [capa común cambiar-monto](../../../../Transversal/docs/transversal/workflows/cambiar-monto.md) · [alta-socio.md](alta-socio.md) · [link-inscripcion.md](link-inscripcion.md) · [subscriptions.md](../subscriptions.md)

## 1. Qué permite Payku

| Vía | ¿Cambia el monto? | Respaldo |
| --- | --- | --- |
| API | ❌ No existe `PUT`/`PATCH` de suscripción. `amount` solo se envía al **crear** (planes variables) | Doc oficial v2.1.01 revisada el 2026-10-12: 17 endpoints de suscripción, ninguno edita ✅ |
| **Portal de Payku** | ✅ Permite cambiar el monto, incluso en suscripciones de **plan fijo** | Observado por TECHO en el portal (2026-10-12). ⚠️ Comportamiento no documentado (Q-31, Q-32) |
| Suscripción nueva | ✅ Con el plan del monto nuevo | API documentada ✅. El socio vuelve a inscribir la tarjeta y paga $50 de validación ✅ |

**Cómo verificar por API:** `GET /api/suclient/{cl…}` devuelve `subcriptions.amount` (string) ✅. Después del primer cobro con el monto nuevo, también `paid[].amount_paid` en V3.

## 2. Camino A · Portal (normal)

```text
PASO 1 · Estado actual                          GET /api/suclient/{cl…}
↓  subcriptions.status == active · guardar subcriptions.amount (anterior)
↓
PASO 2 · Tarea para operaciones                  (backoffice)
↓  "Cambiar el monto de su… (cliente cl…, email …) de $A a $B desde la próxima cuota"
↓  La tarea indica la fecha límite: antes del próximo cobro, si se quiere que rija en esa cuota
↓
PASO 3 · Operaciones lo cambia en el portal de Payku y marca la tarea como hecha
↓
PASO 4 · Verificar por API                      GET /api/suclient/{cl…}
↓  ├─ subcriptions.amount == nuevo → APLICADO
↓  └─ distinto → devolver la tarea a operaciones (no se cierra el cambio)
↓
PASO 5 · Confirmar con el primer cobro           GET /api/sususcriptionv3 (barrido) o webhook de cobro
↓  paid[].amount_paid del siguiente ciclo == nuevo → cierre definitivo
↓  ⚠️ Si se cobró el monto anterior: revisar si el portal aplica el cambio al ciclo en curso (Q-32)
```

**Regla de vigencia:** si el cambio se aplica en el portal **antes** del próximo cobro, rige en esa cuota. Si el cobro ya se hizo o está en reintento, rige desde la siguiente.

## 3. Camino B · Suscripción nueva (alternativa)

Para cuando el portal no está disponible o la operación no puede hacerse a tiempo.

```text
PASO 1 · Estado actual                          GET /api/sususcription/{su…}  → active
↓
PASO 2 · Plan del monto nuevo                   Catálogo payku_plans_catalog (fijo) o plan variable + amount (alta-socio.md § 9)
↓
PASO 3 · Crear la suscripción nueva             POST /api/sususcription {plan, client, amount?}
↓  → su_nueva + url · guardar en suscripcion_cambios (PENDIENTE_REINSCRIPCION)
↓  La anterior SIGUE activa (el socio sigue aportando el monto anterior)
↓
PASO 4 · Link seguro al socio                   caso CAMBIO_MONTO → url de su_nueva (inscribe tarjeta, $50)
↓
PASO 5 · Nueva activa                           webhook url_notify_suscription + GET /api/sususcription/{su_nueva} → active
↓
PASO 6 · Evitar doble cobro                     Plan fijo: el primer cobro es "a partir del mes siguiente" ✅
↓  ├─ La anterior ya cobró este mes → OK: la nueva empieza el mes siguiente
↓  └─ La anterior NO cobró este mes → el mes quedaría sin cobro: decidir con el socio
↓       (cobro único del mes con POST /api/transaction, como el primer aporte del alta) o aceptar el mes sin cobro
↓  ⚠️ Plan variable: no se sabe si cobra al activarse (Q-27)
↓
PASO 7 · Eliminar la anterior                   DELETE /api/sususcription/{su_anterior} → GET para ver el estado final (Q-13)
↓
RESULTADO: su_nueva activa con el monto nuevo; su_anterior eliminada; un solo cobro por mes
```

## 4. Endpoints

| Camino | Método | Endpoint | `Sign` | Para qué |
| --- | --- | --- | --- | --- |
| A, B | `GET` | `/api/suclient/{cl…}` | ✅ | `subcriptions.amount`, estado |
| A | `GET` | `/api/sususcriptionv3` | ✅ | `paid[].amount_paid` del ciclo siguiente |
| B | `GET` | `/api/suplan/plans` | ✅ | Validar el plan de destino |
| B | `POST` | `/api/sususcription` | ✅ | Suscripción nueva |
| B | `GET` | `/api/sususcription/{id}` | ✅ | Estado de la nueva y de la anterior |
| B | `DELETE` | `/api/sususcription/{id}` | ✅ | Eliminar la anterior |
| B | `POST` | `/api/transaction` | No | Cobro único del mes, si se decide |

## 5. Implementación (Python, referencia)

```python
class CambiarMontoPayku:
    def cambiar_monto(self, sus, monto_nuevo: int, cambio, via: str = "PORTAL") -> str:
        cl = payku.get(f"/api/suclient/{sus.payku_client_id}")
        if (cl.get("subcriptions") or {}).get("status") != "active":
            raise NoAplica("La suscripción no está activa")
        cambio.update(monto_anterior=int(cl["subcriptions"]["amount"]))

        if via == "PORTAL":
            tareas.crear("payku", sus.socio_id,
                         f"Cambiar monto de {sus.payku_subscription_id} (cliente {sus.payku_client_id}) "
                         f"de ${cambio.monto_anterior} a ${monto_nuevo} desde la próxima cuota",
                         vence=proximo_cobro(sus))
            cambio.update(estado="PENDIENTE_OPERACION", metodo="PORTAL")
            return "PENDIENTE_OPERACION"

        plan = repo.planes.find_fijo(amount=monto_nuevo, currency="CLP")
        body = {"plan": plan.plan_id, "client": sus.payku_client_id} if plan else {
            "plan": settings.PAYKU_PLAN_VARIABLE_ID, "client": sus.payku_client_id, "amount": str(monto_nuevo)}
        r = payku.post("/api/sususcription", body)            # sin reintentos a ciegas (no hay idempotencia)
        if r.get("status") == "failed":
            raise ErrorPayku(r)
        cambio.update(estado="PENDIENTE_REINSCRIPCION", metodo="NUEVA_SUSCRIPCION",
                      suscripcion_nueva_id=r["id"], activation_url=r["url"])
        links.emitir(sus.socio_id, canal="payku", caso="CAMBIO_MONTO", referencia=cambio.id)
        return "PENDIENTE_REINSCRIPCION"

    def verificar(self, cambio) -> str:
        if cambio.metodo == "PORTAL":
            cl = payku.get(f"/api/suclient/{cambio.payku_client_id}")
            return "APLICADO" if int((cl.get("subcriptions") or {}).get("amount", 0)) == cambio.monto_nuevo else "PENDIENTE"
        s = payku.get(f"/api/sususcription/{cambio.suscripcion_nueva_id}")
        return {"active": "APLICADO", "register": "PENDIENTE"}.get(s.get("status"), "FALLIDO")

    def cerrar(self, cambio) -> None:                         # solo camino B, con la nueva activa
        # Guardia: nunca borrar la suscripción nueva por error de variable
        assert cambio.suscripcion_id != cambio.suscripcion_nueva_id, (
            f"suscripcion_id == suscripcion_nueva_id ({cambio.suscripcion_id}): "
            "riesgo de eliminar la suscripción recién creada"
        )
        if not ya_cobro_este_mes(cambio.suscripcion_id):
            tareas.crear("payku", cambio.socio_id, "Mes en curso sin cobro: decidir cobro único o dejarlo")
        payku.delete(f"/api/sususcription/{cambio.suscripcion_id}")
        estado = payku.get(f"/api/sususcription/{cambio.suscripcion_id}").get("status")   # delete o cancel (Q-13)
        cambio.update(estado="APLICADO", aplicado_at=now(), estado_final_anterior=estado)
```

## 6. Errores y casos borde

| Caso | Qué hacer |
| --- | --- |
| HTTP 200 con `status: failed` | Es un error ✅ |
| Portal: `subcriptions.amount` no cambia tras la tarea | Devolver la tarea; no cerrar el cambio |
| Portal: el siguiente cobro sale con el monto anterior | Revisar Q-32; el cambio rige desde el ciclo siguiente |
| Cliente con dos suscripciones | `subcriptions` es un objeto (Q-23): usar `GET /api/sususcription/{id}` y el monto de nuestra base |
| B: el socio no inscribe la tarjeta en 7 días | Eliminar la suscripción nueva (`register`); la anterior sigue activa |
| B: timeout al crear la nueva | No reintentar: buscar la suscripción nueva del cliente antes de crear otra |

## 7. Preguntas abiertas

Q-31 (¿qué endpoint usa el portal para cambiar el monto? ¿Puede exponerse por API?) y Q-32 (¿el cambio en el portal aplica al ciclo en curso, y se refleja en `subcriptions.amount` y V3?). También afectan Q-13, Q-23 y Q-27. Ver [open-questions.md](../open-questions.md).

## 8. Probarlo en Postman

Carpeta **`03 · Cambiar monto`** de `Payku API v2.postman_collection.json` (sandbox), con dos subcarpetas:

| Subcarpeta | Request | Qué hace | Siguiente |
| --- | --- | --- | --- |
| A · Portal | CA-1 Monto actual | Muestra `subcriptions.amount` y guarda el monto anterior | FIN (cambiar en el portal) |
| | CA-2 Verificar cambio del portal | Compara `subcriptions.amount` con `cm_monto` (Q-32) | FIN |
| B · Suscripción nueva | CB-1 Plan del monto nuevo | Elige el plan (catálogo `alta_planes_fijos` o variable) y arma el body | CB-2 |
| | CB-2 Crear suscripción nueva | `POST` → `url` en consola | CB-3 |
| | CB-3 Confirmar nueva | `active` → CB-4 · Otro → FIN | |
| | CB-4 Eliminar la anterior ⚠️ | `DELETE` de **`cm_old_subscription_id`** (guardado en CB-1). El script verifica que `cm_old_subscription_id ≠ cm_new_subscription_id` antes de enviar. **Requiere confirmación manual** en el Collection Runner. | CB-5 |
| | CB-5 Estado final de la anterior | `delete` o `cancel` (Q-13) | FIN |

**Variables de entorno:** `client_id`, `subscription_id` (la anterior; CB-1 la copia en `cm_old_subscription_id` antes de que CB-2 sobrescriba `subscription_id`), `cm_monto`, y para B `alta_planes_fijos` y `alta_plan_variable_id`. Los scripts llenan `cm_monto_anterior`, `cm_old_subscription_id`, `cm_sub_body`, `cm_new_subscription_id` y `cm_new_url`.

> ⚠️ **CB-4 es manual**: antes de enviar el DELETE, confirma en consola que `cm_old_subscription_id` (la que se va a eliminar) es distinta de `cm_new_subscription_id` (la recién creada). Si son iguales, algo falló en CB-1.
