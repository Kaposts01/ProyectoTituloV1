# VirtualPOS

VirtualPOS aporta clientes, planes, suscripciones, cargos y pagos. Usa autenticacion JWT HS256 y sincronizacion paginada. Los datos se sanean antes de staging.

**Observed 2026-10-01:** los cargos operativos se extraen de `charge_program` embebido en cada suscripcion, ya que la respuesta de pagos no conserva una referencia de cargo que permita reconstruir una relacion 1:1. La conciliacion se realiza de forma agregada por plataforma, estado y monto; no debe inferirse una relacion individual entre cargo y pago sin un identificador verificado del proveedor. Una respuesta de coleccion con envelope invalido falla la sincronizacion en vez de registrarse como vacia.

Las escrituras se realizan solamente desde rutas internas autorizadas y con `VIRTUALPOS_WRITES_ENABLED=true`. El detalle contractual historico existente esta en [la investigacion de VirtualPOS](../history/integrations/virtualpos-appscript-research.md).

Riesgo conocido: existen suscripciones historicas sin cargos locales cuya recuperacion no fue posible por la ruta disponible del proveedor.
