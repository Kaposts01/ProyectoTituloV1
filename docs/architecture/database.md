# Base de Datos

## Principio central

**Status: Accepted**

PostgreSQL es la fuente central de verdad. Alembic administra el esquema desplegado; los proveedores no escriben directamente en tablas Core.

## Capas conceptuales

**Status: Proposed**

- Staging / Raw independiente por proveedor.
- Core independiente de proveedor para cliente, suscripcion, cobro programado o cuota, pago o transaccion, liquidacion, plan y plataforma.
- Trazabilidad hacia el identificador externo, registro raw y transformacion que originan cada dato Core.
- Registros operativos para sincronizaciones, ETL y escrituras autorizadas.

## Estado actual observado

**Status: Accepted**

Existen `source_records`, ejecuciones de sincronizacion, ETL y escritura, entidades centralizadas iniciales y tablas de canal. La consolidacion de antiguas BD locales se cerro; no deben reintroducirse en el flujo vivo sin una decision nueva.

## Identidad

**Status: Accepted**

CLIENTE usara un identificador interno estable y podra relacionarse con identidades externas trazables por fuente. RUT, email y telefono son atributos personales y senales de comparacion, no claves transversales. La vinculacion transversal inicial basada en atributos personales requiere revision manual; cualquier merge debe ser auditado y reversible. El esquema fisico y el gobierno de datos personales siguen pendientes. Vease [ADR-001](../decisions/ADR-001-identidad-centralizada-socios.md).
