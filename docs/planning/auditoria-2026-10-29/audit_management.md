# Auditoría: gestión de suscripciones desde el CRM (baja y cambio de monto) por canal

Fecha: 2026-10-29. Solo lectura (código, docs/integrations, colecciones Postman). Nada ejecutado contra proveedores ni bases.
Leyenda de confianza: [C] confirmado en código/Postman; [D] según docs del repo (no medido); [I] inferencia mía.

## 1. Qué permite cada proveedor (Postman + docs)

| Capacidad | VirtualPOS | Toku | Payku | TCH |
|---|---|---|---|---|
| Cancelar suscripción | `DELETE /v3/suscription/{id}` [C]. Pasa los cargos `pendiente` a `cancelado` (docs; el reintento en vuelo puede salir igual, sin medir) | `DELETE /subscriptions/{id}` (irreversible) o `POST /subscriptions/{id}/status` PAUSED/CANCELLED; fin programado con `PUT end_date` [C] | `DELETE /api/sususcription/{id}` (único mecanismo; irreversible; sin pausa) [C] | Sin API |
| Cancelar cargos pendientes/futuros | `DELETE /v3/charges/{sub}` (plural) y `DELETE /v3/charge/{id}` (individual) [C]. Con baja de suscripción queda implícito | No hay cargos programados: son *invoices*. `POST /invoices/{id}/void` (`delete_invoice:false`) o `DELETE /invoices/{id}`; las `in_progress` no se tocan. `DELETE` de suscripción no garantiza qué pasa con las impagas ya generadas [D] | No hay endpoint de cuotas; no se sabe si `DELETE` detiene un cobro `pending/retry` en curso [D] | n/a |
| Eliminar medio de pago | **No existe** endpoint (ni en Postman). Solo `PUT .../changecard` (link). Bloqueo indirecto: `PUT /v3/client` status BLOQUEADO [C] | `DELETE /payment-methods?id_payment_method=` (borrado lógico, idempotente; `force_status_change`) [C]. Medio compartido con otras suscripciones: verificar antes | `POST /api/suscriptionsdeletecards` (POST, valor = identifier de tarjeta; nombre del campo `card` sin validar, Q-09). Eliminar la única tarjeta no está documentado | n/a (mandato fuera del CRM) |
| Cambiar monto | **No existe** edición. Solo cargos individuales (Opción A) o suscripción nueva | `PUT /subscriptions/{id}` `amount` + `PUT /invoices/{id}` para cuotas ya generadas [C][D] | **No existe** por API (solo portal Payku, sin documentar; o suscripción nueva) | Sin API |
| Cancelar/reembolsar pagos ya hechos | `DELETE /v3/payment/{uuid}` (existe en Postman) | Refunds (`/refund/*`) | `/api/nullification` | n/a |

## 2. Qué existe hoy en el CRM

Rutas en `app/api/v1/routes/writes.py` (todas con `require_permissions` + `require_csrf`; servicios en `app/services/write_*.py`, cada uno crea un `write_runs` pending → remote_succeeded → completed/failed/reconciliation_required; secretos sanitizados con `safe_error_message`).

| Canal | Baja suscripción | Cancelar cargos | Medio de pago | Cambio de monto |
|---|---|---|---|---|
| VirtualPOS | `DELETE /writes/virtualpos/subscriptions/{id}` (perm `virtualpos.subscriptions.cancel`). Hace GET posterior, actualiza `Subscription.status/raw_payload` y `SourceRecord`. UI: botón solo en ACTIVA con modal (AppCore.tsx) | `DELETE .../subscriptions/{id}/charges` (dry_run por defecto, bloquea si hay marca/cobros gestionados/solicitud abierta) y `DELETE /writes/virtualpos/charges/{id}`; `/reassign-amount` (flujo viejo, protegido) | Nada. Solo link de cambio de tarjeta (`virtualpos.cards.change`) | Opción A completa: `/api/v1/billing/*` (change_amount, change_date, renew_calendar, one_off_charge), solicitud → aprobación → `apply_change_request` con lock, orden crear-primero, compensación y verificación. Solo `virtualpos1/2` (CHECK de BD) |
| Toku | `DELETE /writes/toku/subscriptions/{id}` (perm `toku.subscriptions.manage`) con void previo de invoices impagas no `in_progress`; `POST .../status` (PAUSED/ACTIVE/CANCELLED). UI: modal de estado y de eliminación | Void solo dentro de `delete_subscription`. Rutas `PUT/DELETE /toku/invoices/{id}` existen, **sin ruta de `void`** | Cliente tiene `delete_payment_method`, **sin ruta ni servicio** | Cliente tiene `update_subscription`, **sin ruta ni servicio**; solo `PUT invoices` (amount/due_date) |
| Payku | `DELETE /writes/payku/subscriptions/{id}` (perm `payku.subscriptions.cancel`). No relee el estado: fuerza `status="cancelled"` local | n/a | Cliente tiene `delete_subscription_card`, **sin ruta** | No hay API; no implementado |
| TCH | Nada. Solo lectura + import Excel (`POST /tch/import-report`, admin) | n/a | n/a | n/a |

