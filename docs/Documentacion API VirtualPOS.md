# Guia de datos e integracion: VirtualPOS API v3

Fecha de contraste: 2026-08-25.

Esta es la referencia operativa del proyecto para extraer, normalizar, reconciliar y analizar datos de VirtualPOS. Contrasta la documentacion oficial con la implementacion actual de Google Apps Script en esta carpeta.

Fuentes oficiales:

- Inicio: <https://virtualpos.readme.io/reference/getting-started-with-your-api>
- Indice de referencia: <https://virtualpos.readme.io/llms.txt>
- Autenticacion: <https://virtualpos.readme.io/reference/autenticación-y-firma>
- Paginacion: <https://virtualpos.readme.io/reference/paginacion-para-el-listado-de-objetos>
- Errores: <https://virtualpos.readme.io/reference/objeto-error>

## 1. Alcance y modelo conceptual

VirtualPOS expone dos dominios de pago relevantes para el proyecto:

| Dominio | Entidad | Granularidad | Rol analitico |
| --- | --- | --- | --- |
| Pagos puntuales | Payment | Un intento de pago / una orden (`order.uuid`) | Ventas, autorizaciones, medios de pago y abonos. |
| Recurrencia | Plan | Una configuracion comercial | Define precio, frecuencia y vigencia de una suscripcion. |
| Recurrencia | Suscription | Adhesion de cliente a un plan (`id`) | Base de clientes recurrentes y su estado. |
| Recurrencia | Charge | Cobro programado de una suscripcion (`id`) | Hecho financiero recurrente, pagado, pendiente o rechazado. |
| Maestro | Client | Cliente del comercio (`uuid`) | Identidad, contacto y tarjeta registrada. |
| Liquidacion | Deposit | Un abono por fecha | Conciliacion: ventas - retenciones - servicios. |

Relaciones esperadas:

```text
Plan 1 --- N Suscription 1 --- N Charge 0..1 --- Payment
Client 1 --- N Suscription
Client 1 --- N Payment
Deposit 1 --- N Payment pagados
Deposit 1 --- N Withholdings
```

Un Charge puede no tener Payment todavia. Un Payment puntual puede no relacionarse con una Suscription. La relacion Charge-Payment debe tratarse como opcional y nunca inferirse solamente por fecha o monto.

## 2. Ambientes, cuentas y configuracion

| Ambiente | Host Payments | Credenciales del proyecto | Cuentas |
| --- | --- | --- | --- |
| Produccion | `https://api.virtualpos.cl` | `VP1_API_KEY`, `VP1_SECRET_KEY`, `VP2_API_KEY`, `VP2_SECRET_KEY` | 1 y 2 |
| Sandbox | `https://api.virtualpos-sandbox.com` | `VP_API_KEY_SANDBOX`, `VP_SECRET_KEY_SANDBOX` | Una cuenta |

Propiedades de Script adicionales:

| Propiedad | Uso | Regla |
| --- | --- | --- |
| `VP_URL` | Host de produccion | Opcional; por defecto usa el host oficial. |
| `VP_URL_SANDBOX` | Host de sandbox | Obligatoria para sandbox. |
| `VP_LIMIT` | Tamano de pagina | Entero entre 1 y 100; el codigo usa 100 si no existe. |
| `VP_ENV` | Ambiente por defecto | `PROD` o `SANDBOX`; los menus pasan el ambiente explicitamente. |

La columna `plataforma` es obligatoria en todas las hojas para separar fuentes: `virtualPOS1`, `virtualPOS2` y `sandbox`. Ninguna llave de negocio debe asumirse unica entre cuentas.

## 3. Autenticacion y transporte

Cada request requiere los headers siguientes:

| Header | Contenido |
| --- | --- |
| `Content-Type` | `application/json` |
| `Authorization` | API key del comercio y ambiente |
| `Signature` | JWT HS256 firmado con la secret key |
| `accept` | `application/json` |

La firma actual se genera con payload `{ "api_key": API_KEY }` en `construirFirmaJwt_` de `Config.js`. El cliente comun es `vp_solicitudApi_` en `Cliente.js`.

Reglas de seguridad:

