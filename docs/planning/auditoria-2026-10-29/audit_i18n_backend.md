# Auditoría i18n del backend (solo lectura) — CRM SynkmetriX

Fecha: 2026-10-29. Reglas del usuario: (1) todo lo visible, en español; (2) todo el código, en inglés.
Alcance: `app/` (128 .py, ~27.0 k líneas), `scripts/` (25, ~3.6 k), `tests/` (104, ~19.5 k; 1346 funciones `test*` por AST, 1700+ con parametrización), `alembic/` (50 migraciones), `tests_contract/`.
Método: AST con `.venv\Scripts\python.exe -I` (scripts en el scratchpad: `scan_es.py`, `scan_sub.py`, `keys_scan.py`, `detail_scan.py`, `tests_dep.py`, `testnames.py`) + revisión a ojo. Es una heurística por palabras: puede haber falsos negativos (compuestos) y falsos positivos (`roles` es inglés correcto; se descartó).

## Conclusión corta

- El código de `app/` ya es mayoritariamente inglés. El español está **concentrado** en el canal TCH (tablas `tch_*`, ruta `/tch/*`, `scripts/etl_tch.py`) y en pocos servicios (`export_queries`, `dashboard_general`, `vp_current_amount`, `recovery`, `reports`, `staging`).
- Hay **776 apariciones** de identificadores con palabras españolas (sin falsos `roles`): app 192 (137 nombres únicos, 20 archivos), scripts 132 (94 únicos, 1 archivo: `etl_tch.py`), tests 440 (254 únicos, 46 archivos), tests_contract 10, alembic 2 (migraciones, no se editan). Por tipo: variables 287, funciones/métodos 237, kwargs 168, parámetros 73, clases 6, atributos 4, módulos 1.
- Además hay ~262 de 1346 funciones de test con nombre en español (frases enteras: `test_dia_31_con_pagados_...`), que este escaneo por tokens subestima.
- La pieza de riesgo es el esquema de base de datos en español: **8 tablas `tch_*` con ~75 columnas** (de 68 tablas en total; el resto del esquema ya está en inglés).
- El contrato con el frontend tiene claves JSON en español en: `/tch/*`, `/staging/*` (parte), `/recovery/*` (CSV y algunas claves), `/reports/*` y los dos endpoints nuevos (`/dashboard/general`, `/changes/daily`).

## (A) Identificadores en español en Python

### Top 20 archivos (apariciones)

| # | Archivo | N | Cat. |
|---|---|---|---|
| 1 | scripts/etl_tch.py | 132 | a + c (hojas/columnas del Excel de TCH en strings; la variable sí se renombra) |
| 2 | tests/test_etl_tch.py | 78 | a (sigue al código) |
| 3 | app/models/tch.py | 74 | **b** |
| 4 | tests/test_export_endpoints.py | 35 | a/b (usa SQL crudo con columnas `tch_*`) |
| 5 | app/api/v1/routes/tch.py | 33 | a + c (claves JSON y URLs) |
| 6 | tests/test_staging_api.py | 27 | a |
| 7 | tests/test_billing_apply_tanda1.py | 25 | a (nombres de test) |
| 8 | tests/test_tch_par07.py | 25 | a/b |
| 9 | tests/test_dashboard_general.py | 23 | a/c |
| 10 | tests/test_tch_par03.py | 22 | a/b |
| 11 | app/api/v1/routes/staging.py | 15 | a + c (3598 líneas) |
| 12 | tests/test_dashboard_kpis.py | 15 | a |
| 13 | app/services/export_queries.py | 14 | a + c (encabezados CSV) |
| 14 | tests/test_billing_plan.py | 14 | a |
| 15 | tests/test_parity_check.py | 14 | a/b |
| 16 | app/services/dashboard_general.py | 13 | a + c (claves JSON, endpoint nuevo) |
| 17 | tests/test_status_events.py | 13 | a |
| 18 | tests/test_sync_tch_conditional.py | 13 | a/b |
| 19 | tests/test_tch_par09.py | 13 | a/b |
| 20 | tests/test_classify_rejection.py | 11 | a |

