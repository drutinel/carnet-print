CARNET-PRINT — impresión de carnets en Entrust Sigma DS3 y Zebra ZC300
=======================================================================

Generador web de carnets + middleware (Python/FastAPI) + puentes a los SDK
de los fabricantes (C#/.NET). Detalles: README.md, WINDOWS.md, HANDOFF.md.

Arranque rápido (Windows):
    powershell -ExecutionPolicy Bypass -File run-windows.ps1
    Abrir http://127.0.0.1:8787/ui/generador-carnets.html


DÓNDE BAJAR CADA COSA
---------------------

Ya incluidos en este repositorio (copias de conveniencia; la fuente oficial
es el fabricante):

  windows-drivers/entrust/XPSCardPrinter_8.8.048.0.exe   Driver XPS Entrust v8.8
      https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe
  windows-drivers/zebra/DZCG.01.11.00.00.exe             Driver Windows Zebra ZC300
      https://www.zebra.com/us/en/support-downloads/printers/card/zc-series-quikcard-id.html
      (instalar ANTES de conectar el USB)
  bridge/CardBridge/EntrustSdk/                          Fuentes "common" del
      XPS Card Printer SDK v8.8 de Entrust (BidiSpl.cs, DXP01SDK.cs, util.cs,
      printTicketXml.cs). SDK completo, con ejemplos y SDK_Dev_Guide.pdf:
      https://downloads.entrust.com/drivers/XPS_Card_Printer_SDK_v8.8.zip
  docs/zebra-zc100-300-linux-driver-ug-en.pdf            Guía del driver Linux Zebra
      https://www.zebra.com/us/en/support-downloads/printers/card/zc-series-quikcard-id.html

Se bajan solos al compilar:
  SDK Link-OS de Zebra para tarjetas (NuGet Zebra.Printer.Card.SDK 2.15.2634,
  EULA de Zebra): lo restaura `dotnet build` de bridge/ZebraBridge.
      https://www.nuget.org/packages/Zebra.Printer.Card.SDK
      Documentación: https://techdocs.zebra.com/link-os/2-14/pc_card_net

Hay que instalar aparte:
  Python 3.11+ (marcar "py launcher")   https://www.python.org/downloads/windows/
  .NET SDK 8 o superior                 https://dotnet.microsoft.com/download
  SumatraPDF (solo conector "windows")  https://www.sumatrapdfreader.org/download-free-pdf-viewer

Documentación de los fabricantes:
  Entrust DS3 soporte      https://www.entrust.com/support/instant-id-card-issuance-systems/ds3-direct-to-card-printer-support
  Entrust guía del driver  https://www.entrust.com/sites/default/files/documentation/productsupport/527280-005l-xps-card-printer-driver-8-8.pdf
  Entrust guía del SDK     https://www.entrust.com/sites/default/files/documentation/productsupport/527250-003h-reference-guide-windows-xps-driver-software-development-kit-sdk.pdf
  Zebra ZC300 ficha        https://zebra.com/gb/en/products/spec-sheets/printers/card/zc300.html

Nota: www.entrust.com bloquea descargas por línea de comandos; bajar desde el
navegador. downloads.entrust.com sí responde.

Nota: .env trae la API key de desarrollo del middleware (solo escucha en
127.0.0.1). Para usarlo en otro equipo, cambiar CARDPRINT_API_KEY en .env.