- API key y secret key solo deben estar en Script Properties; nunca en hojas, logs, Markdown ni codigo.
- Los datos cargados contienen PII: RUT/DNI, email, telefono, nombre, fecha de nacimiento y datos parciales de tarjeta. Aplicar acceso minimo al Sheet y no exportarlos sin autorizacion.
- Nunca persistir PAN completo, CVV ni payloads de autorizacion. El proyecto solo guarda ultimos digitos o numero enmascarado segun lo devuelto por la API.
- Los endpoints de Payout no se integran: usan hosts `payout-api.*` y mTLS; Apps Script no soporta certificado de cliente en `UrlFetchApp`.

## 4. Paginacion y extraccion confiable

La API usa query params `page` y `limit`; `limit` debe estar entre 1 y 100.

| Recurso | Respuesta de paginacion documentada | Estrategia requerida |
| --- | --- | --- |
| Payments, Plans, Suscriptions, Charges y movimientos de Deposit | `pagination.limit`, `pagination.page`, `pagination.pages`, `pagination.total` | Iterar desde pagina 1 hasta `pages`. |
| Clients | `page`, `limit`, `total` en la documentacion reciente | Iterar hasta pagina vacia o hasta completar `ceil(total / limit)`; validar que el total obtenido coincida. |

El codigo usa `vp_paginarApi_`. Si falla una pagina, aborta la extraccion y entrega un error con pagina, limite y total extraido; ningun sync que reciba ese error se registra como exitoso ni avanza su watermark.

Reglas para un extractor robusto:

1. En cada ejecucion registrar entidad, cuenta, ambiente, pagina, total remoto, filas recibidas, fecha de inicio y termino.
2. Validar que los IDs de la pagina no sean vacios ni duplicados antes del upsert.
3. No usar `items.length < limit` como unica condicion si la API entrega `pagination.pages`.
4. Reintentar errores de red, `429` y `5xx` con backoff exponencial; no reintentar automaticamente `4xx` de validacion.
5. Aceptar cualquier respuesta HTTP `2xx`, no solo `200`. La documentacion de autorizar Payment incluye respuesta `201` para un rechazo financiero procesado correctamente.

## 5. Catalogo completo de rutas usadas

`Sincronizado` significa que el endpoint alimenta una hoja. `Helper` significa que la funcion existe para ser invocada desde otro flujo, pero no tiene una carga masiva directa.

### 5.1 Payment y Web Checkout

| Metodo | Ruta | Funcion | Estado | Notas |
| --- | --- | --- | --- | --- |
| POST | `/v3/payment/` | `vp_crearPago_` | Helper | Crea Payment y puede devolver `url_redirect`. |
| POST | `/v3/payment/{uuid}/webcheckout` | `vp_obtenerLinkWebcheckout_` | Helper | Requiere `return_url` y `callback_url` en Base64; admite `webpay`, `khipu`, `fintoc`, `mach`, `redpay` o `all`. |
| GET | `/v3/payment/{uuid}` | `vp_obtenerPago_` | Helper | Fuente de verdad de estado de un Payment puntual. |
| DELETE | `/v3/payment/{uuid}` | `vp_cancelarPago_` | Helper | Solo aplicable cuando el estado permite cancelacion. |
| GET | `/v3/payment/{uuid}/logs` | `vp_obtenerLogsPago_` | Helper / debug | Secuencia textual de eventos. |
| GET | `/v3/payment/{uuid}/attempts` | `vp_obtenerIntentosPago_` | Helper / debug | Incluye `authorization_attempts_cards`. |
| GET | `/v3/payments` | `vp_traerTodosPagos_`, `API_SYNC_PAGOS` | Sincronizado | Fuente principal de `API Pagos`. |
| POST | `/v3/payment/{uuid}/authorize` | `vp_autorizarPago_` | Helper | Acepta `CREDIT_CARD` o `TOKEN_CARD`; nunca registrar CVV ni tarjeta completa. |
| POST | `/v3/payment/{uuid}/send` | `vp_enviarPago_` | Helper | Envia por `EMAIL`, `WHATSAPP` o `SMS` si el comercio lo tiene habilitado. |
| GET | `/v3/deposit/{date}` | `vp_obtenerAbono_` | Helper | Resumen de liquidacion por fecha. |
| GET | `/v3/deposit/{date}/sales` | `vp_obtenerVentasAbono_` | Helper | Detalle de ventas incluidas en el abono. |
| GET | `/v3/deposit/{date}/withholdings` | `vp_obtenerRetencionesAbono_` | Helper | Detalle de anulaciones/retenciones. |

