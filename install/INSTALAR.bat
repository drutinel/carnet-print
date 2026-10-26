@echo off
REM ============================================================
REM  INSTALAR.bat
REM  Doble clic y listo: pide permisos de Administrador solo,
REM  evita el bloqueo de PowerShell y corre instalar-servicio.ps1.
REM  No hace falta abrir PowerShell a mano ni escribir nada.
REM ============================================================

REM ---- Si no estamos como Administrador, relanzar este mismo .bat elevado ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Pidiendo permisos de Administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM ---- Ya estamos como Administrador: correr el instalador real ----
cd /d "%~dp0"
echo.
echo ============================================================
echo  Instalando CarnetPrintService
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-servicio.ps1"

echo.
echo ============================================================
echo  Termino. Revisa los mensajes de arriba.
echo ============================================================
pause
