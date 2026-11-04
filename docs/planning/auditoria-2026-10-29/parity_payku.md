# Paridad Payku: reportes descargados vs. CRM (base `crm`, solo lectura)

Fecha de auditoría: 2026-10-29. Sin PII impresa; solo encabezados, conteos y distribuciones. Scripts en el scratchpad (`pk_*.py`).

## 1. Inventario de reportes (Downloads\CRM_reportes\Payku)

| Archivo | Hoja | Filas (con encabezado) | Rango | Columnas |
|---|---|---|---|---|
| Payku_dataTransacciones | Export | 10.593 (10.589 útiles + 3 vacías/totales) | 2025-01-01 a 2026-10-20 | Transacción, Comercio ID, Fecha de Transacción, Proveedor, Tipo de Pago, Nombre/Teléfono/Email Origen, Orden, Concepto, Monto, Comisión, Monto Final |
| Payku_datasubscripciones | Export | 826 (822 útiles) | Última cobro 2024-02-05 a 2026-10-20 | Email, Nombre, Teléfono, Suscripción ID, Estatus, Nombre Plan, Frecuencia de Cobro, Tipo de Monto, Última Fecha Cobro, Próxima Fecha Cobro, Monto |
| consolidado_2020..2026 / Transacciones | 1.042, 3.276, 4.019, 6.500, 11.712, 46, 4.854 (total 31.449; 31.442 útiles) | 2020-08-18 a 2026-10-20 (2025 solo trae el 1-ene) | Identificador/vaucher, Fecha, Concepto, Orden, Monto, Comisión, Monto Final, Email, Liquidación, 4 últimos dígitos, Medio de pago, Orden Externa (vacía), Débito/Crédito |
| consolidado_* / Monedero | 107, 295, 327, 281, 266, 1, 218 | | Identificador Monedero, Orden, Concepto, Fecha, Ingreso/Egreso, Monto, Balance, Liquidación Origen, Estatus, Tipo movimiento |
| consolidado_* / Liquidaciones | 94 en cada año (idéntica, 93 filas: 89 Pagado, 4 Pendiente, $33,2 M, depósitos 2026-06 a 2026-10) | | Liquidación, Monto, Estatus, Fecha Depósito |
| consolidado_* / Retiros | 2 (vacía) | | |

