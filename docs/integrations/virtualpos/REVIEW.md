# WFL-VP-01: Revisión de workflows VirtualPOS contra código existente

**Fecha:** 2026-10-15
**Rama:** feature/hito5-workflows-operacionales
**Revisor:** agente SynkmetriX (esteban.b@techo.org)

---

## Tabla resumen

| # | Workflow | Estado | Discrepancias | Acción requerida |
|---|----------|--------|---------------|-----------------|
| 1 | alta-socio.md | ⚠️ Parcial | El CRM no implementa el flujo de alta completo (formulario → lock → upsert client → plan → suscripción nueva). Solo existen operaciones atómicas separadas sin orquestación end-to-end ni antiduplicado por RUT. | Implementar orquestador de alta o documentar que cada paso se coordina externamente. |
| 2 | link-inscripcion.md | ❌ No implementado | No existe adaptador de link seguro, ni lógica de `url_redirect` persistido al crear la suscripción, ni polling de confirmación, ni `card_change_url` con reutilización. | Pendiente de un workflow de link seguro aprobado. |
| 3 | cambiar-monto.md | ❌ No implementado | No existe flujo de cambio de monto. El CRM puede crear y cancelar suscripciones por separado, pero no orquesta la secuencia crear-nueva → confirmar → eliminar-cargos-duplicados → cancelar-anterior. | Requiere diseño explícito y aprobación antes de implementar. |
| 4 | cambio-tarjeta.md | ⚠️ Parcial | Existe `create_card_change_link` (escribe en `write_runs`, llama a `PUT /v3/suscription/{id}/changecard`). Faltan: huella de tarjeta previa, persistencia de `card_change_requests`, polling de confirmación, reintentos automáticos al detectar cambio de huella, y límite de 3 links. | Completar la persistencia y el ciclo de seguimiento de cambio de tarjeta. |
| 5 | cancel-subscription.md | ✅ Implementado | `cancel_subscription` cubre DELETE, post-confirmación con `GET`, reconciliación de `source_record`, traza en `write_runs`. Falta: verificación explícita de cargos `procesando` antes de cancelar (el workflow lo exige; el código procede sin ese chequeo). | Bajo riesgo: agregar pre-chequeo de cargo en procesando como mejora defensiva. |
| 6 | charge-subscription.md | ⚠️ Parcial | `create_charge` y `cancel_charge` y `retry_charge` existen. El workflow documenta que `POST /v3/charge` es solo para `MONTO_VARIABLE` y no debe implementarse para `MONTO_FIJO`; el endpoint `POST /virtualpos/subscriptions/{id}/charges` lo expone sin restricción de tipo de plan. El flujo de cobro mensual automatizado (`MONTO_FIJO` vía `charge_program`) no existe en el CRM como job. | Restringir `create_charge` solo a planes `MONTO_VARIABLE` o documentar explícitamente su alcance. Añadir job de reconciliación mensual de cuotas. |
| 7 | create-client.md | ✅ Implementado | `create_client` y `update_client` existen con `write_runs`, sanitización, RUT normalizado, `source_record`. Falta: el E-083 del flujo de upsert (buscar por email si RUT ya existe en otro cliente) no está manejado en el servicio; si VirtualPOS devuelve E-083 la operación simplemente falla con `HTTPStatusError`. | Manejar explícitamente E-083 buscando por email antes de propagarlo como error. |
| 8 | create-subscription.md | ✅ Implementado | `create_subscription` cubre POST, encode de URLs a base64, persistencia en `source_record` y `write_runs`. Falta: no hay antiduplicado local previo a la llamada al proveedor (buscar suscripciones `SUSCRIBIENDO`/`ACTIVA` del mismo `service_id` antes de crear). | Agregar chequeo de antiduplicado en `create_subscription` o en el endpoint que lo invoca. |
| 9 | editar-socio.md | ⚠️ Parcial | `update_client` con `PUT /v3/client/{uuid}` está implementado. Faltan: verificación previa de email/RUT libre (GET /v3/clients antes del PUT), detección de desincronización con la copia en la suscripción, y auditoría de cambios (antes/después). | Agregar pre-chequeo de unicidad de email/RUT y lógica de detección de desincronización en suscripción. |
| 10 | exportar-objetos-completos.md | ⚠️ Parcial | La sincronización lee clientes, pagos, planes y suscripciones con paginación. Faltan: paginación de suscripciones por todos los estados (el código hace `list_subscriptions` sin parámetro `status`, lo que puede no devolver todos los estados), cargos obtenidos por detalle individual (`GET /v3/charge/{id}`), abonos (`GET /v3/deposit/`), pasada final de conciliación, y `export_run` con contadores. | Ampliar la sincronización para cubrir todos los estados de suscripción, detalle de cargos e integridad de la exportación. |
| 11 | gestionar-suscripcion-monto-fijo.md | ⚠️ Parcial | `cancel_charge` para omitir un mes existe. No existe flujo de pausa por X meses (listar cargos pendientes en rango y cancelarlos uno a uno con pre-verificación). El cambio de monto no está implementado (ver workflow 3). | Implementar flujo de pausa con recorrido de cargos en rango. |
| 12 | reintento-cobro-rechazado.md | ⚠️ Parcial | `retry_charge` existe con traza en `write_runs` y `ChargeRecovery`. El CRM no implementa la clasificación de motivo (CAMBIO_TARJETA vs REINTENTAR vs DIFERIR vs MANUAL), no obtiene el motivo desde `GET /v3/payment/{uuid}/attempts`, y no decide automáticamente entre reintentar y cambiar tarjeta. El endpoint de retry expone la acción sin clasificación previa. | Implementar clasificación de motivo antes del retry (lectura de `/attempts`) o documentar que la clasificación es responsabilidad del operador. |
| 13 | seguimiento-cobros.md | ⚠️ Parcial | La sincronización trae `charge_program[]` de las suscripciones activas y persiste cargos. Faltan: job de seguimiento diario con detección de cambios de estado, puente cuota→transacción vía `GET /v3/charge/{id}` → `payment.order.uuid`, sincronización incremental de pagos con ventana de fechas, integración de abonos (`GET /v3/deposit/`), cuadratura diaria, y alertas de cuotas atrasadas. Los pendientes V-1 a V-4 siguen sin validar. | Completar el job de seguimiento de cobros. |
| 14 | sync-virtualpos.md | ⚠️ Parcial | Sincronización implementada para clientes, pagos, planes y suscripciones (con `charge_program[]`). Falta paginación por estado en suscripciones, abonos/depósitos, sincronización incremental de clientes nuevos, y `sync_state` checkpoint por recurso. La paginación de clientes usa el modelo estándar en lugar del modelo específico de Client (`page * limit >= total`). | Ampliar la sincronización con abonos, todos los estados de suscripción, e incrementalidad por recurso. |
| 15 | web-checkout-payment.md | ⚠️ Parcial | `cancel_payment` existe. No existe flujo completo de Web Checkout (`POST /v3/payment/` + `POST /v3/payment/{uuid}/webcheckout`). `create_payment` no está implementado. El cliente HTTP sí expone `delete_payment`. | Implementar flujo de Web Checkout si se requiere cobro spot; actualmente es una capacidad no activada. |

