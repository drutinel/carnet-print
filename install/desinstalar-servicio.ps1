<#
.SINOPSIS
  Detiene y elimina el servicio de Windows CarnetPrintService.
  No borra los archivos publicados en C:\Program Files\CarnetPrintService;
  eso se puede borrar a mano despues si ya no se necesita.

.USO
  Como Administrador:  .\desinstalar-servicio.ps1
#>

$ErrorActionPreference = "Stop"
$nombreSvc = "CarnetPrintService"

$esAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $esAdmin) {
    Write-Host "Hay que ejecutar esto como Administrador." -ForegroundColor Red
    exit 1
}

$svc = Get-Service -Name $nombreSvc -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "No hay ningun servicio llamado $nombreSvc instalado." -ForegroundColor Yellow
    exit 0
}

Write-Host "Deteniendo $nombreSvc..." -ForegroundColor Cyan
Stop-Service -Name $nombreSvc -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

& sc.exe delete $nombreSvc | Out-Null

Write-Host "Servicio eliminado. Los archivos en C:\Program Files\CarnetPrintService siguen ahi; borralos a mano si quieres." -ForegroundColor Green
