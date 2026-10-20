# Revisión de workflows Payku — WFL-PK-01

Fecha de revisión: 2026-10-15  
Rama: `feature/hito5-workflows-operacionales`  
Revisor: agente `provider-integration`

---

## Tabla resumen

| Workflow | Estado | Discrepancias principales | Acción requerida |
|---|---|---|---|
| `alta-socio.md` | ❌ No implementado | Las tablas `payku_altas`, `payku_plans_catalog` y `payku_cliente_map` no existen. No hay orquestación ni máquina de estados. | Diseñar e implementar el flujo completo; resolver Q-27 antes de producción. |
| `link-inscripcion.md` | ❌ No implementado | `affiliate_card()` existe en el cliente HTTP pero no hay tabla `card_links` ni adaptador. | Implementar el adaptador; resolver Q-09, Q-16, Q-28, Q-29. |
| `cambiar-monto.md` | ❌ No implementado | `create_subscription()` y `delete_subscription()` existen pero no hay tabla `suscripcion_cambios` ni orquestación de ninguno de los dos caminos. | Implementar ambos caminos; resolver Q-31, Q-32 antes de confirmar camino A. |
| `cancel-subscription.md` | ⚠️ Parcial | `delete_subscription()` en `write_payku.py` existe con trazabilidad `write_run`. Sin embargo, `_delete()` **no envía cabecera `Sign`** y el estado local se fija a `'cancelled'` sin hacer GET de confirmación. | Agregar `Sign` en `_delete()`; hacer GET posterior; registrar el estado real. |
| `create-customer.md` | ⚠️ Parcial | `create_client()` y `get_client()` existen. No hay tabla `payku_cliente_map` ni patrón `ensure_payku_customer`. | Implementar tabla de mapeo y la función idempotente de búsqueda/creación. |
| `create-subscription.md` | ⚠️ Parcial | `create_subscription()` existe. Sin estado `PENDIENTE_ACTIVACION`, sin handler de webhook `url_notify_suscription`, sin jobs de verificación de respaldo. | Implementar la máquina de estados y los jobs de respaldo. |
| `editar-socio.md` | ⚠️ Parcial | `update_client()` existe con `write_run`. No verifica disponibilidad del email nuevo, no compara diff antes de enviar, no actualiza `payku_cliente_map` en cambio de email. | Agregar verificación de email disponible y actualización del mapa. |
| `get-subscriptions.md` | ⚠️ Parcial | Solo usa V1 sin fechas. `list_subscriptions_v3()` existe en el cliente pero no se usa en el sync. Sin ventanas de fecha ni detección de cambio por hash. | Migrar al snapshot V3 con ventanas y hash-change detection. |
| `get-transactions.md` | ⚠️ Parcial | Solo lee transacciones embebidas en V1. `list_transactions()` y `get_conciliations()` existen en el cliente pero no se usan en el sync. Sin conciliación. | Incorporar sync de `/api/transaction` y conciliación. |
| `seguimiento-cobros.md` | ❌ No implementado | No existen las tablas `payku_cuotas_esperadas`, `payku_cycles`, `payku_charges`, `payku_settlement_lines`. `PaykuTransaction` no tiene `authorization_code`, `order` ni `payment_key`. | Diseñar modelo y sync; bloqueado por Q-06, Q-08, Q-11. |
| `suspend-subscription.md` | ❌ No implementado | El campo `status` en `PaykuSubscription` puede capturar `suspended`, pero no hay detección activa, alertas ni generación de link de tarjeta. | Implementar detección en el barrido diario y comunicación al socio. |
| `sync-payku.md` | ⚠️ Parcial | No usa V3 ni ventanas de fecha. No sincroniza `/api/transaction` ni conciliación. Sin `payload_hash` ni detección de cambios. La firma tiene `&` final en params vacíos (Q-01 no validada). | Migrar a la estrategia de snapshot V3 + webhooks + barrido transaccional. |
| `update-card.md` | ❌ No implementado | `affiliate_card()` y `delete_subscription_card()` existen en el cliente pero sin orquestación, ni rastreo de estado, ni comparación de tarjetas. | Implementar flujo completo; validar Q-09 antes de habilitar eliminación de tarjeta. |

