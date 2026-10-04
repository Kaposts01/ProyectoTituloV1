# Plan de consolidacion de BDlocales

> **Estado: completado y cerrado (2026-09-15).** Los datos ya viven en `crm`.
> Se retiraron `app/services/bdlocales_sync.py`, `bdlocales_import.py`,
> `etl_consolidation.py`, `etl_orchestration.py` y los scripts
> `scripts/import_bdlocales.py`/`inspect_bdlocales.py`, junto con las
> variables `VIRTUALPOS_DB_URL`, `TOKU_DB_URL` y `PAYKU_DB_URL`. Las tres
> BDlocales (`VirtualPOS_Local`, `Toku_Local`, `Payku_Local`) ya no son
> requisito de ejecucion; este documento queda como registro historico de
> la decision y el proceso de migracion.

## Decision

Se migraran los datos ya sincronizados desde `BDlocales` a la unica base
`crm`. No se ejecutara una sincronizacion completa contra proveedores: las
tres bases locales contienen 354.921 registros y la lectura remota demora
horas. La sincronizacion posterior sera incremental y escribira directamente
en la base central.

| Canal | Registros locales | Tablas destino |
| --- | ---: | --- |
| VirtualPOS | 260.179 | `vp_*` |
| Payku | 58.338 | `p_*` |
| Toku | 36.404 | `tk_*` |

TCH ya reside en `crm` con tablas `tch_*` y queda fuera de esta migracion.

## Estado encontrado

- `BDlocales` mantiene tres PostgreSQL activos en los puertos 5434, 5435 y
  5436; se usaran unicamente como fuente de lectura durante la migracion.
- La base central no esta iniciada actualmente.
- Existen tablas de canal parcialmente implementadas: `vp_*`, `toku_*` y
  `payku_*`. Las dos ultimas no respetan los prefijos solicitados `tk_*` y
  `p_*`.
- Coexisten dos ETL: el historico desde BDlocales a entidades centralizadas y el
  nuevo desde tablas de canal a entidades centralizadas. Se retirara el primero
  una vez validado el nuevo flujo, para mantener una sola ruta de datos.

## Implementacion

1. Crear una migracion Alembic que renombre `toku_*` a `tk_*` y `payku_*` a
   `p_*`, incluidos indices y restricciones. Actualizar modelos, servicios y
   pruebas con los nuevos nombres.
2. Agregar `platform` a cada tabla `vp_*` y hacer sus claves unicas por
   `(platform, external_id)`. VirtualPOS tiene dos cuentas y sus IDs no se
   deben mezclar. Las entidades centralizadas conservaran `virtualpos1` y
   `virtualpos2` como `source`.
3. Implementar un importador read-only desde las tres BDlocales a las tablas
   de canal. Leera por lotes, saneando cada `raw_payload` antes de persistir.
   Se eliminaran PAN, CVV/CVC, tokens, BIN, codigos de autorizacion y campos
   equivalentes de tarjeta. Los upserts haran el proceso repetible.
4. Consolidar desde `vp_*`, `tk_*` y `p_*` hacia las entidades centralizadas en
   orden clientes, planes, suscripciones, cargos, metodos de pago y pagos.
   Se corregiran las relaciones para conservar el canal y la cuenta de origen.
5. Unificar las sincronizaciones read-only para que actualicen las tablas de
   canal de `crm` y luego ejecuten esta consolidacion. Las BDlocales dejaran
   de ser requisito de ejecucion, pero se mantendran sin cambios hasta pasar
   la validacion y contar con un respaldo.
6. Mantener los contratos actuales del frontend (`/api/v1/staging/*`) y sus
   filtros, orden global, paginacion y fichas. El cambio sera interno a las
   consultas y no alterara la experiencia del CRM.

## Validacion y corte

1. Respaldar las tres BDlocales y registrar sus conteos por tabla.
2. Levantar `crm`, aplicar Alembic e importar un canal de prueba en una
   transaccion controlada.
3. Comparar conteos, IDs distintos, relaciones y muestras de cada recurso
   entre origen y destino. Verificar explicitamente que no hay campos de
   tarjeta sensibles en `raw_payload` central.
4. Ejecutar la importacion completa y repetirla: la segunda ejecucion debe
   conservar los conteos sin duplicados.
5. Ejecutar `python -m pytest`, `ruff check app tests alembic scripts` y la
   compilacion del frontend. Validar en el navegador las tablas, fichas,
   filtros, orden y metricas por los tres canales.
6. Solo despues de esa validacion, configurar la sincronizacion incremental
   central y marcar la consolidacion como completada.
