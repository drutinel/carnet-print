# Empaqueta CarnetPrint.exe (Windows). Requiere Python 3.11+ y .NET SDK 8.
# Uso: powershell -ExecutionPolicy Bypass -File build-exe.ps1
# Resultado en dist\:  CarnetPrint.exe  +  bridge\ (CardBridge.exe y sus DLL)
# Junto al .exe se crean solos en la primera ejecución: .env, printers.yaml,
# templates.json y carnets.json.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv-build)) { py -3 -m venv .venv-build }
.\.venv-build\Scripts\python -m pip install -q --upgrade pip
.\.venv-build\Scripts\python -m pip install -q -e ".[build]"

dotnet build bridge\CardBridge\CardBridge.csproj -c Release -o bridge\bin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

.\.venv-build\Scripts\python -m PyInstaller --noconfirm --clean carnet-print.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force dist\bridge | Out-Null
Copy-Item bridge\bin\* dist\bridge -Recurse -Force
Write-Host "Listo: $PSScriptRoot\dist\CarnetPrint.exe (con dist\bridge\)"
Write-Host "Copia CarnetPrint.exe y la carpeta bridge\ juntas al equipo destino (necesita .NET 8 Runtime y el driver XPS de Entrust)."
