# Plan de Validacion en Sandbox — VirtualPOS

> Creado: 2026-10-15. Tarea: VAL-VP-01.
> Fuentes: seguimiento-cobros.md, exportar-objetos-completos.md, charges.md, payments.md, subscriptions.md, sandbox.md.

---

## Resumen de preguntas abiertas

| # | Pregunta | Impacto | Carpeta Postman |
|---|---|---|---|
| V-1 | ¿`GET /v3/suscriptions` trae `charge_program[]` completo de cada suscripcion (como el ejemplo oficial)? | VP-28, seguimiento masivo | 05 · Seguimiento de cobros |
| V-2 | ¿`GET /v3/charge/{id}` de cargo pagado trae `payment.order.uuid`? | VP-28 (critico) | 05 · Seguimiento |
| V-3 | ¿`GET /v3/payments` incluye transacciones recurrentes PAT? | seguimiento completo | 05 · Seguimiento |
| V-4 | ¿Un reintento reutiliza el mismo Payment o crea uno nuevo? | REC-02, seguimiento | 05 · Seguimiento |

---

## Procedimiento de validacion por pregunta

### V-1: ¿El listado `GET /v3/suscriptions` trae `charge_program[]` completo?

**Contexto.** El job diario de seguimiento depende de obtener todas las cuotas en `~50` llamadas recorriendo el listado de suscripciones activas. Si `charge_program[]` del listado viene truncado o vacio, el job necesitaria un `GET /v3/suscription/{id}` adicional por cada suscripcion, multiplicando las llamadas por el numero de socios activos.

**Prerequisito.** Una suscripcion en sandbox con al menos 3 cargos en `charge_program[]` (uno `pagado`, uno `pendiente`, uno `rechazado`). Usar tarjeta VISA `4051 8856 0044 6623` para crear la suscripcion. Dejar pasar suficiente tiempo para que VirtualPOS intente al menos el primer cargo.

**Request Postman (SC-1).**

```http
GET {{base_url}}/v3/suscriptions?status=ACTIVA&limit=100&page=1
Authorization: {{api_key}}
Signature: {{jwt_token}}
```

**Que campo del response valida la pregunta.**
- `suscriptions[0].charge_program[]` — observar si esta presente y cuantos elementos tiene.
- Comparar el conteo con `GET /v3/suscription/{id}/charges` de la misma suscripcion (request SC-2).

**Resultados esperados.**
- Caso A (confirmado): `charge_program[]` en el listado tiene todos los cargos, identicos a los que devuelve `/charges`. El job masivo no necesita llamadas adicionales.
- Caso B (problema): `charge_program[]` viene vacio o truncado. El job debe hacer un `GET /v3/suscription/{id}` adicional por cada suscripcion activa para obtener los cargos.

**Como documentar el resultado.**
Anotar en este documento bajo "Resultados observados V-1" la cantidad de elementos en `charge_program[]` del listado vs. los devueltos por `/charges`, incluyendo el `suscription_id` de prueba, la fecha y la version del ejemplo.

**Impacto en el codigo segun el resultado.**
- Si Caso A: la logica de `PASO 1` del job diario (seguimiento-cobros.md § 3) queda validada tal como esta diseñada.
- Si Caso B: agregar un paso entre PASO 1 y PASO 2: por cada suscripcion, `GET /v3/suscription/{id}` y usar su `charge_program[]`. Actualizar `vpos_charges` con ese resultado. Esto multiplica las llamadas pero es la unica alternativa dado que no existe endpoint global de cargos.

---

### V-2: ¿`GET /v3/charge/{id}` de cargo pagado trae `payment.order.uuid`?

**Contexto.** El objeto Charge documentado oficialmente muestra un ejemplo con `charge.payment.order.uuid`, pero el endpoint `GET /v3/charge/{id}` devuelve en su ejemplo solo los campos basicos sin el objeto `payment`. Si el endpoint no incluye `payment`, el puente cuota → transaccion no es posible por este camino y la cuadratura (`vpos_charges.payment_uuid IS NULL`) fallara para todas las cuotas pagadas.

