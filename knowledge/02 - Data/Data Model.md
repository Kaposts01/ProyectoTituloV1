# Data Model

## Capas de datos

- **Raw / staging:** `source_records` conserva respuestas saneadas, fuente, tipo de recurso e identificador externo. La clave `(source, resource_type, external_id)` respalda la idempotencia.
- **Tablas por canal:** VirtualPOS, Toku, Payku y TCH conservan estructuras operativas propias antes de la consolidacion.
- **Entidades CRM iniciales:** clientes, planes, suscripciones, cargos, pagos y metodos de pago centralizan consultas operativas sin reemplazar los identificadores de origen.
- **Seguridad:** usuarios, roles, permisos y sus relaciones soportan el acceso controlado.
- **Trazabilidad operativa:** `sync_runs`, `etl_runs`, `write_runs` y recuperaciones registran ejecuciones y operaciones autorizadas.

## Problemas abiertos

- La identidad centralizada esta aceptada conceptualmente, pero su esquema fisico, matching, revision y merge reversible siguen pendientes.
- Varias relaciones se resuelven mediante identificadores externos y contexto verificable, no con relaciones transversales completas.
- La trazabilidad desde consolidacion hacia el registro raw no esta completamente determinada para todos los flujos.
- La taxonomia transversal de estados, periodicidad, montos, monedas y zonas horarias permanece pendiente.

## Referencias tecnicas

- [Modelo centralizado](../../docs/data/centralized-model.md)
- [Cliente o socio](../../docs/data/cliente.md)
- [Suscripcion](../../docs/data/suscripcion.md)
- [Pago y cobro programado](../../docs/data/pago.md)
- [ADR-001](../../docs/decisions/ADR-001-identidad-centralizada-socios.md)
- [Base de datos](../../docs/architecture/database.md)