Archivos de `app/` con más casos: models/tch.py 74, routes/tch.py 33, routes/staging.py 15, services/export_queries.py 14, services/dashboard_general.py 13, routes/recovery.py 8, services/core_vp_etl.py 7 (rut/clientes), routes/export.py 5, services/billing_requests.py 5, core_tch_etl.py 4, vp_current_amount.py 4 (`pick_monto_vigente`, `load_monto_vigente`, `MontoVigenteMap`), reports.py (`pagos_mes`, `rec_mes`, ...).
Nombres más repetidos (fuera de tests): `periodo` 35, `estado` 38, `rut` 27, `numero_ficha` 20, `monto` 16, `ficha` 13, `archivo_origen` 12, `aceptadas/rechazadas_cantidad|monto` 40.

### Clasificación

**(a) Internos, renombrables sin riesgo** (no cruzan DB, API ni archivos externos):
- `scripts/etl_tch.py`: funciones `_norm_rut/_norm_monto/_norm_cuota/_norm_periodo`, `_estado_mandato`, `_estado_cargo`, `_find_estado_col`, `_transform_recaudacion_mensual`, `_transform_suscripciones`, `_transform_historial_cargos`, `_bulk_upsert_clientes`, `_load_suscripciones`, `_load_recaudacion_mensual`, `_codigo_from_motivo`, `_apply_implicit_bajas`, `_purge_future_recaudacion`, `_transform_bancos_from_tablas`, `_load_bancos_catalogo`; constantes `SHEET_RECHAZADOS_MANDATOS`, `SHEET_HISTORICO_RECAUDACION_CAN/FLUJO`, `SHEET_VIGENTES`, `_ESTADOS_MANDATO`, `_CLIENTE_DEFAULTS`, `_RAZON_BAJA_IMPLICITA`; ~35 variables `c_*` (`c_ficha`, `c_mandato`, `c_razon`, ...), `df_mandatos_rech`, `rows_mandatos_rech`, `fichas_vigentes`. Los valores de los strings (nombres de hoja y encabezado del Excel) NO cambian.
- `export_queries.py`: `_clientes_cclient/_clientes_tch`, `_cobros_cclient/_cobros_tch`, `_pagos_cclient`, `rut_key`, `_rut_key_sql`, `_rut_match`, `rut_field/rut_col`.
- `routes/tch.py`: `_serialize_cliente`, `_parse_monto`, `_recaudo_mensual_kpis`, `list_clientes/list_suscripciones`, `get_cliente/get_suscripcion` y ~25 variables locales (`tasa_rechazo`, `monto_eliminadas`, `ultimo_run`, ...).
- `routes/staging.py`: `_rut_key`, `_normalized_rut`, `_vigente`, `rut_needle`, `sin_rut_failed`, `cobrable_*`, `tch_equivalente_vigente`; `routes/recovery.py`: `_vigente`, `unique_clients_by_rut`, `clients_by_rut`; `routes/reports.py`: `pagos_mes`, `rec_mes`, `tasa`, `altas/bajas`.
- `dashboard_general.py`: `_parse_monto`, `SOCIOS_NOTA/SOCIOS_UNIDAD`, `rut_of`, `socios`, `socios_inicio`, `is_baja`, `_baja_condition_csub`, `alta_m/baja_m`.
- `core_*_etl.py` (`clientes`, `suscripciones`), `client_match_detector.py` (`_normalize_rut`, `_find_rut_matches`), `write_virtualpos.normalize_rut`, `_RUT_RE` (toku_report_import/parser, webhook_intake), `vp_current_amount.py`, `status_history.py` (`BAJA_STATES`, `bajas_acc`), `channel_consolidation.py` (`vigente`).
- Spanglish a limpiar: `suscription_date` / `suscription_url` / `total_suscription*` (typo de `subscription`; ojo: `suscription_date` puede ser nombre de campo del proveedor VirtualPOS, verificar antes), `cobrable_*`.
- `tests/`: 254 nombres únicos (variables, helpers, 262 nombres de test). Cambian con el código; cero riesgo funcional pero mucho diff.

**Decisión pendiente D-1 (RUT):** `rut` aparece 27+ veces y es una sigla chilena (documento de identidad). Hoy conviven `rut`, `social_id` y `government_id`. Recomendación: usar `tax_id` solo en identificadores internos nuevos y mantener `rut` en la UI (texto visible) y en datos del proveedor; pedir confirmación al usuario antes de renombrar `rut`.