**Prerequisito.** Un cargo en estado `pagado` en sandbox. Para lograrlo:
1. Crear una suscripcion con tarjeta VISA aprobada.
2. Esperar a que VirtualPOS intente el primer cargo (o usar `POST /v3/charge/online` sobre la suscripcion si el plan es `MONTO_VARIABLE`).
3. Confirmar que el cargo quedo `pagado` con `GET /v3/suscription/{id}` revisando `charge_program[].status`.

**Request Postman (SC-3).**

```http
GET {{base_url}}/v3/charge/{{charge_id}}
Authorization: {{api_key}}
Signature: {{jwt_token}}
```

donde `charge_id` es un `cid_...` con estado `pagado`.

**Que campo del response valida la pregunta.**
Presencia (o ausencia) del objeto `charge.payment` y del campo `charge.payment.order.uuid` en el body de la respuesta HTTP 200.

**Resultados esperados.**
- Caso A (confirmado): `charge.payment.order.uuid` presente. El PASO 3 del job diario funciona como esta disenado: al detectar un cargo que cambio a `pagado`, `GET /v3/charge/{id}` entrega el uuid del Payment y se persiste en `vpos_charges.payment_uuid`.
- Caso B (problema): `charge.payment` no aparece o `order.uuid` es nulo. La cuadratura "cuota pagada sin transaccion" siempre dispara. El unico camino alternativo es usar `GET /v3/deposit/{fecha}/sales` que trae `suscription_charge.cid` ↔ `uuid`, pero esto solo funciona despues del abono (dias mas tarde) y no el mismo dia del cobro.

**Como documentar el resultado.**
Guardar el response completo del endpoint en el scratchpad de la sesion Postman. Anotar en "Resultados observados V-2" si `payment` esta presente, si `order.uuid` tiene valor no nulo y el `charge_id` utilizado.

**Impacto en el codigo segun el resultado.**
- Si Caso A: implementar PASO 3 directamente.
- Si Caso B: el codigo de cuadratura debe tolerar `payment_uuid IS NULL` sin alertar de inmediato, y usar el abono diario como unica fuente del enlace. Actualizar `seguimiento-cobros.md § 5` indicando que la cuadratura se hace con T+N dias de retardo.

---

### V-3: ¿`GET /v3/payments` incluye transacciones recurrentes PAT?

**Contexto.** El listado masivo de Payments se usa en el PASO 4 del job diario para obtener las transacciones de un periodo. Si los cobros automaticos PAT (Pago Automatico con Tarjeta, que genera VirtualPOS al cobrar una cuota de suscripcion) no aparecen en ese listado, la tabla `vpos_payments` solo tendria pagos spot y habria que obtener las transacciones de suscripcion exclusivamente via el puente `charge.payment.order.uuid` (V-2).

El endpoint `/v3/payment/{uuid}/logs` muestra en su ejemplo una descripcion "Orden de pago creada desde Pago Automatico con tarjeta de credito PAT.", lo que sugiere que el Payment si existe para cobros recurrentes. Lo que no esta claro es si aparece en el listado de `/v3/payments` y con que `merchant_internal_code`.

**Prerequisito.** Un cobro recurrente completado en sandbox (cargo `pagado` de una suscripcion activa). El `payment.order.uuid` obtenido en V-2 sirve como referencia.

**Request Postman (SC-6).**

```http
GET {{base_url}}/v3/payments?authorization_from={{auth_desde}}&authorization_to={{auth_hasta}}&limit=100&page=1
Authorization: {{api_key}}
Signature: {{jwt_token}}
```

donde `auth_desde` y `auth_hasta` cubren la fecha en que se autorizo el cargo recurrente de prueba.

**Que campo del response valida la pregunta.**
- ¿Aparece en `payments` (objeto o arreglo) el `order.uuid` que se obtuvo en V-2?
- Si aparece, ¿que valor tiene `order.merchant_internal_code` y `order.merchant_internal_channel`?
- ¿Tiene `order.payment_method: "PAT"` u otro campo que lo distinga de un pago spot?