---

## Detalle por workflow

### 1. alta-socio.md

**Estado:** Parcial

Las piezas individuales existen: `create_client`, `create_plan`, `create_subscription`, `cancel_subscription`. Sin embargo el flujo de alta completo documentado (lock por RUT, búsqueda de cliente, reutilización de plan existente, antiduplicado de suscripción SUSCRIBIENDO, generación de `url_redirect`, polling de respaldo) no existe como orquestador. No hay lógica de "lock por RUT" ni verificación de suscripción ACTIVA o SUSCRIBIENDO antes de crear.

**Discrepancias observadas:**
- El código no verifica si ya existe una suscripción activa para el mismo RUT antes de llamar a `POST /v3/suscription`.
- No hay manejo del `E-083` en `create_client` (si VirtualPOS retorna E-083, la función falla sin intentar buscar por email).
- `url_redirect` de la respuesta de `POST /v3/suscription` no se almacena persistentemente en ninguna tabla del CRM.

**Pendientes confirmados (V-x):** ninguno específico de este workflow; aplican V-1 a V-4 de `seguimiento-cobros.md`.

**Riesgo operativo:** moderado. Si se crea una suscripción desde el CRM sin verificar duplicados, pueden resultar dos suscripciones activas para el mismo socio y doble cobro mensual.

---

### 2. link-inscripcion.md

**Estado:** No implementado

No existe adaptador de link de inscripción. El CRM no implementa la capa común de link seguro ni la lógica que diferencia caso A (alta en SUSCRIBIENDO) de caso B (socio existente, cambio de tarjeta). El `url_redirect` no se persiste en ninguna tabla local.

