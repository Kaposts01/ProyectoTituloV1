# Plan de Validacion — Payku

> Creado: 2026-10-15. Tarea: VAL-PK-01.
> Fuentes: seguimiento-cobros.md, alta-socio.md, get-transactions.md, get-subscriptions.md, open-questions.md, transactions.md, subscriptions.md.

---

## Preguntas criticas ordenadas por impacto

| # | Pregunta | Impacto | Bloqueante de |
|---|---|---|---|
| Q-27 | ¿El plan variable cobra al activarse la suscripcion? | Alta duplica el cobro del mes 1 si tambien se cobra la transaccion unica | BLQ-PK-01, alta-socio |
| Q-06 | ¿Los cobros de suscripcion aparecen en conciliacion y en `GET /api/transaction`? | Seguimiento de cobros: modelo de pagos, enlace cuota → liquidacion | VAL-PK-01 |
| Q-08 | ¿Cual es la clave estable del cobro en `paid[].transactions[]`? | Trazabilidad cuota → pago; enlace `payku_cycles` ↔ `payku_charges` | PK-05 |
| Q-11 | ¿Sobre que fecha filtra `date_init=` en V3? | Cobertura historica: define desde que fecha arrancar la carga inicial | PK-05 |
| Q-29 | ¿`POST /api/suinscriptionscards` genera URL para suscripcion en `register`? | link-inscripcion caso A: recuperar un alta pendiente de activacion | WFL-PK-01 |

---

## Procedimiento de validacion por pregunta

### Q-27: ¿El plan variable cobra al activarse la suscripcion?

**Contexto.** El flujo de alta de socio (alta-socio.md) cobra el primer aporte con una transaccion unica `POST /api/transaction` (Paso 7) apenas la suscripcion queda `active`. La decision de 2026-10-12 aclara: para un plan de monto fijo, Payku cobra "a partir del mes siguiente". Esta regla no esta confirmada para el plan de **monto variable** (el unico plan al que se le envia el campo `amount` al crear la suscripcion). Si el plan variable cobra en el momento de la activacion, el socio quedaria con dos cobros del mes 1: el cobro automatico de Payku mas la transaccion unica del backend.

**Estado actual del codigo.** `alta-socio.md § 8 Riesgos de duplicidad` documenta el riesgo: "Si cobra al activarse, omitir el paso 7 para `plan_tipo = VARIABLE`". El codigo aun no tiene ese condicional; el riesgo esta pendiente de validacion antes de habilitar altas con plan variable en produccion.

**Request Postman (carpeta SP-3 del plan de validacion, o carpeta PA-5/PA-6).**

Preparacion:
1. Suscribir un cliente al plan variable en sandbox con `amount` (ejemplo `amount: "5000"`).
2. Completar la inscripcion de tarjeta aprobada.
3. Esperar 30 minutos.

```http
# Verificar si aparece un cobro en V3 ese mismo dia
GET /api/sususcriptionv3?date_init=HOY&date_end=HOY&page=1&per_page=100
Authorization: Bearer {{token_publico}}
Sign: {{firma}}

# Consultar el detalle de la suscripcion
GET /api/sususcription/{{subscription_id}}
Authorization: Bearer {{token_publico}}
Sign: {{firma}}
```

**Que observar en el response.**
- `paid[]` de V3: ¿tiene algun elemento con `payment_cycle_day` igual a hoy y `status: success`?
- `transactions[]` del detalle: ¿tiene el cobro de activacion de $50 mas algun otro cobro del monto del plan?
- Separar el cobro de activacion ($50) del posible cobro del primer mes.

**Resultados esperados.**
- Caso A (cobra al activarse): `paid[]` contiene un ciclo `success` con `amount_paid` igual al monto del plan ese mismo dia. El backend NO debe ejecutar el Paso 7 para `plan_tipo = VARIABLE`. La transaccion unica de primer aporte se omite.
- Caso B (no cobra al activarse): `paid[]` solo muestra el cobro de activacion de $50 o no muestra cobros del monto del plan. El plan variable se comporta igual que el plan fijo: cobra desde el mes siguiente. El backend ejecuta el Paso 7 normalmente para ambos tipos de plan.

**Como documentar el resultado.**
Guardar la respuesta de V3 y del detalle de la suscripcion. Anotar fecha, `subscription_id`, `amount`, `paid[]` completo y `transactions[]`. Marcar Q-27 en open-questions.md con fecha y conclusion.

