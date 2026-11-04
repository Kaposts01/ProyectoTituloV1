# Paridad Toku: reportes (fuente de verdad) vs CRM (base `crm`, medido 2026-10-29, solo agregados)

## 1. Inventario de reportes
Carpeta `CRM_reportes\Toku` (generados 2026-10-20, encabezado en fila 7 salvo indicación) y `Reportes Toku` (2026-08-09, subconjunto antiguo; el nuevo lo contiene).

| Reporte | Filas | Rango de fechas | Soporta el parser |
|---|---|---|---|
| Productos (=suscripciones) | 658 (157 con Fecha de Eliminación; 501 vivos; 460 clientes con producto vivo) | creación 2024-08-13 a 2026-10-19; eliminación 2024-08-20 a 2026-08-31 | Sí (`productos`) |
| Métodos de pago | 588 (291 chargeable, 136 temporary_failed, 122 permanent_failed, 39 deleted) | 2024-10-09 a 2026-10-20 | Sí (`medios_pago`) |
| Intentos de pago | 31.359 (FALLIDO 28.970, AUTORIZADO 2.379, EN PROCESO 10; 66 eliminados) + hoja Códigos de Error (24 filas: TE 13, PE 9, SU 1, UE 1) | 2024-10-10 a 2026-10-20 | Sí (`intentos` + catálogo) |
| Inscripciones de medio de pago | 720 (SUCCESS 632, FAILED 86, inscription_failed 2) | 2024-10-09 a 2026-10-20 | Sí (`inscripciones`) |
| Deudas | solo en `Reportes Toku` de 2026-08-09 (antiguo; USR-09 pendiente) | hasta ago-2026 | Sí (`deudas`) |
| Clientes | 653 (122 eliminados) | 2024-08-13 a 2026-10-18 | No (UnsupportedReport) |
| Pagos (v1, 2.379) y Pagos v2 (2.380 + hoja Pagos) | 2.379 / 2.380 | 2024-10-10 a 2026-10-20 | No |
| Liquidaciones 2.0 | 2.368 filas deudas/transacciones, 433 de resumen | depósitos 2024-10-17 a 2026-10-20 | No |
| Facturación Toku (comisiones) | 159 comisiones, 8 cobros | solo ago-2026 | No |
| Contracargos (5 filas), Validaciones de destinatario (651), Mensajes, Eventos de mensajes, Eventos portal de pagos (1.253) | — | — | No |

Además `Historico Toku - *.csv` (sync Apps Script del 2026-10-26): Clientes 540, Suscripciones 510, Deudas 6.426 (UNPAID 4.011, PAID 2.412, VOID 1), Métodos de pago 553, Transacciones 31.534, RESUMEN 569 (trae `Estado` ACTIVE/PAUSED/Eliminada y `Estado Secundario` Cobrable/Incobrable calculado). Es derivado de la API; sirve de contraste, no es fuente de verdad.
Los `customers-*.csv` y `payments_monthly-*.csv` de Downloads (6.077 y 3.267 filas, separador `;`) son de **VirtualPOS**, no de Toku (fuera de este canal); hay copias idénticas `(1)`.

## 2. Mapeo columna del reporte -> CRM y estado
| Columna del reporte | Destino previsto | Estado hoy |
|---|---|---|
| Productos: ID / Cliente / Monto / due_day / is_recurring | `tk_report_products.*` | Tabla creada, **0 filas** |
| Productos: ID Producto (RUT) | `product_key_hash` (HMAC) | Requiere `TOKU_REPORT_HASH_PEPPER`; sin él el importador no carga |
| Productos: Fecha de Creación (inicio real) | `created_at_source` -> debería ir a `core_subscriptions.started_at` / `subscriptions.suscription_date` | `suscription_date` se llena con `recurring.anchor` (próximo cobro; min 2026-08-01 vs inicio real 2024-08-13); `core.started_at` NULL en las 613 de Toku |
| Productos: Fecha de Eliminación | `deleted_at_source` -> `ended_at` / `canceled_at` | `canceled_at` 0/518; `core.ended_at` 0; el ETL crea 112 stubs `deleted_at_source` sin fecha (reporte: 157 eliminados) |
| Productos: Estado (= estado del medio de pago) | `payment_method_status` -> señales | Sin cargar; la API solo da `ACTIVE/PAUSED` (511) y 7 NULL |
| Medios de pago: Estado, Tipo/Marca tarjeta, Banco emisor, Procesador | `tk_report_payment_methods` | 0 filas; `payment_methods` (API) solo `status` + raw (403 vs 588: faltan eliminados) |
| Medios: last_payment_intent_response_code/message | `last_response_*` | Vacío en 100% del reporte (derivar del último intento) |
| Intentos: Código de Respuesta Toku, Estado, Fecha Transacción, Monto, Procesador, ID Mandato | `tk_report_attempts` (+ severidad por catálogo) | 0 filas. En API: `transaction.response_code` (formato largo TEPSP1008) está en raw pero **no se proyecta** a `payments`/`core_payments.rejection_*` (NULL en todas) |
| Intentos: Comisión cliente, Monto Neto, Cuenta de cobro, ID Externo Deuda | sin tabla | No se importan |
| Deudas: monto, pagado, anulado, vencimiento, estado | `tk_report_debts` | 0 filas; la API (`tk_invoices`) ya cubre estos campos casi 1:1 |
| Inscripciones: Estado transacción, Código (SU/TE/PE/UE+PSP+4 díg.), Estado último intento, id_subscription | `tk_report_inscriptions` | 0 filas; la API no tiene inscripciones |
| Clientes: Fecha de Eliminación, Silenciado hasta | sin tabla | No soportado; `clients.status` NULL en 547/547 |
| Pagos v2: Tipo de Pago, N.º cuotas; Liquidaciones: depósito, comisión, neto, liquidado; Facturación: comisión Toku | sin tabla | No soportado |
| Catálogo de códigos (24) | `tk_report_response_codes` | 0 filas -> sin glosas legibles |

