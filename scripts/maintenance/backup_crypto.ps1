# BCK-01a: cifrado de respaldos para la copia en la nube. Lo cargan encrypt_backup.ps1 y decrypt_backup.ps1 con
# dot-sourcing. No hace nada por si solo.
#
# Formato SYNKBK01 (solo .NET incluido en Windows / PowerShell, sin instalar nada):
#   "SYNKBK01" (8 bytes) | iteraciones PBKDF2 (int32 LE) | sal (16) | IV (16) | texto cifrado | HMAC-SHA256 (32)
# Clave: PBKDF2-HMAC-SHA256(frase, sal, iteraciones) -> 64 bytes: 32 para AES-256-CBC (PKCS7) y 32 para el HMAC.
# El HMAC cubre cabecera + texto cifrado (encrypt-then-MAC): al descifrar se verifica ANTES de escribir nada, asi
# una clave equivocada o un archivo alterado fallan sin producir basura. Procesa por bloques de 1 MB (sirve para
# dumps de cientos de MB sin cargarlos en memoria).

Set-StrictMode -Version 3.0

$script:CryptoMagic = [System.Text.Encoding]::ASCII.GetBytes('SYNKBK01')
$script:CryptoIterations = 600000
$script:CryptoChunk = 1MB
$script:KeyEnvVar = 'CRM_BACKUP_KEY'

