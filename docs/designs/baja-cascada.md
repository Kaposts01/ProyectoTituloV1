# Baja en cascada de suscripciones: lo hecho y lo que falta (familia MGT)

> Estado: en curso (tanda 1 de MGT hecha; MGT-07 a MGT-10 y MGT-16 hechas en backend en la tanda 2: ver §5) · Creado: 2026-10-29 (Sprint 5, rama `sprint-5/sync-confiable`) · Alcance: baja de suscripciones por canal (VirtualPOS, Toku, Payku; TCH sin API).
> Fuente de la auditoría: informe `audit_management` del 2026-10-29 (solo lectura; hallazgos 1 a 12 y tareas MGT-01 a MGT-17). Este documento registra lo implementado en la tanda de backend y lo que sigue del diseño unificado. El plan y el estado de cada tarea viven en `docs/tasks.md` (no se reestructura aquí).

## 1. Hecho en esta tanda (backend)

| Tarea | Qué cambia | Dónde |
|---|---|---|
| MGT-01 | Todo `write_runs` creado por las rutas `/api/v1/writes/*` (VirtualPOS, Toku, Payku) guarda `requested_by_user_id` con el usuario del token. Los servicios reciben `requested_by_user_id` como keyword opcional (los llamadores que no lo pasan siguen dejando `NULL`). Sin cambios de firma públicos ni de respuestas. | `app/api/v1/routes/writes.py`, `app/services/write_{virtualpos,toku,payku}.py` |
| MGT-05 | `delete_subscription` de Toku falla **cerrado también en producción**: si falla el listado de invoices impagas, o la anulación (void) de alguna impaga que no esté `in_progress`, **no** se elimina la suscripción. Error `DeleteAbortedError` con código fijo (`INVOICE_LIST_FAILED` o `INVOICE_VOID_FAILED`, sin texto libre del proveedor); la ruta responde 502 con ese código. El `write_run` guarda el paso fallido, las invoices anuladas, las `in_progress` (ahora D30 niega la baja, ver abajo) y queda `reconciliation_required` si ya hubo anulaciones (irreversibles). | `app/services/write_toku.py`, ruta `DELETE /writes/toku/subscriptions/{id}` |
| MGT-06 | Servicio `refresh_subscription(db, source, external_id, *, run_id=None)`: relee **una** suscripción y sus cobros por GET (VP: `get_subscription` + cobros; Toku: `get_subscription` + invoices de esa suscripción; Payku: `get_subscription` con sus transacciones embebidas), actualiza tablas del canal, `source_records` y la consolidación centralizada **solo de ese registro**, con eventos de estado firmados con un `run_id` propio. Idempotente, fail-closed (códigos `UNSUPPORTED_SOURCE`, `PROVIDER_READ_FAILED`, `EMPTY_SUBSCRIPTION`, `LOCAL_WRITE_FAILED`, `CONSOLIDATION_FAILED`; nada local se escribe si una lectura falla) y devuelve un resumen (estado antes/después, cobros pendientes y en procesamiento). Para acotar la consolidación, las funciones de suscripciones/cobros/invoices/transacciones aceptan un `scope` opcional; `load_monto_vigente` acepta `subscription_ids`. | `app/services/subscription_refresh.py`, `channel_consolidation.consolidate_subscription`, `vp_current_amount.py` |
| MGT-03 | La baja de VirtualPOS toma el **mismo lock por suscripción** que `billing_apply` (409 si está tomado) y llama a `ensure_no_billing_flow_conflict` en modo baja (`closing_subscription=True`): bloquea las solicitudes `aplicando`/`requiere_conciliacion` y los cobros del CRM en `requiere_conciliacion`; el resto lo resuelve la propia baja. Tras el DELETE cierra las solicitudes `pendiente`/`aprobada` como `no_ejecutable` (motivo fijo `SUBSCRIPTION_CANCELLED`, evento inmutable con actor y `write_run_id`), retira la marca de calendario y pasa a `cancelado` los cobros del CRM vivos. | `write_virtualpos.cancel_subscription_with_outcome` |
| MGT-04 | Tras la baja llama a `refresh_subscription` y exige que **no queden cobros pendientes**; si quedan, los cancela uno a uno por `charge_id` (nunca el DELETE plural) y vuelve a verificar. Un cobro `procesando` **no** se cancela: la baja queda con `requires_reconciliation` y motivo (`processing_charges`). Otros motivos fijos: `pending_charges_remain`, `refresh_failed`, `local_cleanup_failed`. Fija `canceled_at` si el proveedor no lo trajo. La baja ya hecha **no se revierte** nunca: el `write_run` queda `reconciliation_required`. La respuesta de la ruta suma campos aditivos (`requires_reconciliation`, `reconciliation_reason`, `pending_charges`, `processing_charges`). | `write_virtualpos.py`, ruta `DELETE /writes/virtualpos/subscriptions/{id}` |

