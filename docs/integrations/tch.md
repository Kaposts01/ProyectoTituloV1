# TCH

TCH representa mandatos de debito bancario cargados desde reportes Excel locales. No existe una API externa ni sincronizacion remota para este canal.

El canal conserva clientes, suscripciones, transacciones y control de recaudacion mensual historicos. El plan de origen se conserva en [el plan ETL TCH historico](../history/tch/2026-09-etl-plan.md); algunas propuestas de ese documento son anteriores a la implementacion actual y no deben tomarse como esquema vigente sin validacion.

El ETL conserva la proyeccion TCH en PostgreSQL y sanea los payloads Raw de credenciales de pago, PAN y numeros de cuenta. Una carga `full` reconstruye la proyeccion en una unica transaccion para no dejarla vacia o parcial si un archivo falla.

## Importacion administrativa

- **Confirmed:** El rol `admin` puede importar un unico reporte `.xlsx` desde Administracion > Sincronizacion mediante `POST /api/v1/tch/import-report`.
- La importacion es incremental, se ejecuta en segundo plano y queda trazada en `etl_runs` con el canal `tch`.
- El archivo se almacena solo en una ubicacion temporal durante el ETL y se elimina al finalizar, incluso si el procesamiento falla.
- La ruta requiere sesion autenticada y token CSRF. Otros roles reciben `403` y no ven el control de importacion.
- El limite de carga es 250 MiB. El tipo MIME declarado por el navegador no se considera una prueba del contenido; el ETL valida la estructura del reporte.

El dashboard calcula altas, bajas, suscripciones activas acumuladas y churn mensual desde las fechas de activación y eliminación disponibles en la proyección ETL. Los resultados de recaudación usan los controles mensuales cuando existen; de lo contrario usan las transacciones cargadas.
