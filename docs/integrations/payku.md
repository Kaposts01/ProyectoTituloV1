# Payku

Payku aporta clientes, planes, suscripciones y transacciones. Su integracion usa autenticacion de backend con cabeceras de autorizacion y firma.

**Observed 2026-10-01:** la sincronizacion actual obtiene transacciones embebidas en las suscripciones. No usa `/api/transaction` ni presenta reanudacion por pagina, porque los filtros historicos observados no son confiables. Esta fuente no certifica por si sola la completitud historica; su cobertura, orden y paginacion siguen `TBD` hasta validacion con el proveedor. Un envelope invalido o mas de 2.000 paginas termina la sincronizacion como fallida.

La lectura de transacciones historicas tiene una limitacion documentada: los filtros de fecha pueden devolver cero registros y la coleccion completa puede requerir un timeout local mayor. Las escrituras internas requieren `PAYKU_WRITES_ENABLED=true`.

**Observed:** algunas transacciones históricas usan `transaction` como identificador y no incluyen `id`; el conector las materializa con ese valor. `scripts/maintenance/backfill_payku_transactions.py` permite reconstruir `p_transactions` desde los `source_records` existentes sin consultar al proveedor; después debe ejecutarse el ETL normal para actualizar `payments`.

El dashboard calcula la actividad de cobros desde `created_at` de las transacciones, y altas, bajas, suscripciones activas acumuladas y churn mensual desde `start`, `end` y estados terminales fechados. El selector anual considera todas esas series fechadas. Estos indicadores describen únicamente la cobertura cargada localmente y no certifican el historial completo del proveedor.

## Estructura operacional

La documentacion operacional detallada esta organizada en [docs/integrations/payku/README.md](payku/README.md).

Incluye 13 flujos paso a paso y 23 documentos de recursos (contratos de API, autenticacion, paginacion, errores, data model, open-questions, productos adicionales).

### Preguntas abiertas criticas

| Clave | Descripcion | Impacto |
|---|---|---|
| **Q-06** | No confirmado si los cobros de suscripcion aparecen en `/api/transaction` y en la conciliacion con la misma clave que en `paid[]`. | El seguimiento de cobros no puede enlazar ciclos con conciliacion de forma confiable. |
| **Q-08** | La clave estable del cobro no esta documentada. `paid[].transactions[]` no esta especificado. | El job de seguimiento no puede enlazar ciclo <-> cobro de forma determinista. |
| **Q-27** | Plan variable: no se sabe si cobra al activarse la suscripcion nueva (afecta cambiar-monto camino B). | Riesgo de doble cobro o mes sin cobro al cambiar monto por API. |
| **Q-29** | No confirmado si `POST /api/suinscriptionscards` genera una `url` nueva para una suscripcion en estado `register`. | El link de inscripcion para un alta pendiente depende de este comportamiento. |

## Webhooks

**Confirmed:** Payku puede enviar callbacks `POST` de pagos únicos mediante `urlnotify` y de suscripciones mediante `url_notify_suscription` y `url_notify_payment`. Los payloads incluyen identificadores de transacción o suscripción y, para cobros, `verification_key`. La API de consulta mantiene la referencia para reconciliar el estado recibido.

**TBD:** Payku no documenta la verificación de autenticidad del callback, firma entrante, identificador único de entrega, orden, reintentos ni tiempo de espera. La cabecera `Sign` corresponde a solicitudes salientes a la API y no se debe reutilizar como prueba de autenticidad del callback. No se implementará un receptor de Payku hasta verificar un control de autenticidad con el proveedor.

Fuentes oficiales: [transacciones](https://docs.payku.com/cl/api/transaction/), [suscripciones](https://docs.payku.com/cl/api/subscriptions/), [firma de solicitudes API](https://docs.payku.com/cl/signature/) y [sandbox](https://docs.payku.com/cl/api-access/).
