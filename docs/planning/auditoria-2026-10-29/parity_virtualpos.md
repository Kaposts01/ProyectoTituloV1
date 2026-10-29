# Paridad CRM vs reportes del portal: canal VirtualPOS (auditoría de solo lectura, 2026-10-29)

Base medida: `crm` (datos reales locales). Sin datos personales en este informe. Scripts de medición en el scratchpad (`prof1.py`, `prof2.py`, `cmp1.py` a `cmp6.py`, `db1.py`, `db2.py`, `dbq.py`).

## 1. Resumen ejecutivo

1. **La cantidad ya es paritaria.** Para la ventana de los reportes (cobros programados 2025-02-24 a 2026-10-26) los 86.541 cobros únicos del portal están TODOS en `vp_charges` (0 faltantes, 0 sobrantes, mes por mes idéntico), con mismo estado, misma fecha programada, mismo monto y misma suscripción. Suscripciones: 9.005 del reporte, todas en `vp_subscriptions` (9.014); las 9 de más son del 26/10 en adelante (posteriores al reporte).
2. **La brecha es de calidad/campos, no de cantidad.** Lo que el portal tiene y el CRM no: glosa y código de rechazo (0% poblado en 23.8k cobros rechazados), medio de pago por cobro (Débito/Crédito/Prepago), motivo de rechazo de la suscripción, tarjeta de 1.784 suscripciones, vínculo pago-cobro, y el vínculo cliente en cobros/suscripciones.
3. **Hay datos que SÍ están en el CRM pero escondidos en `raw_payload` y no en columnas**: fecha de autorización, comisión, abono, fecha de abono, alias POS, código de vendedor, origen, marca/tipo/últimos 4 de tarjeta. Coinciden con el reporte (>99,9%). Cierre barato: promoverlos a columnas.
4. **Riesgo operativo para la sincronización diaria:** las corridas de `virtualpos2` fallan desde el 2026-10-27 con «VirtualPOS virtualpos2 is not configured» (últimas 4 corridas; última exitosa 2026-10-26 17:35 UTC). VP2 es el 76% de los datos. `virtualpos1` sigue bien (última 2026-10-28 05:00 UTC). Hipótesis: el proceso que dispara el scheduler corre con `APP_ENV=sandbox` o sin las variables de la cuenta 2 (en sandbox la cuenta 2 queda vacía por diseño). No se inspeccionó el `.env`; la causa debe verificarla el usuario.
5. **Datos futuros inflan el CRM:** `vp_charges` tiene 151.204 cobros `cancelado` con fecha 2026-10-27 a 2031-09-24 (el `charge_program` de la API trae la programación futura de las suscripciones). El portal no los exporta. Esto distorsiona el conteo de `cancelado` (CRM 165.076 vs 13.872 del reporte en la ventana) si no se filtra por fecha.

## 2. Inventario de reportes fuente

