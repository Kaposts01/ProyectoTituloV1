# BCK-01a: funciones compartidas por backup_db.ps1, restore_drill.ps1 y el cifrado de respaldos.
# Se carga con dot-sourcing (. "$PSScriptRoot\backup_common.ps1"). No hace nada por si solo.
#
# Por que System.Diagnostics.Process y no tuberias de PowerShell: Windows PowerShell 5.1 (el que usa el
# Programador de tareas si no hay pwsh) reescribe la salida binaria de los comandos nativos como texto y
# corrompe el dump. Copiar los flujos (stdout/stdin) byte a byte evita el problema en 5.1 y en 7.
# Tampoco se crean archivos temporales dentro del contenedor: el dump viaja por stdout y vuelve por stdin.

Set-StrictMode -Version 3.0

$script:RestoreTestDatabase = 'crm_restore_test'

function Get-DefaultProjectDir {
    # scripts\maintenance -> raiz del repo (donde estan compose.yaml y el .env que lee docker compose).
    return (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
}

function Assert-DatabaseName {
    param([Parameter(Mandatory)][string]$Name)
    # Solo nombres simples: evita inyeccion en los argumentos de docker y en el patron de archivos.
    if ($Name -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') {
        throw "Nombre de base invalido: '$Name' (solo letras, numeros y guion bajo)."
    }
}

function ConvertTo-ProcessArgument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Invoke-Compose {
    <#
      Corre `docker compose -f <ProjectDir>\compose.yaml --project-directory <ProjectDir> <Arguments>`.
      -InFile: el archivo se envia por stdin (binario). -OutFile: stdout se guarda tal cual (binario).
      Sin -OutFile, stdout se devuelve como texto en .StdOut. Siempre devuelve ExitCode y StdErr.
    #>
    param(
        [Parameter(Mandatory)][string]$ProjectDir,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$InFile,
        [string]$OutFile
    )
    $compose = Join-Path $ProjectDir 'compose.yaml'
    if (-not (Test-Path -LiteralPath $compose)) { throw "No existe $compose (revise -ProjectDir)." }
    $all = @('compose', '-f', $compose, '--project-directory', $ProjectDir) + $Arguments
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'docker'
    $psi.Arguments = ($all | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' '
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = [bool]$InFile
    $psi.WorkingDirectory = $ProjectDir

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    # Windows PowerShell 5.1 (.NET Framework) crea el StreamWriter de stdin con Console.InputEncoding y, si esa
    # codificacion tiene preambulo (BOM UTF-8), lo escribe al inicio y corrompe el dump. Se usa UTF-8 sin BOM
    # mientras arranca el proceso. En PowerShell 7 se fija directamente StandardInputEncoding.
    $prevInputEncoding = $null
    if ($InFile) {
        if ($psi.PSObject.Properties['StandardInputEncoding']) {
            $psi.StandardInputEncoding = New-Object System.Text.UTF8Encoding $false
        } else {
            try { $prevInputEncoding = [Console]::InputEncoding; [Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false }
            catch { $prevInputEncoding = $null }
        }
    }
    try { [void]$proc.Start() }
    finally { if ($prevInputEncoding) { try { [Console]::InputEncoding = $prevInputEncoding } catch { } } }
    $errTask = $proc.StandardError.ReadToEndAsync()
    $stdout = $null
    $outTask = $null
    $outStream = $null
    try {
        if ($OutFile) {
            $outStream = [System.IO.File]::Open($OutFile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
            $outTask = $proc.StandardOutput.BaseStream.CopyToAsync($outStream)
        } else {
            $outTask = $proc.StandardOutput.ReadToEndAsync()
        }
        if ($InFile) {
            $inStream = [System.IO.File]::OpenRead($InFile)
            try { $inStream.CopyTo($proc.StandardInput.BaseStream) }
            catch [System.IO.IOException] { }  # el proceso cerro stdin antes (fallo): se reporta por el codigo de salida
            finally { $inStream.Dispose(); try { $proc.StandardInput.Close() } catch { } }
        }
        $outTask.Wait()
        if (-not $OutFile) { $stdout = $outTask.Result }
        $proc.WaitForExit()
    } finally {
        if ($outStream) { $outStream.Dispose() }
    }
    return [pscustomobject]@{
        ExitCode = $proc.ExitCode
        StdOut   = $stdout
        StdErr   = $errTask.Result
    }
}

function Get-PgUser {
    param([Parameter(Mandatory)][string]$ProjectDir)
    $r = Invoke-Compose -ProjectDir $ProjectDir -Arguments @('exec', '-T', 'postgres', 'printenv', 'POSTGRES_USER')
    $user = ("" + $r.StdOut).Trim()
    if ($r.ExitCode -ne 0 -or -not $user) {
        throw "No se pudo obtener POSTGRES_USER del contenedor (codigo $($r.ExitCode)). Esta corriendo docker compose?"
    }
    return $user
}

function Get-ShortError {
    # Primera linea del error, recortada: el log no debe crecer con volcados ni arrastrar filas de datos.
    param([string]$Text)
    $line = (("" + $Text) -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
    if (-not $line) { return '(sin detalle)' }
    if ($line.Length -gt 200) { $line = $line.Substring(0, 200) + '...' }
    return $line.Trim()
}

function Write-BackupLog {
    param([Parameter(Mandatory)][string]$LogFile, [Parameter(Mandatory)][string]$Message, [string]$Level = 'INFO')
    $dir = Split-Path $LogFile -Parent
    if (-not (Test-Path -LiteralPath $dir)) { [void](New-Item -ItemType Directory -Path $dir -Force) }
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Remove-OldBackups {
    <#
      Retencion de una carpeta. Borra solo:
        - <db>_YYYYMMDD_HHmm.dump con mas de -Days dias, y
        - <db>_YYYYMMDD_HHmm.dump.partial con mas de 1 dia (restos de un respaldo o copia que se corto a la mitad;
          uno en curso es reciente y no se toca).
      Nunca toca otros archivos (p. ej. crm_predeploy_*.dump). Devuelve la cantidad de archivos borrados.
    #>
    param([Parameter(Mandatory)][string]$Folder, [Parameter(Mandatory)][string]$Database, [Parameter(Mandatory)][int]$Days)
    $base = '^' + [regex]::Escape($Database) + '_\d{8}_\d{4}\.dump'
    $dumpPattern = $base + '$'
    $partialPattern = $base + '\.partial$'
    $limit = (Get-Date).AddDays(-$Days)
    $partialLimit = (Get-Date).AddDays(-1)
    $removed = 0
    foreach ($f in Get-ChildItem -LiteralPath $Folder -File -Filter "$Database`_*") {
        $old = ($f.Name -cmatch $dumpPattern -and $f.LastWriteTime -lt $limit) -or
               ($f.Name -cmatch $partialPattern -and $f.LastWriteTime -lt $partialLimit)
        if ($old) {
            Remove-Item -LiteralPath $f.FullName -Force
            $removed++
        }
    }
    return $removed
}

function Copy-BackupToExternal {
    <#
      Copia atomica al disco externo: primero <nombre>.partial, se compara el tamano y recien entonces se renombra
      al nombre definitivo. Si algo falla (disco que se desconecta a la mitad, sin espacio) se borra el .partial y se
      relanza el error: nunca queda un archivo truncado con el nombre definitivo. Devuelve la ruta final.
    #>
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Folder)
    if (-not (Test-Path -LiteralPath $Folder -PathType Container)) {
        throw "El destino externo no esta disponible: $Folder (disco desconectado?)."
    }
    $name = Split-Path $Source -Leaf
    $dest = Join-Path $Folder $name
    if (Test-Path -LiteralPath $dest) { throw "Ya existe $name en el destino externo (no se sobrescribe)." }
    $tmp = "$dest.partial"
    try {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction Stop }
        Copy-Item -LiteralPath $Source -Destination $tmp -ErrorAction Stop
        if ((Get-Item -LiteralPath $tmp).Length -ne (Get-Item -LiteralPath $Source).Length) {
            throw 'La copia externa no tiene el mismo tamano que el original.'
        }
        Move-Item -LiteralPath $tmp -Destination $dest -ErrorAction Stop
    } catch {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        throw
    }
    return $dest
}

function Invoke-BackupCopyAndRetention {
    <#
      Pasos posteriores a un dump ya validado: copia externa opcional y retencion local.
      La retencion local se aplica SIEMPRE, aunque la copia externa falle (con el disco desconectado la carpeta local
      se seguiria llenando). Si la copia externa fallo, devuelve su mensaje de error (el llamador sale con 1 y avisa);
      si todo salio bien devuelve $null. Un error de la retencion local se lanza como excepcion.
    #>
    param(
        [Parameter(Mandatory)][string]$DumpFile,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$Database,
        [Parameter(Mandatory)][int]$RetentionDays,
        [Parameter(Mandatory)][string]$LogFile,
        [string]$ExternalCopyPath
    )
    $externalError = $null
    if ($ExternalCopyPath) {
        try {
            [void](Copy-BackupToExternal -Source $DumpFile -Folder $ExternalCopyPath)
            $extRemoved = Remove-OldBackups -Folder $ExternalCopyPath -Database $Database -Days $RetentionDays
            Write-BackupLog $LogFile "Copia externa OK en $ExternalCopyPath (borrados por retencion: $extRemoved)."
        } catch {
            $externalError = Get-ShortError $_.Exception.Message
            Write-BackupLog $LogFile "Copia externa fallida: $externalError Se sigue con la retencion local." 'WARN'
        }
    }
    $removed = Remove-OldBackups -Folder $Destination -Database $Database -Days $RetentionDays
    Write-BackupLog $LogFile "Retencion: $removed archivo(s) de '$Database' borrado(s) ($RetentionDays dias; .partial de mas de 1 dia)."
    return $externalError
}

function ConvertTo-TaskPathArgument {
    <#
      Ruta entre comillas para la linea de argumentos de una tarea programada. En la linea de comandos de Windows
      `\"` escapa la comilla, asi que una ruta que termina en barra (p. ej. la raiz `E:\`) quedaria `"E:\"` y se
      comeria la comilla de cierre y el resto de los argumentos. Se quitan las barras finales; si queda una raiz de
      unidad (`E:`) se normaliza a `E:\.`, que sigue siendo la raiz y no termina en barra.
    #>
    param([Parameter(Mandatory)][string]$Path)
    if ($Path.Contains('"')) { throw "Ruta invalida (contiene comillas): $Path" }
    $p = $Path.TrimEnd('\', '/')
    if (-not $p) { throw "Ruta invalida: '$Path'." }
    if ($p -match '^[A-Za-z]:$') { $p += '\.' }
    return '"' + $p + '"'
}

function Get-DumpTocCount {
    <# Valida un dump -Fc con `pg_restore --list` (enviado por stdin). Devuelve la cantidad de entradas del TOC. #>
    param([Parameter(Mandatory)][string]$ProjectDir, [Parameter(Mandatory)][string]$DumpFile)
    $r = Invoke-Compose -ProjectDir $ProjectDir -InFile $DumpFile -Arguments @('exec', '-T', 'postgres', 'pg_restore', '--list')
    if ($r.ExitCode -ne 0) { throw "pg_restore --list fallo (codigo $($r.ExitCode)): $(Get-ShortError $r.StdErr)" }
    $entries = @(("" + $r.StdOut) -split "`r?`n" | Where-Object { $_ -match '^\d+;' })
    if ($entries.Count -eq 0) { throw 'pg_restore --list no devolvio entradas: el dump esta vacio o corrupto.' }
    return $entries.Count
}

function Get-TableCounts {
    <# Conteo exacto de filas por tabla (schema.tabla -> filas) de una base. Solo lee; no imprime datos. #>
    param([Parameter(Mandatory)][string]$ProjectDir, [Parameter(Mandatory)][string]$PgUser, [Parameter(Mandatory)][string]$Database)
    Assert-DatabaseName $Database
    $sql = @"
select t.table_schema || '.' || t.table_name || '|' ||
       (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', t.table_schema, t.table_name), false, true, '')))[1]::text
from information_schema.tables t
where t.table_type = 'BASE TABLE' and t.table_schema not in ('pg_catalog', 'information_schema')
order by 1;
"@
    $r = Invoke-Compose -ProjectDir $ProjectDir -Arguments @('exec', '-T', 'postgres', 'psql', '-U', $PgUser, '-d', $Database,
        '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-c', ($sql -replace "`r?`n", ' '))
    if ($r.ExitCode -ne 0) { throw "No se pudieron contar las tablas de $Database (codigo $($r.ExitCode)): $(Get-ShortError $r.StdErr)" }
    $counts = [ordered]@{}
    foreach ($line in (("" + $r.StdOut) -split "`r?`n")) {
        if ($line -match '^(.+)\|(\d+)$') { $counts[$Matches[1]] = [long]$Matches[2] }
    }
    return $counts
}