### Decisiones tomadas (recomendadas al usuario; reversibles)
- **Solicitud abierta de la Opción A al dar de baja VirtualPOS:** se cierra como `no_ejecutable` (decisión 5 del informe). Solo las `pendiente`/`aprobada`; las `aplicando`/`requiere_conciliacion` **bloquean** la baja (409) hasta resolverlas, porque ahí hay cobros del CRM a medio crear.
- **Toku con `in_progress` (D30, aprobada por el usuario el 2026-10-29):** si **alguna** factura de la suscripción está `in_progress`, la baja se **niega**: `DELETE /writes/toku/subscriptions/{id}` responde **409** con `detail={"code":"INVOICE_IN_PROGRESS","message":...}` (código fijo, sin texto del proveedor), **no anula ninguna factura** (ni las otras impagas) y **no** elimina la suscripción. El `write_run` queda `failed` (nada irreversible hecho) con `error_message` que lleva el código y `response_payload` `{step: "invoice_in_progress", skipped_in_progress: [ids], voided_invoice_ids: [], requires_reconciliation: false}`. La comprobación ocurre justo después de listar las impagas y antes de cualquier void. El resto del fail-closed de MGT-05 (`INVOICE_LIST_FAILED`, `INVOICE_VOID_FAILED` → 502) no cambia. Reintentar la baja cuando la factura deje de estar en curso. Nota para el frontend: el `detail` del 409 es un objeto `{code, message}` (los 502 siguen siendo texto).

### Efecto en producción cuando se despliegue
- **MGT-05 vuelve más estricta la baja de Toku en producción:** antes, un fallo del listado o de un void solo avisaba en el log y borraba la suscripción igual; ahora aborta con 502 y el código. El usuario verá errores donde antes había éxito con invoices impagas vivas.
- **VirtualPOS:** la baja puede responder 409 (lock tomado o solicitud `aplicando`/`requiere_conciliacion`) y ahora tarda más (relectura de la suscripción y sus cobros). El frontend actual solo lee `external_id` y `status`, por lo que los campos nuevos no lo rompen.
- No hay migraciones en esta tanda.

## 2. Lo que faltaba del diseño unificado (MGT-07 en adelante)

> Actualización: MGT-07, MGT-08, MGT-09, MGT-10 y MGT-16 quedaron implementados en backend en la tanda 2 (ver §5); esta tabla se conserva como registro de la auditoría. Siguen pendientes MGT-11 a MGT-15 y MGT-17 (ver §5.8).