Frontend (`frontend/src/AppCore.tsx`, `features/billing`): la baja y los cambios de estado son botones directos (modal de confirmación) que llaman a `/writes/*`; **no pasan por solicitud/aprobación**. La bandeja `features/billing` solo cubre cambios de cobro de VirtualPOS. Tras la baja, la UI parchea el estado en memoria (no re-sincroniza cargos).

Guardas generales [C]: JWT cookie HttpOnly + CSRF double-submit (`refreshCsrfToken` antes de cada escritura); flags `*_WRITES_ENABLED` (403 si apagadas); Toku además con `write_guard` (host, allowlist, prefijo TEST-, tope, ARMED); VirtualPOS con `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` para cargos; errores del proveedor sin eco al cliente.

## 3. Hallazgos (brechas y defectos)

1. **Sin autor en el flujo viejo.** `write_runs.requested_by_user_id` solo lo llenan `billing_apply`/Opción A (grep: ningún `write_*.py` lo asigna). Las bajas y cancelaciones por `/writes/*` quedan sin saber quién las hizo. Auditoría de baja incompleta. [C]
2. **Permisos fantasma.** `toku.invoices.update`, `toku.invoices.delete` y `virtualpos.payments.cancel` se exigen en `writes.py` pero no están en `rbac.PERMISSIONS` ni en migraciones: nadie (ni admin) puede usarlos salvo inserción manual. Hay que decidir: sembrar o retirar. [C]
3. **Roles.** Solo `admin` recibe todos los permisos por código; `ejecutivo` y `soporte` están definidos (solo `.view`, soporte + reintento + ambiente). `coordinador` y `jefatura` **no tienen definición de permisos en el código** (la base manda; `seed_coordinador.py` está en `legacy`). No hay permiso "solicitar baja" ni "aprobar baja". Los permisos de baja (`*.cancel`, `toku.subscriptions.manage`) son de ejecución directa, no de solicitud. [C]
4. **VirtualPOS `cancel_subscription` no protege la Opción A**: no llama a `ensure_no_billing_flow_conflict`, no toma el advisory lock, no cancela/cierra la solicitud abierta ni marca el calendario ni `vp_managed_charges`. Una baja con solicitud `aprobada/aplicando` o cobros gestionados vivos crea carreras. [C]
5. **VirtualPOS: cargos locales desactualizados tras la baja.** Solo se actualiza la suscripción; los cargos `pendiente` locales siguen así hasta el próximo sync (la KPI de pendientes y el recuperador mienten, ya hubo un caso de 1.343 cancelados contados). `canceled_at` no se fija en baja (viene del payload). No hay verificación posterior `GET charges?status=pendiente` vacío (paso 4 del workflow). No se maneja cargo `procesando`. [C][D]
6. **Toku `delete_subscription` es fail-open en producción**: si falla el listado de invoices o el void de alguna, solo hace `log.warning` y procede al DELETE (irreversible) dejando impagas vivas; fuera de producción falla cerrado. Contradice la prudencia del workflow ("preferir PAUSED/end_date"). `in_progress` omitidas pero igual se borra la suscripción. Sin marcar la suscripción local como "baja con pendientes". [C]
7. **Toku sin ruta para cambio de monto ni eliminación de medio de pago**; no hay endpoint propio para `void` aislado. Toku no tiene sandbox verificado de escritura (misma URL que producción). [C]
8. **Payku**: baja sin verificación por GET (estado literal `delete/cancel`), sin revisión de `transactions[]` pending/retry, sin motivo; cambio de monto imposible por API (decisión de negocio: portal manual o suscripción nueva). `payku` sin sandbox (bloqueado por soporte). [C][D]
9. **Sin cascada ni orquestación.** Cada paso es una ruta independiente que el usuario debe encadenar a mano; no existe "baja de socio" como unidad (cancelar todas las suscripciones del socio, ni siquiera duplicadas, que la doc VP advierte). [C]
10. **Sin estado de solicitud para bajas.** `billing_change_requests.request_type` solo admite 4 tipos y `platform` solo `virtualpos1/2`; la política/aprobadores/expiración/auditoría inmutable no cubren bajas ni otros canales. [C]
11. **Baja de TCH no definida** (ni modelo ni UI). El mandato bancario se gestiona fuera del CRM; hoy `fecha_eliminacion` solo llega por Excel. [C]
12. **Sin re-sync por suscripción.** Existen syncs por canal completo (`sync_virtualpos`, `sync_toku`, `sync_payku`); el refresco puntual lo implementa cada `write_*` ad hoc (VP sí hace GET; Toku y Payku solo parchean `raw_payload`). [C]