function Test-PathInside {
    param([string]$Child, [string]$Parent)
    $sep = [System.IO.Path]::DirectorySeparatorChar
    $c = [System.IO.Path]::GetFullPath($Child).TrimEnd($sep) + $sep
    $p = [System.IO.Path]::GetFullPath($Parent).TrimEnd($sep) + $sep
    return $c.StartsWith($p, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-BackupPassphrase {
    <#
      Frase de cifrado: del archivo -KeyFile (primera linea) o, si no se pasa, de la variable de entorno CRM_BACKUP_KEY.
      Guardas: el archivo de clave no puede estar dentro del repo ni en la misma carpeta (o subcarpeta) que el
      respaldo de entrada o el archivo de salida. Minimo 20 caracteres. Nunca se imprime.
    #>
    param([string]$KeyFile, [string]$RepoDir, [string[]]$DataPaths)
    if ($KeyFile) {
        if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) { throw 'No existe el archivo de clave indicado.' }
        $keyFull = [System.IO.Path]::GetFullPath($KeyFile)
        if ($RepoDir -and (Test-PathInside $keyFull $RepoDir)) {
            throw 'RECHAZADO: el archivo de clave esta dentro del repo. Guardelo fuera (gestor de claves o un USB aparte).'
        }
        foreach ($p in $DataPaths) {
            if (-not $p) { continue }
            $dir = Split-Path ([System.IO.Path]::GetFullPath($p)) -Parent
            if (Test-PathInside $keyFull $dir) {
                throw 'RECHAZADO: el archivo de clave esta en la misma carpeta que el respaldo. La clave nunca va junto al archivo.'
            }
        }
        $pass = Get-Content -LiteralPath $KeyFile -TotalCount 1 -Encoding UTF8
    } else {
        $pass = [Environment]::GetEnvironmentVariable($script:KeyEnvVar)
        if (-not $pass) { throw "Falta la clave: defina la variable de entorno $($script:KeyEnvVar) o pase -KeyFile (fuera del repo)." }
    }
    $pass = ('' + $pass).Trim()
    if ($pass.Length -lt 20) { throw 'La frase de cifrado debe tener al menos 20 caracteres.' }
    return $pass
}

function New-BackupKeys {
    param([string]$Passphrase, [byte[]]$Salt, [int]$Iterations)
    $kdf = New-Object System.Security.Cryptography.Rfc2898DeriveBytes(
        [System.Text.Encoding]::UTF8.GetBytes($Passphrase), $Salt, $Iterations,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256)
    try { $bytes = $kdf.GetBytes(64) } finally { $kdf.Dispose() }
    return @{ Enc = [byte[]]$bytes[0..31]; Mac = [byte[]]$bytes[32..63] }
}

function Read-Exactly {
    param([System.IO.Stream]$Stream, [byte[]]$Buffer, [int]$Count)
    $read = 0
    while ($read -lt $Count) {
        $n = $Stream.Read($Buffer, $read, $Count - $read)
        if ($n -le 0) { throw 'Fin de archivo inesperado.' }
        $read += $n
    }
}

function Invoke-CipherStream {
    # Pasa $Length bytes de $In por el transformador AES y escribe en $Out. Con $Mac, autentica lo que se escribe.
    param($In, $Out, [long]$Length, $Transform, $Mac)
    $chunk = [int]$script:CryptoChunk
    $buf = New-Object byte[] $chunk
    $outBuf = New-Object byte[] ($chunk + 32)
    $remaining = $Length
    while ($remaining -gt $chunk) {
        Read-Exactly $In $buf $chunk
        $n = $Transform.TransformBlock($buf, 0, $chunk, $outBuf, 0)
        if ($n -gt 0) {
            $Out.Write($outBuf, 0, $n)
            if ($Mac) { [void]$Mac.TransformBlock($outBuf, 0, $n, $null, 0) }
        }
        $remaining -= $chunk
    }
    $last = [int]$remaining
    if ($last -gt 0) { Read-Exactly $In $buf $last }
    $final = $Transform.TransformFinalBlock($buf, 0, $last)
    if ($final.Length -gt 0) {
        $Out.Write($final, 0, $final.Length)
        if ($Mac) { [void]$Mac.TransformBlock($final, 0, $final.Length, $null, 0) }
    }
}

function Protect-BackupFile {
    param([Parameter(Mandatory)][string]$InFile, [Parameter(Mandatory)][string]$OutFile, [Parameter(Mandatory)][string]$Passphrase)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $salt = New-Object byte[] 16
    $iv = New-Object byte[] 16
    $rng.GetBytes($salt); $rng.GetBytes($iv); $rng.Dispose()
    $keys = New-BackupKeys $Passphrase $salt $script:CryptoIterations
    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'; $aes.Key = $keys.Enc; $aes.IV = $iv
    $hmac = New-Object System.Security.Cryptography.HMACSHA256 (, $keys.Mac)
    $in = [System.IO.File]::OpenRead($InFile)
    $out = [System.IO.File]::Open($OutFile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        [byte[]]$header = $script:CryptoMagic + [System.BitConverter]::GetBytes([int]$script:CryptoIterations) + $salt + $iv
        $out.Write($header, 0, $header.Length)
        [void]$hmac.TransformBlock($header, 0, $header.Length, $null, 0)
        $enc = $aes.CreateEncryptor()
        Invoke-CipherStream -In $in -Out $out -Length $in.Length -Transform $enc -Mac $hmac
        $enc.Dispose()
        [void]$hmac.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        $out.Write($hmac.Hash, 0, 32)
    } finally { $in.Dispose(); $out.Dispose(); $aes.Dispose(); $hmac.Dispose() }
}

function Unprotect-BackupFile {
    param([Parameter(Mandatory)][string]$InFile, [Parameter(Mandatory)][string]$OutFile, [Parameter(Mandatory)][string]$Passphrase)
    $headerLen = 8 + 4 + 16 + 16
    $in = [System.IO.File]::OpenRead($InFile)
    try {
        if ($in.Length -lt ($headerLen + 16 + 32)) { throw 'El archivo es demasiado corto: no es un respaldo cifrado SYNKBK01.' }
        $header = New-Object byte[] $headerLen
        Read-Exactly $in $header $headerLen
        if ([System.Text.Encoding]::ASCII.GetString($header, 0, 8) -ne 'SYNKBK01') { throw 'Formato desconocido: falta la cabecera SYNKBK01.' }
        $iter = [System.BitConverter]::ToInt32($header, 8)
        if ($iter -lt 100000 -or $iter -gt 10000000) { throw 'Cabecera invalida (iteraciones fuera de rango).' }
        $salt = [byte[]]$header[12..27]
        $iv = [byte[]]$header[28..43]
        $keys = New-BackupKeys $Passphrase $salt $iter
        $ctLen = $in.Length - $headerLen - 32

        # 1) Verificar el HMAC antes de escribir nada.
        $hmac = New-Object System.Security.Cryptography.HMACSHA256 (, $keys.Mac)
        [void]$hmac.TransformBlock($header, 0, $headerLen, $null, 0)
        $buf = New-Object byte[] ([int]$script:CryptoChunk)
        $remaining = $ctLen
        while ($remaining -gt 0) {
            $n = [int][Math]::Min([long]$buf.Length, $remaining)
            Read-Exactly $in $buf $n
            [void]$hmac.TransformBlock($buf, 0, $n, $null, 0)
            $remaining -= $n
        }
        [void]$hmac.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        $tag = New-Object byte[] 32
        Read-Exactly $in $tag 32
        $expected = $hmac.Hash
        $hmac.Dispose()
        $diff = 0
        for ($i = 0; $i -lt 32; $i++) { $diff = $diff -bor ($tag[$i] -bxor $expected[$i]) }
        if ($diff -ne 0) { throw 'Clave incorrecta o archivo alterado/corrupto (el HMAC no coincide). No se escribio nada.' }

        # 2) Descifrar.
        [void]$in.Seek($headerLen, [System.IO.SeekOrigin]::Begin)
        $aes = [System.Security.Cryptography.Aes]::Create()
        $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'; $aes.Key = $keys.Enc; $aes.IV = $iv
        $out = [System.IO.File]::Open($OutFile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
        try {
            $dec = $aes.CreateDecryptor()
            Invoke-CipherStream -In $in -Out $out -Length $ctLen -Transform $dec
            $dec.Dispose()
        } finally { $out.Dispose(); $aes.Dispose() }
    } finally { $in.Dispose() }
}
