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

## Validacion del checkout local 2026-11-18

- Resueltos: PostgreSQL 18 local arrancado y uso explicito de IPv4; snapshots React estabilizados (1.464 pruebas frontend pasan). Copia local migrada a 0082 con respaldo y cuarentena de ocho suscripciones autorizada por el usuario.
- Corregidas causas de fallos backend: zona horaria SQL UTC por conexion, clasificacion de rutas publicas SPA y aislamiento de variables de tests. suite completa final: 3.747 pasan y 23 se omiten por guardas previstas.
- Abierto DEV-LOCAL-02: siete alertas en herramientas de desarrollo derivadas de picomatch, sin parche publicado. Auditoria de dependencias de produccion da cero.
- Evidencia actual: [reparacion local](../quality/local-repair-2026-11-18.md). La base original se conserva sin migrar.

## Viabilidad ML en QA (2026-11-24)

- ML-DATA-01: la copia QA 0082 no contiene Core, detalles/historial de rechazos o recuperaciones; Toku/Payku no tienen transacciones y VP no tiene rechazos. TCH conserva glosas parciales sin historia de recuperacion util. Esto impide entrenar/evaluar P2 a 30 dias y confirmar el benchmark multicanal, no preparar reglas o anotacion P1. No demuestra ausencia de datos en produccion.
- Alcance aclarado por el usuario: su socio tiene datos mas completos y ejecutara las pruebas estadisticas en su entorno controlado. No bloquea desarrollar codigo y pruebas funcionales aqui ni exige trasladar la base. Sigue pendiente comprobar cobertura/etiquetas en el entorno del socio; su validacion condiciona eleccion y activacion, no la implementacion local. Materializacion, importaciones o llamadas a proveedores requieren tareas separadas. [Auditoria](../planning/ml-rechazos/QA-2026-11-24.md) y [protocolo con el socio](../planning/ml-rechazos/VALIDACION-SOCIO.md).
