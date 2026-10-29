# Bloqueos

## Integraciones

**Status: Accepted**

- Observed 2026-10-20, cuenta local Toku: `/organization/payments` devuelve HTTP 404 y bloquea la sincronizacion estandar completa. Se cargaron y consolidaron los otros cinco recursos mediante una ejecucion acotada que registra la exclusion; el contrato de pagos requiere confirmacion/correccion antes de certificar cobertura financiera.

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

- Confirmed 2026-10-20: Docker Desktop no inicia su motor Linux por `HCS_E_HYPERV_NOT_INSTALLED`; WSL informa virtualizacion no habilitada. PostgreSQL 17 de Compose sigue bloqueado. El arranque local de la API quedo resuelto con autorizacion del usuario mediante PostgreSQL 18 nativo aislado en `127.0.0.1:5433`, sin modificar bases existentes.

- Algunos procesos locales requieren privilegios elevados para identificacion o detencion.
- La posible inconsistencia entre `POSTGRES_USER` y el usuario del healthcheck debe revisarse como deuda tecnica.

Detalle operativo y evidencia: [tasks.md](../tasks.md).

## 2026-10-29 — Entrega sprint-5

- Una instalacion nueva falla en migracion historica 0035 por `op.Column`; CI backend queda bloqueado antes de tests. Se conserva la revision publicada por regla de inmutabilidad. Pendiente decision de reparacion historica.
- La antigua base local con revision de atributos 0032 tiene una cadena distinta de la publicada (0032 source_status); requiere reconciliacion explicita y respaldo antes de cualquier upgrade. No se modifico la base operativa.
- Evidencia: [entrega sprint-5](../quality/sprint-5-delivery-2026-10-29.md).
