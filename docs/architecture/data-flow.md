# Flujo de Datos

## Flujo objetivo

**Status: Proposed**

```text
Fuente externa -> Connector -> Staging / Raw -> ETL / Normalizacion -> PostgreSQL Core -> API -> CRM, reportes y analytics
```

Cada connector lee o usa exclusivamente los flujos de escritura internos autorizados. Staging conserva el contexto de origen; ETL transforma hacia conceptos Core sin que el proveedor escriba directamente en ellos.

## Flujo implementado observado

**Status: Accepted**

VirtualPOS, Toku y Payku persisten respuestas saneadas en `source_records` usando la clave `(source, resource_type, external_id)`. `sync_runs` registra sincronizaciones y `write_runs` operaciones autorizadas. TCH carga reportes Excel en sus tablas propias.

Los datos de tarjeta y seguridad conocidos se eliminan antes de persistir staging. La relacion entre entidades solo se materializa cuando hay identificadores o contexto verificable.

## Tiempo real hacia la interfaz (decision D9, cierra OPS-09 y RT-01)

**Status: Accepted** (decision D9 de la auditoria 2026-10-29: SSE con polling de respaldo)

Son dos tramos distintos y se resuelven por separado:

1. **Proveedor -> backend**: webhooks (`docs/data/webhooks.md`), reconciliacion dirigida y sync diaria. Todos terminan en `status_change_events` (append-only, sin datos personales).
2. **Backend -> navegador**: SSE en `GET /api/v1/events/stream` (`app/api/v1/routes/events.py`). No lee proveedores: solo avisa que algo ya cambio en nuestra base.

```text
proveedor -> webhook_events -> procesador / reconciliacion / sync -> status_change_events -> SSE -> useChangeStream (invalida cache, avisos)
```

Decisiones evaluadas (OPS-09):

| Criterio | Decision |
|---|---|
| Transporte | SSE. WebSocket descartado: no hay mensajes navegador -> servidor y exige mas codigo (handshake, latido, reconexion manual). |
| Autenticacion | Cookie JWT HttpOnly de la sesion (el router v1 exige `get_current_user`) + permiso `dashboard.view`, el mismo de `/changes/daily`. `EventSource` manda la cookie (`withCredentials`). La conexion se cierra cada `EVENTS_STREAM_MAX_SECONDS` (300 s) y al reconectar se revalida la sesion. |
| Reconexion | `retry: 5000` + `Last-Event-ID` (o `?last_event_id=`). El id es `<microsegundos>.<uuid>` de `detected_at`; se reenvia con un margen de 2 min para transacciones que confirman tarde y el cliente descarta repetidos. Cursor invalido o de mas de 24 h: evento `reset` y el cliente recarga. |
| Persistencia | La tabla `status_change_events` es la fuente: un navegador cerrado recupera lo perdido al reconectar (hasta 24 h). |
| Multi-worker | Cada conexion relee la tabla cada `EVENTS_STREAM_POLL_SECONDS` (5 s), en una sesion corta. `event_bus.notify_status_changes()` solo adelanta la relectura dentro del mismo proceso. El `event_bus` en memoria sigue solo para el progreso de corridas del scheduler. `LISTEN/NOTIFY` de Postgres queda como evolucion si la carga de relectura lo pide (requiere una conexion dedicada por proceso). |
| Respaldo | Si `EventSource` no existe o la conexion queda cerrada (error HTTP), el frontend invalida la cache cada 60 s y reintenta el stream. |
| Datos | Entidad, canal, id externo del proveedor, tipo de cambio, campo, estados/montos y fecha. Sin baseline, sin glosas (texto libre) ni datos personales. |

Limites conocidos: una fila detectada mas de 2 min antes de confirmarse, cuando ya pasaron eventos posteriores, puede no empujarse (la cubre el respaldo y la recarga normal). Los avisos se muestran como toasts globales (`frontend/src/components/ChangeToasts.tsx`); donde mas mostrarlos (barra, dashboard, ficha) queda como decision de producto.
