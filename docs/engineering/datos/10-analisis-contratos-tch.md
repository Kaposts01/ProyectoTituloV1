# Análisis de Contrato de Datos — TCH (Excel ETL)

**Última actualización:** 2026-10-20
**Fuente analizada:** `20260930 TCH IG SEPTIEMBRE 2026.XLSX` (32 hojas)
**Propósito:** Mapear qué datos entrega TCH por Excel, qué captura el staging TCH en el CRM, y qué llega al modelo Core. Identificar gaps y campos sin utilizar.

---

## 1. Estructura del Excel TCH

### 1.1 Hojas del archivo (32 en total)

| Grupo | Hojas | Propósito |
|-------|-------|-----------|
| Resumen ejecutivo | `KPI`, `CONSOLIDADO` | Métricas globales del mes |
| Cartera activa | `VIGENTES`, `RESUMEN CARTERA VIGENTE` | Socios con mandato activo |
| Bajas | `ELIMINADOS`, `RECHAZADOS` | Mandatos eliminados/rechazados 2026 |
| Flujo | `FLUJO MANDATOS CANT`, `FLUJO MANDATOS MONTO` | Movimientos mensuales |
| Histórico | `HISTORICO RECAUDACION CAN`, `HISTORICO RECAUDACION FLUJO` | Serie histórica |
| Detalle operativo | `CARGOS ACEPTADOS`, `CARGOS RECHAZADOS`, `RECHAZOS` | Transacciones del mes |
| Eficiencia | `EFICIENCIA ENT`, `ENT RECHAZOS` | Por entidad recaudadora |
| Por canal | `TOC`, `REG`, `WT`, `CP`, `CE`, `BB`, `VV`, `CHD`, `CC9`–`CC15` | Desglose por centro de costo |
| Operativo | `DIA CARGO`, `ENVIADOS BANCO` | Cobros por día y envíos a bancos |
| Referencia | `TABLAS` | Catálogos internos |

### 1.2 Dimensiones del archivo (Septiembre 2026)

| Hoja | Filas de datos | Notas |
|------|---------------|-------|
| `VIGENTES` | 9,691 | Socios con mandato activo |
| `ELIMINADOS` | (< 1,000 estimado) | Bajas del año 2026 |
| `CARGOS ACEPTADOS` | 5,644 | Cobros exitosos del mes |
| `CARGOS RECHAZADOS` | 2,094 | Rechazos del mes |

---

## 2. Modelo de datos del Excel

### 2.1 Hoja VIGENTES — esquema de columnas

La hoja VIGENTES tiene estructura multi-nivel (merging de celdas). El esquema real, verificado por inspección, es:

**Bloque A — Identificación organizacional (cols 0–7)**

| Col | Campo | Ejemplo |
|-----|-------|---------|
| 0 | Centro Costo | CHILEDAR, TECHO OC, BIO BIO, VIÑA-VALPO... |
| 1 | Estrategia | CALL CENTER, CONVENIO... |
| 2 | Origen / Campaña | CHILEDAR, SOCIOS 2023... |
| 3 | Lugar Captacion | CALL CENTER, STAND, WEB... |
| 4 | Captador | Nombre del captador o canal |
| 5 | Ficha DUES | 12294 (ID interno DUES) |
| 6 | Mandato DUES | 12387 (ID del mandato en DUES) |
| 7 | Folio | 0 |

**Bloque B — Socio (cols 8–16)**

| Col | Campo | Ejemplo |
|-----|-------|---------|
| 8 | Rut | 9555379-6 |
| 9 | Referencia | Señora / Señor |
| 10 | Nombre | NIEVES DEL CARMEN |
| 11 | Apellido | FUENTES . |
| 12 | Fecha Nacimiento | — |
| 13 | Profesión | — |
| 14 | Tipo Socio | SOCIO |
| 15 | Ley | Sin Ley / con ley tributaria |
| 16 | Reajuste | — |

**Bloque C — Datos del titular de la cuenta (cols 17–21)**