**Impacto en el codigo segun el resultado.**
- Si Caso A: en `alta_socio_payku` (alta-socio.md § 5), agregar condicional: `if alta.plan_tipo == "VARIABLE": skip paso 7`. Actualizar `alta-socio.md § 7 Errores` y `§ 8 Riesgos`. Eliminar la nota "validar Q-27 antes de produccion".
- Si Caso B: remover el riesgo documentado. No se requiere condicional. Actualizar open-questions.md y alta-socio.md.

---

### Q-06: ¿Los cobros de suscripcion aparecen en conciliacion y en `GET /api/transaction`?

**Contexto.** Payku tiene dos "mundos" de transacciones (get-transactions.md § 2): cobros de suscripcion (dentro de la suscripcion como `transactions[]` o `paid[]`) y pagos unicos (`GET /api/transaction`). El seguimiento de cobros (seguimiento-cobros.md § 2) advierte: no sumar ambos mundos "hasta validarlo, para evitar contar dos veces". La conciliacion (`POST /api/conciliation`) es la fuente de los depositos netos; si los cobros de suscripcion no aparecen en ella, no se puede saber el neto depositado por cuotas recurrentes.

**Estado actual del codigo.** `payku_settlement_lines` enlaza por `order / payment_key`, pero no se sabe si los cobros de suscripcion tienen un `order` o `payment_key` en la conciliacion. El modelo de seguimiento (seguimiento-cobros.md § 4 PASO 4) dice "Enlazar por order / payment_key (⚠️ Q-06)".

**Request Postman (carpeta SP-3 y SP-4).**

Preparacion: necesitar al menos un cobro de suscripcion completado (`status: success`) y haber esperado suficiente tiempo para que aparezca en conciliacion (puede ser T+1 o T+2 dias).

```http
# SP-3: buscar el cobro de suscripcion en /api/transaction
GET /api/transaction?date_init=FECHA_COBRO&date_end=FECHA_COBRO&success=true&page=1&per_page=100
Authorization: Bearer {{token_publico}}

# Buscar por numero de transaccion conocido de la suscripcion
GET /api/transaction/{{transaction_number}}
Authorization: Bearer {{token_publico}}

# SP-4: conciliacion del periodo
POST /api/conciliation
Authorization: Bearer {{token_publico}}
Content-Type: application/json

{
  "date_init": "FECHA_COBRO",
  "date_end": "FECHA_COBRO_PLUS_3DIAS"
}
```

**Que observar en el response.**
- En `GET /api/transaction`: ¿aparece el numero de transaccion de la suscripcion? ¿Con que `order`?
- En `POST /api/conciliation`: ¿aparece el cobro de suscripcion? ¿Con que `payment_key` u `order`? ¿Coincide con algun valor conocido del cobro?

**Resultados esperados.**
- Caso A (aparece en ambos): los cobros de suscripcion tienen un `order` o `payment_key` que aparece en `/api/transaction` y en `/api/conciliation`. El modelo de seguimiento puede unificar la fuente de liquidaciones. Documentar el campo de enlace exacto.
- Caso B (no aparece en `/api/transaction`): los cobros de suscripcion son un mundo separado. El neto liquidado se toma de la conciliacion si aparece ahi; si no, preguntar a Payku sobre otro endpoint.
- Caso C (no aparece en conciliacion): los depositos de cuotas recurrentes no son trazables por API. Requiere consultar con soporte de Payku.

**Como documentar el resultado.**
Guardar los responses de SP-3 y SP-4. Anotar si los `order` o `payment_key` de los cobros de suscripcion coinciden con los de la conciliacion. Marcar Q-06 en open-questions.md.

**Impacto en el codigo segun el resultado.**
- Si Caso A: actualizar `seguimiento-cobros.md § 4 PASO 4` con la clave de enlace exacta. Agregar logica en el ETL para cruzar `payku_charges.order` con `payku_settlement_lines.order`.
- Si Caso B o C: actualizar el modelo de seguimiento para indicar que la trazabilidad de neto de cuotas no esta disponible por API. Escalar a Payku (Q-06 esta marcada como pregunta para soporte).

---

### Q-08: ¿Cual es la clave estable del cobro en `paid[].transactions[]`?

**Contexto.** La tabla `payku_cycles` (desde V3) y `payku_charges` (desde detalle/V1/callback) se enlazan hoy por `(subscription_id, fecha, monto)` segun seguimiento-cobros.md § 4 PASO 2, pero ese enlace es fragil: si dos cobros del mismo mes tienen el mismo monto, el cruce es ambiguo. La V3 de Payku tiene un campo `paid[].transactions[]` cuya estructura no esta documentada (Q-08). Si ese campo trae el numero de transaccion, seria la clave directa para enlazar ciclo ↔ cobro.

