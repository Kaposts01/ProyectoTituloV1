# Baja en cascada de suscripciones: lo hecho y lo que falta (familia MGT)

> Estado: en curso · Creado: 2026-10-29 (Sprint 5, rama `sprint-5/sync-confiable`) · Alcance: baja de suscripciones por canal (VirtualPOS, Toku, Payku; TCH sin API).
> Fuente de la auditoría: informe `audit_management` del 2026-10-29 (solo lectura; hallazgos 1 a 12 y tareas MGT-01 a MGT-17). Este documento registra lo implementado en la tanda de backend y lo que sigue del diseño unificado. El plan y el estado de cada tarea viven en `docs/tasks.md` (no se reestructura aquí).

## 1. Hecho en esta tanda (backend)

| Tarea | Qué cambia | Dónde |
|---|---|---|
| MGT-01 | Todo `write_runs` creado por las rutas `/api/v1/writes/*` (VirtualPOS, Toku, Payku) guarda `requested_by_user_id` con el usuario del token. Los servicios reciben `requested_by_user_id` como keyword opcional (los llamadores que no lo pasan siguen dejando `NULL`). Sin cambios de firma públicos ni de respuestas. | `app/api/v1/routes/writes.py`, `app/services/write_{virtualpos,toku,payku}.py` |
| MGT-05 | `delete_subscription` de Toku falla **cerrado también en producción**: si falla el listado de invoices impagas, o la anulación (void) de alguna impaga que no esté `in_progress`, **no** se elimina la suscripción. Error `DeleteAbortedError` con código fijo (`INVOICE_LIST_FAILED` o `INVOICE_VOID_FAILED`, sin texto libre del proveedor); la ruta responde 502 con ese código. El `write_run` guarda el paso fallido, las invoices anuladas, las omitidas por `in_progress` (intactas) y queda `reconciliation_required` si ya hubo anulaciones (irreversibles). | `app/services/write_toku.py`, ruta `DELETE /writes/toku/subscriptions/{id}` |
| MGT-06 | Servicio `refresh_subscription(db, source, external_id, *, run_id=None)`: relee **una** suscripción y sus cobros por GET (VP: `get_subscription` + cobros; Toku: `get_subscription` + invoices de esa suscripción; Payku: `get_subscription` con sus transacciones embebidas), actualiza tablas del canal, `source_records` y la consolidación centralizada **solo de ese registro**, con eventos de estado firmados con un `run_id` propio. Idempotente, fail-closed (códigos `UNSUPPORTED_SOURCE`, `PROVIDER_READ_FAILED`, `EMPTY_SUBSCRIPTION`, `LOCAL_WRITE_FAILED`, `CONSOLIDATION_FAILED`; nada local se escribe si una lectura falla) y devuelve un resumen (estado antes/después, cobros pendientes y en procesamiento). Para acotar la consolidación, las funciones de suscripciones/cobros/invoices/transacciones aceptan un `scope` opcional; `load_monto_vigente` acepta `subscription_ids`. | `app/services/subscription_refresh.py`, `channel_consolidation.consolidate_subscription`, `vp_current_amount.py` |
| MGT-03 | La baja de VirtualPOS toma el **mismo lock por suscripción** que `billing_apply` (409 si está tomado) y llama a `ensure_no_billing_flow_conflict` en modo baja (`closing_subscription=True`): bloquea las solicitudes `aplicando`/`requiere_conciliacion` y los cobros del CRM en `requiere_conciliacion`; el resto lo resuelve la propia baja. Tras el DELETE cierra las solicitudes `pendiente`/`aprobada` como `no_ejecutable` (motivo fijo `SUBSCRIPTION_CANCELLED`, evento inmutable con actor y `write_run_id`), retira la marca de calendario y pasa a `cancelado` los cobros del CRM vivos. | `write_virtualpos.cancel_subscription_with_outcome` |
| MGT-04 | Tras la baja llama a `refresh_subscription` y exige que **no queden cobros pendientes**; si quedan, los cancela uno a uno por `charge_id` (nunca el DELETE plural) y vuelve a verificar. Un cobro `procesando` **no** se cancela: la baja queda con `requires_reconciliation` y motivo (`processing_charges`). Otros motivos fijos: `pending_charges_remain`, `refresh_failed`, `local_cleanup_failed`. Fija `canceled_at` si el proveedor no lo trajo. La baja ya hecha **no se revierte** nunca: el `write_run` queda `reconciliation_required`. La respuesta de la ruta suma campos aditivos (`requires_reconciliation`, `reconciliation_reason`, `pending_charges`, `processing_charges`). | `write_virtualpos.py`, ruta `DELETE /writes/virtualpos/subscriptions/{id}` |