| Col | Campo | Ejemplo |
|-----|-------|---------|
| 17 | Personalidad | Natural / Jurídico |
| 18 | Rut titular | 9555379-6 (puede diferir del socio) |
| 19 | Referencia | Señora |
| 20 | Nombre | NIEVES DEL CARMEN |
| 21 | Apellidos | FUENTES . |

**Bloque D — Antecedentes y estado del mandato (cols 22–34)**

| Col | Campo | Ejemplo |
|-----|-------|---------|
| 22 | Firma (fecha) | 2013-12-06 |
| 23 | Tipo Mandato | PAC / CMR Falabella / PAT Bancario |
| 24 | Banco/Institución | Banco Estado / BCI / Falabella / Santander |
| 25 | Tipo Cuenta | Cuenta Corriente / Cuenta Rut / Cuenta Vista |
| 26 | Número Cuenta | XXXX-8084 (últimos 4 dígitos) |
| 27 | Ingreso | 2018-01-01 |
| 28 | Entrega Banco | 2018-01-01 |
| 29 | Fecha Activación | 2018-01-08 |
| 30 | Fecha Rechazo | — |
| 31 | Fecha Eliminado | — |
| 32 | ESTADO | Activo / Rechazado / Eliminado |
| 33 | Motivo | (motivo de baja) |
| 34 | Solicitado Por | — |

**Bloque E — Contacto (cols 35–43)**

| Col | Campo |
|-----|-------|
| 35 | Teléfonos |
| 36 | eMail |
| 37 | Dirección |
| 38 | Número |
| 39 | Casa/Depto |
| 40 | VILLA/POB. |
| 41 | COMUNA |
| 42 | CIUDAD |
| 43 | REGION |

**Bloque F — Mandato anterior (cols 44–46)**

| Col | Campo |
|-----|-------|
| 44 | N° Mandato Anterior |
| 45 | Fecha Primer Cobro (anterior) |
| 46 | Monto Primer Cobro (anterior) |

**Bloque G — Mandato actual (cols 47–54)**

| Col | Campo | Ejemplo |
|-----|-------|---------|
| 47 | Moneda Vigente | Pesos / UF |
| 48 | Monto Vigente | 3000 |
| 49 | Equivalente en Pesos | 3000 |
| 50 | Fecha Primer Cobro | 2018-02-01 |
| 51 | Monto Primer Cobro | 3000 |
| 52 | Diferencia vs Anterior | 3000 |
| 53 | Cuotas Cobradas | 103 |
| 54 | Monto Cobrado | 309000 |

**Bloque H — Aportes acumulados (cols 55–58)**

| Col | Campo |
|-----|-------|
| 55 | Cuotas acumuladas |
| 56 | Monto acumulado |
| 57 | Promedio Donación |
| 58 | Meses Continuos Sin Aporte |

**Bloque I — Permanencia (cols 59–61)**

| Col | Campo |
|-----|-------|
| 59 | Meses de permanencia |
| 60 | Años de permanencia |
| 61 | Mes actual |

**Bloque J — Historial últimos 12 meses (cols 62–97)**

Para cada mes (SEPT26 → OCT25), 3 columnas: `Nº cuota`, `Estado`, `Monto`. Estados posibles: `Pagada`, `Rechazada`, `Pendiente`, `Sin Cargo`.

**Bloque K — Columnas operativas extra (cols 98–103)**

| Col | Campo |
|-----|-------|
| 98 | CANTIDAD (cobros vigentes) |
| 99 | TIPO CARGO SIN ESTADO |
| 100 | ENTIDAD |
| 101 | NVO (nuevo este mes) |
| 102 | RECH MES (rechazos en el mes) |
| 103 | ELI MES (eliminados en el mes) |

### 2.2 Hoja CARGOS ACEPTADOS — columnas verificadas