| Tipo | Archivos / filas | Columnas | Clave única | Rango |
|---|---|---|---|---|
| `TransaccionesPAT-VirtualPOS-*.csv` (cobros, oficial del portal) | 42 archivos únicos (CRM_reportes/VirtualPOS + Downloads); 93.295 filas, 86.541 `Id cargo` únicos (el resto son solapes entre archivos) | 33: Id suscripción, nombre/apellido/email/RUT, Plan suscrito, Estado de suscripción, Total cargos programados, Número de cargo, Monto, Moneda, Costo de despacho, Fecha programada, Estado del cargo, Id plan, **Id cargo**, Id cargo comercio, Total comisión, Total abono, Fecha de abono, Código y Glosa de autorización/error/rechazo, **UUID transacción**, Final número tarjeta, Medio de pago, Fecha de autorización, Fecha de suscripción, Origen de la suscripción, Alias POS, ID suscripción interno, Código de vendedor, Origen del cargo, Cód. de nómina | `Id cargo` (`cid_...`); `UUID transacción` (16 chars, 1 a 1 con cobro; 72.816 únicos) | programada 2025-02-24 a 2026-10-26 |
| `SuscriptoresPAT-VirtualPOS-*.csv` (suscripciones, oficial) | 37 archivos; 9.227 filas, 9.005 `Id de suscripción` únicos | 40: Id de suscripción, Fecha de suscripción, datos del cliente (nombre, email, RUT, teléfono, nacimiento, género), Plan suscrito, Id de plan, Estado, Total cargos programados, **Fecha de cancelación**, contadores de cargos (autorizados, rechazados, pendientes, en proceso, cancelados), Fecha/Número/Monto/Estado próximo cargo, Moneda, Canal/Origen, Num serie POS, Alias POS, Código de vendedor, Tipo tarjeta, Últimos 4 dígitos, Marca, Dirección/Comuna/Región de despacho, **Motivo de rechazo**, ID suscripción interno | `Id de suscripción` (13 caracteres, trae un tabulador final) | suscripción 2025-02 a 2026-10 |
| `1. [Nuevo] VirtualPOS - Cobros.csv` (derivado del Sheet/Apps Script, NO oficial) | 64.330 filas / 64.330 únicos; 64.314 en CRM, 16 no | 23: id_cobro, id_suscripcion, rut, nombre, plan, estado_cobro, codigo_respuesta, glosa_respuesta, numero_cargo, medio_pago, montos, fechas, alias_pos, **plataforma**, match_suscripcion | `id_cobro` | hasta oct-2026 |
| `1. [Nuevo] VirtualPOS - Subscripciones.csv` (derivado) | 9.154 filas / 9.089 únicas; 9.000 en CRM, 89 no; 14 del CRM no están | 30: plataforma, id, estado, estado_secundario (Cobrable/Incobrable/Inactiva…), fecha_cancelacion, fecha_ultimo_pagado, racha_rechazos, banco_emisor, tipo_tarjeta, vencimiento_tarjeta, contadores, Metadata | `id` | |
| `CRM_reportes/VirtualPOS/para_sheets/*` y `Reportes VirtualPOS/*` | Cobros(_v3)_para_carga (169.550 filas), Subscripciones(_v2/_v3)_para_carga (27.000), ids_recientes, correcciones_plataforma, Trans_mes_A/B, Cargos/Sub_VirtualPOS1/2 | variantes de las anteriores, preparadas para el Sheet | | no son fuente primaria |

Notas: los PAT NO traen plataforma (virtualpos1/2); solo los derivados del Sheet la traen. El CRM la obtiene del origen de la sincronización. Los derivados del Sheet tienen 100 cobros `procesando` que hoy en el CRM están `rechazado` (foto anterior al cierre) y 2 cobros con plataforma distinta a la del CRM (a revisar, VP-PAR-12).

## 3. Mapeo columna del reporte a campo del CRM

Leyenda: COL = columna propia; RAW = solo en `raw_payload` (JSONB); NO = no existe en el CRM.

### 3.1 Cobros (TransaccionesPAT)

| Columna del reporte | Campo CRM | Estado / % poblado en CRM |
|---|---|---|
| Id cargo | `vp_charges.external_id` (`cid_...`), `core_charges.external_id` | COL, 100%; paridad exacta |
| Id suscripción | `vp_charges.subscription_external_id` | COL, 100%, igual al reporte en los 86.541 |
| Estado del cargo | `vp_charges.status` | COL; pagado/rechazado/cancelado/procesando idénticos |
| Fecha programada de cargo | `vp_charges.charge_date` (texto ISO) / `core_charges.due_at` | COL; 0 diferencias |
| Monto de cargo | `vp_charges.amount` (String, GAP-VP-01) | COL; 0 diferencias |
| Moneda | `vp_charges.currency` | COL |
| Número de cargo (N de M) | NO | no existe (ni `num_charges` por cobro) |
| UUID transacción | `vp_payments.external_id` (= `order.uuid`) | COL en payments, pero **sin vínculo al cobro** (ver abajo) |
| Código de autorización/error/rechazo | `core_payments.rejection_code`, `core_charges.latest_rejection_code` | **COL existe, 0% poblado** (0 de 23.755 rechazados) |
| Glosa de autorización/error/rechazo | `core_payments.rejection_reason`, `core_charges.latest_rejection_reason` | **COL existe, 0% poblado** |
| Medio de pago (Débito/Crédito/Prepago) por cobro | NO (`order.payment_method` vale `PAT`/`WEBPAY`…, no Débito/Crédito) | NO EXISTE. Aproximable con `payment_method.card_type` de la suscripción (TD/TC/TP) pero discrepa en unas 2.400 de 48.900 pagados y es nulo para 7.800 |
| Fecha de autorización | `vp_payments.raw_payload.order.authorized_at` | RAW; coincide 48.906/48.906 |
| Total comisión | `...order.deposits[0].processing_fee` | RAW; coincide 48.873/48.906 (99,93%) |
| Total abono | `...deposits[0].payout_amount` | RAW; coincide 48.860/48.906 |
| Fecha de abono | `...deposits[0].payout_date` | RAW; coincide 48.873/48.906 |
| Final número tarjeta | `vp_subscriptions.raw_payload.payment_method.last4CardDigit` (de la suscripción, no del cobro) | RAW parcial |
| Id cargo comercio / Origen del cargo (API) | `...order.merchant_internal_code` / `merchant_internal_channel` | RAW; 98% vacío en el reporte también |
| Alias POS, Código de vendedor, Origen de la suscripción | `vp_subscriptions.raw_payload.terminal_pos / seller_id / origin` | RAW; coincide 8.844/8.844 alias y 2.615/2.615 vendedor |
| Costo de despacho, Cód. de nómina | NO | 100% vacíos en el reporte; sin valor |
| Total de cargos programados / Id plan / Plan suscrito | `vp_plans.raw_payload.num_charges`, `vp_subscriptions.plan_external_id` | RAW/COL |
| Nombre, apellido, email, RUT | `vp_clients.*` y `vp_subscriptions.client_social_id` | COL (`client_external_id` de cobros y suscripciones 100% NULL, ver 6) |

