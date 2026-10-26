@echo off
REM ============================================================
REM  DESINSTALAR.bat
REM  Doble clic: pide permisos de Administrador solo y quita el
REM  servicio CarnetPrintService. No borra los archivos publicados
REM  en C:\Program Files\CarnetPrintService; eso se hace a mano.
REM ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Pidiendo permisos de Administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo.
echo ============================================================
echo  Quitando CarnetPrintService
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar-servicio.ps1"

echo.
pause
