# Investigación: captura de código y glosa de rechazo (VirtualPOS, Toku, Payku)

Fecha de medición: 2026-10-29. Solo lectura. Bases consultadas: `crm` (agregados, sin filas). API: solo sandbox de VirtualPOS, 15 peticiones GET en total (tope 30). Sin datos personales.

## 0. Conclusión corta

| Canal | ¿Hay un endpoint que traiga el código/glosa? | ¿Ya está en nuestra base? | Qué falta |
|---|---|---|---|
| VirtualPOS | Sí, pero NO en el listado. `GET /v3/payment/{uuid}` trae `rejected_object` (medido en sandbox, nivel superior de la respuesta, hermano de `payment`). `GET /v3/payment/{uuid}/attempts` (documentado) agrega los intentos con `response_code` del adquirente. | No (0 de 73.013 pagos y 237.915 cobros tienen `rejected_object`/intentos en `raw_payload`). | Llamar al detalle (1 petición por pago rechazado) o importar el reporte PAT del portal (0 peticiones, cubre el 100% de los rechazos). Además falta el vínculo pago-cobro. |
| Toku | Sí, y YA LLEGA: el listado `GET /transactions` trae `transaction.response_code` y `original_response_message` por transacción. | Sí, en `tk_transactions.raw_payload`. | Solo proyectarlo a `core_*` (no requiere API). Quedan 1.267 FAILED sin ningún dato (4,3%). |
| Payku | Sí: el listado `GET /api/transaction?rejected=true&date_init&date_end` trae `gateway_response.message` y `subscriptions.id` por fila. | No (las transacciones embebidas en la suscripción solo traen `transaction, order, created_at, status, amount, authorization_code, description`). | Un barrido por meses (aprox. 75 peticiones, no 8.595) y cruzarlo por `order` + fecha. Requiere una prueba de 1 petición en producción (el sandbox de Payku no existe). |

La intuición del usuario ("en algún listado de los últimos 30 días viene el código") es correcta para Toku (ya lo tenemos) y Payku (listado de transacciones con filtro de fechas y de rechazadas); es incorrecta para VirtualPOS, donde el listado de pagos no lo trae.

## 1. VirtualPOS

### 1.1 Qué endpoints devuelven código/glosa (doc + Postman + medición)

La colección Postman tiene, entre otros: `GET /v3/payments` (listar), `GET /v3/payment/:uuid`, `GET /v3/payment/:uuid/attempts`, `GET /v3/payment/:uuid/logs`, `GET /v3/suscription/:id/charges`, `GET /v3/charge/:id`, `GET /v3/charge/:id/retry`. No hay webhook de cobros recurrentes.

| Endpoint | Parámetros | ¿Trae código/glosa de rechazo? | Evidencia |
|---|---|---|---|
| `GET /v3/payments` | `page`, `limit` (máx. 100) | No. Solo `order{uuid,status,amount,created_at,authorized_at,payment_method,deposits,...}` y `client`. | Medido en `crm`: 73.013 pagos, 0 con `rejected_object`; claves de `order` listadas. Medido en sandbox: mismas claves. |
| `GET /v3/payment/{uuid}` | ninguno | Sí: `rejected_object {code, message, doc_url}` en el nivel superior de la respuesta (no dentro de `order`). Para un pagado devuelve `code:"0"`, `message:"Operación exitosa"`. Para un expirado la clave no viene. | Medido en sandbox (2 pagos, 200 OK). Un pago rechazado real no se pudo medir: el sandbox tiene 38 pagos (33 pagado, 4 expirado, 1 cancelado), 0 rechazados. |
| `GET /v3/payment/{uuid}/attempts` | ninguno | Documentado: `payment.order.authorization_attempts_cards[]` con `created_at, response_code, acquirer, response_message, response_description, authorization_type` y `rejected_object` del último resultado. | Doc `payments.md` (ejemplo con `-2122`, Klap, "VIOLACION DE SEGURIDAD"). En sandbox responde **403 Forbidden** (también `/logs`), así que NO se pudo verificar. |
| `GET /v3/payment/{uuid}/logs` | ninguno | Solo texto libre de bitácora ("Transacción PAT autorizada."); no es fuente de código. | Doc. 403 en sandbox. |
| `GET /v3/suscription/{id}/charges` | `status` (pendiente/pagado/cancelado/procesando/rechazado), `page`, `limit`; `charge_date_from/to` se ignoran (handoff §9) | No trae `rejected_object`, pero cada cobro trae `payment{client,commerce,order{uuid,status,card_number,auth_code,authorized_at,...}}`. Es decir, aporta el vínculo cobro a `uuid` de pago. | Medido en sandbox con un cobro pagado: claves `amount, charge_date, created_at, description, id, internal_code, payment, status`. Falta confirmar que un cobro RECHAZADO también trae `payment` (la doc lo deja como duda: `discrepancies.md`). |
| `GET /v3/charge/{id}` | ninguno | Igual que arriba: `payment.order.uuid`, sin `rejected_object`. | Medido en sandbox. |
| `charge_program[]` (dentro de la suscripción) | | No: solo `id,status,charge_date,amount,currency,description`. | `vp_charges.raw_payload` en `crm`. Es lo que usa el sync. |
| Webhook de Payment | `callback_url` | Solo envía el `uuid` (formato y firma no documentados); hay que releer `GET /payment/{uuid}`. No existe webhook para cobros recurrentes. | `webhooks.md`. `stg_vpos_webhook_events` tiene 80 filas (no es una fuente de glosas). |