Filtros oficiales de `/v3/payments`: `status`, `merchant_internal_code`, `authorization_from`, `authorization_to`, `created_from`, `created_to`.

### 5.2 Plans

| Metodo | Ruta | Funcion | Estado | Notas |
| --- | --- | --- | --- | --- |
| POST | `/v3/plan` | `vp_crearPlan_` | Helper | Crea configuracion de recurrencia. |
| GET | `/v3/plan/{id}` | `vp_obtenerPlan_` | Helper | Recupera detalle de un plan. |
| GET | `/v3/plans` | `vp_traerTodosPlanes_`, `API_SYNC_PLANES` | Sincronizado | Fuente de `API Planes`. |

### 5.3 Suscriptions

La API utiliza deliberadamente la grafia `suscription` en rutas y respuestas. El proyecto conserva esa grafia para que la integracion coincida con el proveedor.

| Metodo | Ruta | Funcion | Estado | Notas |
| --- | --- | --- | --- | --- |
| POST | `/v3/suscription` | `vp_crearSuscripcion_` | Helper | Inicia adhesion a un Plan. |
| GET | `/v3/suscription/{id}` | `vp_obtenerSuscripcion_` | Helper | Recupera detalle y programa de cargos. |
| DELETE | `/v3/suscription/{id}` | `vp_cancelarSuscripcion_` | Helper | Detiene la suscripcion y cancela cargos futuros. |
| GET | `/v3/suscriptions` | `vp_traerTodasSuscripciones_`, `API_SYNC_SUSCRIPCIONES` | Sincronizado | Fuente de `API Suscripciones`; admite filtro `status`. |
| PUT | `/v3/suscription/{id}/changecard` | `vp_linkCambioTarjeta_` | Helper | Devuelve URL y fecha de expiracion del link. |

### 5.4 Charges

| Metodo | Ruta | Funcion | Estado | Notas |
| --- | --- | --- | --- | --- |
| POST | `/v3/charge` | `vp_crearCobro_` | Helper | Programa un cobro; `charge_date` no puede ser pasada. |
| POST | `/v3/charge/online` | `vp_crearCobroOnline_` | Helper | Crea cobro inmediato. |
| GET | `/v3/charge/{id}` | `vp_obtenerCobro_` | Helper / debug | Recupera un Charge individual. |
| DELETE | `/v3/charge/{id}` | `vp_cancelarCobro_` | Helper | Cancela un Charge pendiente. |
| GET | `/v3/charge/{id}/retry` | `vp_reintentarCharge_` | Helper | Solo para rechazados; intenta una vez diaria durante tres dias consecutivos. |
| DELETE | `/v3/charges/{suscription_id}` | `vp_cancelarCargosFuturos_` | Helper | Cancela todos los cargos futuros de una suscripcion. |
| GET | `/v3/suscription/{id}/charges` | `vp_traerCobrosDesuscripcion_`, `API_SYNC_COBROS` | Sincronizado | No existe listado global; admite filtro `status`. |

La ausencia de listado global es la principal restriccion operativa. `API_SYNC_COBROS` debe listar todas las suscripciones, generar una cola oculta y consultar cada ruta hija. Guarda checkpoint en `VP_COBROS_ESTADO`, trabaja con `fetchAll` por lotes de 20 y continua con triggers.

### 5.5 Clients

