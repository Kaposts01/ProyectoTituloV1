# VirtualPOS

VirtualPOS aporta clientes, planes, suscripciones, cargos y pagos. Usa autenticacion JWT HS256 y sincronizacion paginada. Los datos se sanean antes de staging.

**Observed 2026-10-04:** los cargos operativos se extraen de `charge_program` embebido en cada suscripcion. La respuesta global de pagos conserva el RUT del cliente, que permite mostrar transacciones de ese cliente dentro de la misma cuenta. Los registros locales actuales no contienen un identificador de cargo o suscripcion verificable en las transacciones ni UUID de orden util en los cargos; por ello no se asignan transacciones individualmente a un cargo o suscripcion. Una respuesta de coleccion con envelope invalido falla la sincronizacion en vez de registrarse como vacia.

Las escrituras se realizan solamente desde rutas internas autorizadas y con `VIRTUALPOS_WRITES_ENABLED=true`. El detalle contractual historico existente esta en [la investigacion de VirtualPOS](../history/integrations/virtualpos-appscript-research.md).

Riesgo conocido: existen suscripciones historicas sin cargos locales cuya recuperacion no fue posible por la ruta disponible del proveedor.