Forma de la respuesta del detalle (sandbox, sin datos personales):
```
{ "status":"OK","code":200,"commerce":{...},"payment":{"client":{...},"order":{"uuid","status","amount","created_at","authorized_at","auth_code","card_number","payment_method","payment_type_code","bank","deposits":[...]}},
  "rejected_object":{"code":"0","message":"Operación exitosa","doc_url":"..."} }
```
Los errores llegan con HTTP 200/400 y `{"status":"NOK","error":{"error_code":"E-0xx"}}` (handoff §9). La doc advierte que `rejected_object` usa `code` o `error_code` según el ejemplo: leer ambos.

Hallazgo de código: `_enrich_charges_with_rejections` (`app/services/core_vp_etl.py:245`) busca `rejected_object` DENTRO de `order` (`payload.payment.order.rejected_object`), pero la API lo entrega en el nivel superior de la respuesta, como hermano de `payment`. Aunque se guardara la respuesta completa del detalle, esa función no lo encontraría. Además exige `vp_payments.charge_external_id`, que es NULL en las 73.013 filas.

### 1.2 Dónde está el dato hoy en nuestra base

| Dato | Conteo |
|---|---|
| `vp_payments` rechazados | 24.043 (virtualpos1 9.410, virtualpos2 14.633), todos entre 2025-02-24 y 2026-10-28 |
| `vp_charges` rechazados | 23.891 (todos desde 2025-02-24) |
| `vp_payments` con `rejected_object` o intentos en `raw_payload` | 0 |
| `vp_payments.charge_external_id` no nulo | 0 |
| `core_payments.rejection_code/reason` en VP | 0 (0 de 23.755 rechazados) |
| `core_charges.latest_rejection_code` en VP | 0 (0 de 238.000 cobros; 0 de 23.891 rechazados) |
| Suscripciones con al menos un cobro rechazado | 3.759 (2.714 con rechazo en los últimos 35 días) |
| Volumen diario | ~110 pagos rechazados por día (3.051 en octubre; 3.228 en los últimos 30 días); 131 cobros rechazados en los últimos 2 días |

Fuente SIN API (backfill): los reportes `TransaccionesPAT-VirtualPOS-*.csv` del portal (42 archivos, 86.541 `Id cargo` únicos, ventana programada 2025-02-24 a 2026-10-26) traen "Código y Glosa de autorización/error/rechazo" más `UUID transacción` enlazado 1 a 1 con `Id cargo` (parity_virtualpos.md). Como TODOS los rechazos del CRM son posteriores a 2025-02-24, el reporte cubre el 100% del histórico salvo lo posterior al corte (27 y 28 de octubre, ~130 cobros). Esto resuelve a la vez la glosa y el vínculo pago-cobro, sin una sola petición. Es la tarea VP-PAR-02/03 ya propuesta; no existe aún el importador.

### 1.3 Catálogo existente (`app/services/vp_rejection_codes.py`)