Ademas, no esta claro si `paid_number` y `try_number` son unicos dentro de una suscripcion (para usarlos como clave compuesta).

**Estado actual del codigo.** `seguimiento-cobros.md § 6` muestra el comentario: "⚠️ Q-08: clave de enlace ciclo ↔ cobro no documentada; usar `transaction` (numero) como clave primaria cuando este disponible, NO solo `order`".

**Request Postman (carpeta SP-2).**

Preparacion: suscripcion con al menos un ciclo `success` y al menos un reintento documentado (para verificar si `try_number` sube con el mismo `paid_number`).

```http
# V3 con cobros completados
GET /api/sususcriptionv3?date_init=FECHA_INICIO&date_end=HOY&page=1&per_page=100
Authorization: Bearer {{token_publico}}
Sign: {{firma}}

# Detalle de la suscripcion para ver transactions[]
GET /api/sususcription/{{subscription_id}}
Authorization: Bearer {{token_publico}}
Sign: {{firma}}
```

**Que observar en el response.**
- En V3, bajo `paid[]`, buscar si existe `transactions[]` como subcampo de cada elemento del ciclo.
- Si existe, ver que campos tiene: ¿`transaction` (numero)? ¿`authorization_code`? ¿`order`?
- Comparar `paid[i].payment_cycle_day` y `paid[i].try_number` con `transactions[].created_at` y `transactions[].transaction`.
- Verificar si `paid_number` es unico por ciclo o se repite en reintentos.

**Resultados esperados.**
- Caso A (`paid[].transactions[]` trae el numero de transaccion): la clave de enlace es `paid[i].transactions[j].transaction`. El cruce `payku_cycles` ↔ `payku_charges` es directo y estable.
- Caso B (`paid[].transactions[]` esta vacio o no existe): el cruce sigue siendo `(subscription_id, fecha, monto)` con riesgo de ambiguedad. Documentar limitacion.
- Caso C (`paid[].transactions[]` existe pero sin numero de transaccion): documentar los campos disponibles y evaluar si algun otro campo sirve como clave estable.

**Como documentar el resultado.**
Guardar la respuesta de V3 mostrando la estructura de `paid[]` completa para al menos un ciclo con reintento. Anotar los campos presentes en `transactions[]`.

**Impacto en el codigo segun el resultado.**
- Si Caso A: actualizar el modelo de tablas en seguimiento-cobros.md § 7 para usar `paid[].transactions[].transaction` como FK en `payku_cycles`. Eliminar el enlace por `(fecha, monto)`.
- Si Caso B o C: documentar la limitacion en seguimiento-cobros.md y en el ETL. Agregar alerta cuando dos cobros del mismo mes tienen el mismo monto (posible ambiguedad).

---

### Q-11: ¿Sobre que fecha filtra `date_init=` en V3?

**Contexto.** El endpoint `GET /api/sususcriptionv3` acepta `date_init` y `date_end`, pero la documentacion no especifica sobre que fecha filtra: ¿fecha de creacion de la suscripcion, `start` del primer cobro, o fecha del ultimo cobro? Esto define como construir las ventanas para la carga inicial historica. Si filtra por fecha de creacion, una suscripcion creada en 2020 solo aparece si la ventana incluye 2020. Si filtra por fecha del ultimo cobro, la misma suscripcion apareceria en la ventana actual.

La nota en get-subscriptions.md § 9 advierte: "No sabemos sobre que fecha filtra el rango (Q-11). Hasta validarlo, para 'todas las suscripciones vigentes' usa un rango desde el inicio de la cuenta hasta hoy, en ventanas."

**Estado actual del codigo.** La sincronizacion usa ventanas desde el inicio de la cuenta para evitar perder suscripciones antiguas, lo cual es costoso en tiempo de llamadas. Si se confirma que filtra por fecha de cobro, se podria usar una ventana mas corta (ultimos 60 dias) para la operacion diaria.

**Request Postman (carpeta SP-1, variante de fechas).**

Preparacion:
- Necesitar una suscripcion creada hace mas de 30 dias que haya tenido cobros recientes.
- Conocer su `subscription_id` y su fecha de creacion.