**Resultados esperados.**
- Caso A (confirmado): el Payment del cobro recurrente aparece en `/v3/payments` con el uuid conocido. El PASO 4 del job masivo cubre tanto pagos spot como cuotas recurrentes. `merchant_internal_code` puede ser el `charge_id` o algun codigo de VirtualPOS; documentarlo.
- Caso B (problema): el Payment del cobro recurrente no aparece en el listado. El listado solo trae pagos spot. Las transacciones de cuotas deben obtenerse uno a uno via `GET /v3/payment/{uuid}` usando los uuid del puente V-2.

**Como documentar el resultado.**
Anotar si el uuid de V-2 aparece en el listado, el valor de `merchant_internal_code` y `payment_method` si estuviera presente.

**Impacto en el codigo segun el resultado.**
- Si Caso A: el PASO 4 del job diario es suficiente para cubrir todas las transacciones. No se requiere logica diferenciada para pagos recurrentes vs. spot.
- Si Caso B: separar en el ETL el upsert de `vpos_payments` segun origen: los de spot llegan del listado masivo y los de cuotas recurrentes llegan del puente `charge.payment.order.uuid`. Documentar en `sync-virtualpos.md`.

---

### V-4: ¿Un reintento de cargo rechazado reutiliza el mismo Payment o crea uno nuevo?

**Contexto.** El flujo de reintento de cobro rechazado usa `GET /v3/charge/{charge_id}/retry`. Segun la documentacion oficial, VirtualPOS hace un intento diario durante 3 dias seguidos. La pregunta es si cada reintento crea un nuevo Payment con un `order.uuid` distinto, o si los intentos adicionales van acumulandose en el mismo Payment (visible en `/attempts`).

Esto afecta a REC-02 (flujo de reintento) y al seguimiento: si se crea un nuevo Payment, `vpos_charges.payment_uuid` debe actualizarse al nuevo uuid. Si es el mismo Payment con mas intentos, el uuid no cambia y solo crece `authorization_attempts_cards[]`.

**Prerequisito.**
1. Crear una suscripcion con tarjeta MASTERCARD `5186 0595 5959 0568` (rechazada en sandbox).
2. El cargo quedara `rechazado` tras el primer intento.
3. Obtener el `charge_id` del cargo rechazado y el `payment.order.uuid` inicial (V-2 aplicado al cargo rechazado).
4. Llamar a `GET /v3/charge/{charge_id}/retry` para reintentar.
5. Esperar unos minutos y consultar el cargo de nuevo.

**Request Postman (SC-3 aplicado al cargo rechazado, luego retry).**

```http
# Primer GET para obtener payment.order.uuid inicial
GET {{base_url}}/v3/charge/{{charge_id}}

# Reintento
GET {{base_url}}/v3/charge/{{charge_id}}/retry

# Segundo GET tras el reintento
GET {{base_url}}/v3/charge/{{charge_id}}
```

**Que campo del response valida la pregunta.**
Comparar `charge.payment.order.uuid` antes y despues del reintento. Si el uuid cambia → nuevo Payment. Si es el mismo → mismos Payment con mas intentos.

**Resultados esperados.**
- Caso A (mismo Payment): `charge.payment.order.uuid` es identico antes y despues. `GET /v3/payment/{uuid}/attempts` muestra mas entradas en `authorization_attempts_cards[]`. El codigo no necesita actualizar `vpos_charges.payment_uuid` al reintentar; solo recarga los intentos.
- Caso B (nuevo Payment): el `order.uuid` cambia tras el reintento. El codigo debe actualizar `vpos_charges.payment_uuid` al nuevo uuid cada vez que se detecte un reintento exitoso o fallido, y ademas hacer upsert del nuevo Payment en `vpos_payments`.

**Como documentar el resultado.**
Guardar ambos uuids (antes y despues del reintento) y el conteo de `authorization_attempts_cards[]` antes y despues.

