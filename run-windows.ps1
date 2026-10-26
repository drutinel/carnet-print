# Arranca el middleware en Windows. Uso: powershell -ExecutionPolicy Bypass -File run-windows.ps1 [-Port 8787]
# (8787 por defecto: en esta PC el 8080 lo ocupa Apache/httpd y el 8090 Wondershare).
param([int]$Port = 8787)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { py -3 -m venv .venv; .\.venv\Scripts\pip install -e . }
if (-not (Test-Path bridge\bin\CardBridge.exe) -or -not (Test-Path bridge\zbin\ZebraBridge.exe)) { & .\bridge\build.ps1; if ($LASTEXITCODE -ne 0) { exit 1 } }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Edita .env (CARDPRINT_API_KEY) y vuelve a ejecutar."; exit 1 }
if (-not (Test-Path printers.yaml)) { Copy-Item printers.windows.example.yaml printers.yaml; Write-Host "Edita printers.yaml (nombres de impresora) y vuelve a ejecutar."; exit 1 }
.\.venv\Scripts\uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port
