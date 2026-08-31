# VirtualPOS Sandbox: contrato observado

## Validacion read-only

- Fecha: 2026-08-30.
- Operaciones ejecutadas: `GET /v3/clients`, `GET /v3/plans`, `GET /v3/suscriptions`, `GET /v3/payments`.
- Resultado: sincronizaciones completadas correctamente. Sandbox entrega 25 clientes, 8 planes, 16 suscripciones, 452 cargos y 35 pagos. No se registraron secretos ni datos de tarjeta en esta documentacion.
- La ruta de cargos se invoca por cada suscripcion y su identificador se conserva como contexto de sincronizacion, separado del payload crudo.

## Contrato disponible

- La respuesta observada es un objeto: los registros se encuentran en `clients`, `plans`, `suscriptions` y `payments`, respectivamente. Tambien se admiten listas directas y los envelopes `data`, `results`, `items` y `charges`.
- Las suscripciones aceptan `page` y `limit`; la coleccion de Postman tambien muestra el filtro opcional `status`. La respuesta observada incluye `pagination` con `page`, `pages`, `limit` y `total`.
- El sincronizador continua mientras la respuesta tenga una pagina completa. Cuando el proveedor expone `pagination` o `meta`, usa `pages`, `total_pages`, `last_page`, `has_next` o `has_next_page`.
- Los identificadores se resuelven desde `id`, `uuid`, `_id` y los campos especificos del recurso. Si faltan, se usa un hash del payload, por lo que esos registros requieren validacion adicional antes de considerarlos estables.
- El staging solo actualiza el payload cuando cambia; `records_processed` contabiliza registros nuevos o modificados. La API del proveedor no ofrece, en el contrato local disponible, un marcador de cambios para evitar leer las colecciones completas.

## Campos canonicos provisionales

Los campos se extraen solo si existen y son opcionales hasta obtener registros reales:

- Cliente: `uuid`, `first_name`, `last_name`, `email`, `phone_number`, `status`.
- Suscripcion: `id`, `client`, `plan_id`, `service_id`, `status`, `renewal`.
- Cargo: `id`, `amount`, `charge_date`, `status`; la suscripcion procede de la URL de consulta.
- Pago: `order.uuid` es el identificador estable y `order` contiene los datos de estado e importe.

Cada entidad canonica conserva `source`, `external_id` y `source_record_id`, que referencia el payload de staging saneado. No se infieren relaciones que el proveedor no haya devuelto.

Antes de persistir staging se eliminan campos de tarjeta y seguridad (`card_number`, `card_pan`, `pan`, `cvv`, `cvc` y `security_code`).
