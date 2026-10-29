# Cargar los reportes de Toku (procedimiento para el usuario)

> TK-19, TK-PAR-05, TK-PAR-06 y TK-20. Contexto y reglas en [`toku.md`](toku.md). Esta guía es para quien opera la base real `crm`:
> **los agentes no ejecutan `--apply` ni migraciones sobre `crm`**.

Los reportes del Backoffice de Toku traen lo que la API no da: estado del medio de pago, fecha de alta real, suscripciones
eliminadas y motivo de rechazo. Contienen **datos personales** (la columna `ID Producto` incluye el RUT del socio): no los abra en
herramientas compartidas, no los suba al repositorio (`*.xlsx` está ignorado por git) y no pegue filas en chats o tickets.

## Qué cambia en la base y qué no

* **Migraciones: esta entrega no agrega ninguna.** Las tablas `tk_report_*`, `core_subscription_signals` y el permiso
  `toku.reports.import` ya existen desde las migraciones `20261028_0039` a `20261028_0041`. Lo único que hay que comprobar es que
  `crm` esté en ese punto o más adelante (paso 3). Las migraciones `0042` a `0049` del código son de otras tareas y se aplican
  cuando usted lo decida; no son requisito de este procedimiento.
* Las cargas solo escriben en `tk_report_*`. El ETL de Toku escribe en `core_subscriptions` (fechas y bajas) y, solo con la bandera
  encendida, en `core_subscription_signals` y en el `status` de `core_subscriptions`. No cambia KPI, dashboards ni el recuperador.

## Procedimiento, en orden

1. **Defina el secreto `TOKU_REPORT_HASH_PEPPER`** en su `.env` (una cadena larga y aleatoria; nunca se versiona ni se comparte).
   Sin él, la ruta responde `503 pepper_not_configured` y el script se detiene. Cambiarlo después invalida la correlación con los
   hashes ya guardados (habría que recargar los reportes). Reinicie el backend para que lo lea.
2. **Haga un respaldo** de `crm` (`pg_dump` no está en el `PATH`; use la ruta completa de PostgreSQL).
3. **Compruebe las migraciones** (solo lectura): `alembic current` debe mostrar `20261028_0041` o posterior. Si falta, aplíquelas usted
   (`alembic upgrade head`) y repita `scripts/maintenance/seed_roles.py` para que `admin` tenga el permiso `toku.reports.import`.
4. **Exporte los reportes del Backoffice** (formato `.xlsx`, con la ventana de fechas completa que quiera conservar):
   **Productos**, **Medios de pago**, **Intentos de pago**, **Inscripciones** y, además, **Deudas** (hoy solo existe el de
   2026-08-09; USR-09). Deudas e Intentos son los que permiten medir la racha por cuotas. Guárdelos en una carpeta fuera del repo y
   no los renombre ni los edite (la fecha de generación sale de las filas 1 a 6 del archivo). Repita cada semana (DEC-21).
5. **Pruebe la carga en seco** (no escribe nada; imprime tipo, filas válidas, omitidas, ventana y si ya se cargó):

   ```powershell
   $env:PYTHONPATH='.'
   .venv\Scripts\python.exe scripts\maintenance\import_toku_reports.py --dir "C:\ruta\a\Toku"
   ```

6. **Cargue** (una transacción por archivo; Productos se carga primero para resolver el `sub_` de Intentos y Deudas):

   ```powershell
   .venv\Scripts\python.exe scripts\maintenance\import_toku_reports.py --dir "C:\ruta\a\Toku" --apply
   ```

   También se puede subir de a un archivo con `POST /api/v1/imports/toku-reports` (solo `admin`). Un archivo ya cargado
   (mismo contenido) responde «YA CARGADO»/`409`. Un reporte más viejo que el dato guardado no lo pisa (filas «obsoletas»).
7. **Revise el efecto de las fechas y las señales en seco**:

   ```powershell
   .venv\Scripts\python.exe scripts\maintenance\toku_report_lifecycle.py --signals
   ```

   Verá cuántas suscripciones recibirían fecha de alta y de baja, cuántas bajas se crearían (se esperan unas 140 que la API no lista),
   cuántas son activas efectivas y cuántas recuperables por motivo (`blocked_card`, `expired_card`, `streak`). Solo conteos.
8. **Aplique el ETL de Core de Toku.** Las fechas y las bajas se aplican siempre que el ETL corre (el job diario con
   `SYNC_CORE_ETL_ENABLED=true`, o a mano con `scripts/maintenance/toku_report_lifecycle.py --apply`). Las **señales y el estado
   reporte > API** quedan detrás de `TOKU_REPORT_SIGNALS_ENABLED` (apagada por defecto): para poblarlas una vez sin encender la bandera
   use `... toku_report_lifecycle.py --signals --apply`; para que se recalculen en cada corrida del ETL ponga
   `TOKU_REPORT_SIGNALS_ENABLED=true` y reinicie. `TOKU_REPORT_FIRM_UNPAID_DAYS` (7 por defecto) son los días sin intento para
   considerar una cuota fallida «en firme»; confirme el valor.
9. **Verifique** (solo conteos, sin datos personales):

   ```sql
   SELECT report_type, status, count(*) FROM tk_report_files GROUP BY 1, 2;
   SELECT count(*) FILTER (WHERE started_at IS NOT NULL) AS con_alta,
          count(*) FILTER (WHERE ended_at IS NOT NULL)   AS con_baja,
          count(*) FILTER (WHERE status = 'deleted_at_source') AS bajas
   FROM core_subscriptions WHERE source = 'toku';
   SELECT lifecycle_status, is_effectively_active, is_recoverable, recoverable_reason, count(*)
   FROM core_subscription_signals GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC;
   ```

   Referencias de los reportes del 2026-10-20: 658 productos (157 eliminados), unas 178 suscripciones activas efectivas y 72
   suscripciones con racha de 3 o más cuotas (frente a 138 si se contaran intentos). Si la racha se acerca a 138 algo está contando
   intentos; avise.

## Si algo falla

* `503 pepper_not_configured` / «falta TOKU_REPORT_HASH_PEPPER»: paso 1 (reinicie el backend).
* `422 invalid_format`: el mensaje trae solo nombres de columnas; el archivo no es uno de los cinco tipos soportados (Clientes, Pagos y
  Liquidaciones aún no se leen) o no es `.xlsx`.
* `500 import_failed` con una etiqueta (`etapa:Excepcion`): la carga completa de ese archivo se revirtió; `tk_report_files` queda en
  `failed` y se puede reintentar. Envíe la etiqueta, nunca el archivo.
* `403`: la sesión no es `admin` o falta `seed_roles.py` (paso 3).
* Para deshacer las señales: apague la bandera; la tabla `core_subscription_signals` se puede vaciar sin afectar nada más (nadie la
  lee todavía). Las bajas creadas en core tienen `status = 'deleted_at_source'` y las fechas son aditivas.

## Riesgos conocidos

* El umbral de 7 días para una cuota «en firme» y la regla de precedencia (el reporte gana sin comparar con la fecha del último
  sync) son supuestos pendientes de confirmar (ver `toku.md`).
* Los reportes son una foto semanal: entre cargas, la racha y el medio de pago pueden quedar atrasados hasta 7 días.
* Los códigos 1051, 2043 y 2044 no aparecen en la hoja de 24 códigos de los reportes; se usan por el catálogo oficial de Toku (DEC-24).