- 27 códigos (-1 a -11 y -1001 a -1018). Coincide exactamente con el "Objeto Rechazo" de `errors.md` (sin faltantes ni sobrantes).
- Huecos: los códigos negativos de 4 dígitos del adquirente (-2119, -2121, -2122, -2133, -2150, -2152, ...). La doc oficial dice explícitamente que no tienen catálogo (`discrepancies.md`). El reporte del portal registra 165 rechazos con 12 de estos códigos. La glosa de `response_description`/`response_message` del intento (o la glosa del reporte) es la única fuente.
- `format_rejection_reason` prefiere el texto del catálogo sobre el del proveedor: correcto para los códigos oficiales, y devuelve el texto del proveedor si el código no está. Para el esquema final conviene guardar SIEMPRE los dos (código y texto crudo del proveedor) y dejar la traducción para la capa de presentación.
- Verificar el texto del `-11`: el reporte lo llama "Excede límite de reintentos de rechazo" (11.155 casos, el más frecuente) y el catálogo dice "El pagador excedió el límite de rechazos de la marca". Se debe acordar la redacción.

### 1.4 Medición en sandbox (15 GET, APP_ENV=sandbox fijado antes de importar settings)

- `list_payments`: 38 pagos, sin `rejected_object`; una segunda página devuelve E-041 ("no existen transacciones").
- `payment/{uuid}` en pagado y expirado: 200; solo el pagado trae `rejected_object`.
- `attempts` y `logs`: 403 con la llave sandbox (4 de 4). Hipótesis: permiso/producto no habilitado en sandbox o en la cuenta. NO se insistió. Para confirmarlo hace falta 1 GET en producción con un `uuid` rechazado conocido (decisión del usuario).
- `list_subscriptions` (20 suscripciones): cobros pendiente 94, cancelado 1.343, pagado 32, rechazado 0. `charges` y `charge/{id}` de un cobro pagado traen `payment.order.uuid`.
- El sandbox no tiene datos de rechazo: no se pudo ver la forma real de un rechazo.

### 1.5 Diseño recomendado de captura (VirtualPOS)

1. Hacia adelante (diario): en `virtualpos_sync.py`, después de guardar pagos, tomar los pagos rechazados que aún no tienen glosa (`rejection_checked_at IS NULL`) y llamar `GET /v3/payment/{uuid}` (o `/attempts` si en producción responde 200; trae además el código del adquirente). Tope por corrida (p. ej. 500), pausa de 0,3 a 0,5 s entre peticiones, reintento con backoff en 429/5xx, y marcar `checked_at` aunque falle (con contador de intentos) para no reintentar sin fin. Costo: unas 110 peticiones por día.
2. Vínculo pago a cobro (necesario para `core_charges.latest_rejection_*`): para las suscripciones con cobros rechazados nuevos, `GET /suscription/{id}/charges?status=rechazado` y leer `payment.order.uuid` (si un rechazado también lo trae; confirmar en producción con 1 petición). Costo: aprox. una petición por suscripción afectada por día (unas 130 al día). Alternativa sin API para el histórico: el reporte PAT (`Id cargo` a `UUID transacción`).
3. Destino: ver sección 5 (tabla de detalle de rechazo) y luego una paso de "aplicar" que ACTUALICE `core_payments.rejection_*` y `core_charges.latest_rejection_*`. Hoy `core_vp_etl.py:395` inserta pagos con `on_conflict_do_nothing`, por lo que los pagos ya existentes nunca se actualizarían; hace falta `UPDATE ... FROM` explícito o `on_conflict_do_update`.
4. Backfill:
   - Opción A (recomendada): importar los reportes PAT (0 peticiones) para código, glosa y vínculo del histórico 2025-02-24 a 2026-10-26.
   - Opción B (solo API): 24.043 `GET payment/{uuid}` + 3.759 `charges` por suscripción. A 2 peticiones por segundo son 3,5 horas, a 4 por segundo 1,7 horas; el límite de tasa de VP está sin medir (handoff §9), por lo que se debe empezar a 2/s con backoff y subir. Corrida reanudable por lotes de 500.
   - Lo que se puede hacer con datos ya guardados: nada para VP (el dato nunca se guardó).

## 2. Toku

### 2.1 Endpoints y forma de respuesta

