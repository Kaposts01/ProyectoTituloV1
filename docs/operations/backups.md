# Respaldos de la base de datos (BCK-01a)

Runbook de respaldo, cifrado y restauración de PostgreSQL del CRM. Todos los scripts viven en
`scripts/maintenance/` y se corren desde la raíz del repo, en PowerShell, con `docker compose` arriba.

| Script | Qué hace |
|---|---|
| `backup_db.ps1` | `pg_dump -Fc` vía docker, valida con `pg_restore --list`, copia opcional a disco externo, retención y log. |
| `encrypt_backup.ps1` / `decrypt_backup.ps1` | Cifra/descifra un `.dump` para la copia en la nube (AES-256 + HMAC-SHA256, sin instalar nada). |
| `restore_drill.ps1` | Restaura un dump en `crm_restore_test` y compara los conteos por tabla contra el origen. |
| `register_backup_task.ps1` | Registra la tarea diaria de las 05:00 en el Programador de tareas (lo corre el usuario). |
| `backup_alert.py` | Aviso de "respaldo fallido" por el pipeline de alertas (`app/services/alerts.py`). |
| `backup_common.ps1`, `backup_crypto.ps1` | Funciones compartidas (no se corren solas). |

## Cómo funciona

1. **Respaldo diario (05:00).** La tarea programada corre `backup_db.ps1 -Database crm`:
   - `docker compose exec -T postgres pg_dump -U <POSTGRES_USER> -Fc -d crm`. El dump sale por stdout y se
     escribe en `C:\Users\Usuario\Downloads\CRM_backups\crm_YYYYMMDD_HHmm.dump` (primero como `.partial`).
     No se crean archivos dentro del contenedor.
   - Se valida con `pg_restore --list` (el archivo entra por stdin). Si no es un archivo válido, se borra el
     `.partial` y el script sale con código 1.
   - Con `-ExternalCopyPath E:\CRM_backups` copia el dump al disco externo y comprueba el tamaño.
   - Retención: borra los archivos de más de 14 días (`-RetentionDays`) que calcen **exactamente** con
     `<db>_YYYYMMDD_HHmm.dump`, en la carpeta local y en la externa. Nunca toca otros archivos
     (por ejemplo `crm_predeploy_D127_20261103_0039.dump`).
   - Log: `CRM_backups\logs\backup_db.log` (fecha, base, archivo, tamaño, entradas del TOC, duración, estado).
     Sin datos personales ni credenciales; los errores se recortan a su primera línea.
   - Con `-AlertOnFailure`, si algo falla manda un aviso por el mismo SMTP de las alertas
     (`ALERT_EMAIL_TO`, `ALERT_SMTP_*`). El aviso solo lleva la base y la etapa que falló.
2. **Copia fuera del PC (decisión d156 c).** Disco externo (`-ExternalCopyPath`) y nube **cifrada**:
   el `.dump` se cifra con `encrypt_backup.ps1` y solo el `.dump.enc` se sube a la nube.
3. **Simulacro de restauración.** `restore_drill.ps1` prueba que el respaldo se puede restaurar de verdad.

Funciona con PowerShell 7 (`pwsh`) y con Windows PowerShell 5.1: los flujos binarios se copian byte a byte con
`System.Diagnostics.Process` (las tuberías de PowerShell 5.1 corrompen binarios).

## Cifrado para la nube

Herramienta: .NET incluido en Windows/PowerShell (no hay que instalar nada). Formato `SYNKBK01`:
PBKDF2-HMAC-SHA256 (600 000 iteraciones, sal aleatoria) → AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC).
Al descifrar se verifica el HMAC **antes** de escribir: una clave equivocada o un archivo alterado no producen salida.
`encrypt_backup.ps1` además descifra a un temporal y compara el SHA-256 con el original.