```http
# Ventana 1: solo incluye la fecha de creacion de la suscripcion
GET /api/sususcriptionv3?date_init=FECHA_CREACION&date_end=FECHA_CREACION_PLUS_1&page=1&per_page=100
Authorization: Bearer {{token_publico}}
Sign: {{firma}}

# Ventana 2: solo incluye la fecha del cobro mas reciente
GET /api/sususcriptionv3?date_init=FECHA_ULTIMO_COBRO&date_end=HOY&page=1&per_page=100
Authorization: Bearer {{token_publico}}
Sign: {{firma}}

# Ventana 3: no incluye ninguna de las dos fechas (periodo intermedio sin eventos)
GET /api/sususcriptionv3?date_init=FECHA_SIN_EVENTOS&date_end=FECHA_SIN_EVENTOS_PLUS_5&page=1&per_page=100
Authorization: Bearer {{token_publico}}
Sign: {{firma}}
```

**Que observar en el response.**
- ¿Aparece la suscripcion conocida en cada una de las tres ventanas?
- Comparar el campo de fecha en cada elemento de la respuesta (`start`, `created_at` u otro) con las ventanas.

**Resultados esperados.**
- Caso A (filtra por fecha de creacion): la suscripcion solo aparece en la Ventana 1. La carga inicial debe usar ventanas que cubran toda la historia desde el inicio de la cuenta.
- Caso B (filtra por fecha del ultimo cobro): la suscripcion aparece en la Ventana 2. La operacion diaria puede usar una ventana de 60 dias y capturar todas las suscripciones con cobros recientes. Suscripciones sin cobros recientes (sin actividad) se capturan con una pasada mensual amplia.
- Caso C (filtra por `start` u otra fecha): documentar el campo exacto y ajustar la estrategia de ventanas.

**Como documentar el resultado.**
Guardar las tres responses y anotar en que ventanas aparece la suscripcion de prueba. Anotar el nombre del campo de fecha que determina la inclusion.

**Impacto en el codigo segun el resultado.**
- Si Caso A: mantener la estrategia actual de ventanas desde el inicio de la cuenta para la carga historica. Para la operacion diaria, el job puede usar ventanas mas cortas solo si se confirma que no hay suscripciones con cobros recientes creadas hace mucho tiempo sin aparecen en la ventana reciente (es decir, Caso A implica que si no incluyes la fecha de creacion, no la ves). Actualizar `sync-payku.md` con la estrategia definitiva.
- Si Caso B o C: reducir el costo de llamadas del job diario. Actualizar `sync-payku.md` y `get-subscriptions.md § 9`.

---

### Q-29: ¿`POST /api/suinscriptionscards` genera URL para suscripcion en `register`?

**Contexto.** El flujo de alta de socio (alta-socio.md § 2 PASO 6) maneja el caso de una suscripcion que sigue en `register` despues de 7 dias: se puede intentar enviar al socio la misma URL original (si aun esta vigente) o crear una nueva con `DELETE` + alta nueva. El endpoint `POST /api/suinscriptionscards` existe para el flujo de cambio de tarjeta (suscripciones `active` o `suspended`), pero no esta claro si tambien funciona para suscripciones aun en `register` (alta pendiente de activacion). Si funciona, permite generar una nueva URL de activacion sin tener que borrar y recrear la suscripcion.

**Estado actual del codigo.** `alta-socio.md § 7 Errores` para el PASO 6 dice: "Sigue `register` > 7 dias → Recordatorio con la misma `url` (⚠️ vigencia Q-16) o `DELETE` y alta nueva". No hay logica para `POST /api/suinscriptionscards` en el caso A del alta pendiente, solo en el flujo de cambio de tarjeta.

**Request Postman (carpeta SP-3 del link de inscripcion, subcarpeta A).**

Preparacion:
- Tener una suscripcion en estado `register` (alta no completada).
- Anotar la `url` original devuelta por `POST /api/sususcription`.

```http
# LA-2: POST /api/suinscriptionscards sobre suscripcion en register
POST /api/suinscriptionscards
Authorization: Bearer {{token_publico}}
Sign: {{firma}}
Content-Type: application/json

{
  "suscription": "{{subscription_id}}"
}
```

**Que observar en el response.**
- ¿Responde HTTP 200 con una nueva `url`?
- ¿La URL original (`url` del `POST /api/sususcription`) sigue funcionando o queda invalidada?
- ¿El estado de la suscripcion cambia de `register` a algun otro valor?