**(b) Atributos de modelo SQLAlchemy ligados a columnas/tablas en español** (`app/models/tch.py`, 8 clases / 8 tablas / ~75 columnas):
- Clases: `TchBanco, TchTipoMandato, TchOrigen, TchCentroCosto, TchCliente, TchSuscripcion, TchTransaccion, TchRecaudacionMensual`.
- Tablas: `tch_bancos, tch_tipos_mandato, tch_origenes, tch_centros_costo, tch_clientes, tch_suscripciones, tch_transacciones, tch_recaudacion_mensual`.
- Columnas (muestra): `numero_ficha, numero_mandato, cliente_rut, banco_nombre, fecha_cargo, numero_cuota, total_cuotas, tipo_transaccion, estado, entidad_recaudadora, codigo_respuesta, razon_rechazo, archivo_origen, reporte_periodo, rechazo_previo(_motivo|_en), fecha_activacion/ingreso/entrega_banco/rechazo/eliminacion, razon_baja, aceptadas_*/rechazadas_*, nvo_mes/rech_mes/eli_mes`, etc.
- Uso: 356 líneas en 12 archivos de `app/`, 194 en 3 de `scripts/`, 159 en 16 de `tests/`, 77 líneas en 9 migraciones (no se editan), 230 en `docs/`. Hay SQL crudo con nombres de tabla/columna en `tests/test_export_endpoints.py:63-65` y menciones en docstrings de `core_tch_etl`, `channel_consolidation`, `etl_tch`, `parity_check`.
- Opciones:
  - **B1 (recomendada, fase 1, sin migración):** renombrar solo el atributo/clase Python y fijar el nombre real con el primer argumento posicional de `mapped_column`: `file_number: Mapped[int] = mapped_column("numero_ficha", Integer, ...)`; clases `TchBank`, `TchSubscription`, `TchTransaction`... conservando `__tablename__`. Riesgos: casi nulo en DB (el esquema no cambia, `alembic revision --autogenerate` debe salir vacío: se comprueba con el test de metadatos existente). Quedan dos riesgos: strings con el nombre de columna usados en `select(text(...))`, `order_by("...")`, `getattr(model, "numero_ficha")`, `.filter_by(**dict)` y SQL crudo; hay que buscarlos con grep exacto (incluye `tests/test_export_endpoints.py`). Los índices/constraints conservan sus nombres (`uq_tch_*`).
  - **B2 (fase final, opcional):** migración Alembic que renombra tablas y columnas. En PostgreSQL `ALTER TABLE ... RENAME COLUMN/TO` es solo cambio de catálogo (no reescribe filas, sin importar las 1,47 M), pero toma un `ACCESS EXCLUSIVE` breve, no renombra solos índices/constraints (hay que renombrarlos aparte si se quiere coherencia), exige desplegar código y migración a la vez (el código viejo falla contra el esquema nuevo y viceversa) y lo aplica el usuario (el handoff prohíbe a los agentes correr Alembic). Beneficio: cero asimetría nombre Python/columna. Recomendación: hacerla solo si el usuario insiste en que el esquema también esté en inglés; probar por pytest en `crm_test`, con downgrade incluido.
  - **Valores almacenados** en español (`estado` = `VIGENTE/ACEPTADA/RECHAZADA/ELIMINADA`; VirtualPOS `activa`, `pagado`) son datos del proveedor/Excel: no se migran; se encapsulan en constantes inglesas (`TchStatus.ACTIVE = "VIGENTE"`) y se traducen al mostrar. Hoy están dispersos como literales (staging.py ~48, etl_tch ~26, tch.py 16, reports.py 8, dashboard_general 8).

**(c) Contrato externo (la variable se renombra, el literal NO):**
- Hojas y encabezados del Excel de TCH en `etl_tch.py` (`"CARGOS ACEPTADOS"`, `"RECHAZADOS MANDATOS"`, `"FICHA"`, `"RAZON"`...): son del proveedor. Renombrar `c_ficha`, `SHEET_RECHAZADOS_MANDATOS` pero no sus valores.
- Reportes de Toku/VirtualPOS (`toku_report_parser`, `vp_report_parser`): ya con nombres internos en inglés salvo `medios_pago`, `intentos` como claves de dict internas (renombrables).
- Claves de los payloads de proveedor en `raw_payload` (JSONB, datos históricos): no tocar.
- Claves JSON hacia el frontend: ver (C).