| Metodo | Ruta | Funcion | Estado | Notas |
| --- | --- | --- | --- | --- |
| POST | `/v3/client` | `vp_crearCliente_` | Helper | Crea un cliente del comercio. |
| GET | `/v3/client/{uuid}` | `vp_obtenerCliente_` | Helper / debug | Fuente puntual; documentacion mezcla path y query para `uuid`, validar en sandbox. |
| GET | `/v3/clients` | `vp_traerTodosClientes_`, `API_SYNC_CLIENTES` | Sincronizado | Fuente de `API Clientes`; orden por defecto `created` descendente. |
| PUT | `/v3/client/{uuid}` | `vp_actualizarCliente_` | Helper | Actualizacion parcial; no se pueden modificar `uuid` ni `created`. |

Filtros oficiales de `/v3/clients`: `status`, `type`, `social_id`, `email`, `created_from`, `created_to`.

## 6. Contratos de entidades y campos analiticos

### 6.1 Payment

Llave natural: `plataforma + order.uuid`.

| Campo API | Tipo esperado | Uso de datos |
| --- | --- | --- |
| `order.uuid` | string | ID unico del Payment. |
| `order.status` | enum | Estado financiero actual. |
| `order.created_at` | datetime | Fecha de creacion; candidato para incremental. |
| `order.authorized_at` | datetime nullable | Fecha de exito financiero; base de ventas autorizadas. |
| `order.amount` | numeric | Monto bruto cobrado. |
| `order.tip_amount` | numeric nullable | Propina; disponible en respuestas recientes. |
| `order.payment_method` | string nullable | Ejemplo: `PAT`; medio operativo. |
| `order.payment_type_code` | enum nullable | Tipo de tarjeta/transferencia. |
| `order.card_number` | string/integer nullable | Guardar solo valor enmascarado o ultimos cuatro. |
| `order.auth_code` | string nullable | Codigo de autorizacion. |
| `order.installment_number` | integer/string nullable | Numero de cuotas. |
| `order.installment_amount` | numeric nullable | Monto de cuota. |
| `order.merchant_internal_code` | string nullable | ID de pedido/factura del negocio. |
| `order.merchant_internal_channel` | string nullable | Canal comercial. |
| `order.deposits[]` | array | Un Payment puede tener uno o mas componentes de abono. |
| `client.*` | PII | Cliente asociado al Payment. |
| `commerce.*` | string | Identidad del comercio; validar contra cuenta. |

Estados documentados:

| Estado | Categoria analitica | Regla |
| --- | --- | --- |
| `pendiente` | Abierto | No sumar como ingreso ni abono. |
| `pagado` | Exito | Sumar venta; reconciliar posteriormente con deposito. |
| `rechazado` | Fallido | No sumar ingreso; conservar para tasa de rechazo. |
| `reintentando` | En proceso | No clasificar como exito ni fracaso final. |
| `expirado` | Fallido final | Tiempo maximo por defecto: 30 dias. |
| `cancelado` | Cancelado | No sumar ingreso. |

Codigos `payment_type_code`: `VD` debito, `VN` credito sin cuotas, `VC` credito en cuotas, `SI` 3+ cuotas sin interes, `S2` 2 cuotas sin interes, `NC` cuotas comercio, `VP` prepago y `TE` transferencia electronica. El proyecto normaliza todos salvo `TE`; conservar el codigo original junto al nombre derivado.

### 6.2 Deposit y conciliacion

Llave natural: `plataforma + deposit_date`.

La documentacion define:

```text
total_deposit = sales.net_total - withholdings.net_total - services.net_total
```

Campos de control:

| Grupo | Campos clave |
| --- | --- |
| Cabecera | `deposit_date`, `total_deposit`, `deposit_status` (`VERIFIED` o `NOT VERIFIED`) |
| Sales | `quantity`, `total_amount`, `commission_and_taxes`, `net_total` |
| Withholdings | `quantity`, `total_amount`, `refund_commission_and_taxes`, `net_total` |
| Services | `total_amount`, `taxes`, `net_total` |
| Bank account | Datos altamente sensibles: banco, cuenta, RUT, nombre y email. No cargar a hojas analiticas abiertas. |

Conciliacion recomendada:

1. Extraer Deposit diario para cada cuenta con rezago operativo acordado con Finanzas.
2. Persistir cabecera, ventas y retenciones en tablas separadas si se implementa la carga.
3. Reconciliar Payment `pagado` con `deposit.sales.uuid`, no solo con `payout_date`.
4. Explicar diferencias por comisiones, impuestos, cuotas, anulaciones y servicios.
5. Considerar final un deposito solo si `deposit_status = VERIFIED`.

