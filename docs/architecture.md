# Arquitectura inicial

## Alcance actual

VirtualPOS Sandbox es la única fuente habilitada en este hito. La API consulta clientes, planes, suscripciones, cargos y pagos. No llama a endpoints que creen, autoricen, cancelen o reintenten operaciones.

## Flujo

`VirtualPOS Sandbox -> cliente HTTP -> sync_runs/source_records (staging) -> modelos canonicos -> API REST -> dashboard React`

Cada ejecución queda registrada en `sync_runs`. Cada respuesta externa se almacena con fuente, tipo, identificador externo, payload JSON saneado y marca temporal. La clave única `(source, resource_type, external_id)` garantiza que las sincronizaciones repetidas sean idempotentes.

El dashboard React consume solo la API REST local mediante el proxy de Vite. No recibe credenciales de VirtualPOS ni llama al proveedor directamente.

## Seguridad

La cabecera `Signature` es un JWT HS256 cuyo payload contiene `api_key`; se firma con `secret_key`. Ambos valores proceden de variables de entorno. La aplicación no registra estos valores ni los devuelve en respuestas HTTP. Antes de staging se eliminan campos de tarjeta y seguridad.
