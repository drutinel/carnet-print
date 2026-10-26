# Compila los puentes de SDK (requiere .NET SDK 8 o superior):
#   bridge\bin\CardBridge.exe    Entrust (net8)
#   bridge\zbin\ZebraBridge.exe  Zebra Link-OS Card SDK (net48; el SDK solo trae net471)
# Uso: powershell -ExecutionPolicy Bypass -File bridge\build.ps1
dotnet build "$PSScriptRoot\CardBridge\CardBridge.csproj" -c Release -o "$PSScriptRoot\bin"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
dotnet build "$PSScriptRoot\ZebraBridge\ZebraBridge.csproj" -c Release -o "$PSScriptRoot\zbin"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Listo: $PSScriptRoot\bin\CardBridge.exe y $PSScriptRoot\zbin\ZebraBridge.exe"
Write-Host 'Prueba: bridge\bin\CardBridge.exe status --printer "XPS Card Printer"'
Write-Host 'Prueba: bridge\zbin\ZebraBridge.exe status'