---

## Hallazgos por workflow

### 1. `alta-socio.md`

Estado: **No implementado**

El workflow describe un flujo de 8 pasos con máquina de estados completa. El cliente HTTP tiene los métodos individuales necesarios (`create_client`, `create_subscription`, `create_transaction`, `affiliate_card`) pero no existe ninguna orquestación.

Tablas requeridas ausentes: `payku_altas`, `payku_plans_catalog`, `payku_cliente_map`. Sin estas tablas no se puede persistir el estado del alta, el catálogo de planes fijos/variable, ni el mapeo persona-cliente.

El flujo requiere un mecanismo de lock por email (advisory lock o SETNX) para evitar altas dobles; no está implementado.

El paso 7 (primer aporte vía `POST /api/transaction`) requiere que el plan variable no cobre al activarse. Esto es Q-27, bloqueante crítico.

Preguntas abiertas que afectan este workflow: Q-27 (bloqueante), Q-07, Q-16, Q-18, Q-28, Q-33.

**Riesgo operativo:** Sin antidoble cobro, un socio podría quedar con dos suscripciones activas y pagar el doble mensualmente.

---

### 2. `link-inscripcion.md`

Estado: **No implementado**

`PaykuClient.affiliate_card()` (POST /api/suinscriptionscards) y `delete_subscription_card()` (POST /api/suscriptionsdeletecards) existen en `app/integrations/payku/client.py`. No hay adaptador, tabla `card_links` ni tabla `payku_altas` para los casos A y B.

El workflow distingue caso A (alta en register) de caso B (socio existente); ambos requieren lógica de negocio ausente.

La eliminación de la tarjeta anterior (caso B, paso opcional) está bloqueada por Q-09 (campo del body no documentado).

Preguntas abiertas que afectan este workflow: Q-09, Q-15, Q-16, Q-28, Q-29 (bloqueante para caso A si la URL expiró).

**Riesgo operativo:** Sin el link de inscripción operativo, socios con tarjeta vencida o suscripción suspendida no pueden reactivarse por flujo propio.

---

### 3. `cambiar-monto.md`

Estado: **No implementado**

Los métodos `create_subscription()` y `delete_subscription()` existen, pero no hay tabla `suscripcion_cambios` ni lógica de Camino A (portal) ni Camino B (suscripción nueva).

El Camino A (vía portal de Payku) requiere que un operador intervenga manualmente y luego el sistema verifique el cambio vía `GET /api/suclient/{cl…}`. Sin tabla de registro de cambios pendientes, este proceso no es trazable.

El Camino B crea una suscripción nueva y elimina la anterior. La guardia de seguridad (`assert cambio.suscripcion_id != cambio.suscripcion_nueva_id`) descrita en el workflow no existe en el código.

Preguntas abiertas: Q-31 (bloquea confirmar endpoint del portal), Q-32 (afecta verificación de Camino A), Q-27 (afecta Camino B con plan variable), Q-13 (estado final tras DELETE).

**Riesgo operativo:** Sin este workflow, cambiar el monto de un socio requiere intervención manual en el portal de Payku sin rastreabilidad interna.

---

### 4. `cancel-subscription.md`

Estado: **Parcial**

`write_payku.delete_subscription()` existe con trazabilidad vía `WriteRun`, guarda `request_payload`, respeta el flag `payku_writes_enabled`, y expuesto en la ruta de writes.

Discrepancias:

1. **`_delete()` no envía cabecera `Sign`**: El método `_delete` en `app/integrations/payku/client.py` no incluye el header `Sign`, mientras que el workflow indica "Sign obligatorio" para `DELETE /api/sususcription/{id}`. El comportamiento esperado es un 401 de Payku al intentar eliminar una suscripción. Este es un defecto de implementación.