**(d) Migraciones antiguas:** solo 2 coincidencias en nombres (`20261029_0047_tch_unique_cuota_key.py` nombre de archivo con "cuota"; `_SUSCRIPCION_COLUMNS` en `0048`) y 77 líneas que citan tablas `tch_*` (9 archivos: 0014, 0016, 0019, 0021, 0022b, 0023, 0025, 0031, 0047/0048). No se editan.

## (B) Texto visible que sale del backend

1. **Mensajes `detail` de HTTPException:** 236 apariciones en 24 archivos. Idioma medido por heurística: ~85 en español, ~91 en inglés, ~60 ambiguos (`str(exc)`, `_toku_blocked_detail(exc)` dinámicos). **Mezcla en el mismo archivo**: `writes.py` (99 detalles: 54 es / 26 en / 19 ?; incluso el mismo mensaje en ambos idiomas: `writes.py:170` "At least one field is required" vs `:713/:822/:978` "Al menos un campo es requerido"), `staging.py` (36: 19 en, 14 ?, 3 es), `scheduler.py` (9 es), `tch.py` (8 es), `security.py` (10, mayoría en), `admin.py` (17, 15 en), webhooks (en).
2. **Formas distintas de error:** texto libre (la mayoría); `{"code","message"}` en `changes.py:35-39`, `dashboard.py:21`, `imports.py:34`, `writes.py:938` (`INVOICE_IN_PROGRESS`); y códigos estables en `billing_changes` que el frontend ya traduce con `CODE_MESSAGES` (`frontend/src/features/billing/billingErrors.ts`, ~30 códigos + `STATUS_MESSAGES` por HTTP). `frontend/src/api.ts:10-33` muestra `detail` crudo al usuario si es string: por eso el inglés llega a pantalla.
3. **Dónde conviene `code` estable en inglés + texto en frontend** (recomendado para todo error nuevo y para estos): `writes.py` (toda la familia VirtualPOS/Toku/Payku: "VirtualPOS writes are disabled", "... rejected the update", "requires local reconciliation", "Invalid RUT"), `staging.py` ("... not found", "Invalid filter field", "Unknown staging source"), `security.py` (permiso/credenciales), `scheduler.py`, `tch.py` (importación: "reporte ya cargado", "supera el tamaño"). Esfuerzo mayor, pero es la única forma de que el español dependa de un solo lugar. Alternativa barata (fase 0 del frontend): mapa `status -> mensaje` ya existente (`STATUS_MESSAGES`) como respaldo y no mostrar `detail` en inglés.
4. **Encabezados CSV:**
   - `export_queries.py:50-72` (`ENTITY_COLUMNS`, usado por `/export/{entity}`): encabezados `canal,id_externo,estado,fecha_alta,rut,nombre,correo,telefono,direccion,id_suscripcion,estado_secundario,fecha_inicio,fecha_termino,monto,moneda,ultimo_cobro,rut_cliente,nombre_cliente,id_cobro,fecha_cobro,periodo,motivo_rechazo,id_pago,fecha_pago`. Son español en snake_case (ni etiqueta humana ni inglés). `ExportColumn(key, header)` ya separa clave y encabezado: las **claves internas** pasan a inglés (`channel, external_id, status, ...`) y el **encabezado** a etiqueta legible («Canal», «ID externo», «Fecha de cobro»). Se puede cambiar sin compatibilidad hacia atrás salvo que alguien procese el CSV con scripts.
   - `recovery.py:637-648` (`CSV_COLUMNS`, 17 encabezados mezclados: `cuenta, id_suscripcion, id_cargo, monto, fecha_rechazo, codigo_rechazo, motivo_rechazo, estado, intentos, ultimo_cobro, fecha_cancelacion, source_record_id, external_id, rut, nombre, email, telefono`): mezcla español/inglés; usa `csv.writer` propio en vez de `csv_stream`/`exporter`. Mapear a las mismas etiquetas; `source_record_id`/`external_id` se renombran a «ID de registro de origen»/«ID externo».
   - Nombres de archivo descargado: `export.py:65 _filename`, `recovery.py` (`filename=`). Revisar que estén en español o en inglés de forma consistente (es parte de lo visible).