| Endpoint | Parámetros | Código/glosa |
|---|---|---|
| `GET /transactions` | `page`, `page_size` (máx. 100), `start_date`, `end_date` (se comparan con la fecha de la transacción), `status` (`FAILED`, ...), `id_invoice`, `id_customer`, `types`; 1 petición por segundo | Sí: `items[].transaction.response_code` (formato `TEPSP1008` = gravedad(2) + fuente(3) + detalle(4)) y `original_response_message` (texto crudo del procesador). |
| `GET /transactions/{id}` | | Misma `AggregatedTransaction`. |
| Webhooks `transaction.failed` / `bulk_failed` | | Mismo objeto agregado (no se usa; `stg_toku_webhook_events` tiene 38 filas). |
| `GET /payment-methods` | | `toku_response_code` de la inscripción: viene vacío en todos los medios (handoff §7). |
| Reporte "Intentos de pago" del Backoffice | carga manual | Código de respuesta Toku por intento, 99,8% con código. Importador hecho (TK-17/18), falta la ruta de subida (TK-19). |

Forma (sin datos personales): `{"transaction":{"id","type":"PAYMENT","status":"FAILED","amount","response_code":"TEPSP1008","original_response_message":"[05] RECHAZADA- CONTACTE A SU EMISOR","transaction_date","id_payout","voucher",...},"payment_intents":[{"id","id_invoice","id_subscription","amount","status"}],"customer":{...},"payment_instrument":{...}}`.

El ítem ya se guarda completo: `tk_transactions.raw_payload` tiene las claves `transaction, customer, payment_intents, payment_instrument, wallet_movements`. El sync actual pagina `/transactions` sin ventana de fechas.

### 2.2 Dónde está el dato (conteos en `crm`)

| Medida | Valor |
|---|---|
| `tk_transactions` total / FAILED | 31.675 / 29.238 (rango 2024-10-10 a 2026-10-28) |
| FAILED con `response_code` | 23.826 (81,5%); 21 códigos distintos (19 detalles de 4 dígitos) |
| FAILED con `original_response_message` | 27.971 (95,7%); 451 mensajes distintos (este es el "catálogo de ~400") |
| FAILED sin código pero con mensaje | 4.145 |
| FAILED sin código ni mensaje | 1.267 (4,3%) |
| FAILED sin código por mes | nov-2024 a ago-2025 prácticamente todos; sep-2025 28 de 7.294; oct-2025 94 de 660; desde nov-2025 cero |
| FAILED con `payment_intents[0].id_invoice` | 29.237 de 29.238; 27.305 enlazan con un `core_charges` Toku (1.725 cobros distintos) |
| `core_payments` Toku | 2.377 (solo los pagos de `tk_payments`; las transacciones FAILED NO se materializan en core); `rejection_*` = 0 |
| `core_charges` Toku | 6.363 (3.984 UNPAID); `latest_rejection_*` = 0 |
| `tk_report_attempts` / `tk_report_response_codes` | 0 / 0 filas (importador sin usar) |
| `source_records` transaction Toku | 50.505 filas (31.675 transacciones distintas; la clave `external_id` de `source_records` difiere de la de `tk_transactions`; el dato es el mismo) |

Prefijos de código en los FAILED con código: TEPSP10xx 19.762, TEPSP20xx 2.599, TETOK20xx 625, PEPSP10xx 486, UEPSP99xx 130, PEBCH20xx 110, TEBCH10xx 102, otros 12.

Hallazgo: el "código" no solo falta en la proyección; para 4.145 de los 5.412 sin código existe la glosa del procesador, con un número ISO 8583 entre corchetes (`[51]`, `[05]`, `[91]`) que sirve de código secundario.

### 2.3 Catálogo

- Oficial: hoja "Códigos de Error Toku" del reporte `Toku_intentosdepago.xlsx` (24 códigos de detalle: 0000, 1001, 1002, 1007, 1008, 1010, 1011, 1017, 1019, 1059, 1062, 1073, 2005, 2006, 2008, 2009, 2028, 2035, 2063, 2070, 2106, 4007, 5408, 9999; columnas Gravedad, Mensaje, Descripción). Cubre el 100% de los códigos presentes en nuestros FAILED (23.826 de 23.826). Se indexa por los 4 últimos dígitos del `response_code`.
- Huecos: las reglas DEC-16 a DEC-25 usan 1051, 2043 y 2044 y esos NO están en la hoja de 24 códigos; hay que pedirlos a Toku o tomarlos de la lista web (`docs.trytoku.com/reference/codigos-de-pago-rechazado`). La tabla `tk_report_response_codes` está vacía y no hay catálogo en código Python.
- Las 451 glosas del procesador son texto libre con fechas y horas incrustadas ("REINTENTAR EL 01-10-2025 A LAS 07:33"): para agrupar hay que normalizarlas (quitar fecha y hora, extraer el número entre corchetes).