| # | Campo | Ejemplo |
|---|-------|---------|
| 0 | Número Ficha | 28892 |
| 1 | Número Mandato | 29243 |
| 2 | Tipo Mandato | PAC |
| 3 | Entidad Recaudadora | Banco Estado |
| 4 | Centro Costo | TECHO OC |
| 5 | Origen | SOCIOS 2023 |
| 6 | Captador | COLABORA LAB |
| 7 | Ley | Sin Ley |
| 8 | Rut | 7614914-3 |
| 9 | Nombre | MARIA |
| 10 | Apellido | OSORIO LIRA |
| 11 | Transacción | Reintento / Normal |
| 12 | Numero Pagos del Mandato | 24 |
| 13 | Periodo | 1 (número de periodo) |
| 14 | N° Cuota | 12 |
| 15 | Cuota Mes | SEPT 26 |
| 16 | Moneda | Pesos |
| 17 | Monto Cuota | 7000 |
| 18 | TOTAL CARGADO | 7000 |
| 19 | Fecha Cobro | 2026-09-09 |

### 2.3 Hoja CARGOS RECHAZADOS — columnas adicionales

Mismas que CARGOS ACEPTADOS, más:
- **Col 20: Motivo** — descripción del rechazo (texto descriptivo del banco)

### 2.4 Motivos de rechazo disponibles en TCH (verificado)

| Motivo | Count Sept 2026 | Monto |
|--------|----------------|-------|
| Cuenta Errónea | 331 | 3,787,000 |
| Firma Disconforme | 321 | 3,150,000 |
| Sin Registro de Firma | 165 | 2,073,000 |
| No Existe Cuenta | 89 | 1,015,000 |
| Mandato No Existe | (en CARGOS RECHAZADOS) | — |
| Rut Erróneo | 58 | 661,000 |
| Cliente Rechaza Mandato | 42 | 499,000 |
| Fotocopia Rut Ilegible | 45 | 331,000 |
| Mandato Enmendado | 56 | 578,000 |
| Falta Fondos | (en CARGOS RECHAZADOS) | — |
| Cuenta Cerrada | 4 | 45,000 |
| ... (21 motivos en total) | | |
| **TOTAL** | **1,292** | **13,514,000** |

---

## 3. Tablas TCH en el CRM (staging)

### 3.1 Inventario de tablas

| Tabla | Filas | Descripción |
|-------|-------|-------------|
| `tch_bancos` | 22 | Catálogo de bancos/instituciones |
| `tch_centros_costo` | 8 | TOC, REG, WT, CP, CE, BB, VV, CHD |
| `tch_tipos_mandato` | 7 | PAC, PAT, CMR Falabella, etc. |
| `tch_origenes` | 22 | Campañas/años de origen |
| `tch_clientes` | 28,982 | Socios históricos (29 archivos) |
| `tch_suscripciones` | 29,295 | Mandatos históricos |
| `tch_transacciones` | 1,472,231 | Transacciones históricas 2017–2026 |
| `tch_recaudacion_mensual` | 128 | Resumen mensual por archivo |

### 3.2 Mapeo Excel → Staging

#### VIGENTES → tch_suscripciones

| Campo Excel | Campo staging | Estado |
|-------------|--------------|--------|
| Centro Costo | `centro_costo` | OK |
| Ficha DUES | `numero_ficha` | OK |
| Mandato DUES | `numero_mandato` | OK |
| Rut socio | `cliente_rut` | OK |
| Tipo Mandato | `tipo_mandato` | OK |
| Banco/Institución | `banco_nombre` | OK |
| Tipo Cuenta | `tipo_cuenta` | OK |
| Número Cuenta (masked) | `numero_cuenta` | OK |
| Fecha Ingreso | `fecha_ingreso` | OK |
| Fecha Entrega Banco | `fecha_entrega_banco` | OK |
| Fecha Activación | `fecha_activacion` | OK |
| Fecha Rechazo | `fecha_rechazo` | OK |
| Fecha Eliminado | `fecha_eliminacion` | OK |
| ESTADO | `estado` | OK |
| Motivo (baja) | `razon_baja` | OK |
| Monto Vigente | `monto` | OK |
| Equivalente en Pesos | `equivalente_pesos` | OK |
| Origen | `origen` | OK |
| Captador | `captador` | OK |
| Ley | `ley` | OK |
| Reajuste | `reajuste` | OK |
| Firma (fecha) | `firma` | OK |
| **Estrategia** | — | **GAP: no en staging** |
| **Lugar Captacion** | — | **GAP: no en staging** |
| **Folio** | — | **GAP: no en staging** |
| **Personalidad titular** | — | **GAP: no en staging** |
| **Rut titular** (diferente de socio) | — | **GAP: no en staging** |
| **N° Mandato Anterior** | — | **GAP: no en staging** |
| **Fecha/Monto Primer Cobro actual** | — | **GAP: no en staging** |
| **REGION** | — | **GAP: no en staging** |

