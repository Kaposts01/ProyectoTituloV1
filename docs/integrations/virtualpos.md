# VirtualPOS

VirtualPOS aporta clientes, planes, suscripciones, cargos y pagos. Usa autenticacion JWT HS256 y sincronizacion paginada. Los datos se sanean antes de staging.

**Confirmed 2026-10-20:** la [documentacion oficial de endpoints](https://virtualpos.readme.io/reference/endpoints) define `https://api.virtualpos.cl` para produccion y `https://api.virtualpos-sandbox.com` para sandbox. `VIRTUALPOS_BASE_URL` guarda solo esa base; el cliente del repositorio agrega `/v3/...`. No seleccionar ni cambiar el ambiente automaticamente.

La [autenticacion oficial](https://virtualpos.readme.io/reference/autenticaci%C3%B3n-y-firma) requiere API KEY y SECRET KEY del mismo comercio y ambiente; se obtienen en Perfil > Configuracion de cuenta > Integracion. Una API KEY sola no permite generar la firma requerida. Esta verificacion documental no certifica credenciales ni conectividad de una cuenta.

**Observed 2026-10-04:** los cargos operativos se extraen de `charge_program` embebido en cada suscripcion. La respuesta global de pagos conserva el RUT del cliente, que permite mostrar transacciones de ese cliente dentro de la misma cuenta. Los registros locales actuales no contienen un identificador de cargo o suscripcion verificable en las transacciones ni UUID de orden util en los cargos; por ello no se asignan transacciones individualmente a un cargo o suscripcion. Una respuesta de coleccion con envelope invalido falla la sincronizacion en vez de registrarse como vacia.

Las escrituras se realizan solamente desde rutas internas autorizadas y con `VIRTUALPOS_WRITES_ENABLED=true`. El detalle contractual historico existente esta en [la investigacion de VirtualPOS](../history/integrations/virtualpos-appscript-research.md).

Riesgo conocido: existen suscripciones historicas sin cargos locales cuya recuperacion no fue posible por la ruta disponible del proveedor.

## Cargos, pagos y rechazos

**Confirmed:** el detalle de un Charge puede incluir `payment.order.uuid`; ese valor identifica de forma verificable al Payment correspondiente. Los motivos de rechazo pertenecen a `rejected_object` y contienen código, mensaje y URL documental. La lectura puntual de un cargo y un pago rechazados confirmó ambas estructuras.

**Observed:** la sincronización vigente obtiene cargos desde `suscription.charge_program`, que solo contiene programación y estado. Por ello los cargos locales actuales no conservan el Payment embebido ni la relación verificable; el listado global de Payments tampoco incluye `rejected_object`. Debe enriquecerse mediante detalles de proveedor antes de relacionar cargos y pagos o mostrar motivos de rechazo históricos.

**Known limitation:** no todo Charge debe tener un Payment: cargos pendientes, cancelados o en proceso pueden no haber generado una transacción. Solo se enlazarán pares respaldados por el UUID de orden del proveedor.

## Estructura operacional

La documentacion operacional detallada esta organizada en [docs/integrations/virtualpos/README.md](virtualpos/README.md).

Incluye 15 flujos paso a paso y 14 documentos de recursos (contratos de API, autenticacion, paginacion, errores, sandbox).

### Bloqueantes y pendientes activos

| Clave | Descripcion |
|---|---|
| **V-1** | No confirmado que `GET /v3/suscriptions` devuelva `charge_program` completo en el listado masivo. Pendiente validacion en sandbox. |
| **V-2** | No confirmado que una cuota `pagado` o `rechazado` traiga `payment.order.uuid` en `GET /v3/charge/{id}`. |
| **V-3** | No confirmado que `GET /v3/payments` incluya transacciones de cuotas recurrentes (no solo pagos spot). |
| **V-4** | Un reintento de cuota rechazada: no confirmado si reutiliza el mismo Payment o crea otro. |
| **charge_program** | Los cargos locales no conservan el Payment embebido ni la relacion verificable con la transaccion. Requiere enriquecimiento por detalle de proveedor para motivos de rechazo historicos. |
| **return_url en changecard** | `PUT /v3/suscription/{id}/changecard` no acepta `return_url`. El socio no vuelve a nuestra pagina; confirmacion depende del job. Pendiente consulta a soporte@virtualpos.cl. |

## Webhooks

**Confirmed:** VirtualPOS puede notificar pagos y eventos PAT a una URL HTTPS. Los pagos y suscripciones creados por API aceptan `callback_url`; los eventos PAT se configuran desde el Portal Comercio. Los eventos observables incluyen activación o fallo de suscripción, cargo pagado o rechazado y cambio de tarjeta. El callback aporta identificadores para recuperar el recurso por API, por lo que no reemplaza la sincronización ni se considera fuente completa.

**TBD:** la documentación no define firma, secreto, identificador único de entrega, orden, reintentos ni tiempo de espera para estos callbacks. La firma documentada para Payout no aplica al flujo de pagos o PAT. No se implementará un receptor de VirtualPOS hasta contar con un método verificable de autenticidad.

Fuentes oficiales: [Webhook](https://virtualpos.readme.io/reference/webhook), [crear Payment](https://virtualpos.readme.io/reference/crear-un-objeto-payment), [crear Suscription](https://virtualpos.readme.io/reference/crear-una-suscription) y [webhook Payout](https://virtualpos.readme.io/reference/webhook-payout).

## Core — asociaciones conservadoras (DATA-01, 2026-10-20)

El ETL Core prioriza client_external_id de la suscripcion; si existe pero no tiene identidad externa conocida, conserva client_id nulo. Solo usa el fallback por RUT cuando falta ID explicito y existe un unico cliente con ese valor en la misma cuenta. RUT compartido no selecciona el primer cliente ni participa en asociaciones automaticas de pagos a suscripciones. La proyeccion operativa por canal no cambia. Las asociaciones Core existentes no se reasignan mediante el upsert; requieren revision antes de cualquier reparacion historica.
