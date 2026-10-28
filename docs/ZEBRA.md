# Zebra ZC300

El flujo principal del proyecto es la **Entrust Sigma DS3**. Esto es lo que se sabe de la Zebra ZC300, que
se conserva en el código pero **no está verificada con la impresora** en esta versión.

## Qué hay

- Adaptador `zebra-sdk` ([app/printers/zebra_sdk.py](../app/printers/zebra_sdk.py)) y el puente
  `bridge/ZebraBridge` (.NET Framework 4.8, NuGet `Zebra.Printer.Card.SDK` 2.15.2634, SDK Link-OS).
- Compilar: `powershell -File bridge\build.ps1 -Target zebra` → `bridge\zbin\ZebraBridge.exe`
  (no va en el instalador ni en `CarnetPrint.exe`).
- Activar: descomentar el bloque `zebra-zc300` en `printers.yaml` y reiniciar.
- Opciones por trabajo: `back_type` (color/mono/none), `overlay_front`, `overlay_back`, `source`.

## Estado de verificación

- El puente compila y los tests del adaptador pasan, pero **nunca se probó con la ZC300**: al integrarlo la
  impresora no estaba conectada (USB `VID_0A5F&PID_0148` con `Present=False`, `discover` vacío).
  Pendiente: conectarla y correr `bridge\zbin\ZebraBridge.exe status` y una tarjeta.
- Hubo una verificación anterior en macOS con el driver de Zebra (1.0.10.0) y CUPS: una tarjeta real se imprimió
  desde el generador. Esa ruta (CUPS y PDF) se retiró del programa; sigue en el historial de git.

## Cinta Hologram y overlays

- La cinta `Hologram` del ZC300 es solo overlay: el driver solo permite `22FrontO`, `23FrontOBackO`, `46BackO`
  y `47BackOFrontO`. Hay que pasar la tarjeta dos veces (primero YMCKO, luego Hologram). No probado: no se sabe si
  la imagen enviada actúa como máscara.
- El overlay con bitmap y los paneles de seguridad (plateado, perlado, YMCKLL) se configuran en la app de
  Zebra, no por las opciones del driver.

## Drivers y documentación

- Driver Windows (instalar **antes** de conectar el USB; si no, Zebra tiene pasos de recuperación):
  <https://www.zebra.com/us/en/support-downloads/printers/card/zc-series-quikcard-id.html> (pide aceptar el EULA).
- SDK Link-OS para tarjetas: <https://techdocs.zebra.com/link-os/2-15/cardindex>
- Instalar con el driver ZDesigner de Windows: <https://support.zebra.com/article/000027281?language=en_US>
