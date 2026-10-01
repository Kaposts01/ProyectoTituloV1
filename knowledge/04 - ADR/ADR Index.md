# ADR Index

## ADR existentes

| Identificador | Titulo | Estado | Descripcion |
| --- | --- | --- | --- |
| [ADR-001](../../docs/decisions/ADR-001-identidad-centralizada-socios.md) | Identidad centralizada de socios | Accepted | Define CLIENTE con identificador interno, identidades externas trazables, matching conservador y merges manuales reversibles. |

## Decisiones importantes aun sin ADR

- PostgreSQL es la fuente central de verdad.
- Cada proveedor conserva staging independiente y trazable.
- APScheduler ejecuta la sincronizacion diaria de canales.
- El acceso aplica RBAC y sesion con cookie JWT/CSRF.
- Las escrituras de proveedores se exponen solo mediante flujos internos autorizados y banderas locales.

Estas decisiones se describen en la documentacion vigente, pero no tienen un ADR individual encontrado.

## Referencias tecnicas

- [Indice de decisiones](../../docs/decisions/README.md)
- [Estado del proyecto](../../docs/memory/PROJECT_STATE.md)
- [Seguridad](../../docs/architecture/security.md)
