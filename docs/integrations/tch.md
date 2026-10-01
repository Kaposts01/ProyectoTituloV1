# TCH

TCH representa mandatos de debito bancario cargados desde reportes Excel locales. No existe una API externa ni sincronizacion remota para este canal.

El canal conserva clientes, suscripciones, transacciones y control de recaudacion mensual historicos. El plan de origen se conserva en [ETL_PLAN_CRM_SUBSCRIPCIONES.md](../ETL_PLAN_CRM_SUBSCRIPCIONES.md); algunas propuestas de ese documento son anteriores a la implementacion actual y no deben tomarse como esquema vigente sin validacion.

El ETL conserva la proyeccion TCH en PostgreSQL y sanea los payloads Raw de credenciales de pago, PAN y numeros de cuenta. Una carga `full` reconstruye la proyeccion en una unica transaccion para no dejarla vacia o parcial si un archivo falla.

El dashboard calcula altas, bajas, suscripciones activas acumuladas y churn mensual desde las fechas de activación y eliminación disponibles en la proyección ETL. Los resultados de recaudación usan los controles mensuales cuando existen; de lo contrario usan las transacciones cargadas.