## 3. Brecha cuantitativa (reporte vs base)
| Magnitud | Reporte | CRM | Brecha |
|---|---|---|---|
| Clientes | 653 (531 vivos); 590 distintos en productos | 547 en `tk_customers`, canónico y core; `status` NULL | Cantidad similar, sin estado ni eliminado |
| Suscripciones | 658 (501 vivas) | 518 API (499 ACTIVE, 12 PAUSED, 7 NULL); core 630 (518 + 112 stubs); canónico 518 | ~140 eliminadas faltan en canónico; fechas inicio/cancelación vacías |
| Suscripciones activas efectivas (DEC-18) | 178 vivas con medio chargeable | dashboard deriva de `payment_methods` (227 chargeable, sin excluir eliminadas) | No comparable hasta cargar reportes |
| Medios de pago | 588 (+720 inscripciones) | 403 (chargeable 227, temp 94, perm 33, insc_failed 49) | 185 filas; faltan eliminados y detalle de inscripción |
| Intentos | 31.359 | 31.675 (`tk_transactions`/`payments`, hasta 2026-10-27) | Cantidad OK (+316 posteriores al 10-20) |
| Intentos con código de rechazo | 99,8% con código (57 vacíos) | FAILED sin código: **5.412 de 29.238** (todos nov-2024 a oct-2025); `payments` canónico sin columna de rechazo; core NULL | El reporte rellena ~5,4 mil códigos históricos |
| Éxitos | 2.379 AUTORIZADO / 2.380 pagos v2 | 2.432 SUCCESS (`tk_payments` 2.431) | OK |
| `core_payments` Toku | — | solo 2.377 (solo éxitos, `source_status` NULL) | Intentos fallidos no están en core |
| Deudas | 6.426 (hist. 10-26) | 6.503 `tk_invoices` y canónico; 6.363 `core_charges` | Core 140 menos: ETL desactualizado |
| Montos | por producto/intento/pago | strings en `tk_*`, Numeric en core | Sin diferencia de formato; no se verificó monto a monto (requeriría cruce por ID) |

## 4. Brecha por mes
- Intentos AUT/FALL (reporte, mes de Fecha Transacción) vs API (`created_at_api`, UTC): 2024-10 a 2026-07 coinciden salvo desfases de frontera de mes por huso (p. ej. 2025-06 FALL 738 vs 714 y 2025-07 718 vs 740; la suma se compensa). AUT idéntico en todos los meses hasta 2026-07. Recientes: ago-26 AUT 158 vs 130; sep-26 173 vs 201; oct-26 131 vs 184 y FALL 808 vs 1.136 (la API llega al 10-27 y el reporte al 10-20; no es error).
- «EN PROCESO»: reporte 10 (abr-26 2, may-26 7, oct-26 1); la API no lo distingue (aparece como FAILED: abr 1.521 vs 1.523, may 1.613 vs 1.631).
- Deudas por mes de vencimiento: PAID/UNPAID idénticos entre histórico, `tk_invoices` y core hasta 2026-04; jun a sep-26 `tk_invoices` tiene 1 a 4 UNPAID más (creadas tras el 10-26); **oct-26: PAID histórico 146, tk 165, core 111**; nov-26: tk 67 UNPAID futuros, core 0.
- Pagos por mes: `tk_payments` = `core_payments` hasta sep-26; ago-26 pagos v2 158 vs 129; sep-26 173 vs 201; oct-26 tk 184 vs core 130.
- Altas por mes (Productos): picos nov/dic-24 (119/104), ene-25 (102), ago-26 (185), sep-26 (63). En el CRM el `anchor` mínimo es 2026-08-01, así que la «fecha de suscripción» refleja un reinicio de ancla, no el alta real. Eliminaciones: pico ene-25 (42) y feb-25 (23); el CRM no tiene ninguna fecha de cancelación.

