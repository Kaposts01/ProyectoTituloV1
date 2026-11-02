# DATA-04 — Modelo de Datos TCH

> Sprint 1 — Auditoría de Datos. Fuente: `app/models/tch.py`, `app/services/channel_consolidation.py`.

## Origen de datos

TCH (Transferencias Continuas) es un canal propio vía archivos Excel. La carpeta de reportes (auditoría del 2026-10-29,
[parity_tch.md](../planning/auditoria-2026-10-29/parity_tch.md)) tiene **30 archivos .xlsx** que cubren dic-2017 a
sep-2026: 9 cierres de diciembre (2017 a 2025), 12 mensuales 2025 (`NN - TCH IG MES 2025`, sin fecha numérica en el
nombre) y 9 mensuales 2026 (`AAAAMMDD TCH IG MES 2026`). Uno es copia exacta de otro (`12 - TCH IG DICIEMBRE 2025 (1)`
= `20260101 TCH IG DICIEMBRE 2025`, mismo sha256): la carga completa lo omite, así que se procesan **29 únicos**.

Volumen: antes de la recarga D13 la base tenía **1.472.231** filas en `tch_transacciones` (no ~150 k como decía esta
página), con duplicados por la clave antigua; tras la recarga se esperan ~1,0 M intentos más el historial fuera del
rango del control (ver [tch-reload.md](tch-reload.md)).

El ETL es `scripts/etl_tch.py` (CLI `--mode full|incremental` y `import_incremental_file`, que usa la carga desde
administración, TCH-07). No existe `scripts/load_tch_excel.py`.

### Variantes de layout del reporte (TCH-PAR-19)

| Variante | Reportes | Encabezado | Cómo la trata el ETL |
|---|---|---|---|
| A | cierres 2017-2021 y 2024-2025, mensuales 2025-2026 | grupo en la fila 6, columna en la 7, datos desde la 8 | `header=[5, 6]` |
| B | cierre dic-2022 | una fila más abajo | se detecta por la primera ficha numérica (`_detect_header_rows`) |
| Sin cartera | cierre dic-2023 | VIGENTES es una tabla numérica de 11 columnas | VIGENTES se ignora y no se infieren bajas; ELIMINADOS, RECHAZADOS y CARGOS sí se cargan |

Las tres variantes tienen pruebas con Excel sintético sin datos personales (`tests/tch_layouts.py`,
`tests/test_tch_par19.py`). Cada reporte se abre una sola vez y cada hoja se recorre una sola vez (`ReportBook`,
TCH-PAR-16).

## Tablas de canal (`tch_*`)

| Tabla | Modelo SQLAlchemy | Clave de idempotencia | Descripción |
|---|---|---|---|
| `tch_clientes` | `TchClient` | `UNIQUE(rut)` | Clientes/socios TCH |
| `tch_suscripciones` | `TchSubscription` | `UNIQUE(numero_ficha)` | Fichas de suscripción TCH |
| `tch_transacciones` | `TchTransaction` | `UNIQUE(dedupe_key)` | Cobros/transacciones mensuales |
| `tch_recaudacion_mensual` | `TchMonthlyCollection` | `UNIQUE(periodo)` | Control mensual oficial de recaudación |
| `tch_bancos` | `TchBank` | `UNIQUE(nombre)` | Catálogo de bancos |
| `tch_tipos_mandato` | `TchMandateType` | `UNIQUE(codigo)` | Catálogo de tipos de mandato |
| `tch_origenes` | `TchOrigin` | `UNIQUE(nombre)` | Catálogo de orígenes de captación |
| `tch_centros_costo` | `TchCostCenter` | `UNIQUE(nombre)` | Catálogo de centros de costo |

> Desde la tanda de identificadores (D32) las clases y atributos Python están en inglés (`TchTransaction.file_number`, `charge_date`, `installment_number`...) pero las tablas y columnas de la base conservan los nombres en español de esta página (`numero_ficha`, `fecha_cargo`, `numero_cuota`...): cada atributo fija el nombre real con `mapped_column("nombre_real", ...)` y `tests/test_tch_schema_unchanged.py` prueba que el esquema no cambia.

