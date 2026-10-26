# Handoff — Middleware de impresión de carnets (Zebra ZC300 + Entrust Sigma DS3)

Fecha: 2026-10-23. Continúa en Windows. Contexto completo: `README.md`, `WINDOWS.md`, `DRIVERS.md`.

## Actualización 2026-10-23 (Windows)

- **Puente Entrust hecho y probado con el DS3 real:** `bridge/CardBridge` (.NET 8) + adaptador
  `entrust-sdk` (`app/printers/entrust_sdk.py`). Tarjeta de prueba frente/reverso por `POST /jobs`
  → `state: printed`, job de impresora 2484 `JobSucceeded`. Ver `WINDOWS.md`.
- El SDK de Entrust **no trae ensamblado**: son fuentes C# (`samples/csharp/common`), copiados en
  `bridge/CardBridge/EntrustSdk/`.
- DS3 de esta PC: Sigma DS3IDRD, 300 ppp, cinta YMCKT, dúplex auto, sin banda magnética ni laminador.
- Middleware en puerto 8787 (8080 lo usa Apache). Dependencia nueva: `pypdfium2` (PDF → PNG).
- Esta carpeta ya tenía otro servicio C# (`src/CarnetPrintService`, puerto 17580, instalado como
  servicio de Windows). El zip pisó `web/generador-carnets.html`; la versión de ese servicio quedó
  como `web/generador-carnets-servicio.html`.
- **Zebra (SDK Link-OS):** `bridge/ZebraBridge` (net48, NuGet `Zebra.Printer.Card.SDK` 2.15.2634)
  + adaptador `zebra-sdk` (`app/printers/zebra_sdk.py`; base común `app/printers/bridge.py`, también
  la usa `entrust_sdk.py`). Compila y los tests pasan, pero **no se probó con la impresora**: al
  integrarlo la ZC300 no estaba conectada (USB `VID_0A5F&PID_0148` con `Present=False`, `discover`
  vacío). Pendiente: conectar/encender y correr `bridge\zbin\ZebraBridge.exe status` y una tarjeta.
- Arreglado: `status` del conector `windows` siempre daba "offline" (`$args` no llega con `-Command`).
- Pendiente en `web/generador-carnets.html`: la config `zc300-api` aún manda opciones CUPS
  (`DualSidePrinting`, `RibbonName`, `RibbonCombination`) que el middleware de Windows descarta.

## Dónde nos quedamos (macOS)

**Hecho y verificado (en macOS, con el ZC300 real)**
- Middleware Python/FastAPI (`app/`): `GET /printers`, `GET /printers/{id}/options`, `POST /jobs` (PDF, o PNG `front`+`back` que se convierte a PDF CR80), `GET /jobs/{id}`. Auth por header `X-API-Key`. Cola serial por impresora.
- Generador de carnets (`web/generador-carnets.html`, servido en `/ui/…`) imprime por API. Tarjeta real impresa en el ZC300 desde ahí (driver Mac de Zebra + CUPS).
- Opciones del ZC300 por CUPS sacadas del PPD oficial (`printers.example.yaml`).
- Conector Windows (`app/printers/windows.py`): imprime el PDF en una impresora de Windows con SumatraPDF. **Solo probado con simulaciones (23 tests), nunca en Windows real.**

**Hallazgos**
- Cinta `Hologram` del ZC300 = solo overlay: el driver solo permite `22FrontO`, `23FrontOBackO`, `46BackO`, `47BackOFrontO`. Hay que pasar la tarjeta dos veces (primero YMCKO, luego Hologram). **No probado todavía**; no se sabe si la imagen enviada actúa como máscara.
- Overlay con bitmap y paneles de seguridad (plateado, perlado, YMCKLL) se configuran en la app de Zebra, no por CUPS.
- El driver XPS de Entrust y su SDK son **solo Windows**. El SDK va *encima* del driver XPS ya instalado.

**Decisión tomada (usuario):** en Windows no se pueden tocar las *Preferencias de impresión* del driver, así que hay que usar el **SDK completo** de cada fabricante para fijar opciones por trabajo, en vez del conector SumatraPDF.
Orden acordado: **1) puente C#/.NET para el Sigma DS3 (SDK de Entrust), 2) SDK de Zebra para el ZC300.** Nada del puente está escrito todavía.

## Siguiente paso: puente C# (`CardBridge.exe`)