**Discrepancias observadas:**
- El workflow describe que `url_redirect` debe guardarse obligatoriamente al crear la suscripción porque la API no lo devuelve después; el CRM no lo persiste.

**Riesgo operativo:** alto si se inician altas o cambios de tarjeta desde el CRM sin persistir el link.

---

### 3. cambiar-monto.md

**Estado:** No implementado

No existe ninguna función de cambio de monto. Las capacidades necesarias (crear nueva suscripción, eliminar cargos duplicados, cancelar suscripción anterior) existen como operaciones independientes, pero no hay orquestador ni estado `suscripcion_cambios`.

**Discrepancias observadas:**
- El workflow documenta explícitamente el orden: crear primero la nueva, activarla y solo entonces cancelar la anterior. Sin orquestador no hay garantía de ese orden.

**Riesgo operativo:** alto si se realiza el cambio de monto en pasos manuales sin coordinar el estado.

---

### 4. cambio-tarjeta.md

**Estado:** Parcial

El endpoint `POST /recovery/card-change-links/{subscription_id}` existe en `recovery.py` y llama correctamente a `PUT /v3/suscription/{id}/changecard`. Se registra un `WriteRun` con la operación.

**Discrepancias observadas:**
- El código no guarda la huella de la tarjeta anterior (`payment_method.bin + last4CardDigit + expiration_date + brand`) antes de emitir el link.
- No existe la tabla `card_change_requests` ni equivalente: no hay persistencia de `change_card_expiration_date`, motivo, ni estado del link.
- El response del endpoint extrae `response.get("url") or response.get("link") or response.get("card_change_url")` pero el campo real de la API es `change_card_url`: el código puede no extraer correctamente la URL.
- No hay polling diario para detectar cambio de huella.
- No hay lógica de límite de 3 links ni escalada a gestión manual.
- No se reintenta cargos rechazados automáticamente tras confirmar el cambio de huella.

**Riesgo operativo:** moderado. El link se genera pero sin trazabilidad de vigencia ni confirmación.

---

### 5. cancel-subscription.md

**Estado:** Implementado

`cancel_subscription` en `write_virtualpos.py` ejecuta `DELETE /v3/suscription/{id}`, intenta obtener el estado final con `GET`, reconcilia `source_record` y marca el `WriteRun`. El flujo está cubierto para el caso principal.

**Discrepancias observadas:**
- El workflow especifica verificar si hay un cargo `procesando` antes del DELETE y avisar si lo hay. El código procede directamente al DELETE sin ese chequeo. En el modelo `MONTO_FIJO` esto es un riesgo menor pero documentado en el workflow como `⚠️`.
- La cancelación local pone `status = "CANCELADA"` en la entidad, lo cual es correcto.

**Riesgo operativo:** bajo. El comportamiento esperado de VirtualPOS es pasar los cargos pendientes a cancelado. El caso de cargo en vuelo es un riesgo reconocido en el workflow que requiere validación en sandbox (V no listada, pero documentada).

---

### 6. charge-subscription.md

**Estado:** Parcial

`create_charge`, `cancel_charge` y `retry_charge` existen. El cliente HTTP tiene los métodos correspondientes.

**Discrepancias observadas:**
- El workflow documenta explícitamente que `POST /v3/charge` es solo para planes `MONTO_VARIABLE` y retorna `E-113` para `MONTO_FIJO`. El endpoint `POST /virtualpos/subscriptions/{subscription_id}/charges` no verifica el tipo de plan antes de llamar al proveedor, lo que puede generar un error operativo.
- No hay job automatizado de cobro mensual. Los cargos de `MONTO_FIJO` los crea VirtualPOS al activarse la suscripción; el CRM los sincroniza via `charge_program[]` pero no tiene un ciclo de reconciliación diaria de estados.
- `retry_charge` actualmente no incluye clasificación de motivo (ver workflow 12).

**Riesgo operativo:** moderado. El endpoint de creación de cargo puede ser llamado erróneamente para suscripciones `MONTO_FIJO` y generar E-113 en producción.

---

### 7. create-client.md

**Estado:** Implementado

`create_client` y `update_client` en `write_virtualpos.py` cubren los casos principales. Se normaliza RUT, se registra `write_run`, se persiste `source_record`, y se sanitizan payloads.

