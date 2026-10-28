# Compila los puentes de SDK (requiere .NET SDK 8 o superior).
#   -Target entrust   bridge\bin\CardBridge.exe     Entrust (net8)
#   -Target zebra     bridge\zbin\ZebraBridge.exe   Zebra Link-OS Card SDK (net48; el SDK solo trae net471)
#   -Target all       los dos (por omisión)
# Uso: powershell -ExecutionPolicy Bypass -File bridge\build.ps1 [-Target entrust]
param([ValidateSet("all", "entrust", "zebra")][string]$Target = "all")
$ErrorActionPreference = "Stop"
# MSBuild toma las variables de entorno como propiedades: un VERSION=v1.2.3 del entorno pisa $(Version) y
# NuGet no puede restaurar. Se quita aquí por si quien llama lo trae.
Remove-Item Env:VERSION -ErrorAction SilentlyContinue

if ($Target -in "all", "entrust") {
  dotnet build "$PSScriptRoot\CardBridge\CardBridge.csproj" -c Release -o "$PSScriptRoot\bin"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Write-Host 'Prueba: bridge\bin\CardBridge.exe status --printer "XPS Card Printer"'
}
if ($Target -in "all", "zebra") {
  dotnet build "$PSScriptRoot\ZebraBridge\ZebraBridge.csproj" -c Release -o "$PSScriptRoot\zbin"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Write-Host "Prueba: bridge\zbin\ZebraBridge.exe status"
}
