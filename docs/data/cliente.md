# Cliente o Socio

**Status: Proposed**

CLIENTE representa la entidad interna de socio o donante. Debe poder relacionarse con multiples suscripciones y con multiples identificadores externos sin depender de que exista RUT, email o telefono.

## Identidad

**Status: Accepted**

- CLIENTE usa un identificador interno estable y puede tener multiples identidades externas, incluso dentro de la misma plataforma.
- Una identidad externa conserva fuente, identificador externo y trazabilidad al registro de staging; no presupone una tabla fisica con un nombre determinado.
- RUT, email y telefono son atributos personales normalizables y senales de matching. No son claves primarias ni prueban por si solos una identidad transversal.
- Las coincidencias transversales se revisan manualmente en la fase inicial. Los merges requieren evidencia, auditoria y capacidad de reversion.

Vease [ADR-001](../decisions/ADR-001-identidad-centralizada-socios.md) para la politica de matching, conflictos de fuentes y reversibilidad.

## Estado actual observado

**Status: Accepted**

El CRM conserva clientes por origen. El RUT participa en algunas relaciones internas de canal, pero no implementa deduplicacion global.