Programa .NET que el middleware Python llama por trabajo (JSON/argumentos), un adaptador nuevo `sdk` en `app/printers/`.
Lo aprendido del SDK de Entrust (v8.8, ejemplos en `samples/csharp/print`, `common/BidiSpl.cs`, `common/util.cs`):
- Flujo: `BidiSplWrap.BindDevice(nombre)` → leer estado (`PRINTER_OPTIONS2`: debe estar `Ready`/`Busy`, cabezal instalado) → `Util.StartJob` (tolva/`hopper`) → imprimir con `System.Drawing.Printing.PrintDocument` → `Util.WaitForWindowsJobID` + `ENDJOB` → `Util.PollForJobCompletion`. Errores: `BidiException` → `Util.CancelJob`.
- Opciones por trabajo vía **Print Ticket** (`PrintQueue.MergeAndValidatePrintTicket` + `Commit()`, XML en `printTicketXml.cs`): una/dos caras, orientación por cara, giro 180° por cara (`PageFlipFront/Back`), desactivar impresión por cara (`DocumentEncodeOnly`), topcoat y bloqueo (`PageFront/BackPrintAndTopcoat` y excepciones: chip, mag 2/3 pistas, JIS). Papel `ISO ID-1 (85.60 x 53.98 mm)` a 300 dpi (DS3 de 600 dpi: `ISO ID-1 Retransfer`, escala 2).
- **Holograma/laminado:** ejemplo `samples/csharp/lamination` (Print Ticket de laminador L1/L2, caras, tolva). **No existe en Java**, por eso el puente debe ser C#.
- Ojo: `Commit()` cambia las preferencias del driver en la máquina; el SDK está pensado para eso.
- La Mac no tiene .NET: el código se escribirá sin compilar. Compilar y probar en Windows (Visual Studio / `dotnet build`, ejemplos en `print.csproj`).

Luego: bajar el SDK de Zebra (pide EULA) y repetir para el ZC300; después estado real de trabajos, prueba de holograma, despliegue en Linux/servidor.

## Qué descargar en Windows

**Incluido en el zip (`windows-drivers/`)**
- Zebra ZC300 driver Windows `DZCG.01.11.00.00.exe` (41 MB). Instalar **antes** de conectar el USB (si no: recovery steps de Zebra).
- Entrust XPS driver `XPSCardPrinter_8.8.048.0.exe` (13 MB).

**Links (no incluidos)**
| Qué | Link |
|---|---|
| Python 3.11+ (marcar "py launcher") | https://www.python.org/downloads/windows/ |
| SumatraPDF (solo para el conector Windows actual) | https://www.sumatrapdfreader.org/download-free-pdf-viewer |
| .NET SDK (para compilar el puente) | https://dotnet.microsoft.com/download |
| Visual Studio Community (alternativa) | https://visualstudio.microsoft.com/vs/community/ |
| Entrust XPS Driver SDK v8.8 (zip, 29 MB: jars, ejemplos C#/C++/VB/Java, `SDK_Dev_Guide.pdf`) | https://downloads.entrust.com/drivers/XPS_Card_Printer_SDK_v8.8.zip |
| Entrust XPS driver v8.8 (por si hay que bajarlo otra vez) | https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe |
| Entrust DS3 — página de soporte (drivers, guías) | https://www.entrust.com/support/instant-id-card-issuance-systems/ds3-direct-to-card-printer-support |
| Entrust XPS Driver User Guide 8.8 | https://www.entrust.com/sites/default/files/documentation/productsupport/527280-005l-xps-card-printer-driver-8-8.pdf |
| Entrust SDK Reference Guide | https://www.entrust.com/sites/default/files/documentation/productsupport/527250-003h-reference-guide-windows-xps-driver-software-development-kit-sdk.pdf |
| Entrust SDK release notes 8.8 | https://www.entrust.com/sites/default/files/documentation/productsupport/528182-001g-xps-driver-sdk-release-notes-v8-8.pdf |
| Entrust Install & Admin Guide DS3 | https://www.entrust.com/sites/default/files/documentation/productsupport/528062-001l-ds1-ds2-ds3-inst-admin-guide.pdf |
| Entrust Printer Dashboard guide | https://www.entrust.com/sites/default/files/documentation/productsupport/528114-001r-printer-dashboard-online%20help.pdf |
| Zebra ZC100/300 — soporte y drivers (Windows, Mac, Linux; pide EULA) | https://www.zebra.com/us/en/support-downloads/printers/card/zc-series-quikcard-id.html |
| Zebra Link-OS SDK para tarjetas (.NET/Java) — **pendiente de bajar** | https://techdocs.zebra.com/link-os/2-15/cardindex |
| Zebra: instalar con ZDesigner Windows driver | https://support.zebra.com/article/000027281?language=en_US |

Nota: `www.entrust.com` bloquea descargas por terminal (403); bájalas desde el navegador. `downloads.entrust.com` sí responde.

## Arranque rápido en Windows (conector actual, sin SDK)
1. Instalar Python, SumatraPDF y los dos drivers.
2. `Get-Printer | Select Name` → nombres exactos de las impresoras.
3. `powershell -ExecutionPolicy Bypass -File run-windows.ps1` (crea `.venv`, `.env`, `printers.yaml` desde `printers.windows.example.yaml`; editar y volver a ejecutar).
4. Abrir `http://localhost:8080/ui/generador-carnets.html`, API key en "Conexión al middleware", elegir "… vía middleware (API)".

## Pendientes
- Puente C# Entrust → adaptador `sdk`; luego SDK de Zebra.
- Probar cinta Hologram en el ZC300 (tarjeta ya impresa, `CardSource=0Manual`, overlay solo frente).
- Estado real de trabajos (hoy `submitted` = CUPS/Windows lo aceptó, no "impreso").
- Defecto visual del original: el código del carnet se corta en el borde derecho del frente.
- La API key de desarrollo (`devkey-local`) y el middleware sin HTTPS son solo para pruebas locales.
