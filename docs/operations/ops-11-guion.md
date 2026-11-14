# Guion de la ventana de despliegue OPS-11 (producción, `crm`)

> Ficha d194 (aprobada). Versión 2 (2026-11-13): suma todo lo aprobado después (d209, d211, d212, d214, CRM-15A/15B,
> d196, TK-PAR-04, MET-02 y, condicionado a d215, `SYNC_CORE_ETL_ENABLED`). Fecha: a definir. **Lo ejecuta el
> usuario**, con acompañamiento por chat. Ningún agente corre Alembic, scripts con `--apply`, `DELETE` ni toca `crm`
> (handoff §2, reglas 4 y 6).
> Fuentes: `handoff.md` §2 a §7, `docs/tasks.md` §3.10; `docs/data/tch-reload.md`, `docs/data/toku-reports-load.md`,
> `docs/data/alerts.md`, `docs/operations/backups.md`; y el código de `master` (`f2e747e`) o de la rama que se indica.
> Convención: **⚠ verificar** marca lo que no se pudo confirmar en código o documentación; **«requiere integrar
> `<rama>` antes»** marca lo que no existe en `master` todavía.
> Regla de todos los pasos que escriben: **dry-run primero**, verificación por **conteos agregados** (nunca filas,
> nombres, RUT ni montos por socio) y rescate escrito antes de aplicar.

## Ramas que deben estar integradas en `master` antes de la ventana

Verificado el 2026-11-13 contra `origin/master` (`f2e747e`): ninguna de estas ramas está integrada. Las dos de TCH
tocan `scripts/etl_tch.py` y `tch-reload.md` y se combinan sin conflictos (`git merge-tree`).

| Rama | Qué aporta | Pasos que la necesitan | Si no está integrada |
|---|---|---|---|
| `fix/fechas-alta-tch-vp` (d209, TCH-PAR-21) | El ETL de TCH carga «Ingreso» en `fecha_ingreso` y actualiza `fecha_entrega_banco` | 4 | **No recargar TCH**: la recarga habría que repetirla |
| `fix/tch-recuperador-estado-monto` (CRM-15B) | Estado de la ficha con «Fecha Eliminado» y «el reporte más nuevo gana» para estado y monto | 4 | **No recargar TCH** (mismo motivo) |
| `fix/sanitize-claves-tilde` (d212) | Saneador que pliega tildes y el script `redact_raw_payload_accounts.py` | 8 (obligatoria); conviene antes del 4 para que la recarga ya entre enmascarada | Omitir el paso 8 |
| `fix/motivos-rechazo` (CRM-15A/15C) | Códigos y glosas de rechazo de VirtualPOS (PAT) y Payku en el recuperador y en el ETL Core de Payku | 6 (ETL Core de Payku y conteo de glosas), 12 | El paso 6 corre, pero sin glosas de Payku ni del recuperador; repetir 6.3 tras integrarla |
| `feat/payku-prueba-y-retiro` (CRM-14F) | Permiso `payku.wallet.withdraw` (lo crea `seed_roles.py`) y el botón «Retirar fondos» (apagado por `PAYKU_WALLET_WITHDRAW_ENABLED=false`) | 2 (verificación del permiso) | El paso 2 corre igual; el permiso se crea al repetir `seed_roles.py` cuando se integre |
| `fix/sync-ui-estado` (13B, 13D) | Pantalla con «Ejecutar todos» y estados de canal en español | 11 (opcional) | Usar el botón de `sync_all_channels` que ya está en `master` |
| `feat/s7-metricas` (MET-02) | `scripts/diagnostics/operation_metrics.py` | 12.3 (después de la ventana, d201 b) | Omitir MET-02 |

