@echo off
REM Arranca el servicio simulado (en Node) para probar el generador sin
REM instalar nada de .NET ni tocar impresoras reales. Los PNG que el
REM generador mande a imprimir se guardan en tools\salida\.
REM
REM Requiere Node.js (https://nodejs.org). Si no lo tienes instalado,
REM Windows te lo va a decir.

cd /d "%~dp0"
echo Servicio simulado de impresion de carnets
echo Los PNG que se "impriman" se guardan en: %~dp0salida\
echo.
echo Deja esta ventana abierta. Cierra con Ctrl+C cuando termines de probar.
echo.
node mock-service.js
pause