### 6.3 Plan

Llave natural: `plataforma + id`.

| Campo | Reglas documentadas |
| --- | --- |
| `is_active` | `T` activo, `F` inactivo. |
| `amount` | Numeric; puede ser CLP o UF. |
| `currency` | `CLP` o `UF`. |
| `type` | `MONTO_FIJO`, `MONTO_VARIABLE`, `PROGRAMA_DE_PAGOS`. |
| `frequency_type` | La entidad publica menciona Diario, Semanal, Mensual, Semestral, Anual; el endpoint crear enumera Diario, Semanal y Mensual. Validar contra ambiente antes de asumir valores. |
| `fixed_amount_day_charge` | `0`, `01`, `05`, `10`, `15`, `20`, `25`, `28`, `30`; `0` cobra al suscribir. |
| `automatic_renewal` | `T` o `F`. |
| `trial_days` | Dias sin cobro. |
| `num_charges` | Cantidad programada de cargos. |

El monto de Plan es una referencia comercial. Para ingresos reales usar Charges pagados o Payments pagados, no multiplicar planes por suscripciones sin controlar estado, prueba, cancelaciones, UF y cargo variable.

### 6.4 Suscription

Llave natural: `plataforma + id`.

| Campo | Uso |
| --- | --- |
| `id` | ID de suscripcion; relaciona Charges. |
| `status` | Estado de ciclo de vida. |
| `plan_id`, `plan_name` | Relacion y descripcion comercial. |
| `suscription_date` | Alta; usar como fecha de cohorte. |
| `currency`, `amount` | Valor vigente reportado por la suscripcion. |
| `automatic_renewal` o `renewal` | La documentacion y respuestas usan ambos nombres; normalizar a una columna. |
| `service_id`, `channel`, `origin`, `seller_id` | Atributos de trazabilidad comercial cuando existan. |
| `payment_method.*` | BIN, emisor, marca, ultimos cuatro, vencimiento y tokenizacion. |
| `charge_program[]` | Programa de cargos; no reemplaza la extraccion detallada de Charges. |
| `client.*` | Datos de cliente asociados. |

Estados documentados:

| Estado | Interpretacion |
| --- | --- |
| `SUSCRIBIENDO` | Flujo inicial; medio de pago aun no confirmado. |
| `SUSCRIPCION_FALLIDA` | No se pudo inscribir medio de pago. |
| `ACTIVA` | Medio de pago valido inscrito; no implica cobro exitoso reciente. |
| `CANCELADA` | Detenida; no deberia procesar cargos futuros. |
| `FINALIZADA` | Expirada; espera maxima por defecto de 30 dias. |

El campo derivado `estado_secundario` del proyecto se calcula asi:

| Condicion | Valor |
| --- | --- |
| Estado no activo | `Incobrable` |
| Activa sin Charge pagado | `Nunca se ha cobrado` |
| Activa y ultimo Charge pagado hace menos de 6 meses | `Cobrable` |
| Activa y ultimo Charge pagado hace 6 o mas meses | `Incobrable` |

Esta clasificacion es analitica propia; no es un estado oficial de VirtualPOS.

### 6.5 Charge

Llave natural: `plataforma + id_suscripcion + id`.

| Campo | Uso |
| --- | --- |
| `id` | ID del Charge. |
| `suscription_id` | Relacion obligatoria al contexto de extraccion. |
| `charge_date` | Fecha programada; base de vencimiento y forecast. |
| `created_at` | Fecha de generacion del Charge. |
| `amount` | Monto programado. |
| `status` | Estado financiero del cobro. |
| `description`, `internal_code` | Trazabilidad comercial. |
| `payment.order.*` | Payment resultante si existe: UUID, autorizacion, monto, tarjeta, comisiones y abono. |
| `payment.client.*` | Cliente asociado. |

Estados: `pendiente`, `pagado`, `cancelado`, `procesando`, `rechazado`.