| Tarea | Pendiente | Nota |
|---|---|---|
| MGT-07 | Generalizar `billing_change_requests` (canal, `request_type` de baja/medio de pago/monto Toku, `steps_json`, motivo obligatorio) | **Requiere migración** (la aplica el usuario); decisión: extender la tabla (recomendado) o tabla nueva |
| MGT-08 | Ejecutor de baja VirtualPOS (cascada ordenada, idempotente) sobre MGT-03/04/06 | Hoy la lógica vive dentro de `cancel_subscription_with_outcome`; el ejecutor la reutilizará. Decisión: ¿bloquear el cliente VP al dar de baja? |
| MGT-09 | Ejecutor de baja Toku (void fail-closed hecho en MGT-05 → PAUSED/`end_date`/DELETE → verificación con `refresh_subscription`) | Decisión: PAUSED (reversible, recomendado) vs DELETE; el sandbox de Toku comparte host con producción |
| MGT-10 | Ejecutor de baja Payku (DELETE → `refresh_subscription` → revisión de transacciones `pending`/`retry`) | Hoy `delete_subscription` de Payku fuerza `status="cancelled"` local sin releer; sin sandbox de Payku |
| MGT-11 | Eliminación de medios de pago (Toku `DELETE payment-methods` si no es compartido; Payku `suscriptionsdeletecards` tras validar Q-09; VP sin API) | Decisión del usuario: ¿se eliminan o se conservan? |
| MGT-12 a MGT-14 | Cambio de monto de Toku, baja de TCH (solicitud interna + exportación + verificación por Excel) y monto de Payku (tarea manual) | Decisiones 6 y 8 del informe |
| MGT-15, MGT-16 | Interfaz unificada de baja con vista previa y permisos/roles nuevos (`*.membership.request/approve`); definir en código `jefatura` y `coordinador` | Frontend: lo coordina otra sesión |
| MGT-17 | Pruebas de contrato en sandbox (VP; Toku solo con `TEST-` y `ALLOWED_IDS`; Payku bloqueado) | Necesita aprobación de los escenarios de escritura |
| RT-05 / webhooks / conciliación | Usar `refresh_subscription` como pieza común | MGT-06 ya la deja disponible; falta conectarla |

Pendientes menores detectados:
- `refresh_subscription` no refresca **pagos** de VirtualPOS ni de Toku (sus listados de pagos son globales, sin filtro por suscripción); en Payku sí (transacciones embebidas). Si se necesita, es una ampliación de MGT-06.
- No ejecuta `materialize_core_clients` (núcleo de clientes): solo suscripción y cobros del canal.
- `canceled_at` se fija con la hora UTC de la baja cuando el proveedor no la trae; el siguiente sync lo sobrescribe con el valor del proveedor.

## 3. Decisiones que siguen siendo del usuario

> Resueltas el 2026-10-29: 1 (tabla nueva, §5.1), 2 (D12: jefatura solicita; admin o jefatura aprueban; ejecutivo lee), 4 (Toku: PAUSED/`end_date`, no DELETE), 6 (botones directos solo admin, §5.5). Siguen abiertas: 3 (medios de pago), 5 (responsable bancario de TCH), 7 (monto Payku) y 8 (aprobar MGT-05 en producción).

1. Modelo de solicitudes de baja: extender `billing_change_requests` (recomendado) o tabla nueva.
2. Quién solicita y quién aprueba bajas.
3. Medios de pago: eliminarlos o conservarlos por trazabilidad (VP no tiene API).
4. Toku: baja = PAUSED/`end_date` (recomendado, reversible) o DELETE; (la pregunta de `in_progress` quedó resuelta por D30: impide el borrado).
5. Definición de baja TCH y responsable ante el banco.
6. Mantener o restringir los botones directos de baja del frontend.
7. Cambio de monto de Payku: tarea manual o suscripción nueva.
8. Aprobar el cambio de comportamiento de MGT-05 en producción (ya implementado en código, aún sin desplegar).

### Permisos «fantasma» (MGT-02): D28 = NO sembrarlos (decidido por el usuario)
Se conservan inalcanzables; el flujo nuevo de bajas no depende de ellos y un test (`tests/test_cancellation_permissions.py`) lo vigila. Texto original de la tanda 1:
Las rutas `DELETE /writes/virtualpos/payments/{id}`, `PUT /writes/toku/invoices/{id}` y `DELETE /writes/toku/invoices/{id}` exigen los permisos `virtualpos.payments.cancel`, `toku.invoices.update` y `toku.invoices.delete`, que **no existen** en `app/services/rbac.py` (`PERMISSIONS`) ni en las migraciones: nadie, ni `admin`, puede usarlas salvo inserción manual en la base. Esta tanda **no** los siembra ni los retira. Alternativas:
- A (recomendada si se quieren usar): sembrarlos en `rbac.PERMISSIONS` con una migración de datos que los asigne a `admin` (la ejecuta el usuario) y tests.
- B: retirar las tres rutas (y sus botones, si existen) por ser superficie de escritura sin uso real.
- C: dejarlas inertes tal como están (hoy equivale a «cerradas»).