2. **Estado local fijado sin confirmación**: Después del DELETE, el código escribe `status = "cancelled"` localmente sin hacer `GET /api/sususcription/{id}`. El workflow indica que el estado real puede ser `delete` o `cancel` (Q-13 pendiente de validar). El estado local puede quedar desincronizado.

3. **No verifica cobros pendientes**: El workflow recomienda revisar `transactions[]` si hay un cobro `pending`/`retry` en curso. El código no realiza esta verificación.

Preguntas abiertas: Q-13 (estado final real tras DELETE).

**Riesgo operativo:** Si `_delete()` falla por falta de `Sign`, la baja nunca se ejecuta en Payku pero el `write_run` queda en `failed`. El socio continúa siendo cobrado.

---

### 5. `create-customer.md`

Estado: **Parcial**

`PaykuClient.create_client()` y `get_client()` existen y son funcionales. No existe la función `ensure_payku_customer` ni la tabla `payku_cliente_map`. Sin el mapeo persistido:
- No se puede saber si un socio ya tiene un cliente en Payku sin consultarle directamente.
- En caso de timeout del POST, no hay guarda que evite crear un cliente duplicado.
- No se guarda `source` (`found` vs `created`), ni `environment`, ni `email_al_vincular`.

El método `get_client(identifier)` construye la URL `f"/api/suclient/{identifier}"` sin percent-encoding del `@`. La firma `build_sign` sí codifica el path con `quote(path, safe='')`, lo que produciría `%40` en la firma pero `@` en la URL. Si Payku valida la firma contra el path percent-encoded, habrá 401. Este es el impacto de Q-03.

Preguntas abiertas: Q-03 (firma del email en path), Q-10 (largo máximo), Q-18 (unicidad del email).

**Riesgo operativo:** Sin `payku_cliente_map`, cada alta requiere un GET a Payku para verificar existencia, y no hay forma de detectar duplicados históricos.

---

### 6. `create-subscription.md`

Estado: **Parcial**

`PaykuClient.create_subscription()`, `get_subscription()` y `delete_subscription()` existen. `write_payku.delete_subscription()` está expuesto con trazabilidad.

No implementado:
- Estado `CREANDO` → `PENDIENTE_ACTIVACION` → `ACTIVA` en ninguna tabla.
- No hay receptor de webhook `url_notify_suscription`.
- No hay jobs de verificación de respaldo (15 min, 1 h, 24 h).
- Ante timeout del `POST /api/sususcription`, el código no tiene el patrón "marcar VERIFICAR + buscar suscripción nueva del cliente".

Preguntas abiertas: Q-07 (amount/coupon opcionales), Q-16 (vigencia de la url).

---

### 7. `editar-socio.md`

Estado: **Parcial**

`write_payku.update_client()` existe con trazabilidad `WriteRun` y respeta `payku_writes_enabled`. El cliente HTTP `_put()` incluye la firma `Sign` sobre el body.

Discrepancias:

1. **No verifica disponibilidad del email nuevo (Paso 2)**: El código no llama `GET /api/suclient/{email_nuevo}` antes del PUT. Si el email nuevo ya pertenece a otro cliente, Payku puede rechazarlo o crear un conflicto silencioso.

2. **No compara diff antes de enviar**: El código envía todos los `changes` recibidos sin comparar con el estado actual en Payku. Podría enviar campos que ya tienen el valor correcto, generando firma y llamada innecesarias.

3. **No actualiza `payku_cliente_map`**: Si cambia el email, el código no actualiza ninguna tabla de mapeo (que tampoco existe).

4. **No hace GET de confirmación (Paso 4)**: El código hace `provider.get_client(client_id)` solo para tomar el payload `refreshed` y actualizarlo localmente, pero no compara campo a campo lo enviado vs lo recibido para detectar fallos silenciosos.