### tch_clientes — campos clave

| Campo | Tipo | Notas |
|---|---|---|
| `rut` | String(20) | **Llave del cliente en el canal** (ID de proveedor, ADR-001), no clave transversal. Formato `12.345.678-5`; un documento sin forma de RUT (pasaporte) se aísla como `EXT-<alfanumérico>` (TCH-PAR-14) |
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
| `estado` | String(20) | VIGENTE / PENDIENTE / ELIMINADA / RECHAZADA (columna ESTADO del reporte) |
| `monto` | String(20) | Monto del mandato (string) |
| `fecha_activacion` | String(20) | Fecha de activación. Desde jul-2025 el reporte ya no la trae: el dashboard usa como respaldo `fecha_primer_cobro` y luego `fecha_entrega_banco` (TCH-PAR-17, clave `activaciones_fuente` de `/tch/summary`) |
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
| `tch_clientes` | `clients` | `source="tch"`, `external_id=rut`, `social_id=rut` **solo si el verificador es válido** (TCH-PAR-14) |
| `tch_suscripciones` | `subscriptions` | `source="tch"`, `external_id=str(numero_ficha)`, `client_external_id=cliente_rut` (TCH-PAR-12), `client_social_id=cliente_rut` solo si es un RUT válido |
| `tch_transacciones` | `charges` | `source="tch"`, `external_id=dedupe_key`, `subscription_external_id=str(numero_ficha)`, `client_external_id=cliente_rut` de la ficha (TCH-PAR-12) |

**Nota:** `tch_recaudacion_mensual`, `tch_bancos`, `tch_tipos_mandato`, `tch_origenes` y `tch_centros_costo` **no se consolidan** a tablas canónicas. Son catálogos de referencia y control operativo.

### RUT e identidad (TCH-PAR-14, ADR-001)

El RUT es el `external_id` del cliente dentro del canal (`external_identities` con `source='tch'`). Solo un RUT con
dígito verificador correcto sale del canal como señal de identidad: atributo `rut` en `core_client_attributes` (lo usa
el detector de candidatos, que nunca hace merge) y `social_id` en las canónicas. Un RUT con verificador incorrecto
conserva su llave en el canal pero no se usa para cruzar; los atributos `rut` inválidos ya cargados se retiran en el
siguiente ETL Core. Código: `app/services/tch_rut.py`.

### Core (TCH-PAR-12)

`run_tch_core_etl` materializa cada cuota (`dedupe_key` = ficha|periodo real|cuota) como `core_charges` con
`period_reference` real, `due_at` (fecha de cobro o primer día del mes si viene solo del historial) y
`latest_rejection_*` (rechazo vigente, o el rechazo previo si la cuota se pagó después). El último intento es un
`core_payments` ligado por `charge_id`; `latest_rejection_payment_id` apunta a él solo si el último estado es un
rechazo. Lee `tch_transacciones` por páginas de id y solo reescribe filas cambiadas: dos corridas dan el mismo resultado.

### Trazabilidad `source_record_id` (SYNC-D-16)

Cada fila `tch_*` tiene un `source_records` con `source='tch'` y las mismas claves que la consolidación
(`client`=rut, `subscription`=ficha, `transaction`=dedupe_key); el payload solo dice la tabla de origen (sin datos
personales). Se registran en cada carga; para lo ya cargado: `scripts/etl_tch.py --backfill-source-records` (dry-run;
`--apply --confirm-database <base>` para confirmar). Idempotente, con ids estables entre recargas.

### Procesamiento en chunks

`_consolidate_tch_transactions` usa paginación de 2000 filas (OFFSET) sobre ~1,47 M filas antes de la recarga; hacerla
incremental es TCH-PAR-13. El resto de las funciones TCH cargan todo en memoria.

## Flujo de sincronización

