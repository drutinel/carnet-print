## Instalación

1. Descarga **`CarnetPrint-<versión>-win-x64.zip`** y descomprímelo en una carpeta de la PC (deja `CarnetPrint.exe` y `bridge\` juntos).
2. Doble clic en `CarnetPrint.exe`. La primera vez crea `.env` (con una API key aleatoria) y `printers.yaml` junto al `.exe`.

`CarnetPrint.exe` suelto sirve para actualizar un equipo que ya tiene la carpeta `bridge\`.

## Requisitos de la PC

- Driver XPS de Entrust 8.8: [descargar](https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe)
- .NET 8 Desktop Runtime (x64): [descargar](https://dotnet.microsoft.com/download/dotnet/8.0)
- La Entrust Sigma DS3 conectada y encendida

Si falta algo, el programa lo avisa al abrir con el enlace de descarga.

## Estado

El build prueba que el `.exe` arranca, sirve la web y crea sus archivos. **La impresión con la DS3 real todavía no se ha verificado con este build.**

---