### 3.2 Suscripciones (SuscriptoresPAT)

| Columna del reporte | Campo CRM | Estado |
|---|---|---|
| Id de suscripción | `vp_subscriptions.external_id` | COL; 9.005/9.005 presentes |
| Estado de suscripción | `vp_subscriptions.status` | COL; 8.995 de 9.005 coinciden; 10 difieren por cambio posterior al corte (9 ACTIVA que luego se cancelaron y 1 SUSCRIBIENDO que pasó a FALLIDA) |
| Fecha de suscripción | `vp_subscriptions.suscription_date` / `core_subscriptions.started_at` | COL; 0 diferencias en 9.005 |
| **Fecha de cancelación** | `vp_subscriptions.canceled_at` / `core_subscriptions.ended_at` | COL; 2.049/2.049 CANCELADA con fecha (100%); solo 9 difieren (canceladas después del corte del reporte) |
| Plan suscrito / Id de plan | `plan_external_id`, `vp_plans.name` | COL |
| Monto / Moneda | `amount`, `currency` | COL (monto vigente: `vp_current_amount.py`) |
| Total de cargos autorizados / rechazados / pendientes / en proceso / cancelados | NO como columnas (derivables de `vp_charges`) | NO persistidos; el reporte de suscriptores mide "cancelados" distinto (164.461 vs 12.167 en detalle) |
| **Motivo de rechazo** (suscripción fallida: 818 valores) | NO | **NO EXISTE** |
| Tipo tarjeta, Marca, Últimos 4 | `raw_payload.payment_method.card_type/brand/last4CardDigit` | RAW; 6.346 de 9.014 (70,4%); el reporte tiene últimos 4 en 8.122 → **faltan 1.784 suscripciones (22%)**. Donde ambos existen, últimos 4 coincide 6.338/6.338 y tipo 6.280/6.338 |
| Alias POS, Num serie POS, Código de vendedor, Canal/Origen | `terminal_pos`, `seller_id`, `origin` (RAW) | RAW, coincide |
| Teléfono, nacimiento, género | `vp_clients.phone_number/birth_date/gender_id` | COL (nacimiento 73,7% vacío y género 74,2% vacío; el reporte también 71% vacío: es limitación del proveedor) |
| Dirección / Comuna / Región / Política / Costo despacho | `raw_payload.address` | RAW; en el reporte 99,96% vacío, sin valor |
| Fecha/N°/Monto/Estado próximo cargo | NO | 100% vacíos en el reporte |
| (Derivados del Sheet) fecha_ultimo_pagado, racha_rechazos, estado_secundario (Cobrable/Incobrable…) | NO | no oficiales; derivables de `vp_charges` |

## 4. Brecha de cantidad por mes (ventana de reportes)

Cobros por fecha programada. «Solo reporte» y «solo CRM» son 0 en todos los meses.