## 4. Pruebas de esta tanda
- `tests/test_writes_actor.py` (MGT-01), `tests/test_toku_delete_fail_closed.py` (MGT-05; se actualizaron también dos pruebas de `test_toku_write_guard.py` que fijaban el comportamiento fail-open), `tests/test_subscription_refresh.py` (MGT-06), `tests/test_virtualpos_cancel_subscription.py` (MGT-03/04). Todo con clientes falsos: ninguna llamada a proveedores ni escritura en `crm`/`crm_sandbox`.
- Las rutas de prueba que usaban usuarios sintéticos ahora crean la fila real en `users` (el `write_runs.requested_by_user_id` es FK).

## 5. Diseño unificado implementado (tanda 2: MGT-16, MGT-07 y siguientes)

### 5.1 Modelo de solicitudes de baja (MGT-07): tabla nueva, no se extiende `billing_change_requests`
Decisión (recomendada en el informe como «extender», **cambiada a tabla nueva** por riesgo): se creó `subscription_cancellation_requests` (+ `subscription_cancellation_request_events`, migración `20261029_0051`). Motivos:
- `billing_change_requests` tiene `platform` limitado por CHECK a `virtualpos1/2`, `request_type` con CHECK de 4 tipos, columnas de monto/día/horizonte que no aplican a una baja, y **estados en español** que D38 deja sin renombrar ni migrar en esta tanda. Extenderla obligaba a relajar esos CHECK, a mezclar dos máquinas de estados (español e inglés) en una tabla y a tocar datos de la Opción A.
- La Opción A queda **intacta** (modelo, estados, índice único, API, bandeja). Una tabla nueva se descarta con un `DROP` limpio si el diseño cambia; una extensión no.
- Se reutiliza sin duplicar: el advisory lock por suscripción (`billing_apply.subscription_lock`), la política (`billing_policy`: autoaprobación, doble aprobación, expiración) y la función de base `billing_audit_immutable()` (creada en la 0038) para el trigger de eventos inmutables.
- Máquina de estados (inglés): `pending → approved → applying → completed | failed | requires_reconciliation | pending_external` y `rejected | withdrawn | expired | not_executable`. Abiertos (ocupan el cupo): `pending, approved, applying, requires_reconciliation, pending_external`.
- Campos: canal, suscripción, motivo obligatorio (`reason_code` fijo + `reason_comment` no vacío), solicitante, aprobador, `options` (cascada), `cascade_preview`, `steps` (resultado por paso), `requires_reconciliation`, expiración y `write_run_id`. Índice único parcial: una sola solicitud abierta por (canal, suscripción). CHECK de la baja de Payku: exige `options.confirm_irreversible = true`.
- Un `write_runs.request_id` apunta por FK a `billing_change_requests`, así que las ejecuciones de baja guardan `cancellation_request_id` en su `request_payload` (el `write_run_id` de la solicitud apunta de vuelta).

### 5.2 Permisos y roles (MGT-16)
Permisos nuevos (migración `20261029_0050`, sembrados en `rbac.PERMISSIONS`): `subscriptions.cancellation.request`, `.approve` y `.view`. Matriz (D12): `admin` y `jefatura` solicitan y aprueban; `soporte`, `ejecutivo` y `coordinador` solo ven (y `jefatura`/`admin` también ven). Si un rol no existe en la base, la migración no falla ni lo crea. **`coordinador`** no tiene permisos definidos en el código (manda la base de datos); lo único garantizado hoy es la lectura de las solicitudes de baja: no solicita ni aprueba. Los permisos «fantasma» (D28) siguen sin sembrarse y el flujo nuevo no depende de ellos (un test lo vigila).