#### VIGENTES → tch_clientes

| Campo Excel | Campo staging | Estado |
|-------------|--------------|--------|
| Rut | `rut` | OK |
| Nombre | `nombre` | OK |
| Apellido | `apellido` | OK |
| Fecha Nacimiento | `fecha_nacimiento` | OK |
| Profesión | `profesion` | OK |
| Tipo Socio | `tipo_socio` | OK |
| Tipo Persona (Personalidad) | `tipo_persona` | OK |
| Teléfonos | `telefono` | OK |
| eMail | `email` | OK |
| Dirección + Número | `direccion` | OK (concatenado) |
| COMUNA | `comuna` | OK |
| CIUDAD | `ciudad` | OK |
| **VILLA/POB.** | — | **GAP: no en staging** |
| **REGION** | — | **GAP: no en staging** |

#### CARGOS ACEPTADOS/RECHAZADOS → tch_transacciones

| Campo Excel | Campo staging | Estado |
|-------------|--------------|--------|
| Número Ficha | `numero_ficha` | OK |
| Número Mandato | `numero_mandato` | OK |
| Entidad Recaudadora | `entidad_recaudadora` | OK |
| Transacción (Normal/Reintento) | `tipo_transaccion` | OK |
| Numero Pagos del Mandato | `total_cuotas` | OK |
| Periodo (número) | `periodo` | OK |
| N° Cuota | `numero_cuota` | OK |
| Monto Cuota | `monto` | OK |
| Fecha Cobro / Fecha Intento | `fecha_cargo` | OK |
| Motivo rechazo | `razon_rechazo` | OK |
| **Tipo Mandato** | — | **GAP: no en tch_transacciones** (join requerido a suscripciones) |
| **Centro Costo** | — | **GAP: no en tch_transacciones** (join requerido) |
| **Origen** | — | **GAP: no en tch_transacciones** (join requerido) |
| **Moneda** | — | **GAP: no en tch_transacciones** |
| **Cuota Mes** (label mes) | — | **GAP: no en tch_transacciones** (derivable del periodo) |
| Estado de la transacción | `estado` | OK (Aceptado/Rechazado) |
| Código respuesta banco | `codigo_respuesta` | OK (disponible aunque no en Excel) |

---

## 4. Core Layer — qué llega de TCH

Actualmente el ETL TCH escribe a:
- `core_clients` — desde `tch_clientes` (vía RUT)
- `core_subscriptions` — desde `tch_suscripciones`
- `core_charges` — desde `tch_transacciones`
- `core_payments` — desde `tch_transacciones` (transacciones aceptadas)

### Gaps en Core Layer para TCH

| ID | Descripción | Impacto |
|----|-------------|---------|
| TCH-1 | `centro_costo` de tch_suscripciones no llega a `core_subscriptions` | Sin segmentación por entidad (TECHO OC, BIO BIO, etc.) en Core |
| TCH-2 | `region` no está en staging, por lo tanto no en Core | Sin análisis geográfico a nivel región |
| TCH-3 | `razon_rechazo` descriptivo de tch_transacciones no mapeado a `core_charges` | Motivo de rechazo disponible en staging pero ausente en Core |
| TCH-4 | `tipo_mandato` (PAC/PAT/CMR) no en tch_transacciones → no en `core_charges` | Tipo de canal de cobro inaccesible sin JOIN |
| TCH-5 | `permanencia` (meses/años de socio) no computada ni almacenada en Core | Sin indicador de fidelidad en `core_clients` |
| TCH-6 | `meses_continuos_sin_aporte` no computado ni almacenado | Sin indicador de riesgo de churn en Core |
| TCH-7 | `moneda` de transacciones (Pesos/UF) no en tch_transacciones → no en Core | No distinguible cuotas en UF vs CLP en Core |