## 4. Matriz canal × acción (objetivo)

| Acción | VirtualPOS | Toku | Payku | TCH |
|---|---|---|---|---|
| Baja suscripción | Automática por API (DELETE sub) | Automática (PAUSED por defecto o `end_date`; DELETE solo si se confirma irreversibilidad) | Automática (DELETE) | **Solo interna** (ver §5) |
| Cancelar cargos pendientes | Implícita en DELETE sub + verificación `charges?status=pendiente`; los `procesando` se avisan | Void de invoices impagas no `in_progress` ANTES (fail-closed); `in_progress` → reintentar luego | Aviso si hay cobro pending/retry; sin acción API | n/a |
| Eliminar medio de pago | **No hay API**: bloquear cliente (`BLOQUEADO`) solo si no tiene otras suscripciones activas, o tarea manual en portal; registrar como "pendiente manual" | `DELETE payment-methods` solo si no asociado a otras suscripciones activas | `suscriptionsdeletecards` (tras validar Q-09 en sandbox) o sin eliminar (opcional) | Revocar mandato en banco (tarea manual) |
| Cambio de monto | Opción A (existente) | `PUT /subscriptions/{id}` amount + `PUT /invoices` de cuotas sin `in_progress` | No por API: tarea manual en portal, o suscripción nueva + baja de la anterior (socio reinscribe tarjeta) | Solicitud interna + export |
| Re-sync tras ejecutar | GET sub + GET charges de la sub | GET sub + invoices de la sub | GET sub | n/a |

## 5. Qué significa "baja" en TCH
TCH es mandato bancario cargado por Excel; el CRM no puede detenerlo. Propuesta: **"baja TCH" = solicitud interna aprobada** (nuevo estado `baja_solicitada`/`baja_pendiente_banco` en la suscripción TCH o tabla `membership_actions`) que (a) deja registro con autor, motivo y aprobador, (b) genera una **exportación** (CSV/Excel sin PAN) para tesorería/banco, (c) cierra la tarea cuando el siguiente reporte Excel trae `fecha_eliminacion` (verificación automática en el ETL) y (d) mientras tanto marca la suscripción como "baja en trámite" en el recuperador/dashboard sin inflar churn. Decisión de usuario: ¿quién tramita en el banco y plazo?

## 6. Diseño de flujo unificado (reutilizando la Opción A)

Generalizar `billing_change_requests` → "solicitudes de gestión" con `channel` (virtualpos1/2, toku, payku, tch) y `request_type` ampliado: `cancel_membership` (baja con cascada configurable), `change_amount` (por canal), `remove_payment_method`. Reusar tal cual: máquina de estados (pendiente → aprobada → aplicando → ejecutada/fallida/requiere_conciliacion/…), índice único de una solicitud abierta por suscripción, eventos inmutables, política de aprobadores (+ autoaprobación auditada), expiración, advisory lock, `sweep_stuck_applying`, `write_runs.request_id`/`requested_by_user_id`, UI de bandeja.

