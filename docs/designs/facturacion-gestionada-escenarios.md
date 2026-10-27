# Facturación gestionada por el CRM (opción A): escenarios de prueba

> Estado: borrador de QA/diseño · Creado: 2026-10-27 · Revisado: 2026-10-28 (corrección de alcance, ver "Decisiones finales") · Alcance: suscripciones VirtualPOS de plan `MONTO_FIJO` (más de 6000; no se pueden cambiar de plan).
> Fuentes: `app/services/write_virtualpos.py` (`create_charge`, `cancel_future_charges`, `reassign_subscription_amount`, `retry_charge`), `app/services/vp_current_amount.py`, `app/integrations/virtualpos/client.py`, `docs/integrations/virtualpos/` (VALIDATION-PLAN.md, resources/sandbox.md, resources/charges.md, resources/subscriptions.md, resources/plans.md, workflows/*), `tests/`, `tests_contract/virtualpos/` y `reports/contract/virtualpos/drift-20261027-122600.md`.
> Este documento no cambia código. Solo lista escenarios y qué resultado espera el diseño ya decidido.

## Decisiones finales (2026-10-28)

Estas decisiones sustituyen a las de la versión anterior (2026-10-27) donde se contradigan.

1. **VirtualPOS sigue creando los cobros mensuales.** Todos los cobros mes a mes de las suscripciones los sigue generando VirtualPOS con su calendario automático. El CRM **no** tiene un proceso que cree cobros para todos los socios. El CRM solo **crea** cobros en dos casos: (a) cuando aplica un cambio aprobado a una suscripción (cambio de monto o de fecha de cobro), o (b) cuando una tarea específica necesita un cobro puntual. En todo lo demás el CRM solo lee y sincroniza, **reintenta** cobros rechazados (función existente `retry_charge`, que no se reintenta sola ante un timeout) y gestiona pendientes (cancelar o reemplazar) dentro de un cambio aprobado.
2. **Horizonte de 12 meses solo al aplicar un cambio.** Al aplicar un cambio a una suscripción concreta se crean los cobros de los próximos 12 meses y se cancelan los automáticos **solo** dentro de ese horizonte. Esa suscripción pasa a ser una "suscripción con calendario modificado". El job diario de reposición masiva **se elimina** como creador de cobros. En su lugar hay un **chequeo diario de solo lectura** (no escribe en el proveedor) que busca suscripciones con calendario modificado cuyo último cobro programado por el CRM esté a menos de N días (propuesta: N = 60) y genera una tarea o alerta "renovar calendario". Una persona la aprueba y la aplica con el mismo flujo de solicitud y aprobación.
3. **Rechazos: el CRM no crea cobros ni suspende.** Ante un rechazo el CRM solo reintenta (`retry_charge`) y gestiona el caso. La marca "racha de rechazos" (3 o más seguidos) pasa a ser una ayuda **opcional** de solo lectura en el recuperador, no una regla de ningún proceso automático.
4. **Ventana de 31 días solo dentro de un cambio.** Ya no es un proceso de fondo. Al aplicar un cambio: si la fecha del mes actual pasó hace 31 días o menos y ese mes no tiene cobro `pagado`/`procesando`/`rechazado`, se crea el cobro de reemplazo con fecha de mañana. Si pasó hace más de 31 días, no se crea y el mes queda marcado para revisión manual dentro de la misma solicitud.
5. **Aprobaciones.** Por ahora **solo el rol admin aprueba** (jefatura aún no está capacitada). Habrá una **configuración en el panel de administración** (política editable) donde se define quién puede aprobar (roles y/o usuarios) y si el solicitante puede aprobar lo propio. La **autoaprobación queda ACTIVADA** por ahora, porque hoy el admin es quien solicita y aprueba; queda auditada. Habrá una **interfaz de solicitudes** para aprobadores: bandeja de pendientes, vista previa de los cargos que se crearán y cancelarán, aprobar o rechazar con comentario e historial. La doble aprobación por umbral queda como opción configurable y **APAGADA** por ahora.

**Qué cambió respecto de la versión anterior (2026-10-27):**

| Tema | Antes | Ahora |
| --- | --- | --- |
| Creación de cobros | El CRM, mediante un job diario, creaba el cobro de cada mes de cada suscripción gestionada | VirtualPOS crea los cobros. El CRM crea solo al aplicar un cambio aprobado o por una tarea específica |
| Job diario | Reponía M0+12 cada día (creaba el manual y cancelaba el automático) | Eliminado como creador. Queda un chequeo diario de solo lectura que genera tareas "renovar calendario" |
| Horizonte de 12 meses | Se mantenía rodando con el job | Se fija una vez por cambio; al acercarse su fin se renueva con una nueva solicitud aprobada |
| Rechazos | El job seguía creando el mes siguiente; racha de 3 marcaba al socio | El CRM no crea nada por rechazos; reintenta (manual, `retry_charge`) y gestiona. Racha: ayuda opcional de solo lectura |
| Ventana de 31 días | Proceso de fondo del job | Solo se evalúa al aplicar un cambio |
| Aprobaciones | Permisos solicitar/aprobar; nadie aprueba lo propio salvo admin en cambios pequeños; doble aprobación para masivos o variación > 50 % | Solo admin aprueba (configurable); autoaprobación activada y auditada; doble aprobación configurable y apagada; bandeja, vista previa, comentario e historial |
| Escenarios | 148 | 175 vigentes, 13 descartados (se conservan con la marca "Descartado (decisión 2026-10-28)"), 40 nuevos |

## 0. Resumen del diseño que se prueba

| Regla | Decisión |
| --- | --- |
| Quién crea los cobros | VirtualPOS, con su calendario automático. El CRM solo crea cobros al aplicar un cambio aprobado (monto o fecha) o por una tarea específica aprobada. |
| Monto de la suscripción | `monto_vigente` = último cargo `pagado`/`procesando` con `charge_date <= hoy` (`vp_current_amount.py`). |
| Aplicar un cambio de monto | Dentro del horizonte (12 meses): **crear primero** un cargo por mes, **cancelar** los automáticos (solo los del horizonte) si se crearon todos, **compensar** si falla a la mitad y **verificar al final** que haya exactamente un `pendiente` por mes con el monto nuevo. Los automáticos posteriores al horizonte se dejan con el monto antiguo (red de seguridad). La suscripción queda como "calendario modificado". |
| Renovación del calendario | Chequeo diario **de solo lectura**: si el último cobro programado por el CRM de una suscripción con calendario modificado está a menos de N días (N = 60, configurable), se genera una tarea "renovar calendario". Se aplica solo tras aprobación, con el mismo flujo de un cambio. |
| Día de cobro | `charge_day` (dato propio) = día del último cargo. Cambiarlo es un cambio explícito, con aprobación, que reprograma los pendientes del horizonte. |
| Rechazos | El CRM **no crea cobros ni suspende**. Reintenta con `retry_charge` (manual, sin reintento automático ante timeout) y gestiona en el recuperador. "Racha de rechazos" (3 o más seguidos) = ayuda opcional de solo lectura. |
| Ventana de 31 días | Solo al aplicar un cambio. Si la fecha del mes actual pasó hace 31 días o menos y ese mes no tiene cargo `pagado`/`procesando`/`rechazado`, se crea uno con fecha de mañana (VirtualPOS exige `charge_date >= hoy`, E-078). Si pasó hace más de 31 días, no se cobra y el mes queda para revisión manual dentro de la solicitud. |
| Aprobaciones | Configuración editable en el panel de administración: aprobadores (roles y/o usuarios; hoy solo rol admin), autoaprobación (hoy activada, auditada) y doble aprobación por umbral (hoy apagada). Bandeja de solicitudes con vista previa, aprobar/rechazar con comentario e historial. |

**Hechos medidos en sandbox (2026-10-27):** `POST /v3/charge` aceptado en plan fijo (VP-C05). Los errores llegan con HTTP 200 y cuerpo NOK (VP-C11, C12, C21, C27). `internal_code` no es idempotente (VP-C07). Reutilizar un `internal_code` tras cancelar se acepta (VP-C29). DELETE plural cancela todos los pendientes. Los filtros de fecha de `/charges` se ignoran (VP-C26). El listado de suscripciones trae el `charge_program` completo (VP-C01), pero **sin `internal_code`**, que solo aparece en `/charges` y en el detalle (VP-C28). No hubo 429 con ~3 req/s (VP-C16).

**Convenciones.** Cómo se prueba: `UNIT` (pytest con fakes del proveedor) · `CONTRATO` (sandbox, `tests_contract/`) · `MANUAL` (sandbox con tarjeta y espera de la fecha de cobro) · `PILOTO` (producción, suscripciones de prueba). Estado: `a verificar` · `cubierto por test X` · `medido en sandbox` · `Descartado (decisión 2026-10-28)` (se conserva la fila para no reutilizar el ID). "Parcial" quiere decir que hoy un test cubre la versión de **un mes** (`reassign_subscription_amount` actual), no la del horizonte de 12 meses. "Aplicar cambio" = ejecución de una solicitud aprobada (cambio de monto, de fecha o renovación del calendario).

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
| GB-CO-06 | El automático de M está `procesando` | Aplicar cambio sobre M | No se crea manual ni se cancela nada. M queda cubierto con el monto viejo; el monto nuevo rige desde M+1 | UNIT | P0 | a verificar |
| GB-CO-07 | El automático de M está `pagado` | Aplicar cambio sobre M | Igual que CO-06: M cubierto, sin escrituras | UNIT | P0 | a verificar |
| GB-CO-08 | El automático de M está `rechazado` (con o sin reintentos de VP en curso) | Aplicar cambio sobre M | M se considera cubierto. No se crea manual (evita cobrar dos veces si un reintento se aprueba). La recuperación va por `retry_charge` o `changecard` | UNIT | P0 | a verificar |
| GB-CO-09 | M sin cargos (automático cancelado por una **pausa registrada**) | Aplicar cambio | El cambio no crea M: la pausa explícita manda. La vista previa lo muestra como "mes en pausa". Sin pausa registrada, rige la ventana de 31 días (JB-03 a JB-06) | UNIT | P0 | a verificar |
| GB-CO-10 | M solo tiene un cargo `cancelado` con el `internal_code` del CRM | Aplicar cambio que crea M con el mismo `internal_code` | VP acepta el POST (VP-C29). El CRM no adopta el cancelado y crea uno nuevo | CONTRATO + UNIT | P1 | medido en sandbox (VP-C29); cubierto por `test_crea_si_solo_hay_cancelado_con_ese_codigo` |
| GB-CO-11 | Orden inverso (cancelar el automático y después crear) y el POST falla | — | Prohibido por diseño: el socio quedaría sin cargo del mes. Test de guarda: ningún DELETE antes de que todos los POST terminen bien | UNIT | P0 | parcial: `test_reassign_post_failure_cancels_nothing` |
| GB-CO-12 | Ya existe un manual `pendiente` con el `internal_code` X | Segundo intento con X (reintento o doble clic) | VP crearía otro (VP-C07). El CRM lista `/charges`, encuentra X y lo adopta sin POST | UNIT | P0 | medido en sandbox (VP-C07); cubierto por `test_adopta_pendiente_con_mismo_codigo_sin_post` |
| GB-CO-13 | Cargos manuales creados por el CRM | Sync diario desde `GET /v3/suscriptions` | `charge_program[]` no trae `internal_code` (VP-C28). El CRM debe reconocer sus cargos por `charge_id` en un **registro propio** y no por `internal_code` del listado | UNIT | P0 | medido en sandbox (VP-C28); diseño a verificar |
| GB-CO-14 | Automáticos programados más allá del horizonte (hay suscripciones con 120–300 cargos, hasta 2031) | Aplicar cambio (o renovación) | Solo se cancelan los automáticos de M0..M0+11. Los de M0+12 en adelante siguen `pendiente` con el monto viejo (red de seguridad, ver Hallazgo 2) | UNIT | P0 | a verificar |
| GB-CO-15 | Como CO-14, al día siguiente | Job repone M0+12 | — | — | — | Descartado (decisión 2026-10-28): ya no existe job de reposición. La continuidad la cubren el chequeo de renovación (JB-25) y la renovación aprobada (JB-30) |
| GB-CO-16 | Suscripción con calendario modificado | Alguien llama a `cancel_future_charges` **sin** `charge_ids` (usa el DELETE plural) | Debe bloquearse en suscripciones con calendario modificado: el plural cancela todo, incluidos los manuales y los automáticos fuera del horizonte (la red de seguridad). Hoy el código usa el plural cuando `charge_ids` es None | UNIT | P0 | a verificar |
| GB-CO-17 | Plan `num_charges` corto (p. ej. 3), `automatic_renewal=T` | Se cancelan automáticos y se crean manuales; se agota el calendario | Medir si VP renueva el bloque, si cuenta los manuales y los cancelados, y si genera automáticos nuevos que se superpongan con los manuales (posible duplicado) | CONTRATO + MANUAL | P1 | a verificar |
| GB-CO-18 | `num_charges` corto, `automatic_renewal=F` | Se agota el calendario | Medir el estado final de la suscripción y si `POST /v3/charge` sigue aceptándose (o E-060). Si deja de estar ACTIVA, el CRM deja de ofrecer cambios y el chequeo de renovación deja de alertar | CONTRATO | P1 | a verificar |
| GB-CO-19 | Plan fijo con N automáticos | Se cancelan los N del horizonte | Medir si los cancelados "consumen" `num_charges` y terminan la suscripción antes de tiempo (los manuales responderían E-060) | CONTRATO | P0 | a verificar |
| GB-CO-20 | Suscripción CANCELADA con manuales `pendiente` | Baja (`DELETE /v3/suscription`) o ejecución de una solicitud pendiente | VP pasa los manuales a `cancelado` (verificar). Un POST posterior da E-060 y el CRM no reintenta | CONTRATO | P0 | a verificar |
| GB-CO-21 | Suscripción FINALIZADA, SUSCRIPCION_FALLIDA o SUSCRIBIENDO | Solicitud de cambio o chequeo de renovación | Nunca se escribe. La solicitud se rechaza al crearla o al ejecutarla; el chequeo no genera tarea | UNIT | P1 | a verificar |
| GB-CO-22 | Plan con `fixed_amount_day_charge="0"` (cobro al suscribir) | Primer cambio sobre la suscripción | `charge_day` = día del último cargo. Si no hay ningún pagado, día de alta. Nunca 0 | UNIT | P1 | a verificar |
| GB-CO-23 | Plan con día 05 pero `charge_day=20` (cambiado a pedido) | Aplicar cambio de monto | Usa 20 (dato guardado), no el día del plan | UNIT | P1 | a verificar |
| GB-CO-24 | `charge_day` 29, 30 o 31 | Aplicar cambio que cruza meses de 30 días, febrero 2027 (28) y febrero 2028 (29, bisiesto) | Se usa el último día del mes. Exactamente un cargo por mes; ningún mes sin cargo ni con dos | UNIT | P0 | a verificar |
| GB-CO-25 | Día de cobro no estándar para VP (p. ej. 31, 29 o 07) | POST manual con ese día | Medir si VP acepta cualquier día (los planes solo ofrecen 01/05/10/15/20/25/28/30) | CONTRATO | P1 | a verificar |
| GB-CO-26 | M0 = diciembre | Aplicar cambio de 12 meses | Meses 2026-12..2027-11 bien calculados. El `internal_code` usa YYYYMM y no colisiona entre años | UNIT | P1 | a verificar |
| GB-CO-27 | `charge_date = hoy` (E-078 permite "igual o mayor a hoy") | POST con fecha de hoy | Medir si VP lo acepta y si lo cobra el mismo día o lo deja vencido. Por eso el diseño usa mañana | CONTRATO + MANUAL | P2 | a verificar |
| GB-CO-28 | Monto 0, negativo o con decimales | Solicitud de cambio de monto | El CRM rechaza antes de llamar a VP (E-055 como respaldo) | UNIT | P2 | a verificar |

## 2. Rechazos y tarjetas

Regla de esta sección: **ningún rechazo hace que el CRM cree un cobro ni suspenda la suscripción**. VirtualPOS sigue con su calendario (y sus reintentos automáticos, si los hace). El CRM solo sincroniza, reintenta con `retry_charge` y gestiona el caso en el recuperador.

| ID | Precondiciones | Acción / evento | Resultado esperado en el CRM | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-RZ-01 | Plan fijo | Enrolamiento con T1, T2, T4 o T6 | Suscripción ACTIVA con `charge_program`. El CRM calcula `charge_day` y la deja elegible para cambios | MANUAL | P1 | a verificar |
| GB-RZ-02 | Plan fijo | Enrolamiento con T3, T5 o T7 | SUSCRIPCION_FALLIDA o sin activar (sandbox.md caso 4, "a verificar"). El CRM no acepta cambios sobre ella | MANUAL | P1 | a verificar |
| GB-RZ-03 | Suscripción ACTIVA (T1), plan día 0 | Primer cobro automático | `pagado`. `monto_vigente` = ese monto. Racha 0 | MANUAL | P1 | a verificar |
| GB-RZ-04 | ACTIVA con T1, después `changecard` a T3 | Primer cobro automático | `rechazado`. Racha 1. Aparece en el recuperador. El automático de M+1 sigue programado por VP; el CRM **no** crea nada | MANUAL | P1 | a verificar |
| GB-RZ-05 | Manual del CRM `pendiente` con T1 | Fecha de cobro | `pagado`. El sync actualiza el estado. `monto_vigente` = monto nuevo. Racha 0 | MANUAL | P0 | a verificar (= CO-05) |
| GB-RZ-06 | Manual `pendiente`, tarjeta cambiada a T3 | Fecha de cobro | `rechazado`. Racha +1. Visible en el recuperador. Se registra el motivo (`/attempts`). El cargo del mes siguiente es el que ya estaba programado (manual del horizonte o automático); el CRM **no** crea uno nuevo | MANUAL | P0 | a verificar |
| GB-RZ-07 | Como RZ-06 | Pasan los días +1..+3 | Medir si VP hace reintentos automáticos (1/2/3) sobre un cargo **manual** como lo hace con el automático, y si cada reintento crea un Payment nuevo (V-4) | MANUAL | P0 | a verificar |
| GB-RZ-08 | Cargo rechazado; reintentos automáticos 1, 2 y 3 rechazados | Sync | La racha (ayuda opcional) cuenta **meses** (cargos con rechazo definitivo), no intentos: +1 en total | UNIT | P1 | a verificar |
| GB-RZ-09 | Cargo rechazado; el reintento automático 2 se aprueba | Sync | `pagado`. La racha vuelve a 0. `ChargeRecovery` se cierra como recuperado | UNIT | P1 | parcial: `test_reconcile_charge_recoveries_closes_paid_and_rejected_cycles` |
| GB-RZ-10 | Rechazo con código transitorio (`-2`, `-10`) | `retry_charge` manual desde el CRM | Decisión REINTENTAR. Un solo GET (sin reintento HTTP). `write_run` completed. `ChargeRecovery` con cierre a +4 días | UNIT | P1 | a verificar (clasificador sin test directo) |
| GB-RZ-11 | Rechazo de tarjeta (`-1`, `-4`, `-7`, `-8`, `-11`, …) o palabras "vencid"/"bloquead" | `retry_charge` manual | `RetryBlockedError`, `write_run` blocked y se propone el link `changecard` | UNIT | P1 | parcial: `test_needs_card_change_classifies_card_and_blocked_account_rejections` |
| GB-RZ-12 | Rechazo `-6` o `-3` ya reintentado una vez | Segundo `retry_charge` | Decisión CAMBIO_TARJETA | UNIT | P2 | a verificar |
| GB-RZ-13 | Rechazo por límite del comercio (`-1003`, `-1009`, …) | `retry_charge` o sync | DIFERIR y alerta a finanzas. **Decidir** si cuenta para la racha del socio (propuesta: no) | UNIT | P1 | a verificar (decisión abierta) |
| GB-RZ-14 | Cargo que no cumple condiciones | `retry_charge` responde E-081 (HTTP 200 NOK) | `write_run` failed y queda para revisión MANUAL | UNIT | P2 | parcial: `test_retry_charge_nok_marca_failed` |
| GB-RZ-15 | 3 meses seguidos rechazados | Sync del 3.º rechazo | Si la ayuda está activa, el recuperador muestra la marca "racha de rechazos" (solo lectura). **No** suspende, **no** crea cobros ni cambia nada en VP | UNIT | P1 | a verificar |
| GB-RZ-16 | Racha 2 y luego un mes pagado | Sync | Racha 0. Si tenía la marca, se quita | UNIT | P1 | a verificar |
| GB-RZ-17 | Rechazado, mes en pausa registrada, rechazado | Sync | La pausa no corta la racha ni suma (propuesta) | UNIT | P2 | a verificar (decisión abierta; baja prioridad porque la racha es opcional) |
| GB-RZ-18 | Racha de 6 o más meses | Sync y recuperador | El CRM no crea ni suspende; VP sigue con su calendario. Alerta escalada en el recuperador. Riesgo: VP/marca devuelve `-11` (límite de rechazos de la marca); vigilar y no insistir con `retry_charge` | UNIT | P1 | a verificar |
| GB-RZ-19 | Manuales `pendiente` creados con T1; `changecard` a T3 antes de la fecha | Fecha de cobro | Medir si el cargo manual usa la tarjeta **vigente** al cobrar (se espera rechazo). Igual al revés (T3 → T1: se espera `pagado`) | MANUAL | P0 | a verificar |
| GB-RZ-20 | Cargo manual `rechazado`; el socio cambia a T1 vía `changecard` | Polling detecta la huella nueva | El CRM consulta el estado y ofrece (o ejecuta, según el flujo de `cambio-tarjeta.md`) `retry_charge` una vez por cargo rechazado. Medir si VP reintenta por su cuenta tras el cambio (no documentado) | MANUAL | P1 | a verificar |
| GB-RZ-21 | Cambio de tarjeta el mismo día del cobro | Cobro sale rechazado con la tarjeta anterior | El paso 6 de `cambio-tarjeta.md` lo recupera con `retry_charge`. Sin doble cobro | MANUAL | P2 | a verificar |
| GB-RZ-22 | Tarjeta vencida (no simulable en sandbox) | Cobro con rechazo `-8` o "expirad" (fake) | CAMBIO_TARJETA. Alerta proactiva por `payment_method.expiration_date` a 30–45 días | UNIT | P1 | a verificar |
| GB-RZ-23 | Sin fondos (no simulable en sandbox) | Rechazo `-3` o "fondos" (fake) | REINTENTAR una vez y después CAMBIO_TARJETA | UNIT | P1 | a verificar |
| GB-RZ-24 | Débito T4 / Prepago T6 | Cobro manual | `pagado`, igual que crédito | MANUAL | P2 | a verificar |
| GB-RZ-25 | AMEX T2 | Cobro manual | `pagado` | MANUAL | P2 | a verificar |
| GB-RZ-26 | Prepago MC T7 / Débito T5 vía `changecard` | Cobro manual | `rechazado`. Anotar el `rejected_object.code` real en `discrepancies.md` | MANUAL | P2 | a verificar |
| GB-RZ-27 | Manual `rechazado` en reintento; la suscripción se cancela | `DELETE /v3/suscription` | Medir si el rechazado pasa a `cancelado` y se detienen los reintentos (cancel-subscription.md ⚠️). El CRM deja de ofrecer reintentos y cambios | MANUAL | P1 | a verificar |
| GB-RZ-28 | Cargo `rechazado` del mes M; se aplica un cambio de monto | Aplicar cambio | M cubierto (no se puede cancelar un rechazado, E-059). Los manuales nuevos empiezan en M+1 | UNIT | P1 | a verificar |
| GB-RZ-29 | Cargo `rechazado` (automático o manual del CRM), clasificado REINTENTAR | Usuario pulsa "Reintentar" en el recuperador | Exactamente un `POST /retry` vía `retry_charge`. `write_run` con usuario, `charge_id` y resultado. **Ningún** `POST /v3/charge`. El cargo se resincroniza al terminar | UNIT | P0 | a verificar (nuevo) |
| GB-RZ-30 | Como RZ-29 | Doble clic, o dos usuarios reintentan el mismo cargo a la vez | Idempotente: un solo `/retry` por cargo. El segundo intento ve un `write_run` en curso o reciente para ese `charge_id` (lock por cargo) y responde 409 o "ya en curso" sin llamar a VP | UNIT (concurrencia) | P0 | a verificar (nuevo) |
| GB-RZ-31 | Como RZ-29 | El `/retry` termina en timeout | `retry_charge` **no** reintenta solo. `write_run` queda en estado incierto (`reconciliation_required` o equivalente). Antes de permitir otro reintento manual, el CRM consulta el estado del cargo en VP; si ya se cobró, no reintenta | UNIT | P0 | a verificar (nuevo) |
| GB-RZ-32 | Cargo que estaba `rechazado` y ya pasó a `pagado` (reintento automático de VP) pero el CRM aún no sincronizó | Reintento manual | El CRM relee el estado antes del `/retry`. Si ya no está `rechazado`, no llama a VP y lo informa (no-op) | UNIT | P1 | a verificar (nuevo) |
| GB-RZ-33 | Suscripción con varios meses `rechazado` | Reintento de un mes concreto | Solo se reintenta el `charge_id` elegido. No hay reintento masivo implícito ni se crean cargos para los otros meses | UNIT | P1 | a verificar (nuevo) |
| GB-RZ-34 | Cualquier combinación de rechazos (1, 3, 6 meses; con o sin racha marcada) | Sync, recuperador y chequeo de renovación | Test de guarda: cero llamadas a `create_charge` y cero DELETE originadas por rechazos. Solo `retry_charge` disparado por una persona | UNIT | P0 | a verificar (nuevo) |

## 3. Reasignación de monto y cambio de fecha

Todo cambio de esta sección se ejecuta solo tras una solicitud aprobada (sección 5).

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-RA-01 | 12 automáticos `pendiente` en el horizonte; monto sube | Reasignar (aprobado) | 12 POST OK y después 12 DELETE individuales. Verificación final: exactamente un `pendiente` por mes con el monto nuevo. `write_run` completed | UNIT | P0 | parcial: `test_reassign_creates_first_then_cancels_matching_period` |
| GB-RA-02 | Igual que RA-01; monto baja más del 50 % | Reasignar | Igual que RA-01. Con la doble aprobación apagada (configuración actual) basta 1 aprobación; si se enciende, exige 2 (AP-09) | UNIT | P0 | a verificar |
| GB-RA-03 | Monto nuevo = monto programado | Reasignar | No-op: sin POST ni DELETE. Se registra como "sin cambios" | UNIT | P1 | a verificar |
| GB-RA-04 | El horizonte ya tiene manuales del CRM (cambio o renovación anterior) | Reasignar otra vez | Crea los nuevos y cancela los **manuales anteriores** (no solo automáticos). Cada mes queda con un único pendiente | UNIT | P0 | a verificar |
| GB-RA-05 | La fecha de M0 ya pasó este mes | Reasignar | M0 sigue la ventana de 31 días dentro del cambio (JB-03 a JB-06): si M0 está cubierto, el monto nuevo rige desde M0+1; si no, cargo con fecha de mañana. Nunca se envía una fecha pasada (E-078) | UNIT | P0 | parcial: `test_create_charge_nok_e078_falla_con_codigo` |
| GB-RA-06 | La suscripción tiene menos de 12 automáticos futuros (calendario corto) | Reasignar | Se crean los 12 meses igual. Los meses sin automático no requieren DELETE | UNIT | P1 | a verificar |
| GB-RA-07 | POST k (1<k≤12) responde NOK | Reasignar | **Compensación:** se cancelan los k-1 nuevos. No se cancela ningún automático. `write_run` failed. La verificación final muestra el estado original | UNIT | P0 | parcial: `test_reassign_post_failure_cancels_nothing` (k=1) |
| GB-RA-08 | POST k con timeout, pero el cargo sí se creó | Reintento o compensación | El reintento lo adopta por listado (no duplica). La compensación también lista `/charges` para encontrar el huérfano y cancelarlo | UNIT | P0 | parcial: `test_timeout_en_post_y_reintento_adopta` |
| GB-RA-09 | Compensación en curso; un DELETE de un cargo nuevo falla | — | `reconciliation_required` y alerta P0. La suscripción queda **bloqueada** para nuevas operaciones hasta resolverlo. El control diario CS-03 lo vigila antes de `charge_date` | UNIT | P0 | a verificar |
| GB-RA-10 | 12 POST OK; el DELETE del automático j falla (red o 5xx) | — | No compensar (los nuevos son correctos). Reintentar el DELETE j. `reconciliation_required` si persiste. Plazo: antes de la `charge_date` de j | UNIT | P0 | a verificar |
| GB-RA-11 | Entre el listado y el DELETE, el automático j pasó a `procesando`/`pagado` (E-059) | DELETE j | Se omite j. Hay que **cancelar el manual nuevo de j** para no cobrar dos veces | UNIT | P0 | parcial: `test_cancel_selected_e059_is_skipped` (falta cancelar el manual) |
| GB-RA-12 | `/charges` falla antes de empezar | Reasignar | No se crea nada | UNIT | P1 | cubierto por `test_error_del_listado_impide_crear` |
| GB-RA-13 | Doble clic o dos solicitudes aprobadas sobre la misma suscripción | Ejecutar ambas | Lock por suscripción (advisory lock o una única operación activa). La segunda recibe 409 o espera. Nunca dos lotes intercalados (el dedupe por listado no protege una carrera) | UNIT (concurrencia) | P0 | a verificar |
| GB-RA-14 | Misma reasignación ejecutada dos veces seguidas | Reintento | Idempotente: el segundo adopta y no duplica | UNIT | P1 | parcial: `test_reassign_dos_veces_es_idempotente` |
| GB-RA-15 | El job diario procesa la suscripción en el mismo momento | Reasignación | — | — | — | Descartado (decisión 2026-10-28): no hay job que escriba. La concurrencia relevante pasa a RA-27 (reintento manual a la vez que un cambio) y RA-13 |
| GB-RA-16 | `charge_day` 5 → 20 (pedido del socio) | Cambio de fecha (aprobado) | Actualiza `charge_day`. Por cada mes del horizonte: crea el cargo del día 20 y después cancela el del 5. Mismo orden seguro y compensación que RA-07. La suscripción queda con calendario modificado | UNIT | P0 | a verificar |
| GB-RA-17 | Hoy día 10; `charge_day` 25 → 5; M0 tiene pendiente el 25 | Cambio de fecha | M0 conserva su cargo del 25 (no se mueve a una fecha pasada ni se cobra dos veces). Los meses siguientes pasan al día 5 | UNIT | P1 | a verificar |
| GB-RA-18 | Cambio de fecha y reasignación pedidos a la vez | Ejecutar ambos | Se serializan (lock). El resultado combina fecha nueva y monto nuevo, con un pendiente por mes | UNIT | P1 | a verificar |
| GB-RA-19 | Reasignación el mismo día de cobro de M0: el automático pasa a `procesando` en medio del lote | Reasignar | M0 cubierto con el monto viejo. Si el manual de M0 ya se creó, se cancela (ver RA-11) | UNIT | P0 | a verificar |
| GB-RA-20 | Cargo `procesando` en el mes a reemplazar | Reasignar | No se cancela ni se crea en ese mes | UNIT | P0 | a verificar (= CO-06) |
| GB-RA-21 | Cargo `rechazado` con reintento automático en curso en M0 | Reasignar | No se crea manual para M0 | UNIT | P1 | a verificar (= CO-08) |
| GB-RA-22 | Suscripción cancelada entre la aprobación y la ejecución | Ejecutar | El primer POST responde E-060. No se cancela nada. Solicitud "no ejecutable" | UNIT | P0 | a verificar |
| GB-RA-23 | Bandera `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` apagada | Reasignar | Bloqueado sin llamar a VP (422) | UNIT | P0 | cubierto por `test_flag_off_blocks_fixed_or_unknown_plan_without_provider_call` y `test_route_reassign_and_create_422_when_flag_off` |
| GB-RA-24 | `dry_run` | Reasignar | Devuelve el plan (12 creaciones y N cancelaciones) sin `write_run` ni escrituras. Es la base de la vista previa de la bandeja (AP-29) | UNIT | P0 | parcial: `test_reassign_dry_run_does_not_write` |
| GB-RA-25 | Lote masivo aprobado (p. ej. 500 suscripciones) | Ejecutar | Pausa entre llamadas. Cada suscripción falla de forma aislada. Reporte por suscripción. Reintento solo de las fallidas. Backoff ante 429/5xx/timeout y nunca un POST a ciegas: primero lista y adopta (absorbe el antiguo JB-14) | CONTRATO + PILOTO | P1 | a verificar |
| GB-RA-26 | Recién reasignado; aún no hay cobro nuevo | Ver ficha y KPI | `monto_vigente` sigue en el viejo hasta el primer `pagado` nuevo. La UI muestra además el "monto programado" | UNIT | P1 | a verificar |
| GB-RA-27 | Un usuario ejecuta `retry_charge` sobre un cargo de la suscripción mientras se aplica un cambio aprobado | Ambas operaciones | Comparten el lock por suscripción: la segunda espera o recibe 409. El cambio relee el estado al tomar el lock (un mes recién `pagado` queda cubierto) | UNIT (concurrencia) | P0 | a verificar (nuevo) |
| GB-RA-28 | Cambio aplicado con éxito | Fin de la ejecución | La suscripción queda marcada "calendario modificado" con: fecha del último cobro programado por el CRM, monto programado, `charge_day` y solicitud de origen. Es la entrada del chequeo de renovación (JB-25). Si el cambio falló y se compensó, la marca no cambia | UNIT | P0 | a verificar (nuevo) |
| GB-RA-29 | Tarea específica que necesita un cobro puntual (decisión 1b) | Solicitud aprobada de "cobro por tarea" | Un solo `POST /v3/charge` con `internal_code` propio de la tarea y fecha ≥ mañana. No cancela automáticos ni marca "calendario modificado". Idempotente por `internal_code` + listado (CO-12). Queda en el registro propio y en la auditoría | UNIT | P1 | a verificar (nuevo) |

## 4. Ventana de 31 días dentro de un cambio y chequeo de renovación (solo lectura)

Antes: "Ventana de 31 días y job de reposición". Desde la decisión 2026-10-28 no hay job que cree cobros. La ventana de 31 días se evalúa solo al aplicar un cambio, y el proceso diario solo lee y genera tareas.

### 4.1 Ventana de 31 días al aplicar un cambio

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-JB-01 | Día normal; M0+12 sin cargo gestionado | Job | — | — | — | Descartado (decisión 2026-10-28): no hay reposición diaria. Ver JB-25/JB-30 |
| GB-JB-02 | M0+12 ya tiene manual (segunda corrida del día) | Job | — | — | — | Descartado (decisión 2026-10-28): no hay reposición diaria. La idempotencia del chequeo está en JB-27 |
| GB-JB-03 | Fecha de M0 hace 1 día; sin `pagado`/`procesando`/`rechazado` | Aplicar cambio | Crea el cargo de M0 con fecha de mañana | UNIT | P0 | a verificar |
| GB-JB-04 | Hace 15 días, igual | Aplicar cambio | Igual que JB-03 | UNIT | P0 | a verificar |
| GB-JB-05 | Hace **31** días (borde) | Aplicar cambio | Crea con fecha de mañana (borde inclusivo) | UNIT | P0 | a verificar |
| GB-JB-06 | Hace **32** días | Aplicar cambio | No cobra ese mes. La solicitud registra el mes como "revisión manual" (visible en la vista previa y en el resultado). El resto del cambio sí se aplica | UNIT | P0 | a verificar |
| GB-JB-07 | Hace 1 día, pero el mes tiene un `rechazado` | Aplicar cambio | No crea (mes cubierto) | UNIT | P0 | a verificar |
| GB-JB-08 | Mes con un `pendiente` **vencido** (VP no lo intentó, `charge_date < hoy-2`) | Aplicar cambio | Un pendiente vencido no cubre el mes. El cambio crea uno con fecha de mañana y **cancela el vencido** (riesgo: VP lo intenta tarde y cobra dos veces). Medir en sandbox si VP cobra pendientes vencidos. Fuera de un cambio, el CRM solo alerta (CS-04) | UNIT + CONTRATO | P0 | a verificar |
| GB-JB-09 | M-1 (a menos de 31 días) y M0 sin cubrir, ambas fechas pasadas | Aplicar cambio | Definir: crear ambos con fecha de mañana (dos cobros el mismo día, posible E-087) o espaciarlos (M-1 mañana, M0 pasado mañana). Propuesta: espaciar | UNIT | P1 | a verificar (decisión abierta) |
| GB-JB-10 | El job no corrió durante 5 días | Primera corrida al volver | — | — | — | Descartado (decisión 2026-10-28): no hay reposición. La recuperación tras días sin correr del chequeo está en JB-33 |
| GB-JB-11 | El job estuvo caído más de 31 días | Corrida | — | — | — | Descartado (decisión 2026-10-28): la regla de "más de 31 días" se prueba dentro de un cambio (JB-06) |
| GB-JB-12 | El job se cae a mitad de corrida | Reinicio | — | — | — | Descartado (decisión 2026-10-28): para un cambio, ver RA-08 y RA-14 (adopción e idempotencia) |
| GB-JB-13 | Límite de escrituras por corrida alcanzado | Corrida | — | — | — | Descartado (decisión 2026-10-28): el chequeo no escribe; los lotes de cambios se controlan en RA-25 |
| GB-JB-14 | VP responde 429, 5xx o timeout | Corrida | — | — | — | Descartado (decisión 2026-10-28): absorbido por RA-25 (lotes) y RA-08 (timeout en POST) |
| GB-JB-15 | Error de negocio con HTTP 200 NOK | Aplicar cambio | Se trata como error, con el código E-nnn en el `write_run` | UNIT | P1 | cubierto por `test_nok_con_http_200_lanza_error_con_codigo` y `test_sync_con_nok_falla_el_run_con_el_codigo` |
| GB-JB-16 | La suscripción se cancela entre el listado y el POST | Corrida | — | — | — | Descartado (decisión 2026-10-28): duplicado de RA-22 |
| GB-JB-17 | Suscripción cancelada desde el panel de VP | Sync y chequeo de renovación | El sync la ve CANCELADA: el chequeo deja de generar tareas y las solicitudes pendientes sobre ella pasan a "no ejecutable". Verificar que VP canceló los manuales pendientes | CONTRATO | P0 | a verificar (= CO-20) |
| GB-JB-18 | `dry_run` del job | Corrida | — | — | — | Descartado (decisión 2026-10-28): el `dry_run` de un cambio es RA-24 y la vista previa AP-29 |
| GB-JB-19 | `VIRTUALPOS_WRITES_ENABLED` apagada, bandera de plan fijo apagada o bandera de facturación gestionada apagada | Aplicar cambio y chequeo de renovación | El cambio no escribe y la solicitud queda "bloqueada por configuración" con el motivo. El chequeo de renovación sigue funcionando porque no escribe | UNIT | P0 | parcial: `test_cancel_future_blocked_when_writes_disabled` |
| GB-JB-20 | Allowlist del piloto | Solicitud de cambio y chequeo | Solo se aceptan solicitudes para suscripciones de la allowlist. El chequeo de renovación solo revisa esas | UNIT | P0 | a verificar |
| GB-JB-21 | El sync corre a la vez que se aplica un cambio | — | El sync no pisa el registro de cargos gestionados, la marca "calendario modificado" ni `charge_day` | UNIT | P1 | a verificar |
| GB-JB-22 | Cambio aplicado o chequeo corrido cerca de medianoche | Cálculo de "hoy", "mañana" y "días hasta el último cobro" | Usar la fecha de America/Santiago, no UTC (`vp_current_amount` usa `datetime.now(UTC)`). Nunca E-078 por desfase horario | UNIT | P1 | a verificar |
| GB-JB-23 | La suscripción termina (calendario agotado sin renovación) | Chequeo de renovación | Deja de generar tareas para ella (CO-18) | UNIT | P1 | a verificar |
| GB-JB-24 | Suscripciones en `virtualpos1` y `virtualpos2` | Aplicar cambio | Cada escritura va a su cuenta (`platform` correcto) | UNIT | P1 | a verificar |

### 4.2 Chequeo diario de renovación (solo lectura) — escenarios nuevos

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-JB-25 | Suscripción con calendario modificado; último cobro programado por el CRM dentro de 59 días | Chequeo diario | Genera una tarea/alerta "renovar calendario" con suscripción, último mes programado, monto programado y fecha límite. **Cero** llamadas de escritura al proveedor | UNIT | P0 | a verificar (nuevo) |
| GB-JB-26 | Último cobro programado a exactamente 60 días y a 61 días | Chequeo diario | 60 → genera tarea (borde inclusivo, "a 60 días o menos"); 61 → no genera | UNIT | P0 | a verificar (nuevo) |
| GB-JB-27 | Ya existe una tarea de renovación abierta o una solicitud de renovación pendiente para la suscripción | Chequeo de nuevo (mismo día o días siguientes) | No duplica la tarea. Actualiza "días restantes" y, si faltan menos de 15 días, sube la prioridad (propuesta) | UNIT | P0 | a verificar (nuevo) |
| GB-JB-28 | Suscripción sin calendario modificado (solo automáticos de VP) | Chequeo diario | Nunca genera tarea; no le corresponde renovación | UNIT | P0 | a verificar (nuevo) |
| GB-JB-29 | Escrituras y banderas encendidas; fake de `VirtualPOSClient` que cuenta llamadas | Chequeo diario sobre 100 suscripciones de prueba | Test de guarda: 0 `POST /v3/charge`, 0 `DELETE`, 0 `/retry`. El chequeo no crea `write_run` de escritura (solo un registro de corrida de lectura) | UNIT | P0 | a verificar (nuevo) |
| GB-JB-30 | Tarea de renovación aprobada (flujo de la sección 5) | Aplicar renovación | Se aplica como un cambio: horizonte de 12 meses que empieza en el mes siguiente al último programado; crea primero, cancela los automáticos solo dentro del nuevo horizonte y deja los posteriores. Actualiza la marca de RA-28. La tarea se cierra con la solicitud enlazada | UNIT + CONTRATO | P0 | a verificar (nuevo) |
| GB-JB-31 | Nadie aprueba la tarea y se agota el horizonte | Llega el primer mes posterior | VP cobra el automático con el **monto antiguo** (red de seguridad): ningún mes queda sin cargo. La tarea pasa a "vencida", escala y el control CS-14 registra "volvió al monto antiguo" | UNIT + PILOTO | P0 | a verificar (nuevo) |
| GB-JB-32 | Tarea de renovación rechazada por el aprobador con comentario (p. ej. el socio pidió volver al monto original) | Rechazar | La tarea se cierra con el comentario. La suscripción deja de estar "calendario modificado" desde el fin del horizonte y el chequeo no vuelve a alertar por ese horizonte | UNIT | P1 | a verificar (nuevo) |
| GB-JB-33 | El chequeo no corrió durante varios días | Primera corrida al volver | Detecta igual todas las suscripciones dentro de N días (solo depende de la fecha del último cobro). Con N = 60 hay margen; si alguna ya pasó el fin del horizonte, la tarea nace "vencida" (JB-31) | UNIT | P1 | a verificar (nuevo) |
| GB-JB-34 | Un admin cambia N (p. ej. 60 → 90) en la configuración | Próxima corrida | Rige el N nuevo. El cambio de N queda auditado (AP-35) | UNIT | P2 | a verificar (nuevo) |
| GB-JB-35 | Suscripción con calendario modificado cuyo estado en VP cambió a CANCELADA, FINALIZADA o SUSCRIPCION_FALLIDA | Chequeo diario | No genera tarea; cierra la abierta como "no aplica" | UNIT | P1 | a verificar (nuevo) |
| GB-JB-36 | Último sync de la suscripción con más de 48 h de antigüedad (o falló) | Chequeo diario | Genera la tarea igual pero marcada "datos desactualizados", y la vista previa de la renovación obliga a sincronizar antes de aprobar | UNIT | P1 | a verificar (nuevo) |

## 5. Aprobaciones (maker-checker)

Configuración actual (decisión 2026-10-28): aprobadores = rol admin; autoaprobación = activada (auditada); doble aprobación por umbral = apagada. Las tres cosas son editables en el panel de administración.

### 5.1 Reglas y permisos

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-AP-01 | Usuario aprobador por configuración (no admin); autoaprobación **desactivada** | Aprueba su propia solicitud | 403 "autoaprobación no permitida" | UNIT | P1 | a verificar |
| GB-AP-02 | Admin solicitante; autoaprobación **activada** (configuración actual) | Aprueba lo propio | Permitido. Auditado como "autoaprobación" con usuario y fecha | UNIT | P0 | a verificar |
| GB-AP-03 | Admin; cambio grande o masivo | Aprueba lo propio | — | — | — | Descartado (decisión 2026-10-28): con autoaprobación activada y doble aprobación apagada, se permite (AP-02). La restricción con doble aprobación encendida está en AP-36 |
| GB-AP-04 | Usuario que no es aprobador según la configuración (p. ej. jefatura hoy) | Aprueba o rechaza cualquier solicitud | 403. Sin cambio de estado. Intento auditado | UNIT | P0 | a verificar |
| GB-AP-05 | Usuario sin permiso de solicitar | Crea una solicitud | 403 | UNIT | P0 | parcial: `test_routes_permissions_and_csrf` |
| GB-AP-06 | Solicitud individual; doble aprobación apagada | 1 aprobación | Se ejecuta | UNIT | P0 | a verificar |
| GB-AP-07 | Doble aprobación **encendida**; masivo de 21 suscripciones | 1 aprobación | Queda en "1/2". Ejecuta con un segundo aprobador **distinto** del primero y del solicitante. Con la opción apagada, ejecuta con 1 (AP-06) | UNIT | P2 | a verificar (opción apagada por ahora) |
| GB-AP-08 | Doble aprobación encendida; masivo de 20 exactas (borde) | 1 aprobación | Se ejecuta | UNIT | P2 | a verificar (opción apagada por ahora) |
| GB-AP-09 | Doble aprobación encendida; variación de 50 % exacto y de 50,1 % | Aprobación | 50 % → 1 aprobación; 50,1 % → 2. La base es el monto programado (o `monto_vigente`) al solicitar. Subidas y bajadas se miden en valor absoluto | UNIT | P2 | a verificar (opción apagada por ahora) |
| GB-AP-10 | Solicitud pendiente más allá del plazo (p. ej. 7 días) | Aprobar | Expirada; no ejecutable. Sale de la bandeja de pendientes y pasa al historial | UNIT | P1 | a verificar |
| GB-AP-11 | Solicitud pendiente | Rechazar | Estado "rechazada" con comentario obligatorio (vacío → 422). No ejecuta. El solicitante ve el comentario | UNIT | P1 | a verificar |
| GB-AP-12 | Ya hay una solicitud pendiente para la misma suscripción | Nueva solicitud | 409 (o reemplazo explícito de la anterior) | UNIT | P1 | a verificar |
| GB-AP-13 | Entre la solicitud y la ejecución cambia el estado (CANCELADA, otro cambio aplicado, `procesando`) | Ejecutar | Se revalida al ejecutar. Si la suscripción no está ACTIVA, no se ejecuta. Si la doble aprobación está encendida y la variación cambió de categoría, pide reaprobación | UNIT | P0 | a verificar |
| GB-AP-14 | Dos aprobadores aprueban a la vez | Aprobar | Una sola ejecución (transición atómica de estado) | UNIT | P0 | a verificar |
| GB-AP-15 | Se cambian los umbrales con solicitudes pendientes | Aprobar | — | — | — | Descartado (decisión 2026-10-28): reemplazado por AP-25 a AP-27 (cambio de configuración con solicitudes pendientes) |
| GB-AP-16 | Cualquier solicitud | Ciclo completo | Auditoría inmutable: solicitante, aprobadores, si fue autoaprobación, fechas, comentarios, monto antes y después, vista previa aprobada, IDs de `write_run`, resultado. Sin PII innecesaria | UNIT | P0 | a verificar |
| GB-AP-17 | Masivo aprobado con fallos parciales | Reintento | Solo se reintentan las fallidas, sin nueva aprobación, mientras la aprobación siga vigente | UNIT | P1 | a verificar |
| GB-AP-18 | Cambio de `charge_day` | Solicitud | Requiere aprobación con el mismo flujo (decidido 2026-10-28: todo cambio que hace que el CRM cree cobros pasa por aprobación) | UNIT | P1 | a verificar (decidido) |
| GB-AP-19 | Rutas de escritura, de aprobación y de configuración | Sin CSRF, sin sesión o con rol incorrecto | 403/401 | UNIT | P1 | parcial: `test_routes_permissions_and_csrf` |

### 5.2 Configuración de aprobadores (panel de administración) — escenarios nuevos

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-AP-20 | Instalación nueva o migración | Leer la configuración | Valores por defecto: aprobadores = rol `admin`; usuarios aprobadores = ninguno; autoaprobación = activada; doble aprobación = apagada (umbrales guardados pero inactivos); N renovación = 60 | UNIT | P0 | a verificar (nuevo) |
| GB-AP-21 | Admin | Agrega el usuario X (no admin) como aprobador | X ve la bandeja y puede aprobar o rechazar. Quitarlo revoca el acceso de inmediato | UNIT | P1 | a verificar (nuevo) |
| GB-AP-22 | Usuario no admin | Lee o edita la configuración de aprobaciones | Edición: 403. Lectura: solo admin (propuesta) | UNIT | P0 | a verificar (nuevo) |
| GB-AP-23 | Admin | Guarda una configuración sin ningún aprobador (sin roles ni usuarios) | Rechazada al guardar (422): el sistema nunca queda sin aprobador | UNIT | P0 | a verificar (nuevo) |
| GB-AP-24 | El único aprobador es también el único solicitante habitual | Desactiva la autoaprobación | Advertencia explícita: "sus solicitudes no tendrán quién las apruebe". Se bloquea si no existe otro aprobador activo distinto (propuesta) | UNIT | P1 | a verificar (nuevo) |
| GB-AP-25 | Solicitud pendiente; el aprobador X es quitado de la configuración | X intenta aprobar | 403. **Quién puede aprobar** se evalúa con la configuración vigente al aprobar | UNIT | P0 | a verificar (nuevo) |
| GB-AP-26 | Solicitudes propias del admin pendientes; se desactiva la autoaprobación | El admin intenta aprobar las suyas | 403: la regla de autoaprobación se evalúa al aprobar. Las solicitudes siguen pendientes para otro aprobador | UNIT | P1 | a verificar (nuevo) |
| GB-AP-27 | Solicitudes pendientes; se enciende la doble aprobación o se cambian los umbrales | Aprobar | **Cuántas aprobaciones** se necesitan queda fijado al crear la solicitud (snapshot). Las pendientes conservan su regla; las nuevas usan la nueva | UNIT | P2 | a verificar (nuevo) |
| GB-AP-35 | Cualquier cambio en la configuración (aprobadores, autoaprobación, doble aprobación, umbrales, N) | Guardar | Auditoría inmutable: quién, cuándo, valor anterior y nuevo. Visible en el historial de configuración | UNIT | P0 | a verificar (nuevo) |
| GB-AP-36 | Doble aprobación encendida y autoaprobación activada | Admin solicitante aprueba lo propio en un cambio que exige 2 | Su aprobación cuenta como una sola; la segunda debe venir de otro aprobador distinto | UNIT | P2 | a verificar (nuevo; opción apagada por ahora) |

### 5.3 Interfaz de solicitudes (bandeja, vista previa, historial) — escenarios nuevos

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-AP-28 | Aprobador (hoy, admin) | Abre la bandeja | Lista solo solicitudes pendientes (cambio de monto, cambio de fecha, renovación, cobro por tarea), con tipo, suscripción, solicitante, antigüedad y vencimiento. Un no aprobador no ve la entrada de menú y la API responde 403 | UNIT + MANUAL (UI) | P0 | a verificar (nuevo) |
| GB-AP-29 | Solicitud pendiente | Abre la vista previa | Muestra, mes a mes: cargos que se **crearán** (fecha, monto), cargos que se **cancelarán** (`charge_id`, fecha, monto, tipo automático/manual), meses cubiertos sin cambio, meses en "revisión manual" (ventana de más de 31 días) y los automáticos posteriores al horizonte que **se conservan**. Generada con `dry_run` (RA-24), sin escrituras | UNIT + MANUAL (UI) | P0 | a verificar (nuevo) |
| GB-AP-30 | El estado en VP cambió desde que se generó la vista previa (p. ej. un mes pasó a `pagado`) | Aprobar | Al aprobar se recalcula el plan. Si difiere de lo mostrado, no ejecuta: muestra la diferencia y pide confirmar de nuevo. Nunca se ejecuta un plan distinto del aprobado sin verlo | UNIT | P0 | a verificar (nuevo) |
| GB-AP-31 | Solicitud pendiente | Aprobar con comentario / sin comentario | Comentario opcional al aprobar; queda en la auditoría y el historial | UNIT | P2 | a verificar (nuevo) |
| GB-AP-32 | Solicitudes cerradas (aprobadas, rechazadas, expiradas, retiradas, fallidas) | Abre el historial | Solo lectura. Muestra estado, resultado de ejecución, `write_run`, aprobador(es), si hubo autoaprobación y comentarios. Filtros por estado, tipo, suscripción y fecha | UNIT + MANUAL (UI) | P1 | a verificar (nuevo) |
| GB-AP-33 | Solicitud pendiente propia | El solicitante la retira | Estado "retirada"; no ejecutable; sale de la bandeja | UNIT | P2 | a verificar (nuevo) |
| GB-AP-34 | Tarea "renovar calendario" generada por el chequeo (JB-25) | Abrir desde la tarea | Crea (o enlaza) una solicitud de tipo "renovación" que aparece en la bandeja con su vista previa; se aprueba o rechaza igual que cualquier otra | UNIT | P0 | a verificar (nuevo) |

## 6. Consistencia CRM–proveedor

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-CS-01 | Reasignada y sin cobro nuevo aún | Ficha, KPI MRR | `monto_vigente` = monto viejo. El KPI sigue al último cobro. El "monto programado" se muestra aparte | UNIT | P1 | parcial: `test_kpi_mrr_sigue_el_ultimo_cobro_no_el_plan` |
| GB-CS-02 | Un pendiente del horizonte con monto distinto del programado | Control diario (solo lectura) | Alerta de desfase con suscripción y mes | UNIT | P0 | a verificar |
| GB-CS-03 | Un mes con **dos** pendientes | Control diario (D-3 antes de `charge_date`) | Alerta P0 y bloqueo de la suscripción para nuevos cambios hasta resolver | UNIT | P0 | a verificar |
| GB-CS-04 | Un mes del horizonte sin pendiente y no cubierto ni pausado, o con un pendiente vencido | Control diario (solo lectura) | Alerta. El CRM **no** repone por su cuenta: se resuelve con una solicitud de cambio aprobada (donde aplica la ventana de 31 días) | UNIT | P0 | a verificar |
| GB-CS-05 | Cargos creados por el CRM | Sync desde el listado de suscripciones | Se reconocen por `charge_id` en el registro propio (el listado no trae `internal_code`, VP-C28). Sin duplicados en `vp_charges`/`charges` | UNIT | P0 | a verificar |
| GB-CS-06 | Alguien crea un cargo desde el **panel de VP** en un mes gestionado | Sync | Se detecta "cargo no registrado". No se cancela automáticamente. Alerta de revisión (posible doble cobro) | UNIT | P0 | a verificar |
| GB-CS-07 | Alguien cancela desde el panel un manual del CRM | Sync | Hueco detectado. Alerta. No se repone automáticamente (puede ser una pausa pedida por otro canal) | UNIT | P1 | a verificar |
| GB-CS-08 | Suscripción cancelada en el panel | Sync | Deja de aceptar cambios y de generar tareas de renovación (JB-17) | UNIT | P0 | a verificar |
| GB-CS-09 | `write_run` en `reconciliation_required` | Cola de reconciliación | Aparece en la cola. Bloquea la suscripción. La resolución manual queda trazada | UNIT | P0 | a verificar |
| GB-CS-10 | Cuota `pagado` | Cuadratura (seguimiento-cobros § 5) | `charge.amount == payment.order.amount`. Si difieren, alerta | UNIT | P1 | a verificar (depende de V-2) |
| GB-CS-11 | Dos `pagado` en el mismo mes | Cuadratura | Alerta de doble cobro. La devolución es manual (no hay endpoint de reembolso) | UNIT | P0 | a verificar |
| GB-CS-12 | Dos cargos `pagado` el mismo día (duplicado) | `monto_vigente` | Desempate determinista por `external_id` | UNIT | P2 | cubierto por `test_helper_ultimo_pagado_procesando_futuros_plan_y_desempate` |
| GB-CS-13 | Tablas `vp_*` y centralizadas | `load_monto_vigente(family=vp/crm)` | Mismo resultado en ambas familias para las suscripciones gestionadas | UNIT | P2 | a verificar |
| GB-CS-14 | Registro propio de cargos creados por el CRM | Control diario | Todo cargo creado por el CRM tiene una solicitud o tarea aprobada asociada; si no, alerta P0. Además, si una suscripción con calendario modificado cobró un mes con el monto antiguo tras el fin del horizonte, alerta "volvió al monto antiguo" (JB-31) | UNIT | P0 | a verificar (nuevo) |

## 7. Migración y piloto

| ID | Precondiciones | Acción / evento | Resultado esperado según el diseño | Cómo se prueba | Prio | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| GB-PI-01 | Escenarios P0 de CONTRATO/MANUAL resueltos (CO-01, 03, 04, 05, 14, 19, 20; RZ-06, 07, 19; JB-08) | Puerta de entrada | No se activa nada en producción hasta tener esas respuestas. Bandera de plan fijo encendida **solo** para la allowlist. Bandeja y configuración de aprobadores operativas (AP-20, AP-28, AP-29) | revisión | P0 | a verificar |
| GB-PI-02 | Selección | Elegir 5–10 suscripciones de producción | Voluntarios internos con consentimiento y tarjeta propia. Montos bajos. Días de cobro variados (05, 15, 28/30 y al menos uno de día 0). Sin rechazos recientes, sin `procesando`, sin `reconciliation_required` | PILOTO | P0 | a verificar |
| GB-PI-03 | Fase 1: 1 suscripción | Solicitud aprobada que cambia solo M0+1 (1 mes) | Un único cobro real con el monto nuevo. Sync y `monto_vigente` correctos | PILOTO | P0 | a verificar |
| GB-PI-04 | Fase 2: las 5–10 | Cambio con horizonte de 12 meses aplicado vía solicitudes aprobadas; chequeo de renovación activo (solo lectura) | 2 ciclos de cobro completos, sin incidentes. Ninguna escritura fuera de solicitudes aprobadas (CS-14) | PILOTO | P0 | a verificar |
| GB-PI-05 | Tras cada ciclo | Criterios de éxito | 100 % de meses con exactamente 1 cobro y monto correcto. 0 dobles cobros. 0 meses sin cargo. 0 `reconciliation_required` abiertos más de 24 h. Sync y cuadratura en verde | PILOTO | P0 | a verificar |
| GB-PI-06 | Cualquier ciclo | Criterios de abort | Abortar ante cualquier doble cobro, monto incorrecto, mes sin cargo, E-113/E-087 en producción, manual no cobrado en su fecha, dos pendientes en un mes a menos de 3 días de su fecha o cualquier cobro creado por el CRM sin solicitud aprobada | PILOTO | P0 | a verificar |
| GB-PI-07 | Abort | Reversión | No se puede volver al automático en los meses cuyos automáticos se cancelaron. Procedimiento: (1) quitar las suscripciones de la allowlist y cerrar sus tareas de renovación; (2) los manuales ya creados siguen cobrando; si el monto era el problema, aplicar con aprobación un cambio con el monto anterior (orden seguro); (3) desde el fin del horizonte siguen los automáticos originales, siempre que **nunca** se haya usado el DELETE plural (CO-16). Así la gestión manual tiene una "cola" máxima de 12 meses. Alternativa: suscripción nueva con re-enrolamiento | PILOTO + UNIT (script de reversión) | P0 | a verificar |
| GB-PI-08 | Doble cobro detectado | Devolución | Payout o gestión manual (sin endpoint de reembolso). Comunicación al socio | MANUAL | P1 | a verificar |
| GB-PI-09 | Escalado | 50 → 500 → todas, por lotes | Avanzar de etapa solo si la anterior cumple PI-05. Medir rate limits reales (RA-25) | PILOTO | P1 | a verificar |
| GB-PI-10 | Cambio de monto | Aviso al socio | Notificación previa con el monto nuevo y la fecha | MANUAL | P2 | a verificar |
| GB-PI-11 | Una suscripción del piloto con N de renovación forzado alto (p. ej. 400 días) | Chequeo diario | Genera la tarea de renovación en la bandeja sin ninguna escritura al proveedor (JB-25, JB-29). Aprobarla aplica la renovación (JB-30) | PILOTO | P1 | a verificar (nuevo) |

---

## Resultados medidos en el sandbox (2026-10-27/28)

Suscripciones de prueba creadas con el formulario público del plan y la VISA aprobada de `resources/sandbox.md`: `CT-CO-AUTO` y `CT-DUP1` (plan `MONTO_FIJO` "Plan Básico", $9.990, 12 automáticos `pendiente` desde 2026-11-05). Escrituras activadas solo por variables de proceso; todo lo creado se canceló o quedó descrito aquí.

| Escenario | Qué se hizo | Resultado observado |
| --- | --- | --- |
| GB-CO-01 | Manual 2026-11-12 ($7.000) en un mes con automático pendiente (2026-11-05, $9.990) | **Aceptado.** Conviven ambos `pendiente`; no se reemplaza ni se rechaza. Sin E-087 |
| GB-CO-02 | Segundo manual en el mismo mes (2026-11-20) | **Aceptado.** El proveedor no distingue por mes: hay tres `pendiente` en noviembre. No existe límite mensual observable (al menos hasta 3) |
| GB-CO-04 | (parcial) | Dos cargos `pendiente` en el mismo mes confirmados. **Sigue sin medirse si el proveedor cobra ambos en sus fechas** (requiere esperar la fecha; ver CT-00-COBRO) |
| GB-CO-18/19 (parcial) | Manual el 2027-12-15, más allá de los 12 cobros del plan | **Aceptado.** `num_charges` no limita la creación de manuales. Sigue sin medirse el efecto de cancelar automáticos sobre `num_charges` |
| GB-RA-01 (un mes) | `reassign` de noviembre a $6.500 (fecha 2026-11-10) en `CT-DUP1`; simulación previa | Simulación: crearía $6.500 y cancelaría el automático del 5. Real: creado el manual del 10 y cancelado el del 5; diciembre y enero intactos (12 pendientes: 11 automáticos y 1 manual; 1 cancelado) |
| Idempotencia de `reassign` | Repetir la misma llamada | **Adopta** el mismo cargo (mismo id), sin crear ni cancelar nada más |
| VP-C28 | Lectura de campos | Los automáticos **no** traen `internal_code`; los manuales sí. Sirve para distinguirlos en el listado de cargos por suscripción |

Consecuencia de diseño confirmada: el orden "crear el nuevo primero y luego cancelar el automático del **mismo mes**" es correcto y no está bloqueado, y la cancelación del automático del mes reemplazado es **obligatoria** (sin ella el socio tendría dos cargos pendientes en ese mes).

## Hallazgos de diseño detectados al escribir los escenarios

1. **El DELETE plural es incompatible con la opción A** (CO-16). `cancel_future_charges` sin `charge_ids` cancela todo: manuales y automáticos fuera del horizonte, que son la red de seguridad si la renovación no se aprueba. Hay que prohibirlo en suscripciones con calendario modificado.
2. **Los automáticos posteriores al horizonte se dejan vivos a propósito, con el monto antiguo** (CO-14, JB-30, JB-31). Al aplicar un cambio solo se cancelan los automáticos de los 12 meses del horizonte. Al terminar el horizonte, VirtualPOS sigue cobrando esos automáticos con el monto antiguo: esa es la red de seguridad (ningún mes queda sin cargo aunque el CRM se detenga). El riesgo es que el socio **vuelva en silencio al monto viejo**; el chequeo de renovación (aviso a N = 60 días) y el control CS-14 existen para evitarlo.
3. **El listado de suscripciones no trae `internal_code`** (VP-C28). El sync masivo no distingue manuales de automáticos. Hace falta un registro propio de `charge_id` creados, o leer `/charges` por suscripción (N+1 sobre 6000).
4. **E-087 ("máximo de cargos mensuales") no aparece en el sandbox** (medido el 2026-10-27, CO-01/CO-02): el proveedor acepta varios cargos en el mismo mes, así que el orden "crear primero" no falla. El riesgo se invierte: **sin cancelar el automático del mes, hay doble cobro pendiente.** Sigue sin medirse si ambos se cobran en sus fechas.
5. **Un pendiente vencido** no cubre el mes, pero VP podría cobrarlo tarde (JB-08). Se cancela solo cuando un cambio aprobado lo reemplaza; fuera de un cambio el CRM solo alerta (CS-04).
6. **La fecha de "hoy" está en UTC** en `vp_current_amount.py`. Los cambios y el chequeo de renovación deben usar la hora de Chile (JB-22).
7. **El dedupe por listado no protege una carrera** entre dos procesos (RA-13, RA-27, RZ-30). Hace falta un lock por suscripción (cambios) y por cargo (reintentos).
8. **Sin job de reposición, el CRM nunca "rellena" meses.** Un mes con rechazo depende de `retry_charge` (manual) y de los reintentos automáticos de VP; un mes sin cargo solo se corrige con una solicitud aprobada. Por eso las alertas CS-04 y CS-14 pasan a ser el control principal.
9. **`retry_charge` no se reintenta ante timeout** (RZ-31). El estado queda incierto; antes de permitir otro reintento hay que consultar el cargo en VP para no cobrar dos veces.
10. **Todo cobro creado por el CRM debe tener una solicitud o tarea aprobada** (CS-14). Es la forma verificable de la decisión 1.

## (a) Escenarios que requieren una suscripción de prueba en sandbox

Ambiente: sandbox, cuenta 1. Escrituras activadas solo por variables de proceso, como en `tests_contract/README.md`. Al terminar cada prueba, cancelar los cargos de prueba. Advertencia: V-2 a V-4 siguen pendientes porque requieren "tarjeta y cobro real". Antes de las recetas MANUAL hay que confirmar que el sandbox **ejecuta** cobros en la fecha programada (CT-00).

| Prio | Nombre sugerido | Receta | Escenarios |
| --- | --- | --- | --- |
| P0 | CT-00-COBRO | Plan `MONTO_FIJO`, día `0`, `num_charges` 12, renovación `T`. Enrolar con T1. Crear un manual con fecha de mañana | ¿El sandbox cobra en la fecha? CO-05, RZ-03, RZ-05 |
| P0 | CT-CO-AUTO | Plan `MONTO_FIJO` con el día disponible más cercano a hoy+2 (p. ej. `05`/`28`), `num_charges` 12, renovación `T`, T1. Debe tener al menos 3 automáticos `pendiente` futuros. **Es la "suscripción de prueba con cobros futuros" del punto bloqueante 1** | CO-01, CO-02, CO-03, CO-14, RA-01 (se quita CO-15, descartado) |
| P0 | CT-CO-DUP | Igual que CT-CO-AUTO, con el **primer automático en 1–2 días**. Crear el manual del mismo mes y **no** cancelar el automático | CO-04 (¿doble cobro?) |
| P0 | CT-CO-NC3 | Plan `MONTO_FIJO`, `num_charges` 3, renovación `F`, T1. Cancelar los 3 automáticos y crear manuales | CO-19, CO-18 |
| P0 | CT-RZ-MC | Plan `MONTO_FIJO`, día `0`, T1. Después `changecard` a T3 y manual con fecha de mañana. Observar 4 días | RZ-06, RZ-07, RZ-19 (T1 → T3) |
| P0 | CT-RZ-SWAP | Como CT-RZ-MC. Tras el rechazo, `changecard` a T1 y `retry_charge`; repetir el reintento dos veces seguidas para medir la idempotencia | RZ-19 (T3 → T1), RZ-20, RZ-29, RZ-30 |
| P0 | CT-CANCEL | Plan `MONTO_FIJO`, T1, 2 manuales `pendiente`. `DELETE /v3/suscription` y luego un POST | CO-20, JB-17 |
| P0 | CT-STALE | Plan `MONTO_FIJO`, T1. Buscar o esperar un automático `pendiente` con fecha pasada; aplicar un cambio que crea el reemplazo con fecha de mañana | JB-08 (¿VP cobra pendientes vencidos?) |
| P1 | CT-RENEW | Plan `MONTO_FIJO`, `num_charges` 24, renovación `T`, T1. Aplicar un cambio con horizonte reducido **solo en sandbox** (p. ej. 2 meses, parámetro de prueba) y N alto para que el chequeo dispare de inmediato. Aprobar la renovación | JB-25, JB-30, CO-14 (automáticos posteriores intactos) (nuevo) |
| P1 | CT-CO-NC3R | Plan `MONTO_FIJO`, `num_charges` 3, renovación `T`, T1. Dejar agotar con manuales | CO-17 |
| P1 | CT-DAY30 | Plan `MONTO_FIJO`, día `30`, T1. Manuales con fechas 2027-02-28, 2028-02-29 y 2026-11-30 | CO-24, CO-25 |
| P1 | CT-DAY0 | Plan `MONTO_FIJO`, día `0`, T1 | CO-22, RZ-01 |
| P1 | CT-ENR-REJ | Planes `MONTO_FIJO`; enrolar con T3, T5 y T7 (una suscripción por tarjeta) | RZ-02 |
| P1 | CT-RZ-CANCEL | Como CT-RZ-MC; cancelar la suscripción mientras hay reintentos | RZ-27 |
| P1 | CT-LOTE | 20–30 suscripciones de plan fijo con T1 (reusar las existentes) y ráfaga de POST/DELETE sin pausa | RA-25 (se quita JB-14, descartado) |
| P2 | CT-TODAY | Plan `MONTO_FIJO`, T1; manual con `charge_date` = hoy | CO-27 |
| P2 | CT-CARDS-OK | Tres suscripciones de plan fijo con T2, T4 y T6; manual con fecha de mañana | RZ-24, RZ-25 |
| P2 | CT-CARDS-REJ | `changecard` a T5 y T7; manual con fecha de mañana | RZ-26 |

## (b) Escenarios que deben convertirse primero en pruebas automáticas con fakes

Orden sugerido: cada bloque es un archivo de test, con un fake de `VirtualPOSClient` que guarda el estado de los cargos y cuenta las llamadas de escritura.

1. **Orden seguro, compensación y verificación** (cambio con horizonte): RA-01, RA-04, RA-07, RA-08, RA-09, RA-10, RA-11, RA-19, RA-28, CO-11, CO-14.
2. **Cobertura de mes y estados**: CO-06, CO-07, CO-08, CO-09, RA-20, RA-21, RZ-28.
3. **Ventana de 31 días dentro de un cambio y fechas**: JB-03 a JB-09, CO-24, CO-26, JB-22, RA-05, RA-17.
4. ~~Job de reposición~~ — Descartado (decisión 2026-10-28). Se reemplaza por: **Chequeo de renovación (solo lectura)**: JB-25, JB-26, JB-27, JB-28, JB-29, JB-32, JB-33, JB-35, JB-36, y JB-30 (renovación aprobada).
5. **Guardas**: CO-16 (DELETE plural prohibido), RA-13 y RA-27 (lock), RA-22, CO-13 y CS-05 (registro propio de `charge_id`), JB-19, JB-20, RZ-34 y CS-14 (ningún cobro sin solicitud aprobada).
6. **Reintento manual y recuperador (solo lectura)**: RZ-29, RZ-30, RZ-31, RZ-32, RZ-33, RZ-10, RZ-11; ayuda opcional de racha: RZ-08, RZ-15, RZ-16.
7. **Aprobaciones: reglas y permisos**: AP-01, AP-02, AP-04, AP-06, AP-13, AP-14, AP-16, AP-25, AP-26.
8. **Configuración de aprobadores** (nuevo): AP-20, AP-21, AP-22, AP-23, AP-24, AP-27, AP-35, AP-36.
9. **Bandeja de solicitudes** (nuevo; API con fakes, más una pasada MANUAL de UI): AP-28, AP-29, AP-30, AP-31, AP-32, AP-33, AP-34, AP-10, AP-11, AP-12.
10. **Controles de consistencia**: CS-02, CS-03, CS-04, CS-06, CS-09, CS-11, CS-14.

## Conteo de escenarios

| Sección | Originales | Descartados (2026-10-28) | Nuevos | Vigentes |
| --- | --- | --- | --- | --- |
| 1. Coexistencia (CO) | 28 | 1 (CO-15) | 0 | 27 |
| 2. Rechazos (RZ) | 28 | 0 | 6 (RZ-29 a RZ-34) | 34 |
| 3. Cambio de monto y fecha (RA) | 26 | 1 (RA-15) | 3 (RA-27 a RA-29) | 28 |
| 4. Ventana y renovación (JB) | 24 | 9 (JB-01, 02, 10, 11, 12, 13, 14, 16, 18) | 12 (JB-25 a JB-36) | 27 |
| 5. Aprobaciones (AP) | 19 | 2 (AP-03, AP-15) | 17 (AP-20 a AP-36) | 34 |
| 6. Consistencia (CS) | 13 | 0 | 1 (CS-14) | 14 |
| 7. Piloto (PI) | 10 | 0 | 1 (PI-11) | 11 |
| **Total** | **148** | **13** | **40** | **175** |

## Estado de cada punto bloqueante

| Punto | Tema | Estado | Fecha |
| --- | --- | --- | --- |
| 1 | Suscripción de prueba en sandbox con cobros automáticos futuros (receta CT-CO-AUTO) | Pendiente de crear | — |
| 2 | Diseño de aprobaciones (aprobadores configurables, hoy solo admin; autoaprobación activada y auditada; doble aprobación configurable y apagada; bandeja, vista previa, comentario e historial) | Decidido | 2026-10-28 |
| 3 | Tarjetas de sandbox (confirmar que el sandbox ejecuta cobros, CT-00, y medir rechazos reales de T3/T5/T7) | Pendiente | — |
| 4 | Horizonte y reposición: horizonte de 12 meses solo al aplicar un cambio; sin job de reposición; chequeo diario de solo lectura con aviso a N = 60 días | Resuelto | 2026-10-28 (revisa la decisión del 2026-10-27) |
| 5 | Rechazos: el CRM no crea cobros ni suspende; solo reintenta (`retry_charge`) y gestiona; racha como ayuda opcional | Resuelto | 2026-10-28 (revisa la decisión del 2026-10-27) |
| 6 | Ventana de 31 días: solo dentro de un cambio; más de 31 días → revisión manual en la solicitud | Resuelto | 2026-10-28 (revisa la decisión del 2026-10-27) |

> Nota: la numeración de los puntos 4 a 6 sigue el orden de las decisiones de diseño de este documento (horizonte, rechazos, ventana). Si la lista original de bloqueantes usaba otro orden, ajustar solo los números.

Decisiones que siguen abiertas (no bloquean el piloto): RZ-13 (si el límite del comercio cuenta para la racha), RZ-17 (pausa y racha), JB-09 (dos meses sin cubrir: espaciar o no).
