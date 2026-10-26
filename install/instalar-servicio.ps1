<#
.SINOPSIS
  Publica CarnetPrintService y lo instala como servicio de Windows, para
  que arranque solo con la PC y no dependa de tener una ventana abierta.

.USO
  Clic derecho sobre este archivo > "Ejecutar con PowerShell" (como
  Administrador), o desde una consola de PowerShell como Administrador:

    cd install
    .\instalar-servicio.ps1

.REQUISITOS
  - Windows 10/11.
  - .NET 8 SDK instalado (https://dotnet.microsoft.com/download/dotnet/8.0).
    Sin esto el script se detiene y lo dice.
  - Ejecutarse como Administrador (crear un servicio de Windows lo exige).
#>

$ErrorActionPreference = "Stop"

function Fail($msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ---- 0. Administrador -----------------------------------------------------
$esAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $esAdmin) {
    Fail "Hay que ejecutar esto como Administrador (clic derecho > Ejecutar con PowerShell, elige Si en el aviso)."
}

# ---- 1. .NET SDK -----------------------------------------------------------
try {
    $null = dotnet --version
} catch {
    Fail "No encuentro el .NET SDK. Instala .NET 8 SDK desde https://dotnet.microsoft.com/download/dotnet/8.0 y vuelve a correr este script."
}

# ---- 2. Rutas ---------------------------------------------------------------
$raiz       = Split-Path -Parent $PSScriptRoot
$proyecto   = Join-Path $raiz "src\CarnetPrintService\CarnetPrintService.csproj"
$destino    = "C:\Program Files\CarnetPrintService"
$nombreSvc  = "CarnetPrintService"

if (-not (Test-Path $proyecto)) {
    Fail "No encuentro $proyecto. Revisa que este script siga dentro de la carpeta install dentro del proyecto."
}

# ---- 3. Si ya existe el servicio, pararlo antes de publicar ---------------
$svc = Get-Service -Name $nombreSvc -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "Servicio existente encontrado: deteniendolo para actualizar..." -ForegroundColor Yellow
    Stop-Service -Name $nombreSvc -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# ---- 4. Publicar -------------------------------------------------------------
Write-Host "Publicando CarnetPrintService en $destino ..." -ForegroundColor Cyan
if (-not (Test-Path $destino)) { New-Item -ItemType Directory -Path $destino -Force | Out-Null }

dotnet publish $proyecto -c Release -r win-x64 --self-contained false -o $destino
if ($LASTEXITCODE -ne 0) { Fail "dotnet publish fallo. Revisa el mensaje de arriba." }

$exe = Join-Path $destino "CarnetPrintService.exe"
if (-not (Test-Path $exe)) { Fail "La publicacion termino pero no encuentro $exe." }

# ---- 5. Crear o actualizar el servicio -------------------------------------
if ($svc) {
    Write-Host "Actualizando el servicio existente..." -ForegroundColor Cyan
    & sc.exe config $nombreSvc binPath= "`"$exe`"" start= auto | Out-Null
} else {
    Write-Host "Creando el servicio de Windows..." -ForegroundColor Cyan
    New-Service -Name $nombreSvc `
        -BinaryPathName "`"$exe`"" `
        -DisplayName "Carnet Print Service" `
        -Description "Middleware local de impresion de carnets (ENTRUST / Zebra ZC300). Solo escucha en 127.0.0.1." `
        -StartupType Automatic | Out-Null
}

# ---- 6. Arrancar y comprobar ------------------------------------------------
Start-Service -Name $nombreSvc
Start-Sleep -Seconds 2
$estado = (Get-Service -Name $nombreSvc).Status

Write-Host ""
if ($estado -eq "Running") {
    Write-Host "Listo. El servicio $nombreSvc esta corriendo." -ForegroundColor Green
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:17580/health" -TimeoutSec 5
        Write-Host ("Respondio: " + $resp.service + " " + $resp.version + " - tarjeta " + $resp.cardWidthPx + "x" + $resp.cardHeightPx + " px a " + $resp.dpi + " ppp.") -ForegroundColor Green
    } catch {
        Write-Host "El servicio arranco pero no respondio en /health todavia. Dale unos segundos y abre http://127.0.0.1:17580/health en el navegador." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Revisa appsettings.json en $destino si los nombres de impresora" -ForegroundColor Cyan
    Write-Host "(ENTRUST / ZC300) no coinciden con los que ves en Configuracion > Impresoras y escaneres." -ForegroundColor Cyan
} else {
    Fail "El servicio quedo en estado $estado. Revisa el Visor de eventos de Windows (Aplicacion) para el detalle."
}