Fases del ejecutor por canal (patrón "pasos con compensación", cada paso = fila en eventos + write_run):
1. **Solicitud**: ejecutivo/jefatura crea con motivo obligatorio, alcance (todas las suscripciones del socio, cascada: sí/no cargos, sí/no medio de pago), y vista previa (qué se cancelará: cargos con fecha/monto, invoices, medios, `procesando`/`in_progress` avisados). Permiso nuevo `*.membership_cancel.request`.
2. **Aprobación**: jefatura/admin según política (el solicitante no aprueba su propia baja salvo autoaprobación activada por política; doble aprobación opcional para lotes).
3. **Ejecución** (re-leer estado real del proveedor y detectar drift como en `apply_change_request`; lock por socio/suscripción; chequeo de conflicto con solicitudes de cobro abiertas, que se cierran como `no_ejecutable` con evento):
   - VP: GET sub → (si hay `procesando` avisar) → DELETE sub → GET charges pendiente = vacío → [medio de pago: tarea manual/bloqueo cliente].
   - Toku: listar invoices → void impagas (fail-closed en todos los ambientes) → PAUSED/`end_date` o DELETE sub → [DELETE payment-method si no compartido] → verificar.
   - Payku: DELETE sub → GET sub (estado literal) → revisar transactions pending/retry → [delete card tras validar].
   - Orden: **detener lo que cobra primero (suscripción), luego limpiar cargos, y por último medios de pago** (lo irreversible al final y solo si todo lo previo verificó). Para Toku, void de invoices antes de borrar/pausar (no se puede revertir un void, así que sin compensación: se limita el alcance y se pausa primero).
   - Compensación: la baja de VP/Payku es irreversible, así que la "compensación" es parar ante el primer fallo, dejar `requiere_conciliacion`/`ejecutada_parcial` con la lista de pasos hechos y pendientes, y reintento idempotente que reanuda desde el paso fallido (cada paso verifica "ya está hecho" por GET: E-079/E-059/CANCELADA ya = éxito). Para cambio de monto en Toku sí hay compensación real (volver `amount` anterior).
4. **Verificación**: re-sync puntual de la suscripción (nuevo servicio `refresh_subscription(channel, id)` que hace GET y upsert en provider tables + `SourceRecord` + core vía consolidación acotada), contraste con expectativa; estado final `ejecutada` solo si verifica, si no `requiere_conciliacion`.
5. **Auditoría**: eventos inmutables + `write_runs` con autor y `request_id`; log de decisiones; visible en el detalle del socio; sin PII en payloads.
6. **TCH**: pasos 1–2 iguales; ejecución = registrar + exportar; verificación diferida por Excel.

Cambios de monto: Toku se integra como nuevo `change_amount` canal-específico (PUT sub + PUT invoices con `in_progress` excluidas, compensación posible); Payku como tarea manual con seguimiento (estado `pendiente_manual` y verificación leyendo `suclient.subscriptions.amount` en el siguiente sync); VP no cambia.

Permisos (RBAC): `*.membership.request` (ejecutivo no; jefatura/coordinador sí según decisión), `*.membership.approve` (jefatura/admin), `*.membership.execute` interno (solo ejecutor; las rutas `/writes/*` directas de baja quedan restringidas a admin con aviso o se cierran). CSRF y `require_permissions` como hoy; el actor siempre sale del token.

## 7. Tabla de brecha

