# Facturación gestionada por el CRM (opción A): escenarios de prueba

> Estado: borrador de QA/diseño · Fecha: 2026-10-27 · Alcance: suscripciones VirtualPOS de plan `MONTO_FIJO` (más de 6000; no se pueden cambiar de plan).
> Fuentes: `app/services/write_virtualpos.py` (`create_charge`, `cancel_future_charges`, `reassign_subscription_amount`, `retry_charge`), `app/services/vp_current_amount.py`, `app/integrations/virtualpos/client.py`, `docs/integrations/virtualpos/` (VALIDATION-PLAN.md, resources/sandbox.md, resources/charges.md, resources/subscriptions.md, resources/plans.md, workflows/*), `tests/`, `tests_contract/virtualpos/` y `reports/contract/virtualpos/drift-20261027-122600.md`.
> Este documento no cambia código. Solo lista escenarios y qué resultado espera el diseño ya decidido.

## 0. Resumen del diseño que se prueba

| Regla | Decisión |
| --- | --- |
| Monto de la suscripción | `monto_vigente` = último cargo `pagado`/`procesando` con `charge_date <= hoy` (`vp_current_amount.py`). |
| Reasignar monto | Dentro del horizonte (12 meses): **crear primero** un cargo por mes, **cancelar** los automáticos solo si se crearon todos, **compensar** si falla a la mitad y **verificar al final** que haya exactamente un `pendiente` por mes con el monto nuevo. El job diario repone el mes M0+12. |
| Día de cobro | `charge_day` (dato propio) = día del último cargo. El job usa siempre el dato guardado. Cambiarlo es una operación explícita que reprograma los pendientes del horizonte. |
| Rechazos | El job **no suspende**. Crea el cargo de cada mes. Con 3 o más rechazos seguidos el socio queda marcado como "racha de rechazos" en el recuperador. Solo se deja de gestionar si la suscripción se cancela o termina. |
| Ventana de 31 días | Si la fecha de un mes pasó hace 31 días o menos y ese mes no tiene cargo `pagado`/`procesando`/`rechazado`, se crea uno con fecha de mañana (VirtualPOS exige `charge_date >= hoy`, E-078). Si pasó hace más de 31 días, no se cobra y el mes queda para revisión manual. |
| Aprobaciones (propuesta) | Permisos separados para solicitar y aprobar. Nadie aprueba lo propio, salvo un admin en cambios pequeños. 1 aprobación para cambios individuales. 2 para cambios masivos (más de 20 suscripciones) o con variación grande (más del 50 %). Umbrales configurables. |

**Hechos medidos en sandbox (2026-10-27):** `POST /v3/charge` aceptado en plan fijo (VP-C05). Los errores llegan con HTTP 200 y cuerpo NOK (VP-C11, C12, C21, C27). `internal_code` no es idempotente (VP-C07). Reutilizar un `internal_code` tras cancelar se acepta (VP-C29). DELETE plural cancela todos los pendientes. Los filtros de fecha de `/charges` se ignoran (VP-C26). El listado de suscripciones trae el `charge_program` completo (VP-C01), pero **sin `internal_code`**, que solo aparece en `/charges` y en el detalle (VP-C28). No hubo 429 con ~3 req/s (VP-C16).

**Convenciones.** Cómo se prueba: `UNIT` (pytest con fakes del proveedor) · `CONTRATO` (sandbox, `tests_contract/`) · `MANUAL` (sandbox con tarjeta y espera de la fecha de cobro) · `PILOTO` (producción, suscripciones de prueba). Estado: `a verificar` · `cubierto por test X` · `medido en sandbox`. "Parcial" quiere decir que hoy un test cubre la versión de **un mes** (`reassign_subscription_amount` actual), no la del horizonte de 12 meses.

Tarjetas: se nombran por tipo y últimos 4 dígitos, según `resources/sandbox.md` (que pide no copiar los números completos a otros archivos).

| Alias | Tarjeta (sandbox.md) | Resultado declarado |
| --- | --- | --- |
| T1 | Crédito VISA …6623 | Aprobada |
| T2 | Crédito AMEX …2032 | Aprobada |
| T3 | Crédito MASTERCARD …0568 | Rechazada |
| T4 | Débito …7763 | Aprobada |
| T5 | Débito …3829 | Rechazada |
| T6 | Prepago VISA …6590 | Aprobada |
| T7 | Prepago MASTERCARD …9480 | Rechazada |

> La documentación **no declara el motivo** del rechazo de T3/T5/T7. Tampoco existe en sandbox una tarjeta "vencida" ni "sin fondos" (acepta "cualquier vencimiento"). Esos motivos solo se prueban con fakes (códigos `-8`, `-4`, `-3` y palabras clave de `_classify_rejection`).

---

## 1. Coexistencia de cargo automático y cargo manual (la duda abierta)

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-CO-01 | Plan fijo ACTIVO; el mes M tiene un cargo automático `pendiente` (monto viejo, día D) | `POST /v3/charge` en M, mismo día D, monto nuevo | Hay que medir cuál de estos ocurre: (a) quedan dos `pendiente`, (b) VP reemplaza el automático, (c) NOK (p. ej. E-087 "máximo de cargos mensuales" o E-113). El diseño supone (a) y por eso crea primero y cancela después. Con (b), no hay que cancelar. Con (c), la opción A no es viable sin cancelar antes (orden inseguro) | CONTRATO | P0 | a verificar |
| GB-CO-02 | Igual que CO-01 | POST en M con otro día (D+5) | Igual que CO-01. Anotar si VP distingue por mes o por fecha exacta | CONTRATO | P0 | a verificar |
| GB-CO-03 | Resultado (a) de CO-01 | `DELETE /v3/charge/{auto}` | El automático pasa a `cancelado`. El manual sigue `pendiente` y no cambia monto ni fecha. La suscripción sigue ACTIVA | CONTRATO | P0 | a verificar (medido en plan VARIABLE, V-5 B) |
| GB-CO-04 | Resultado (a); **no** se cancela el automático | Llegan las dos fechas | Hay que medir si VP cobra **ambos** (doble cobro). Esto define la gravedad de una compensación fallida (RA-09/RA-10) | MANUAL (T1) | P0 | a verificar |
| GB-CO-05 | Plan fijo; mes sin automático (cancelado); manual `pendiente` con T1 | Llega la fecha del manual | El cargo pasa a `pagado`, con `payment.order.uuid`. El sync lo ve y `monto_vigente` pasa a ser el monto nuevo | MANUAL (T1) | P0 | a verificar (V-5 límite 4) |
| GB-CO-06 | El automático de M está `procesando` | Reasignación o job sobre M | No se crea manual ni se cancela nada. M queda cubierto con el monto viejo; el monto nuevo rige desde M+1 | UNIT | P0 | a verificar |
| GB-CO-07 | El automático de M está `pagado` | Reasignación o job sobre M | Igual que CO-06: M cubierto, sin escrituras | UNIT | P0 | a verificar |
| GB-CO-08 | El automático de M está `rechazado` (con o sin reintentos de VP en curso) | Reasignación o job sobre M | M se considera cubierto. No se crea manual (evita cobrar dos veces si un reintento se aprueba). La recuperación va por `/retry` o `changecard` | UNIT | P0 | a verificar |
| GB-CO-09 | M sin cargos (automático cancelado por una **pausa registrada**) | Job | No repone M: la pausa explícita manda. Sin pausa registrada → CO-10 | UNIT | P0 | a verificar |
| GB-CO-10 | M solo tiene un cargo `cancelado` con el `internal_code` del CRM | Job crea M con el mismo `internal_code` | VP acepta el POST (VP-C29). El CRM no adopta el cancelado y crea uno nuevo | CONTRATO + UNIT | P1 | medido en sandbox (VP-C29); cubierto por `test_crea_si_solo_hay_cancelado_con_ese_codigo` |
| GB-CO-11 | Orden inverso (cancelar el automático y después crear) y el POST falla | — | Prohibido por diseño: el socio quedaría sin cargo del mes. Test de guarda: ningún DELETE antes de que todos los POST terminen bien | UNIT | P0 | parcial: `test_reassign_post_failure_cancels_nothing` |
| GB-CO-12 | Ya existe un manual `pendiente` con el `internal_code` X | Segundo intento con X (reintento o doble clic) | VP crearía otro (VP-C07). El CRM lista `/charges`, encuentra X y lo adopta sin POST | UNIT | P0 | medido en sandbox (VP-C07); cubierto por `test_adopta_pendiente_con_mismo_codigo_sin_post` |
| GB-CO-13 | Cargos manuales creados por el CRM | Sync diario desde `GET /v3/suscriptions` | `charge_program[]` no trae `internal_code` (VP-C28). El CRM debe reconocer sus cargos por `charge_id` en un **registro propio** y no por `internal_code` del listado | UNIT | P0 | medido en sandbox (VP-C28); diseño a verificar |
| GB-CO-14 | Automáticos programados más allá del horizonte (hay suscripciones con 120–300 cargos, hasta 2031) | Reasignación | Solo se cancelan los automáticos de M0..M0+11. Los de M0+12 en adelante siguen `pendiente` con el monto viejo | UNIT | P0 | a verificar |
| GB-CO-15 | Como CO-14, al día siguiente | Job repone M0+12 | Crea el manual de M0+12 con el monto nuevo y **después** cancela el automático de M0+12. Si no lo cancela, ese mes se cobra dos veces | UNIT + CONTRATO | P0 | a verificar |
| GB-CO-16 | Suscripción gestionada | Alguien llama a `cancel_future_charges` **sin** `charge_ids` (usa el DELETE plural) | Debe bloquearse en suscripciones gestionadas: el plural cancela todo, incluidos los manuales y los automáticos fuera del horizonte (la red de seguridad). Hoy el código usa el plural cuando `charge_ids` es None | UNIT | P0 | a verificar |
| GB-CO-17 | Plan `num_charges` corto (p. ej. 3), `automatic_renewal=T` | Se cancelan automáticos y se crean manuales; se agota el calendario | Medir si VP renueva el bloque, si cuenta los manuales y los cancelados, y si genera automáticos nuevos que se superpongan con los manuales (posible duplicado) | CONTRATO + MANUAL | P1 | a verificar |
| GB-CO-18 | `num_charges` corto, `automatic_renewal=F` | Se agota el calendario | Medir el estado final de la suscripción y si `POST /v3/charge` sigue aceptándose (o E-060). Si deja de estar ACTIVA, el job deja de gestionarla | CONTRATO | P1 | a verificar |
| GB-CO-19 | Plan fijo con N automáticos | Se cancelan los N del horizonte | Medir si los cancelados "consumen" `num_charges` y terminan la suscripción antes de tiempo (los manuales responderían E-060) | CONTRATO | P0 | a verificar |
| GB-CO-20 | Suscripción CANCELADA con manuales `pendiente` | Baja (`DELETE /v3/suscription`) o job | VP pasa los manuales a `cancelado` (verificar). Un POST posterior da E-060 y el job no reintenta | CONTRATO | P0 | a verificar |
| GB-CO-21 | Suscripción FINALIZADA, SUSCRIPCION_FALLIDA o SUSCRIBIENDO | Job | Nunca se gestiona ni se escribe | UNIT | P1 | a verificar |
| GB-CO-22 | Plan con `fixed_amount_day_charge="0"` (cobro al suscribir) | Alta en gestión | `charge_day` = día del último cargo. Si no hay ningún pagado, día de alta. Nunca 0 | UNIT | P1 | a verificar |
| GB-CO-23 | Plan con día 05 pero `charge_day=20` (cambiado a pedido) | Job | Usa 20 (dato guardado), no el día del plan | UNIT | P1 | a verificar |
| GB-CO-24 | `charge_day` 29, 30 o 31 | Meses de 30 días, febrero 2027 (28) y febrero 2028 (29, bisiesto) | Se usa el último día del mes. Exactamente un cargo por mes; ningún mes sin cargo ni con dos | UNIT | P0 | a verificar |
| GB-CO-25 | Día de cobro no estándar para VP (p. ej. 31, 29 o 07) | POST manual con ese día | Medir si VP acepta cualquier día (los planes solo ofrecen 01/05/10/15/20/25/28/30) | CONTRATO | P1 | a verificar |
| GB-CO-26 | M0 = diciembre | Reasignación de 12 meses | Meses 2026-12..2027-11 bien calculados. El `internal_code` usa YYYYMM y no colisiona entre años | UNIT | P1 | a verificar |
| GB-CO-27 | `charge_date = hoy` (E-078 permite "igual o mayor a hoy") | POST con fecha de hoy | Medir si VP lo acepta y si lo cobra el mismo día o lo deja vencido. Por eso el diseño usa mañana | CONTRATO + MANUAL | P2 | a verificar |
| GB-CO-28 | Monto 0, negativo o con decimales | Solicitud de reasignación | El CRM rechaza antes de llamar a VP (E-055 como respaldo) | UNIT | P2 | a verificar |

## 2. Rechazos y tarjetas

| ID | Precondiciones | Acción / evento | Resultado esperado en el CRM | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-RZ-01 | Plan fijo | Enrolamiento con T1, T2, T4 o T6 | Suscripción ACTIVA con `charge_program`. El CRM calcula `charge_day` y la deja elegible para gestión | MANUAL | P1 | a verificar |
| GB-RZ-02 | Plan fijo | Enrolamiento con T3, T5 o T7 | SUSCRIPCION_FALLIDA o sin activar (sandbox.md caso 4, "a verificar"). El CRM no la gestiona | MANUAL | P1 | a verificar |
| GB-RZ-03 | Suscripción ACTIVA (T1), plan día 0 | Primer cobro automático | `pagado`. `monto_vigente` = ese monto. Racha 0 | MANUAL | P1 | a verificar |
| GB-RZ-04 | ACTIVA con T1, después `changecard` a T3 | Primer cobro automático | `rechazado`. Racha 1. Aparece en el recuperador. El job sigue creando M+1 | MANUAL | P1 | a verificar |
| GB-RZ-05 | Manual del CRM `pendiente` con T1 | Fecha de cobro | `pagado`. El sync actualiza el estado. `monto_vigente` = monto nuevo. Racha 0 | MANUAL | P0 | a verificar (= CO-05) |
| GB-RZ-06 | Manual `pendiente`, tarjeta cambiada a T3 | Fecha de cobro | `rechazado`. Racha +1. Visible en el recuperador. Se registra el motivo (`/attempts`). El job **sigue** creando el mes siguiente | MANUAL | P0 | a verificar |
| GB-RZ-07 | Como RZ-06 | Pasan los días +1..+3 | Medir si VP hace reintentos automáticos (1/2/3) sobre un cargo **manual** como lo hace con el automático, y si cada reintento crea un Payment nuevo (V-4) | MANUAL | P0 | a verificar |
| GB-RZ-08 | Cargo rechazado; reintentos automáticos 1, 2 y 3 rechazados | Sync | La racha cuenta **meses** (cargos con rechazo definitivo), no intentos: +1 en total | UNIT | P0 | a verificar |
| GB-RZ-09 | Cargo rechazado; el reintento automático 2 se aprueba | Sync | `pagado`. La racha vuelve a 0. `ChargeRecovery` se cierra como recuperado | UNIT | P1 | parcial: `test_reconcile_charge_recoveries_closes_paid_and_rejected_cycles` |
| GB-RZ-10 | Rechazo con código transitorio (`-2`, `-10`) | `/retry` manual desde el CRM | Decisión REINTENTAR. Un solo GET (sin reintento HTTP). `write_run` completed. `ChargeRecovery` con cierre a +4 días | UNIT | P1 | a verificar (clasificador sin test directo) |
| GB-RZ-11 | Rechazo de tarjeta (`-1`, `-4`, `-7`, `-8`, `-11`, …) o palabras "vencid"/"bloquead" | `/retry` manual | `RetryBlockedError`, `write_run` blocked y se propone el link `changecard` | UNIT | P1 | parcial: `test_needs_card_change_classifies_card_and_blocked_account_rejections` |
| GB-RZ-12 | Rechazo `-6` o `-3` ya reintentado una vez | Segundo `/retry` | Decisión CAMBIO_TARJETA | UNIT | P2 | a verificar |
| GB-RZ-13 | Rechazo por límite del comercio (`-1003`, `-1009`, …) | `/retry` o sync | DIFERIR y alerta a finanzas. **Decidir** si cuenta para la racha del socio (propuesta: no) | UNIT | P1 | a verificar (decisión abierta) |
| GB-RZ-14 | Cargo que no cumple condiciones | `/retry` responde E-081 (HTTP 200 NOK) | `write_run` failed y queda para revisión MANUAL | UNIT | P2 | parcial: `test_retry_charge_nok_marca_failed` |
| GB-RZ-15 | 3 meses seguidos rechazados | Sync del 3.º rechazo | Marca "racha de rechazos" en el recuperador. **No** suspende. El job crea M+1 | UNIT | P0 | a verificar |
| GB-RZ-16 | Racha 2 y luego un mes pagado | Sync | Racha 0. Si tenía la marca, se quita | UNIT | P0 | a verificar |
| GB-RZ-17 | Rechazado, mes en pausa registrada, rechazado | Sync | La pausa no corta la racha ni suma (propuesta) | UNIT | P1 | a verificar (decisión abierta) |
| GB-RZ-18 | Racha de 6 o más meses | Job | Sigue creando cargos (decisión). Alerta escalada. Riesgo: VP/marca devuelve `-11` (límite de rechazos de la marca); vigilar | UNIT | P1 | a verificar |
| GB-RZ-19 | Manuales `pendiente` creados con T1; `changecard` a T3 antes de la fecha | Fecha de cobro | Medir si el cargo manual usa la tarjeta **vigente** al cobrar (se espera rechazo). Igual al revés (T3 → T1: se espera `pagado`) | MANUAL | P0 | a verificar |
| GB-RZ-20 | Cargo manual `rechazado`; el socio cambia a T1 vía `changecard` | Polling detecta la huella nueva | El CRM consulta el estado y llama `/retry` una vez por cargo rechazado. Medir si VP reintenta por su cuenta tras el cambio (no documentado) | MANUAL | P1 | a verificar |
| GB-RZ-21 | Cambio de tarjeta el mismo día del cobro | Cobro sale rechazado con la tarjeta anterior | El paso 6 de `cambio-tarjeta.md` lo recupera con `/retry`. Sin doble cobro | MANUAL | P2 | a verificar |
| GB-RZ-22 | Tarjeta vencida (no simulable en sandbox) | Cobro con rechazo `-8` o "expirad" (fake) | CAMBIO_TARJETA. Alerta proactiva por `payment_method.expiration_date` a 30–45 días | UNIT | P1 | a verificar |
| GB-RZ-23 | Sin fondos (no simulable en sandbox) | Rechazo `-3` o "fondos" (fake) | REINTENTAR una vez y después CAMBIO_TARJETA | UNIT | P1 | a verificar |
| GB-RZ-24 | Débito T4 / Prepago T6 | Cobro manual | `pagado`, igual que crédito | MANUAL | P2 | a verificar |
| GB-RZ-25 | AMEX T2 | Cobro manual | `pagado` | MANUAL | P2 | a verificar |
| GB-RZ-26 | Prepago MC T7 / Débito T5 vía `changecard` | Cobro manual | `rechazado`. Anotar el `rejected_object.code` real en `discrepancies.md` | MANUAL | P2 | a verificar |
| GB-RZ-27 | Manual `rechazado` en reintento; la suscripción se cancela | `DELETE /v3/suscription` | Medir si el rechazado pasa a `cancelado` y se detienen los reintentos (cancel-subscription.md ⚠️). El CRM deja de gestionar | MANUAL | P1 | a verificar |
| GB-RZ-28 | Cargo `rechazado` del mes M; se reasigna el monto | Reasignación | M cubierto (no se puede cancelar un rechazado, E-059). Los manuales nuevos empiezan en M+1 | UNIT | P1 | a verificar |

## 3. Reasignación de monto y cambio de fecha

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-RA-01 | 12 automáticos `pendiente` en el horizonte; monto sube | Reasignar (aprobado) | 12 POST OK y después 12 DELETE individuales. Verificación final: exactamente un `pendiente` por mes con el monto nuevo. `write_run` completed | UNIT | P0 | parcial: `test_reassign_creates_first_then_cancels_matching_period` |
| GB-RA-02 | Igual que RA-01; monto baja más del 50 % | Reasignar | Igual que RA-01. Exige doble aprobación (AP-09) | UNIT | P0 | a verificar |
| GB-RA-03 | Monto nuevo = monto programado | Reasignar | No-op: sin POST ni DELETE. Se registra como "sin cambios" | UNIT | P1 | a verificar |
| GB-RA-04 | El horizonte ya tiene manuales del CRM (reasignación anterior) | Reasignar otra vez | Crea los nuevos y cancela los **manuales anteriores** (no solo automáticos). Cada mes queda con un único pendiente | UNIT | P0 | a verificar |
| GB-RA-05 | La fecha de M0 ya pasó este mes | Reasignar | M0 sigue la regla de la ventana: si M0 está cubierto, el monto nuevo rige desde M0+1; si no, cargo con fecha de mañana. Nunca se envía una fecha pasada (E-078) | UNIT | P0 | parcial: `test_create_charge_nok_e078_falla_con_codigo` |
| GB-RA-06 | La suscripción tiene menos de 12 automáticos futuros (calendario corto) | Reasignar | Se crean los 12 meses igual. Los meses sin automático no requieren DELETE | UNIT | P1 | a verificar |
| GB-RA-07 | POST k (1<k≤12) responde NOK | Reasignar | **Compensación:** se cancelan los k-1 nuevos. No se cancela ningún automático. `write_run` failed. La verificación final muestra el estado original | UNIT | P0 | parcial: `test_reassign_post_failure_cancels_nothing` (k=1) |
| GB-RA-08 | POST k con timeout, pero el cargo sí se creó | Reintento o compensación | El reintento lo adopta por listado (no duplica). La compensación también lista `/charges` para encontrar el huérfano y cancelarlo | UNIT | P0 | parcial: `test_timeout_en_post_y_reintento_adopta` |
| GB-RA-09 | Compensación en curso; un DELETE de un cargo nuevo falla | — | `reconciliation_required` y alerta P0. La suscripción queda **bloqueada** para nuevas operaciones hasta resolverlo. El control diario CS-03 lo vigila antes de `charge_date` | UNIT | P0 | a verificar |
| GB-RA-10 | 12 POST OK; el DELETE del automático j falla (red o 5xx) | — | No compensar (los nuevos son correctos). Reintentar el DELETE j. `reconciliation_required` si persiste. Plazo: antes de la `charge_date` de j | UNIT | P0 | a verificar |
| GB-RA-11 | Entre el listado y el DELETE, el automático j pasó a `procesando`/`pagado` (E-059) | DELETE j | Se omite j. Hay que **cancelar el manual nuevo de j** para no cobrar dos veces | UNIT | P0 | parcial: `test_cancel_selected_e059_is_skipped` (falta cancelar el manual) |
| GB-RA-12 | `/charges` falla antes de empezar | Reasignar | No se crea nada | UNIT | P1 | cubierto por `test_error_del_listado_impide_crear` |
| GB-RA-13 | Doble clic o dos solicitudes simultáneas sobre la misma suscripción | Ejecutar ambas | Lock por suscripción (advisory lock o una única operación activa). La segunda recibe 409 o espera. Nunca dos lotes intercalados (el dedupe por listado no protege una carrera) | UNIT (concurrencia) | P0 | a verificar |
| GB-RA-14 | Misma reasignación ejecutada dos veces seguidas | Reintento | Idempotente: el segundo adopta y no duplica | UNIT | P1 | parcial: `test_reassign_dos_veces_es_idempotente` |
| GB-RA-15 | El job diario procesa la suscripción en el mismo momento | Reasignación | Mismo lock que RA-13; el job salta o espera | UNIT | P0 | a verificar |
| GB-RA-16 | `charge_day` 5 → 20 (pedido del socio) | Cambio de fecha | Actualiza `charge_day`. Por cada mes del horizonte: crea el cargo del día 20 y después cancela el del 5. Mismo orden seguro y compensación que RA-07 | UNIT | P0 | a verificar |
| GB-RA-17 | Hoy día 10; `charge_day` 25 → 5; M0 tiene pendiente el 25 | Cambio de fecha | M0 conserva su cargo del 25 (no se mueve a una fecha pasada ni se cobra dos veces). Los meses siguientes pasan al día 5 | UNIT | P1 | a verificar |
| GB-RA-18 | Cambio de fecha y reasignación pedidos a la vez | Ejecutar ambos | Se serializan (lock). El resultado combina fecha nueva y monto nuevo, con un pendiente por mes | UNIT | P1 | a verificar |
| GB-RA-19 | Reasignación el mismo día de cobro de M0: el automático pasa a `procesando` en medio del lote | Reasignar | M0 cubierto con el monto viejo. Si el manual de M0 ya se creó, se cancela (ver RA-11) | UNIT | P0 | a verificar |
| GB-RA-20 | Cargo `procesando` en el mes a reemplazar | Reasignar | No se cancela ni se crea en ese mes | UNIT | P0 | a verificar (= CO-06) |
| GB-RA-21 | Cargo `rechazado` con reintento automático en curso en M0 | Reasignar | No se crea manual para M0 | UNIT | P1 | a verificar (= CO-08) |
| GB-RA-22 | Suscripción cancelada entre la aprobación y la ejecución | Ejecutar | El primer POST responde E-060. No se cancela nada. Solicitud "no ejecutable" | UNIT | P0 | a verificar |
| GB-RA-23 | Bandera `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` apagada | Reasignar | Bloqueado sin llamar a VP (422) | UNIT | P0 | cubierto por `test_flag_off_blocks_fixed_or_unknown_plan_without_provider_call` y `test_route_reassign_and_create_422_when_flag_off` |
| GB-RA-24 | `dry_run` | Reasignar | Devuelve el plan (12 creaciones y N cancelaciones) sin `write_run` ni escrituras | UNIT | P0 | parcial: `test_reassign_dry_run_does_not_write` |
| GB-RA-25 | Lote masivo (p. ej. 500 suscripciones) | Ejecutar | Pausa entre llamadas. Cada suscripción falla de forma aislada. Reporte por suscripción. Reintento solo de las fallidas | CONTRATO + PILOTO | P1 | a verificar |
| GB-RA-26 | Recién reasignado; aún no hay cobro nuevo | Ver ficha y KPI | `monto_vigente` sigue en el viejo hasta el primer `pagado` nuevo. La UI muestra además el "monto programado" | UNIT | P1 | a verificar |

## 4. Ventana de 31 días y job de reposición

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-JB-01 | Día normal; M0+12 sin cargo gestionado | Job | Crea el manual de M0+12 y después cancela el automático de ese mes, si existe (CO-15) | UNIT | P0 | a verificar |
| GB-JB-02 | M0+12 ya tiene manual (segunda corrida del día) | Job | No-op (registro propio + listado) | UNIT | P0 | a verificar |
| GB-JB-03 | Fecha de M0 hace 1 día; sin `pagado`/`procesando`/`rechazado` | Job | Crea cargo con fecha de mañana | UNIT | P0 | a verificar |
| GB-JB-04 | Hace 15 días, igual | Job | Igual que JB-03 | UNIT | P0 | a verificar |
| GB-JB-05 | Hace **31** días (borde) | Job | Crea con fecha de mañana (borde inclusivo) | UNIT | P0 | a verificar |
| GB-JB-06 | Hace **32** días | Job | No cobra. Marca el mes para revisión manual | UNIT | P0 | a verificar |
| GB-JB-07 | Hace 1 día, pero el mes tiene un `rechazado` | Job | No crea (mes cubierto) | UNIT | P0 | a verificar |
| GB-JB-08 | Mes con un `pendiente` **vencido** (VP no lo intentó, `charge_date < hoy-2`) | Job | Un pendiente vencido no cubre el mes. Crea uno con fecha de mañana y **cancela el vencido** (riesgo: VP lo intenta tarde y cobra dos veces). Medir en sandbox si VP cobra pendientes vencidos | UNIT + CONTRATO | P0 | a verificar |
| GB-JB-09 | M-1 (a menos de 31 días) y M0 sin cubrir, ambas fechas pasadas | Job | Definir: crear ambos con fecha de mañana (dos cobros el mismo día, posible E-087) o espaciarlos (M-1 mañana, M0 pasado mañana). Propuesta: espaciar | UNIT | P1 | a verificar (decisión abierta) |
| GB-JB-10 | El job no corrió durante 5 días | Primera corrida al volver | Repone M0+12 de cada día perdido (idempotente) y aplica la ventana. Nada se pierde si son 31 días o menos | UNIT | P0 | a verificar |
| GB-JB-11 | El job estuvo caído más de 31 días | Corrida | Los meses fuera de la ventana van a revisión manual. No hay cobro retroactivo | UNIT | P1 | a verificar |
| GB-JB-12 | El job se cae a mitad de corrida | Reinicio | Retoma. Lo ya procesado es no-op. Ningún duplicado (adopción por `internal_code`) | UNIT | P0 | a verificar |
| GB-JB-13 | Límite de escrituras por corrida (p. ej. N=200) alcanzado | Corrida | Se detiene de forma ordenada. El resto queda para la siguiente. El reporte dice cuántas quedan | UNIT | P1 | a verificar |
| GB-JB-14 | VP responde 429, 5xx o timeout | Corrida | Backoff. Nunca reintenta un POST a ciegas: primero lista y adopta. No se observó 429 a ~3 req/s (VP-C16); falta medir lotes grandes | UNIT + CONTRATO | P0 | a verificar (VP-C16 medido solo en ráfaga corta) |
| GB-JB-15 | Error de negocio con HTTP 200 NOK | Corrida | Se trata como error, con el código E-nnn en el `write_run` | UNIT | P1 | cubierto por `test_nok_con_http_200_lanza_error_con_codigo` y `test_sync_con_nok_falla_el_run_con_el_codigo` |
| GB-JB-16 | La suscripción se cancela entre el listado y el POST | Corrida | E-060. Se marca como no gestionada, sin reintentos | UNIT | P0 | a verificar |
| GB-JB-17 | Suscripción cancelada desde el panel de VP | Sync y job | El sync la ve CANCELADA y el job deja de gestionarla. Verificar que VP canceló los manuales pendientes | CONTRATO | P0 | a verificar (= CO-20) |
| GB-JB-18 | `dry_run` del job | Corrida | Lista lo que crearía o cancelaría, sin `write_run` ni escrituras | UNIT | P0 | a verificar |
| GB-JB-19 | `VIRTUALPOS_WRITES_ENABLED` apagada, bandera de plan fijo apagada o bandera de facturación gestionada apagada | Corrida | No escribe. Registra "skipped" con el motivo | UNIT | P0 | parcial: `test_cancel_future_blocked_when_writes_disabled` |
| GB-JB-20 | Allowlist del piloto | Corrida | Solo procesa las suscripciones incluidas | UNIT | P0 | a verificar |
| GB-JB-21 | El sync corre a la vez que el job | — | El sync no pisa el registro de cargos gestionados ni `charge_day` | UNIT | P1 | a verificar |
| GB-JB-22 | Corrida cerca de medianoche | Cálculo de "hoy" y "mañana" | Usar la fecha de America/Santiago, no UTC (`vp_current_amount` usa `datetime.now(UTC)`). Nunca E-078 por desfase horario | UNIT | P1 | a verificar |
| GB-JB-23 | La suscripción termina (calendario agotado sin renovación) | Corrida | Deja de gestionarla (CO-18) | UNIT | P1 | a verificar |
| GB-JB-24 | Suscripciones en `virtualpos1` y `virtualpos2` | Corrida | Cada escritura va a su cuenta (`platform` correcto) | UNIT | P1 | a verificar |

## 5. Aprobaciones (maker-checker)

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-AP-01 | Usuario con permisos de solicitar y aprobar (no admin) | Aprueba su propia solicitud | 403 | UNIT | P0 | a verificar |
| GB-AP-02 | Admin; cambio individual pequeño (bajo el umbral) | Aprueba lo propio | Permitido. Auditado como "autoaprobación admin" | UNIT | P1 | a verificar |
| GB-AP-03 | Admin; cambio grande o masivo | Aprueba lo propio | 403 | UNIT | P0 | a verificar |
| GB-AP-04 | Usuario sin permiso de aprobar | Aprueba | 403 | UNIT | P0 | a verificar |
| GB-AP-05 | Usuario sin permiso de solicitar | Crea una solicitud | 403 | UNIT | P0 | parcial: `test_routes_permissions_and_csrf` |
| GB-AP-06 | Individual, variación ≤ 50 % | 1 aprobación | Se ejecuta | UNIT | P0 | a verificar |
| GB-AP-07 | Masivo de 21 suscripciones | 1 aprobación | Queda en "1/2". Ejecuta con un segundo aprobador **distinto** del primero y del solicitante | UNIT | P0 | a verificar |
| GB-AP-08 | Masivo de 20 exactas (borde) | 1 aprobación | Se ejecuta | UNIT | P1 | a verificar |
| GB-AP-09 | Variación de 50 % exacto y de 50,1 % | Aprobación | 50 % → 1 aprobación; 50,1 % → 2. La base es el monto programado (o `monto_vigente`) al solicitar. Subidas y bajadas se miden en valor absoluto | UNIT | P0 | a verificar |
| GB-AP-10 | Solicitud pendiente más allá del plazo (p. ej. 7 días) | Aprobar | Expirada; no ejecutable | UNIT | P1 | a verificar |
| GB-AP-11 | Solicitud pendiente | Rechazar | Estado "rechazada" con motivo obligatorio. No ejecuta | UNIT | P1 | a verificar |
| GB-AP-12 | Ya hay una solicitud pendiente para la misma suscripción | Nueva solicitud | 409 (o reemplazo explícito de la anterior) | UNIT | P1 | a verificar |
| GB-AP-13 | Entre la solicitud y la ejecución cambia el estado (CANCELADA, otro cambio aplicado, `procesando`) | Ejecutar | Se revalida al ejecutar. Si la suscripción no está ACTIVA, no se ejecuta. Si la variación cambió de categoría, pide reaprobación | UNIT | P0 | a verificar |
| GB-AP-14 | Dos aprobadores aprueban a la vez | Aprobar | Una sola ejecución (transición atómica de estado) | UNIT | P0 | a verificar |
| GB-AP-15 | Se cambian los umbrales con solicitudes pendientes | Aprobar | Rigen los umbrales guardados al solicitar (propuesta) | UNIT | P2 | a verificar |
| GB-AP-16 | Cualquier solicitud | Ciclo completo | Auditoría inmutable: solicitante, aprobadores, fechas, monto antes y después, IDs de `write_run`, resultado. Sin PII innecesaria | UNIT | P0 | a verificar |
| GB-AP-17 | Masivo aprobado con fallos parciales | Reintento | Solo se reintentan las fallidas, sin nueva aprobación, mientras la aprobación siga vigente | UNIT | P1 | a verificar |
| GB-AP-18 | Cambio de `charge_day` | Solicitud | Definir si requiere aprobación (propuesta: 1 aprobación o autoservicio verificado) | UNIT | P2 | a verificar (decisión abierta) |
| GB-AP-19 | Rutas de escritura | Sin CSRF, sin sesión o con rol incorrecto | 403/401 | UNIT | P1 | parcial: `test_routes_permissions_and_csrf` |

## 6. Consistencia CRM–proveedor

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-CS-01 | Reasignada y sin cobro nuevo aún | Ficha, KPI MRR | `monto_vigente` = monto viejo. El KPI sigue al último cobro. El "monto programado" se muestra aparte | UNIT | P1 | parcial: `test_kpi_mrr_sigue_el_ultimo_cobro_no_el_plan` |
| GB-CS-02 | Un pendiente del horizonte con monto distinto del programado | Control diario | Alerta de desfase con suscripción y mes | UNIT | P0 | a verificar |
| GB-CS-03 | Un mes con **dos** pendientes | Control diario (D-3 antes de `charge_date`) | Alerta P0 y bloqueo de la suscripción hasta resolver | UNIT | P0 | a verificar |
| GB-CS-04 | Un mes del horizonte sin pendiente y no cubierto ni pausado | Control diario | El job lo repone (ventana) o alerta | UNIT | P0 | a verificar |
| GB-CS-05 | Cargos creados por el CRM | Sync desde el listado de suscripciones | Se reconocen por `charge_id` en el registro propio (el listado no trae `internal_code`, VP-C28). Sin duplicados en `vp_charges`/`charges` | UNIT | P0 | a verificar |
| GB-CS-06 | Alguien crea un cargo desde el **panel de VP** en un mes gestionado | Sync | Se detecta "cargo no registrado". No se cancela automáticamente. Alerta de revisión (posible doble cobro) | UNIT | P0 | a verificar |
| GB-CS-07 | Alguien cancela desde el panel un manual del CRM | Sync | Hueco detectado. Alerta. No se repone automáticamente si no hay certeza (puede ser una pausa pedida por otro canal) | UNIT | P1 | a verificar |
| GB-CS-08 | Suscripción cancelada en el panel | Sync | Deja de gestionarse (JB-17) | UNIT | P0 | a verificar |
| GB-CS-09 | `write_run` en `reconciliation_required` | Cola de reconciliación | Aparece en la cola. Bloquea la suscripción. La resolución manual queda trazada | UNIT | P0 | a verificar |
| GB-CS-10 | Cuota `pagado` | Cuadratura (seguimiento-cobros § 5) | `charge.amount == payment.order.amount`. Si difieren, alerta | UNIT | P1 | a verificar (depende de V-2) |
| GB-CS-11 | Dos `pagado` en el mismo mes | Cuadratura | Alerta de doble cobro. La devolución es manual (no hay endpoint de reembolso) | UNIT | P0 | a verificar |
| GB-CS-12 | Dos cargos `pagado` el mismo día (duplicado) | `monto_vigente` | Desempate determinista por `external_id` | UNIT | P2 | cubierto por `test_helper_ultimo_pagado_procesando_futuros_plan_y_desempate` |
| GB-CS-13 | Tablas `vp_*` y centralizadas | `load_monto_vigente(family=vp/crm)` | Mismo resultado en ambas familias para las suscripciones gestionadas | UNIT | P2 | a verificar |

## 7. Migración y piloto

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-PI-01 | Escenarios P0 de CONTRATO/MANUAL resueltos (CO-01, 03, 04, 05, 15, 19, 20; RZ-06, 07, 19; JB-08) | Puerta de entrada | No se activa nada en producción hasta tener esas respuestas. Bandera de plan fijo encendida **solo** para la allowlist | revisión | P0 | a verificar |
| GB-PI-02 | Selección | Elegir 5–10 suscripciones de producción | Voluntarios internos con consentimiento y tarjeta propia. Montos bajos. Días de cobro variados (05, 15, 28/30 y al menos uno de día 0). Sin racha, sin `procesando`, sin `reconciliation_required` | PILOTO | P0 | a verificar |
| GB-PI-03 | Fase 1: 1 suscripción | Reasignar solo M0+1 (1 mes) | Un único cobro real con el monto nuevo. Sync y `monto_vigente` correctos | PILOTO | P0 | a verificar |
| GB-PI-04 | Fase 2: las 5–10 | Horizonte de 12 meses, job activo con límite bajo | 2 ciclos de cobro completos, sin incidentes | PILOTO | P0 | a verificar |
| GB-PI-05 | Tras cada ciclo | Criterios de éxito | 100 % de meses con exactamente 1 cobro y monto correcto. 0 dobles cobros. 0 meses sin cargo. 0 `reconciliation_required` abiertos más de 24 h. Sync y cuadratura en verde | PILOTO | P0 | a verificar |
| GB-PI-06 | Cualquier ciclo | Criterios de abort | Abortar ante cualquier doble cobro, monto incorrecto, mes sin cargo, E-113/E-087 en producción, manual no cobrado en su fecha o dos pendientes en un mes a menos de 3 días de su fecha | PILOTO | P0 | a verificar |
| GB-PI-07 | Abort | Reversión | No se puede volver al automático en los meses cuyos automáticos se cancelaron. Procedimiento: (1) apagar el job para esas suscripciones; (2) los manuales ya creados siguen cobrando; si el monto era el problema, crear manuales con el monto anterior (orden seguro); (3) desde M0+12 siguen los automáticos originales, siempre que **nunca** se haya usado el DELETE plural (CO-16). Así la gestión manual tiene una "cola" máxima de 12 meses. Alternativa: suscripción nueva con re-enrolamiento | PILOTO + UNIT (script de reversión) | P0 | a verificar |
| GB-PI-08 | Doble cobro detectado | Devolución | Payout o gestión manual (sin endpoint de reembolso). Comunicación al socio | MANUAL | P1 | a verificar |
| GB-PI-09 | Escalado | 50 → 500 → todas, por lotes | Avanzar de etapa solo si la anterior cumple PI-05. Medir rate limits reales (RA-25, JB-14) | PILOTO | P1 | a verificar |
| GB-PI-10 | Cambio de monto | Aviso al socio | Notificación previa con el monto nuevo y la fecha | MANUAL | P2 | a verificar |

---

## Hallazgos de diseño detectados al escribir los escenarios

1. **El DELETE plural es incompatible con la opción A** (CO-16). `cancel_future_charges` sin `charge_ids` cancela todo: manuales y automáticos fuera del horizonte, que son la red de seguridad si el job falla. Hay que prohibirlo en suscripciones gestionadas.
2. **Los automáticos fuera del horizonte siguen vivos** (CO-14/15). El job tiene que cancelar el automático de M0+12 cada día. A cambio, si el CRM se detiene, VP sigue cobrando el monto viejo desde M0+12, así que el socio no queda sin cobro.
3. **El listado de suscripciones no trae `internal_code`** (VP-C28). El sync masivo no distingue manuales de automáticos. Hace falta un registro propio de `charge_id` creados, o leer `/charges` por suscripción (N+1 sobre 6000).
4. **E-087 ("máximo de cargos mensuales")** es una respuesta plausible a la duda de CO-01. Si aparece, el orden "crear primero" falla en todos los meses con automático.
5. **Un pendiente vencido** no cubre el mes, pero VP podría cobrarlo tarde (JB-08). Hay que cancelarlo cuando se repone.
6. **La fecha de "hoy" está en UTC** en `vp_current_amount.py`. El job debe usar la hora de Chile (JB-22).
7. **El dedupe por listado no protege una carrera** entre dos procesos (RA-13). Hace falta un lock por suscripción.

## (a) Escenarios que requieren una suscripción de prueba en sandbox

Ambiente: sandbox, cuenta 1. Escrituras activadas solo por variables de proceso, como en `tests_contract/README.md`. Al terminar cada prueba, cancelar los cargos de prueba. Advertencia: V-2 a V-4 siguen pendientes porque requieren "tarjeta y cobro real". Antes de las recetas MANUAL hay que confirmar que el sandbox **ejecuta** cobros en la fecha programada (CT-00).

| Prio | Nombre sugerido | Receta | Escenarios |
| --- | --- | --- | --- |
| P0 | CT-00-COBRO | Plan `MONTO_FIJO`, día `0`, `num_charges` 12, renovación `T`. Enrolar con T1. Crear un manual con fecha de mañana | ¿El sandbox cobra en la fecha? CO-05, RZ-03, RZ-05 |
| P0 | CT-CO-AUTO | Plan `MONTO_FIJO` con el día disponible más cercano a hoy+2 (p. ej. `05`/`28`), `num_charges` 12, renovación `T`, T1. Debe tener al menos 3 automáticos `pendiente` futuros | CO-01, CO-02, CO-03, CO-14, CO-15, RA-01 |
| P0 | CT-CO-DUP | Igual que CT-CO-AUTO, con el **primer automático en 1–2 días**. Crear el manual del mismo mes y **no** cancelar el automático | CO-04 (¿doble cobro?) |
| P0 | CT-CO-NC3 | Plan `MONTO_FIJO`, `num_charges` 3, renovación `F`, T1. Cancelar los 3 automáticos y crear manuales | CO-19, CO-18 |
| P0 | CT-RZ-MC | Plan `MONTO_FIJO`, día `0`, T1. Después `changecard` a T3 y manual con fecha de mañana. Observar 4 días | RZ-06, RZ-07, RZ-19 (T1 → T3) |
| P0 | CT-RZ-SWAP | Como CT-RZ-MC. Tras el rechazo, `changecard` a T1 y `/retry` | RZ-19 (T3 → T1), RZ-20 |
| P0 | CT-CANCEL | Plan `MONTO_FIJO`, T1, 2 manuales `pendiente`. `DELETE /v3/suscription` y luego un POST | CO-20, JB-17 |
| P0 | CT-STALE | Plan `MONTO_FIJO`, T1. Buscar o esperar un automático `pendiente` con fecha pasada; crear el reemplazo con fecha de mañana | JB-08 (¿VP cobra pendientes vencidos?) |
| P1 | CT-CO-NC3R | Plan `MONTO_FIJO`, `num_charges` 3, renovación `T`, T1. Dejar agotar con manuales | CO-17 |
| P1 | CT-DAY30 | Plan `MONTO_FIJO`, día `30`, T1. Manuales con fechas 2027-02-28, 2028-02-29 y 2026-11-30 | CO-24, CO-25 |
| P1 | CT-DAY0 | Plan `MONTO_FIJO`, día `0`, T1 | CO-22, RZ-01 |
| P1 | CT-ENR-REJ | Planes `MONTO_FIJO`; enrolar con T3, T5 y T7 (una suscripción por tarjeta) | RZ-02 |
| P1 | CT-RZ-CANCEL | Como CT-RZ-MC; cancelar la suscripción mientras hay reintentos | RZ-27 |
| P1 | CT-LOTE | 20–30 suscripciones de plan fijo con T1 (reusar las existentes) y ráfaga de POST/DELETE sin pausa | RA-25, JB-14 |
| P2 | CT-TODAY | Plan `MONTO_FIJO`, T1; manual con `charge_date` = hoy | CO-27 |
| P2 | CT-CARDS-OK | Tres suscripciones de plan fijo con T2, T4 y T6; manual con fecha de mañana | RZ-24, RZ-25 |
| P2 | CT-CARDS-REJ | `changecard` a T5 y T7; manual con fecha de mañana | RZ-26 |

## (b) Escenarios que deben convertirse primero en pruebas automáticas con fakes

Orden sugerido: cada bloque es un archivo de test, con un fake de `VirtualPOSClient` que guarda el estado de los cargos.

1. **Orden seguro, compensación y verificación** (`reassign` de horizonte): RA-01, RA-04, RA-07, RA-08, RA-09, RA-10, RA-11, RA-19, CO-11.
2. **Cobertura de mes y estados**: CO-06, CO-07, CO-08, CO-09, RA-20, RA-21, RZ-28.
3. **Ventana de 31 días y fechas**: JB-03 a JB-08, CO-24, CO-26, JB-22, RA-05, RA-17.
4. **Job de reposición**: JB-01, JB-02, JB-10, JB-12, JB-16, JB-18, JB-19, JB-20, CO-15.
5. **Guardas**: CO-16 (DELETE plural prohibido), RA-13 y RA-15 (lock), RA-22, CO-13 y CS-05 (registro propio de `charge_id`).
6. **Racha y recuperador**: RZ-08, RZ-15, RZ-16, RZ-06 (con fake del estado).
7. **Aprobaciones**: AP-01, AP-03, AP-04, AP-07, AP-09, AP-13, AP-14, AP-16.
8. **Controles de consistencia**: CS-02, CS-03, CS-04, CS-06, CS-09, CS-11.