5. **Plantilla HTML** `app/templates/reports/virtualpos.html` (294 KB, `lang="es"`): ya en español salvo el typo «Subscripción/Subscripciones» (debe ser «Suscripción»; líneas 61, 92, 99, 102) y un snapshot de datos embebido (`const D = {...}`, revisar que no contenga datos personales). `reports.py` además genera HTML inline en Python (botón «Descargar HTML» y estilos, líneas ~380-570): texto en español; las claves `ACTIVA/CANCELADA`, `estado_dist` van al JS de la plantilla (mapa `edLbl` ya traduce a «Activa/Cancelada/Fallida»).
6. **Estados y etiquetas devueltos para mostrar:** el backend mezcla (i) valores crudos del proveedor (`Paid`, `Active`, `activa`, `ACEPTADA`, `RECHAZADA`, `VIGENTE`...) y (ii) etiquetas ya traducidas (`"Consolidado"`, `"Aceptadas"`, `"Nunca Cobrado"` duplicada en `tch.py:92/97` y `staging.py:699/705`, `"Sin nombre"`, `"Sin dato"`). Para `staging.py`, `_general_transaction_status` ya normaliza a «Aceptadas/Rechazadas» a partir de ~15 sinónimos en ambos idiomas (staging.py:112-114, `recovery.py:42`, `reports.py:194/714/724`). Regla propuesta: el backend devuelve **siempre** `status_code` normalizado en inglés (`paid, rejected, active, cancelled, pending`) y conserva `provider_status` crudo; el frontend traduce («Pagado», «Rechazado», «Activa»). `Paid → Pagado` debe vivir en un solo mapa del frontend (hoy hay traducciones dispersas en 12+ archivos: `ChannelDashboardView.tsx`, `GeneralKpis.tsx`, `SchedulerPanel.tsx`...). Las etiquetas fijas de la lista (ii) mejor pasarlas a `code` (`never_charged`, `consolidated`) y que el frontend ponga el texto.
7. **Textos de estados de solicitudes de cobro** (`billing_changes.py:90`: `pendiente, aprobada, aplicando, ejecutada, rechazada, expirada, retirada, fallida`): son valores de la API en español. Si el frontend ya los consume (sí, 28 archivos con `/billing`), renombrar a `pending, approved, applying, executed, rejected, expired, withdrawn, failed` exige cambio coordinado y migración de datos (columna `status` almacenada). Se recomienda **no** hacerlo en esta fase salvo decisión explícita (riesgo medio-alto).

## (C) Claves JSON de la API en español