**Resultados esperados.**
- Caso A (genera URL para `register`): el endpoint responde con una nueva URL de activacion para la suscripcion en `register`. Se puede enviar al socio un recordatorio de activacion sin borrar la suscripcion ni crear una nueva. Verificar si la URL original queda invalidada (abrir ambas).
- Caso B (error o URL invalida para `register`): el endpoint solo funciona para suscripciones `active` o `suspended`. Para una suscripcion en `register`, no se puede generar una URL nueva. El flujo de recuperacion debe usar la URL original (mientras sea vigente, Q-16) o `DELETE` + alta nueva.

**Como documentar el resultado.**
Guardar el response de `POST /api/suinscriptionscards` con la suscripcion en `register`. Si genera URL, probar ambas URLs (original y nueva). Marcar Q-29 en open-questions.md.

**Impacto en el codigo segun el resultado.**
- Si Caso A: en `alta_socio_payku`, el job de respaldo de las 15 min / 1 h / 24 h puede llamar a `POST /api/suinscriptionscards` para regenerar la URL y enviarla al socio por correo. Actualizar `alta-socio.md § 7 Errores` PASO 6 con el nuevo camino. Documentar si la URL original queda invalidada.
- Si Caso B: mantener la logica actual: la recuperacion de un alta en `register` > 7 dias requiere `DELETE` + alta nueva. Actualizar open-questions.md y `alta-socio.md § 7 Errores` con la conclusion.

---

## Estado actual del codigo respecto a cada pregunta

| Pregunta | Que asume el codigo hoy | Riesgo si la suposicion es incorrecta |
|---|---|---|
| Q-27 | El plan variable NO cobra al activarse (igual que el fijo) | Doble cobro del mes 1: una cuota automatica de Payku + la transaccion unica del backend. Socio afectado: cobrado dos veces en el mes de alta. |
| Q-06 | Los cobros de suscripcion son un mundo separado; no se suman con `/api/transaction`. La conciliacion puede o no tenerlos. | Si aparecen en `/api/transaction`, el ETL actual los omite. Si no aparecen en conciliacion, la trazabilidad de netos queda incompleta sin alternativa. |
| Q-08 | El enlace `payku_cycles` ↔ `payku_charges` se hace por `(subscription_id, fecha, monto)` | Ambiguedad si dos cobros del mismo mes tienen el mismo monto (reintento exitoso vs. cobro del ciclo siguiente). Datos incorrectos en `v_payku_cuotas_mensuales`. |
| Q-11 | El rango `date_init`/`date_end` de V3 filtra sobre alguna fecha de la suscripcion; se usan ventanas desde el inicio de la cuenta para no perder ninguna | La carga inicial es costosa en llamadas. Si el filtro no es sobre fecha de creacion, se podrian usar ventanas mas cortas y aun capturar suscripciones con actividad reciente. |
| Q-29 | `POST /api/suinscriptionscards` no se usa para altas en `register`; solo para `active`/`suspended` | Si funciona para `register`, hay una oportunidad de recuperacion de altas abandonadas sin borrar y recrear la suscripcion. No usar ese camino implica mas pasos (DELETE + alta nueva) y perder el `subscription_id` original. |

---

## Que actualizar despues de validar

| Pregunta | Archivos a actualizar |
|---|---|
| Q-27 | `docs/integrations/payku/workflows/alta-socio.md` § 8; conector de alta-socio si se agrega condicional. `docs/integrations/payku/resources/open-questions.md` Q-27. |
| Q-06 | `docs/integrations/payku/workflows/seguimiento-cobros.md` § 4 PASO 4; `docs/integrations/payku/resources/open-questions.md` Q-06; ETL de conciliacion. |
| Q-08 | `docs/integrations/payku/workflows/seguimiento-cobros.md` § 7; modelo de tablas `payku_cycles`; ETL de enlace ciclo ↔ cobro. `docs/integrations/payku/resources/open-questions.md` Q-08. |
| Q-11 | `docs/integrations/payku/workflows/sync-payku.md`; `docs/integrations/payku/workflows/get-subscriptions.md` § 9. `docs/integrations/payku/resources/open-questions.md` Q-11. |
| Q-29 | `docs/integrations/payku/workflows/alta-socio.md` § 7 PASO 6; `docs/integrations/payku/workflows/link-inscripcion.md` (caso A). `docs/integrations/payku/resources/open-questions.md` Q-29. |
| Todas | `docs/integrations/payku/resources/open-questions.md`: marcar cada pregunta como resuelta con fecha y evidencia. |