| Brecha | Estado hoy | Objetivo | Tarea |
|---|---|---|---|
| Autor de escrituras | No se guarda en flujo viejo | `requested_by_user_id` siempre | MGT-01 |
| Permisos inexistentes | 3 códigos no sembrados | Sembrar o retirar | MGT-02 |
| Baja VP vs Opción A | Sin lock/conflicto | Mismo guard que cancel_future_charges | MGT-03 |
| Cargos locales tras baja VP | Desactualizados | Reconciliar + verificar | MGT-04 |
| Toku DELETE fail-open | Procede con impagas | Fail-closed siempre | MGT-05 |
| Re-sync puntual | Ad hoc | Servicio único por canal | MGT-06 |
| Modelo de solicitud | Solo VP, 4 tipos | Multicanal + baja | MGT-07 |
| Ejecutor de baja en cascada | No existe | Por canal con verificación | MGT-08..10 |
| Toku cambio de monto | Cliente sin ruta | Ruta + servicio + solicitud | MGT-12 |
| Medios de pago | Sin rutas | Toku/Payku con reglas de compartición | MGT-11 |
| Baja TCH | No definida | Solicitud + export + verificación | MGT-13 |
| Payku monto | Imposible | Tarea manual con seguimiento | MGT-14 |
| UI unificada | Botones directos | Pantalla de solicitud/bandeja | MGT-15 |
| Roles | jefatura/coordinador sin definición en código | Permisos nuevos asignados | MGT-16 |
| Pruebas | FakeVP; sin sandbox Toku escrituras ni Payku | Contrato sandbox VP; Toku con TEST-; Payku bloqueado | MGT-17 |

## 8. Tareas priorizadas (familia MGT-xx)

| ID | Descripción | Archivos principales | Esfuerzo | Riesgo | Decisión del usuario |
|---|---|---|---|---|---|
| MGT-01 | Registrar `requested_by_user_id` en todos los `write_runs` de `/writes/*` (pasar `current_user` desde las rutas) | `routes/writes.py`, `services/write_{virtualpos,toku,payku}.py`, tests | S | Bajo | No |
| MGT-02 | Sembrar o retirar `toku.invoices.update/delete` y `virtualpos.payments.cancel`; documentar quién los tiene | `services/rbac.py`, migración de permisos (la corre el usuario), tests | S | Bajo | ¿Sembrar o eliminar las rutas? |
| MGT-03 | `cancel_subscription` VP: `ensure_no_billing_flow_conflict`, advisory lock, cierre de solicitudes abiertas y marcas/gestionados al dar de baja | `write_virtualpos.py`, `billing_apply.py`, `billing_requests.py` | M | Medio | Qué hacer con solicitud abierta (cerrar `no_ejecutable` recomendado) |
| MGT-04 | VP: tras DELETE sub, GET `charges?status=pendiente` (debe estar vacío), reconciliar cargos locales a `cancelado`, fijar `canceled_at`, aviso si `procesando` | `write_virtualpos.py`, `core_materialization`/consolidación, tests | M | Medio | No |
| MGT-05 | Toku `delete_subscription` fail-closed en producción (abortar si listado/void fallan; no borrar con `in_progress`; preferir PAUSED+`end_date`) | `write_toku.py`, tests | S | Medio (cambia comportamiento de producción) | Sí: confirmar (producción) y preferencia PAUSED vs DELETE |
| MGT-06 | Servicio `refresh_subscription(channel, id)` (GET puntual → provider tables → SourceRecord → core) reutilizado por todos los ejecutores | nuevo `services/subscription_refresh.py`, `*_sync.py`, `channel_consolidation.py` | M | Medio | No |
| MGT-07 | Generalizar modelo de solicitudes: `channel`, `request_type` (`cancel_membership`, `remove_payment_method`, `change_amount_toku`), `steps_json`, motivo obligatorio; migración (la aplica el usuario) | `models/billing.py` (o nuevo `management.py`), `alembic/versions/`, `billing_requests.py` | L | Alto (BD) | Sí: ¿tabla nueva o extender la actual? (recomiendo extender) |
| MGT-08 | Ejecutor de baja VirtualPOS (cascada ordenada, idempotente, verificación) sobre MGT-03/04/06 | nuevo `services/membership_cancel.py` | M | Medio | Sí: ¿bloquear cliente VP al dar de baja? |
| MGT-09 | Ejecutor de baja Toku (void fail-closed → PAUSED/end_date/DELETE → verificación) | `membership_cancel.py`, `write_toku.py` | M | Alto (sandbox = host de producción) | Sí: DELETE vs PAUSED; ¿borrar payment-method? |
| MGT-10 | Ejecutor de baja Payku (DELETE → GET estado → revisión de transacciones) | `membership_cancel.py`, `write_payku.py` | S | Medio (sin sandbox) | Sí: esperar sandbox de Payku |
| MGT-11 | Rutas/servicios de eliminación de medio de pago: Toku `DELETE payment-methods` (no compartido) y Payku `suscriptionsdeletecards` (tras validar Q-09); VP queda como tarea manual | `write_toku.py`, `write_payku.py`, `writes.py`, `rbac.py` | M | Alto | Sí: ¿se eliminan medios o se conservan? |
| MGT-12 | Cambio de monto Toku: `PUT /subscriptions` + `PUT /invoices` (excluye `in_progress`), compensación y verificación | `write_toku.py`, `billing_*`/ejecutor, `writes.py` | L | Alto | Sí: reutilizar bandeja y aprobadores |
| MGT-13 | Baja TCH: modelo de solicitud, exportación sin PAN, verificación vía ETL, estado "baja en trámite" | `models/tch.py`, `routes/tch.py`, `scripts/etl_tch.py`, nueva exportación | M | Medio | Sí: definición de baja TCH y responsable bancario |
| MGT-14 | Payku cambio de monto: tarea manual con seguimiento y verificación en sync | ejecutor, `payku_sync.py` | S | Bajo | Sí: manual vs suscripción nueva |
| MGT-15 | Frontend: pantalla/diálogo "Dar de baja" y "Cambiar monto" por canal con vista previa de cascada, bandeja unificada; reemplazar botones directos | `frontend/src/features/billing/`, `AppCore.tsx` | L | Medio | Sí: ¿se retiran los botones directos de baja? |
| MGT-16 | Permisos y roles: `*.membership.request/approve`, política de aprobadores ampliada; definir en código jefatura/coordinador | `rbac.py`, `billing_policy`, seed | M | Medio | Sí: quién solicita y quién aprueba (ejecutivo no; jefatura solicita; admin/jefatura aprueba) |
| MGT-17 | Pruebas: unitarias con fakes; contrato sandbox VP (CT-CANCEL ya catalogado, BILL-11); Toku solo con claves `TEST-` y ALLOWED_IDS; Payku bloqueado | `tests/`, `tests_contract/` | M | Bajo | Aprobación de escenarios de escritura en sandbox (clase "avisar") |

