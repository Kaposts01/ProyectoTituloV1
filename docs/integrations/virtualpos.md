# VirtualPOS

VirtualPOS aporta clientes, planes, suscripciones, cargos y pagos. Usa autenticacion JWT HS256 y sincronizacion paginada. Los datos se sanean antes de staging.

**Observed 2026-10-04:** los cargos operativos se extraen de `charge_program` embebido en cada suscripcion. La respuesta global de pagos conserva el RUT del cliente, que permite mostrar transacciones de ese cliente dentro de la misma cuenta. Los registros locales actuales no contienen un identificador de cargo o suscripcion verificable en las transacciones ni UUID de orden util en los cargos; por ello no se asignan transacciones individualmente a un cargo o suscripcion. Una respuesta de coleccion con envelope invalido falla la sincronizacion en vez de registrarse como vacia.

Las escrituras se realizan solamente desde rutas internas autorizadas y con `VIRTUALPOS_WRITES_ENABLED=true`. El detalle contractual historico existente esta en [la investigacion de VirtualPOS](../history/integrations/virtualpos-appscript-research.md).

Riesgo conocido: existen suscripciones historicas sin cargos locales cuya recuperacion no fue posible por la ruta disponible del proveedor.

## Cargos, pagos y rechazos

**Confirmed:** el detalle de un Charge puede incluir `payment.order.uuid`; ese valor identifica de forma verificable al Payment correspondiente. Los motivos de rechazo pertenecen a `rejected_object` y contienen código, mensaje y URL documental. La lectura puntual de un cargo y un pago rechazados confirmó ambas estructuras.

**Observed:** la sincronización vigente obtiene cargos desde `suscription.charge_program`, que solo contiene programación y estado. Por ello los cargos locales actuales no conservan el Payment embebido ni la relación verificable; el listado global de Payments tampoco incluye `rejected_object`. Debe enriquecerse mediante detalles de proveedor antes de relacionar cargos y pagos o mostrar motivos de rechazo históricos.

**Known limitation:** no todo Charge debe tener un Payment: cargos pendientes, cancelados o en proceso pueden no haber generado una transacción. Solo se enlazarán pares respaldados por el UUID de orden del proveedor.

## Webhooks

**Confirmed:** VirtualPOS puede notificar pagos y eventos PAT a una URL HTTPS. Los pagos y suscripciones creados por API aceptan `callback_url`; los eventos PAT se configuran desde el Portal Comercio. Los eventos observables incluyen activación o fallo de suscripción, cargo pagado o rechazado y cambio de tarjeta. El callback aporta identificadores para recuperar el recurso por API, por lo que no reemplaza la sincronización ni se considera fuente completa.

**TBD:** la documentación no define firma, secreto, identificador único de entrega, orden, reintentos ni tiempo de espera para estos callbacks. La firma documentada para Payout no aplica al flujo de pagos o PAT. No se implementará un receptor de VirtualPOS hasta contar con un método verificable de autenticidad.

Fuentes oficiales: [Webhook](https://virtualpos.readme.io/reference/webhook), [crear Payment](https://virtualpos.readme.io/reference/crear-un-objeto-payment), [crear Suscription](https://virtualpos.readme.io/reference/crear-una-suscription) y [webhook Payout](https://virtualpos.readme.io/reference/webhook-payout).