Hechos clave sobre el contenido:
- Los reportes contienen **solo transacciones cobradas con éxito** (todo Monto > 0, sin columna de estado ni de rechazo). **No existe glosa de rechazo en ningún reporte.**
- El 2025 se cubre con `dataTransacciones` (el consolidado 2025 solo trae 45 filas del 1-ene). 2026 es idéntico entre ambos archivos (mismos conteos por mes).
- 10.186 filas (aprox. $486 M) son **donaciones puntuales / campañas** (Concepto sin «Cobro: #»: «ARRIBA CHILE - Juntos nos levantamos» 5.676, «Campaña por incendios» 1.072, «Donación puntual», «Rifa...»). El pico de feb-2024 (6.305 filas, $217 M) es una campaña puntual. Esas filas **no están en el CRM** (el sync solo trae transacciones embebidas en suscripciones).
- 2.724 filas del consolidado repiten el «Identificador/vaucher» (mismo monto; 2.136 son cuotas y 589 de la rifa): el voucher no es único en los años antiguos (ids de 3, 14, 16, 19 y 40 caracteres). Desde 2025 sí lo es (16 caracteres).
- En `datasubscripciones` solo hay estados Activa (314) y Suspendida (508); no hay canceladas/eliminadas ni «register». «Monto» **no** es la cuota: es múltiplo de ella (756 de 822 = cuota x (cuotas pagadas + 1)); parece un acumulado. «Próxima Fecha Cobro» solo existe en 295 filas, todas Activas.

## 2. Estado del CRM (base `crm`)

| Tabla | Filas | Notas |
|---|---|---|
| p_clients / p_plans / p_subscriptions / p_transactions | 4.033 / 62 / 5.700 / 35.969 | `p_transactions`: success 27.018, rejected 8.595, pending 356; 2020-08-18 a 2026-10-25; sin duplicados |
| source_records payku | 4.033 / 62 / 5.700 / 35.990 | |
| core_subscriptions (payku) | 5.700 | status crudos: register 3.414, suspended 1.047, active 442, delete 680, cancel 116, otro 1 |
| core_payments (payku) | 35.854 (faltan 115 = oct-2026) | success 26.938, rejected 8.560, pending 356; `rejection_code`/`rejection_reason` = 0 |
| core_charges (payku) | 0 | por diseño (GAP-PK-04) |
| sync_runs payku | 26 completed, 17 failed | los últimos 4 (27 y 28 oct) fallaron: «Illegal header value b'Bearer '» (4 en total), CardinalityViolation en ON CONFLICT (2), getaddrinfo (1), reinicio del servidor (3), vacíos (7) |

Nota: el prompt habla de `pk_*`; los nombres reales son `p_*` (`p_transactions`, etc.).

## 3. Brecha por mes (cuotas de suscripción exitosas: reporte vs `p_transactions` success)

Cuotas = filas del reporte cuyo Concepto contiene «Cobro: #»; 2025-01 en adelante desde `dataTransacciones`.

- **Coincidencia exacta en conteo y en monto en los 74 meses de 2020-08 a 2026-09** (p. ej. 2021-01: 180 / $1.383.500; 2024-12: 506 / $4.812.000; 2026-09: 411 / $4.776.000). Total reporte 26.948 cuotas / $253,50 M vs CRM success 27.018 / $254,33 M.
- Única diferencia: **2026-10**: CRM 341 ($3.973.000) vs reporte 271 ($3.146.000). Causa: el reporte se descargó el 20-oct y el CRM sincronizó hasta el 25-oct (+70 cuotas, +$827.000). No es pérdida de datos.
- Brecha de contenido (no de cantidad): **donaciones puntuales no presentes en el CRM** por mes. Meses relevantes: 2020-10 (271), 2020-11 (274), 2021-10 (315), 2021-11 (143), 2022-12 (335), 2023-02 (1.231), 2024-02 (5.903), 2026-01 (251). Total 10.186 filas / $486 M.
- Rechazos: CRM 8.595 (p. ej. 2026-01: 330; 2026-07: 265); reportes 0. **El CRM tiene más información que los reportes**; los rechazos no se pueden verificar contra el portal con estos archivos.
- Suscripciones: de las 822 del reporte, **822 existen en el CRM** (100% por Suscripción ID). Estado: Activa 312 active + 1 delete + 1 suspended; Suspendida 508 = 508 suspended. Cuota (`p_subscriptions.amount`) igual a la última cuota exitosa en 822/822. «Última Fecha Cobro» == última cuota exitosa del CRM en 678/822; en 144 el CRM es más reciente (reporte de 20-oct); en 0 el reporte es más reciente.
- El CRM tiene 5.700 suscripciones frente a 822 del reporte (el reporte omite register 3.414, delete 681, cancel 116 y ~1.048-508 suspendidas históricas). El reporte no sirve para validar esas.

## 4. Brecha por campo

| Campo (reporte) | Equivalente CRM | Estado |
|---|---|---|
| Transacción / Identificador voucher | `p_transactions.external_id` (16 car. 2025+; 22.064) | OK. 100% de `dataTransacciones` casa con `p_transactions` (10.146 de 10.146 cuotas); consolidado casa 17.690 ids únicos |
| Fecha de Transacción | `created_at_api` (texto con hora) -> `core_payments.occurred_at` | Existe, pero el ETL **trunca a fecha y asume UTC** (pierde la hora; riesgo de borde de mes menor) |
| Monto | `amount` (string) | OK (igual en 74 meses) |
| Comisión, Monto Final (neto) | ninguno | **Sin equivalente** (el API de transacciones por suscripción no las trae; sí `GET /api/transaction/{id}`) |
| Medio de pago / Proveedor / Tipo de pago (Débito, Crédito, Prepago, Webpay, Fintoc, MACH...) | ninguno en columnas (parcial en `raw_payload.cards.card_type`) | Sin equivalente |
| Liquidación, Fecha depósito, Estatus liquidación, Monedero | ninguno (`liquidacion.md` es de otro canal) | Sin equivalente |
| Concepto («Cobro: # n») | `raw_payload.description` | Existe en raw; el número de cuota no está normalizado |
| 4 últimos dígitos | `raw_payload.cards.last_4_digits` (sub) | Existe en raw por suscripción |
| Orden | `raw_payload.order` | Existe en raw (7 car.; casa 10.146/10.146) |
| Email / Nombre / Teléfono | `p_clients` | OK (contacto) |
| Estatus (Activa/Suspendida) | `p_subscriptions.status` (active/suspended/delete/cancel/register) | OK; **sin normalizar** a taxonomía común |
| Tipo de Monto (Fijo/Variable), Frecuencia (Mensual/Anual), Nombre Plan | `p_plans`/raw `plan` (nombre sí; tipo y frecuencia no verificados) | Parcial; GAP-PK-02 (`plan_type` NULL) |
| Próxima Fecha Cobro | ninguno | **Sin equivalente** (solo 295 filas; sirve para REC-05) |
| Última Fecha Cobro | derivable de `p_transactions` | OK por derivación |
| Monto (suscripciones) | cuota != acumulado del reporte | Semántica distinta: no mezclar |
| **Glosa de rechazo** | `core_payments.rejection_*` = vacío (0 de 8.560 rechazos). `last_status_current_payment` solo da un código grueso (maximum attempt limit 1.247, first payment rejected 217, retry 15, canceled by paymaster 58, canceled by customer 7) | **Sin equivalente en ningún reporte. En el API solo vía detalle `GET /api/transaction/{id}` -> `gateway_response.message` (~7 textos); el sync no lo llama** |
| **Fecha de suscripción** | `start_date` 5.700/5.700 | OK |
| **Fecha de cancelación** | `end_date`: suspended 1.048/1.048, delete 146/681 (21%), cancel 11/116 (9%), active 47/440, register 218/3.414. El log `raw_payload.logs.status[]` (claves `change_date`, `initial_status`, `final_status`) da fecha para cancel 116/116, delete 265/681, suspended 579/1.048; unión (log o end) = delete 382/681 (56%) | **Brecha real**: `core_payku_etl` solo usa `end_date` y no lee los logs; 299 delete (44%) no tienen fecha en ninguna fuente. Además docs/data/payku.md dice que se usa `logs.status`, pero la clave real es `final_status` |
| Montos de suscripción | `amount` NULL en 3.417 (3.414 son register) | Brecha para `register`: sin cuota, aunque el plan podría darla |

## 5. Causas de las brechas

1. Los reportes son solo de cobros exitosos: no hay rechazos ni glosa; la glosa no existe en ningún archivo y el payload embebido de suscripciones no la incluye.
2. El sync usa solo transacciones embebidas en `/api/sususcription` (v1); no consume `/api/transaction` (donaciones puntuales, comisión, medio de pago) ni `/api/transaction/{id}` (message), ni `/api/sususcriptionv3` (ciclos `paid[]`).
3. El ETL de core (`core_payku_etl.py`) no está en la rutina diaria (`sync_all` solo consolida a legacy `payments`); solo corre por `POST /etl` manual. `core_payments` quedó en 21-oct (115 filas atrás) y los estados `delete`/`suspended` difieren en 1 fila.
4. Fecha de cancelación: el ETL ignora los logs de estados y usa solo `end_date`.
5. La carga diaria falló los últimos 4 intentos (27-28 oct): token vacío («Bearer ») y conflictos ON CONFLICT; 17 fallos en total.
6. Cobertura histórica (PK-05/PK-06): ver sección 6.

## 6. PK-05 / PK-06 y el importador de reportes (TK-18 para Payku)

- **Resultado de la prueba de cobertura con reportes**: la cobertura histórica de **cuotas exitosas es completa y exacta** (2020-08 a 2026-09: 74 meses coinciden en cantidad y monto). Con esto PK-05 se puede **certificar para éxitos** sin esperar a soporte (Q-08/Q-11 solo siguen bloqueando la forma de reconstruir por API el histórico futuro/rechazos). Lo que no se puede certificar con reportes: rechazos (8.595), pendientes (356) y suscripciones no activas.
- Los rechazos históricos están en el CRM sin glosa; la única fuente potencial es `GET /api/transaction/{id}` (lectura; 8.595 llamadas, requiere throttle y confirmar que el detalle de un rechazo trae `message`). Q-27, sandbox e incidentes de credenciales (`Bearer` vacío) bloquean la validación en vivo.
- PK-06 (modelo de cargos `p_cycles` + `p_transactions` ampliada) sigue válido: hoy no hay `core_charges` de Payku, y la normalización de estado y la glosa deben vivir ahí.
- **¿Importador de reportes tipo Toku (TK-18) para Payku?** Valor bajo-medio y no es lo primero. Razones: (a) las cuotas exitosas ya coinciden 100%; (b) los reportes no traen rechazos ni glosa, que es la brecha principal; (c) aportan comisión/neto, medio de pago, liquidación y donaciones puntuales, útiles para conciliación financiera, no para el recuperador; (d) contienen PII (email, nombre, teléfono), hay que respetar la regla 11 (hash/solo conteos). Recomendación: **importador mínimo y opcional** (parser por firma de columnas + upsert por voucher, hacia una tabla `p_report_*` separada, idempotente, con guarda de fecha) solo si el negocio quiere conciliar comisiones/liquidaciones o ingestar donaciones puntuales. Alternativa recomendada primero: ampliar el sync al detalle de transacción.

## 7. Tareas priorizadas (propuestas)

| ID | Descripción | Archivos | Esfuerzo | Riesgo |
|---|---|---|---|---|
| PK-PAR-01 | Arreglar la sincronización diaria: token vacío («Bearer »), `ON CONFLICT DO UPDATE ... CardinalityViolation` (duplicados dentro del mismo lote), y alertar tras N fallos | `app/integrations/payku/auth.py`, `client.py`, `app/services/channel_store.py`, `payku_sync.py` | M | Medio (afecta producción; sin sandbox) |
| PK-PAR-02 | Incluir `run_payku_core_etl` en `sync_all` tras consolidar (o job propio), con SAVEPOINT y marca de frescura | `app/scheduler/jobs/sync_all.py`, `app/services/core_payku_etl.py` | S | Medio |
| PK-PAR-03 | Fecha de cancelación: usar `logs.status[].final_status/change_date` (el más reciente al estado actual) con fallback a `end_date`; corregir docs; test con fixtures | `core_payku_etl.py` (y `channel_consolidation.py`), `docs/data/payku.md`, tests | S | Bajo |
| PK-PAR-04 | Persistir la hora de la transacción y la zona (Chile) en `occurred_at` en vez de truncar a UTC | `core_payku_etl.py` (`_parse_date`) | S | Bajo-medio (cambia agrupaciones por mes) |
| PK-PAR-05 | Glosa de rechazo: enriquecer rechazos con `GET /api/transaction/{id}` (`gateway_response.message`) en lote con throttle, guardar en `raw_payload` y mapear a `rejection_reason`/`rejection_code`; empezar con 20 casos y confirmar que el rechazo trae el mensaje | `payku_sync.py`, `client.py`, `core_payku_etl.py` | M-L | Alto (8.595 lecturas, rate limit, sin sandbox; solo GET) |
| PK-PAR-06 | Derivar `rejection_reason` mínimo desde `last_status_current_payment` (maximum attempt limit, first payment rejected...) a nivel suscripción como respaldo mientras no exista PAR-05 | `core_payku_etl.py`, `core_subscriptions` | S | Bajo |
| PK-PAR-07 | Normalizar estados Payku a la taxonomía común (`active`/`suspended`/`cancelled`/`pending_enrollment`) y completar `amount` de `register` desde el plan | `core_payku_etl.py`, ADR/taxonomía | M | Medio |
| PK-PAR-08 | Certificar PK-05 con evidencia: script de conciliación mensual reporte vs `p_transactions` (conteo y monto) y registro en docs; marcar PK-05 «éxitos certificados 2020-08..2026-09; rechazos sin certificar» | `scripts/maintenance/` (nuevo, solo lectura), `docs/integrations/payku/`, `docs/tasks.md` | S | Bajo |
| PK-PAR-09 | Decisión de negocio (DEC): ingestar donaciones puntuales (10.186 filas, $486 M) desde `GET /api/transaction` por ventanas de 30 días o por reporte | `payku_sync.py`, modelos `p_*` | L | Medio-alto (cambia KPIs y MRR si se mezclan con cuotas) |
| PK-PAR-10 | Importador opcional de reportes Payku (consolidado y dataTransacciones) hacia tabla separada; comisión/neto, medio de pago, liquidación; sin PII en logs; fixtures sintéticas | `app/services/payku_report_parser.py`, `payku_report_import.py`, modelos y migración nuevos, tests | L | Medio (PII, migración; opcional) |
| PK-PAR-11 | Campos sin equivalente (comisión, neto, medio de pago, próxima fecha de cobro, número de cuota) en columnas de `p_transactions`/`p_subscriptions` si el negocio los quiere | modelos + migración | M | Medio |

Orden sugerido: PK-PAR-01, 02, 03, 08 (barato, alto valor) -> 06/07/04 -> 05 (prueba pequeña primero) -> decisión sobre 09/10/11.

## 8. Reglas respetadas
Sin cambios de código, sin commits, sin Alembic, sin llamadas al proveedor. `.env` no impreso. Solo SELECT agregados sobre `crm` (`current_database() = crm`, es producción local) y lectura de reportes con `-I`.