Un Charge es mutable: puede pasar de pendiente/procesando a pagado/rechazado, y un rechazado puede reintentarse. Por eso el upsert es correcto; no es una tabla solo de insercion.

### 6.6 Client

Llave oficial: `plataforma + uuid`. La API declara `uuid` como identificador unico interno del cliente.

| Campo | Regla documentada |
| --- | --- |
| `uuid` | Solo respuesta; formato `cli_<alfanumerico>`. |
| `type` | Requerido: `PERSONA` o `EMPRESA`. |
| `first_name` | Requerido; para empresa corresponde a razon social. |
| `last_name` | Requerido para `PERSONA`; opcional para `EMPRESA`. |
| `email` | Requerido y unico por comercio. |
| `social_id` | Opcional, pero unico por comercio si existe. |
| `social_id_type` | `1` RUT, `2` DNI; la API tambien puede devolver etiqueta como `RUT`. |
| `status` | `ACTIVO` o `BLOQUEADO`. |
| `created`, `updated` | Auditoria de fuente; `updated` es valioso para futuro incremental. |

El codigo actual usa `plataforma + rut + email` como clave de upsert. Es una desviacion del contrato: debe migrarse a `plataforma + uuid`, conservando RUT y email como atributos. De lo contrario, cambios de email/RUT o clientes sin esos campos pueden duplicar o fusionar registros incorrectamente.

## 7. Mapeo actual hacia Google Sheets

| Funcion | Hoja | Tipo de carga | Clave actual | Observaciones |
| --- | --- | --- | --- | --- |
| `API_SYNC_PAGOS` | `API Pagos` | Upsert sobre listado completo | `plataforma + uuid_pago` | Debe aprovechar filtros `created_*` / `authorization_*` para incremental. |
| `API_SYNC_PLANES` | `API Planes` | Upsert sobre listado completo | `plataforma + id` | El endpoint no documenta filtro de fecha. |
| `API_SYNC_SUSCRIPCIONES` | `API Suscripciones` | Upsert sobre listado completo | `plataforma + id` | Depende de Cobros para estado derivado. |
| `API_SYNC_COBROS` | `API Cobros` | Upsert por cola y triggers | `plataforma + id_suscripcion + id` | Fan-out obligatorio: no existe ruta global. |
| `API_SYNC_CLIENTES` | `API Clientes` | Upsert sobre listado completo | `plataforma + rut + email` | Corregir hacia UUID. |

La API puede variar nombres de campos entre respuestas. El proyecto ya tolera algunas variantes mediante `primerValor_`: `id`/`subscription_id`/`uuid`, `automatic_renewal`/`renewal`, `phone`/`phone_number`, `last4CardDigit`/`last4`. Mantener esa capa, pero registrar campos inesperados y no ocultar silenciosamente una deriva de esquema.

## 8. Estrategia de carga recomendada

### Primera carga historica

1. Preparar hojas y validar encabezados.
2. Cargar Plans, Clients y Suscriptions.
3. Cargar Payments en paginas de 100.
4. Cargar Charges mediante cola, permitiendo que terminen los triggers.
5. Recalcular `estado_secundario` solo tras terminar Charges.
6. Comparar conteos API vs Sheet por cuenta y entidad.
7. Registrar fecha de corte, ambiente y resultado como una corrida identificable.

### Carga diaria incremental

| Entidad | Watermark propuesto | Ventana de solape | Motivo |
| --- | --- | --- | --- |
| Payments | `created_at` y/o `authorized_at` | 48 horas | Un Payment puede autorizarse despues de creado. |
| Clients | `updated` si la API permite filtro; si no `created_from` mas relectura controlada | 7 dias | Cambios de datos y bloqueos. |
| Suscriptions | Sin filtro documentado por fecha | Completa o confirmar filtros con proveedor | Su estado puede cambiar. |
| Charges | No hay ruta global ni filtro de fecha global | Recorrer activas y recientemente cerradas; definir retencion | Cambios de estado y reintentos. |
| Deposits | `deposit_date` | Releer ultimos 7-14 dias | Ajustes, retenciones y verificacion tardia. |

Un solape no duplica datos si el upsert usa llave estable. No avanzar un watermark cuando una cuenta, pagina o lote queda parcial.