---

## 5. Comparativa TCH vs otros canales

### Lo que TCH ofrece que los demás no tienen

| Dato | TCH | VirtualPOS | Toku | Payku |
|------|-----|------------|------|-------|
| **Motivo de rechazo** | 21 códigos específicos por banco | No existe en API | No aplica | Descripción genérica |
| **Centro de costo** | TECHO OC, BIO BIO, CHILEDAR, etc. | Plataforma (1/2) | No | No |
| **Captador** | Nombre del captador | No | No | No |
| **Tipo de cuenta** | Cta Cte / Cta RUT / Cta Vista | No | Método de pago | Tarjeta |
| **Entidad recaudadora** | Banco específico | Adquirente | Procesador Toku | Paymaster |
| **Permanencia calculada** | Meses y años | No | No | No |
| **Historial 12 meses** | Por cuota (estado + monto) | Solo Core | Solo Core | Solo Core |
| **Mandato anterior** | Trazabilidad de cambio de monto | No | No | No |

### Restricciones únicas de TCH

| Restricción | Descripción |
|-------------|-------------|
| **Batch mensual** | TCH no es API en tiempo real — es un reporte Excel mensual cargado manualmente |
| **Número cuenta parcial** | Solo últimos 4 dígitos (XXXX-8084) — correcto por PCI |
| **Sin fecha de pago exacta en UF** | La conversión a pesos se hace en el momento del cobro — el monto en UF se pierde |
| **RUT como único identificador** | No existe `client_id` numérico externo — el RUT es la clave de identidad |
| **Carga idempotente por dedupe_key** | `tch_transacciones.dedupe_key` es el mecanismo de deduplicación entre cargas del mismo archivo |

---

## 6. Acciones recomendadas

### Corto plazo (no requieren cambio de modelo Core)

| Acción | Gap resuelto | Archivo |
|--------|-------------|---------|
| Agregar `region` a `tch_clientes` | TCH-2 | Migración Alembic + ETL TCH |
| Agregar `tipo_mandato` a `tch_transacciones` (derivar de suscripciones) | TCH-4 | Script de backfill |
| Agregar `villa_poblacion` a `tch_clientes` | — | Migración Alembic + ETL TCH |

### Requieren decisión de arquitectura

| Acción | Gap | Decisión necesaria |
|--------|-----|-------------------|
| Mapear `centro_costo` → `core_subscriptions` | TCH-1 | ¿Nuevo campo en Core o solo consulta vía staging? |
| Mapear `razon_rechazo` → `core_charges` | TCH-3 | Requiere campo `rejection_reason` en Core (vs `latest_rejection_reason` ya existente) |
| Calcular y almacenar permanencia en Core | TCH-5/6 | ¿En `core_clients` como atributo calculado, o en `core_client_attributes`? |

### Documentar como limitación (no corregible)

- `moneda` de transacciones en UF: no hay forma de recuperarla del Excel histórico
- `folio` no crítico para el modelo de negocio del CRM
- Datos de mandato anterior: disponible en el Excel actual pero no en archivos históricos pre-2024

---

## 7. Validación de integridad (Septiembre 2026)

| Métrica | Excel | CRM (si cargado) | Diferencia esperada |
|---------|-------|-----------------|---------------------|
| Cargos aceptados | 5,644 | rows en tch_transacciones con estado=Aceptado periodo=09/2026 | 0 |
| Cargos rechazados | 2,094 | rows en tch_transacciones con estado=Rechazado periodo=09/2026 | 0 |
| Total recaudado (aceptados) | 46,687,623 CLP | SUM(monto) de tch_transacciones aceptadas | 0 |
| Socios vigentes | 9,691 | tch_suscripciones con estado=Activo | puede diferir (datos de todos los archivos) |

---

*Documento generado el 2026-10-20 a partir de inspección del Excel `20260930 TCH IG SEPTIEMBRE 2026.XLSX` y de la BD CRM en Docker :5433.*