| Endpoint | Claves en español | ¿Lo consume el frontend? | ¿Renombrable sin compatibilidad? |
|---|---|---|---|
| `GET /api/v1/dashboard/general` (`dashboard_general.py`, `docs/data/dashboard-general.md`) | `socios_totales, socios_inicio, socios, valor, valor_mes_anterior, delta_vs_mes_anterior(_pct), acumulado_anio, crecimiento_neto, altas_sin_fecha, bajas_sin_fecha, ingreso, ingreso_total, ingreso_por_canal, canales, estado_meta, socios_totales_nota/unidad` (28 claves) | **No** (0 archivos del frontend; el frontend usa `/staging/dashboard/general`) | **Sí** (endpoint nuevo). |
| `GET /api/v1/changes/daily` (`changes.py`) | `code` ya en inglés; mensajes «source no valido», «date debe ser YYYY-MM-DD» en español | **No** | **Sí**: pasar `message` a inglés o quitarlo y dejar solo `code`. |
| `GET /api/v1/tch/summary`, `/tch/clientes`, `/tch/clientes/{rut}`, `/tch/suscripciones`, `/tch/suscripciones/{numero_ficha}`, `/tch/transacciones`, `/tch/transacciones/{id}`, `POST /tch/import-report`, `GET /tch/etl/runs` | 44 claves: `numero_ficha, numero_mandato, cliente_rut, banco_nombre, tipo_mandato, tipo_cuenta, fecha_activacion, fecha_rechazo, fecha_eliminacion, fecha_nacimiento, razon_baja, razon_rechazo, fecha_cargo, numero_cuota, total_cuotas, tipo_transaccion, archivo_origen, monto, monto_total, monto_vigentes, monto_eliminadas, tasa_rechazo_pct, recaudo_mensual, ultimo_etl, transacciones_fuente, apellido, telefono, direccion, comuna, ciudad, ...`; además `activaciones_mensuales, bajas_mensuales, transacciones_mensuales, total_vigentes`. **Rutas**: `/clientes`, `/suscripciones`, `/transacciones` y parámetros `rut, estado, banco, origen, periodo` | **Sí** (`frontend/src/features/tch/useTch.ts`, `TchContent.tsx` y 3 archivos más con `numero_ficha`, `razon_rechazo`, `fecha_cargo`, `banco_nombre`, `tasa_rechazo_pct`) | No sin cambio simultáneo del frontend. Opción: nueva versión con alias (aceptar ambos 1 sprint). |
| `GET /api/v1/staging/*` (dashboard, alertas, listados) | `canal, id_cargo, id_cliente, intentos, monto_vigente, ultimo_cobro, ultimo_estado, periodo, tipo, client_rut(inglés+sigla), rut` (51 usos) | **Sí** (`OperationalAlerts.tsx`, `GeneralClientsPanel.tsx`, `RecoveryPanel.tsx`, `types.ts`; `monto_vigente` en 7 archivos) | No sin cambio de frontend. |
| `GET /api/v1/recovery/*` | `monto_vigente`, `monto`, `estado`, `rut`, `intentos`; CSV con 17 encabezados | **Sí** (`RecoveryPanel.tsx`, `RecoveryTable.tsx`: `intentos`, `monto_vigente`); las claves del CSV no las lee el frontend | JSON: no sin frontend. CSV: sí. |
| `GET /api/v1/export/{entity}`, `/count` | Valores de `entity`: `clientes, suscripciones, cobros, pagos`; query `canal`; `canales` en la respuesta de `/count` | **Sí** (`exportMapping.ts`, `ExportButton.tsx`, tests) | No sin cambio de frontend (rutas y parámetro). |
| `GET /api/v1/reports/{scope}`, `/automatic` | `cargos_pag, cargos_rec, cuenta, estado_dist, pagos_mes, rec_mes, com_mes, recaud_prom_activa, ult_pago, alertas_resumen, total_pagado, total_clientes, meses, ...` (46) | HTML autónomo (consumido por la propia plantilla) y `AutomaticReport.tsx` para `/automatic` (usa `intentos`) | `/reports/{scope}`: sí (HTML autogenerado; cambiar plantilla y claves juntas). `/automatic`: coordinar. |
| `POST /api/v1/billing/*`, `/core/*`, `/imports/*`, `/scheduler/*`, `/admin/*`, `/etl/*`, `/writes/*` | Claves ya en inglés (salvo estados de solicitud en español, ver B.7) | n/a | n/a |

Nota: dentro de los endpoints que ya consume el frontend, las claves se renombran **solo** si se cambia `frontend/src/**/types.ts` y los componentes en el mismo paso (hay 150 archivos .ts/.tsx; los afectados por TCH son ~5, por staging ~10, por recovery ~7).

## (D) Propuesta de ejecución

### Herramientas disponibles
- En `.venv` solo hay **ruff 0.16.5**, pytest 8.4.2, pandas, openpyxl. **No hay rope, libcst, pyright ni jedi.** Ruff no renombra (sus reglas `N` solo vigilan mayúsculas/minúsculas, no el idioma). Python es 3.14.
- Recomendado (sin tocar el repo): script propio en el scratchpad que (1) recibe un mapa `antiguo -> nuevo` por módulo, (2) usa `tokenize` para reemplazar **solo tokens NAME** (no cadenas ni comentarios), (3) en un segundo paso lista con `grep -w` las cadenas que contienen el nombre viejo (SQL crudo, `getattr`, claves JSON, `order_by("...")`) y las trata a mano, (4) verifica con `ast.parse` y `ruff check app tests alembic`. Alternativa: instalar `rope`/`libcst` en un venv aparte fuera del repo (no en `.venv`) y usar `rope.refactor.rename` solo para módulos y clases; igual hay que revisar cadenas.
- Cada paso: `git diff --stat` y revisar el diff; `grep -w` del nombre viejo en `app scripts tests alembic/env.py docs frontend/src` (migraciones viejas excluidas a propósito).