### 5.3 Ejecutores por canal (MGT-08/09/10 y TCH)
`apply_cancellation_request` (`app/services/cancellation_apply.py`) reutiliza el esqueleto de `billing_apply`: banderas, D30 e irreversibilidad se comprueban **antes** de cambiar de estado (la solicitud sigue `approved`); lock por suscripción (`billing_apply.subscription_lock`) y transición atómica `approved → applying`; revalida que la suscripción siga activa (si no, `not_executable`); y ejecuta en este orden: **detener la suscripción → cancelar cobros pendientes → medio de pago**. Cada paso se persiste en `steps` (con evento inmutable `step_completed|step_failed|step_manual`) y se verifica releyendo el proveedor (`refresh_subscription`). Parada en el **primer fallo**:
- Fallo **sin** pasos previos hechos: `failed` (reintentable).
- Fallo **con** pasos hechos (las bajas de VirtualPOS/Payku y los void de Toku son irreversibles): `requires_reconciliation` + `requires_reconciliation = true`; nunca se revierte lo hecho.
- `reopen` (solo aprobador, comentario obligatorio) devuelve la solicitud a `approved` **conservando los pasos hechos**; el siguiente `apply` reanuda desde el paso fallido y no repite lo ya hecho (idempotente). `apply` sobre una solicitud `completed` o `pending_external` es un no-op.
- `dry_run=true` calcula el plan (pasos por hacer, bloqueos, facturas a anular en Toku) sin reclamar la solicitud ni escribir.
- Autoaprobación auditada (evento `self_approved`) según la política de la Opción A; la doble aprobación está **apagada** por defecto y, con una sola suscripción por solicitud, nunca exige dos aprobaciones.
- `sweep_stuck_applying` pasa a `requires_reconciliation` las solicitudes atascadas en `applying` más de 30 min (función lista; ver §5.8 sobre el job).

| Canal | Paso 1: detener | Paso 2: cobros pendientes | Paso 3: medio de pago |
|---|---|---|---|
| VirtualPOS | `cancel_subscription_with_outcome` (MGT-03/04, `lock_held=True` para no retomar el lock): DELETE de la suscripción, cierra solicitudes de la Opción A abiertas como `no_ejecutable`, retira la marca de calendario | Los pendientes los cancela el proveedor al dar de baja; se verifica con `refresh_subscription` y, si queda alguno, se cancela **por `charge_id`** (nunca el DELETE plural). Un cobro `procesando` no se cancela: `PROCESSING_CHARGES` → conciliación | **Tarea manual** registrada (`VP_NO_PAYMENT_METHOD_API`): VirtualPOS no tiene API |
| Toku | **PAUSED** (por defecto) o **`end_date`** (D12: reversible, NUNCA DELETE). Antes de tocar nada se lee el proveedor y, si alguna factura está `in_progress`, la baja se **niega** (D30, `INVOICE_IN_PROGRESS`, 409, la solicitud sigue `approved`) | `void` de cada factura impaga (irreversible), fail-closed (`INVOICE_LIST_FAILED`, `INVOICE_VOID_FAILED`) y verificación sin pendientes | **Tarea manual** registrada (`TOKU_PAYMENT_METHOD_DECISION_PENDING`): la eliminación del medio de pago de Toku (`DELETE payment-methods` si no es compartido) sigue pendiente de decisión (MGT-11) |
| Payku | `DELETE /api/sususcription/{id}` (**irreversible**: exige `confirm_irreversible = true` en la solicitud; un CHECK de base lo impone) | Payku no tiene API para cuotas: solo se verifica con `refresh_subscription`; si quedan `pending/retry` → `PENDING_CHARGES_REMAIN` → conciliación manual | **No se eliminan tarjetas** (Q-09 sin validar): tarea manual (`PAYKU_CARD_DELETE_Q09_UNVALIDATED`) |
| TCH | `register_internal`: la solicitud aprobada pasa a **`pending_external`** («en trámite»); sin proveedor ni `write_run` | n/a | `bank_mandate`: **tarea manual** (revocar el mandato en el banco; `TCH_BANK_MANDATE_OUTSIDE_CRM`) |

