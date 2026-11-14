<#
.SYNOPSIS
  BCK-01a: respaldo de una base PostgreSQL del CRM (pg_dump -Fc via docker compose), validado y con retencion.

.DESCRIPTION
  1. pg_dump -Fc dentro del contenedor `postgres`; el dump sale por stdout y se escribe en
     <Destination>\<db>_YYYYMMDD_HHmm.dump (primero como .partial; se renombra solo si todo sale bien).
  2. Valida el archivo con `pg_restore --list` (enviado por stdin al contenedor).
  3. Copia opcional a un disco externo (-ExternalCopyPath), atomica (<nombre>.partial y renombre al final), con la
     misma retencion.
  4. Borra los respaldos mas viejos que -RetentionDays que calcen EXACTAMENTE con <db>_YYYYMMDD_HHmm.dump, y los
     <db>_YYYYMMDD_HHmm.dump.partial de mas de 1 dia (nunca toca otros archivos, p. ej. crm_predeploy_*.dump).
     La retencion local se aplica aunque falle la copia externa; en ese caso el script igual sale con 1 y avisa.
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

    # Copia externa y retencion local: la retencion local corre siempre, aunque la copia externa falle.
    $failureStage = 'retencion'
    $externalError = Invoke-BackupCopyAndRetention -DumpFile $final -Destination $Destination -Database $Database `
        -RetentionDays $RetentionDays -LogFile $logFile -ExternalCopyPath $ExternalCopyPath
    if ($externalError) {
        $failureStage = 'copia externa'
        throw $externalError
    }
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
