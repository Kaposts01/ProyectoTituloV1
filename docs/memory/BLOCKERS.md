# Bloqueos

## Integraciones

**Status: Accepted**

- Payku presenta limitaciones para recuperar cierto historial de transacciones; los filtros de fecha pueden devolver cero registros y la lectura completa puede exceder el timeout.
- VirtualPOS puede responder de forma no JSON durante la lectura de cargos, por lo que no se puede asumir que el historial local este completo.
- Algunas suscripciones historicas de VirtualPOS no tienen cargos recuperables por la ruta disponible del proveedor.
- Payku no permite certificar una sincronizacion historica integral: la implementacion usa transacciones embebidas y los filtros del endpoint historico siguen sin validacion confiable del proveedor.

## Decisiones necesarias

**Status: TBD**

- No existe contrato transversal para liquidaciones.
- No esta definido el gobierno de conflictos para datos personales.

## Entorno local

**Status: Accepted**

- Algunos procesos locales requieren privilegios elevados para identificacion o detencion.
- La posible inconsistencia entre `POSTGRES_USER` y el usuario del healthcheck debe revisarse como deuda tecnica.

Detalle operativo y evidencia: [tasks.md](../tasks.md).