TCH: `close_tch_cancellations_from_report` cierra (`completed`, evento `closed_by_report`) las solicitudes `pending_external` cuya ficha ya trae `fecha_eliminacion` en `tch_suscripciones`. Mientras está «en trámite» la solicitud ocupa el cupo de una solicitud abierta por ficha. **Solo están el modelo y el cierre**: falta invocarlo al final del ETL/importación del Excel de TCH y la exportación para tesorería/banco (ver §5.8).

### 5.4 API `/api/v1/cancellations`
`POST /preview`, `POST` (crear, 201), `GET` (filtros: estado, canal, suscripción, solicitante, fechas), `GET /{id}`, `GET /{id}/events`, `POST /{id}/approve|reject|withdraw|reopen|apply`. Permisos: crear, vista previa y retirar exigen `subscriptions.cancellation.request`; aprobar, rechazar, reabrir y aplicar exigen `...approve`; leer exige `...view`. Retirar solo lo hace el solicitante o un admin (403 antes que 409). El actor sale siempre del token; los cuerpos rechazan campos extra; toda escritura exige CSRF. Errores `detail={code,message,...}` con mensajes fijos y sin eco de valores. Códigos HTTP: 409 `open_request_exists`, `invalid_request_state`, `subscription_busy`, `INVOICE_IN_PROGRESS`; 403 `writes_disabled`, `not_approver`, `self_approval_not_allowed`; 422 validación (`irreversibility_confirmation_required`, `comment_required`); 502 `apply_failed` (solicitud `failed`); 503 `reconciliation_required` (solicitud `requires_reconciliation`).

### 5.5 Cambio de comportamiento: botones directos de baja de `/writes/*` (decisión D12-7)
`DELETE /writes/virtualpos/subscriptions/{id}`, `DELETE /writes/toku/subscriptions/{id}`, `DELETE /writes/payku/subscriptions/{id}` y `POST /writes/toku/subscriptions/{id}/status` con `status = CANCELLED` exigen ahora el **rol `admin`** además de su permiso. Quien tuviera solo el permiso (p. ej. una jefatura con `virtualpos.subscriptions.cancel` en la base) recibe 403: debe usar `/cancellations`. Pausar o reactivar en Toku no cambia. El frontend actual muestra esos botones según permisos: otra sesión debe ocultarlos a quien no sea admin (MGT-15).

### 5.6 Matriz canal × acción (estado final de esta tanda)
| Acción | VirtualPOS | Toku | Payku | TCH |
|---|---|---|---|---|
| Solicitar / aprobar baja | `/cancellations` (jefatura y admin) | igual | igual | igual |
| Baja de la suscripción | Automática (DELETE, irreversible) | Automática: PAUSED o `end_date` (reversible) | Automática: DELETE (irreversible, confirmación explícita) | **Interna**: «en trámite»; cierre al llegar el Excel con la ficha eliminada |
| Cancelar cobros pendientes | Implícita + verificación + por `charge_id`; `procesando` → conciliación | `void` de impagas (fail-closed); `in_progress` **niega** la baja (D30) | Solo verificación (sin API) | n/a |
| Eliminar medio de pago | **Manual** (sin API) | **Manual** (decisión pendiente, MGT-11) | **Manual** (Q-09 sin validar) | **Manual** (mandato en el banco) |
| Cambio de monto | Opción A (sin cambios) | **Pendiente** (MGT-12) | **Pendiente**: manual (MGT-14) | **Pendiente** (MGT-13) |
| Verificación posterior | `refresh_subscription` | `refresh_subscription` | `refresh_subscription` | Excel (`fecha_eliminacion`) |
| Directo `/writes/*` | Solo admin | Solo admin (DELETE y CANCELLED) | Solo admin | n/a |