| Mes | Reporte | CRM | | Mes | Reporte | CRM |
|---|---|---|---|---|---|---|
| 2025-02 | 43 | 43 | | 2026-01 | 5.059 | 5.059 |
| 2025-03 | 500 | 500 | | 2026-02 | 4.979 | 4.979 |
| 2025-04 | 885 | 885 | | 2026-03 | 6.282 | 6.282 |
| 2025-05 | 1.136 | 1.136 | | 2026-04 | 5.777 | 5.777 |
| 2025-06 | 1.207 | 1.207 | | 2026-05 | 6.391 | 6.391 |
| 2025-07 | 1.632 | 1.632 | | 2026-06 | 6.662 | 6.662 |
| 2025-08 | 2.010 | 2.010 | | 2026-07 | 7.489 | 7.489 |
| 2025-09 | 2.191 | 2.191 | | 2026-08 | 7.508 | 7.508 |
| 2025-10 | 2.849 | 2.849 | | 2026-09 | 7.432 | 7.432 |
| 2025-11 | 3.528 | 3.528 | | 2026-10 (hasta 26) | 8.247 | 8.247 |
| 2025-12 | 4.734 | 4.734 | | **Total** | **86.541** | **86.541** |

Por estado (reporte = CRM en la intersección): pagado 48.906, rechazado 23.760, cancelado 13.872, procesando 3.
Cobros del CRM fuera de la ventana: 151.374 (151.204 `cancelado` futuros hasta 2031-09-24; 39 pagado y 131 rechazado del 27 y 28/10, posteriores al reporte).

Suscripciones por mes de alta: coinciden en los 20 meses 2025-02 a 2026-09 (p. ej. 2025-12: 1.119/1.119); 2026-10: reporte 81, CRM 90 (las 9 son posteriores al corte). Por estado (reporte vs CRM): ACTIVA 6.234 vs 6.081, CANCELADA 2.074 vs 2.049, FALLIDA 918 vs 884, SUSCRIBIENDO 1 vs 0 (los archivos del reporte repiten algunas suscripciones en varios cortes; tras deduplicar por id la confusión es: 6.073 ACTIVA=ACTIVA, 2.040 CANCELADA=CANCELADA, 882 FALLIDA=FALLIDA, 9 ACTIVA→CANCELADA, 1 SUSCRIBIENDO→FALLIDA).

Pagos: `vp_payments` 73.013 vs UUID únicos del reporte 72.816; los 72.816 están en el CRM (`external_id` = `order.uuid`); 197 pagos del CRM no están en el reporte (posteriores al corte). Estados de pago del CRM: pagado 48.918, rechazado 24.043, anulado 33, expirado 17, pendiente 2.

Otros hallazgos de cantidad: tabla canónica `charges` tiene 5 cobros virtualpos1 rechazados sin fila en `vp_charges` (huérfanos), y quedan filas del canal legado `virtualpos` (452 cobros, 35 pagos, 15 suscripciones; fechas 2026-06-23 a 2031) que no están en `vp_*`.

## 5. Campos del CRM con alto % de nulos (VirtualPOS)

| Campo | % nulo |
|---|---|
| `core_payments.rejection_code/reason/reported_at` (rechazados) | 100% (0 de 23.755) |
| `core_charges.latest_rejection_*` (rechazados) | 100% (0 de 23.891) |
| `core_payments.charge_id` | 100% (73.013) |
| `vp_payments.charge_external_id`, `vp_payments.client_external_id` | 100% |
| `vp_charges.client_external_id` | 100% |
| `vp_subscriptions.client_external_id` | 100% |
| `core_subscriptions.last_payment_status` | 100% |
| `vp_subscriptions.service_id` | 1,8% (161) |
| `core_subscriptions.client_id` | 2,8% (250) |
| `payment_method` de suscripción (tarjeta) | 29,6% (2.668: 884 fallidas, 209 canceladas, 1.575 activas) |
| `vp_clients.birth_date` / `gender_id` | 73,7% / 74,2% (igual que el portal) |
| `vp_payments.raw order.merchant_internal_channel` | 99,99% vacío |
Tipos: montos y fechas siguen como `String(50)` en `vp_*` y `charges/payments/subscriptions` (GAP-VP-01); en `core_*` ya son Numeric/DateTime.

## 6. Causas probables

