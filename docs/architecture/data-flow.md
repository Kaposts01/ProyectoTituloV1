# Flujo de Datos

## Flujo objetivo

**Status: Proposed**

```text
Fuente externa -> Connector -> Staging / Raw -> ETL / Normalizacion -> PostgreSQL Core -> API -> CRM, reportes y analytics
```

Cada connector lee o usa exclusivamente los flujos de escritura internos autorizados. Staging conserva el contexto de origen; ETL transforma hacia conceptos Core sin que el proveedor escriba directamente en ellos.

## Flujo implementado observado

**Status: Accepted**

VirtualPOS, Toku y Payku persisten respuestas saneadas en `source_records` usando la clave `(source, resource_type, external_id)`. `sync_runs` registra sincronizaciones y `write_runs` operaciones autorizadas. TCH carga reportes Excel en sus tablas propias.

Los datos de tarjeta y seguridad conocidos se eliminan antes de persistir staging. La relacion entre entidades solo se materializa cuando hay identificadores o contexto verificable.
