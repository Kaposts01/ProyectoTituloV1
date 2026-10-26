# Levanta la instancia SANDBOX del backend (puerto 8001, base SANDBOX_DATABASE_URL del .env).
# La instancia de produccion corre aparte en el puerto 8000 (sin APP_ENV=sandbox).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:APP_ENV = 'sandbox'
& "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