1. **Glosa/código de rechazo vacíos.** El listado `GET /payments` no trae `rejected_object` (las claves de `raw_payload.order` no lo incluyen: se verificó). El código `_enrich_charges_with_rejections` en `core_vp_etl.py` lo busca allí y además exige el vínculo pago-cobro, que no existe. Solo `GET /payment/{uuid}/attempts` (o `GET /payment/{uuid}`) devuelve `rejected_object` y los intentos. El reporte del portal sí trae código y glosa (19 códigos distintos; los más frecuentes -11 «Excede límite de reintentos de rechazo» 11.155, -3 «Excede monto máximo» 7.619, -10 3.410, -6 716, -8 374, -7 310). 165 rechazos del reporte (12 códigos, p. ej. -2119, -2152, -2150, -2133, -2121) no están en `VP_REJECTION_LABELS`; el catálogo quedó incompleto (los códigos -2xxx son del adquirente).
2. **Sin vínculo pago-cobro.** `charge_program` de la API trae solo `id, status, charge_date, amount, currency, description`, sin UUID del pago; el reporte sí enlaza `Id cargo` a `UUID transacción` (1 a 1, sin reintentos con UUID distinto).
3. **Medio de pago por cobro, motivo de rechazo de suscripción, tarjetas faltantes:** el API de suscripciones solo expone la tarjeta vigente (`payment_method`); es nula en suscripciones fallidas/canceladas/sin tarjeta vigente. El reporte conserva los datos históricos.
4. **Datos orphan `pay:`** (memoria): no hay filas `pay:` en estas tablas (todos los cobros son `cid_`); la hipótesis conocida (VP API devuelve 0 cobros de suscripciones CANCELADAS) sigue vigente para el histórico de otros orígenes, pero **no se manifiesta aquí**: las 2.049 canceladas del CRM tienen sus cobros (los 13.872 cancelados + pagados/rechazados de la ventana coinciden con el portal). Conclusión: el sync actual (por `charge_program`) ya cubre lo que exporta el portal para esta ventana. Vigilar cobros previos a 2025-02 (fuera de los reportes; la API no los devuelve).
5. **Fallo de la cuenta 2:** VP2 no sincroniza desde 2026-10-27 (ver 1.4): la brecha de cantidad empezará a abrirse solo si no se corrige (~150 cobros nuevos por día).
6. **Cancelados futuros:** el sync guarda toda la programación futura del `charge_program`.

## 7. Lista priorizada de tareas (propuestas)

