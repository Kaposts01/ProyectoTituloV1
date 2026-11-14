# Motivo y monto de un cobro rechazado (CRM-15C)

Qué entrega Payku sobre un cobro de suscripción rechazado, qué no entrega y cómo lo muestra el CRM.
Revisión del 2026-11-13: documentación oficial (`payku-docs-es.md`), reportes descargados del portal y cinco
lecturas `GET` a producción (solo nombres de campos y si vienen vacíos; sin datos personales).

## 1. Dónde está cada dato

| Fuente | Motivo del rechazo | Monto del intento | Período / ciclo |
| --- | --- | --- | --- |
| `GET /api/sususcription/{id}` (V1, lo que guarda el sync) → `transactions[]` | No. Claves: `created_at`, `amount`, `transaction`, `authorization_code`, `order`, `description`, `status`. | `amount` = **0** en la mayoría de los rechazados (≈75 % en producción). | No trae `paid[]`. |
| `GET /api/sususcription/{id}` → `last_status_current_payment` | Solo el **último** estado de cobro de la suscripción (`maximum attempt limit`, `first payment rejected`, `payment consumes failed`). | No. | No. |
| `GET /api/sususcription/{id}` → `logs.status[]` | No: cambios de estado de la suscripción (`initial_status`, `final_status`, `change_date`). | No. | No. |
| `GET /api/sususcriptionv3` → `paid[]` | No (estado del ciclo). | `amount_paid`. | `payment_cycle_day`, `try_number`. En producción respondió «there are no records» para la consulta probada. |
| `GET /api/transaction/{id}` y `GET /api/transaction?rejected=true` | **Sí**: `gateway_response.status = rejected` y `gateway_response.message` = **un código** con forma `-N` (p. ej. `-11 `, con espacio final). En una muestra de 100 rechazos de oct–nov 2026 los 100 traían código y ninguno uno de los siete textos que lista la documentación. | **Sí**: `amount` > 0 también en transacciones que la suscripción informa con 0. | No. |
| Webhook `urlnotifypayment` | No: solo `transaction_id`, `verification_key`, `order`, `status`, `subscriptions`. | No. | No. |
| Reportes del portal (`Payku_dataTransacciones`, `Payku_reporte_consolidado_*`) | No: solo transacciones pagadas, liquidaciones y monedero; sin columna de estado ni de motivo. | Solo de pagos aprobados. | No. |

## 2. Lo que Payku no entrega

1. **Glosa del código de rechazo.** `gateway_response.message` trae un código numérico negativo, pero la documentación de
   Payku solo lista siete textos (`Rechazo de transacción.`, `Excede cupo máximo mensual.`, …) y no publica el catálogo
   de códigos. Los códigos tienen la misma forma que los de Transbank que usa VirtualPOS, pero el proyecto no inventa
   glosas (d120): el CRM guarda y muestra el código tal cual hasta que Payku (o una decisión explícita) documente el
   catálogo.
2. **Motivo en el listado de suscripciones.** El sync lee `transactions[]` de la suscripción, que no trae
   `gateway_response`. Para tener el código hay que leer `GET /api/transaction/{id}` por cada rechazo (PK-PAR-05:
   ~8.600 lecturas, con pausa; bloqueada por decisión del usuario).
3. **Monto del intento en el listado.** El listado lo informa en 0; el monto real solo está en `GET /api/transaction/{id}`.
4. **Ciclos (`paid[]`).** El endpoint V1 no los trae; sin ciclos no hay `p_cycles` ni `core_charges` de Payku, por eso no
   hay período de ciclo.

## 3. Cómo lo muestra el CRM

- **Motivo** (`core_payments.rejection_code` / `rejection_reason`):
  1. código de `gateway_response.message` cuando el payload guardado lo trae (`payku_gateway_rejection`; queda listo para
     PK-PAR-05, hoy ningún `p_transactions.raw_payload` lo tiene);
  2. respaldo PK-PAR-06: `last_status_current_payment` solo en el rechazo más reciente de cada suscripción
     (requiere correr el ETL Core de Payku);
  3. si no hay nada: «No informado por Payku».
- **Monto** (vista de rechazos del recuperador): el del intento si es > 0; si no, el monto vigente de la suscripción
  (`amount_source = subscription`); si tampoco hay, vacío (nunca $0).
- **Período**: el del ciclo enlazado; si no hay ciclo, el mes (hora de Chile) del intento (`period_source = attempt`).
