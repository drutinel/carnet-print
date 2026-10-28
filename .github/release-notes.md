## Instalación (recomendada)

Descarga y ejecuta **`CarnetPrint-Setup-<versión>.exe`**. El instalador, en una sola pasada:

- copia `CarnetPrint.exe` y `bridge\` a `C:\CarnetPrint` (ahí mismo se guardan `.env`, plantillas, carnets y PNG);
- instala el **.NET 8 Desktop Runtime** si la PC no lo tiene (viene incluido, no necesita internet);
- ofrece descargar e instalar el **driver XPS de Entrust 8.8** si Windows no tiene la impresora «XPS Card Printer»;
- crea los accesos directos. Al desinstalar no borra tus datos.

Después conecta y enciende la DS3 y abre CarnetPrint. Si falta algo, el programa lo avisa con el enlace de descarga.

## Sin instalador

`CarnetPrint-<versión>-win-x64.zip` trae `CarnetPrint.exe` **y la carpeta `bridge\`: deben ir juntos**. Si copias solo el
`.exe`, avisará que falta `CardBridge.exe`. Requisitos a mano:
[driver XPS de Entrust 8.8](https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe) y
[.NET 8 Desktop Runtime x64](https://dotnet.microsoft.com/download/dotnet/8.0).
`CarnetPrint.exe` suelto sirve para actualizar un equipo que ya tiene `bridge\`.

> Windows SmartScreen puede avisar de «editor desconocido» porque los archivos no están firmados: «Más información > Ejecutar de todos modos».

## Estado

El build prueba que el `.exe` arranca, sirve la web y crea sus archivos. **La impresión con la DS3 real todavía no se ha verificado con este build.**

---
