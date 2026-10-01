# Seguridad

## Principios

**Status: Accepted**

- Credenciales y API keys no se almacenan en Git ni se entregan al navegador.
- Los datos raw se sanean antes de persistirse; no se almacenan PAN, CVV/CVC ni codigos de seguridad.
- Los proveedores operan por Connectors y API interna, nunca contra tablas Core de forma directa.
- Las transformaciones y escrituras autorizadas deben dejar trazabilidad.

## Controles observados

**Status: Accepted**

Las rutas internas usan sesion con cookie HttpOnly, CSRF para operaciones mutables y permisos por usuario, rol, canal y operacion. Las escrituras de proveedor requieren una bandera local explicita. FastAPI es el control definitivo; el frontend solo complementa la experiencia.

## Pendiente

**Status: TBD**

Definir politicas de retencion, rectificacion y eliminacion de datos personales, junto con el gobierno de conflictos de identidad.