### 2.4 Diseño recomendado (Toku)

1. Nada de API para lo ya descargado. Proyectar en el ETL (`core_toku_etl.py`): para cada `tk_transactions` FAILED, `rejection_code` = `response_code` (o `[NN]` del mensaje si no hay), `rejection_reason` = `original_response_message`, `rejection_reported_at` = `transaction_date`. Hoy no se crea ningún `core_payments` para FAILED; hay que decidir si se materializan los intentos fallidos como pagos (decisión 2) o solo se actualiza `core_charges.latest_rejection_*` con el intento más reciente por cobro (menor riesgo, 1.725 cobros).
2. Enlace: `payment_intents[0].id_invoice` = `core_charges.external_id` (27.305 de 29.238 enlazan). El sync ya trae todo el historial.
3. Hacia adelante: sin cambios en la API; el listado ya trae ambos campos. Cuidado: el sync no tiene ventana de fechas; si se agrega, usar `start_date` con solapamiento de 24 h y volver a leer los `INITIALIZED`.
4. Para los 1.267 sin dato (y para tener código en los 4.145 sin código): cargar el reporte "Intentos de pago" con el importador existente (TK-19) y completar por el id de intento/transacción. Verificar con solo el encabezado si la columna de intento coincide con `transaction.id` (si no, cruzar por `id_invoice` + fecha). Alternativa API: `GET /transactions?status=FAILED&start_date&end_date` por ventanas mensuales (unas 12 ventanas, 100 por página, 1 petición por segundo, miles de páginas): solo vale la pena si se comprueba antes con 3 a 5 `GET /transactions/{id}` que la API devuelve el código para esas fechas. No se puede medir en sandbox (0 transacciones; comparte host con producción, por lo que la prueba es con el usuario).

## 3. Payku

### 3.1 Endpoints

| Endpoint | Parámetros | Glosa |
|---|---|---|
| `GET /api/transaction` | `date_init`, `date_end` (AAAA-MM-DD), `success`/`pending`/`rejected` (booleanos), `page`, `per_page` (máx. 4000) | Cada fila trae `status`, `gateway_response {status, message}`, `order`, `payment {...}`, `subscriptions {id, status}`. Mensajes documentados: `successful transaction`, `Rechazo de transacción.`, `Transacción debe reintentarse.`, `Error en transacción.`, `Rechazo por error de tasa.`, `Excede cupo máximo mensual.`, `Excede límite diario por transacción.`, `Rubro no autorizado.` |
| `GET /api/transaction/{id}` | id, `payment_key` o `transaction_key` | Igual que una fila del listado. 404 si no existe. |
| `GET /api/sususcription`, `/sususcriptionv3` | | Cobros embebidos (`transactions[]`, `paid[]`) SIN `gateway_response`. |

Evidencia de que el listado trae la glosa y la suscripción: el proyecto histórico `Downloads\API_Payku` (`src/api/transactions.py`, `src/sync/sync_transactions.py`) hacía exactamente eso: iteraba mes a mes (por timeouts en rangos amplios), `per_page=4000`, `success=true&rejected=true`, y guardaba `gateway_response.message` y `subscriptions.id`. Su ejemplo (`docs/api_responses/07_transaction_list.json`) tiene las claves `status, id, created_at, order, email, full_name, phone, subject, amount, payment, gateway_response, subscriptions`. No pude medir en vivo: Payku no tiene sandbox y la regla del proyecto exige al usuario para producción.

### 3.2 Dónde está el dato

| Medida | Valor |
|---|---|
| `p_transactions` | 35.969 (success 27.018, rejected 8.595, pending 356); 2020-08-18 a 2026-10-25 |
| Rechazados por año | 2020 101, 2021 543, 2022 928, 2023 1.303, 2024 1.644, 2025 1.930, 2026 2.146 |
| Órdenes distintas entre los rechazados | 2.528 (varios intentos por orden) |
| Claves de `raw_payload` de una transacción | `transaction, created_at, status, amount, order, authorization_code, description` (sin mensaje) |
| `p_subscriptions.raw_payload.logs.status` | historial de estado de la suscripción (`initial_status` a `final_status`, `change_date`); NO es de cobros |
| `p_subscriptions.last_status_current_payment` | código grueso: maximum attempt limit 1.247, first payment rejected 217, retry 15, canceled by paymaster 58, canceled by customer 7 (parity_payku.md) |
| `core_payments` Payku rechazados / con `rejection_*` | 8.560 / 0 (core_payku_etl pone `None`; `charge_id` también `None`; no hay `core_charges` Payku) |