**La clave nunca va junto al archivo ni en el repo.** Se lee de:
- la variable de entorno `CRM_BACKUP_KEY` (solo en la sesión: `$env:CRM_BACKUP_KEY = '...'`), o
- `-KeyFile <ruta>`: primera línea de un archivo. Los scripts se niegan si el archivo está dentro del repo o en la
  misma carpeta (o subcarpeta) que el respaldo o la salida.

Mínimo 20 caracteres. Guarde la frase en un gestor de contraseñas **y** en papel en un lugar seguro: sin la frase,
la copia de la nube es irrecuperable.

```powershell
$env:CRM_BACKUP_KEY = Read-Host 'Frase de cifrado'   # no queda en el historial
.\scripts\maintenance\encrypt_backup.ps1 -InputFile C:\Users\Usuario\Downloads\CRM_backups\crm_20261108_0500.dump `
    -OutputFile "$env:USERPROFILE\OneDrive\CRM_backups\crm_20261108_0500.dump.enc"
Remove-Item Env:CRM_BACKUP_KEY
```

### Alternativas (si se prefiere una herramienta estándar)

Los archivos `SYNKBK01` solo se abren con `decrypt_backup.ps1` (está en el repo; conviene guardar también una
copia del script junto a la frase, fuera de la nube). Si se prefiere un formato estándar:

- **7-Zip (AES-256)**, tras instalar 7-Zip:
  `& 'C:\Program Files\7-Zip\7z.exe' a -t7z -mhe=on -p"$env:CRM_BACKUP_KEY" crm_20261108_0500.7z crm_20261108_0500.dump`
  y para abrir: `7z x crm_20261108_0500.7z -p"$env:CRM_BACKUP_KEY"`. (Ojo: la frase queda visible en la línea de
  comandos del proceso mientras corre; omitir `-p...` para que 7-Zip la pida.)
- **age** (`winget install FiloSottile.age`): con clave pública, el PC no necesita la privada para cifrar.
  `age-keygen -o C:\ruta\fuera\del\repo\age.key` (guardar la privada fuera del PC),
  cifrar: `age -r <clave_publica> -o crm.dump.age crm.dump`, descifrar: `age -d -i age.key -o crm.dump crm.dump.age`.

## Cómo verificar

- **Cada día:** revisar `CRM_backups\logs\backup_db.log`: debe haber una línea `OK crm_YYYYMMDD_0500.dump (...)`.
  En el Programador de tareas, "Resultado de la última ejecución" debe ser `0x0`.
- **Cada mes (o después de un cambio de esquema):** simulacro con el último respaldo:

```powershell
.\scripts\maintenance\restore_drill.ps1 -DumpFile C:\Users\Usuario\Downloads\CRM_backups\crm_20261108_0500.dump -SourceDatabase crm
```

  Restaura en `crm_restore_test` (la borra y la recrea) y compara el conteo exacto de filas por tabla contra `crm`
  (solo lectura). Resultado: `RESULTADO: OK` (código 0) o `RESULTADO: DIFERENCIAS` (código 3). Si `crm` recibió
  escrituras después del respaldo, las tablas que cambiaron saldrán con diferencias: correr el drill justo después
  del respaldo o fuera de horario de sincronizaciones.
- **Copia de la nube (trimestral):** descifrar el `.dump.enc` más reciente a una carpeta temporal y pasarle el drill.

Guarda dura del drill: el destino debe llamarse exactamente `crm_restore_test`; con otro nombre se niega
(código 2) antes de tocar docker. Tampoco acepta que el origen sea `crm_restore_test`.

## Restaurar en una emergencia

> La restauración sobre `crm` reemplaza todos los datos actuales. Hacerla solo con la decisión explícita del
> responsable, y con la app y las sincronizaciones detenidas.

1. **Detener** el backend, el frontend y cualquier tarea programada de sincronización (para que nadie escriba).
2. **Respaldar el estado actual** aunque esté dañado (sirve para análisis posterior):
   `.\scripts\maintenance\backup_db.ps1 -Database crm -Destination C:\Users\Usuario\Downloads\CRM_backups\pre_restore`
3. **Elegir el dump.** El más reciente válido de `CRM_backups` o del disco externo. Si solo queda la nube:
   descargar el `.dump.enc` y descifrarlo con `decrypt_backup.ps1 -InputFile ... -OutputFile C:\restore\crm.dump`.
4. **Probarlo primero** en `crm_restore_test` (sin comparar, porque `crm` está dañada):
   `.\scripts\maintenance\restore_drill.ps1 -DumpFile C:\restore\crm.dump -SkipCompare`
   y revisar a mano en `crm_restore_test` que los datos se ven bien (socios, cobros recientes, `alembic_version`).
5. **Restaurar sobre `crm`** (a mano, a propósito no hay script):

```powershell
$u = (docker compose exec -T postgres printenv POSTGRES_USER).Trim()
docker compose exec -T postgres dropdb -U $u --force crm
docker compose exec -T postgres createdb -U $u crm
# El dump entra por stdin. En PowerShell 7.4+ la redireccion binaria funciona; en 5.1 usar cmd:
cmd /c "docker compose exec -T postgres pg_restore -U $u -d crm --exit-on-error --no-owner < C:\restore\crm.dump"
```

6. **Verificar:** `.venv\Scripts\alembic.exe current` debe mostrar la misma revisión que el código desplegado; abrir
   el panel y revisar el dashboard y las últimas sincronizaciones.
7. **Reanudar** backend, frontend y sincronizaciones. Las sincronizaciones traerán lo que pasó entre el respaldo y
   ahora desde los proveedores (VirtualPOS, Toku, Payku). Los cambios hechos a mano en el CRM en ese intervalo
   se pierden: anotarlos.

## Si el respaldo falla

El script sale con código 1, escribe `[ERROR] FALLO en etapa '<etapa>'` en el log y, con `-AlertOnFailure`, manda
un correo "respaldo de la base crm fallido".

| Etapa en el log | Causa probable | Qué hacer |
|---|---|---|
| `usuario de postgres` | Docker Desktop apagado o el contenedor caído | Abrir Docker Desktop, `docker compose up -d postgres`, correr el respaldo a mano. |
| `pg_dump` | Base inexistente, disco del contenedor lleno, conexión cortada | Leer el mensaje del log; `docker compose logs postgres`. |
| `validacion` | Dump truncado o corrupto | Revisar espacio libre en el disco de `CRM_backups`; reintentar. |
| `copia externa` | Disco externo desconectado o con otra letra | Conectarlo; el respaldo local ya quedó bien (está en el log como `OK`). |
| `retencion` | Archivo en uso o sin permisos | El respaldo ya quedó; revisar permisos de la carpeta. |

Reintento manual: `.\scripts\maintenance\backup_db.ps1` (mismos parámetros que la tarea). Si fallan dos días
seguidos, tratarlo como incidente: sin respaldo reciente no hay forma de recuperar datos.

## Activar en producción (una sola vez, lo hace el usuario)

1. Respaldo y drill de prueba a mano:
   `.\scripts\maintenance\backup_db.ps1` y luego
   `.\scripts\maintenance\restore_drill.ps1 -DumpFile <dump recién creado> -SourceDatabase crm`.
2. Ver lo que registraría: `.\scripts\maintenance\register_backup_task.ps1 -AlertOnFailure -WhatIf`.
3. Registrar: `.\scripts\maintenance\register_backup_task.ps1 -AlertOnFailure` (agregar
   `-ExternalCopyPath E:\CRM_backups` si el disco externo queda conectado; si no, copiarlo a mano semanalmente).
4. Probar la tarea: `Start-ScheduledTask -TaskName 'SynkmetriX - Respaldo diario crm'` y revisar el log.
5. Definir la frase de cifrado, guardarla fuera del PC y subir el primer `.dump.enc` a la nube.

La tarea corre con la sesión del usuario iniciada (Docker Desktop vive en esa sesión). Si el PC estaba apagado a
las 05:00, corre apenas se encienda (`StartWhenAvailable`).
