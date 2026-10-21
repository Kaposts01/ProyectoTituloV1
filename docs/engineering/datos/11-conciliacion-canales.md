# Conciliación de Canales — SynkmetriX

**Fecha:** 2026-10-20  
**Fuente de reportes:** `C:\Users\Usuario\Downloads\CRM_reportes\`  
**Base de datos:** PostgreSQL 17, puerto 5433, DB `crm`

---

## Resumen ejecutivo

Se realizó una conciliación completa entre los reportes descargados manualmente de cada canal (VirtualPOS, Toku, Payku, TCH) y los datos almacenados en la base de datos del CRM. El análisis cubrió conteos de registros, IDs únicos, montos y distribución de estados.

---

## 1. VirtualPOS

### Archivos analizados
- **34** archivos `SuscriptoresPAT-VirtualPOS-*.csv`
- **40** archivos `TransaccionesPAT-VirtualPOS-*.csv`

### Campo de join identificado
- Suscripciones: el portal usa un ID numérico (`Id de suscripción`) distinto al ID de la API (hex). La reconciliación se hizo por conteo y distribución de estados.
- Pagos: `UUID transacción` (col 22) = `vp_payments.external_id` ✓

### Suscripciones

| Métrica | Reporte | BD (`vp_subscriptions`) |
|---------|---------|------------------------|
| Registros | 8,894 | 8,999 |
| ACTIVA | 6,006 | 6,081 |
| CANCELADA | 2,023 | 2,036 |
| SUSCRIPCION_FALLIDA | 864 | 881 |
| SUSCRIBIENDO | 1 | 1 |

- **6 suscripciones en reporte no están en BD** — posible latencia de sincronización.
- **111 suscripciones en BD no están en reporte** — probable VirtualPOS2 o suscripciones antiguas del período no cubierto por los archivos disponibles.

### Pagos

| Métrica | Reporte | BD (`vp_payments`) |
|---------|---------|-------------------|
| Filas totales | 83,011 | 71,011 |
| UUIDs únicos | 70,989 | 71,011 |
| Match (UUID = external_id) | 70,984 (99.99%) | — |
| Solo en reporte | 5 | — |
| Solo en BD | — | 27 |

**Observación VP-REPORTE-1:** El reporte tiene 83,011 filas pero solo 70,989 UUIDs únicos. Las ~12,022 filas sin UUID corresponden a cargos con estado `cancelado`/`procesando` en el portal que no generaron transacción en la API (sin UUID asignado). Esto es arquitecturalmente esperado — el portal clasifica estos estados de forma distinta a la API.

**Mapeo de estados portal → API:**

| Estado portal | Estado API |
|--------------|-----------|
| pagado | pagado |
| rechazado | rechazado |
| cancelado | reintentando / anulado / expirado |
| procesando | pendiente / reintentando |

---

## 2. Toku

### Archivos analizados
- `Toku_pagos.xlsx` (formato antiguo, headers fila 1): 2,379 registros
- `Toku_pagosv2_nuevo.xlsx` (formato nuevo, headers fila 7): 2,380 registros
- `Toku_intentosdepago.xlsx` (headers fila 7): 31,359 intentos
- `Toku_clientes.xlsx` (headers fila 7): 653 clientes

### Pagos

| Métrica | Reporte (old) | Reporte (new) | Unión | BD (`tk_payments`) |
|---------|--------------|--------------|-------|-------------------|
| IDs únicos | 2,379 | 2,380 | 4,759 | 2,377 |
| Match con BD | 2,377 (100%) | — | 2,377 | — |
| Solo en reporte | — | — | **2,382** | — |
| Solo en BD | — | — | 0 | — |

**Gap TK-REPORTE-1 (Alta):** 2,382 pagos presentes en los reportes del portal Toku (principalmente `pagosv2_nuevo.xlsx`) **no están en la BD**. Todos los 2,377 pagos de la BD están cubiertos por los reportes, pero hay pagos adicionales en el portal que nunca fueron sincronizados. El formato nuevo puede cubrir un período o tipo de pago no capturado por la sincronización actual.

### Intentos de cobro vs Facturas

| Métrica | Reporte (`Toku_intentosdepago.xlsx`) | BD (`tk_invoices`) |
|---------|-------------------------------------|-------------------|
| Facturas únicas (campo `Deuda`) | 3,583 | 6,363 |
| Match | 3,446 | — |
| Solo en reporte | **137** | — |
| Solo en BD | — | **2,917** (UNPAID/VOID) |

- 2,917 facturas en BD sin intentos en el reporte: en su mayoría `UNPAID` (futuras/pendientes) y `VOID` — nunca tuvieron intento de cobro registrado en el reporte.
- 137 facturas con intentos en el reporte no están en BD.
- Distribución de estados en intentos: FALLIDO (28,970), AUTORIZADO (2,379), EN PROCESO (10).

### Clientes

| Métrica | Reporte (`Toku_clientes.xlsx`) | BD (`tk_customers`) |
|---------|-------------------------------|---------------------|
| Registros | 653 | 538 |
| Match | 532 (81%) | — |
| Solo en reporte | **121** | — |
| Solo en BD | — | 6 |

**Gap TK-REPORTE-2 (Media):** 121 clientes en el portal Toku no están en `tk_customers`. La sincronización de clientes puede ser incompleta o hay clientes creados recientemente.

---

## 3. Payku

### Archivos analizados
- `Payku_datasubscripciones.xlsx`: 822 suscripciones (activas + suspendidas)
- `Payku_dataTransacciones.xlsx`: 10,591 transacciones
- `Payku_reporte_consolidado_2020.xlsx` a `_2026.xlsx`: 7 archivos anuales

### Suscripciones

| Métrica | Reporte | BD (`p_subscriptions`) |
|---------|---------|------------------------|
| Registros | 822 | 5,700 |
| Match | **822 (100%)** | — |
| Solo en reporte | 0 | — |
| Solo en BD | — | 4,878 (históricas) |

El reporte de Payku exporta solo el estado actual (activas + suspendidas). La BD contiene el historial completo incluyendo `delete` (680), `cancel` (116) y `register` (3,414). **Cobertura correcta.**

Distribución BD: `register` 3,414 · `suspended` 1,047 · `delete` 680 · `active` 442 · `cancel` 116 · `suspended_awaits_change_plan` 1.

### Transacciones

| Métrica | Reporte | BD (`p_transactions`) |
|---------|---------|----------------------|
| IDs únicos | 10,591 | 35,854 |
| Match | 10,136 (96%) | — |
| Solo en reporte | **455** | — |
| Solo en BD | — | 25,718 |
| Monto total (col10) | 256,948,270 CLP | — |
| Monto success en BD | — | 253,396,298 CLP |

**Gap PK-REPORTE-1 (Media):** 455 transacciones en el reporte portal no están en la BD. Probablemente transacciones de los últimos días/semanas, posteriores a la última sincronización.

La BD tiene 25,718 transacciones no en el reporte `dataTransacciones` — el reporte es una exportación del período reciente, no el histórico completo. Los reportes consolidados anuales cubren el histórico.

Distribución BD: `success` 26,938 · `rejected` 8,560 · `pending` 356.

### Reportes consolidados anuales

| Año | Monto (col5 = Monto) | Filas |
|-----|----------------------|-------|
| 2020 | 6,957,000 CLP | 1,041 |
| 2021 | 30,317,430 CLP | 3,275 |
| 2022 | 47,156,787 CLP | 4,018 |
| 2023 | 114,154,093 CLP | 6,499 |
| 2024 | 284,049,368 CLP | 11,711 |
| 2025 | 350,500 CLP | 45 |
| 2026 | 58,341,147 CLP | 4,853 |
| **TOTAL** | **541,326,325 CLP** | **31,442** |

> El total consolidado (541M) difiere del monto success en BD (253M) porque los consolidados incluyen liquidaciones, comisiones, movimientos netos y otros tipos de movimiento que no son pagos de suscripción directos. Los IDs (`Identificador/vaucher`) no son comparables directamente con los IDs de `p_transactions`.

---

## 4. TCH

### Archivos analizados
30 archivos Excel mensuales (enero 2025 hasta septiembre 2026, más históricos desde 2017).

### Cobertura de archivos

| Métrica | Disco | BD |
|---------|-------|----|
| Archivos | 30 | 30 |
| Match | 29 | — |
| Solo en disco | `20260831 TCH IG AGOSTO 2026.XLSX` | — |
| Solo en BD | — | `20260831 TCH IG GESTION AGOSTO 2026.XLSX` |

**Gap TCH-REPORTE-1 (Baja):** Existen dos versiones del reporte de agosto 2026 en disco. La versión `GESTION` está cargada en BD (con 135,081 transacciones para 2026-08). La versión sin sufijo no fue cargada — puede ser un duplicado o una versión con datos parcialmente distintos. Requiere revisión manual.

### Transacciones

| Estado | Filas en BD | Fichas únicas |
|--------|-------------|---------------|
| ACEPTADA | 999,131 | 23,308 |
| RECHAZADA | 386,660 | 21,768 |
| NULA | 58,120 | 14,398 |
| EN PROCESO | 28,289 | 2,478 |
| CONGELADA | 31 | 23 |
| **TOTAL** | **1,472,231** | — |

- **Períodos cubiertos:** 2017-01 a 2026-09 (99 períodos)
- **Monto ACEPTADA:** ~6,938,864,448 CLP (suma histórica total)
- **Clientes:** 28,982 únicos por RUT
- **Suscripciones:** 29,295 mandatos únicos

> **Nota de formato:** Los RUTs en los reportes Excel usan formato sin puntos (ej: `11631470-3`) mientras que en la BD se almacenan con puntos (ej: `11.631.470-3`). Esto impide la comparación directa por RUT sin normalización previa.

---

## 5. Gaps identificados en esta conciliación

| ID | Canal | Severidad | Descripción | Estado |
|----|-------|-----------|-------------|--------|
| TK-REPORTE-1 | Toku | **Alta** | 2,382 pagos en reporte portal no están en BD — el formato nuevo `pagosv2` puede cubrir pagos no sincronizados por el conector actual | Nuevo |
| TK-REPORTE-2 | Toku | Media | 121 clientes en portal no sincronizados en `tk_customers` | Nuevo |
| PK-REPORTE-1 | Payku | Media | 455 transacciones en portal no están en BD — posible latencia de sincronización reciente | Nuevo |
| TCH-REPORTE-1 | TCH | Baja | Archivo `20260831 TCH IG AGOSTO 2026.XLSX` en disco no cargado (hay versión `GESTION` cargada) | Nuevo |
| VP-REPORTE-1 | VP | Informativo | 12,022 filas sin UUID en reporte — cargos cancelados/procesando sin transacción generada. Comportamiento esperado de la API | Documentado |

---

## 6. Estado de cobertura por canal

| Canal | Suscripciones | Pagos/Transacciones | Cobertura general |
|-------|--------------|--------------------|--------------------|
| VirtualPOS | ✅ 99.9% | ✅ 99.99% | Excelente |
| Toku | ⚠️ 2,382 pagos faltantes | ⚠️ 121 clientes faltantes | Requiere revisión |
| Payku | ✅ 100% activas | ⚠️ 455 recientes faltantes | Buena, latencia menor |
| TCH | ✅ 30/30 archivos | ✅ 1,472,231 transacciones | Excelente |

---

## 7. Próximas acciones recomendadas

1. **TK-REPORTE-1:** Analizar si el endpoint Toku que genera `pagosv2_nuevo.xlsx` es distinto al que sincroniza el conector actual. Revisar `app/connectors/toku.py` y documentación de la API.
2. **TK-REPORTE-2:** Revisar si el conector Toku sincroniza todos los clientes o solo los asociados a suscripciones activas.
3. **PK-REPORTE-1:** Ejecutar sincronización manual de Payku y verificar si los 455 IDs aparecen en BD.
4. **TCH-REPORTE-1:** Comparar contenido de ambas versiones del archivo agosto 2026 antes de decidir si cargar la versión sin sufijo.
5. **Normalización RUT TCH:** Considerar normalizar los RUTs en `tch_clientes` para facilitar conciliaciones futuras.
