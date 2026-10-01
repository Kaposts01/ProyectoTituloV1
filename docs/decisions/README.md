# Registro de Decisiones

Las decisiones vigentes observadas son:

- PostgreSQL es la base de datos operativa y Alembic controla su esquema.
- `source_records` conserva staging saneado y trazable con upsert idempotente.
- Los proveedores se consultan desde backend; el navegador no recibe credenciales.
- Las escrituras requieren rutas internas, permisos, CSRF y una bandera local por proveedor.
- TCH se carga desde reportes locales, no desde una API externa.
- La consolidacion de antiguas BD locales por canal esta cerrada.

Las decisiones nuevas deben crearse como notas fechadas en este directorio y enlazarse desde este indice.

## ADRs

- [ADR-001 - Identidad centralizada de socios](ADR-001-identidad-centralizada-socios.md) - estrategia de UUID interno, identidades externas trazables, matching conservador y merge reversible.
