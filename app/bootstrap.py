import secrets
from pathlib import Path

DEFAULT_PRINTERS = """\
# Impresoras del middleware. Editar y reiniciar CarnetPrint.exe.
# `printer_name` = nombre EXACTO en "Impresoras y escáneres" (PowerShell: Get-Printer | Select Name).
printers:
  # SDK de Entrust (bridge\\CardBridge.exe, junto a este .exe). "printed" cuando la tarjeta sale.
  - id: entrust-sigma-ds3
    label: Entrust Sigma DS3
    adapter: entrust-sdk
    printer_name: "XPS Card Printer"
    allowed_options:
      rotate_front: ["true", "false"]
      rotate_back: ["true", "false"]
      topcoat_front: ["all", "chip", "mag2", "mag3", "magjis"]
      topcoat_back: ["all", "chip", "mag2", "mag3", "magjis"]
      disable_printing: ["off", "front", "back", "all"]
      hopper: ["1", "2", "3", "4", "5", "6"]
      print_mode: ["standard", "best", "custom"]
      color_dpi: ["300x300", "300x600"]
      mono_dpi: ["300x300", "300x600", "300x1200"]
      color_mode: ["icc", "vivid"]
      split_ribbon: ["ymct_k", "ymc_kt"]

  # Zebra ZC300 por el SDK Link-OS (bridge\\zbin\\ZebraBridge.exe, compilado con bridge\\build.ps1). Sin verificar
  # con la impresora (ver docs/ZEBRA.md). Para usarla, quita los «#» y compila el puente.
  # - id: zebra-zc300
  #   label: Zebra ZC300
  #   adapter: zebra-sdk
  #   printer_name: "Zebra ZC300 USB Card Printer"   # informativo; la conexión es USB directa
  #   allowed_options:
  #     back_type: ["color", "mono", "none"]
  #     overlay_front: ["true", "false"]
  #     overlay_back: ["true", "false"]
  #     source: ["feeder", "internal", "atm"]
"""


def ensure_config(data_dir: Path) -> str | None:
    """Crea `.env` (con API key aleatoria) y `printers.yaml` si faltan.

    Devuelve la API key recién generada, o None si `.env` ya existía.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    new_key = None
    env = data_dir / ".env"
    if not env.exists():
        new_key = secrets.token_urlsafe(24)
        env.write_text(f"CARDPRINT_API_KEY={new_key}\n", encoding="utf-8")
    printers = data_dir / "printers.yaml"
    if not printers.exists():
        printers.write_text(DEFAULT_PRINTERS, encoding="utf-8")
    return new_key
