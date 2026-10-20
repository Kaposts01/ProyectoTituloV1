# Flujo transversal: cambiar el monto del aporte

> Comparacion del comportamiento entre VirtualPOS, Toku y Payku para el flujo de cambio de monto de una suscripcion recurrente.
> Fuente: adaptadores por canal en `workflows/cambiar-monto.md` de cada canal.

---

## Que permite cada canal por API

| Dimension | VirtualPOS | Toku | Payku |
|---|---|---|---|
| Editar monto de la suscripcion por API | **No existe** endpoint de edicion. Solo crear, recuperar, cancelar, listar y changecard. | **Si:** `PUT /subscriptions/{id}` con campo `amount` (numero entero, no string). "Cambios aplican a Invoices que se generen en adelante." | **No existe** `PUT`/`PATCH` de suscripcion por API (17 endpoints revisados al 2026-10-12, ninguno edita). |
| Alternativa por portal | No aplica (el modelo es siempre suscripcion nueva) | No aplica (hay API) | **Si:** el portal de Payku permite cambiar el monto incluso en planes fijos. Comportamiento no documentado (Q-31, Q-32). |
| Alternativa por API | Suscripcion nueva al plan fijo del monto nuevo (unico camino) | No aplica (hay API directa) | Suscripcion nueva al plan del monto nuevo (el socio vuelve a inscribir tarjeta y paga $50 de validacion) |
| Cuotas generadas pendientes | Al cancelar la anterior, sus cargos pendientes quedan cancelados. Los del plan nuevo en meses ya cobrados se eliminan manualmente antes del DELETE de la anterior. | Las cuotas no cobradas se corrigen con `PUT /invoices/{id}` (excepto las que esten `in_progress`). | No hay cuotas como objeto; el cambio de monto rige desde el proximo ciclo. |

---

## Flujo comparado

### VirtualPOS: suscripcion nueva (unico camino)

```
1. GET /v3/suscription/{anterior}           → verificar ACTIVA, guardar plan, service_id, datos del socio
2. Buscar o crear plan del monto nuevo       → GET /v3/plans / POST /v3/plan (mismo tipo, frecuencia, dia)
3. POST /v3/suscription (plan nuevo)         → sus_nueva + url_redirect; guardar en suscripcion_cambios
4. Link seguro al socio (caso CAMBIO_MONTO)  → url_redirect de sus_nueva
5. Confirmacion: callback / return_url       → GET /v3/suscription/{nueva} → ACTIVA
6. Eliminar cargos duplicados                → para cada cargo PENDIENTE de sus_nueva en un mes ya cubierto
                                               por la anterior (pagado o procesando) → DELETE /v3/charge/{id}
7. Cancelar la anterior                      → DELETE /v3/suscription/{anterior}
```

**Regla de vigencia:** la nueva rige desde la proxima cuota no cobrada por la anterior. Si VirtualPOS programa un cargo en el mes actual y ya fue pagado, se elimina el de la nueva antes de cancelar la anterior.

**Riesgo:** si la nueva no se activa en 30 dias, queda `FINALIZADA` y el cambio falla; la anterior sigue activa. El cambio no tiene efecto sin reinscripcion de tarjeta.

---

### Toku: edicion directa por API

```
1. GET /subscriptions/{sub}                  → verificar is_recurring ACTIVE o PAUSED, guardar recurring.amount
2. PUT /subscriptions/{sub} {amount: nuevo}  → verificar recurring.amount == nuevo en la respuesta
3. GET /invoices?…&in_progress=true          → guardar IDs de cuotas en cobro (intocables)
4. GET /invoices?…&in_progress=false         → cola de cuotas sin cobro en curso con monto distinto
5. PUT /invoices/{in} {amount: nuevo}        → para cada cuota de la cola (sin releer el detalle)
6. Verificar: GET /invoices?…&in_progress=false → todas las cuotas pendientes tienen el monto nuevo
```

**Regla de vigencia:** el monto nuevo rige desde la proxima cuota no cobrada (`due_date` mas proximo de las corregidas). Las cuotas `in_progress` se cobran con el monto anterior; el nuevo aplica desde la siguiente.