### Orden de aplicación (de menor a mayor riesgo)
0. **Decisiones previas** (preguntar al usuario con alternativas y recomendación): D-1 `rut` vs `tax_id`; D-2 si se hace B2 (migración) o solo B1; D-3 estados de solicitudes de cobro (inglés vs. español); D-4 formato de errores (`code` estable).
1. Servicios internos pequeños sin contrato: `status_history.py`, `vp_current_amount.py`, `client_match_detector.py`, `write_virtualpos.py`, `toku_report_*`, `webhook_intake.py`, `core_vp_etl.py`, `core_toku_etl.py`, `core_payku_etl.py`, `channel_consolidation.py` (solo variables), `rbac.py`.
2. Endpoints **nuevos no consumidos**: `dashboard_general.py` + `routes/dashboard.py` (28 claves, renombrar claves + `docs/data/dashboard-general.md` + `tests/test_dashboard_general.py`), `routes/changes.py` (mensajes), `export_queries.py` y `routes/export.py` (claves internas del CSV a inglés, encabezados a etiquetas en español), `recovery.py` (solo CSV y variables).
3. Bloque TCH backend interno: `scripts/etl_tch.py` (132), `core_tch_etl.py`, `tch_report_registry.py`, `reports.py` y `staging.py` (solo variables/funciones). Sin tocar columnas ni claves JSON.
4. Modelo TCH con B1 (`models/tch.py`: clases + atributos con nombre de columna explícito) y todos los usos (356 + 194 + 159 líneas). Verificar que Alembic autogenerate no detecta cambios.
5. Rutas/JSON consumidos por el frontend (`routes/tch.py`, `staging.py`, `recovery.py`): cambiar claves + `frontend/src/features/**/types.ts` + tests del frontend en el mismo paso; mantener alias de lectura temporal si hay clientes externos.
6. Errores: unificar `detail` a `{code, message_en}` o solo `code` y un mapa en el frontend (`api.ts`) que traduzca; empezar por `writes.py` (99) y `staging.py` (36).
7. Tests: renombrar helpers/variables y los 262 nombres de test en español, archivo por archivo, en un commit aparte (nombres de test no afectan al código pero sí la regla del usuario).
8. (Opcional) B2: migración que renombra tablas y columnas `tch_*` (la aplica el usuario).

### Cómo probar cada paso
- Una sola sesión de pytest a la vez (todas recrean `crm_test`): `$env:PYTHONPATH='.'; .venv\Scripts\pytest.exe -q` completo tras **cada módulo**; si falla `tmp_path`, usar `--basetemp=<scratchpad>`. Antes: línea base (conteo de pasados/fallidos) para comparar.
- `ruff check app tests alembic` tras cada paso.
- Para API/CSV: `GET /openapi.json` (las rutas siguen), tests de export (`test_export_endpoints.py`, `test_export_streaming.py`), y frontend (`npm test`, `npm run build`, `npm run lint`) cuando se toque contrato.
- Test de metadatos Alembic (autogenerate vacío) tras el paso 4.
- No tocar bases ni correr Alembic; solo pytest en `crm_test`.

### Cuántos tests dependen de nombres en español
- Funciones `test*`: 1346 (por AST; 99 archivos `test_*.py`; ~1700 con parametrización).
- ~290 funciones (21 %) están en 18 archivos que importan modelos/ETL/rutas de TCH (`test_etl_tch`, `test_tch_par03/04/07/09`, `test_sync_tch_conditional`, `test_tch_import`, `test_core_etl_helpers`, `test_export_endpoints`, `test_parity_check`, `test_dashboard_*`...). Se rompen si se renombran modelos, columnas o helpers de TCH.
- 122 funciones (39 archivos) usan identificadores españoles (no genéricos) definidos en `app/` o `scripts/`.
- Unión: ~333 funciones (~25 %) cambiarían de contenido; ~262 funciones tienen **su propio nombre** en español.
- Archivos más afectados: `test_staging_api.py` (53), `test_etl_tch.py` (50 de 50), `test_core_etl_helpers.py` (44), `test_dashboard_data_integrity.py` (22), `test_billing_apply_tanda1.py` (31/32, solo nombre), `test_billing_plan.py` (19/20, solo nombre).

### Lista de trabajo por archivo (esfuerzo S/M/L; riesgo)