**Impacto en el codigo segun el resultado.**
- Si Caso A: en el PASO 3 del job diario, al detectar un cargo que paso de `rechazado` a `rechazado` nuevamente (sin cambiar a `pagado`), no actualizar `payment_uuid`. Solo recargar `/attempts` para el motivo del rechazo.
- Si Caso B: al detectar cualquier cambio de estado en un cargo que estaba `rechazado`, siempre releer `GET /v3/charge/{id}` y actualizar `payment_uuid` en `vpos_charges`. Agregar una fila en `vpos_charge_retries` con el nuevo uuid. Documentar en `sync-virtualpos.md § retries`.

---

## Instrucciones de preparacion de sandbox

**Acceso.** Base URL: `https://api.virtualpos-sandbox.com`. Portal de llaves: `https://comercios.virtualpos-sandbox.com` → Perfil > Configuracion de cuenta > Integracion. Checkout: `https://pay.virtualpos-sandbox.com/...`.

**Datos de tarjeta.**

| Resultado | Tipo | Numero | CVV |
|---|---|---|---|
| Aprobada (V-1, V-2, V-3) | Credito VISA | `4051 8856 0044 6623` | `123` |
| Rechazada (V-4) | Credito MASTERCARD | `5186 0595 5959 0568` | `123` |

Simulador de banco: RUT `11.111.111-1`, clave `123`.

**Preparacion para V-1, V-2, V-3.**
1. Crear un plan de monto fijo (o variable) en el portal de sandbox.
2. Llamar a `POST /v3/suscription` con la tarjeta VISA aprobada para crear una suscripcion activa.
3. Anotar el `suscription_id` y esperar a que el primer cargo quede `pagado`.
4. Anotar el `charge_id` del cargo pagado.

**Preparacion para V-4.**
1. Crear una suscripcion con la tarjeta MASTERCARD rechazada.
2. Confirmar que el primer cargo quedo `rechazado`.
3. Anotar el `charge_id` y el `payment.order.uuid` obtenido de `GET /v3/charge/{id}`.

**Coleccion Postman.** Carpeta `05 · Seguimiento de cobros` de `VirtualPOS API v2.postman_collection.json`. Variables de coleccion relevantes: `suscription_id`, `charge_id`, `sc_payment_uuid`, `sc_desde`, `sc_hasta`, `sc_deposit_date`.

---

## Resultados observados

> Rellenar al ejecutar las pruebas. Incluir fecha, ambiente (sandbox), response relevante resumido y conclusion.

| # | Fecha | Resultado (A/B) | Evidencia resumida | Conclusion |
|---|---|---|---|---|
| V-1 | — | — | — | Pendiente |
| V-2 | — | — | — | Pendiente |
| V-3 | — | — | — | Pendiente |
| V-4 | — | — | — | Pendiente |

---

## Que actualizar despues de validar

| Pregunta | Archivos a actualizar |
|---|---|
| V-1 (Caso B) | `ingestion/connectors/virtualpos/sync.py` o equivalente: agregar GET individual por suscripcion. `docs/integrations/virtualpos/workflows/sync-virtualpos.md` § Paso 1. |
| V-2 (Caso B) | `seguimiento-cobros.md § 5` cuadratura: indicar retardo por abono. Conector: no alertar cuota pagada sin uuid inmediatamente. |
| V-3 (Caso B) | `sync-virtualpos.md` PASO 4: separar fuente de pagos recurrentes vs. spot. Conector: no upsert de recurrentes desde listado. |
| V-4 (Caso B) | `sync-virtualpos.md` PASO 3: siempre releer `GET /v3/charge/{id}` y actualizar `payment_uuid`. Agregar logica de `vpos_charge_retries`. |
| V-1 a V-4 (cualquiera) | `docs/integrations/virtualpos/workflows/seguimiento-cobros.md` § 8 Pendientes: marcar la pregunta como resuelta con fecha y resultado. |