5. **No verifica Q-30 (Paso 5)**: No consulta `GET /api/sususcription/{id}` para ver si el objeto `client` embebido se actualizó.

Preguntas abiertas: Q-18 (unicidad email), Q-30 (objeto client en suscripción).

---

### 8. `get-subscriptions.md`

Estado: **Parcial**

El sync usa `list_subscriptions()` V1 (`/api/sususcription`) sin `date_init`/`date_end`. El cliente tiene `list_subscriptions_v3()` implementado pero no se invoca desde el sync.

Diferencias respecto al workflow:

- El workflow recomienda V3 (`/api/sususcriptionv3`) como endpoint principal para el barrido masivo, con `per_page=4000` y ventanas de fecha.
- El sync actual usa V1 con `per_page=100` sin fechas: devuelve solo el estado actual sin los campos de cobros `paid[]`, `logs.status[]`, `payment_cycle_day`, `try_number`.
- Sin `payload_hash`, no hay detección de cambios para disparar un `GET /api/sususcription/{id}`.
- No se obtiene `active_cards[].identifier` (solo disponible en el detalle).

Preguntas abiertas: Q-11 (sobre qué fecha filtra V3), Q-12 (per_page máximo en V1), Q-22 (monto y periodicidad del plan).

**Riesgo operativo:** Sin V3, los cobros `paid[]` y los estados de reintento no se sincronizan. El modelo `PaykuSubscription` solo refleja el estado último de la suscripción, no su historial de cobros.

---

### 9. `get-transactions.md`

Estado: **Parcial**

El sync extrae transacciones embebidas en el payload de cada suscripción V1 y las persiste en `p_transactions` vía `store_payku_resources`. Esto es el único origen de transacciones en el sync actual.

No implementado:
- `list_transactions()` (`GET /api/transaction`) existe en el cliente pero no se usa en el sync. El docstring de `payku_sync.py` lo confirma explícitamente: "No se usa el endpoint /api/transaction porque requiere filtro de fecha y hace timeout en datos históricos."
- `get_conciliations()` (`POST /api/conciliation`) existe en el cliente pero no se usa.
- El modelo `PaykuTransaction` no tiene campos `authorization_code`, `order`, `payment_key` como columnas propias; están solo en `raw_payload`.
- No hay separación estructurada entre "cobros de suscripción" y "transacciones de pago único".

Preguntas abiertas: Q-06 (¿cobros de suscripción aparecen en /api/transaction?), Q-08 (clave estable del cobro).

**Riesgo operativo:** Sin conciliación, no se sabe qué cobros fueron liquidados ni cuándo. Las métricas de saldo/depósitos son incompletas.

---

### 10. `seguimiento-cobros.md`

Estado: **No implementado**

Este es el workflow más complejo y ninguna de sus tablas de datos existe:

| Tabla del workflow | Existe en el código |
|---|---|
| `payku_cuotas_esperadas` | No |
| `payku_cycles` | No |
| `payku_charges` | No (las transacciones embebidas van a `p_transactions` con campos limitados) |
| `payku_settlement_lines` | No |

`PaykuTransaction` no tiene `authorization_code`, `order` ni `payment_key` como columnas propias.

El modelo conceptual del workflow ("cuota esperada calculada por el CRM" vs "ciclo cobrado por Payku") no existe en ningún punto del código.

La vista `v_payku_cuotas_mensuales` no existe.

Preguntas abiertas bloqueantes: Q-06 (sin esto no se sabe qué aparece en conciliación), Q-08 (sin esto no hay clave de cobro estable), Q-11 (afecta el barrido V3 necesario para poblar `payku_cycles`).

**Riesgo operativo:** Sin seguimiento de cobros, el CRM no puede detectar socios que no pagaron, ni contar reintentos, ni saber cuándo la suscripción pasó a `maximum attempt limit`.