## 5. Causas
1. Importador (TK-17/18) hecho pero **nunca ejecutado**: las 7 tablas `tk_report_*` y `core_subscription_signals` tienen 0 filas. Falta pepper (`TOKU_REPORT_HASH_PEPPER`), ruta/panel de subida (TK-19; no existe ninguna ruta que invoque `toku_report_import`) y Deudas nuevo (USR-09).
2. Sin ETL de señales (TK-20): nada del reporte llega a `core_*`. Además el dashboard (`staging._toku_centralized_dashboard`) lee las tablas canónicas (`subscriptions/charges/payments/payment_methods`), no `core_*`; hay que decidir en qué capa se refleja el dato del reporte.
3. Mapeos faltantes/erróneos del ETL de API: `suscription_date` = `recurring.anchor`; `canceled_at`/`ended_at`/`started_at` nunca se llenan; la API no lista suscripciones eliminadas; `payments` canónico no tiene columnas de rechazo y `core_payments.rejection_*`/`source_status` son NULL aunque `transaction.response_code` existe en raw (25.096 de 31.675; los rechazos anteriores a oct-2025 llegan vacíos desde la API).
4. `core_*` desactualizado frente a la API (último pago en core 2026-10-19 vs 2026-10-27), aunque la última corrida registrada fue 2026-10-28.
5. Tipos de reporte sin parser (Clientes, Pagos, Liquidaciones, Facturación): comisiones, neto, depósitos, cuotas y estado de cliente no existen en el CRM.
6. Huso horario: reporte en hora Chile, API en UTC; produce corrimientos de 1 a 3% en bordes de mes.

## 6. Tareas priorizadas
| ID | Descripción | Archivos | Esfuerzo | Riesgo |
|---|---|---|---|---|
| TK-PAR-01 | (usuario) Definir pepper en `.env`, aplicar 0039-0041 en `crm` (USR-10) y exportar Deudas nuevo (USR-09); primero probar carga en sandbox | `.env` (solo el usuario), docs | S | Bajo/medio |
| TK-PAR-02 | TK-19: POST de subida, panel de administración, aviso si el dato supera 7 días | `app/api/v1/routes/` (nuevo `toku_reports.py`), `frontend/src/features/admin/` | M | Medio (datos personales en tránsito) |
| TK-PAR-03 | Rechazos desde API: proyectar `transaction.response_code`/`original_response_message` a `payments` canónico (columnas nuevas) y a `core_payments.rejection_*`, `source_status` y `core_charges.latest_rejection_*`; incluir intentos fallidos en core | `core_toku_etl.py`, `models/core.py` + migración (la aplica el usuario), `channel_consolidation.py` | M | Medio |
| TK-PAR-04 | TK-20: ETL de señales (activa efectiva, racha por cuotas, bloqueada, vencida) desde `tk_report_*`; backfill de los 5.412 códigos históricos vacíos desde el reporte de Intentos (match por deuda + fecha) | `core_toku_etl.py`, nuevo `toku_signals_etl.py` | L | Alto (define «activa») |
| TK-PAR-05 | Fechas reales: `started_at` = Fecha de Creación del producto; `ended_at`/`canceled_at` = Fecha de Eliminación; corregir `suscription_date`; crear las ~140 eliminadas en canónico | `core_toku_etl.py`, `channel_consolidation.py` | M | Medio (cambia MRR/ARPU) |
| TK-PAR-06 | Estado de suscripción y de medio de pago en core/canónico: lifecycle (activa/pausada/eliminada) + `payment_method_status`; precedencia reporte > API (DEC-23) | `core_toku_etl.py`, `staging.py` | M | Medio |
| TK-PAR-07 | Parser de Clientes (eliminado, silenciado) y carga de medios eliminados/atributos e inscripciones al canónico | `toku_report_parser.py`, `toku_report_import.py`, modelos + migración | M | Bajo |
| TK-PAR-08 | Encadenar el ETL core tras cada sync de Toku y alerta si core queda atrás (hoy faltan ~54 pagos de oct-26) | scheduler, `run_toku_core_etl`, `scripts/sync_toku.py` | S | Bajo |
| TK-PAR-09 | Nuevos tipos: Pagos v2 (tipo de pago, cuotas) y Liquidaciones/Facturación (comisión, neto, depósito) | parser, import, migración | L | Medio |
| TK-PAR-10 | Script de paridad de solo lectura (conteos por mes y estado, reporte vs base, bucket America/Santiago) como prueba/diagnóstico | `scripts/diagnostics/` | S | Bajo |
| TK-PAR-11 | Evaluar descarga automática vía `POST /reports/{entity}` (hoy bloqueado por guardas; solo GET columns verificado) para tener reportes a diario | `app/integrations/toku/client.py`, `write_guard.py` | L | Alto |
| TK-PAR-12 | TK-21 (fixtures sintéticas + guarda PII), TK-22 (contrato de columnas en `docs/data/toku.md`) y TK-13 (KPIs) | `tests/`, `docs/data/toku.md` | M | Bajo |

Orden sugerido: 08 y 03 (no dependen de reportes) -> 01 y 02 -> 05, 06, 04 -> 07, 10 -> 09, 11, 12.
