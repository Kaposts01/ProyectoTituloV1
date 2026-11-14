<#
.SYNOPSIS
  BCK-01a: simulacro de restauracion. Restaura un dump -Fc en `crm_restore_test` y compara los conteos por tabla
  contra la base de origen.

.DESCRIPTION
  GUARDA DURA: el destino tiene que llamarse EXACTAMENTE `crm_restore_test`. Con cualquier otro nombre (crm,
  crm_sandbox, CRM_RESTORE_TEST...) el script se niega antes de tocar docker y sale con codigo 2. El drill borra y
  recrea la base destino, asi que nunca debe apuntar a una base con datos que importen.

  Pasos: valida el dump (pg_restore --list) -> DROP/CREATE de crm_restore_test -> pg_restore por stdin
  (--exit-on-error --no-owner --no-acl) -> conteo exacto de filas por tabla en origen y destino -> informe.

  La base de origen solo se LEE (count(*) por tabla). Si el origen recibio escrituras despues del dump, apareceran
  diferencias esperables en las tablas que cambiaron: para un drill limpio, comparar contra un origen quieto o
  correr el drill justo despues del respaldo.

  Codigos de salida: 0 = OK; 3 = DIFERENCIAS; 2 = rechazado por la guarda; 1 = error.

.EXAMPLE
  .\scripts\maintenance\restore_drill.ps1 -DumpFile C:\temp\bk\crm_sandbox_20261107_2010.dump -SourceDatabase crm_sandbox
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DumpFile,
    [string]$SourceDatabase = 'crm',
    [string]$TargetDatabase = 'crm_restore_test',
    [switch]$SkipCompare,
    [string]$ProjectDir
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\backup_common.ps1"

# ---- Guarda dura: antes de cualquier otra cosa ----
if (-not ($TargetDatabase -ceq $script:RestoreTestDatabase)) {
    Write-Host "RECHAZADO: el destino del drill debe ser exactamente '$($script:RestoreTestDatabase)' (se recibio '$TargetDatabase'). No se hizo nada."
    exit 2
}
if ($SourceDatabase -ceq $TargetDatabase) {
    Write-Host "RECHAZADO: el origen no puede ser la misma base del drill ('$TargetDatabase'). No se hizo nada."
    exit 2
}

if (-not $ProjectDir) { $ProjectDir = Get-DefaultProjectDir }
$logFile = Join-Path (Split-Path $DumpFile -Parent) 'logs\restore_drill.log'

try {
    Assert-DatabaseName $SourceDatabase
    if (-not (Test-Path -LiteralPath $DumpFile -PathType Leaf)) { throw "No existe el dump: $DumpFile" }
    $dumpName = Split-Path $DumpFile -Leaf
    Write-BackupLog $logFile "Drill: $dumpName -> $TargetDatabase (origen para comparar: $SourceDatabase)."

    $pgUser = Get-PgUser -ProjectDir $ProjectDir
    $toc = Get-DumpTocCount -ProjectDir $ProjectDir -DumpFile $DumpFile
    Write-BackupLog $logFile "Dump valido ($toc entradas en el TOC)."

    $r = Invoke-Compose -ProjectDir $ProjectDir -Arguments @('exec', '-T', 'postgres', 'dropdb', '-U', $pgUser, '--if-exists', '--force', $TargetDatabase)
    if ($r.ExitCode -ne 0) { throw "dropdb fallo: $(Get-ShortError $r.StdErr)" }
    $r = Invoke-Compose -ProjectDir $ProjectDir -Arguments @('exec', '-T', 'postgres', 'createdb', '-U', $pgUser, $TargetDatabase)
    if ($r.ExitCode -ne 0) { throw "createdb fallo: $(Get-ShortError $r.StdErr)" }

    $started = Get-Date
    $r = Invoke-Compose -ProjectDir $ProjectDir -InFile $DumpFile -Arguments @('exec', '-T', 'postgres', 'pg_restore',
        '-U', $pgUser, '-d', $TargetDatabase, '--exit-on-error', '--no-owner', '--no-acl')
    if ($r.ExitCode -ne 0) { throw "pg_restore fallo (codigo $($r.ExitCode)): $(Get-ShortError $r.StdErr)" }
    Write-BackupLog $logFile ("Restauracion completa en {0} s." -f [int]((Get-Date) - $started).TotalSeconds)

    if ($SkipCompare) { Write-BackupLog $logFile 'Comparacion omitida (-SkipCompare).'; exit 0 }

    $src = Get-TableCounts -ProjectDir $ProjectDir -PgUser $pgUser -Database $SourceDatabase
    $dst = Get-TableCounts -ProjectDir $ProjectDir -PgUser $pgUser -Database $TargetDatabase
    $names = @(@($src.Keys) + @($dst.Keys) | Sort-Object -Unique)
    $rows = foreach ($t in $names) {
        $a = if ($src.Contains($t)) { $src[$t] } else { $null }
        $b = if ($dst.Contains($t)) { $dst[$t] } else { $null }
        [pscustomobject]@{ Tabla = $t; Origen = $a; Restaurada = $b; Estado = $(if ($a -eq $b -and $null -ne $a) { 'OK' } else { 'DIFERENCIA' }) }
    }
    $rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
    $diff = @($rows | Where-Object { $_.Estado -ne 'OK' })
    $totalSrc = ($src.Values | Measure-Object -Sum).Sum
    $totalDst = ($dst.Values | Measure-Object -Sum).Sum
    if ($diff.Count -eq 0) {
        Write-BackupLog $logFile ("RESULTADO: OK ({0} tablas, {1} filas en origen y restaurada)." -f $names.Count, $totalSrc)
        exit 0
    }
    Write-BackupLog $logFile ("RESULTADO: DIFERENCIAS en {0} de {1} tablas ({2}). Filas origen {3} / restaurada {4}." -f `
        $diff.Count, $names.Count, (($diff | Select-Object -First 10 -ExpandProperty Tabla) -join ', '), $totalSrc, $totalDst) 'WARN'
    exit 3
}
catch {
    $msg = Get-ShortError $_.Exception.Message
    try { Write-BackupLog $logFile "FALLO del drill: $msg" 'ERROR' } catch { Write-Host "FALLO del drill: $msg" }
    exit 1
}
