# Payku

Payku aporta clientes, planes, suscripciones y transacciones. Su integracion usa autenticacion de backend con cabeceras de autorizacion y firma.

**Observed 2026-10-01:** la sincronizacion actual obtiene transacciones embebidas en las suscripciones. No usa `/api/transaction` ni presenta reanudacion por pagina, porque los filtros historicos observados no son confiables. Esta fuente no certifica por si sola la completitud historica; su cobertura, orden y paginacion siguen `TBD` hasta validacion con el proveedor. Un envelope invalido o mas de 2.000 paginas termina la sincronizacion como fallida.

La lectura de transacciones historicas tiene una limitacion documentada: los filtros de fecha pueden devolver cero registros y la coleccion completa puede requerir un timeout local mayor. Las escrituras internas requieren `PAYKU_WRITES_ENABLED=true`.

**Observed:** algunas transacciones históricas usan `transaction` como identificador y no incluyen `id`; el conector las materializa con ese valor. `scripts/maintenance/backfill_payku_transactions.py` permite reconstruir `p_transactions` desde los `source_records` existentes sin consultar al proveedor; después debe ejecutarse el ETL normal para actualizar `payments`.

El dashboard calcula la actividad de cobros desde `created_at` de las transacciones, y altas, bajas, suscripciones activas acumuladas y churn mensual desde `start`, `end` y estados terminales fechados. El selector anual considera todas esas series fechadas. Estos indicadores describen únicamente la cobertura cargada localmente y no certifican el historial completo del proveedor.

## Webhooks

**Confirmed:** Payku puede enviar callbacks `POST` de pagos únicos mediante `urlnotify` y de suscripciones mediante `url_notify_suscription` y `url_notify_payment`. Los payloads incluyen identificadores de transacción o suscripción y, para cobros, `verification_key`. La API de consulta mantiene la referencia para reconciliar el estado recibido.

**TBD:** Payku no documenta la verificación de autenticidad del callback, firma entrante, identificador único de entrega, orden, reintentos ni tiempo de espera. La cabecera `Sign` corresponde a solicitudes salientes a la API y no se debe reutilizar como prueba de autenticidad del callback. No se implementará un receptor de Payku hasta verificar un control de autenticidad con el proveedor.

Fuentes oficiales: [transacciones](https://docs.payku.com/cl/api/transaction/), [suscripciones](https://docs.payku.com/cl/api/subscriptions/), [firma de solicitudes API](https://docs.payku.com/cl/signature/) y [sandbox](https://docs.payku.com/cl/api-access/).