**Discrepancias observadas:**
- El flujo upsert del workflow especifica: si `POST /v3/client` retorna E-083, buscar por email y vincular. El código actual no maneja E-083; cualquier `HTTPStatusError` del POST se propaga directamente. El `create_client` del CRM no intenta un `GET /v3/clients?email=` en caso de E-083.
- El flujo de búsqueda previa por `social_id` antes de crear existe implícitamente via `_check_duplicate_client`, pero esta función consulta la tabla local (no VirtualPOS), lo que puede no detectar un cliente existente en VirtualPOS pero no sincronizado aún.

**Riesgo operativo:** bajo-moderado. El E-083 puede aparecer en creaciones paralelas o si el cliente existe en VirtualPOS pero no en el CRM local.

---

### 8. create-subscription.md

**Estado:** Implementado

`create_subscription` cubre el flujo principal: POST, encode de URLs a base64, persistencia en `source_record`, `write_run`. El campo `url_redirect` llega en la respuesta pero no se almacena en una tabla dedicada.

**Discrepancias observadas:**
- No existe antiduplicado previo: no se consulta si hay una suscripción SUSCRIBIENDO o ACTIVA del mismo `service_id` o RUT antes de llamar al proveedor.
- `url_redirect` de la respuesta no se persiste en ninguna tabla del CRM (solo queda en `WriteRun.response_payload`).

**Riesgo operativo:** moderado. Doble envío del formulario puede crear dos suscripciones.

---

### 9. editar-socio.md

**Estado:** Parcial

`update_client` con `PUT /v3/client/{uuid}` existe y está probado con permisos y CSRF.

**Discrepancias observadas:**
- El workflow exige verificar que el email nuevo y el RUT nuevo estén libres (`GET /v3/clients?email=` y `GET /v3/clients?social_id=`) antes del PUT. El código no hace estas verificaciones previas en VirtualPOS.
- No hay lógica de comparación con la copia del cliente dentro de la suscripción para detectar desincronización.
- No hay auditoría de cambios (tabla `socio_cambios` ni equivalente).
- El código sí normaliza el RUT si `social_id_type == "1"`.

**Riesgo operativo:** moderado. Sin pre-chequeo, el PUT puede fallar con E-083 (email/RUT ya usado por otro cliente) devolviendo un error HTTP al operador sin diagnóstico útil.

---

### 10. exportar-objetos-completos.md

**Estado:** Parcial

La sincronización existente (`sync_virtualpos`) obtiene clientes, pagos, planes y suscripciones con paginación y persiste RAW via `source_record` y tablas específicas via `channel_store`.

**Discrepancias observadas:**
- Suscripciones: `list_subscriptions` llama sin parámetro `status`, por lo que puede no devolver todos los estados (SUSCRIBIENDO, SUSCRIPCION_FALLIDA, CANCELADA, FINALIZADA). El workflow especifica recorrer explícitamente cada estado.
- Cargos: la sincronización usa `charge_program[]` embebido en la suscripción, no el endpoint de detalle `GET /v3/charge/{charge_id}`. El detalle de cargos pagados o rechazados (con `payment.order.uuid`) no se obtiene individualmente.
- Abonos/depósitos: `GET /v3/deposit/{date}` y `GET /v3/deposit/{date}/sales` no están implementados en la sincronización.
- No existe `export_run` con contadores de objetos, errores y última página procesada.
- Paginación de clientes: el código usa el mismo patrón de paginación estándar para todos los recursos; el workflow documenta que la paginación de Client usa `page * limit >= total` con `total` en raíz, no en `pagination`.

**Riesgo operativo:** moderado. La falta de abonos afecta la cuadratura y los reportes financieros. La falta de estados en suscripciones puede resultar en suscripciones terminadas que no se marcan en el CRM.

---

### 11. gestionar-suscripcion-monto-fijo.md

**Estado:** Parcial

`cancel_charge` (omitir un cobro) existe. `cancel_subscription` (baja definitiva) existe.

**Discrepancias observadas:**
- No existe flujo de pausa por X meses (listar cargos pendientes en un rango de fechas y cancelarlos uno a uno con pre-verificación de `status == pendiente`).
- El cambio de monto, frecuencia o día de cobro no está implementado (ver workflow 3).
- No existe auditoría en `vpos_subscription_changes` (tabla sugerida en el workflow).

**Riesgo operativo:** moderado. La pausa manual desde el portal de VirtualPOS puede ejecutarse fuera del CRM sin traza local.

---

### 12. reintento-cobro-rechazado.md

**Estado:** Parcial

