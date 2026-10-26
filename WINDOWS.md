# Continuar en Windows

> Estado actual y siguiente paso: ver `HANDOFF.md`.

1. Instalar **Python 3.11+** (python.org, marcar "py launcher"), **.NET SDK 8+** (para compilar el puente
   de Entrust) y, solo para la Zebra, **SumatraPDF** (`C:\Program Files\SumatraPDF`; otra ruta →
   `sumatra_path` en `printers.yaml`).
2. Instalar los drivers de las impresoras (ver `DRIVERS.md`). **Entrust Sigma DS3:** `windows-drivers/entrust/XPSCardPrinter_8.8.048.0.exe`.
   **Zebra ZC300:** `windows-drivers/zebra/DZCG.01.11.00.00.exe` (Zebra advierte: instalar el driver ANTES de conectar el USB).
3. Conectar las impresoras y anotar su nombre exacto: `Get-Printer | Select Name`
   (en esta PC: `XPS Card Printer` y `Zebra ZC300 USB Card Printer`).
4. Ejecutar `powershell -ExecutionPolicy Bypass -File run-windows.ps1` (la primera vez crea `.venv`,
   compila `bridge\bin\CardBridge.exe`, crea `.env` y `printers.yaml`; edítalos y vuelve a ejecutar).
   Puerto por defecto **8787** (en esta PC el 8080 lo usa Apache y el 8090 Wondershare); otro: `-Port 9000`.
5. Abrir `http://localhost:8787/ui/generador-carnets.html`, pegar la API key en "Conexión al middleware"
   y elegir "… vía middleware (API)".

## Entrust Sigma DS3 por SDK (verificado con la impresora real)

`adapter: entrust-sdk` llama a `bridge\bin\CardBridge.exe`, que usa los fuentes del *XPS Card Printer
SDK v8.8* (`bridge/CardBridge/EntrustSdk/`, IBidiSpl por COM):
BindDevice → estado → StartJob → PrintDocument + Print Ticket → EndJob → sondeo hasta `JobSucceeded`.
El trabajo de la API pasa a `printed` solo cuando la impresora confirma que la tarjeta salió;
errores del equipo (sin tarjetas, cinta, atasco) cancelan el trabajo y quedan en `error`.

Opciones por trabajo (`options` en `POST /jobs`): `rotate_front`, `rotate_back` (`true`/`false`),
`topcoat_front`, `topcoat_back` (`all|chip|mag2|mag3|magjis`), `disable_printing`
(`off|front|back|all`), `hopper`. Sin opción de topcoat se usa lo que tenga el driver.
El Print Ticket se guarda con `Commit()`, o sea que cambia las *Preferencias de impresión* del driver
en la PC (así funciona el SDK).

Prueba directa sin middleware:

    bridge\bin\CardBridge.exe status --printer "XPS Card Printer"
    bridge\bin\CardBridge.exe print --printer "XPS Card Printer" --front frente.png --back reverso.png

La primera llamada tras un rato inactiva puede tardar >25 s (la impresora despierta).

Cómo funciona por dentro: el SDK (IBidiSpl) controla el trabajo (StartJob/EndJob, estado, errores,
fin del trabajo) y el Print Ticket fija las opciones; la imagen va por el driver XPS de Entrust en el
spooler de Windows, dentro de ese StartJob/EndJob. El SDK XPS no tiene vía de imagen sin driver.

Desde el generador: elegir "ENTRUST Sigma DS3 · vía middleware (API)". La pantalla espera hasta que la
tarjeta sale (30-60 s) y muestra "Impreso…" o el error de la impresora.

Arranque automático al iniciar sesión: `install\middleware-autostart.ps1` (quitar con `-Remove`).

## Zebra ZC300 por SDK (compilado, SIN probar con la impresora)

`adapter: zebra-sdk` llama a `bridge\zbin\ZebraBridge.exe` (.NET Framework 4.8, paquete NuGet
`Zebra.Printer.Card.SDK` 2.15.2634 — EULA de Zebra; el SDK solo trae net471, por eso no va dentro de
CardBridge). Conexión **USB directa** del SDK (`UsbDiscoverer` + `UsbConnection`), no el spooler:
frente `Color` + `Overlay`, reverso `Color`/`MonoK`/nada + `Overlay`, `CARD_SOURCE` Feeder,
`CARD_DESTINATION` Eject, `Print(copias, …)` y sondeo de `GetJobStatus` hasta `done_ok`; error o
alarma (sin tarjetas, cinta, atasco) cancela el trabajo y queda en `error`.

