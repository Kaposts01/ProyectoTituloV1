<#
.SYNOPSIS
  BCK-01a: descifra un respaldo .dump.enc (formato SYNKBK01) creado con encrypt_backup.ps1.

.DESCRIPTION
  La frase se lee de CRM_BACKUP_KEY o de -KeyFile (fuera del repo y fuera de la carpeta del respaldo).
  Verifica el HMAC ANTES de escribir: con una clave equivocada o un archivo alterado no se crea ningun archivo.
  Despues, valide el dump con restore_drill.ps1 (restaura en crm_restore_test y compara conteos).

  Codigos de salida: 0 = OK; 1 = error, clave incorrecta o rechazo.

.EXAMPLE
  $env:CRM_BACKUP_KEY = '<frase larga>'
  .\scripts\maintenance\decrypt_backup.ps1 -InputFile D:\Nube\crm_20261108_0500.dump.enc -OutputFile C:\restore\crm_20261108_0500.dump
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InputFile,
    [string]$OutputFile,
    [string]$KeyFile
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\backup_crypto.ps1"
$repoDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$partial = $null

try {
    if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) { throw "No existe el archivo de entrada: $InputFile" }
    $InputFile = (Resolve-Path -LiteralPath $InputFile).ProviderPath
    if (-not $OutputFile) {
        if ($InputFile -notmatch '\.enc$') { throw 'Indique -OutputFile (la entrada no termina en .enc).' }
        $OutputFile = $InputFile -replace '\.enc$', ''
    }
    $OutputFile = [System.IO.Path]::GetFullPath($OutputFile)
    if (Test-Path -LiteralPath $OutputFile) { throw "Ya existe el archivo de salida: $OutputFile (no se sobrescribe)." }

    $pass = Get-BackupPassphrase -KeyFile $KeyFile -RepoDir $repoDir -DataPaths @($InputFile, $OutputFile)
    $partial = "$OutputFile.partial"
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    Unprotect-BackupFile -InFile $InputFile -OutFile $partial -Passphrase $pass
    Move-Item -LiteralPath $partial -Destination $OutputFile
    $partial = $null
    Write-Host "OK: descifrado en $OutputFile. Siguiente paso: restore_drill.ps1 -DumpFile `"$OutputFile`""
    exit 0
}
catch {
    Write-Host "FALLO del descifrado: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($partial -and (Test-Path -LiteralPath $partial)) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
}