`retry_charge` existe en `write_virtualpos.py` con `write_runs` y `ChargeRecovery`. El endpoint `POST /virtualpos/charges/{charge_id}/retry` está expuesto y protegido con permisos y CSRF.

**Discrepancias observadas:**
- El workflow exige clasificar el motivo antes de llamar a `/retry`: obtener `charge.payment.order.uuid`, consultar `GET /v3/payment/{uuid}/attempts`, clasificar en CAMBIO_TARJETA/REINTENTAR/DIFERIR/MANUAL, y solo entonces actuar. El código actual llama a `/retry` directamente sin clasificación.
- El cliente HTTP no expone `GET /v3/payment/{uuid}/attempts`: falta el método `get_payment_attempts` en `VirtualPOSClient`.
- El flujo batch en `POST /recovery/retries` tampoco hace clasificación.
- La tabla `vpos_charge_retries` y `vpos_reject_code_map` descritas en el workflow no existen en el modelo.
- `ChargeRecovery` registra un ciclo de seguimiento pero sin el campo `decision` (CAMBIO_TARJETA, REINTENTAR, etc.).
- El riesgo de duplicar reintentos si VirtualPOS ya los automatiza no está mitigado (el workflow advierte contra esto).

**Riesgo operativo:** alto. Llamar a `/retry` sobre cargos rechazados por tarjeta bloqueada o expirada acumula rechazos y puede activar penalizaciones de las marcas (código -11). El operador no tiene información del motivo antes de ejecutar el reintento.

---

### 13. seguimiento-cobros.md

**Estado:** Parcial

La sincronización obtiene `charge_program[]` de suscripciones activas y persiste cargos. Los pagos se sincronizan en bloque sin filtro de ventana de fechas.

**Discrepancias observadas:**
- No hay job de seguimiento diario que detecte cambios de estado en cuotas.
- No hay puente cuota→transacción: no se llama a `GET /v3/charge/{charge_id}` para obtener `payment.order.uuid` cuando una cuota cambia de estado a `pagado` o `rechazado`.
- Los pagos se sincronizan sin parámetros `created_from`/`authorization_from`; se trae todo paginado cada vez (no hay sincronización incremental).
- No hay integración de abonos (`GET /v3/deposit/{date}/sales`).
- No existe cuadratura diaria ni alertas de cuotas atrasadas.
- Los cuatro pendientes de sandbox (V-1 a V-4) no han sido validados.

**Riesgo operativo:** alto para la fiabilidad financiera. Sin cuadratura no se detectan inconsistencias entre cuota pagada y transacción ausente.

---

### 14. sync-virtualpos.md

**Estado:** Parcial

La sincronización está implementada y es el camino principal de ingesta. Cubre clientes, pagos, planes, suscripciones y sus `charge_program[]`. Registra `SyncRun`. Los payloads se sanitizan y se almacenan en `source_record` y tablas específicas.

**Discrepancias observadas:**
- Suscripciones: sin parámetro `status` en el listado. El workflow especifica `ACTIVA` diariamente y el resto semanalmente.
- Abonos/depósitos: no implementados.
- Clientes nuevos: no hay sincronización incremental (`created_from`). Se trae todo cada vez.
- No existe `sync_state` checkpoint por recurso para avanzar el cursor en caso de fallo parcial.
- Los pagos se sincronizan sin ventana de fechas (`created_from`/`authorization_from`).
- La paginación de pagos usa parámetros `page` y `limit` pero sin solape de 2 días.
- El workflow recomienda detectar cambios por `payload_hash` antes de normalizar; el código ya usa `payload_hash` en `source_record` (condición `where` en el `upsert`), lo que es correcto.

**Riesgo operativo:** bajo en producción (la sincronización funciona), pero la falta de incrementalidad puede generar cargas innecesarias al proveedor y no detectar suscripciones en estados no devueltos por el listado sin filtro.

---

### 15. web-checkout-payment.md

**Estado:** Parcial

El cliente HTTP tiene `delete_payment`, y `cancel_payment` en `write_virtualpos.py` está implementado.

**Discrepancias observadas:**
- No existe `POST /v3/payment/` ni `POST /v3/payment/{uuid}/webcheckout` en el cliente ni en los endpoints del CRM. El flujo de cobro único spot no está implementado.
- El cliente HTTP tiene `list_payments` y `get_payment`, que son la base para sincronizar pagos spot, pero no para iniciarlos.
- El workflow es relevante si el CRM necesita generar pagos únicos (donaciones spot); actualmente esta capacidad no está activada.