Los reportes de Payku solo traen cobros exitosos: no hay glosa de rechazo en ningún archivo (parity_payku.md).

Clave de cruce: `p_transactions.external_id` = valor de `transaction` embebido (6 a 16 caracteres), distinto del `id` numérico del listado `/api/transaction` (según la doc, `id` del listado es un número). La clave más segura es `order` + `created_at`: entre los rechazados no hay ninguna pareja `(order, created_at)` repetida. Hay que comprobar con una petición real que el `order` del listado es el mismo que el embebido.

### 3.3 Catálogo

Los 8 textos de `errors.md §4` (7 de rechazo y 1 de éxito). No hay códigos. Para presentación basta una tabla texto a categoría (rechazo del emisor / reintentable / error técnico / límite). Huecos: pueden existir mensajes no documentados; por eso hay que guardar el texto crudo y medir los distintos que aparezcan.

### 3.4 Diseño recomendado (Payku)

1. Backfill: barrido por meses de `GET /api/transaction?rejected=true&date_init=<1 del mes>&date_end=<último>&per_page=4000` desde 2020-08 hasta hoy: unos 75 meses, de 75 a 150 peticiones en total (no las 8.595 individuales). Empezar por UN mes pequeño (p. ej. 1 a 3 días con `rejected=true`) para comprobar tiempo de respuesta, forma de la fila y el cruce por `order`. Reanudable por mes; throttle de 1 petición cada 2 a 3 s; parar si hay timeout y partir el mes en semanas.
2. Hacia adelante: añadir al `payku_sync.py` un paso diario: `GET /api/transaction?rejected=true&date_init=<hoy-2>&date_end=<hoy>` (1 o 2 peticiones al día) y cruzar con `p_transactions` por `order` + fecha.
3. Respaldo sin API (PK-PAR-06): derivar un motivo mínimo desde `last_status_current_payment` a nivel suscripción; no es glosa de cobro.
4. Destino: `core_payments.rejection_reason` = `gateway_response.message`, `rejection_code` = clase normalizada derivada del texto (p. ej. `REJECT`, `RETRY`, `ERROR`, `RATE`, `MONTHLY_LIMIT`, `DAILY_LIMIT`, `MCC`), `rejection_reported_at` = fecha. `core_payku_etl.py` también inserta con `on_conflict_do_nothing`: usar UPDATE explícito.

## 4. Qué se puede hacer SOLO con datos ya guardados (cero peticiones)

| Canal | Acción | Cobertura |
|---|---|---|
| Toku | Proyectar `response_code` y `original_response_message` de `tk_transactions` a `core_charges.latest_rejection_*` (y opcionalmente a `core_payments`) | 27.971 de 29.238 FAILED tienen glosa (95,7%); 23.826 tienen código |
| Toku | Traducir el código con el catálogo de 24 (hoja del reporte) | 100% de los códigos presentes |
| Payku | Nada (el mensaje nunca se guardó); solo respaldo grueso por suscripción | 0% por cobro |
| VirtualPOS | Nada desde la base; sí desde los reportes PAT del portal ya descargados (importador pendiente) | 100% de los rechazos hasta 2026-10-26 |

## 5. Esquema destino recomendado

Las columnas de destino ya existen: `core_payments.rejection_code/rejection_reason/rejection_reported_at` y `core_charges.latest_rejection_payment_id/code/reason/at`. Falta un lugar de PASO donde guardar lo que llega de la API sin que el siguiente sync lo borre: `source_records` y las tablas `vp_*`, `tk_*`, `p_*` hacen upsert que reemplaza `raw_payload`, así que enriquecer el `raw_payload` con la respuesta del detalle se perdería en el siguiente sync.