Opciones por trabajo: `back_type` (`color|mono|none`), `overlay_front`, `overlay_back`
(`true|false`), `source` (`feeder|internal|atm`), `usb` (dirección si hay varias ZC),
`auto_k` (`true`: sin capa K del generador, el SDK separa el negro con `ExtractBlackImageData`).
Las copias van en **un solo trabajo** del SDK (`--copies N`), no un arranque del puente por tarjeta.
La dirección USB se guarda en `%LOCALAPPDATA%\ZebraBridge\usb.txt` para no redescubrir en cada
trabajo (si falla, se borra y se redescubre).

Paneles especiales (solo con la cinta que los tenga; ficha ZC300: YMCPKO = perla, SrDYMCKO = plata,
blanco monocromo): `--front-special mascara.png --special-type pearl|silver|white` (1 bpp, negro =
se imprime). Overlay parcial: `--overlay-front-mask` / `--overlay-back-mask` (overlay solo donde la
máscara es negra). La ZC300 no tiene laminador ni cinta holográfica en su ficha.

Prueba sin impresora: `ZebraBridge.exe print --dry-run --out DIR --front f.png [--front-k k.png] ...`
valida argumentos, prepara cada panel como lo haría al imprimir (modelo ZC300) y guarda los BMP en DIR.

No aplica a la ZC300: `PRINT_OPTIMIZATION` / `K_OPTIMIZATION_*` del SDK son de ZMotif Serie 9.

    bridge\zbin\ZebraBridge.exe discover
    bridge\zbin\ZebraBridge.exe status
    bridge\zbin\ZebraBridge.exe print --front frente.png --back reverso.png [--back-type mono]
                                      [--front-k frente-k.png] [--back-k reverso-k.png]

Capa K (`--front-k`/`--back-k`): PNG negro puro sobre blanco, mismo tamaño que la cara. Se manda
como `PrintType.MonoK` (1 bpp, umbral sin tramado: `MonochromeConversion.None`) en la misma cara,
encima del panel `Color`, así el texto sale con negro resina nítido. Con `--back-type mono` el
reverso usa la capa K si viene (si no, la imagen umbralizada). Lienzo nativo de la ZC300:
**1006×640** (SDK `PrinterModel.ZC300` y ficha técnica). El puente siempre pasa 1006×640 como
destino a `DrawImage`: 1:1 si la imagen ya mide eso, escalada si no. Ojo: en el SDK, ancho/alto 0
**no** escala al panel, usa el tamaño propio de la imagen (una imagen más grande saldría recortada).

`status` devuelve modelo, firmware, estado, capacidad de impresión, laminador/mag/chip y la cinta
(`media`: tipo, descripción, paneles restantes). Si `discover` sale vacío, la ZC300 no está conectada
o encendida (Windows conserva la cola "Zebra ZC300 USB Card Printer" aunque el equipo no esté).

Alternativa sin SDK: `adapter: windows` (SumatraPDF; cinta/overlay/dúplex en *Preferencias de impresión*).

## Calidad de impresión Entrust (guía Sigma DS1/DS2/DS3)

- Texto fino: Arial/sans-serif en negrita, ≥ 6 pt (8.5 px en la vista previa), por el panel K (clase `kblack` en la web).
- Negro puro (0,0,0) = panel K. El puente pasa el 0,0,0 de la capa de color a (0,0,5) para no tapar fotos y logos.
- Opciones Entrust por trabajo: `print_mode` (standard|best|custom), `color_dpi` (300x300|300x600), `mono_dpi`
  (300x300|300x600|300x1200), `color_mode` (icc|vivid), `split_ribbon` (ymct_k|ymc_kt: una tanda de cinta, reverso solo K).
- Guía del driver (pestaña Color Adjustment): https://www.entrust.com/sites/default/files/documentation/productsupport/527280-005l-xps-card-printer-driver-8-8.pdf