### 5.7 Pasos manuales (quedan registrados como paso `manual` de la solicitud)
1. VirtualPOS: bloquear/retirar la tarjeta en el portal de VirtualPOS si corresponde (no hay API).
2. Toku: decidir si se elimina el medio de pago y hacerlo desde el backoffice si el medio no es compartido.
3. Payku: eliminar la tarjeta en el portal (la API `suscriptionsdeletecards` no se usa hasta validar Q-09).
4. TCH: tramitar la revocación del mandato en el banco (responsable y plazo: decisión pendiente del usuario) y cargar el siguiente Excel.

### 5.8 Pendientes y límites (no resueltos en esta tanda)
- **Jobs** (hecho): `expire_pending_cancellation_requests` (cada hora, :25) y `sweep_stuck_applying` (cada 15 min) están registrados en el scheduler (`cancellation_jobs.py`, filas `sync_runs` con prefijo `cancellation_` excluido de los KPI de canales). Las bajas atascadas además disparan una alerta por correo (`docs/data/alerts.md`).
- **TCH**: `close_tch_cancellations_from_report` ya se invoca al final de la importación del Excel (script y `POST /api/v1/tch/import-report`). Falta la exportación para tesorería (sin PAN); la baja TCH no descuenta aún del churn mientras está «en trámite».
- **MGT-11** (eliminar medios de pago: Toku `DELETE payment-methods` si no es compartido, Payku tras Q-09), **MGT-12** (monto Toku), **MGT-13** (exportación TCH), **MGT-14** (monto Payku manual), **MGT-15** (interfaz unificada y ocultar los botones directos a quien no sea admin) y **MGT-17** (pruebas de contrato en sandbox): sin hacer.
- La vista previa de la cascada se calcula con la **última sincronización local**; el ejecutor relee el proveedor antes de actuar. No se ha probado nada contra proveedores reales: todo con fakes (el sandbox de Toku comparte host con producción).
- Quien aprueba bajas es quien tiene `subscriptions.cancellation.approve` (admin y jefatura); **no** se usa la lista `approver_roles` de `billing_policy` (esa es de la Opción A y por defecto solo incluye `admin`). De la política compartida se reutilizan autoaprobación, doble aprobación y expiración.
- Estados de la Opción A siguen en español (D38 pendiente); los de bajas están en inglés.

### 5.9 Qué debe hacer el usuario
1. **Respaldar `crm`** (`pg_dump`; no está en el `PATH`) y aplicar `alembic upgrade head` (20261029_0050 y 0051; head único `20261029_0051`). Sin esto, `/cancellations` falla (tablas inexistentes) y los permisos no existen.
2. Correr `scripts/maintenance/seed_roles.py` en `crm`: crea `ejecutivo` (con `subscriptions.cancellation.view`), agrega la vista a `soporte`, los tres permisos a `admin` y, **si ya existen**, los permisos de baja a `jefatura` y `coordinador` (nunca crea roles ni quita permisos). La migración 0050 hace lo mismo para los roles existentes al aplicarse. **Verificar** que existan `jefatura` y `coordinador`; si no existen, créelos desde el panel de roles y vuelva a correr `seed_roles.py`.
3. Informar a las jefaturas que las bajas se piden en `/cancellations` (la pantalla llega con MGT-15) y que el botón directo de baja es solo para admin.
4. Decidir: responsable bancario y plazo de la baja TCH, eliminación de medios de pago de Toku, y si se registran los jobs de expiración y barrido.

## 6. Tanda 3 (ola 4, lote L4-BAJAS): MGT-11 a MGT-15

Decisiones del usuario del 2026-11-02: d105 (medios de pago se conservan), d106 (monto de Toku por la bandeja de cambios de cobro), d107 (baja TCH: CSV sin PAN + Excel; la ejecuta un ejecutivo, no Tesorería, con paso de confirmación) y d108 (monto de Payku: tarea manual verificada por la sync).

