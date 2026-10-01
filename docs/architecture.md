# Arquitectura

## Alcance actual

El CRM integra VirtualPOS Sandbox, Toku, Payku y TCH. Los sincronizadores de proveedores en línea usan exclusivamente consultas `GET`; la interfaz consume únicamente la API local y nunca se conecta directamente a un proveedor.

`Proveedor -> source_records (staging, base crm) -> consolidación -> entidades centralizadas CRM -> API local -> dashboard React`

Las entidades centralizadas se materializan desde `source_records` de VirtualPOS, Toku y Payku, todo dentro de la base `crm`. Las bases locales por canal (BDlocales) se usaron durante la migración inicial y ya no forman parte del flujo en vivo; ver `docs/PLAN_CONSOLIDACION_BDLOCAL.md`. Toku incluye métodos de pago centralizados; los payloads saneados permanecen como respaldo de trazabilidad.

## Staging y sincronizacion

Cada ejecucion crea o actualiza un `sync_run`. Las respuestas se sanean y se persisten en `source_records` con fuente, tipo de recurso, identificador externo, payload y marcas de tiempo. La restriccion unica `(source, resource_type, external_id)` mantiene la sincronizacion idempotente; los payloads sin cambios no se reescriben.

Los recursos sincronizados y materializados son:

- VirtualPOS: clientes, planes, suscripciones, cargos y pagos.
- Toku: clientes, deudas, metodos de pago, suscripciones y transacciones.
- Payku: clientes, planes, suscripciones y transacciones. La ejecucion completa de transacciones esta pendiente de ajustar su timeout local.
- TCH: canal de débito bancario cargado desde reportes Excel locales (sin sincronización contra proveedor externo). Las tablas `tch_clientes`, `tch_suscripciones` y `tch_transacciones` almacenan el historial 2017–2026.

Los errores de sincronizacion eliminan secretos configurados y secuencias con formato de tarjeta antes de guardarse.

## Consolidación y API

La API FastAPI se publica bajo `/api/v1`. `/staging` ofrece resumen, listas, mini dashboards y fichas desde las entidades centralizadas de VirtualPOS, Toku y Payku. `/staging/dashboard/general` consolida KPIs, transacciones y activaciones mensuales de los cuatro canales, incluido TCH. `/tch` expone el resumen, clientes, suscripciones y transacciones del canal TCH con filtros y fichas. `/etl/run` rematerializa `source_records` existentes en las entidades centralizadas; `/etl/full-sync` ejecuta lectura read-only de proveedores, actualiza `source_records` y consolida en segundo plano.

Las operaciones de escritura están implementadas para los tres proveedores en línea y denegadas por defecto; cada uno requiere su bandera local (`VIRTUALPOS_WRITES_ENABLED`, `TOKU_WRITES_ENABLED` o `PAYKU_WRITES_ENABLED`). VirtualPOS soporta crear y editar clientes, crear planes, crear y cancelar suscripciones, cancelar y reintentar cargos, y crear cargos sobre suscripciones activas. Toku soporta editar y eliminar clientes, y cambiar el estado de suscripciones. Payku soporta editar y eliminar clientes, y eliminar suscripciones. Tras una respuesta remota exitosa, el servicio actualiza el registro saneado en `source_records` (staging) y rematerializa su entidad centralizada; un rechazo remoto no modifica los datos locales.

Cada escritura registra un `write_run` durable con su estado, solicitud y respuesta saneadas. Si el proveedor confirma pero la persistencia local falla, queda en `reconciliation_required` para recuperarlo mediante una lectura autorizada, sin fingir que la operación quedó completada.

El frontend React usa el proxy de Vite hacia la API local. Sus mini dashboards calculan métricas, estados y actividad mensual desde entidades centralizadas. Las tablas filtran por columnas operativas, ofrecen estados como selector cuando corresponde y ordenan globalmente mediante la API antes de paginar.

Las relaciones se limitan a identificadores que entrega cada proveedor:

- VirtualPOS relaciona cliente y suscripcion por `social_id`/RUT; plan y suscripcion por `plan_id`; cargo y suscripcion por el contexto de sincronizacion. Los cargos se ordenan por `charge_date` descendente.
- Toku usa sus IDs de cliente, suscripcion, metodo de pago, deuda y transaccion. El RUT del cliente procede de `government_id`.
- Payku enlaza clientes, planes y suscripciones mediante los IDs declarados en la suscripcion. Las transacciones sin identificador comprobable quedan sin relacion.

Las tablas de los tres canales filtran en la API local mediante `filter_field` y `query`, preservando el total correcto. `sort_field` y `sort_direction` admiten solo campos visibles permitidos y aplican el orden global antes de la paginación; los métodos de pago Toku incluyen campos anidados de tarjeta saneados.

El frontend incluye modales de edicion visual para clientes y cancelacion de suscripciones VirtualPOS. Se habilitan solo cuando su ruta interna de escritura esté implementada y autorizada mediante la bandera local del proveedor.

La documentacion del proveedor VirtualPOS (rutas, contratos, autenticacion y estrategia incremental) esta en `docs/Documentacion API VirtualPOS.md`.

## Seguridad

Las credenciales se cargan desde variables de entorno. VirtualPOS firma sus solicitudes con JWT HS256; Toku usa `x-api-key`; Payku usa `Authorization: Bearer` y la cabecera `Sign`. Ninguno de esos valores se registra ni se devuelve por HTTP.

## Identidad y autorización

La API usa una sesión JWT firmada en cookie `HttpOnly`, con expiración configurable y protección CSRF para POST, PUT y DELETE. El JWT identifica al usuario, pero los roles y permisos se consultan en PostgreSQL en cada solicitud, por lo que desactivar una cuenta o cambiar sus roles aplica inmediatamente.

`users`, `roles`, `permissions`, `user_roles` y `role_permissions` implementan relaciones muchos-a-muchos. El catálogo de permisos es fijo en código y cubre dashboard global, dashboards por canal, cada tabla por proveedor, sincronizaciones, ETL y escrituras. El frontend oculta los módulos no permitidos, pero FastAPI es el control de seguridad definitivo y filtra o rechaza las rutas no autorizadas.

Antes de staging se eliminan `card_number`, `card_pan`, `pan`, `cvv`, `cvc` y `security_code`. La documentacion y el repositorio tampoco deben incluir datos de tarjeta completos ni codigos de seguridad.