**Riesgo operativo:** ninguno activo (la funcionalidad no está expuesta). Riesgo futuro si se implementa sin el antiduplicado por `merchant_internal_code` ni el webhook de respaldo.

---

## Pendientes V-x (requieren validación en sandbox)

Los cuatro contratos no confirmados identificados en `seguimiento-cobros.md` aplican también a los workflows de sincronización, cargo y reintento:

### V-1: ¿El listado GET /v3/suscriptions trae charge_program[] completo?

**Origen:** seguimiento-cobros.md §8, sync-virtualpos.md
**Pregunta:** El listado paginado de suscripciones (`GET /v3/suscriptions?status=ACTIVA`) incluye `charge_program[]` completo como en el ejemplo oficial, o solo un subconjunto.
**Impacto si es incompleto:** la sincronización actual depende de `charge_program[]` embebido para obtener todos los cargos. Si el listado los trunca, los cargos futuros no se sincronizarían correctamente y la cuadratura sería imposible.
**Cómo validar:** Postman SC-1 contra sandbox: comparar `charge_program[]` del listado con `GET /v3/suscription/{id}/charges`.

### V-2: ¿Una cuota pagado o rechazado trae payment.order.uuid en GET /v3/charge/{id}?

**Origen:** seguimiento-cobros.md §8, reintento-cobro-rechazado.md §1
**Pregunta:** El ejemplo del endpoint `Recuperar Charge` no muestra el bloque `payment`. Confirmación de que un cargo `rechazado` efectivamente trae `payment.order.uuid`.
**Impacto si no viene:** el flujo de clasificación de motivo en `reintento-cobro-rechazado.md` depende de este UUID para llegar a `/attempts`. Sin él, todos los rechazos caen en `DESCONOCIDO` y no se puede automatizar el diagnóstico.
**Cómo validar:** Postman SC-3 con una cuota en estado `rechazado` o `pagado`.

### V-3: ¿GET /v3/payments incluye transacciones de cuotas recurrentes?

**Origen:** seguimiento-cobros.md §8
**Pregunta:** Si el listado global de pagos incluye las transacciones generadas por cobros de suscripción PAT, o solo pagos spot/web checkout.
**Impacto:** la sincronización actual trae todos los pagos sin filtro. Si las cuotas de suscripción no aparecen en ese listado, la tabla de pagos del CRM solo tendría pagos spot.
**Cómo validar:** Postman SC-6 buscando el UUID de un cargo conocido en el listado de pagos del período.

### V-4: ¿Un reintento reutiliza el mismo Payment o crea uno nuevo?

**Origen:** seguimiento-cobros.md §8, reintento-cobro-rechazado.md
**Pregunta:** Cuando VirtualPOS reintenta un cargo rechazado (ya sea por su cuenta o por llamada a `/retry`), el intento adicional aparece como un nuevo `attempt` en el mismo `payment.order.uuid`, o VirtualPOS crea un nuevo Payment con UUID diferente.
**Impacto:** si crea un Payment nuevo, la sincronización puede no capturarlo si solo mira la ventana de fechas original. Afecta la cuadratura y el diagnóstico de recuperación.
**Cómo validar:** en sandbox, rechazar una cuota, llamar a `/retry` y comparar `payment.order.uuid` antes y después.

---

## Resumen de riesgos operativos

| Riesgo | Workflows afectados | Severidad |
|--------|---------------------|-----------|
| Retry de cargo rechazado sin clasificar motivo (puede penalizar tarjetas bloqueadas) | 12, 6 | Alta |
| Sin antiduplicado al crear suscripción (doble cobro posible) | 1, 8 | Alta |
| URL redirect no persistida (link de inscripción irrecuperable) | 2, 1, 8 | Alta si se activan altas desde CRM |
| Clasificación de rechazo sin `/attempts` (sin diagnóstico automático) | 12 | Alta |
| Suscripciones en estados no ACTIVA no sincronizadas completamente | 10, 14 | Moderada |
| Creación de cargo para plan MONTO_FIJO expuesta sin restricción | 6 | Moderada |
| Sin cuadratura cuota↔transacción ni alertas de cobro | 13 | Moderada (financiera) |
| Cambio de tarjeta sin huella ni trazabilidad de vigencia del link | 4 | Moderada |
| Pre-chequeo de email/RUT libre omitido en edición de cliente | 9 | Baja-Moderada |
| E-083 no manejado en creación de cliente | 7 | Baja |