Orden recomendado: MGT-01, 02, 05 (rápidos y de seguridad) → MGT-03, 04, 06 → MGT-07 y 16 (tras decisiones) → MGT-08 → MGT-15 (VP primero) → MGT-09/10/11 → MGT-12/13/14. Producción siempre con el usuario; todo piloto en sandbox primero.

## 9. Decisiones que necesita del usuario
1. Modelo: extender `billing_change_requests` (recomendado) o tabla nueva `management_requests`.
2. Quién solicita/aprueba bajas (recomendado: jefatura solicita, admin/jefatura aprueba, ejecutivo solo lectura; autoaprobación auditada como hoy).
3. Medios de pago: ¿eliminarlos al dar de baja (Toku/Payku) o conservarlos por trazabilidad? En VP no hay API (recomiendo no tocarlos y registrar tarea manual).
4. Toku: baja = PAUSED/`end_date` (recomendado, reversible) o DELETE.
5. Solicitud de cobro abierta al dar de baja VP: cerrar como `no_ejecutable` (recomendado).
6. Definición de baja TCH y responsable ante el banco.
7. Permitir o retirar los botones directos de baja (recomiendo restringir a solicitud y dejar la ruta directa solo para admin).
8. Cambio de monto Payku: tarea manual (recomendado) o suscripción nueva con reinscripción.
9. Aprobar MGT-05 como cambio de comportamiento en producción.

## 10. Restricciones respetadas
Sin escrituras, sin Alembic, sin proveedores, sin valores del `.env`. Hallazgos 1, 2, 4, 5, 6 verificados leyendo el código; la conducta real de los proveedores (reintentos en vuelo, Q-09 de Payku, qué pasa con impagas Toku tras DELETE) sigue sin medir.
