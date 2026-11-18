param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$localRoot = Split-Path -Parent $PSScriptRoot
Set-Location $localRoot
$localDotenv = Join-Path $localRoot '.env.local'
if (-not (Test-Path -LiteralPath $localDotenv)) {
    throw 'Falta .env.local: prepara la copia local documentada en docs/quality/local-repair-2026-11-18.md.'
}
$env:CRM_DOTENV_PATH = $localDotenv
$env:APP_ENV = 'qa'
$env:SANDBOX_SCHEDULER_ENABLED = 'false'
& "$localRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