---

### 11. `suspend-subscription.md`

Estado: **No implementado**

El campo `PaykuSubscription.status` puede persistir el valor `suspended` si llega del sync V1, pero no hay ninguna lógica activa:
- No hay detección de `suspended` en el barrido diario.
- No hay alerta operativa ni comunicación al socio.
- No hay generación del link de cambio de tarjeta al detectar una suspensión.
- No hay barrido de suscripciones en estado `SUSPENDIDA` para detectar reactivaciones.

Preguntas abiertas: Q-17 (calendario de reintentos y transición a `suspended`), Q-14 (¿el webhook avisa `suspended`?).

**Riesgo operativo:** Los socios suspendidos no son detectados ni contactados, lo que produce pérdida de aportes no recuperables.

---

### 12. `sync-payku.md`

Estado: **Parcial**

Implementado (confirmado en código):
- Sync de clientes (`/api/suclient/customers`), planes (`/api/suplan/plans`) y suscripciones V1 (`/api/sususcription`).
- Extracción de transacciones embebidas en el payload de suscripción.
- Sanitización de payloads antes de persistir (`sanitize_payload`).
- Registro de `SyncRun` con estado y conteo de registros.
- Paginación con límite de seguridad (`_MAX_PAGES = 2_000`).
- Backoff exponencial en reintentos para GET (2^attempt, hasta `payku_read_retries`).

No implementado respecto al workflow:
- No usa `GET /api/sususcriptionv3` con ventanas de fecha.
- No hace sync de `/api/transaction` (el docstring lo reconoce explícitamente).
- No hace sync de `/api/conciliation`.
- No hay `payload_hash` para detectar suscripciones que cambiaron y hacer GET de detalle.
- No hay `GET /api/suclient/{id}` por detalle cuando se necesita `active_cards[].identifier`.
- No hay `payku_customers_weekly` job.
- No hay sync de clientes sin suscripción (solo lista paginada de clientes).
- La tabla `payku_sync_run` descrita en el workflow no existe; se usa la tabla compartida `sync_runs`.

Firma en DELETE ausente: El `_delete()` no incluye el header `Sign`. Todos los workflows que usan DELETE (cancel-subscription, cambiar-monto, link-inscripcion) requerirían Sign según la documentación.

Firma en GET con params vacíos: `build_sign` produce `f"{quote(path, safe='')}&{query}"`. Con `query=""` (sin params), el payload termina en `&`. Si Payku no acepta la firma con `&` final para endpoints sin params, los GETs a `/api/suplan/plans` y similares fallarán con 401 (Q-01 no resuelta).

Firma en GET con query params: El código incluye los params en la firma para GET. Si Payku no los espera en la firma, los GETs con `date_init`/`date_end` o paginación fallarán con 401 (Q-03 no resuelta).

Preguntas abiertas: Q-01 (trailing `&`), Q-03 (params en firma), Q-11 (fecha sobre la que filtra V3), Q-19 (rate limits).

**Riesgo operativo:** Si Q-01 o Q-03 confirman que la firma actual es incorrecta, el sync completo fallará con 401 en producción. La ausencia de Sign en DELETE impide cancelar suscripciones.

---

### 13. `update-card.md`

Estado: **No implementado**

`PaykuClient.affiliate_card()` (POST /api/suinscriptionscards) y `delete_subscription_card()` (POST /api/suscriptionsdeletecards) existen en el cliente. No hay orquestación, ni estado de solicitud de cambio, ni comparación de `active_cards[].identifier` antes/después.

El workflow indica que la URL debe generarse "on demand" (al hacer clic), no por adelantado, porque su vigencia es desconocida (Q-16). El código no implementa ninguna lógica de generación on-demand.

La eliminación de la tarjeta anterior (paso 4) está bloqueada por Q-09 (el campo del body — ¿`card` o `suscription`? — no está documentado).

