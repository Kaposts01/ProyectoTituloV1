# DATA-04 — Modelo de Datos TCH

> Sprint 1 — Auditoría de Datos. Fuente: `app/models/tch.py`, `app/services/channel_consolidation.py`.

## Origen de datos

TCH (Transferencias Continuas) es un canal propio vía archivos Excel. Los reportes históricos (2017–2026, 29 archivos) se cargan via ETL (`scripts/load_tch_excel.py` o equivalente) a las tablas `tch_*`.

## Tablas de canal (`tch_*`)

| Tabla | Modelo SQLAlchemy | Clave de idempotencia | Descripción |
|---|---|---|---|
| `tch_clientes` | `TchCliente` | `UNIQUE(rut)` | Clientes/socios TCH |
| `tch_suscripciones` | `TchSuscripcion` | `UNIQUE(numero_ficha)` | Fichas de suscripción TCH |
| `tch_transacciones` | `TchTransaccion` | `UNIQUE(dedupe_key)` | Cobros/transacciones mensuales |
| `tch_recaudacion_mensual` | `TchRecaudacionMensual` | `UNIQUE(periodo)` | Control mensual oficial de recaudación |
| `tch_bancos` | `TchBanco` | `UNIQUE(nombre)` | Catálogo de bancos |
| `tch_tipos_mandato` | `TchTipoMandato` | `UNIQUE(codigo)` | Catálogo de tipos de mandato |
| `tch_origenes` | `TchOrigen` | `UNIQUE(nombre)` | Catálogo de orígenes de captación |
| `tch_centros_costo` | `TchCentroCosto` | `UNIQUE(nombre)` | Catálogo de centros de costo |

### tch_clientes — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `rut` | String(20) | **PK de negocio** — clave de deduplicación; un RUT = un cliente TCH |
| `nombre` | String(150) | Nombre |
| `apellido` | String(150) | Apellido |
| `tipo_socio` | String(50) | Tipo de socio TCH |
| `email` | String(320) | Disponible en TCH pero **no se popula a `clients` canónicos** |
| `telefono` | String(100) | Disponible en TCH pero **no se popula a `clients` canónicos** |
| `fecha_nacimiento` | String(20) | Se mapea a `birth_date` canónico |

### tch_suscripciones — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `numero_ficha` | Integer | **PK de negocio** — ID de la suscripción TCH |
| `numero_mandato` | Integer | Número de mandato bancario |
| `cliente_rut` | String(20) | **FK lógica** a `tch_clientes.rut` |
| `banco_nombre` | String(100) | Nombre del banco (string, no FK física) |
| `tipo_mandato` | String(20) | Código del tipo de mandato |
| `origen` | String(150) | Origen de captación |
| `centro_costo` | String(150) | Centro de costo |
| `estado` | String(20) | VIGENTE / BAJA / SUSPENDIDA |
| `monto` | String(20) | Monto del mandato (string) |
| `fecha_activacion` | String(20) | Fecha de activación |
| `fecha_eliminacion` | String(20) | Fecha de baja |

### tch_transacciones — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `numero_ficha` | Integer | FK lógica a `tch_suscripciones.numero_ficha` |
| `periodo` | String(10) | YYYY-MM — período del cobro |
| `estado` | String(20) | ACEPTADA / RECHAZADA / etc. |
| `monto` | String(20) | Monto del cobro (string) |
| `fecha_cargo` | String(20) | Fecha del cargo |
| `dedupe_key` | String(255) | UNIQUE — clave de deduplicación cross-archivo |
| `archivo_origen` | String(255) | Nombre del archivo Excel fuente |
| `codigo_respuesta` | String(50) | Código de respuesta del banco |
| `entidad_recaudadora` | String(100) | Entidad que ejecutó el cobro |

### tch_recaudacion_mensual — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `periodo` | String(7) | YYYY-MM — único por período |
| `aceptadas_cantidad` | Integer | Cobros aceptados |
| `aceptadas_monto` | String(20) | Monto total aceptado |
| `rechazadas_cantidad` | Integer | Cobros rechazados |
| `rechazadas_monto` | String(20) | Monto total rechazado |
| `archivo_origen` | String(255) | Nombre del archivo Excel fuente |

## Consolidación TCH → Tablas canónicas

| Tabla TCH | Tabla canónica | Mapeo clave |
|---|---|---|
| `tch_clientes` | `clients` | `source="tch"`, `external_id=rut`, `social_id=rut` |
| `tch_suscripciones` | `subscriptions` | `source="tch"`, `external_id=str(numero_ficha)`, `client_social_id=cliente_rut` |
| `tch_transacciones` | `charges` | `source="tch"`, `external_id=dedupe_key`, `subscription_external_id=str(numero_ficha)` |

**Nota:** `tch_recaudacion_mensual`, `tch_bancos`, `tch_tipos_mandato`, `tch_origenes` y `tch_centros_costo` **no se consolidan** a tablas canónicas. Son catálogos de referencia y control operativo.

### Procesamiento en chunks

`_consolidate_tch_transactions` usa paginación de 2000 filas por volumen (~150k registros). El resto de las funciones TCH cargan todo en memoria.

## Flujo de sincronización

```
Archivos Excel TCH (histórico 2017–2026)
  → scripts/load_tch_excel.py (ETL manual/CLI)
  → tch_clientes / tch_suscripciones / tch_transacciones / catálogos
  → channel_consolidation.py (_consolidate_tch_*)
  → clients / subscriptions / charges
```

## Brechas y limitaciones conocidas

| ID | Tipo | Descripción |
|---|---|---|
| GAP-TCH-01 | **Identidad — tensión con ADR-001** | TCH usa RUT como PK (`UNIQUE(rut)` en `tch_clientes`). En la consolidación, `external_id=rut` y `social_id=rut`. Esto viola el principio de ADR-001 de no usar RUT como clave transversal universal. Registrado en Technical Debt. |
| GAP-TCH-02 | Datos perdidos en consolidación | `email` y `telefono` de `tch_clientes` **no se mapean** a `clients` canónicos. Se consolida con `email=NULL`, `phone_number=NULL`. |
| GAP-TCH-03 | Relación cliente-transacción | `client_external_id` en `charges` canónicos es `NULL` para TCH. La relación es: `charges.subscription_external_id` → `subscriptions.external_id` → `subscriptions.client_social_id` → `clients.social_id`. Requiere dos joins. |
| GAP-TCH-04 | Montos como strings | `monto` en `tch_suscripciones`, `tch_transacciones` y `tch_recaudacion_mensual` son `String`. Conversión necesaria para cálculos. |
| GAP-TCH-05 | Fechas como strings | Todas las fechas son `String(20)` para tolerar datos sucios del Excel histórico. No hay validación de formato. |
| GAP-TCH-06 | Sin carga incremental | La carga TCH es batch completo desde Excel. No hay sincronización en tiempo real. |
| GAP-TCH-07 | `numero_ficha` vs `dedupe_key` | `tch_transacciones` usa `dedupe_key` como clave de idempotencia, pero su construcción depende del ETL de carga. Si cambia la lógica del ETL, pueden aparecer duplicados o huecos. |
