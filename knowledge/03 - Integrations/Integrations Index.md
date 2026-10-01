# Integrations Index

| Integracion | Mecanismo de ingesta | Estado | Autenticacion | Escrituras | Webhooks | Referencia |
| --- | --- | --- | --- | --- | --- | --- |
| VirtualPOS | API mediante sincronizacion paginada | Implementada, con limitacion de historial de cargos | Firma JWT HS256 en backend | Si, mediante rutas internas autorizadas | Documentados; implementacion no encontrada | [Ficha](../../docs/integrations/virtualpos.md) |
| Toku | API mediante sincronizadores con reintentos | Implementada | API key solo en backend | Si, controladas por permisos y CSRF | IMPLEMENTACION NO ENCONTRADA | [Ficha](../../docs/integrations/toku.md) |
| Payku | API para clientes, planes, suscripciones y transacciones | Parcial para historial de transacciones | Autorizacion y firma en backend | Si, mediante rutas internas autorizadas | IMPLEMENTACION NO ENCONTRADA | [Ficha](../../docs/integrations/payku.md) |
| TCH | Reportes Excel locales | Implementada, sin sincronizacion remota | No aplica | No se documentan escrituras a proveedor | No aplica | [Ficha](../../docs/integrations/tch.md) |

Las credenciales no se entregan al navegador. Cada canal conserva staging trazable y las operaciones mutables pasan por la API interna.

## Referencias tecnicas

- [Arquitectura de integraciones](../../docs/architecture/integrations.md)
- [Flujo de datos](../../docs/architecture/data-flow.md)