**Importante:** `in_progress` es fiable solo en el listado (`GET /invoices`), no en el detalle individual de la cuota.

---

### Payku: portal (normal) o suscripcion nueva (alternativa)

#### Camino A: portal de Payku

```
1. GET /api/suclient/{cl}                    → verificar active, guardar subcriptions.amount
2. Tarea para operaciones en el backoffice   → "Cambiar monto de su... de $A a $B antes del proximo cobro"
3. Operaciones cambia en el portal de Payku
4. GET /api/suclient/{cl}                    → verificar subcriptions.amount == nuevo
5. Confirmar con el primer cobro             → paid[].amount_paid en V3
```

#### Camino B: suscripcion nueva

```
1. GET /api/sususcription/{su}               → verificar active
2. Plan del monto nuevo (catalogo o variable)
3. POST /api/sususcription                   → su_nueva + url; guardar en suscripcion_cambios
4. Link seguro al socio (caso CAMBIO_MONTO)  → url de su_nueva
5. Confirmacion: webhook url_notify_suscription + GET /api/sususcription/{su_nueva} → active
6. Evitar doble cobro                        → plan fijo cobra "a partir del mes siguiente"; si la anterior
                                               NO cobro este mes, decidir cobro unico o aceptar mes sin cobro
7. DELETE /api/sususcription/{su_anterior}
```

---

## Diferencias criticas para la capa comun

| Aspecto | Diferencia entre canales |
|---|---|
| Reinscripcion de tarjeta | VirtualPOS **siempre** requiere que el socio reinscribe la tarjeta (suscripcion nueva). Toku no la requiere (edicion por API). Payku la requiere solo en el camino B; el camino A no la requiere. |
| Doble cobro en el mes de transicion | VirtualPOS resuelve esto eliminando los cargos pendientes duplicados antes de cancelar la anterior. Toku no tiene este problema (la cuota existente se corrige en monto). Payku camino A: depende del comportamiento del portal (Q-32). Payku camino B: el plan fijo ya define que el primer cobro es "el mes siguiente"; si la anterior no cobro este mes, hay un mes sin cobro. |
| Cuotas generadas pendientes | VirtualPOS no tiene cuotas como objeto independiente: los cargos pendientes se cancelan al eliminar la suscripcion anterior. Toku tiene cuotas concretas que se corrigen individualmente por API. Payku no tiene cuotas pendientes como objeto consulable. |
| Reversibilidad / riesgo | VirtualPOS: si la nueva no se activa, no hay efecto (la anterior sigue activa). Toku: el `PUT` de la Subscription es inmediato; si se hace un error de monto, hay que hacer otro `PUT`. Payku camino A: el cambio depende de operaciones; riesgo de que el portal no lo refleje por API (Q-32). |
| Mes sin cobro | No ocurre en VirtualPOS (hay plan y cargo desde el dia de cobro). No ocurre en Toku (la cuota ya existe o se genera normalmente). Posible en Payku camino B si la anterior no cobro el mes de transicion. |

---

## Pendientes criticos que afectan la capa comun

| Clave | Canal | Descripcion |
|---|---|---|
| T-M1 | Toku | Confirmar si cambiar `amount` de la Subscription afecta un mandato PAC con tope de monto |
| T-M2 | Toku | Confirmar si `PUT /invoices` sobre una cuota ya enviada al banco (PAC) sin `in_progress` puede generar un cobro por el monto anterior |
| Q-27 | Payku | Plan variable: no se sabe si cobra al activarse la suscripcion nueva (camino B) |
| Q-31 | Payku | Confirmar que endpoint usa el portal para cambiar el monto y si puede exponerse por API |
| Q-32 | Payku | Confirmar si el cambio en el portal aplica al ciclo en curso y se refleja en `subcriptions.amount` y V3 |

---

## Referencias por canal

- VirtualPOS: [workflows/cambiar-monto.md](../virtualpos/workflows/cambiar-monto.md)
- Toku: [workflows/cambiar-monto.md](../toku/workflows/cambiar-monto.md)
- Payku: [workflows/cambiar-monto.md](../payku/workflows/cambiar-monto.md)
