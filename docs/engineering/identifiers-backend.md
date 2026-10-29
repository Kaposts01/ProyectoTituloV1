# Identificadores del backend en inglés: balance (tandas 1 a 7)

Regla del usuario: todo lo que va en el código (funciones, variables, constantes, parámetros, clases y módulos) va en inglés; lo visible
para las personas, en español. Este documento resume lo hecho en la rama `sprint-5/sync-confiable` y lo que queda. Auditoría de origen:
`docs/planning/auditoria-2026-10-29/audit_i18n_backend.md`.

## Decisiones aplicadas

| Decisión | Aplicación |
|---|---|
| D32 | La base conserva sus nombres (`tch_*` en español). Solo cambian clases y atributos del modelo TCH, con `mapped_column("nombre_real", ...)`. **Sin migración.** |
| D33 | Las claves JSON de las respuestas no cambian. Lo fijan `tests/test_api_contract_keys.py` (+ `tests/golden/*.json`) y `tests/test_api_contract_openapi.py`. |
| D34 | Solo nombres. Comentarios y docstrings en español se quedan. |
| D35 | Encabezados CSV en español legible con clave interna en inglés (`ExportColumn`); errores como `detail = {code, message}` (tanda 7). |
| D37 | `rut` se conserva como término del dominio chileno. |
| D38 | Estados guardados en español sin migrar; constantes con nombre en inglés (`STATUS_PENDING = "pendiente"`). |

## Módulos hechos

| Tanda | Módulos | Notas |
|---|---|---|
| 1 | `status_history`, `vp_current_amount`, `dashboard_general`, `core_{vp,toku,payku}_etl`, `channel_consolidation`, `export_queries`, `routes/export`, `routes/recovery` | `pick_monto_vigente` -> `pick_current_amount`, `BAJA_STATES` -> `CANCELLATION_STATES`. Export y recovery separan clave (inglés) y encabezado CSV (español). El parámetro Python `canal` pasa a `channel` pero la URL sigue aceptando `?canal=`. |
| 2 | `scripts/etl_tch.py`, `core_tch_etl` | `_norm_*`, `_transform_*`, `_load_*`, `SHEET_*`, ~80 variables `c_*` -> `col_*`, constantes de origen (`ORIGIN_CHARGE`, `ORIGIN_HISTORY`). |
| 3 | `models/tch.py` y todos sus usos | 8 clases (`TchBank`, `TchMandateType`, `TchOrigin`, `TchCostCenter`, `TchClient`, `TchSubscription`, `TchTransaction`, `TchMonthlyCollection`) y 85 atributos. Prueba de esquema: `tests/test_tch_schema_unchanged.py`. |
| 4 | `routes/tch`, `routes/staging`, `routes/reports` | Funciones y variables internas. Los parámetros de consulta de `/tch/*` (`nombre`, `estado`, `banco`, `origen`, `centro_costo`, `periodo`) siguen vigentes con `Query(alias=...)`. El parámetro de ruta `{numero_ficha}` pasa a `{file_number}` (la URL no cambia, sí el nombre del parámetro en OpenAPI). |
| 5 | `models/billing`, `billing_requests`, `billing_apply`, `billing_renewal`, `write_virtualpos`, `alerts`, `routes/billing_changes` | Ver "Constantes agregadas". |
| 6 | `tests/` (243 funciones de test y ~50 helpers/constantes/parámetros), `tests_contract/` (16) | Traducción por glosario de palabras: algunas frases quedan con redacción torpe, solo cambia el nombre. |
| 7 | `routes/writes`, `routes/staging`, `core/security`, `routes/scheduler` | 154 `detail` pasan a `{"code", "message"}`; 90 códigos documentados en `docs/data/error-codes.md`. |
| resto | `toku_report_signals`, `rejection_format` | `_Cuota` -> `_Installment`, `glosa` -> `processor_message`. |

## Constantes agregadas

- `app/models/billing.py`: `STATUS_PENDING/APPROVED/APPLYING/EXECUTED/REJECTED/EXPIRED/WITHDRAWN/FAILED/NEEDS_RECONCILIATION/NOT_EXECUTABLE`
  (estados de solicitud), `EVENT_*` (12 tipos de evento), `MANAGED_CREATED/CANCELLED/COMPENSATED/NEEDS_RECONCILIATION`
  (cobros gestionados) y `TASK_OPEN/OVERDUE/CLOSED/NOT_APPLICABLE` (tareas de renovación). Los valores guardados son los mismos
  de siempre; `tests/test_stored_status_values.py` los fija.