## 9. Calidad de datos y controles

Controles minimos por corrida:

| Control | Regla |
| --- | --- |
| Unicidad | Ninguna clave de hoja puede repetirse. |
| Completitud | `plataforma` e ID principal deben existir en cada fila. |
| Conteos | Comparar `pagination.total` con registros extraidos por cuenta cuando este disponible. |
| Dominio de estados | Alertar valores fuera de los estados documentados; no descartarlos. |
| Moneda | Reportar CLP y UF separados; no sumar sin conversion y fecha UF definida. |
| Fechas | Conservar fecha API como texto ISO o convertir con zona horaria explicitamente; no desplazar `YYYY-MM-DD`. |
| Importes | Tratar monto, comision y abono como numericos; nunca formatear como texto antes de conciliar. |
| Relaciones | Todo Charge debe tener `id_suscripcion`; toda suscripcion debe conservar `plan_id` cuando la fuente lo entregue. |
| Actualizacion | Detectar cambios en estado, monto, autorizacion, abono y tarjeta sin crear duplicados. |

Indicadores operativos:

- Frescura: minutos/horas desde ultima corrida exitosa por entidad y cuenta.
- Exhaustividad: filas extraidas / `pagination.total`.
- Error rate: requests fallidos / requests totales.
- Cobertura de cobros: suscripciones procesadas / suscripciones en cola.
- Reconciliacion: diferencia entre `total_deposit` y formula de componentes.
- Conversion: Payments o Charges pagados / total de intentos, separado por canal y medio de pago.

## 10. Errores y comportamiento financiero

La respuesta de error tiene `error.error_code`, `error.message` y `error.doc_url`. Ejemplos operativos importantes:

| Codigo | Significado | Tratamiento |
| --- | --- | --- |
| `E-001`, `E-002`, `E-014`, `E-015`, `E-016` | Credenciales o firma | Detener cuenta; no reintentar hasta corregir configuracion. |
| `E-090`, `E-091` | `page` o `limit` invalido | Corregir extractor. |
| `E-041`, `E-066`, `E-082` | No hay datos para entidad | Registrar cero filas si el contexto lo permite; no tratar como fallo de conectividad. |
| `E-047` | Plan inexistente asociado a suscripcion | Registrar fila/ID; el flujo de Cobros hoy lo omite silenciosamente. Medirlo. |
| `E-081` | Charge no cumple condiciones de reintento | No reintentar automaticamente. |
| `E-109`, `E-110` | Fecha invalida o sin movimientos de abono | Validar `YYYY-MM-DD`; `E-110` puede ser ausencia valida de movimientos. |

Un rechazo financiero no es un error tecnico. Puede venir como Payment en estado `rechazado`, incluso con HTTP `201` al autorizar. Conservar `rejected_object.code` y `rejected_object.message` cuando el flujo de negocio requiera analisis de rechazo; no confundirlo con fallo del extractor.

## 11. Webhooks, retencion y trazabilidad

VirtualPOS puede enviar un `POST` al `callback_url` con `uuid` tras finalizar un Payment. El receptor debe consultar despues `GET /v3/payment/{uuid}`; el webhook no debe considerarse fuente completa de datos.

La documentacion exige conservar por al menos un ano para pagos autorizados: UUID, fecha de autorizacion, monto, codigo de autorizacion, numero de cuotas y monto de cuota. Las hojas actuales contienen esos campos para Payment y Charge asociado, pero requieren controles de acceso y respaldo.

Modelo de auditoria recomendado para futuras mejoras:

| Campo | Uso |
| --- | --- |
| `run_id` | Identifica una corrida completa. |
| `entity`, `platform`, `primary_key` | Identifica el objeto fuente. |
| `action` | `nuevo`, `actualizado`, `sin_cambios`, `error`. |
| `field`, `old_value`, `new_value` | Cambio de atributos no sensibles. |
| `redacted` | Indica que PII no se persistio en auditoria. |
| `source_observed_at`, `loaded_at` | Diferencia tiempo de fuente y tiempo de carga. |

## 12. Limitaciones, discrepancias y decisiones pendientes

