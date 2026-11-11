# Guion de la ventana de despliegue OPS-11 (producción, `crm`)

> Ficha d194 (aprobada). Fecha prevista: miércoles 2026-11-11. **Lo ejecuta el usuario**, con acompañamiento por chat.
> Ningún agente corre Alembic, scripts con `--apply` ni toca `crm` (handoff §2, reglas 4 y 6).
> Fuentes: `handoff.md` §2 a §7, `docs/tasks.md` §3.10 y filas OPS-11, USR-07, USR-12, TK-PAR-01 y TK-PAR-04;
> `docs/data/tch-reload.md`, `docs/data/toku-reports-load.md`, `docs/data/alerts.md`; `docs/operations/backups.md`
> de la rama `ops/bck-01a-respaldos` (PR #8).
> Convención: **⚠ verificar** marca lo que no se pudo confirmar en el código o en la documentación; antes de
> ejecutarlo, revisarlo en el chat.

## Resumen

| Paso | Qué | Escribe en `crm` | Duración estimada |
|---|---|---|---|
| 0 | Prerrequisitos, aviso y detener el backend 8000 | No | 15 min |
| 1 | Respaldo de `crm`, verificación y simulacro en `crm_restore_test` | No | 25 a 35 min |
| 2 | `alembic upgrade head` (`0068 → 0071`) y `seed_roles.py` | Sí (liviano) | 10 min |
| 3 | Rotar `AUTH_JWT_SECRET` y arrancar el 8000 | No (solo `.env`) | 10 min |
| 4 | Recarga completa de TCH, ETL Core de TCH, consolidación y paridad | Sí (pesado) | 60 a 120 min (estimación desde el código y tiempos registrados; ver «Duración» en el paso 4) |
| 5 | `TOKU_REPORT_HASH_PEPPER`, carga de reportes de Toku y backfill TK-PAR-04 | Sí | 30 a 45 min |
| 6 | SMTP y destinatarios (d140), `ALERTS_ENABLED=true` y correo de prueba | No (solo `.env`) | 15 a 20 min |
| 7 | Usuarios por rol (USR-07) y mover la plantilla de D40 | Sí (usuarios) | 15 min |
| | **Total** | | **≈ 3 h 30 min (rango 3 a 4 h 30 min)** |

Rescate general: sección **R** al final. Cada paso dice si su rescate es la sección R o algo más acotado.

## Variables de la sesión de PowerShell

Abrir **una** terminal PowerShell 7 dedicada a la ventana (no la del backend) y dejar fijadas estas variables.
Ninguna contiene secretos.

```powershell
$repo   = 'C:\Users\Usuario\Downloads\Proyectos\CRM_projectoTitulo'   # checkout principal, rama master
$bkdir  = 'C:\Users\Usuario\Downloads\CRM_backups'                     # fuera del repo
$pgc    = 'crm_projectotitulo-postgres-1'                              # contenedor (handoff §3)
Set-Location $repo
```

## 0. Prerrequisitos y chequeo previo

| # | Comprobación | Comando | Esperado | Si no |
|---|---|---|---|---|
| 0.1 | Git en `master` al día y sin cambios rastreados | `git fetch origin; git status -sb` y luego `git pull --ff-only` | `## master...origin/master` sin `ahead`/`behind`; solo archivos `??` ajenos (p. ej. los `.canvas`) | Abortar y avisar en el chat |
| 0.2 | Head de migraciones en el código | `.venv\Scripts\alembic.exe heads` (tras fijar el ambiente del paso 2.1) | Una sola línea `20261104_0071 (head)` | Abortar |
| 0.3 | ¿PR #8 (BCK-01a) integrado? | `Test-Path .\scripts\maintenance\backup_db.ps1` | `True` → variante 1A; `False` → variante 1B o 1A desde el worktree | — |
| 0.4 | Docker y PostgreSQL arriba | `docker compose ps` | Servicio `postgres` en `running (healthy)`, puerto `5433` | `docker compose up -d` y repetir |
| 0.5 | Espacio en disco | `Get-PSDrive C \| Select-Object Used,Free` | Libre ≥ 10 GB (el respaldo del 2026-11-03 pesó 430 MB; la recarga de TCH reescribe ~1,5 M filas) | Liberar espacio o abortar |
| 0.6 | Reportes TCH presentes | `(Get-ChildItem "$repo\docs\Reportes_TCH" -Filter *.xlsx).Count` | `30` (conteo del 2026-11-10) | ⚠ verificar carpeta: pendiente del usuario (ficha d196) (ver paso 4) |
| 0.7 | Sandbox 8001 | No se toca. `Invoke-RestMethod http://127.0.0.1:8001/health` solo para confirmar que sigue arriba | `status: ok` | Ignorar; no es parte de la ventana |
| 0.8 | Aviso a usuarios | Avisar con anticipación que el CRM estará **fuera de servicio** durante la ventana y que **todas las sesiones se cerrarán** (paso 3): habrá que volver a iniciar sesión | Avisado | No empezar sin aviso |
| 0.9 | Que no haya cargas en curso | Ninguna importación TCH ni sincronización abierta en la pantalla de administración. El ETL de TCH sale con código 2 si hay una corrida activa en `etl_runs` | — | Esperar a que termine |
| 0.10 | **Detener el backend 8000** | En su terminal: `Ctrl+C` | El proceso termina; `Invoke-RestMethod http://127.0.0.1:8000/health` falla con conexión rechazada | — |

El backend se detiene **antes** del respaldo para que nada (scheduler, usuarios) escriba en `crm` entre el respaldo, el
simulacro y la migración. El front 5173 puede quedar arriba (no toca la base). Se vuelve a arrancar en el paso 3.

## 1. Respaldo de `crm` y verificación

### 1A. Con BCK-01a (PR #8)

Scripts: `scripts/maintenance/backup_db.ps1` (parámetros `-Database`, `-Destination`, `-RetentionDays`,
`-ExternalCopyPath`, `-AlertOnFailure`, `-ProjectDir`) y `scripts/maintenance/restore_drill.ps1` (`-DumpFile`,
`-SourceDatabase`, `-TargetDatabase`, `-SkipCompare`, `-ProjectDir`), según la rama `ops/bck-01a-respaldos` (`6fba853`).

**Si el PR #8 ya está en `master`:**

```powershell
.\scripts\maintenance\backup_db.ps1 -Database crm -Destination $bkdir
# con el disco externo conectado, agregar: -ExternalCopyPath E:\CRM_backups
```

**Si el PR #8 no está integrado** (correr los scripts desde el worktree, apuntando al checkout principal):

```powershell
$bck = 'C:\Users\Usuario\Downloads\Proyectos\crm-wt-bck\scripts\maintenance'
& "$bck\backup_db.ps1" -Database crm -Destination $bkdir -ProjectDir $repo
```

> `-ProjectDir $repo` es **obligatorio** desde el worktree: los scripts llaman a
> `docker compose -f <ProjectDir>\compose.yaml --project-directory <ProjectDir>` (`backup_common.ps1`,
> `Invoke-Compose`); sin él, el proyecto de compose sería `crm-wt-bck` (otro contenedor, sin `.env`) y fallaría.
> Política de ejecución (verificado el 2026-11-10): `CurrentUser` y `LocalMachine` están en `RemoteSigned` y los `.ps1`
> no tienen marca de descarga (`Zone.Identifier`), así que **no hace falta `Bypass`**: los docs del PR #8
> (`backups.md`) los invocan directo (`.\scripts\maintenance\backup_db.ps1 ...`). Solo la tarea programada usa
> `-ExecutionPolicy Bypass` (`register_backup_task.ps1`, línea 47). Si aun así apareciera «no está firmado digitalmente»,
> usar el mismo patrón que la tarea, que afecta solo a ese proceso y no cambia la política del equipo:
> `pwsh -NoProfile -ExecutionPolicy Bypass -File "$bck\backup_db.ps1" -Database crm -Destination $bkdir -ProjectDir $repo`
> (o la variante sin `$bck`/`-ProjectDir` si el PR #8 está en `master`). No usar `Set-ExecutionPolicy` ni `Unblock-File`.

**Salida esperada:** una línea `... [INFO] OK crm_YYYYMMDD_HHmm.dump (NNN,N MB, NNN entradas en el TOC, NN s).`
(también queda en `$bkdir\logs\backup_db.log`). Código de salida `0` (`$LASTEXITCODE`).
Tamaño esperado del orden de 430 MB o algo más.

**Simulacro (definición de hecho de S6):**

```powershell
$dump = (Get-ChildItem $bkdir -Filter 'crm_*.dump' | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
Measure-Command { .\scripts\maintenance\restore_drill.ps1 -DumpFile $dump -SourceDatabase crm } | Select-Object TotalMinutes
# desde el worktree: & "$bck\restore_drill.ps1" -DumpFile $dump -SourceDatabase crm -ProjectDir $repo
```

Esperado: tabla de conteos por tabla y `RESULTADO: OK (N tablas, M filas en origen y restaurada).`, código `0`.
Anotar los minutos de `Measure-Command` como **RTO** (y la línea `Restauracion completa en N s.` del log).

### 1B. Sin BCK-01a (`docker compose exec postgres pg_dump -Fc`)

El dump se genera **dentro del contenedor** y se copia con `docker cp` (evita que PowerShell corrompa el binario en una
tubería). La copia en `/tmp` del contenedor se conserva hasta el final de la ventana: hace más rápido el rescate.

```powershell
$u     = (docker compose exec -T postgres printenv POSTGRES_USER).Trim()   # nombre de usuario de la base, no es secreto
$name  = "crm_predeploy_OPS11_$(Get-Date -Format 'yyyyMMdd_HHmm').dump"
New-Item -ItemType Directory -Force $bkdir | Out-Null
docker compose exec -T postgres pg_dump -U $u -Fc -d crm -f "/tmp/$name"
docker compose exec -T postgres pg_restore --list "/tmp/$name" | Measure-Object -Line
docker cp "${pgc}:/tmp/$name" "$bkdir\$name"
docker compose exec -T postgres stat -c %s "/tmp/$name"
(Get-Item "$bkdir\$name").Length
```

Esperado: `pg_dump` sin salida y código 0; `pg_restore --list` con varios cientos o miles de líneas (TOC) y sin error;
los dos tamaños (`stat` y `Length`) **idénticos**.

**Simulacro manual en `crm_restore_test`** (mismo fin que `restore_drill.ps1`):

```powershell
docker compose exec -T postgres dropdb -U $u --if-exists --force crm_restore_test
docker compose exec -T postgres createdb -U $u crm_restore_test
Measure-Command { docker compose exec -T postgres pg_restore -U $u -d crm_restore_test --exit-on-error --no-owner --no-acl "/tmp/$name" } | Select-Object TotalMinutes
$q = "select (select version_num from alembic_version) v, (select count(*) from users) u, (select count(*) from vp_subscriptions) vps, (select count(*) from tch_transacciones) tch, (select count(*) from core_charges) cc, (select count(*) from payments) p"
docker compose exec -T postgres psql -U $u -d crm -At -c $q
docker compose exec -T postgres psql -U $u -d crm_restore_test -At -c $q
```

Esperado: las dos líneas de conteos **idénticas** (`20261103_0068|...`). Anotar los minutos como RTO.

### Verificación del paso 1 (ambas variantes)

```powershell
$u = (docker compose exec -T postgres printenv POSTGRES_USER).Trim()
docker compose exec -T postgres psql -U $u -d crm -At -c "select version_num from alembic_version"
```

Esperado: `20261103_0068`.

**Copia fuera del equipo (d156):** copiar el `.dump` al disco externo y, si se decide subirlo a la nube, **solo cifrado**
con `encrypt_backup.ps1` (variante 1A; ver `docs/operations/backups.md`, sección «Cifrado para la nube»). La frase
de cifrado se escribe con `Read-Host` y nunca va al chat. Puede hacerse al final de la ventana si apura el tiempo,
pero es parte de la definición de hecho.

**Seguir / abortar:** seguir solo si el respaldo terminó con código 0, el TOC se listó, los tamaños coinciden (1B) y el
simulacro dio conteos iguales. Si algo falla: **abortar la ventana** (aún no se cambió nada), arrancar el 8000 como estaba
y revisar en el chat.

**Rescate:** no aplica (paso de solo lectura sobre `crm`).

Anotar aquí el archivo: `RESPALDO_1 = <ruta del .dump>`; es el que usa la sección R.

## 2. `alembic upgrade head` en `crm` y `seed_roles.py`

### 2.1 Fijar el ambiente ANTES de importar `settings` (handoff §2, regla 3)

`alembic/env.py` lee `settings.database_url` al importar, y `app/core/config.py` toma las variables de proceso con
prioridad sobre el `.env` (`CRM_DOTENV_PATH` elige otro `.env`). Con `APP_ENV=sandbox` o `qa` la base pasa a ser
`SANDBOX_DATABASE_URL`. Por eso, en la terminal de la ventana:

```powershell
Set-Location $repo
Remove-Item Env:DATABASE_URL, Env:SANDBOX_DATABASE_URL, Env:CRM_DOTENV_PATH, Env:ALEMBIC_ALLOW_DOWNGRADE -ErrorAction SilentlyContinue
$env:APP_ENV    = 'production'   # explícito; el .env usa el alias histórico de producción
$env:PYTHONPATH = '.'
.venv\Scripts\python.exe -c "from app.core.config import settings; from sqlalchemy.engine import make_url; print(settings.env_mode, make_url(settings.database_url).database)"
```

No se fija `DATABASE_URL` en el proceso (llevaría la contraseña a la terminal): se quitan las anulaciones de proceso y
se usa la del `.env`. El último comando imprime **solo** el modo y el nombre de la base.

Esperado: `production crm`. **Cualquier otra cosa: abortar** (no correr Alembic).

### 2.2 Migración

```powershell
.venv\Scripts\alembic.exe current
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\alembic.exe current
```

Esperado: `current` antes `20261103_0068`; `heads` una sola línea `20261104_0071 (head)`; `upgrade` imprime
`Running upgrade 20261103_0068 -> 20261104_0071, Permiso payku.reports.import ...`; `current` después
`20261104_0071 (head)`. La `0071` solo inserta el permiso `payku.reports.import` y lo asigna a `admin`
(`alembic/versions/20261104_0071_seed_payku_reports_import_permission.py`); es liviana.

### 2.3 Roles

```powershell
.venv\Scripts\python.exe scripts\maintenance\seed_roles.py
```

Esperado (`scripts/maintenance/seed_roles.py`): `Ambiente: production`, `Rol soporte: N permisos`,
`Rol ejecutivo: M permisos`, con N ≥ 36 y M ≥ 35 (valores del 2026-11-03). Es idempotente.

### Verificación

```powershell
docker compose exec -T postgres psql -U $u -d crm -At -c "select version_num from alembic_version"
docker compose exec -T postgres psql -U $u -d crm -At -c "select r.name, count(*) from role_permissions rp join roles r on r.id = rp.role_id join permissions p on p.id = rp.permission_id where p.code = 'payku.reports.import' group by r.name"
```

Esperado: `20261104_0071` y `admin|1`.

**Seguir / abortar:** seguir si la revisión es `20261104_0071` y `seed_roles` terminó sin traza de error. Si `upgrade`
falla, Alembic revierte la transacción de la migración: comprobar `current`; si sigue en `0068`, abortar y revisar en el
chat (no reintentar a ciegas).

**Rescate:** **no usar `alembic downgrade`** (bloqueado en `crm` por `app/db/migration_guard.py` salvo
`ALEMBIC_ALLOW_DOWNGRADE=1`, y no autorizado). Si la base quedó en un estado inconsistente: sección R con `RESPALDO_1`.

## 3. Rotar `AUTH_JWT_SECRET` (USR-12) y arrancar el backend 8000

`app/core/security.py` firma y valida las sesiones con `settings.auth_jwt_secret` (mínimo 32 caracteres, HS256). Al
cambiarlo, toda cookie emitida antes deja de valer. Con el PR #10 (SEC-03, ya en `master`), `SANDBOX_AUTH_JWT_SECRET`
debe ser **distinta** de `AUTH_JWT_SECRET` (`app/core/config.py`); un secreto aleatorio nuevo lo cumple. El 8001 no se
reinicia.

### 3.1 Comprobar la sesión vieja (antes de rotar)

Antes de rotar, dejar una pestaña del navegador con la sesión de producción (5173) abierta. Como el 8000 está detenido
no responderá, pero conserva la cookie vieja para la verificación 3.4.

### 3.2 Copia del `.env` y rotación (no imprime el secreto)

```powershell
Copy-Item "$repo\.env" "$bkdir\env_pre_ops11.bak"     # copia local, fuera del repo; borrarla al cerrar la ventana
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$nuevo = -join ($bytes | ForEach-Object { $_.ToString('x2') })      # 96 caracteres hexadecimales
$lineas = Get-Content "$repo\.env"
$n = @($lineas | Where-Object { $_ -match '^AUTH_JWT_SECRET=' }).Count
if ($n -ne 1) { Write-Host "ABORTAR: hay $n lineas AUTH_JWT_SECRET" } else {
  $lineas = $lineas | ForEach-Object { if ($_ -match '^AUTH_JWT_SECRET=') { "AUTH_JWT_SECRET=$nuevo" } else { $_ } }
  Set-Content -Path "$repo\.env" -Value $lineas -Encoding utf8NoBOM
  Write-Host "AUTH_JWT_SECRET rotado (largo $($nuevo.Length))"
}
Remove-Variable nuevo, bytes, lineas
```

Esperado: `AUTH_JWT_SECRET rotado (largo 96)`. Nunca imprimir ni pegar el valor en el chat.

### 3.3 Arrancar el 8000

En la terminal del backend (handoff §3):

```powershell
Set-Location $repo
Remove-Item Env:APP_ENV, Env:DATABASE_URL, Env:SANDBOX_DATABASE_URL -ErrorAction SilentlyContinue
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

`--reload` vigila el código, no el `.env`: **cada cambio posterior del `.env` (pasos 5 y 6) exige `Ctrl+C` y volver a
lanzar este comando.**

### 3.4 Verificación

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/heartbeat | Select-Object status, environment, database
```

Esperado: `/health` con `status: ok` (`app/main.py`); el heartbeat responde (`ok` o `degraded`, nunca 503) con base `crm`.
En la pestaña con la sesión vieja: refrescar → la app pide iniciar sesión (respuesta 401
`invalid_or_expired_session`). Iniciar sesión de nuevo → entra. Eso cumple «JWT nuevo y sesiones viejas rechazadas».

**Seguir / abortar:** seguir si arranca, `/health` responde y el login nuevo funciona. Si el backend no arranca (error de
validación de `Settings`): revisar el mensaje (no contiene valores, `hide_input_in_errors=True`).

**Rescate:** acotado al `.env`: `Copy-Item "$bkdir\env_pre_ops11.bak" "$repo\.env" -Force` y relanzar el 8000. No hace
falta tocar la base.

## 4. Recarga completa de TCH (d121, TCH-PAR-08)

Procedimiento: `docs/data/tch-reload.md`. Script: `scripts/etl_tch.py` (banderas verificadas en `_build_parser`:
`--folder`, `--mode full`, `--dry-run`, `--apply`, `--confirm-database`, `--exclude-months`, `--tolerance-month`,
`--tolerance-total`, `--backfill-source-records`). La recarga borra y reconstruye todo `tch_*`; es transaccional
(todo o nada) y concilia contra `tch_recaudacion_mensual` antes de confirmar.

**⚠ verificar la carpeta, pendiente del usuario (ficha d196):** `tch-reload.md` indica `C:\Users\Usuario\Downloads\CRM_reportes\TCH`, que **no existe** en
este equipo (comprobado el 2026-11-10). Los Excel de TCH están en `$repo\docs\Reportes_TCH` (30 `.xlsx`, ignorado por
git). Confirmar en el chat cuál es el juego correcto antes del dry-run.

Usar la misma terminal de la ventana (ambiente fijado en 2.1; repetir 2.1 si se abrió otra).

**Duración (estimada; nunca se midió una recarga completa en `crm`):** los 30 `.xlsx` suman ~276 MB (el mayor,
~12,5 MB). Tiempos registrados (`docs/planning/auditoria-2026-10-29/research_sync_opt.md`): el ETL de archivo de TCH
procesa ~1.500 filas/s (80 a 102 s por archivo de 125 a 161 mil filas) y la consolidación ~1.150 filas/s (1,47 M filas
≈ 1.280 s). Con ~1,0 a 1,47 M filas: dry-run 4.1 ≈ 12 a 20 min y apply 4.2 otro tanto (el dry-run hace todo el trabajo
y luego ROLLBACK; el modo full además crea un `source_records` por fila), ETL Core 4.3 ≈ 10 a 20 min (sin medición de
carga completa; mismo orden de filas), consolidación 4.4 ≈ 15 a 21 min y paridad 4.5 ≈ 2 a 5 min. Total ≈ 55 a 90 min;
se mantiene la reserva de **60 a 120 min**. Anotar los tiempos reales de cada subpaso para la próxima vez.

```powershell
$tch   = "$repo\docs\Reportes_TCH"      # ⚠ verificar: pendiente del usuario (ficha d196)
$excl  = '2023-01,2023-02,2023-03,2023-04,2023-05,2023-06,2023-07,2023-08,2023-09,2023-10,2023-11,2023-12'
```

### 4.1 Dry-run (no confirma nada; reconstruye y hace ROLLBACK)

```powershell
.venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder $tch --exclude-months $excl
```

Esperado: `Modo full: N archivos a procesar`, la tabla de conciliación por mes (estado `ok`, `excluido` para 2023 o
`FALLA`), el total, `Fichas VIGENTES resultantes: ~8.401` y `Dry-run terminado: nada se confirmo (ROLLBACK).
Conciliacion OK`. Umbrales por defecto: 0,5 % por mes y 0,1 % total.

**Seguir / abortar:** si hay algún mes en `FALLA` o dice `CON DIFERENCIAS`: **no aplicar**; pegar en el chat solo la
tabla de conciliación (meses y conteos, sin nombres de archivo con datos) y decidir. Código 2 = hay otra corrida activa.

### 4.2 Apply (exige el nombre exacto de la base)

```powershell
.venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder $tch --exclude-months $excl --apply --confirm-database crm
```

Esperado: la misma tabla de conciliación y `Recarga CONFIRMADA. Total procesados: N`. Si la conciliación no cuadra:
`Conciliacion fuera de umbral; ROLLBACK, la base quedo intacta` y código de salida `3` (la base queda como estaba).

### 4.3 ETL Core de TCH (clientes, suscripciones, `core_charges`, pagos)

Verificado el 2026-11-10: **no existe CLI** para el ETL Core de TCH (nada en `scripts/` llama a `run_tch_core_etl`;
`etl_tch.py` solo importa `normalize_tch_currency`, y la noche no lo corre: en `sync_all.py`, `_CORE_ETL_RUNNERS`
excluye TCH). Las dos formas reales son la ruta `POST /api/v1/etl/core/tch` (`app/api/v1/routes/etl.py`, permiso
`etl.run` y cabecera CSRF; la interfaz no tiene botón) y la función `run_tch_core_etl(db)`
(`app/services/core_tch_etl.py`), que hace su propio `db.commit()` y devuelve solo conteos. La línea siguiente es
exactamente lo que hace la ruta en `_run_core_etl_background` (`fn(db)` y `db.commit()`; para TCH la ruta no registra
marca de frescura), salvo la fila de `etl_runs` y el lock exclusivo de corridas. Mismo ambiente fijado en 2.1, desde
`$repo`:

```powershell
.venv\Scripts\python.exe -c "from app.db.session import SessionLocal; from app.services.core_tch_etl import run_tch_core_etl; db = SessionLocal(); r = run_tch_core_etl(db); db.commit(); db.close(); print(r)"
```

Como no toma el lock exclusivo, correrla sin corridas activas (ninguna sincronización ni importación en curso durante
la ventana). Esperado: un diccionario con `clients_created`, `attributes_inserted`, `subscriptions_upserted`,
`charges_inserted` y los pagos. Alternativa equivalente: la ruta con sesión de administrador (login + CSRF), que además
deja la fila en `etl_runs`.

### 4.4 Consolidación de TCH a las tablas centralizadas (`charges`, `payments`)

`tch-reload.md` pide «la consolidación de `charges`» sin dar el comando. Verificado el 2026-11-10: el script es
`scripts/maintenance/consolidate_baseline.py`, con banderas `--source` (repetible; `virtualpos`, `toku`, `payku`,
`tch`; sin ella, todos), `--apply` y `--confirm-database` (debe coincidir exactamente con `current_database()`; si no,
sale con código 2). Llama a `consolidate_to_centralized(db, ['tch'], baseline=True)` y confirma, así que los eventos
quedan `is_baseline=true` y no cuentan como novedad del día (su docstring lo indica «tras una carga histórica»). Es el
camino correcto: dejarlo a la consolidación nocturna (`sync_all.py` consolida `tch` tras una carga nueva) marcaría la
recarga entera como novedades. Requiere la migración `20261029_0042` (si falta, lo dice y no escribe).

```powershell
.venv\Scripts\python.exe scripts\maintenance\consolidate_baseline.py --source tch
.venv\Scripts\python.exe scripts\maintenance\consolidate_baseline.py --source tch --apply --confirm-database crm
```

Esperado: el primero solo muestra base y conteos (solo lectura); el segundo consolida y muestra conteos finales.

### 4.5 Paridad de TCH (solo lectura)

```powershell
.venv\Scripts\python.exe scripts\diagnostics\parity_check.py --channel tch --read-only
```

`--read-only` es **obligatorio** fuera de `_test` (guarda de `scripts/diagnostics/readonly_guard.py`); el script corre
en una transacción `READ ONLY`. Esperado: filas `transaction` y `control_mensual` por mes y estado (`ACEPTADA` /
`RECHAZADA`) con conteos que coinciden mes a mes, salvo 2023 (excluido). Conteos adicionales:

```powershell
$q = "select count(*) total, count(*) filter (where periodo is null) sin_periodo from tch_transacciones"
docker compose exec -T postgres psql -U $u -d crm -At -c $q
```

Esperado: total cercano a 1,0 M (antes 1,47 M) y `sin_periodo = 0`; fichas VIGENTES ~8.401 (salida de 4.2).
(La columna es `periodo`: `app/models/tch.py`, atributo `period` mapeado a `"periodo"`.)

**Seguir / abortar:** seguir si 4.2 confirmó y la paridad está dentro del umbral. Si 4.3 o 4.4 fallan después de un
4.2 confirmado, los datos `tch_*` ya están bien; repetir 4.3/4.4 (son idempotentes) antes de pensar en restaurar.

**Rescate:** si la recarga confirmada resultó mala (paridad fuera de umbral, tablas Core inconsistentes): sección R con
`RESPALDO_1` y luego repetir los pasos 2 y 3 (la `0071` y `seed_roles` vuelven a aplicarse; el `.env` ya está rotado).

**Respaldo intermedio recomendado:** al terminar el paso 4, repetir el paso 1 (sin simulacro) y anotarlo como
`RESPALDO_4`. Así un fallo en los pasos 5 a 7 no obliga a rehacer la recarga de TCH.

## 5. Pepper de Toku, carga de reportes (TK-PAR-01) y backfill TK-PAR-04

Procedimiento: `docs/data/toku-reports-load.md`. Las tablas `tk_report_*` de `crm` están vacías (handoff §4), así que el
backfill de TK-PAR-04 necesita **antes** el pepper y la carga de los reportes (el backfill toma los códigos de
`tk_report_attempts`).

### 5.1 Definir `TOKU_REPORT_HASH_PEPPER` (solo si no existe)

Cambiarlo después invalida los hashes guardados. El script lo agrega solo si no hay una línea activa:

```powershell
$lineas = Get-Content "$repo\.env"
if (@($lineas | Where-Object { $_ -match '^TOKU_REPORT_HASH_PEPPER=.+' }).Count -gt 0) { Write-Host 'Ya existe: no se cambia' } else {
  $bytes = New-Object byte[] 48; [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  Add-Content -Path "$repo\.env" -Value ("TOKU_REPORT_HASH_PEPPER=" + (-join ($bytes | ForEach-Object { $_.ToString('x2') }))) -Encoding utf8NoBOM
  Write-Host 'Pepper agregado'
}
Remove-Variable lineas, bytes -ErrorAction SilentlyContinue
```

Guardar una copia del pepper en el gestor de contraseñas (sin pasar por el chat). Reiniciar el 8000 (`Ctrl+C` y el
comando de 3.3) para que la ruta `/api/v1/imports/toku-reports` lo lea.

### 5.2 Reportes de Toku

⚠ verificar qué juego cargar, pendiente del usuario (ficha d196): `$repo\docs\Reportes_Toku` tiene 14 `.xlsx` (posiblemente dos generaciones, 2026-08-09 y
2026-10-20). Basta el más reciente; cargar uno viejo sobre uno nuevo deja filas «obsoletas». Lo ideal (TK-PAR-01,
USR-09) es exportar reportes nuevos del Backoffice, incluido **Deudas**, a una carpeta **fuera del repo**.

```powershell
$toku = '<carpeta con los reportes de Toku más recientes>'   # ⚠ verificar: pendiente del usuario (ficha d196)
.venv\Scripts\python.exe scripts\maintenance\import_toku_reports.py --dir $toku
.venv\Scripts\python.exe scripts\maintenance\import_toku_reports.py --dir $toku --apply
```

Esperado (dry-run): `Ambiente: production | modo: DRY-RUN (solo lectura) | archivos: N` y una línea por archivo con
tipo, filas válidas y omitidas. Seguir solo si no hay `ERROR` y los tipos son Productos, Medios de pago, Inscripciones,
Deudas e Intentos. El `--apply` carga en orden (`LOAD_ORDER`: productos primero). `pepper_not_configured` → volver a 5.1.

### 5.3 Señales y fechas de Toku (TK-20, parte de TK-PAR-04)

```powershell
.venv\Scripts\python.exe scripts\maintenance\toku_report_lifecycle.py --signals
```

Esperado (solo conteos): suscripciones con fecha de alta/baja, bajas a crear (se esperan ~140), activas efectivas
(~178) y recuperables por motivo; racha de 3 o más cuotas ~72 (si se acerca a 138, está contando intentos: **abortar**).
Solo si cuadra y se aprueba en el chat:

```powershell
.venv\Scripts\python.exe scripts\maintenance\toku_report_lifecycle.py --signals --apply
```

### 5.4 Backfill de códigos de rechazo (TK-PAR-04 / RJ-11)

Script: `scripts/maintenance/project_toku_rejections.py` (dry-run por defecto en transacción de solo lectura; `--apply`
escribe). No llama a la API.

```powershell
.venv\Scripts\python.exe scripts\maintenance\project_toku_rejections.py
```

Esperado: `Ambiente: production | modo: DRY-RUN (solo lectura)` y conteos `failed_total`, `failed_without_information`,
`codes_from_report_by_id`, `codes_from_report_by_debt_day`, `charges_updated`, `payments.payments_updated`, etc.
Referencia: hasta 5.412 códigos históricos vacíos (fila TK-PAR-04). Seguir si `codes_from_report_by_*` > 0 y no hay
error; pegar los conteos en el chat y aplicar con aprobación:

```powershell
.venv\Scripts\python.exe scripts\maintenance\project_toku_rejections.py --apply
.venv\Scripts\python.exe scripts\maintenance\project_toku_rejections.py
```

La segunda corrida (dry-run) debe mostrar `charges_updated = 0` (idempotente).

### Verificación (solo conteos)

```powershell
docker compose exec -T postgres psql -U $u -d crm -c "select report_type, status, count(*) from tk_report_files group by 1, 2"
docker compose exec -T postgres psql -U $u -d crm -c "select lifecycle_status, is_effectively_active, is_recoverable, recoverable_reason, count(*) from core_subscription_signals group by 1, 2, 3, 4 order by 5 desc"
```

No encender `TOKU_REPORT_SIGNALS_ENABLED` ni `TOKU_MATERIALIZE_FAILED_PAYMENTS` en esta ventana (handoff §6, riesgo 8:
en S6 solo alertas).

**Rescate:** si una carga o un `--apply` dejó datos malos: sección R con `RESPALDO_4` (o `RESPALDO_1` y repetir 2 a 4).
El pepper puede quedar en el `.env`.

## 6. SMTP, destinatarios (d140), `ALERTS_ENABLED=true` y correo de prueba

Referencia: `docs/data/alerts.md`. Variables (solo nombres): `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT`, `ALERT_SMTP_USER`,
`ALERT_SMTP_PASSWORD`, `ALERT_SMTP_STARTTLS`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` (lista separada por comas) y
`ALERTS_ENABLED`. Las de negocio, reportes viejos y escrituras fallidas (`ALERT_BUSINESS_ENABLED`,
`ALERT_REPORT_AGE_ENABLED`, `ALERT_WRITE_FAILED_ENABLED`) quedan apagadas.

### 6.1 Editar el `.env` a mano

`notepad "$repo\.env"`: completar las variables `ALERT_*` y dejar `ALERTS_ENABLED=true`. Los valores no van al chat
ni al repo. Guardar y cerrar.

### 6.2 Correo de prueba por el pipeline real (antes de reiniciar)

`scripts/maintenance/send_test_alert.py` se niega fuera de sandbox salvo `--allow-non-sandbox` (verificado en el código).

```powershell
.venv\Scripts\python.exe scripts\maintenance\send_test_alert.py --allow-non-sandbox
.venv\Scripts\python.exe scripts\maintenance\send_test_alert.py --allow-non-sandbox --send
```

Esperado: `Ambiente: production`, `Destinatarios validos: N (invalidos omitidos: 0)` (N = los de d140), el asunto
`[SynkmetriX · ...] Alerta: correo de prueba de alertas` y, con `--send`, `Enviado.`. **Confirmar que el correo llegó**
a cada destinatario (definición de hecho). `No se envio` → revisar `ALERT_EMAIL_TO` y `ALERT_SMTP_*` (el log solo
muestra la clase de la excepción).

### 6.3 Reiniciar el 8000 y verificar

`Ctrl+C` y el comando de 3.3. Luego:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/heartbeat | Select-Object status
```

Y con la sesión de administrador, `GET /api/v1/scheduler/jobs` (o la pantalla del scheduler) debe listar `alerts_check`.
El job corre a los minutos :02, :17, :32 y :47: en el primer tick pueden llegar **alertas reales** (p. ej. `sync_fail`
de un canal mal configurado); es el comportamiento esperado.

**Seguir / abortar:** seguir si llegó el correo de prueba. Si no llega: dejar `ALERTS_ENABLED=false`, reiniciar y
seguir con el paso 7 (no bloquea el resto).

**Rescate:** solo `.env`: `ALERTS_ENABLED=false` y reiniciar. No toca la base.

## 7. Usuarios por rol (USR-07) y plantilla de D40

### 7.1 Usuarios `soporte` y `ejecutivo`

Se crean desde la interfaz: menú **Administración → Usuarios** (`frontend/src/features/admin/UsersSubPanel.tsx`,
`POST /api/v1/admin/users`, permiso `users.manage`), con nombre de usuario, contraseña y rol. Los roles los sembró
`seed_roles.py` en el paso 2. Contraseñas: las elige el usuario y se entregan fuera del chat. Cada ambiente tiene su
propia base de usuarios: esto es solo producción (el sandbox, aparte).

Verificación:

```powershell
docker compose exec -T postgres psql -U $u -d crm -At -c "select r.name, count(*) from user_roles ur join roles r on r.id = ur.role_id join users us on us.id = ur.user_id where us.is_active group by r.name order by 1"
```

Esperado: al menos una fila `soporte|1` y `ejecutivo|1` además de `admin`. Probar el login de cada usuario nuevo en
una ventana privada y comprobar que **no** ve la pestaña de Administración.

**Rescate:** desactivar el usuario desde la misma pantalla (no hace falta restaurar).

### 7.2 Mover `app/templates/reports/virtualpos.html` (D40)

Comprobado el 2026-11-10: el archivo **sigue** en el checkout principal (ignorado por git) y ningún código lo referencia.

```powershell
$priv = 'C:\Users\Usuario\Documents\CRM_privado'      # carpeta fuera del proyecto y de la nube; ⚠ verificar destino: pendiente del usuario (ficha d196)
New-Item -ItemType Directory -Force $priv | Out-Null
Move-Item "$repo\app\templates\reports\virtualpos.html" "$priv\virtualpos.html"
Test-Path "$repo\app\templates\reports\virtualpos.html"
```

Esperado: `False`. No abrir el archivo (contiene nombres reales).

### Fuera del guion técnico

- Enviar los pedidos de TER-01 (correo del usuario).
- VP-PAR-12 (limpieza de huérfanos): **no** se hace sin aprobación explícita.

## Cierre de la ventana

1. `Invoke-RestMethod http://127.0.0.1:8000/health` y login con los tres roles.
2. Variante 1B: borrar la copia del contenedor: `docker compose exec -T postgres rm "/tmp/$name"`.
3. Borrar la copia del `.env`: `[System.IO.File]::Delete("$bkdir\env_pre_ops11.bak")` (handoff §3: `Remove-Item` con
   rutas `C:` puede bloquearse).
4. Copia del respaldo fuera del equipo (disco externo y, cifrada, nube), si no se hizo en el paso 1.
5. Quitar las variables de la terminal: `Remove-Item Env:APP_ENV, Env:PYTHONPATH -ErrorAction SilentlyContinue`.
6. Reportar en el chat: revisión de `crm`, RTO, paridad TCH, conteos de Toku, correo recibido, usuarios creados.

## R. Rescate: restaurar el respaldo sobre `crm`

> Reemplaza todos los datos de `crm`. Solo con decisión explícita del usuario en el chat. Mismo procedimiento que
> `docs/operations/backups.md` («Restaurar en una emergencia»), con el dump copiado al contenedor para no depender de
> tuberías binarias de PowerShell.

1. Detener el backend 8000 (`Ctrl+C`). El 8001 usa `crm_sandbox` y no se toca.
2. Respaldar el estado actual para análisis (opcional pero recomendado): paso 1 con otro nombre.
3. Restaurar:

```powershell
$u   = (docker compose exec -T postgres printenv POSTGRES_USER).Trim()
$rd  = '<RESPALDO_1 o RESPALDO_4>'
docker cp $rd "${pgc}:/tmp/rescate.dump"                 # en la variante 1B, si sigue en /tmp, usar ese archivo
docker compose exec -T postgres pg_restore --list /tmp/rescate.dump | Measure-Object -Line
docker compose exec -T postgres dropdb -U $u --force crm
docker compose exec -T postgres createdb -U $u crm
docker compose exec -T postgres pg_restore -U $u -d crm --exit-on-error --no-owner /tmp/rescate.dump
docker compose exec -T postgres psql -U $u -d crm -At -c "select version_num from alembic_version"
docker compose exec -T postgres rm /tmp/rescate.dump
```

Esperado: `pg_restore` sin errores; revisión `20261103_0068` (con `RESPALDO_1`) o `20261104_0071` (con `RESPALDO_4`).
Con `RESPALDO_1` se puede repetir el paso 1B de conteos para comparar con lo anotado.

4. Si el problema fue de configuración, restaurar también `$bkdir\env_pre_ops11.bak` sobre `.env`.
5. Arrancar el 8000 (paso 3.3) y comprobar `/health` y el login. Avisar a los usuarios.

## Definición de hecho de S6 relacionada (`docs/tasks.md` §3.10)

- [ ] `crm` en `0071` (paso 2: `select version_num from alembic_version` = `20261104_0071`).
- [ ] Un respaldo restaurado en `crm_restore_test` con conteos iguales y **RTO anotado** (paso 1); **copia fuera del
      equipo verificada** (disco externo y, cifrada, nube).
- [ ] JWT nuevo y sesiones viejas rechazadas (paso 3.4).
- [ ] Un correo de alerta recibido (paso 6.2).
- [ ] Paridad de TCH dentro del umbral tras la recarga (paso 4.5).
- [ ] PR #8 (BCK-01a) integrado con la CI en verde (no es de la ventana; si no está, la variante 1B cubre el respaldo).
- [ ] Pedidos a terceros enviados con fecha (TER-01, fuera del guion técnico).
- Además (OPS-11, sin casilla propia en §3.10): `seed_roles.py` aplicado, backfill TK-PAR-04 y pepper de Toku
  (TK-PAR-01), usuarios `soporte` y `ejecutivo` (USR-07), plantilla de D40 fuera del proyecto.

## Lista de «⚠ verificar»

Abiertos, pendiente del usuario (ficha d196):

1. Carpeta de los Excel de TCH: la de `tch-reload.md` no existe; candidata `docs\Reportes_TCH` (paso 4).
5. Qué juego de reportes de Toku cargar y su carpeta (paso 5.2).
7. Carpeta de destino de la plantilla de D40 (paso 7.2).

Cerrados el 2026-11-10 (verificados en código y documentación):

2. Duración de la recarga de TCH: estimada en 55 a 90 min con tiempos registrados; se mantiene la reserva de 60 a
   120 min (paso 4, «Duración»). Sigue sin medirse en `crm`: anotar los tiempos reales.
3. ETL Core de TCH: no hay CLI; la línea de Python reproduce `_run_core_etl_background` (paso 4.3).
4. Consolidación: `consolidate_baseline.py --source tch` y luego `--apply --confirm-database crm` es el camino
   correcto (paso 4.4).
6. `-ExecutionPolicy Bypass`: no hace falta (`RemoteSigned` y scripts locales); comando de respaldo en el paso 1A.