Ya en `master`: BCK-01a (`backup_db.ps1`, `restore_drill.ps1`), migración `0071`, `import_vp_reports.py`,
`import_toku_reports.py`, `toku_report_lifecycle.py`, `consolidate_baseline.py`, `parity_check.py`,
`send_test_alert.py`, nombres VP de la cartera (PR #15) y la bandera `SYNC_CORE_ETL_ENABLED`.

## Resumen y duración

| Paso | Qué | Escribe en `crm` | Duración estimada |
|---|---|---|---|
| 0 | Prerrequisitos, aviso, detener el 8000, `git pull` | No | 20 min |
| 1 | Respaldo de `crm` y simulacro (`RESPALDO_1`) | No | 25 a 35 min |
| 2 | Migración `0071` y `seed_roles.py` | Sí (liviano) | 10 min |
| 3 | Rotar `AUTH_JWT_SECRET` (USR-12) y arrancar el 8000 | No (solo `.env`) | 10 min |
| 4 | TCH: recarga completa, ETL Core, consolidación, paridad y d211; `RESPALDO_4` | Sí (pesado) | 75 a 140 min |
| 5 | Toku: pepper, reportes (d196), señales y códigos (TK-PAR-04) | Sí | 30 a 45 min |
| 6 | VirtualPOS PAT (CRM-15A) y ETL Core de VirtualPOS y Payku | Sí | 25 a 40 min |
| 7 | d214: borrar las 15 filas de prueba | Sí (15 filas) | 10 min |
| 8 | d212: enmascarar cuentas en columnas JSON; `RESPALDO_8` | Sí | 25 a 40 min |
| 9 | SMTP, destinatarios (d137, d140) y correo de prueba | No (solo `.env`) | 15 a 20 min |
| 10 | Usuarios por rol (USR-07) y plantilla D40 | Sí (usuarios) | 15 min |
| 10A | `SYNC_CORE_ETL_ENABLED=true` (**solo si se aprueba d215**) | No (solo `.env`) | 5 a 10 min |
| 11 | Primera sincronización completa y verificación | Sí | 30 a 60 min |
| 12 | Verificación final (MET-02 va después de la ventana) | No | 15 a 20 min |
| | **Total** | | **≈ 5 h 45 min (rango 5 a 7 h 30 min)** |

Ninguna duración pesada se midió en `crm` (la recarga de TCH, el enmascarado y la sincronización completa son
estimaciones): anotar los tiempos reales. **Puntos de corte seguros:** después de `RESPALDO_4` o de `RESPALDO_8` se
puede cerrar la ventana (arrancar el 8000) y seguir otro día; los pasos siguientes no dependen de que sea el mismo día.
La sincronización nocturna corre a las 02:00 y el reintento a las 04:00 (`app/scheduler/engine.py`): la ventana debe
terminar antes, o cortarse en un punto seguro.

Rescate general: sección **R** al final. Cada paso dice su rescate acotado.

## Variables de la sesión de PowerShell

Abrir **una** terminal PowerShell 7 dedicada a la ventana (no la del backend). Ninguna variable contiene secretos.

```powershell
$repo   = 'C:\Users\Usuario\Downloads\Proyectos\CRM_projectoTitulo'   # checkout principal, rama master
$rep    = 'C:\Users\Usuario\Downloads\Proyectos\CRM_reportes'          # ubicación única de reportes (d203)
$bkdir  = 'C:\Users\Usuario\Downloads\CRM_backups'                     # fuera del repo
$pgc    = 'crm_projectotitulo-postgres-1'                              # contenedor (handoff §3)
Set-Location $repo
$u = (docker compose exec -T postgres printenv POSTGRES_USER).Trim()   # nombre del usuario de la base, no es secreto
function q($sql) { docker compose exec -T postgres psql -U $u -d crm -At -v ON_ERROR_STOP=1 -c $sql }
```

`q` solo se usa para lecturas de conteos; los `DELETE` (pasos 4.6 y 7) van en bloques propios.

## 0. Prerrequisitos y chequeo previo

Hoy el 8000 corre con `--reload` desde el checkout principal, **en una ventana propia del usuario**. Con `--reload`,
un `git pull` recargaría el código en caliente con la base aún sin migrar: por eso **primero se detiene el 8000 y
después se actualiza `master`**.

| # | Comprobación | Comando | Esperado | Si no |
|---|---|---|---|---|
| 0.1 | Aviso a usuarios | Avisar que el CRM estará fuera de servicio y que **todas las sesiones se cerrarán** (paso 3) | Avisado | No empezar |
| 0.2 | Sin cargas en curso | Ninguna importación ni sincronización abierta en la pantalla del scheduler (el ETL de TCH sale con código 2 si hay una corrida activa en `etl_runs`) | — | Esperar |
| 0.3 | **Detener el 8000** | En **su ventana** (la del usuario): `Ctrl+C`. Luego, en la terminal de la ventana: `Invoke-RestMethod http://127.0.0.1:8000/health` | El proceso termina; la llamada falla con conexión rechazada | Si sigue respondiendo: `Get-NetTCPConnection -LocalPort 8000 -State Listen` para ubicar el proceso y cerrarlo en su ventana |
| 0.4 | Ramas integradas | `git fetch origin; foreach ($b in 'fix/fechas-alta-tch-vp','fix/tch-recuperador-estado-monto','fix/sanitize-claves-tilde','fix/motivos-rechazo','feat/payku-prueba-y-retiro','fix/sync-ui-estado') { git merge-base --is-ancestor "origin/$b" origin/master; "$b integrada: $($LASTEXITCODE -eq 0)" }` | `True` en las que se integraron (tabla de dependencias) | Seguir la columna «Si no está integrada» |
| 0.5 | `master` al día | `git status -sb` y `git pull --ff-only` | `## master...origin/master` sin `ahead`/`behind`; solo `??` ajenos | Abortar |
| 0.6 | Scripts presentes | `Test-Path .\scripts\maintenance\backup_db.ps1, .\scripts\maintenance\redact_raw_payload_accounts.py` | `True` y `True` (el segundo solo con `fix/sanitize-claves-tilde`) | — |
| 0.7 | Lanzadores del venv | `.venv\Scripts\alembic.exe --help \| Select-Object -First 1; .venv\Scripts\uvicorn.exe --version` | Responden sin «Fatal error in launcher» | Usar `.venv\Scripts\python.exe -m alembic` / `-m uvicorn` |
| 0.8 | Docker y PostgreSQL | `docker compose ps` | `postgres` en `running (healthy)`, puerto 5433 | `docker compose up -d` |
| 0.9 | Disco | `Get-PSDrive C \| Select-Object Used,Free` | Libre ≥ 15 GB (tres respaldos de ~0,5 GB y la recarga de TCH) | Liberar o abortar |
| 0.10 | Reportes | `(Get-ChildItem "$rep\TCH" -Filter *.xlsx).Count; (Get-ChildItem "$rep\VirtualPOS" -Filter *PAT-*.csv).Count; (Get-ChildItem "$rep\VirtualPOS\cargados\2026-11" -Filter *PAT-*.csv).Count; (Get-ChildItem "$rep\Toku" -Filter *.xlsx).Count` | Conteos del 2026-11-13: TCH 30 a 31 `.xlsx` (31 entradas en la carpeta), VirtualPOS 78 (42 Transacciones y 36 Suscriptores), `cargados\2026-11` 7, Toku 16 | Confirmar el juego con el usuario |
| 0.11 | Sandbox 8001 | `Invoke-RestMethod http://127.0.0.1:8001/health` (solo mirar) | `status: ok` | Ignorar; no es parte de la ventana |

No se instala nada en el `.venv` (es de producción): ninguna rama de la tabla agrega dependencias de ejecución
(`feat/s7-metricas` solo agrega `pytest-cov`, que la ventana no usa). El front 5173 puede seguir arriba; si es el
servidor de desarrollo de Vite toma el código nuevo solo.

## 1. Respaldo de `crm` y simulacro (BCK-01a, ya en `master`)

Scripts: `scripts/maintenance/backup_db.ps1` (`-Database`, `-Destination`, `-RetentionDays`, `-ExternalCopyPath`,
`-AlertOnFailure`, `-ProjectDir`) y `scripts/maintenance/restore_drill.ps1` (`-DumpFile`, `-SourceDatabase`,
`-TargetDatabase`, `-SkipCompare`, `-ProjectDir`). Política de ejecución `RemoteSigned`: no hace falta `Bypass`; si
apareciera «no está firmado digitalmente», usar `pwsh -NoProfile -ExecutionPolicy Bypass -File <script> ...` (solo ese
proceso). No usar `Set-ExecutionPolicy` ni `Unblock-File`.

```powershell
.\scripts\maintenance\backup_db.ps1 -Database crm -Destination $bkdir
# con el disco externo conectado, agregar: -ExternalCopyPath E:\CRM_backups
$dump = (Get-ChildItem $bkdir -Filter 'crm_*.dump' | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
Measure-Command { .\scripts\maintenance\restore_drill.ps1 -DumpFile $dump -SourceDatabase crm } | Select-Object TotalMinutes
q "select version_num from alembic_version"
```

Esperado: `... [INFO] OK crm_YYYYMMDD_HHmm.dump (NNN,N MB, NNN entradas en el TOC, NN s).` y código `0`
(`$LASTEXITCODE`); el simulacro termina en `RESULTADO: OK (N tablas, M filas en origen y restaurada).`, código `0`;
revisión `20261103_0068`. Anotar los minutos como **RTO** y `RESPALDO_1 = $dump`.

**Copia fuera del equipo (d156):** disco externo y, si se sube a la nube, solo cifrada con `encrypt_backup.ps1`
(`docs/operations/backups.md`, «Cifrado para la nube»; la frase con `Read-Host`, nunca en el chat). Puede hacerse al
cierre.

**Seguir / abortar:** seguir solo con código 0 en ambos y conteos iguales. Si algo falla: abortar (aún no cambió nada),
arrancar el 8000 como estaba (paso 3.3 sin rotar) y revisar en el chat.

**Rescate:** no aplica (solo lectura sobre `crm`).

## 2. Migración `0071` y `seed_roles.py`

### 2.1 Fijar el ambiente ANTES de importar `settings` (handoff §2, regla 3)

`alembic/env.py` lee `settings.database_url` al importar y `app/core/config.py` da prioridad a las variables de
proceso sobre el `.env`. En la terminal de la ventana:

```powershell
Remove-Item Env:DATABASE_URL, Env:SANDBOX_DATABASE_URL, Env:CRM_DOTENV_PATH, Env:ALEMBIC_ALLOW_DOWNGRADE -ErrorAction SilentlyContinue
$env:APP_ENV    = 'production'
$env:PYTHONPATH = '.'
.venv\Scripts\python.exe -c "from app.core.config import settings; from sqlalchemy.engine import make_url; print(settings.env_mode, make_url(settings.database_url).database)"
```

Esperado: `production crm`. **Cualquier otra cosa: abortar.** Todos los scripts de Python de los pasos 2 a 11 se
corren en esta terminal (repetir 2.1 si se abre otra).

### 2.2 Migración

```powershell
.venv\Scripts\alembic.exe current
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\alembic.exe current
```

Esperado: antes `20261103_0068`; `heads` una sola línea `20261104_0071 (head)`; `Running upgrade 20261103_0068 ->
20261104_0071, ...`; después `20261104_0071 (head)`. La `0071` solo inserta `payku.reports.import` y lo asigna a
`admin`. Si `heads` muestra otra cabeza (alguna rama integrada trajo migración): **abortar y revisar en el chat**
(ninguna rama de la tabla trae migración, verificado el 2026-11-13).

### 2.3 Roles y permisos

```powershell
.venv\Scripts\python.exe scripts\maintenance\seed_roles.py
q "select code from permissions where code in ('payku.reports.import','payku.wallet.withdraw') order by 1"
q "select r.name, count(*) from role_permissions rp join roles r on r.id = rp.role_id join permissions p on p.id = rp.permission_id where p.code in ('payku.reports.import','payku.wallet.withdraw') group by r.name order by 1"
```

`seed_roles.py` llama a `seed_default_roles`, que primero corre `seed_permissions` (`app/services/rbac.py`): crea
todo permiso de `PERMISSIONS` que falte y le da **todos** a `admin`. Con `feat/payku-prueba-y-retiro` integrada, eso
crea `payku.wallet.withdraw` (no termina en `.view`, así que `soporte` y `ejecutivo` no lo reciben).

Esperado: `Ambiente: production`, `Rol soporte: N permisos`, `Rol ejecutivo: M permisos` (N ≥ 36, M ≥ 35); las dos
líneas de permisos (o solo `payku.reports.import` si la rama de Payku no está); en roles, solo `admin|2` (o `admin|1`).
El botón de retiro queda apagado: **no** encender `PAYKU_WALLET_WITHDRAW_ENABLED` en esta ventana.

**Rescate:** **no usar `alembic downgrade`** (bloqueado en `crm` por `app/db/migration_guard.py`). Si `upgrade` falla,
Alembic revierte su transacción: comprobar `current`; si sigue en `0068`, abortar. Estado inconsistente: sección R con
`RESPALDO_1`.

## 3. Rotar `AUTH_JWT_SECRET` (USR-12) y arrancar el 8000

`app/core/security.py` firma las sesiones con `settings.auth_jwt_secret` (≥ 32 caracteres, HS256): al cambiarlo, toda
cookie anterior deja de valer. `SANDBOX_AUTH_JWT_SECRET` debe ser distinta (SEC-03); un secreto aleatorio nuevo lo
cumple. El 8001 no se reinicia.

### 3.1 Sesión vieja

Antes de rotar, dejar una pestaña con la sesión de producción (5173) abierta: conserva la cookie vieja para 3.4.

### 3.2 Copia del `.env` y rotación (no imprime el secreto)

```powershell
Copy-Item "$repo\.env" "$bkdir\env_pre_ops11.bak"     # fuera del repo; se borra al cierre
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$nuevo = -join ($bytes | ForEach-Object { $_.ToString('x2') })
$lineas = Get-Content "$repo\.env"
$n = @($lineas | Where-Object { $_ -match '^AUTH_JWT_SECRET=' }).Count
if ($n -ne 1) { Write-Host "ABORTAR: hay $n lineas AUTH_JWT_SECRET" } else {
  $lineas = $lineas | ForEach-Object { if ($_ -match '^AUTH_JWT_SECRET=') { "AUTH_JWT_SECRET=$nuevo" } else { $_ } }
  Set-Content -Path "$repo\.env" -Value $lineas -Encoding utf8NoBOM
  Write-Host "AUTH_JWT_SECRET rotado (largo $($nuevo.Length))"
}
Remove-Variable nuevo, bytes, lineas
```

Esperado: `AUTH_JWT_SECRET rotado (largo 96)`. Nunca imprimir ni pegar el valor.

### 3.3 Arrancar el 8000 (en la ventana propia del usuario)

En la **misma ventana donde corría** (no en la terminal de la ventana, que tiene `APP_ENV` fijado):

```powershell
Set-Location 'C:\Users\Usuario\Downloads\Proyectos\CRM_projectoTitulo'
Remove-Item Env:APP_ENV, Env:DATABASE_URL, Env:SANDBOX_DATABASE_URL -ErrorAction SilentlyContinue
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

(Si el lanzador falla: `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`.)
Esperar «Application startup complete». `--reload` vigila el código, **no el `.env`**: cada cambio posterior del `.env`
(pasos 5.1, 9, 10A) exige `Ctrl+C` en esa ventana y volver a lanzar este comando. A esto se le llama «reiniciar el
8000» en el resto del guion.

### 3.4 Verificación

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/heartbeat | Select-Object status, environment, database
```

Esperado: `status: ok`; heartbeat `ok` o `degraded` (nunca 503) con base `crm`. En la pestaña vieja: refrescar → pide
iniciar sesión (401 `invalid_or_expired_session`); el login nuevo entra.

**Rescate:** `Copy-Item "$bkdir\env_pre_ops11.bak" "$repo\.env" -Force` y reiniciar el 8000. No toca la base.

## 4. TCH: recarga completa (d209, CRM-15B), consolidación, paridad y d211

> **Requiere integrar `fix/fechas-alta-tch-vp` y `fix/tch-recuperador-estado-monto` antes.** Sin las dos, no hacer
> este paso (la recarga habría que repetirla). Conviene también `fix/sanitize-claves-tilde` (paso 8).

Procedimiento: `docs/data/tch-reload.md`. Script `scripts/etl_tch.py` (banderas en `_build_parser`: `--folder`,
`--mode full`, `--dry-run`, `--apply`, `--confirm-database`, `--exclude-months`, `--tolerance-month`,
`--tolerance-total`, `--backfill-source-records`). La recarga borra y reconstruye todo `tch_*` en una transacción y
concilia contra `tch_recaudacion_mensual` antes de confirmar. No hace falta migración (la columna `fecha_ingreso` ya
existe; el mes del reporte de CRM-15B va en el payload).

Anotar antes los conteos de referencia:

```powershell
q "select count(*) total, count(*) filter (where fecha_ingreso is not null) con_ingreso, count(*) filter (where monto is null) sin_monto from tch_suscripciones"
q "select count(*) filter (where amount is null) sin_monto, count(*) filter (where status in ('VIGENTE','PENDIENTE') and ended_at is not null) activa_con_baja from core_subscriptions where source='tch'"
```

(Diagnóstico del 2026-11-13: `monto` NULL en las 29.295 fichas y `fecha_ingreso` vacía en todas.)

```powershell
$tch  = "$rep\TCH"
$excl = '2023-01,2023-02,2023-03,2023-04,2023-05,2023-06,2023-07,2023-08,2023-09,2023-10,2023-11,2023-12'
```

### 4.1 Dry-run (reconstruye y hace ROLLBACK)

```powershell
Measure-Command { .venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder $tch --exclude-months $excl | Out-Host } | Select-Object TotalMinutes
```

Esperado: `Modo full: N archivos a procesar`, la tabla por mes (`ok`, `excluido` para 2023 o `FALLA`), `Fichas
VIGENTES resultantes: ~8.401` y `Dry-run terminado: nada se confirmo (ROLLBACK). Conciliacion OK`. Umbrales: 0,5 % por
mes y 0,1 % total. **Si hay `FALLA` o `CON DIFERENCIAS`: no aplicar**; pegar en el chat solo la tabla de meses y
conteos. Código 2 = otra corrida activa.

### 4.2 Apply

```powershell
.venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder $tch --exclude-months $excl --apply --confirm-database crm
```

Esperado: la misma tabla y `Recarga CONFIRMADA. Total procesados: N`. Si no cuadra: `Conciliacion fuera de umbral;
ROLLBACK, la base quedo intacta`, código `3`.

### 4.3 ETL Core de TCH (`run_tch_core_etl`)

No hay CLI ni la noche lo corre (`_CORE_ETL_RUNNERS` de `sync_all.py` excluye TCH). La línea siguiente reproduce
`_run_core_etl_background` de `app/api/v1/routes/etl.py` (`fn(db)` y `db.commit()`; para TCH no hay marca de
frescura), sin la fila de `etl_runs` ni el lock: correrla sin otras corridas activas.

```powershell
.venv\Scripts\python.exe -c "from app.db.session import SessionLocal; from app.services.core_tch_etl import run_tch_core_etl; db = SessionLocal(); r = run_tch_core_etl(db); db.commit(); db.close(); print(r)"
```

Esperado: un diccionario de conteos (`clients_created`, `subscriptions_upserted`, `charges_inserted`, pagos...).
Alternativa equivalente con sesión de administrador: `POST /api/v1/etl/core/tch` (permiso `etl.run` y CSRF).

### 4.4 Consolidación `consolidate_baseline --source tch`

```powershell
.venv\Scripts\python.exe scripts\maintenance\consolidate_baseline.py --source tch
.venv\Scripts\python.exe scripts\maintenance\consolidate_baseline.py --source tch --apply --confirm-database crm
```

`--confirm-database` debe coincidir con `current_database()` (si no, código 2). Consolida con `baseline=True`: la
recarga no cuenta como novedad del día. Esperado: el primero solo muestra base y conteos; el segundo, conteos finales.

### 4.5 Paridad (solo lectura) y conteos

```powershell
.venv\Scripts\python.exe scripts\diagnostics\parity_check.py --channel tch --read-only
q "select count(*) total, count(*) filter (where periodo is null) sin_periodo from tch_transacciones"
q "select count(*) total, count(*) filter (where fecha_ingreso is not null) con_ingreso, count(*) filter (where monto is null) sin_monto from tch_suscripciones"
q "select count(*) filter (where amount is null) sin_monto, count(*) filter (where status in ('VIGENTE','PENDIENTE') and ended_at is not null) activa_con_baja from core_subscriptions where source='tch'"
```

`--read-only` es obligatorio fuera de `_test` (`readonly_guard.py`). Esperado: `transaction` y `control_mensual`
coinciden mes a mes salvo 2023; `tch_transacciones` cercano a 1,0 M y `sin_periodo = 0`; `con_ingreso` muy por encima
de 0 y `sin_monto` cercano a 0 en `tch_suscripciones`; en `core_subscriptions`, `sin_monto` cercano a 0 y
`activa_con_baja = 0` (verificación de CRM-15B en `tch-reload.md`).

### 4.6 d211: borrar las filas en 0 de `tch_recaudacion_mensual` (2026-10 a 2027-12)

Va **después** de la paridad (que compara contra este control) y de la recarga (que lo reconstruye). Columnas
(`app/models/tch.py`, `TchMonthlyCollection`): `periodo` (`AAAA-MM`), `aceptadas_cantidad`, `aceptadas_monto`
(texto), `rechazadas_cantidad`, `rechazadas_monto` (texto). Las filas son agregados mensuales: no hay datos personales.

Conteo antes (anotar `N0` = filas en 0 y `NT` = total de la tabla):

```powershell
q "select periodo, aceptadas_cantidad, rechazadas_cantidad, aceptadas_monto, rechazadas_monto from tch_recaudacion_mensual where periodo between '2026-10' and '2027-12' order by 1"
q "select count(*) from tch_recaudacion_mensual"
```

Revisar que los montos de las filas a borrar se lean como `0` (si aparece un formato raro, p. ej. `$0` o vacío,
**parar y revisar en el chat**: la conversión de abajo fallaría y no borraría nada). Luego, en una sesión interactiva
de `psql` (sin `-T`):

```powershell
docker compose exec postgres psql -U $u -d crm -v ON_ERROR_STOP=1
```

```sql
BEGIN;
DELETE FROM tch_recaudacion_mensual
 WHERE periodo BETWEEN '2026-10' AND '2027-12'
   AND aceptadas_cantidad = 0 AND rechazadas_cantidad = 0
   AND aceptadas_monto::numeric = 0 AND rechazadas_monto::numeric = 0;
-- psql imprime DELETE n: debe ser igual a N0
SELECT count(*) FROM tch_recaudacion_mensual WHERE periodo BETWEEN '2026-10' AND '2027-12'
   AND aceptadas_cantidad = 0 AND rechazadas_cantidad = 0;   -- debe dar 0
SELECT count(*) FROM tch_recaudacion_mensual;                -- debe dar NT - N0
COMMIT;   -- solo si los tres números cuadran; si no: ROLLBACK;
\q
```

Conteo después: repetir las dos consultas `q` de arriba (sin filas en 0 en el rango; total `NT - N0`).
Nota: una recarga completa futura de TCH vuelve a crear estas filas si los Excel las traen; repetir 4.6 entonces.

**Rescate del paso 4:** si 4.3 o 4.4 fallan con 4.2 confirmado, repetirlos (son idempotentes). Si la recarga
confirmada resultó mala: sección R con `RESPALDO_1` y repetir 2 y 3. 4.6 mal aplicado (y ya confirmado): sección R con
`RESPALDO_1` o reinsertar las filas desde la tabla anotada en el conteo antes.

**`RESPALDO_4`** (obligatorio): repetir el respaldo del paso 1 sin simulacro y anotarlo. Punto de corte seguro.

## 5. Toku: pepper, reportes (d196), señales y códigos (TK-PAR-04)

Procedimiento: `docs/data/toku-reports-load.md`. Las tablas `tk_report_*` de `crm` están vacías (handoff §4).

### 5.1 `TOKU_REPORT_HASH_PEPPER` (lo define el usuario)

El usuario agrega a mano la línea `TOKU_REPORT_HASH_PEPPER=<valor>` en el `.env` (`notepad "$repo\.env"`), con un
valor largo aleatorio que **guarda en su gestor de contraseñas**; nunca va al chat. Cambiarlo después invalida los
hashes guardados. Comprobación sin mostrar el valor:

```powershell
@(Get-Content "$repo\.env" | Where-Object { $_ -match '^TOKU_REPORT_HASH_PEPPER=.{32,}' }).Count
```

Esperado: `1`. Reiniciar el 8000 (paso 3.3) para que la ruta `/api/v1/imports/toku-reports` lo lea.

### 5.2 Reportes: la generación más reciente de `CRM_reportes\Toku` (d196)

`import_toku_reports.py` (banderas `--dir`, archivos sueltos y `--apply`) toma con `--dir` todos los `*.xlsx` de la
carpeta e informa y omite los de tipo no soportado; los `.csv` de la carpeta no los toma. Contenido al 2026-11-13: 14
`Toku_*.xlsx` del 2026-10-20 y 2 `subscription_report_20261113_*.xlsx` del 2026-11-13.
**⚠ verificar en el dry-run** qué tipo detecta en cada archivo: si un mismo tipo aparece en las dos generaciones, cargar
solo la del 2026-11-13 de ese tipo (pasar los archivos sueltos en vez de `--dir`), porque cargar uno viejo sobre uno
nuevo deja filas «obsoletas».

```powershell
$toku = "$rep\Toku"
.venv\Scripts\python.exe scripts\maintenance\import_toku_reports.py --dir $toku
.venv\Scripts\python.exe scripts\maintenance\import_toku_reports.py --dir $toku --apply
q "select report_type, status, count(*) from tk_report_files group by 1, 2 order by 1, 2"
```

Esperado (dry-run): `Ambiente: production | modo: DRY-RUN (solo lectura) | archivos: N` y una línea por archivo con
tipo, filas válidas y omitidas; seguir si no hay `ERROR`. El `--apply` carga en `LOAD_ORDER` (productos primero).
`pepper_not_configured` → volver a 5.1. Después, `tk_report_files` con un archivo por tipo cargado.

### 5.3 Señales y fechas (`toku_report_lifecycle --signals`, TK-PAR-04 / TK-20)

```powershell
.venv\Scripts\python.exe scripts\maintenance\toku_report_lifecycle.py --signals
.venv\Scripts\python.exe scripts\maintenance\toku_report_lifecycle.py --signals --apply
```

Esperado del dry-run (solo conteos): bajas a crear ~140, activas efectivas ~178, racha de 3 o más cuotas ~72 (si se
acerca a 138 está contando intentos: **abortar**). El `--apply` solo si cuadra.

### 5.4 Códigos de rechazo (TK-PAR-04 / RJ-11)

```powershell
.venv\Scripts\python.exe scripts\maintenance\project_toku_rejections.py
.venv\Scripts\python.exe scripts\maintenance\project_toku_rejections.py --apply
.venv\Scripts\python.exe scripts\maintenance\project_toku_rejections.py
```

Esperado: dry-run con `codes_from_report_by_*` > 0 (referencia: hasta 5.412 códigos vacíos); la última corrida con
`charges_updated = 0` (idempotente).

```powershell
q "select lifecycle_status, is_effectively_active, is_recoverable, count(*) from core_subscription_signals group by 1, 2, 3 order by 4 desc"
```

No encender `TOKU_REPORT_SIGNALS_ENABLED` ni `TOKU_MATERIALIZE_FAILED_PAYMENTS` (handoff §6, riesgo 8).

**Rescate:** sección R con `RESPALDO_4`. El pepper puede quedar en el `.env`.

## 6. VirtualPOS PAT (CRM-15A) y ETL Core de VirtualPOS y Payku

`import_vp_reports.py` está en `master` (banderas: archivos sueltos, `--dir` **una sola carpeta, no recursiva**, y
`--apply`; toma `TransaccionesPAT-*.csv` y `SuscriptoresPAT-*.csv`). Cada archivo es una transacción, un `sha256`
repetido se omite y un reporte más viejo nunca pisa a uno más nuevo; el `--apply` corre `reconcile` una vez al final
(glosas `report_pat` y vínculo pago→cobro). Las glosas de Payku y su uso en el recuperador **requieren integrar
`fix/motivos-rechazo` antes** (toca `core_payku_etl.py`, `recovery_payku.py` y `routes/recovery.py`).

### 6.1 Conteo antes

```powershell
q "select source, count(*) total, count(*) filter (where rejection_code is not null) con_codigo, count(*) filter (where coalesce(rejection_reason,'') <> '') con_glosa from core_payments where source like 'virtualpos%' or source = 'payku' group by 1 order by 1"
q "select source, count(*) total, count(*) filter (where coalesce(rejection_reason,'') <> '') con_glosa from payments where source like 'virtualpos%' or source = 'payku' group by 1 order by 1"
```

### 6.2 Carga de los reportes PAT (dos carpetas, dry-run y apply)

```powershell
$vp  = "$rep\VirtualPOS"
$vpn = "$rep\VirtualPOS\cargados\2026-11"
.venv\Scripts\python.exe scripts\maintenance\import_vp_reports.py --dir $vp
.venv\Scripts\python.exe scripts\maintenance\import_vp_reports.py --dir $vpn
.venv\Scripts\python.exe scripts\maintenance\import_vp_reports.py --dir $vp --apply
.venv\Scripts\python.exe scripts\maintenance\import_vp_reports.py --dir $vpn --apply
```

Esperado (dry-run): por archivo, tipo, filas, omitidas y si ya estaba cargado; seguir si no hay errores de formato.
Con `--apply`, archivos cargados y omitidos por repetidos, y el resumen de `reconcile`.

### 6.3 ETL Core de VirtualPOS y Payku

Mismo cuerpo que la ruta `POST /api/v1/etl/core/virtualpos` y `/payku` (`_run_core_etl_background`: corre, confirma y
registra la marca de frescura `core_etl_mark`), sin la fila de `etl_runs`; correr sin otras corridas activas:

```powershell
.venv\Scripts\python.exe -c "from app.db.session import SessionLocal; from app.services import core_etl_mark; from app.services.core_vp_etl import run_vp_core_etl; db = SessionLocal(); r = run_vp_core_etl(db); db.commit(); core_etl_mark.record(db, 'virtualpos', r); db.commit(); db.close(); print(r)"
.venv\Scripts\python.exe -c "from app.db.session import SessionLocal; from app.services import core_etl_mark; from app.services.core_payku_etl import run_payku_core_etl; db = SessionLocal(); r = run_payku_core_etl(db); db.commit(); core_etl_mark.record(db, 'payku', r); db.commit(); db.close(); print(r)"
```

Alternativa con sesión de administrador: `POST /api/v1/etl/core/virtualpos` y luego `/payku` (permiso `etl.run` y
CSRF; responden con `run_id` y corren en segundo plano). Son idempotentes.

### 6.4 Conteo después

Repetir las dos consultas de 6.1. Esperado: `con_codigo` y `con_glosa` de `virtualpos1`/`virtualpos2` **suben** respecto
de 6.1; los de `payku` suben solo con `fix/motivos-rechazo` integrada. Anotar los números (van a la verificación 12).

**Rescate:** las cargas son idempotentes por `sha256` y no pisan reportes más nuevos; si dejaron datos malos: sección
R con `RESPALDO_4` y repetir 5 y 6.

## 7. d214: borrar las 15 filas de prueba de `virtualpos1`

Filas creadas por una prueba el 2026-10-26 (5 en `charges`, 5 en `subscriptions`, 5 en `clients`). El `WHERE` es el
aprobado en d214, sin cambios.

### 7.1 Conteo antes (debe dar `5|5|5`)

```powershell
q "select (select count(*) from charges WHERE source='virtualpos1' AND external_id ~ '^ch-[0-9a-f]{10}$' AND subscription_external_id ~ '^sub-[0-9a-f]{10}$' AND charge_date='2099-07-01' AND amount='1500' AND status='rechazado' AND created_at >= '2026-10-26 15:41:00+00' AND created_at < '2026-10-26 16:00:00+00'), (select count(*) from subscriptions WHERE source='virtualpos1' AND external_id ~ '^sub-[0-9a-f]{10}$' AND client_external_id ~ '^cl-[0-9a-f]{10}$' AND status='activa' AND created_at >= '2026-10-26 15:41:00+00' AND created_at < '2026-10-26 16:00:00+00'), (select count(*) from clients WHERE source='virtualpos1' AND external_id ~ '^cl-[0-9a-f]{10}$' AND social_id='11111111-1' AND email LIKE 'ana%@example.test' AND created_at >= '2026-10-26 15:41:00+00' AND created_at < '2026-10-26 16:00:00+00')"
```

Si no da `5|5|5`: **no borrar**; revisar en el chat.

### 7.2 Borrado en una transacción que verifica 5 por tabla

Un bloque `DO` es atómico: si algún conteo no es 5, `RAISE EXCEPTION` deshace los tres `DELETE`.

```powershell
$d214 = @'
DO $d214$
DECLARE n_ch int; n_sub int; n_cl int;
BEGIN
  DELETE FROM charges WHERE source='virtualpos1' AND external_id ~ '^ch-[0-9a-f]{10}$' AND subscription_external_id ~ '^sub-[0-9a-f]{10}$' AND charge_date='2099-07-01' AND amount='1500' AND status='rechazado' AND created_at >= '2026-10-26 15:41:00+00' AND created_at < '2026-10-26 16:00:00+00';
  GET DIAGNOSTICS n_ch = ROW_COUNT;
  DELETE FROM subscriptions WHERE source='virtualpos1' AND external_id ~ '^sub-[0-9a-f]{10}$' AND client_external_id ~ '^cl-[0-9a-f]{10}$' AND status='activa' AND created_at >= '2026-10-26 15:41:00+00' AND created_at < '2026-10-26 16:00:00+00';
  GET DIAGNOSTICS n_sub = ROW_COUNT;
  DELETE FROM clients WHERE source='virtualpos1' AND external_id ~ '^cl-[0-9a-f]{10}$' AND social_id='11111111-1' AND email LIKE 'ana%@example.test' AND created_at >= '2026-10-26 15:41:00+00' AND created_at < '2026-10-26 16:00:00+00';
  GET DIAGNOSTICS n_cl = ROW_COUNT;
  IF n_ch <> 5 OR n_sub <> 5 OR n_cl <> 5 THEN
    RAISE EXCEPTION 'd214: borradas %/%/% (se esperaban 5/5/5); ROLLBACK', n_ch, n_sub, n_cl;
  END IF;
  RAISE NOTICE 'd214: borradas 5/5/5';
END
$d214$;
'@
$d214 | docker compose exec -T postgres psql -U $u -d crm -v ON_ERROR_STOP=1
```

Esperado: `NOTICE:  d214: borradas 5/5/5` y `DO`. Un `ERROR` (conteo distinto o clave foránea) deja todo como estaba.
Forma manual equivalente (sesión interactiva, la de d214): `BEGIN;` los tres `DELETE`, revisar que `psql` imprima
`DELETE 5` tres veces y luego `COMMIT;` o `ROLLBACK;`.

### 7.3 Conteo después

Repetir 7.1: debe dar `0|0|0`. Se vuelve a mirar después de la sincronización (paso 12): si la consolidación las
recreara, reportarlo (no repetir el borrado sin revisar).

**Rescate:** sección R con `RESPALDO_4` (repite 5 y 6), o reinsertar desde `crm_restore_test` si se restauró ahí.

## 8. d212: enmascarar cuentas guardadas en columnas JSON

> **Requiere integrar `fix/sanitize-claves-tilde` antes** (el script `redact_raw_payload_accounts.py` no está en
> `master`).

Recorre todas las columnas `json`/`jsonb` de `public` y reemplaza por `••••` + 4 últimos dígitos todo valor de clave de
número de cuenta con más de 4 dígitos. Por defecto es dry-run (solo conteos por `tabla.columna` y ROLLBACK); `--apply`
exige `--confirm-database` y va en una sola transacción. No toca `tch_suscripciones.numero_cuenta` (d199). Va después
de todas las cargas (4 a 6) para cubrir lo que hayan escrito.

```powershell
Measure-Command { .venv\Scripts\python.exe scripts\maintenance\redact_raw_payload_accounts.py | Out-Host } | Select-Object TotalMinutes
.venv\Scripts\python.exe scripts\maintenance\redact_raw_payload_accounts.py --apply --confirm-database crm
.venv\Scripts\python.exe scripts\maintenance\redact_raw_payload_accounts.py
```

Esperado: `DRY-RUN (sin cambios) base=crm`, una línea `tabla.columna: filas=N valores=M` por columna afectada y
`total: filas=... valores=...`; el `--apply` con `APPLY base=crm` y los mismos totales; la tercera corrida (dry-run)
con `total: filas=0 valores=0`. Si el `--apply` falla, la transacción se revierte.

**Rescate:** el enmascarado es irreversible por diseño (es el objetivo de d212); si rompió algo: sección R con
`RESPALDO_4` y repetir 5 a 7.

**`RESPALDO_8`** (recomendado): respaldo del paso 1 sin simulacro. Punto de corte seguro.

## 9. SMTP, destinatarios (d137, d140) y correo de prueba

Referencia: `docs/data/alerts.md`. Variables (solo nombres): `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT`, `ALERT_SMTP_USER`,
`ALERT_SMTP_PASSWORD`, `ALERT_SMTP_STARTTLS`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` (lista con comas, los destinatarios de
d140) y `ALERTS_ENABLED`. `ALERT_BUSINESS_ENABLED`, `ALERT_REPORT_AGE_ENABLED` y `ALERT_WRITE_FAILED_ENABLED` quedan
apagadas.

1. `notepad "$repo\.env"`: completar `ALERT_*` y `ALERTS_ENABLED=true`. Los valores no van al chat.
2. Correo de prueba por el pipeline real (`send_test_alert.py` se niega fuera de sandbox sin `--allow-non-sandbox`):

```powershell
.venv\Scripts\python.exe scripts\maintenance\send_test_alert.py --allow-non-sandbox
.venv\Scripts\python.exe scripts\maintenance\send_test_alert.py --allow-non-sandbox --send
```

Esperado: `Ambiente: production`, `Destinatarios validos: N (invalidos omitidos: 0)` y, con `--send`, `Enviado.`.
**Confirmar que llegó a cada destinatario.**

3. Reiniciar el 8000 y comprobar `Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/heartbeat | Select-Object status`;
en la pantalla del scheduler debe aparecer `alerts_check` (corre a :02, :17, :32 y :47; pueden llegar alertas reales).

**Rescate:** `ALERTS_ENABLED=false` y reiniciar. Si no llega el correo, seguir igual (no bloquea).

## 10. Usuarios por rol (USR-07) y plantilla de D40

### 10.1 Usuarios `soporte` y `ejecutivo`

Desde **Administración → Usuarios** (`POST /api/v1/admin/users`, permiso `users.manage`). Contraseñas fuera del chat.

```powershell
q "select r.name, count(*) from user_roles ur join roles r on r.id = ur.role_id join users us on us.id = ur.user_id where us.is_active group by r.name order by 1"
```

Esperado: al menos `soporte|1` y `ejecutivo|1` además de `admin`. Probar cada login en una ventana privada: **no** ven
Administración. **Rescate:** desactivar el usuario en la misma pantalla.

### 10.2 Mover `app/templates/reports/virtualpos.html` (D40)

```powershell
$priv = 'C:\Users\Usuario\Documents\CRM_privado'      # ⚠ verificar destino con el usuario (d196)
New-Item -ItemType Directory -Force $priv | Out-Null
Move-Item "$repo\app\templates\reports\virtualpos.html" "$priv\virtualpos.html"
Test-Path "$repo\app\templates\reports\virtualpos.html"
```

Esperado: `False`. No abrir el archivo (tiene nombres reales).

## 10A. `SYNC_CORE_ETL_ENABLED=true` (condicionado a la ficha d215)

> **Solo si el usuario aprobó d215.** Si no, se omite y el paso 11 corre sin ETL Core automático.

La bandera la lee `app/scheduler/jobs/sync_all.py` (línea 373, `settings.sync_core_etl_enabled`, por defecto `false`):
encendida, tras cada sincronización de `sync_all_channels` (la nocturna de las 02:00, el reintento de las 04:00 y las
manuales del scheduler) corre el ETL Core de los canales en línea que sincronizaron y consolidaron bien (VirtualPOS,
Toku y Payku; **TCH no**) y registra su marca en `core_etl_mark`. Afecta a esos tres canales en producción desde la
siguiente corrida. No afecta a `POST /api/v1/etl/full-sync`, que no corre ETL Core.

1. El usuario edita `notepad "$repo\.env"` y deja `SYNC_CORE_ETL_ENABLED=true` (una sola línea). Comprobación:

```powershell
@(Get-Content "$repo\.env" | Where-Object { $_ -match '^SYNC_CORE_ETL_ENABLED=true\s*$' }).Count
```

   Esperado: `1`.
2. Reiniciar el 8000 (paso 3.3): el `.env` no se recarga con `--reload`.
3. Marcas antes (para comparar en el paso 11):

```powershell
q "select external_id, payload->>'finished_at' from source_records where source='core_etl' and resource_type='mark' order by 1"
```

La verificación se hace en el paso 11. **Rescate:** dejar `SYNC_CORE_ETL_ENABLED=false` y reiniciar el 8000; lo que ya
materializó el ETL Core es idempotente y no hace falta deshacerlo.

## 11. Primera sincronización completa en producción desde el 2026-11-09

Por qué esta y no otra: `sync_all_channels` es el job que consolida, captura glosas de VirtualPOS y, con 10A, corre el
ETL Core. Formas (todas usan el lock de corridas, nunca dos a la vez):

- **Con `fix/sync-ui-estado` integrada:** pantalla del scheduler → «Ejecutar todos». Corre primero
  `sync_all_channels` y después, uno tras otro, los jobs manuales de facturación y bajas (`billing_*`,
  `cancellation_*`; son solo lectura hacia el proveedor y ya corren por calendario cada 15 minutos).
- **Sin ella (lo que hay en `master`):** pantalla del scheduler → ejecutar `sync_all_channels` (llama a
  `POST /api/v1/scheduler/jobs/sync_all_channels/run`, permiso `sync.run`).
- `POST /api/v1/etl/full-sync` (permiso `etl.run`, CSRF) también sincroniza y consolida VirtualPOS, Toku y Payku, pero
  **no corre el ETL Core** aunque 10A esté encendida: usarla solo si el job falla al lanzarse.

Seguir el avance en la misma pantalla (eventos en vivo). Con 10A, la corrida pasa por la fase `core_etl`
(`etl_runs.phase`; `sync_runs` no tiene columna de fase).

### Verificación (conteos agregados)

```powershell
q "select source, status, count(*), sum(records_processed), max(finished_at) from sync_runs where started_at > now() - interval '3 hours' group by 1, 2 order by 1, 2"
q "select status, phase, channels_processed, records_upserted, started_at, finished_at from etl_runs order by started_at desc limit 3"
q "select external_id, payload->>'finished_at', payload->'result' from source_records where source='core_etl' and resource_type='mark' order by 1"
```

Esperado: una fila `completed` por canal (`virtualpos1`, `virtualpos2`, `toku`, `payku`; `partial` solo si un recurso
opcional devolvió 404) y ninguna `failed`; la corrida de `etl_runs` `completed`. Con 10A: las marcas de `virtualpos`,
`toku` y `payku` con `finished_at` posterior al inicio de esta corrida y sus conteos por entidad. En la pantalla
**Resumen** (`summary`): estado de cada canal al día.

**Seguir / abortar:** una `failed` en un canal no obliga a restaurar: revisar el mensaje de la corrida (sin datos
personales) en el chat. **Rescate:** las sincronizaciones son idempotentes (`source, resource_type, external_id`); si
la consolidación dejó algo mal: sección R con `RESPALDO_8`. Para 10A: volver a `false` y reiniciar.

## 12. Verificación final y métricas

### 12.1 En la interfaz (con el usuario administrador)

| Comprobación | Dónde | Esperado |
|---|---|---|
| Alerta «Datos incompletos» | Resumen (`SummaryView`, «Datos incompletos: ...») | Menos que antes (**969 / 728**); anotar los dos números nuevos |
| Nombres VirtualPOS | Cartera VP (PR #15) | Socios con nombre, no solo identificador |
| Rechazos con glosa | Recuperador / rechazos (VirtualPOS; Payku con `fix/motivos-rechazo`) | Motivo visible en los rechazos recientes |
| TCH con monto | Suscripciones TCH y recuperador | Monto visible; ninguna ficha activa con fecha de baja |

### 12.2 Conteos de cierre

```powershell
q "select count(*) filter (where amount is null) sin_monto, count(*) filter (where status in ('VIGENTE','PENDIENTE') and ended_at is not null) activa_con_baja from core_subscriptions where source='tch'"
q "select source, count(*) filter (where coalesce(rejection_reason,'') <> '') con_glosa, count(*) total from core_payments where source like 'virtualpos%' or source = 'payku' group by 1 order by 1"
q "select count(*) from clients WHERE source='virtualpos1' AND social_id='11111111-1' AND email LIKE 'ana%@example.test'"
.venv\Scripts\python.exe scripts\maintenance\redact_raw_payload_accounts.py
```

Esperado: TCH como en 4.5; glosas al menos como en 6.4; d214 en `0`; d212 con `total: filas=0 valores=0` (la
sincronización no volvió a guardar cuentas completas).

### 12.3 MET-02 (d201 b: **después** de la ventana, solo lectura)

> **Requiere integrar `feat/s7-metricas` antes.** Correrlo un día después, para que la ventana de métricas incluya
> la operación normal.

```powershell
.venv\Scripts\python.exe scripts\diagnostics\operation_metrics.py --database crm --read-only --days 14 --format markdown
```

`--database` es obligatorio y, fuera de `_test`, exige `--read-only` (transacción `READ ONLY`). Solo agregados.

## Cierre de la ventana

1. `Invoke-RestMethod http://127.0.0.1:8000/health` y login con los tres roles.
2. Borrar la copia del `.env`: `[System.IO.File]::Delete("$bkdir\env_pre_ops11.bak")` (`Remove-Item` con rutas `C:`
   puede bloquearse, handoff §3).
3. Copia del respaldo fuera del equipo (disco externo y, cifrada, nube), si no se hizo en el paso 1.
4. Quitar variables: `Remove-Item Env:APP_ENV, Env:PYTHONPATH -ErrorAction SilentlyContinue`.
5. Reportar en el chat: revisión de `crm`, RTO, tiempos reales de 4, 8 y 11, paridad TCH, d211 (`N0`), d214 (5/5/5),
   d212 (totales), conteos de Toku y de glosas, correo recibido, usuarios creados, estado de 10A y números de
   «Datos incompletos».

## R. Rescate: restaurar un respaldo sobre `crm`

> Reemplaza todos los datos de `crm`. Solo con decisión explícita del usuario. Mismo procedimiento que
> `docs/operations/backups.md` («Restaurar en una emergencia»), copiando el dump al contenedor para no pasar binarios
> por tuberías de PowerShell.

1. Detener el 8000 (`Ctrl+C` en su ventana). El 8001 usa `crm_sandbox` y no se toca.
2. Opcional: respaldar el estado actual para análisis (paso 1 con otro nombre).
3. Restaurar:

```powershell
$rd = '<RESPALDO_1, RESPALDO_4 o RESPALDO_8>'
docker cp $rd "${pgc}:/tmp/rescate.dump"
docker compose exec -T postgres pg_restore --list /tmp/rescate.dump | Measure-Object -Line
docker compose exec -T postgres dropdb -U $u --force crm
docker compose exec -T postgres createdb -U $u crm
docker compose exec -T postgres pg_restore -U $u -d crm --exit-on-error --no-owner /tmp/rescate.dump
q "select version_num from alembic_version"
docker compose exec -T postgres rm /tmp/rescate.dump
```

Esperado: sin errores; revisión `20261103_0068` (`RESPALDO_1`) o `20261104_0071` (`RESPALDO_4`, `RESPALDO_8`).

4. Si el problema fue de configuración, restaurar también `$bkdir\env_pre_ops11.bak` sobre `.env` (y, si 10A estaba
   encendida, revisar `SYNC_CORE_ETL_ENABLED`).
5. Arrancar el 8000 (paso 3.3), comprobar `/health` y el login, y avisar a los usuarios.

## Definición de hecho relacionada (`docs/tasks.md` §3.10 y fichas)

- [ ] `crm` en `0071` y `seed_roles.py` aplicado (paso 2); `payku.wallet.withdraw` creado si la rama estaba integrada.
- [ ] Respaldo restaurado en `crm_restore_test` con conteos iguales y **RTO anotado**; copia fuera del equipo (paso 1).
- [ ] JWT nuevo y sesiones viejas rechazadas (paso 3.4).
- [ ] TCH recargado con `fecha_ingreso` y monto/estado (d209, CRM-15B), paridad dentro del umbral, d211 aplicado (paso 4).
- [ ] Pepper, reportes de Toku (d196), señales y códigos (TK-PAR-01, TK-PAR-04) (paso 5).
- [ ] Reportes PAT cargados y ETL Core de VirtualPOS y Payku (CRM-15A) (paso 6).
- [ ] d214 (5/5/5) y d212 (dry-run final en 0) (pasos 7 y 8).
- [ ] Un correo de alerta recibido (paso 9).
- [ ] Usuarios `soporte` y `ejecutivo` (USR-07) y plantilla D40 fuera del proyecto (paso 10).
- [ ] d215 resuelta: 10A aplicado u omitido.
- [ ] Primera sincronización completa sin canales `failed` (paso 11) y verificación final (paso 12).
- [ ] MET-02 en solo lectura después de la ventana (12.3).

## Lista de «⚠ verificar»

Abiertos:

1. Toku (5.2): qué tipo detecta el dry-run en cada `.xlsx` de las dos generaciones (2026-10-20 y 2026-11-13); si un
   tipo se repite, cargar solo el más nuevo.
2. Carpeta de destino de la plantilla de D40 (10.2).
3. Formato de los montos de las filas en 0 de `tch_recaudacion_mensual` (4.6): mirar el conteo antes.
4. Duraciones de 4, 8 y 11: estimadas, nunca medidas en `crm`.

Cerrados el 2026-11-13 (verificados en código):

- Carpeta de TCH: `C:\Users\Usuario\Downloads\Proyectos\CRM_reportes\TCH` (corregida también en `tch-reload.md` de
  `fix/tch-recuperador-estado-monto`).
- `seed_roles.py` crea `payku.wallet.withdraw` vía `seed_permissions` (rama `feat/payku-prueba-y-retiro`).
- `import_vp_reports.py --dir` acepta una sola carpeta y no es recursivo: dos corridas (6.2).
- ETL Core de VirtualPOS y Payku: líneas de Python equivalentes a `_run_core_etl_background`, con marca (6.3).
- `SYNC_CORE_ETL_ENABLED` solo actúa en `sync_all_channels`, no en `/etl/full-sync`; la fase `core_etl` está en
  `etl_runs`, no en `sync_runs` (10A, 11).
- «Ejecutar todos» (`fix/sync-ui-estado`) lanza además los jobs manuales de facturación y bajas (11).