| Tema | Hallazgo | Decision recomendada |
| --- | --- | --- |
| HTTP exitoso | Payments puede responder `201` al autorizar. | El cliente acepta todo rango `200-299`. |
| Firma POST | La guia muestra ejemplos JWT con atributos de la solicitud, pero el cliente actual firma solo `api_key`. | Validar el contrato exacto por endpoint en sandbox o con soporte antes de cambiar la firma. |
| Clientes | La llave oficial es UUID y RUT/correo pueden cambiar. | Se usa `plataforma + uuid`. |
| Variantes de esquema | `renewal`/`automatic_renewal`, `phone`/`phone_number`, tipos string/numericos. | Normalizar y conservar raw opcionalmente. |
| Cobros | Sin listado global. | Se mantiene cola/checkpoint con lock global, continuacion por trigger y estado persistente. |
| Incremental | Payments admite filtros por fecha. | Watermark por cuenta y ambiente, con solape de 48 horas. |
| Deposits | Se agregaron hojas de liquidacion y conciliacion basica. | Validar el esquema de detalle frente a Sandbox cuando cambie la API. |
| Reintentos | `429`, red y `5xx` son fallos transitorios. | Cliente HTTP con hasta tres intentos, backoff y `Retry-After`. |
| Payout | Fuera de alcance por mTLS. | Resolver en servicio fuera de Apps Script si se necesita. |
| Webhooks | Sin receptor en el proyecto. | Mantener polling para reporting; agregar receptor externo si se requiere tiempo real. |

## 13. Referencia de archivos del proyecto

| Archivo | Responsabilidad |
| --- | --- |
| `Config.js` | Endpoints, propiedades, JWT, headers, hojas, setup y upsert. |
| `Cliente.js` | Cliente HTTP, query string, parseo, paginacion y tolerancia de schema. |
| `Payment.js` | Payments, Web Checkout, autorizacion, envio, intentos y deposits. |
| `Plan.js` | Plans. |
| `Suscription.js` | Suscriptions y estado secundario derivado. |
| `Charge.js` | Charges, cola, checkpoint y continuacion por trigger. |
| `ReporteDiario.js` | Borrador de email a partir de hojas ya sincronizadas. |
| `Dashboard.js` | KPIs y tablas analiticas en Google Sheets. |
| `Debug.js` | Inspeccion manual de contratos; no usar para persistir PII. |
| `MenuNuevaAPI.js` | Menus, ejecuciones manuales y reconstruccion completa. |
| `Deposit.js` | Abonos, ventas, retenciones y conciliacion basica. |
| `SyncCore.js` | Locks, corrida diaria, watermarks, estado operativo y `run_id`. |

## 14. Validacion y despliegue

Fecha: 2026-08-25.

- Despliegue realizado mediante `clasp push`: 15 archivos sincronizados con el proyecto Apps Script.
- Validacion funcional confirmada por operacion: sincronizaciones, Cobros reanudables, Abonos, reporte y dashboard funcionan correctamente.
- Validacion estatica local: `node --check` para todos los archivos JavaScript y `git diff --check` sin errores de whitespace.
- Mantener la prueba de contrato Sandbox como control recurrente cuando VirtualPOS cambie su API o credenciales.

## 15. Checklist antes de operar produccion

- [ ] Confirmar que cada credencial corresponde a cuenta y ambiente correctos.
- [ ] Ejecutar pruebas en sandbox sin registrar datos de tarjetas de prueba fuera de los flujos autorizados.
- [ ] Validar conteos, IDs y estados contra una muestra de la consola VirtualPOS.
- [ ] Confirmar zona horaria de negocio `America/Santiago` y formato de fechas.
- [ ] Restringir acceso a hojas con PII y datos financieros.
- [ ] Verificar que no haya sync de Charges pendiente antes de interpretar KPIs de cobrabilidad.
- [ ] Registrar y revisar errores por cuenta en `API Log`.
- [ ] No usar una corrida parcial para reportes financieros o de recaudacion.
- [ ] Validar conciliacion de abonos antes de reportar ingresos netos.
- [ ] Mantener esta guia actualizada cuando VirtualPOS modifique contratos o se agreguen rutas.