Preguntas abiertas: Q-09 (bloqueante para eliminar tarjeta), Q-15 ($50 al cambiar tarjeta), Q-16 (vigencia de la url).

**Riesgo operativo:** Sin este flujo, los socios no pueden actualizar su tarjeta de forma asistida. Las suscripciones suspendidas por tarjeta vencida no pueden reactivarse sin intervención manual.

---

## Preguntas Q-x que bloquean implementación

Ordenadas por impacto en la implementación prioritaria.

### Q-27 — Bloqueante para `alta-socio.md` en plan variable
Prioridad: ROJA

Si el plan variable cobra al activarse (al inscribir la tarjeta), el paso 7 del alta (primer aporte con `POST /api/transaction`) duplicaría el cobro del mes 1. Esto produce un doble cobro real al socio.

Acción: suscribir un cliente al plan variable en sandbox con `amount`, inscribir tarjeta de prueba, revisar `transactions[]` y V3 `paid[]`. Preguntar a soporte de Payku.

Workflows afectados: `alta-socio.md` (bloqueante en producción), `cambiar-monto.md` (Camino B con plan variable).

---

### Q-06 — Bloqueante para `seguimiento-cobros.md` y conciliación
Prioridad: ROJA

¿Los cobros de suscripción aparecen en `GET /api/transaction`? ¿Con qué `payment_key`/`order`? Sin saberlo, no se puede conectar cobros de suscripción con conciliación, ni saber si sumar transacciones de ambos endpoints duplica registros.

Acción: tras un cobro de suscripción en sandbox, buscarlo en `/api/transaction` y en `POST /api/conciliation`.

Workflows afectados: `seguimiento-cobros.md`, `get-transactions.md`, `sync-payku.md`.

---

### Q-08 — Bloqueante para `seguimiento-cobros.md`
Prioridad: ROJA

¿`paid[].transactions[]` trae el número de transacción? ¿`paid_number` y `try_number` se repiten entre ciclos? Sin una clave estable, no se puede hacer upsert idempotente de cobros ni enlazar ciclos con transacciones de detalle.

Acción: observar V3 después de varios cobros y reintentos en sandbox.

Workflows afectados: `seguimiento-cobros.md`, `sync-payku.md` (sección 3.4 claves de cobro).

---

### Q-11 — Bloqueante para el diseño del sync V3
Prioridad: ROJA

¿Sobre qué fecha filtran `date_init`/`date_end` en V3 (creación, `start`, último cobro)? Sin saberlo no se puede garantizar que una carga inicial completa capture todas las suscripciones históricas.

Acción: crear suscripciones en sandbox en fechas distintas y consultar ventanas que las incluyan o excluyan.

Workflows afectados: `sync-payku.md` (carga inicial y barrido diario), `get-subscriptions.md`, `seguimiento-cobros.md`.

---

### Q-29 — Bloqueante para `link-inscripcion.md` caso A
Prioridad: NARANJA

¿`POST /api/suinscriptionscards` genera una URL nueva para una suscripción en `register`? Si no, la única forma de renovar el link de una alta abandonada es borrar la suscripción y crear una nueva, con los riesgos de doble cobro asociados.

Acción: carpeta Postman `01 · Link de inscripción › A · Alta pendiente › LA-2`.

Workflows afectados: `link-inscripcion.md`, `alta-socio.md`.

---

### Q-01 — Afecta toda la autenticación
Prioridad: NARANJA

¿La cadena firmada lleva `&` final cuando no hay params? El `build_sign` actual produce trailing `&` para endpoints sin query params (ej. `/api/suplan/plans`). Si Payku no lo acepta, el sync de planes y cualquier GET sin params falla con 401.

Acción: llamar `GET /api/suplan/plans` en sandbox con y sin trailing `&` en la firma.

Workflows afectados: todos los que llaman GET sin params (`sync-payku.md`, `get-subscriptions.md`, `alta-socio.md`).

