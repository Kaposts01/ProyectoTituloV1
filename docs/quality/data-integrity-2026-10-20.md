# DATA-01 — Integridad de atributos y asociaciones VirtualPOS

Fecha: 2026-10-20. Rama local: codex/estabilizacion-synkmetrix.

## Resultado

La restriccion de core_client_attributes incluye ahora client_id, source, attribute_type y attribute_value. Conserva el nombre de constraint usado por los cuatro ETL. Dos clientes pueden compartir valores sin que el segundo desaparezca por ON CONFLICT DO NOTHING. NULLS NOT DISTINCT conserva la idempotencia de observaciones sin client_id; no crea una identidad por atributo ni fusiona personas.

La migracion 0032 modifica solo la restriccion y conserva filas. El downgrade verifica primero si existen atributos compartidos y se bloquea antes de tocar la restriccion cuando la forma anterior no puede representarlos. No elimina datos para resolver incompatibilidades. Las migraciones anteriores siguen intactas.

VirtualPOS usa el identificador externo de cliente explicito cuando esta presente. Un ID no resuelto deja client_id nulo y no recurre al RUT. Cuando no hay ID explicito, el fallback previo por RUT se limita a una coincidencia unica dentro de la cuenta. Un RUT compartido no selecciona al primer cliente y no genera candidatos automaticos de suscripcion para pagos. La proteccion previa contra varias suscripciones por RUT se conserva.

## Evidencia

- Suite completa en PostgreSQL aislado: 296 passed, 18.85 s. Dos avisos en esa ejecucion: deprecacion Starlette/httpx y configuracion de ruta Alembic en la prueba nueva. Se explicito path_separator en la configuracion de esa prueba; la suite focalizada posterior pasa 13 casos sin avisos.
- Pruebas de los cuatro ETL conservan email compartido para dos clientes y confirman idempotencia.
- Casos VirtualPOS: RUT unico/compartido, cuentas separadas, ID externo conocido/desconocido y exclusiones del indice de pagos.
- Prueba de migracion sobre tabla temporal poblada: preservacion de IDs, upgrade/downgrade compatible y bloqueo de downgrade incompatible sin perder filas.
- Ruff global y git diff --check pasan. Alembic check no detecta operaciones pendientes en la base aislada en 0032.
- Base local crm actualizada de 0031 a 0032 con respaldo previo en .local/backups/crm-before-0032-20261020-192206.dump (20.293.977 bytes). El respaldo no se ensayo mediante restauracion.
- Auditoria agregada previa: cinco claves plataforma/RUT ambiguas en vp_clients; core_client_attributes, core_subscriptions y core_payments tenian cero filas. No se imprimieron valores personales.

## Alcance y limites

No se ejecuto ETL ni backfill sobre datos operativos, no se fusionaron clientes y no se reasignaron relaciones existentes. Los upserts actuales conservan las asociaciones historicas ya insertadas. En otras bases con atributos descartados anteriormente, la migracion sola no los reconstruye: requiere un reprocesamiento controlado desde staging. Los casos ambiguos historicos necesitan auditoria y revision; no se corrigen mediante seleccion automatica.

No se cambiaron frontend ni contratos externos. Entorno de prueba: PostgreSQL 18 y Python 3.14.7; CI declara PostgreSQL 17 y Python 3.14.5. Context7 no estaba disponible; se consultaron fuentes oficiales para la semantica de NULLS NOT DISTINCT: [PostgreSQL 17](https://www.postgresql.org/docs/17/sql-createtable.html) y [SQLAlchemy](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html). Se verifico ademas la implementacion mediante PostgreSQL y Alembic instalados.
