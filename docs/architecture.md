# Arquitectura inicial

## Alcance actual

VirtualPOS Sandbox, Toku y Payku se sincronizan exclusivamente mediante endpoints de lectura. Cada canal se consulta en la UI desde su staging local. No se llama a endpoints que creen, autoricen, cancelen o reintenten operaciones.

## Flujo

`Proveedor read-only -> cliente HTTP -> sync_runs/source_records (staging) -> futuro ETL -> BD_Central -> dashboard React`

Cada ejecución queda registrada en `sync_runs`. Cada respuesta externa se almacena con fuente, tipo, identificador externo, payload JSON saneado y marca temporal. La clave única `(source, resource_type, external_id)` garantiza que las sincronizaciones repetidas sean idempotentes.

El dashboard React consume solo la API REST local mediante el proxy de Vite. Mientras no exista el ETL a `BD_Central`, muestra el resumen de los staging. Los menús VirtualPOS, Toku y Payku muestran únicamente los `source_records` de su fuente y tipo de recurso; no reciben credenciales ni llaman al proveedor directamente. TCH permanece reservado hasta contar con su sincronizador y staging.

Cada mini dashboard de canal consume `/api/v1/staging/dashboard/{source}`. Sus métricas, estados y series mensuales se calculan por fuente: pagos para VirtualPOS, deudas para Toku y transacciones para Payku. Los indicadores solo reflejan campos disponibles en staging y no se consideran consolidados hasta el ETL hacia `BD_Central`.

La ficha de cliente VirtualPOS consulta `/api/v1/staging/virtualpos/clients/{uuid}`. Mientras el proveedor no entregue el UUID del cliente dentro de sus suscripciones, la relación autorizada es `client.social_id` contra el `social_id` del cliente, siempre dentro de la fuente `virtualpos`.

Las fichas de plan y suscripción VirtualPOS consultan `/api/v1/staging/virtualpos/plans/{id}` y `/api/v1/staging/virtualpos/subscriptions/{id}`. Las suscripciones de un plan se filtran por `subscription.plan_id`. Los cargos se filtran por `sync_context.subscription_external_id`, registrado durante la extracción read-only de cargos. El método de pago proviene del payload saneado de la suscripción.

La ficha de cargo VirtualPOS consulta `/api/v1/staging/virtualpos/charges/{id}`. Los cargos asociados a una subscripción se ordenan por `charge_date` descendente.

Las fichas de Toku y Payku consultan `/api/v1/staging/{source}/{resource}/{id}` y se mantienen dentro de su misma fuente. Toku relaciona cliente, subscripción, método de pago, deuda y transacción mediante sus IDs declarados. Payku relaciona cliente, plan y subscripción mediante `subscription.client.id` y `subscription.plan.id`; sus transacciones independientes no se enlazan si el payload no declara un identificador verificable.

Las listas de todos los proveedores filtran en la API local mediante `filter_field` y `query`, para conservar el total correcto de resultados. Los cargos VirtualPOS se ordenan por `charge_date` descendente y las transacciones por `order.authorized_at` descendente, dejando registros sin fecha al final. El RUT de clientes Toku procede de `government_id`.

## Seguridad

La cabecera `Signature` es un JWT HS256 cuyo payload contiene `api_key`; se firma con `secret_key`. Ambos valores proceden de variables de entorno. La aplicación no registra estos valores ni los devuelve en respuestas HTTP. Antes de staging se eliminan campos de tarjeta y seguridad.