Propuesta (decisión del usuario, requiere migración): una tabla única `payment_rejection_details` con `(source, payment_external_id)` único; `charge_external_id`, `code` (código del proveedor o normalizado), `message` (texto crudo), `acquirer`, `acquirer_code`, `severity`, `retryable`, `origin` (`api_detail`, `api_attempts`, `api_list`, `report`, `raw`), `occurred_at`, `fetched_at`, `fetch_attempts`. Una migración sirve a los tres canales y a TCH. Alternativa más barata: columnas `rejection_code`, `rejection_message`, `rejection_checked_at` en `vp_payments` y en `p_transactions`, y nada en `tk_transactions` (ya tiene el dato en raw). Luego un paso "aplicar" al final de cada ETL core que haga UPDATE de `core_payments`/`core_charges` (el más reciente por cobro) y alimente el catálogo `rejection_reason_catalog` propuesto en SYNC-D-01.

Traducción código a glosa: capa de presentación con tres diccionarios (VP `vp_rejection_codes.py`; Toku por los 4 dígitos finales; Payku por texto) y "respaldo = texto del proveedor" (ya es el comportamiento de `format_rejection_reason`). Generalizar esa función para aceptar `source`.

## 6. Tareas priorizadas

| ID | Descripción | Archivos | Esfuerzo | Riesgo | Migración | Decisión del usuario |
|---|---|---|---|---|---|---|
| RJ-01 | Toku: proyectar `response_code` y `original_response_message` de `tk_transactions` FAILED a `core_charges.latest_rejection_*` (intento más reciente por factura, vía `payment_intents[0].id_invoice`) y, si se decide, a `core_payments`; fallback de código `[NN]` desde el mensaje; UPDATE explícito, no `do_nothing` | `app/services/core_toku_etl.py`, tests | M | Bajo (solo lectura de datos propios) | No | Sí: ¿materializar los intentos FAILED como filas de `core_payments` (aprox. 29 mil) o solo actualizar el cobro? |
| RJ-02 | Catálogo Toku: cargar los 24 códigos oficiales de la hoja a un módulo `toku_rejection_codes.py` (clave: 4 dígitos finales) o a `tk_report_response_codes`; añadir 1051, 2043, 2044 cuando Toku/documentación los entregue; función de normalización de glosas libres (quitar fecha y hora) | `app/services/toku_rejection_codes.py` (nuevo), tests | S | Bajo | No | Conseguir la lista web completa o preguntarle a Toku (los 3 códigos) |
| RJ-03 | Generalizar `format_rejection_reason(source, code, reason)` y usarla en `recovery.py`/exportes; catálogo VP: añadir mensaje propio del proveedor como respaldo y revisar el texto de `-11` | `app/services/vp_rejection_codes.py`, `app/api/v1/routes/recovery.py` | S | Bajo | No | Redacción oficial de `-11` |
| RJ-04 | VirtualPOS: importador de los reportes PAT (código, glosa, `UUID transacción` a `Id cargo`) hacia la tabla/columnas destino; rellena histórico y vínculo pago-cobro; luego "aplicar" a `core_*` | `app/services/vp_report_parser.py`, `vp_report_import.py` (nuevos), `app/models/vp.py`, ETL | L | Medio (hay datos personales en los archivos: leer solo encabezados al probar; el patrón ya existe en `toku_report_*`) | Sí (tabla o columnas) | Aprobar esquema (sección 5) y que el reporte sea la fuente del histórico |
| RJ-05 | VirtualPOS: corregir `_enrich_charges_with_rejections` para leer `rejected_object` en el nivel superior de la respuesta del detalle (y `code` o `error_code`), usar el vínculo de RJ-04/RJ-06 y actualizar con UPDATE | `app/services/core_vp_etl.py`, tests | M | Bajo | No | Ninguna |
| RJ-06 | VirtualPOS hacia adelante: paso del sync que, para pagos rechazados sin glosa, llama `get_payment` (o `get_payment_attempts` si producción responde 200), con tope, pausa, backoff y `checked_at`; y para el vínculo, `list_charges(sub, status="rechazado")` leyendo `payment.order.uuid` | `app/services/virtualpos_sync.py`, `app/integrations/virtualpos/client.py` (ya tiene `get_payment_attempts`), ETL | M | Medio (límite de tasa sin medir; usar tope de 500 por corrida) | Sí (RJ-04) | Autorizar 3 a 5 GET de prueba en producción (ver RJ-07) |
| RJ-07 | Prueba de lectura en producción VP (la hace el usuario o con él): 1 `GET /payment/{uuid}` y 1 `GET /payment/{uuid}/attempts` con un `uuid` rechazado conocido, y 1 `GET /suscription/{id}/charges?status=rechazado` para confirmar que el cobro rechazado trae `payment.order.uuid`; guardar solo claves y código/mensaje | script en el scratchpad | S | Bajo-medio (producción, solo GET) | No | Autorizar |
| RJ-08 | Payku: prueba de 1 petición de `GET /api/transaction?rejected=true&date_init&date_end` en una ventana de 1 a 3 días para confirmar forma, `subscriptions.id` y que el `order` coincide con el embebido; luego capturar | script | S | Medio (producción; antes hubo timeouts y `Bearer` vacío) | No | Autorizar |
| RJ-09 | Payku: backfill por meses (75 a 150 peticiones, reanudable) y paso diario de 1 a 2 peticiones; guardar `gateway_response.message` y normalizar a clase; cruce por `order` + fecha; UPDATE de `core_payments.rejection_*` | `app/services/payku_sync.py`, `app/integrations/payku/client.py` (ya tiene `list_transactions`), `app/services/core_payku_etl.py`, modelo/tabla destino | M | Medio (timeouts en rangos amplios: usar meses, partir en semanas si falla) | Sí (tabla o columna en `p_transactions`) | Esquema; fecha de ventana de la corrida; quién la ejecuta |
| RJ-10 | Payku respaldo: motivo mínimo por suscripción desde `last_status_current_payment` (PK-PAR-06) | `core_payku_etl.py` | S | Bajo | No | Ninguna |
| RJ-11 | Toku: cargar los reportes "Intentos de pago" con el importador existente (completar TK-19: ruta de subida) y usar `tk_report_attempts.response_code` para los 1.267 a 5.412 FAILED sin código; verificar la clave de cruce con el encabezado | `app/api/v1/routes/*` (TK-19), `toku_report_import.py`, ETL | M | Medio (datos personales en el archivo; requiere `TOKU_REPORT_HASH_PEPPER` definido por el usuario) | No (tablas `tk_report_*` ya existen) | Definir el pepper; exportar el reporte; decidir si se completa solo lo que falta |
| RJ-12 | Tabla de paso única `payment_rejection_details` (o columnas, ver sección 5) con índice `(source, payment_external_id)` | `app/models/rejection.py` (nuevo), `alembic/env.py`, migración | M | Medio (migración en `crm`: la aplica el usuario) | Sí | Tabla única o columnas por canal |
| RJ-13 | Evento `reason_changed` y catálogo "nuevas glosas" (SYNC-D-01/05) enganchado a RJ-05/06/09 | según audit_sync.md | M | Bajo | Sí (SYNC-D-01) | Orden de prioridad |
| RJ-14 | Webhooks: no es prioridad (VP solo envía `uuid`; Toku `transaction.failed` trae lo mismo que el listado; Payku solo `success/failed`) | n/a | n/a | n/a | n/a | Mantener diferido |