---

### Q-03 — Afecta GET con params y email en path
Prioridad: NARANJA

¿Los query params entran en la firma? ¿El email en el path se firma con `@` o `%40`? El código incluye params en la firma para GET y no percent-encoda el email en el path de la URL (aunque sí en la firma). Si hay discrepancia, todos los GETs paginados o con fechas fallarán con 401.

Acción: probar `GET /api/sususcriptionv3?date_init=…` firmando con y sin query params; probar `GET /api/suclient/{email}` con `@` y `%40`.

Workflows afectados: `sync-payku.md`, `get-subscriptions.md`, `create-customer.md`, `editar-socio.md`.

---

## Cobertura histórica — estado actual de PK-05

PK-05 refiere al problema de que Payku no permite recuperar de forma confiable cierto historial de transacciones (`PROJECT_STATE.md` — Bloqueos).

### Estado actual del sync

El sync actual (`payku_sync.py`) sincroniza transacciones exclusivamente desde el campo `transactions[]` embebido en cada suscripción del endpoint V1 (`/api/sususcription`). Esto tiene las siguientes limitaciones:

- Las transacciones de pago único (`POST /api/transaction`) no se sincronizan. Solo las embebidas en suscripciones.
- El endpoint V1 no incluye los campos `paid[]`, `payment_cycle_day`, `try_number` que ofrece V3. Los datos de cobro disponibles son los que V1 embebe en `transactions[]`.
- No hay sincronización de conciliación (`POST /api/conciliation`), por lo que no se sabe qué montos fueron depositados ni en qué fecha.
- El backfill documentado en `PROJECT_STATE.md` (`scripts/maintenance/backfill_payku_transactions.py`) reconstruye transacciones de `source_records` hacia `p_transactions` para restaurar la actividad mensual del dashboard.

### Workflows dependientes de cobertura completa de transacciones

Los siguientes workflows no pueden operar correctamente hasta que PK-05 esté resuelto o acotado:

| Workflow | Dependencia de cobertura histórica |
|---|---|
| `seguimiento-cobros.md` | Requiere el historial completo de `paid[]` desde el inicio de la cuenta. Sin V3 con ventanas de fecha validadas (Q-11), la tabla `payku_cycles` no puede poblarse históricamente. |
| `get-transactions.md` | La reconciliación por `payment_key`/`order` requiere que los cobros de suscripción aparezcan en `/api/transaction` o en conciliación (Q-06 pendiente). |
| `sync-payku.md` — carga inicial | La carga inicial (Paso 6: `/api/transaction`) queda indefinida hasta saber si hace timeout con datos históricos y si Q-06 confirma que los cobros de suscripción aparecen allí. |
| `alta-socio.md` — control diario | El control `total_suscription_active` del plan vs el conteo propio requiere que el conteo sea fiel a la realidad. Sin V3 completo, el conteo puede estar desactualizado. |

### Limitación conocida a documentar en observabilidad

Mientras PK-05 no esté resuelto, cualquier métrica de "pagos totales", "socios al día" o "churn" derivada de datos Payku tiene cobertura histórica limitada a lo embebido en el sync V1 actual. Las cifras del dashboard deben presentarse con esta limitación explícita, como ya registra `PROJECT_STATE.md`.

---

## Notas de seguridad observadas

- `safe_error_message(exc, (settings.payku_api_key, settings.payku_secret_key))` está presente en todas las rutas de error de `write_payku.py` y `payku_sync.py`. Esto protege los secretos de aparecer en mensajes de error.
- `sanitize_payload()` se aplica a todos los registros antes de persistirlos en `source_records` y antes de registrarlos en `write_run`.
- Los flags `payku_writes_enabled` se comprueban en todas las operaciones de escritura antes de llamar a la API.
- No existe receptor de webhooks Payku en el código. El webhook `urlnotify` descrito en los workflows opera sin receptor implementado.
