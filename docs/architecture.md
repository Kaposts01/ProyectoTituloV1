# Arquitectura inicial

## Alcance actual

VirtualPOS Sandbox es la única fuente habilitada en este hito. La API consulta clientes, planes, suscripciones, cargos y pagos. No llama a endpoints que creen, autoricen, cancelen o reintenten operaciones.

## Flujo

`VirtualPOS Sandbox -> cliente HTTP -> sync_runs/source_records (staging) -> modelos canónicos -> API REST`

Cada ejecución queda registrada en `sync_runs`. Cada respuesta externa se almacena con fuente, tipo, identificador externo, carga original JSON y marca temporal. La clave única `(source, resource_type, external_id)` garantiza que las sincronizaciones repetidas sean idempotentes.

## Seguridad

La cabecera `Signature` es un JWT HS256 cuyo payload contiene `api_key`; se firma con `secret_key`. Ambos valores proceden de variables de entorno. La aplicación no registra estos valores ni los devuelve en respuestas HTTP.
