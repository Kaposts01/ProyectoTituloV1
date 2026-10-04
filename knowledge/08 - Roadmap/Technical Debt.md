# Technical Debt

Esta nota resume deuda documentada o comprobable. La prioridad refleja el sentido de las fuentes y riesgos existentes; no constituye una nueva decision tecnica.

### Critica

- La identidad centralizada aceptada por ADR-001 no tiene aun esquema fisico, revision manual, merge reversible ni gobierno de atributos personales implementados.

### Alta

- `tch_clientes` impone unicidad sobre RUT, en tension con la politica de identidad centralizada que no trata RUT como clave transversal.
- El historial de cargos VirtualPOS puede estar incompleto para algunas suscripciones.
- Payku no recupera de forma confiable parte del historial de transacciones.
- La taxonomia transversal de estados, montos, monedas y periodicidad sigue pendiente.

### Media

- Conviven materializacion legacy y consolidacion por canal; la transicion completa no esta determinada.
- Las relaciones operativas dependen en parte de IDs externos y contexto de origen.
- La trazabilidad de todos los datos consolidados hacia `source_records` no esta completamente determinada.
- El scheduler puede terminar con errores por canal sin representar un fallo total de la ejecucion.
- La cobertura de pruebas frontend sigue pendiente; existe CI para backend y frontend, pero la base actual no supera todas sus verificaciones.
- Documentacion historica y actual puede ser contradictoria.

### Baja

- `compose.yaml` permite configurar un usuario PostgreSQL mientras su healthcheck consulta otro usuario.
- Context7 tiene configuraciones separadas para OpenCode y Claude sin una responsabilidad de mantenimiento definida.

## Referencias tecnicas

- [Estado del proyecto](../../docs/memory/PROJECT_STATE.md)
- [Bloqueos](../../docs/memory/BLOCKERS.md)
- [ADR-001](../../docs/decisions/ADR-001-identidad-centralizada-socios.md)
- [Modelo centralizado](../../docs/data/centralized-model.md)
- [Modelo TCH](../../app/models/tch.py)
- [Tareas operativas](../../docs/tasks.md)