### Decisiones tomadas (recomendadas al usuario; reversibles)
- **Solicitud abierta de la Opción A al dar de baja VirtualPOS:** se cierra como `no_ejecutable` (decisión 5 del informe). Solo las `pendiente`/`aprobada`; las `aplicando`/`requiere_conciliacion` **bloquean** la baja (409) hasta resolverlas, porque ahí hay cobros del CRM a medio crear.
- **Toku con `in_progress`:** se omiten (no se anulan) y la suscripción **sí** se elimina si el resto verificó. El informe sugería no borrar con `in_progress`; queda como pregunta abierta (ver §3, decisión 4).

### Efecto en producción cuando se despliegue
- **MGT-05 vuelve más estricta la baja de Toku en producción:** antes, un fallo del listado o de un void solo avisaba en el log y borraba la suscripción igual; ahora aborta con 502 y el código. El usuario verá errores donde antes había éxito con invoices impagas vivas.
- **VirtualPOS:** la baja puede responder 409 (lock tomado o solicitud `aplicando`/`requiere_conciliacion`) y ahora tarda más (relectura de la suscripción y sus cobros). El frontend actual solo lee `external_id` y `status`, por lo que los campos nuevos no lo rompen.
- No hay migraciones en esta tanda.

## 2. Lo que falta del diseño unificado (MGT-07 en adelante)

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

1. Modelo de solicitudes de baja: extender `billing_change_requests` (recomendado) o tabla nueva.
2. Quién solicita y quién aprueba bajas.
3. Medios de pago: eliminarlos o conservarlos por trazabilidad (VP no tiene API).
4. Toku: baja = PAUSED/`end_date` (recomendado, reversible) o DELETE; y si una invoice `in_progress` debe **impedir** el borrado (hoy no lo impide).
5. Definición de baja TCH y responsable ante el banco.
6. Mantener o restringir los botones directos de baja del frontend.
7. Cambio de monto de Payku: tarea manual o suscripción nueva.
8. Aprobar el cambio de comportamiento de MGT-05 en producción (ya implementado en código, aún sin desplegar).

### Permisos «fantasma» (MGT-02): decisión pendiente del usuario, NO sembrados
Las rutas `DELETE /writes/virtualpos/payments/{id}`, `PUT /writes/toku/invoices/{id}` y `DELETE /writes/toku/invoices/{id}` exigen los permisos `virtualpos.payments.cancel`, `toku.invoices.update` y `toku.invoices.delete`, que **no existen** en `app/services/rbac.py` (`PERMISSIONS`) ni en las migraciones: nadie, ni `admin`, puede usarlas salvo inserción manual en la base. Esta tanda **no** los siembra ni los retira. Alternativas:
- A (recomendada si se quieren usar): sembrarlos en `rbac.PERMISSIONS` con una migración de datos que los asigne a `admin` (la ejecuta el usuario) y tests.
- B: retirar las tres rutas (y sus botones, si existen) por ser superficie de escritura sin uso real.
- C: dejarlas inertes tal como están (hoy equivale a «cerradas»).

## 4. Pruebas de esta tanda
- `tests/test_writes_actor.py` (MGT-01), `tests/test_toku_delete_fail_closed.py` (MGT-05; se actualizaron también dos pruebas de `test_toku_write_guard.py` que fijaban el comportamiento fail-open), `tests/test_subscription_refresh.py` (MGT-06), `tests/test_virtualpos_cancel_subscription.py` (MGT-03/04). Todo con clientes falsos: ninguna llamada a proveedores ni escritura en `crm`/`crm_sandbox`.
- Las rutas de prueba que usaban usuarios sintéticos ahora crean la fila real en `users` (el `write_runs.requested_by_user_id` es FK).
