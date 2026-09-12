# Arquitectura

## Alcance actual

El CRM integra VirtualPOS Sandbox, Toku y Payku en modo read-only. Los sincronizadores configurados usan consultas `GET`; la interfaz consume unicamente la API local y nunca se conecta directamente a un proveedor.

`Proveedor -> BDlocal por proveedor -> ETL -> entidades canónicas CRM -> API local -> dashboard React`

Las entidades canónicas se materializan desde las BDlocales de VirtualPOS, Toku y Payku. Toku incluye métodos de pago canónicos; los payloads saneados permanecen como respaldo de trazabilidad.

## Staging y sincronizacion

Cada ejecucion crea o actualiza un `sync_run`. Las respuestas se sanean y se persisten en `source_records` con fuente, tipo de recurso, identificador externo, payload y marcas de tiempo. La restriccion unica `(source, resource_type, external_id)` mantiene la sincronizacion idempotente; los payloads sin cambios no se reescriben.

Los recursos sincronizados y materializados son:

- VirtualPOS: clientes, planes, suscripciones, cargos y pagos.
- Toku: clientes, deudas, metodos de pago, suscripciones y transacciones.
- Payku: clientes, planes, suscripciones y transacciones. La ejecucion completa de transacciones esta pendiente de ajustar su timeout local.

Los errores de sincronizacion eliminan secretos configurados y secuencias con formato de tarjeta antes de guardarse.

## Consolidación y API

La API FastAPI se publica bajo `/api/v1`. `/staging` ofrece resumen, listas, mini dashboards y fichas desde las entidades canónicas de los tres canales. `/etl/run` ejecuta solo la consolidación desde BDlocales; `/etl/full-sync` ejecuta lectura read-only de proveedores, actualiza BDlocales y consolida en segundo plano.

El frontend React usa el proxy de Vite hacia la API local. Sus mini dashboards calculan métricas, estados y actividad mensual desde entidades canónicas. Las tablas filtran por columnas operativas, ofrecen estados como selector cuando corresponde y ordenan globalmente mediante la API antes de paginar.

Las relaciones se limitan a identificadores que entrega cada proveedor:

- VirtualPOS relaciona cliente y suscripcion por `social_id`/RUT; plan y suscripcion por `plan_id`; cargo y suscripcion por el contexto de sincronizacion. Los cargos se ordenan por `charge_date` descendente.
- Toku usa sus IDs de cliente, suscripcion, metodo de pago, deuda y transaccion. El RUT del cliente procede de `government_id`.
- Payku enlaza clientes, planes y suscripciones mediante los IDs declarados en la suscripcion. Las transacciones sin identificador comprobable quedan sin relacion.

Las tablas de los tres canales filtran en la API local mediante `filter_field` y `query`, preservando el total correcto. `sort_field` y `sort_direction` admiten solo campos visibles permitidos y aplican el orden global antes de la paginación; los métodos de pago Toku incluyen campos anidados de tarjeta saneados.

El frontend incluye modales de edicion visual para clientes y cancelacion de suscripciones VirtualPOS. Estos modales no persisten cambios en el proveedor mientras la integracion Sandbox permanezca en modo read-only.

La documentacion del proveedor VirtualPOS (rutas, contratos, autenticacion y estrategia incremental) esta en `docs/Documentacion API VirtualPOS.md`.

## Seguridad

Las credenciales se cargan desde variables de entorno. VirtualPOS firma sus solicitudes con JWT HS256; Toku usa `x-api-key`; Payku usa `Authorization: Bearer` y la cabecera `Sign`. Ninguno de esos valores se registra ni se devuelve por HTTP.

Antes de staging se eliminan `card_number`, `card_pan`, `pan`, `cvv`, `cvc` y `security_code`. La documentacion y el repositorio tampoco deben incluir datos de tarjeta completos ni codigos de seguridad.