Orden recomendado: RJ-02, RJ-01 (gana 95,7% de Toku sin migración ni API), RJ-03, RJ-05; en paralelo pedir al usuario las pruebas RJ-07 y RJ-08; luego RJ-12, RJ-04 (cierra VP histórico sin API), RJ-06, RJ-09, RJ-11, RJ-10, RJ-13.

## 7. Riesgos y notas

- `on_conflict_do_nothing` en `core_vp_etl.py:395`, `core_payku_etl.py` y (para insertar pagos) `core_toku_etl.py`: el ETL nunca corregirá filas existentes; todo enriquecimiento debe usar UPDATE explícito.
- Enriquecer `raw_payload` no es seguro: el siguiente sync reemplaza el payload (upsert), por eso se propone una tabla/columnas propias.
- La afirmación del handoff "VP /attempts da el código" sigue sin verificar: la llave sandbox recibe 403. El detalle `GET /payment/{uuid}` sí funciona y trae `rejected_object`; para el código del adquirente (-2xxx) se necesita `/attempts` o el reporte.
- En producción, todo GET de prueba es "con el usuario" (regla 4 del handoff). No se envió ninguna petición a producción.
- Datos personales: ningún conteo ni muestra impresa contiene personas; las claves impresas son de esquema; las glosas de rechazo impresas son texto de procesador sin personas.
- Archivos de apoyo en el scratchpad: `rj1.py` a `rj14.py` y `rj_vp_sandbox.py`, `rj_vp_sb2.py`, `rj_vp_sb3.py` (consultas de agregados y sondas de sandbox, solo lectura).
