<#
.SYNOPSIS
  BCK-01a: registra en el Programador de tareas de Windows el respaldo diario de la base `crm` a las 05:00.

.DESCRIPTION
  LO CORRE EL USUARIO, con su aprobacion (no lo corre ningun agente). Crea la tarea "<TaskName>" que ejecuta:
      pwsh (o powershell.exe si no hay pwsh) -File scripts\maintenance\backup_db.ps1 -Database crm [-ExternalCopyPath ...] [-AlertOnFailure]

  - Corre como el usuario actual y solo con la sesion iniciada: Docker Desktop vive en la sesion del usuario, sin
    sesion no hay contenedor que respaldar.
  - StartWhenAvailable: si el PC estaba apagado a las 05:00, corre apenas se pueda.
  - Limite de 2 horas por ejecucion; no despierta al PC.
  - Si la tarea ya existe, se niega salvo con -Force (la reemplaza).
  - Con -WhatIf muestra lo que haria sin registrar nada.

  Para quitarla: Unregister-ScheduledTask -TaskName "<TaskName>" -Confirm:$false

.EXAMPLE
  .\scripts\maintenance\register_backup_task.ps1 -WhatIf
  .\scripts\maintenance\register_backup_task.ps1 -AlertOnFailure
  .\scripts\maintenance\register_backup_task.ps1 -ExternalCopyPath E:\CRM_backups -AlertOnFailure -Force
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'SynkmetriX - Respaldo diario crm',
    [string]$At = '05:00',
    [string]$Destination = 'C:\Users\Usuario\Downloads\CRM_backups',
    [ValidateRange(1, 3650)][int]$RetentionDays = 14,
    [string]$ExternalCopyPath,
    [switch]$AlertOnFailure,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'backup_db.ps1'
$repoDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path -LiteralPath $script)) { throw "No existe $script" }

$shell = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if (-not $shell) { $shell = (Get-Command powershell.exe).Source }

$argList = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "`"$script`"",
    '-Database', 'crm', '-Destination', "`"$Destination`"", '-RetentionDays', $RetentionDays)
if ($ExternalCopyPath) { $argList += @('-ExternalCopyPath', "`"$ExternalCopyPath`"") }
if ($AlertOnFailure) { $argList += '-AlertOnFailure' }
$arguments = $argList -join ' '

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Force) {
    Write-Host "La tarea '$TaskName' ya existe. Use -Force para reemplazarla. No se hizo nada."
    exit 1
}

$action = New-ScheduledTaskAction -Execute $shell -Argument $arguments -WorkingDirectory $repoDir
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Write-Host "Tarea:     $TaskName (diaria a las $At)"
Write-Host "Programa:  $shell"
Write-Host "Argumentos: $arguments"
if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description 'BCK-01a: pg_dump diario de la base crm (docs/operations/backups.md).' -Force:$Force | Out-Null
    Write-Host "Registrada. Pruebela ya con: Start-ScheduledTask -TaskName '$TaskName' y revise $Destination\logs\backup_db.log"
}