### 6.1 Tareas manuales (`subscription_manual_tasks`, migración `20261102_0066`)
- Tipos: `payment_method_retained` (MGT-11), `tch_bank_mandate` (MGT-13), `payku_amount_change` (MGT-14). Estados: `pending → confirmed → verified`, `pending → verified` (la fuente externa lo ve antes) y `pending|confirmed → dismissed` (motivo obligatorio). Una sola abierta por (tipo, canal, suscripción).
- Confirmar deja `confirmed_by_user_id` y `confirmed_at` (CHECK de base) y un evento inmutable (`billing_audit_immutable()`). Lo hace el responsable u otra persona (`by_assignee` en el evento). Responsable por defecto: el solicitante; se reasigna con `/assign`.
- `cancellation_request_id` es referencia blanda (sin FK) para que la 0051 siga siendo reversible por sí sola.
- Permisos: `subscriptions.manual_tasks.view` (admin, jefatura, soporte, ejecutivo, coordinador) y `subscriptions.manual_tasks.confirm` (admin, jefatura). El rol `ejecutivo` del código sigue siendo solo lectura (D12): si el usuario quiere que los ejecutivos confirmen, basta asignarles el permiso de confirmación.
- API `/api/v1/manual-tasks`: `GET` (filtros), `GET /assignees`, `GET /{id}`, `POST /{id}/confirm|assign|dismiss`, `POST /payku-amount`, `GET /tch-export`.

### 6.2 Por tarea
- **MGT-11**: el paso `payment_method` sigue `manual` y crea la tarea `payment_method_retained`; códigos `TOKU_PAYMENT_METHOD_RETAINED` y `PAYKU_PAYMENT_METHOD_RETAINED` (VirtualPOS conserva `VP_NO_PAYMENT_METHOD_API`). La vista previa dice `reason = retained`. Nada se borra en el proveedor.
- **MGT-12**: `billing_change_requests.platform` admite `toku` (solo `change_amount`). Misma creación, aprobación, retiro, reapertura y allowlist del piloto (`BILLING_PILOT_ALLOWLIST` acepta `toku:<id>`). Ejecutor `toku_amount_apply.apply_toku_amount_change` → `write_toku.apply_amount_change`: `PUT /subscriptions/{id}` y `PUT /invoices/{id}` de las impagas **sin** las `in_progress`, verificación releyendo; fallo de una cuota → compensación (montos anteriores) y `fallida`; compensación o verificación fallidas → `requiere_conciliacion`. Detrás de `TOKU_WRITES_ENABLED` (403 `writes_disabled` con `channel = toku`) y de la guarda dura fuera de producción (solo `TEST-`/allowlist, `precheck_writes`). Solo probado con fakes.
- **MGT-13**: la baja TCH crea la tarea `tch_bank_mandate`. `GET /manual-tasks/tch-export` entrega el CSV de bajas «en trámite» con lista blanca de columnas (ficha, mandato, banco, tipo, monto, moneda, motivo, fechas, responsable, estado de la tarea): nunca número de cuenta/tarjeta, RUT ni contacto; celdas protegidas contra fórmulas; cada exportación deja evento `exported`. El Excel que trae `fecha_eliminacion` cierra la solicitud y deja la tarea `verified` (con `confirmed_before`).
- **MGT-14**: `POST /manual-tasks/payku-amount` (permiso `virtualpos.billing_changes.request`) registra la tarea con monto anterior y objetivo. Al final de `sync_payku` (fuera del bloque de la sync: un fallo no la marca fallida) `verify_payku_amount_tasks` cierra las tareas cuyo monto local ya es el pedido.
- **MGT-15**: en «Bajas», botón «Cambiar monto» (VirtualPOS → «Cambios de cobro»; Toku → solicitud en la bandeja con vista previa obligatoria; Payku → tarea manual; TCH → sin cambio desde el CRM) y pestaña «Tareas manuales» (confirmar, descartar, descargar el CSV de TCH).

### 6.3 Pendiente tras esta tanda
- MGT-17 (contrato en sandbox) y aprobar en Toku TEST- el cambio de monto con el usuario.
- La baja de Toku no cierra una solicitud de monto de Toku abierta: queda `no_ejecutable` al aplicarla (la suscripción ya no está activa).
- `refresh_subscription` y los webhooks de Payku no verifican las tareas de monto (solo la sync completa).
