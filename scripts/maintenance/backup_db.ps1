<#
.SYNOPSIS
  BCK-01a: respaldo de una base PostgreSQL del CRM (pg_dump -Fc via docker compose), validado y con retencion.

.DESCRIPTION
  1. pg_dump -Fc dentro del contenedor `postgres`; el dump sale por stdout y se escribe en
     <Destination>\<db>_YYYYMMDD_HHmm.dump (primero como .partial; se renombra solo si todo sale bien).
  2. Valida el archivo con `pg_restore --list` (enviado por stdin al contenedor).
  3. Copia opcional a un disco externo (-ExternalCopyPath), con la misma retencion.
  4. Borra los respaldos mas viejos que -RetentionDays que calcen EXACTAMENTE con <db>_YYYYMMDD_HHmm.dump
     (nunca toca otros archivos, p. ej. crm_predeploy_*.dump).
  5. Log en <Destination>\logs\backup_db.log: fecha, base, nombre del archivo, tamano, entradas del TOC y estado.
     Sin datos personales ni credenciales.
  Sale con 0 si todo salio bien y con 1 si algo fallo. Con -AlertOnFailure, ademas manda un aviso por el
  pipeline de alertas (scripts\maintenance\backup_alert.py -> app/services/alerts.py).

.EXAMPLE
  .\scripts\maintenance\backup_db.ps1                                  # crm -> Downloads\CRM_backups
  .\scripts\maintenance\backup_db.ps1 -Database crm_sandbox -Destination C:\temp\bk
  .\scripts\maintenance\backup_db.ps1 -ExternalCopyPath E:\CRM_backups -AlertOnFailure
#>
[CmdletBinding()]
param(
    [string]$Database = 'crm',
    [string]$Destination = 'C:\Users\Usuario\Downloads\CRM_backups',
    [ValidateRange(1, 3650)][int]$RetentionDays = 14,
    [string]$ExternalCopyPath,
    [switch]$AlertOnFailure,
    [string]$ProjectDir
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\backup_common.ps1"
if (-not $ProjectDir) { $ProjectDir = Get-DefaultProjectDir }

$logFile = Join-Path $Destination 'logs\backup_db.log'
$partial = $null
$failureStage = 'inicio'

function Remove-OldBackups {
    param([string]$Folder, [string]$Db, [int]$Days)
    $pattern = '^' + [regex]::Escape($Db) + '_\d{8}_\d{4}\.dump$'
    $limit = (Get-Date).AddDays(-$Days)
    $removed = 0
    foreach ($f in Get-ChildItem -LiteralPath $Folder -File -Filter "$Db`_*.dump") {
        if ($f.Name -cmatch $pattern -and $f.LastWriteTime -lt $limit) {
            Remove-Item -LiteralPath $f.FullName -Force
            $removed++
        }
    }
    return $removed
}

try {
    Assert-DatabaseName $Database
    if (-not (Test-Path -LiteralPath $Destination)) { [void](New-Item -ItemType Directory -Path $Destination -Force) }
    Write-BackupLog $logFile "Inicio del respaldo de '$Database' (retencion $RetentionDays dias)."

    $failureStage = 'usuario de postgres'
    $pgUser = Get-PgUser -ProjectDir $ProjectDir

    $name = '{0}_{1}.dump' -f $Database, (Get-Date -Format 'yyyyMMdd_HHmm')
    $final = Join-Path $Destination $name
    if (Test-Path -LiteralPath $final) { throw "Ya existe $name (se corrio dos veces en el mismo minuto)." }
    $partial = "$final.partial"
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }

    $failureStage = 'pg_dump'
    $started = Get-Date
    $r = Invoke-Compose -ProjectDir $ProjectDir -OutFile $partial `
        -Arguments @('exec', '-T', 'postgres', 'pg_dump', '-U', $pgUser, '-Fc', '-d', $Database)
    if ($r.ExitCode -ne 0) { throw "pg_dump fallo (codigo $($r.ExitCode)): $(Get-ShortError $r.StdErr)" }
    $size = (Get-Item -LiteralPath $partial).Length
    if ($size -lt 100) { throw "El dump quedo vacio ($size bytes)." }

    $failureStage = 'validacion'
    $toc = Get-DumpTocCount -ProjectDir $ProjectDir -DumpFile $partial
    Move-Item -LiteralPath $partial -Destination $final
    $partial = $null
    $secs = [int]((Get-Date) - $started).TotalSeconds
    Write-BackupLog $logFile ("OK {0} ({1:N1} MB, {2} entradas en el TOC, {3} s)." -f $name, ($size / 1MB), $toc, $secs)

    if ($ExternalCopyPath) {
        $failureStage = 'copia externa'
        if (-not (Test-Path -LiteralPath $ExternalCopyPath)) {
            throw "El destino externo no esta disponible: $ExternalCopyPath (disco desconectado?)."
        }
        Copy-Item -LiteralPath $final -Destination (Join-Path $ExternalCopyPath $name)
        if ((Get-Item -LiteralPath (Join-Path $ExternalCopyPath $name)).Length -ne $size) {
            throw 'La copia externa no tiene el mismo tamano que el original.'
        }
        $extRemoved = Remove-OldBackups -Folder $ExternalCopyPath -Db $Database -Days $RetentionDays
        Write-BackupLog $logFile "Copia externa OK en $ExternalCopyPath (borrados por retencion: $extRemoved)."
    }

    $failureStage = 'retencion'
    $removed = Remove-OldBackups -Folder $Destination -Db $Database -Days $RetentionDays
    Write-BackupLog $logFile "Retencion: $removed respaldo(s) de '$Database' con mas de $RetentionDays dias borrado(s)."
    exit 0
}
catch {
    $msg = Get-ShortError $_.Exception.Message
    try { Write-BackupLog $logFile "FALLO en etapa '$failureStage' del respaldo de '$Database': $msg" 'ERROR' }
    catch { Write-Host "FALLO ($failureStage): $msg" }
    if ($partial -and (Test-Path -LiteralPath $partial)) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
    if ($AlertOnFailure) {
        $python = Join-Path $ProjectDir '.venv\Scripts\python.exe'
        $alertScript = Join-Path $PSScriptRoot 'backup_alert.py'
        try {
            # La configuracion de la app lee el .env del directorio actual: se corre desde la raiz del repo.
            Push-Location -LiteralPath $ProjectDir
            $env:PYTHONPATH = $ProjectDir
            & $python $alertScript --database $Database --stage $failureStage
            Write-BackupLog $logFile "Aviso de fallo por el pipeline de alertas (codigo $LASTEXITCODE; 0 = enviado)." 'WARN'
        } catch {
            Write-BackupLog $logFile 'No se pudo enviar el aviso de fallo.' 'WARN'
        } finally {
            Pop-Location
        }
    }
    exit 1
}
