<#
.SYNOPSIS
  BCK-01a: cifra un respaldo (.dump) para subirlo a la nube. AES-256 + HMAC-SHA256 con .NET (sin instalar nada).

.DESCRIPTION
  La frase de cifrado se lee de la variable de entorno CRM_BACKUP_KEY o de -KeyFile (primera linea). El archivo de
  clave debe estar FUERA del repo y FUERA de la carpeta del respaldo: el script se niega en caso contrario.
  Nunca imprime la clave.

  Por defecto, despues de cifrar descifra a un temporal y compara el SHA-256 con el original (-SkipVerify lo omite).
  Formato y detalles en backup_crypto.ps1 y en docs/operations/backups.md.

  Codigos de salida: 0 = OK; 1 = error o rechazo.

.EXAMPLE
  $env:CRM_BACKUP_KEY = '<frase larga>'   # solo en esta sesion
  .\scripts\maintenance\encrypt_backup.ps1 -InputFile C:\Users\Usuario\Downloads\CRM_backups\crm_20261108_0500.dump `
      -OutputFile D:\Nube\crm_20261108_0500.dump.enc
.EXAMPLE
  .\scripts\maintenance\encrypt_backup.ps1 -InputFile ...\crm_20261108_0500.dump -KeyFile E:\claves\crm_backup.key
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InputFile,
    [string]$OutputFile,
    [string]$KeyFile,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\backup_crypto.ps1"
$repoDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$partial = $null
$tmp = $null

try {
    if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) { throw "No existe el archivo de entrada: $InputFile" }
    $InputFile = (Resolve-Path -LiteralPath $InputFile).ProviderPath
    if (-not $OutputFile) { $OutputFile = "$InputFile.enc" }
    $OutputFile = [System.IO.Path]::GetFullPath($OutputFile)
    if (Test-Path -LiteralPath $OutputFile) { throw "Ya existe el archivo de salida: $OutputFile (no se sobrescribe)." }

    $pass = Get-BackupPassphrase -KeyFile $KeyFile -RepoDir $repoDir -DataPaths @($InputFile, $OutputFile)

    $partial = "$OutputFile.partial"
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    $started = Get-Date
    Protect-BackupFile -InFile $InputFile -OutFile $partial -Passphrase $pass

    if (-not $SkipVerify) {
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("synk_verify_{0}.tmp" -f [guid]::NewGuid().ToString('N'))
        Unprotect-BackupFile -InFile $partial -OutFile $tmp -Passphrase $pass
        $h1 = (Get-FileHash -LiteralPath $InputFile -Algorithm SHA256).Hash
        $h2 = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash
        if ($h1 -ne $h2) { throw 'La verificacion fallo: el archivo descifrado no coincide con el original.' }
    }
    Move-Item -LiteralPath $partial -Destination $OutputFile
    $partial = $null
    Write-Host ("OK: {0} cifrado en {1} s{2}." -f (Split-Path $OutputFile -Leaf), [int]((Get-Date) - $started).TotalSeconds,
        $(if ($SkipVerify) { '' } else { ' (verificado: descifra igual al original)' }))
    exit 0
}
catch {
    Write-Host "FALLO del cifrado: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($partial -and (Test-Path -LiteralPath $partial)) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
    if ($tmp -and (Test-Path -LiteralPath $tmp)) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
}
