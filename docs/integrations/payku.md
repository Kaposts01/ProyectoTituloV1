# Payku

Payku aporta clientes, planes, suscripciones y transacciones. Su integracion usa autenticacion de backend con cabeceras de autorizacion y firma.

**Observed 2026-10-01:** la sincronizacion actual obtiene transacciones embebidas en las suscripciones. No usa `/api/transaction` ni presenta reanudacion por pagina, porque los filtros historicos observados no son confiables. Esta fuente no certifica por si sola la completitud historica; su cobertura, orden y paginacion siguen `TBD` hasta validacion con el proveedor. Un envelope invalido o mas de 2.000 paginas termina la sincronizacion como fallida.

La lectura de transacciones historicas tiene una limitacion documentada: los filtros de fecha pueden devolver cero registros y la coleccion completa puede requerir un timeout local mayor. Las escrituras internas requieren `PAYKU_WRITES_ENABLED=true`.

**Observed:** algunas transacciones históricas usan `transaction` como identificador y no incluyen `id`; el conector las materializa con ese valor. `scripts/maintenance/backfill_payku_transactions.py` permite reconstruir `p_transactions` desde los `source_records` existentes sin consultar al proveedor; después debe ejecutarse el ETL normal para actualizar `payments`.

El dashboard calcula la actividad de cobros desde `created_at` de las transacciones, y altas, bajas, suscripciones activas acumuladas y churn mensual desde `start`, `end` y estados terminales fechados. El selector anual considera todas esas series fechadas. Estos indicadores describen únicamente la cobertura cargada localmente y no certifican el historial completo del proveedor.