- `app/models/tch.py`: `ORIGIN_CHARGE = "cargo"`, `ORIGIN_HISTORY = "historial"`.
- `scripts/etl_tch.py`: `SHEET_*` (nombres de hoja del Excel de TCH), `_MANDATE_STATES`, `_CLIENT_DEFAULTS`, `_IMPLICIT_CANCELLATION_REASON`.

## Excepciones documentadas (no se renombran)

- **`rut`** como término del dominio chileno (D37). También `folio` (número de folio del documento TCH, atributo `folio`, `col_folio`).
- **Valores de proveedores y del Excel** (`VIGENTE`, `ELIMINADA`, `ACEPTADA`, `RECHAZADA`, `activa`, `pagado`...), nombres de hojas y encabezados del
  Excel de TCH, claves de `raw_payload`: son datos, no identificadores. Siguen como literales (ver "Pendiente").
- **Claves de las filas del ETL TCH** (`"numero_ficha"`, `"estado"`...) y el acceso `pg_insert(Modelo).excluded.<columna>`: se escriben con el
  nombre real de la columna (SQLAlchemy Core las resuelve por el nombre de columna). Quedan en español como cadenas/atributos de columna.
- **Claves JSON de la API** y nombres de rutas, URLs y parámetros de consulta (D33).
- **`suscription_date`** (atributo de `Subscription`): replica el campo del proveedor VirtualPOS y su columna.
- **Comentarios y docstrings** en español (D34).
- Cadenas de SQL crudo, nombres de columna `tch_*` en tests de exportación, el `Literal` de `StatusLiteral` (necesario para la validación y OpenAPI)
  y el `CheckConstraint` de estados (SQL).
- Migraciones antiguas de Alembic (no se editan).

## Pendiente y por qué

1. **Constantes para los valores de proveedor de TCH** (`"VIGENTE"`, `"ELIMINADA"`, `"ACEPTADA"`, `"RECHAZADA"`, ~100 literales en
   `staging`, `tch`, `reports`, `etl_tch`): no se hizo para no mezclar un cambio de ~100 puntos con el renombrado; es un cambio mecánico y sin riesgo
   de esquema, pero amplio. Recomendado como paso siguiente.
2. **Variables locales de tests** con nombres en español que no son nombres de test/helper (aprox. 40 identificadores sueltos). Los literales de datos
   de los tests (claves de filas de Excel sintético, valores de proveedor) no se tocan por diseño.
3. **Frontend**: `frontend/src/api.ts` (`extractErrorDetail`) hoy NO muestra un `detail` objeto `{code, message}`; usa el texto genérico del estado HTTP.
   Debe leer `detail.message` (y luego traducir por `detail.code`) para que los errores de `writes`, `staging`, `security` y `scheduler` sigan viéndose
   en español. Los 90 códigos están en `docs/data/error-codes.md`. También el frontend de exportaciones debe esperar los encabezados nuevos del CSV
   (no hay lectura de encabezados en el frontend, solo descarga).
4. **`operationId` de OpenAPI** cambia al renombrar las funciones de ruta de `/tch/*` (`list_clientes` -> `list_clients`...). No lo usa el frontend;
   la colección Postman, si referencia operationIds, habría que regenerarla.
5. `docs/` y `knowledge/` que citan nombres de clase antiguos (`docs/tasks.md`, `docs/memory/PROJECT_STATE.md`, `docs/engineering/*`): solo se actualizó
   `docs/data/tch.md`; el resto son notas históricas.

## Verificación

- `ruff check app tests alembic scripts`: limpio.
- `pytest` completo: 2043 pasan, 2 omitidos (línea base antes de empezar: 2026 pasan, 2 omitidos; +17 tests nuevos de contrato, esquema, estados y códigos).
- Comparación de claves JSON de todas las respuestas ejercitadas por la suite (74 rutas) antes y después: sin diferencias (excepto el nombre del parámetro
  de ruta en `/openapi.json`).
- Autogenerate: `tests/test_tch_schema_unchanged.py` compara la metadata con la base migrada de test y con la referencia del modelo anterior; sin diferencias
  (no se ejecutó la CLI de Alembic contra ninguna base).
