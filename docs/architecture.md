# Arquitectura inicial

## Alcance actual

VirtualPOS Sandbox, Toku y Payku se sincronizan exclusivamente mediante endpoints de lectura. Cada canal se consulta en la UI desde su staging local. No se llama a endpoints que creen, autoricen, cancelen o reintenten operaciones.

## Flujo

`Proveedor read-only -> cliente HTTP -> sync_runs/source_records (staging) -> futuro ETL -> BD_Central -> dashboard React`

Cada ejecución queda registrada en `sync_runs`. Cada respuesta externa se almacena con fuente, tipo, identificador externo, payload JSON saneado y marca temporal. La clave única `(source, resource_type, external_id)` garantiza que las sincronizaciones repetidas sean idempotentes.

El dashboard React consume solo la API REST local mediante el proxy de Vite. Mientras no exista el ETL a `BD_Central`, muestra el resumen de los staging. Los menús VirtualPOS, Toku y Payku muestran únicamente los `source_records` de su fuente y tipo de recurso; no reciben credenciales ni llaman al proveedor directamente. TCH permanece reservado hasta contar con su sincronizador y staging.

Cada mini dashboard de canal consume `/api/v1/staging/dashboard/{source}`. Sus métricas, estados y series mensuales se calculan por fuente: pagos para VirtualPOS, deudas para Toku y transacciones para Payku. Los indicadores solo reflejan campos disponibles en staging y no se consideran consolidados hasta el ETL hacia `BD_Central`.

## Seguridad

La cabecera `Signature` es un JWT HS256 cuyo payload contiene `api_key`; se firma con `secret_key`. Ambos valores proceden de variables de entorno. La aplicación no registra estos valores ni los devuelve en respuestas HTTP. Antes de staging se eliminan campos de tarjeta y seguridad.