| Archivo | Trabajo | Esf. | Riesgo |
|---|---|---|---|
| app/services/status_history.py | `BAJA_STATES`, `bajas_acc` | S | Bajo |
| app/services/vp_current_amount.py | `pick_monto_vigente`, `load_monto_vigente`, `MontoVigenteMap` + usos en staging/recovery/tests (`test_vp_current_amount.py`) | S | Bajo |
| app/services/client_match_detector.py, write_virtualpos.py, toku_report_{import,parser}.py, webhook_intake.py, core_{vp,toku,payku}_etl.py, rbac.py | variables/funciones con `rut`, `clientes`, `suscripciones`, `_RUT_RE` (según D-1) | S | Bajo |
| app/services/channel_consolidation.py | variable `vigente` y comentarios; referencias a modelos TCH en paso 4 | S | Bajo |
| app/services/dashboard_general.py + routes/dashboard.py + docs/data/dashboard-general.md + tests | 28 claves JSON + 13 identificadores | M | Bajo (no consumido) |
| app/api/v1/routes/changes.py | mensajes `detail` a inglés/`code` | S | Bajo |
| app/services/export_queries.py + routes/export.py | funciones `_clientes_*`, `_cobros_*`; `ExportColumn` con clave inglesa y encabezado en español legible; filename | M | Medio (entidades `clientes/...` en URL consumida por frontend: dejar para paso 5) |
| app/api/v1/routes/recovery.py | CSV (17 encabezados), `_vigente`, `unique_clients_by_rut`; usar `csv_stream` | M | Medio (frontend consume `intentos`, `monto_vigente`) |
| app/api/v1/routes/reports.py (+ plantilla virtualpos.html) | claves en español de 46 usos; «Subscripción» → «Suscripción» | M | Medio (plantilla y claves van juntas) |
| scripts/etl_tch.py | 132 identificadores; mantener literales del Excel | L | Medio (1492 líneas, ETL crítico; `test_etl_tch.py` y `tch_synthetic.py` cubren) |
| app/services/core_tch_etl.py, tch_report_registry.py | variables y referencias a `TchSuscripcion/TchTransaccion` | S | Bajo |
| app/models/tch.py | B1: 8 clases + ~75 atributos con `mapped_column("nombre_real", ...)`; constantes `ORIGEN_CARGO/HISTORIAL` | L | Medio (columnas reales intactas; riesgo en strings y SQL crudo) |
| app/api/v1/routes/tch.py | 33 identificadores; claves JSON y rutas con frontend | L | Alto (contrato; 5+ archivos de frontend) |
| app/api/v1/routes/staging.py | 15 identificadores, ~48 literales de estado, `Nunca Cobrado` duplicado, `canal` en JSON | L | Alto (3598 líneas; frontend consume) |
| app/api/v1/routes/writes.py | 99 `detail` en 3 idiomas → `code` | L | Medio (tests y frontend `billingErrors`) |
| app/core/security.py, routes/admin.py, scheduler.py, auth.py | errores a `code` | M | Medio |
| tests/ (46 archivos con 440 apariciones + 262 nombres de test) | seguir al código; sin tocar fixtures de datos | L (volumen) | Bajo (no cambia lógica) |
| tests_contract/virtualpos/* | 10 nombres de test (`test_vp_c05_cargo_sobre_plan_fijo`, ...) | S | Bajo |
| alembic/versions/* | **No se editan** (50 migraciones; 77 líneas citan `tch_*`) | n/a | n/a |
| alembic/ nueva migración (opcional B2) | renombrar 8 tablas y ~75 columnas con índices/constraints | M | Alto (producción, la aplica el usuario; sin reescritura de filas) |

### Riesgos transversales
- `raw_payload` JSONB y filas `source_records` guardan claves históricas: no renombrar.
- Comentarios y docstrings en español (445 líneas con tildes en `app/`, 70 en `scripts/`, 212 en `tests/`; muchos más sin tilde): la regla 2 habla de nombres, pero conviene decidir si se traducen. Se recomienda **no** traducirlos en esta tarea (volumen alto, riesgo nulo, valor bajo) salvo petición.
- `docs/` (230 líneas con nombres TCH en 25 archivos) y `knowledge/` deben actualizarse al final de cada paso.
