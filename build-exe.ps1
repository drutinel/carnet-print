# Empaqueta CarnetPrint.exe (Windows). Requiere Python 3.11+ y .NET SDK 8.
# Uso: powershell -ExecutionPolicy Bypass -File build-exe.ps1 [-Version 1.2.3]
# Resultado en dist\:  CarnetPrint.exe  +  bridge\ (CardBridge.exe y sus DLL)
# Junto al .exe se crean solos en la primera ejecución: .env, printers.yaml y los datos (*.json, png\, images\).
param([string]$Version = "dev")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv-build)) { py -3 -m venv .venv-build }
.\.venv-build\Scripts\python -m pip install -q --upgrade pip
.\.venv-build\Scripts\python -m pip install -q -e ".[build]"

& "$PSScriptRoot\bridge\build.ps1" -Target entrust
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# La versión queda dentro del .exe (GET /health, --version y la web la muestran)
Set-Content -Encoding utf8 app\_build_version.py "VERSION = `"$Version`""
try {
  .\.venv-build\Scripts\python -m PyInstaller --noconfirm --clean carnet-print.spec
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item app\_build_version.py -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force dist\bridge | Out-Null
Copy-Item bridge\bin\* dist\bridge -Recurse -Force
Write-Host "Listo: $PSScriptRoot\dist\CarnetPrint.exe $Version (con dist\bridge\)"
Write-Host "Copia CarnetPrint.exe y la carpeta bridge\ juntas al equipo destino (necesita .NET 8 Desktop Runtime y el driver XPS de Entrust)."