```
Archivos Excel TCH (histórico dic-2017 a sep-2026; 30 archivos, 29 únicos)
  → scripts/etl_tch.py (CLI o carga desde administración, TCH-07)
  → tch_clientes / tch_suscripciones / tch_transacciones / tch_recaudacion_mensual / catálogos + source_records
  → core_tch_etl.py (external_identities, atributos, core_subscriptions, core_charges, core_payments)
  → channel_consolidation.py (_consolidate_tch_*)
  → clients / subscriptions / charges
```

## Hoja de ruta de carga

1. Recarga completa con la clave D13 (la ejecuta el usuario, con respaldo): [tch-reload.md](tch-reload.md). Incluye
   los `source_records` de TCH.
2. Si no se recarga: backfill de `source_records` (`--backfill-source-records`, primero en dry-run).
3. ETL Core de TCH (crea `core_charges` y liga los pagos) y consolidación de TCH.
4. Desde ahí, cada reporte mensual por la carga desde administración (rechaza contenido repetido por sha256).
5. Pendientes: TCH-PAR-08 (cartera dic-2023), TCH-PAR-11 (registro de archivos y conciliación en la UI), TCH-PAR-13
   (consolidación incremental), correr la carga fuera del proceso API (resto de TCH-PAR-16).

## Brechas y limitaciones conocidas

| ID | Tipo | Descripción |
|---|---|---|
| GAP-TCH-01 | Identidad — mitigada (TCH-PAR-14) | `UNIQUE(rut)` en `tch_clientes` se mantiene como llave del proveedor (ADR-001 lo permite dentro del canal). El RUT solo sale como señal de identidad si su verificador es válido; los documentos sin forma de RUT se aíslan (`EXT-`). Pendiente: titular de la cuenta distinto del socio (solo hay indicador). |
| GAP-TCH-02 | Datos perdidos en consolidación | `email` y `telefono` de `tch_clientes` **no se mapean** a `clients` canónicos. Se consolida con `email=NULL`, `phone_number=NULL`. |
| GAP-TCH-03 | Relación cliente-transacción — resuelta (TCH-PAR-12) | `charges.client_external_id` y `subscriptions.client_external_id` llevan la llave del cliente TCH. |
| GAP-TCH-04 | Montos como strings | `monto` en `tch_suscripciones`, `tch_transacciones` y `tch_recaudacion_mensual` son `String`. Conversión necesaria para cálculos. |
| GAP-TCH-05 | Fechas como strings | Todas las fechas son `String(20)` para tolerar datos sucios del Excel histórico. No hay validación de formato. |
| GAP-TCH-06 | Sin carga incremental | La carga TCH es batch completo desde Excel. No hay sincronización en tiempo real. |
| GAP-TCH-07 | `numero_ficha` vs `dedupe_key` | `tch_transacciones` usa `dedupe_key` como clave de idempotencia, pero su construcción depende del ETL de carga. Si cambia la lógica del ETL, pueden aparecer duplicados o huecos. |

## Clave de cargos y campos del reporte (TCH-PAR-03, 04, 09)

- `tch_transacciones.dedupe_key` = `ficha|periodo real|cuota` (D13): una fila por cuota con el ultimo estado ("el ultimo
  reporte gana"); el rechazo previo queda en `rechazo_previo`, `rechazo_previo_motivo`, `rechazo_previo_en`.
- `origen`: `cargo` (hojas CARGOS, con fecha) o `historial` (estado mensual de 12 meses, sin fecha). El historial de
  mandatos RECHAZADOS no se carga como cobro. `reporte_periodo` es el mes del reporte que trajo la fila. Hoy la
  consolidacion y el ETL Core leen ambos origenes (el historial cubre los meses sin detalle de CARGOS); el control
  oficial cuenta ambos.
- `tch_suscripciones` suma `moneda`, `estrategia`, `lugar_captacion`, `folio`, `referencia`, `personalidad`,
  `titular_distinto` (solo indicador; no se guarda el RUT ni el nombre del titular), primer cobro, aportes acumulados,
  permanencia y flags NVO / RECH MES / ELI MES. `tch_clientes.region`, y `tipo_persona` sale de la personalidad real.
- Migraciones 0047 y 0048 (solo agregan columnas). Recarga: [tch-reload.md](tch-reload.md).
