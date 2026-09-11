# Arquitectura

## Alcance actual

El CRM integra VirtualPOS Sandbox, Toku y Payku en modo read-only. Los sincronizadores configurados usan consultas `GET`; la interfaz consume unicamente la API local y nunca se conecta directamente a un proveedor.

`Proveedor -> cliente HTTP -> sync_runs / source_records -> futuro ETL -> BD_Central -> dashboard React`

La capa canonica actual corresponde a VirtualPOS. Toku y Payku se consultan desde sus registros staging, sin mezclarlos con el modelo canonico hasta que exista el ETL hacia `BD_Central`.

## Staging y sincronizacion

Cada ejecucion crea o actualiza un `sync_run`. Las respuestas se sanean y se persisten en `source_records` con fuente, tipo de recurso, identificador externo, payload y marcas de tiempo. La restriccion unica `(source, resource_type, external_id)` mantiene la sincronizacion idempotente; los payloads sin cambios no se reescriben.

Los recursos sincronizados son:

- VirtualPOS: clientes, planes, suscripciones, cargos y pagos.
- Toku: clientes, deudas, metodos de pago, suscripciones y transacciones.
- Payku: clientes, planes, suscripciones y transacciones. La ejecucion completa de transacciones esta pendiente de ajustar su timeout local.

Los errores de sincronizacion eliminan secretos configurados y secuencias con formato de tarjeta antes de guardarse.

## API y frontend

La API FastAPI se publica bajo `/api/v1`. Los endpoints CRM consultan el modelo canonico de VirtualPOS; `/staging` ofrece resumen, listas, mini dashboards y fichas de los tres canales.

El frontend React usa el proxy de Vite hacia la API local. Sus mini dashboards calculan metricas, estados y actividad mensual a partir del staging de cada fuente. Esas metricas no son consolidadas mientras no exista `BD_Central`.

Las relaciones se limitan a identificadores que entrega cada proveedor:

- VirtualPOS relaciona cliente y suscripcion por `social_id`/RUT; plan y suscripcion por `plan_id`; cargo y suscripcion por el contexto de sincronizacion. Los cargos se ordenan por `charge_date` descendente.
- Toku usa sus IDs de cliente, suscripcion, metodo de pago, deuda y transaccion. El RUT del cliente procede de `government_id`.
- Payku enlaza clientes, planes y suscripciones mediante los IDs declarados en la suscripcion. Las transacciones sin identificador comprobable quedan sin relacion.

Las listas de todos los proveedores filtran en la API local mediante `filter_field` y `query`, para conservar el total correcto de resultados. Los cargos VirtualPOS se ordenan por `charge_date` descendente y las transacciones por `order.authorized_at` descendente, dejando registros sin fecha al final. El RUT de clientes Toku procede de `government_id`.

## Seguridad

Las credenciales se cargan desde variables de entorno. VirtualPOS firma sus solicitudes con JWT HS256; Toku usa `x-api-key`; Payku usa `Authorization: Bearer` y la cabecera `Sign`. Ninguno de esos valores se registra ni se devuelve por HTTP.

Antes de staging se eliminan `card_number`, `card_pan`, `pan`, `cvv`, `cvc` y `security_code`. La documentacion y el repositorio tampoco deben incluir datos de tarjeta completos ni codigos de seguridad.
