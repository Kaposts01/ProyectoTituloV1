# KPIs del Sistema — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Indicadores clave de rendimiento del sistema, organizados por dominio.

---

## 1. KPIs de ingesta y sincronización

| KPI | Descripción | Fórmula | Meta |
|-----|-------------|---------|------|
| **Tasa de éxito de sync** | % de SyncRuns completados sin error | `completed / total_runs * 100` | ≥ 98% |
| **Latencia de sync** | Tiempo desde trigger hasta finalización | `SyncRun.ended_at - started_at` | ≤ 5 min por proveedor |
| **Registros sincronizados / día** | Volumen diario por proveedor | `COUNT(source_records) WHERE date = today` | Referencia histórica ± 20% |
| **Tasa de duplicados detectados** | `source_records` con conflict en upsert | `conflicts / total_upserts * 100` | < 5% (indica re-sincronizaciones) |
| **TCH: archivos cargados YTD** | Excel TCH procesados en el año | `COUNT(tch_recaudacion_mensual)` | 12 por año |

---

## 2. KPIs de Core Layer (ETL)

| KPI | Descripción | Fórmula | Meta |
|-----|-------------|---------|------|
| **Tasa de materialización** | % de registros de staging que llegan a Core | `core_entities / staging_entities * 100` | Referencia documentada por proveedor |
| **Latencia ETL** | Tiempo de ejecución de ETL por proveedor | `EtlRun.duration_seconds` | ≤ 10 min por proveedor |
| **Registros creados vs actualizados** | Nuevos vs updates en cada run | `EtlRun.created / EtlRun.updated` | Referencia estable |
| **Clientes sin match cross-canal** | `core_clients` sin vinculación entre canales | `COUNT(core_clients) WHERE no match_candidate` | Tendencia decreciente |
| **Candidatos de match pendientes** | `client_match_candidates` sin revisar | `COUNT WHERE status='pending'` | < 500 pendientes |

---

## 3. KPIs de calidad de datos por canal

### VirtualPOS

| KPI | Valor actual (verificado) | Meta |
|-----|--------------------------|------|
| Pagos descartados (no 'pagado') | 22,783 / 71,011 = **32%** | Documentar; reducir con VP-2 fix |
| Suscripciones sin client_external_id | 8,999 / 8,999 = **100%** | Limitación API (VP-1) |
| Pagos sin charge_id | 71,011 / 71,011 = **100%** | Limitación API (VP-3) |

### Toku

| KPI | Valor actual (verificado) | Meta |
|-----|--------------------------|------|
| Invoices UNPAID invisibles en Core | 3,984 / 6,363 = **63%** | Resolver TK-2 |
| Suscripciones stub (deleted_at_source) | 112 | Monitorear crecimiento |
| Pagos con source_status=NULL | 2,377 / 2,377 = **100%** | Esperado (TK-3 correcto) |

### Payku

| KPI | Valor actual (verificado) | Meta |
|-----|--------------------------|------|
| Rechazos con amount=0 | 6,445 / 8,560 = **75%** | Documentado (PK-1) |
| Suscripciones en 'maximum attempt limit' | 1,246 / 5,700 = **22%** | Alertar si supera 25% |

### TCH

| KPI | Valor actual | Meta |
|-----|-------------|------|
| Transacciones históricas cargadas | 1,472,231 | Completo (29 archivos) |
| Tasa de aceptación mensual (Sept 2026) | 5,644 / (5,644+2,094) = **73%** | Referencia histórica ± 5% |
| Motivo de rechazo más frecuente | Cuenta Errónea (331) | Monitoreo mensual |

---

## 4. KPIs de disponibilidad del sistema

| KPI | Descripción | Meta |
|-----|-------------|------|
| **Uptime API** | % tiempo FastAPI respondiendo en ≤ 2s | ≥ 99% en horario laboral |
| **Uptime PostgreSQL** | % tiempo BD disponible | ≥ 99.5% |
| **Tiempo de recuperación (RTO)** | Tiempo hasta servicio restaurado tras falla | ≤ 30 min |
| **Punto de recuperación (RPO)** | Máximo datos perdidos en una falla | ≤ 24h (último backup) |

---

## 5. KPIs de negocio derivados

Estos KPIs se calculan desde Core Layer — su precisión depende de los gaps pendientes.

| KPI | Consulta | Limitaciones actuales |
|-----|----------|----------------------|
| **Socios activos total** | `COUNT(core_subscriptions) WHERE status='active'` | VP: no se distingue activo vs cancelado fácilmente |
| **Recaudación mensual total** | `SUM(core_payments.amount) WHERE month=X` | VP: 32% rechazados ausentes |
| **Recaudación por canal** | `SUM GROUP BY source` | TCH: centro_costo no en Core |
| **Tasa de retención** | `active_this_month / active_last_month` | Requiere `period_reference` (X-1 gap) |
| **Churn rate** | `cancelaciones / cartera_inicio` | Requiere status tracking en Core |

---

## 6. Alertas recomendadas

| Alerta | Condición | Severidad |
|--------|-----------|-----------|
| Sync fallida | `SyncRun.status = 'failed'` | Alta |
| Sync no ejecutada en > 48h | Última sync hace > 48h | Media |
| ETL fallido | `EtlRun.status = 'failed'` | Alta |
| Payku > 30% 'maximum attempt limit' | PK-2 KPI supera umbral | Media |
| TCH: archivo mensual no cargado | `tch_recaudacion_mensual` sin registro del mes | Media |
| Candidatos match > 1,000 pendientes | `client_match_candidates` acumulados | Baja |

---

*Documento generado el 2026-10-20. Valores actuales verificados contra BD en Docker :5433.*