| ID | Descripción | Archivos a tocar | Esfuerzo | Riesgo |
|---|---|---|---|---|
| VP-PAR-01 | **Corregir el sync diario de virtualpos2** (falla «not configured» desde el 27/10): verificar con qué `APP_ENV`/variables corre el scheduler/tarea, restaurar y relanzar el sync; alerta si un canal falla 2 días seguidos | `app/scheduler/jobs/sync_all.py`, `app/integrations/virtualpos/client.py`, config del proceso (lo ejecuta/valida el usuario) | S | Medio (no tocar `.env` sin el usuario; no correr sync desde sandbox contra `crm`) |
| VP-PAR-02 | **Importador de reportes PAT de VirtualPOS** (como el importador de Toku TK-14..22): parsear `TransaccionesPAT`/`SuscriptoresPAT`, upsert idempotente por `Id cargo`/`UUID`/`Id de suscripción`, sin guardar PII extra; tabla de staging o columnas nuevas. Sirve de histórico y de backfill | nuevo `app/services/vp_report_import.py` + parser, `app/models/vp.py`, migración Alembic (la aplica el usuario), tests | L | Medio (PII en archivos: leer solo encabezados en pruebas) |
| VP-PAR-03 | **Persistir código y glosa de rechazo por cobro** (columnas `rejection_code`, `rejection_reason` en `vp_payments`/`vp_charges`; poblarlas desde el reporte VP-PAR-02) y reactivar `_enrich_charges_with_rejections` leyendo esas columnas; de ahí `core_payments.rejection_*` y `core_charges.latest_rejection_*` | `app/models/vp.py`, `app/services/core_vp_etl.py`, `app/services/vp_rejection_codes.py`, migración | M | Bajo |
| VP-PAR-04 | **Sync diario de motivos de rechazo desde la API**: para cobros nuevos `rechazado` llamar `GET /payment/{uuid}/attempts` (lectura) con tope por corrida y reintento incremental; guardar `code`/`message` y `response_description`. Medir antes con una muestra en sandbox (regla 10 del handoff: no asumir) | `app/services/virtualpos_sync.py`, `app/integrations/virtualpos/client.py` (`get_payment_attempts` ya existe), `core_vp_etl.py` | M | Medio (rate limits sin medir; ~23.8k pagos rechazados por backfill) |
| VP-PAR-05 | **Completar catálogo de códigos** con los 12 códigos -2xxx del adquirente y las glosas del reporte (usar la glosa del proveedor como respaldo; `format_rejection_reason` ya lo hace) | `app/services/vp_rejection_codes.py`, tests | S | Bajo |
| VP-PAR-06 | **Vínculo pago-cobro**: poblar `vp_payments.charge_external_id` y `core_payments.charge_id` usando el cruce UUID a `Id cargo` del reporte (backfill 72.816) y, hacia adelante, por `/payment/{uuid}` o por clave (suscripción + fecha) | `core_vp_etl.py`, `channel_consolidation.py`, script de backfill en `scripts/maintenance/` | M | Medio (asignación equivocada si se infiere por RUT; usar solo el cruce exacto del reporte) |
| VP-PAR-07 | **Promover a columnas los datos de `raw_payload`**: `authorized_at`, `processing_fee`, `payout_amount`, `payout_date`, `terminal_pos`, `seller_id`, `origin`, `card_type/brand/last4` (en `vp_payments`, `vp_subscriptions`, y `core_payments`/`core_subscriptions` donde aplique) | `app/models/vp.py`, `app/models/core.py`, `core_vp_etl.py`, migración | M | Bajo |
| VP-PAR-08 | **Medio de pago por cobro** (Débito/Crédito/Prepago) y últimos 4 históricos: solo vienen en el reporte; guardarlos desde VP-PAR-02 en `vp_payments.payment_method_label`, `card_last4` | `vp_report_import`, `app/models/vp.py` | S (tras 02) | Bajo (los últimos 4 son dato de tarjeta enmascarado; confirmar con política de seguridad que se permite) |
| VP-PAR-09 | **Motivo de rechazo de suscripción** y tarjetas faltantes (1.784 subs sin últimos 4): cargar desde `SuscriptoresPAT` | `vp_report_import`, `app/models/vp.py` (`rejection_reason`) | S (tras 02) | Bajo |
| VP-PAR-10 | **Separar cobros futuros del conteo**: marcar `vp_charges` con `is_future`/usar filtro `charge_date <= hoy` en KPIs y paneles; evitar que 151k «cancelado» futuros aparezcan como cancelados reales | `app/services/charge_stats.py`, consultas de KPI, front | S | Bajo |
| VP-PAR-11 | **Script de paridad permanente** (solo lectura): compara reportes PAT con la base por mes/estado y falla si hay diferencias en la ventana; correrlo tras cada sync diario y publicar el resultado | nuevo `scripts/diagnostics/vp_parity_check.py` (+ doc en `docs/data/virtualpos.md`) | M | Bajo |
| VP-PAR-12 | Limpiar huérfanos: 5 `charges` virtualpos1 sin `vp_charges`; filas del canal legado `virtualpos` (452/35/15); 2 cobros con plataforma distinta entre el Sheet y el CRM; `client_external_id` nulo en cobros/suscripciones | `channel_consolidation.py`, scripts de mantenimiento (con aprobación del usuario) | S | Medio (borrado: solo con instrucción explícita) |
| VP-PAR-13 | Tipar `amount` (Numeric) y fechas (timestamptz) en `vp_*` (GAP-VP-01) | `app/models/vp.py`, migración, consumidores | L | Alto (todas las consultas del front) |
| VP-PAR-14 | Documentar en `docs/data/virtualpos.md` el mapeo reporte a CRM de este informe y actualizar `docs/engineering/datos/11-conciliacion-canales.md` (cifras 2026-10-20 ya desactualizadas: hoy 0 diferencias) | docs | S | Bajo |

Orden sugerido: 01 → 02 → 03/05/07 → 06 → 04 → 08/09 → 10 → 11 → 12/14 → 13.

## 8. Limitaciones de esta medición

- La paridad por cantidad se mide contra los CSV descargados (corte del 26/10); todo cobro posterior no tiene fuente de verdad local.
- No se midió el histórico previo a 2025-02 (no hay reportes ni cobros en la API).
- No se llamó a la API del proveedor; la ausencia de `rejected_object` en el listado se midió en `raw_payload` y se contrastó con `docs/integrations/virtualpos`. La existencia efectiva de la glosa en `/attempts` hay que confirmarla en sandbox (VP-PAR-04).
- Al perfilar los CSV, algunas distribuciones de baja frecuencia de columnas de despacho mostraron texto libre; no se copió a este informe.
