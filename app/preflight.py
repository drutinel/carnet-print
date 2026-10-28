"""Comprobaciones al abrir el programa: lo que debe tener la PC para imprimir con la Sigma DS3.

Solo en Windows y solo para impresoras `entrust-sdk`. Cada fallo trae el enlace de descarga.
No descarga nada: el operador decide si instala.
"""
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import PrinterConfig
from .printers.entrust_sdk import find_bridge

DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet/8.0"
DRIVER_URL = "https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe"
SUPPORT_URL = "https://www.entrust.com/support/instant-id-card-issuance-systems/ds3-direct-to-card-printer-support"
MIN_DOTNET_MAJOR = 8
POWERSHELL_TIMEOUT_S = 15


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    title: str
    detail: str = ""
    url: str = ""
    url_label: str = ""


def desktop_runtime_major(program_files: Path) -> int | None:
    """Mayor versión instalada de Microsoft.WindowsDesktop.App (la que necesita CardBridge)."""
    base = program_files / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"
    majors = [
        int(p.name.split(".")[0]) for p in base.glob("*") if p.name.split(".")[0].isdigit()
    ] if base.is_dir() else []
    return max(majors, default=None)


def windows_printer_driver(name: str) -> str | None:
    """Nombre del driver de la impresora `name` en Windows, o None si no está instalada."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Printer -Name $env:CARDPRINT_CHECK_PRINTER -ErrorAction Stop).DriverName"],
        capture_output=True, text=True, timeout=POWERSHELL_TIMEOUT_S,
        env={**os.environ, "CARDPRINT_CHECK_PRINTER": name},
    )
    return out.stdout.strip() or None if out.returncode == 0 else None


def run_checks(
    printers: list[PrinterConfig],
    *,
    platform: str = sys.platform,
    program_files: Path | None = None,
    printer_driver=windows_printer_driver,
) -> list[Check]:
    entrust = [p for p in printers if p.adapter == "entrust-sdk"]
    if platform != "win32" or not entrust:
        return []
    program_files = program_files or Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    checks: list[Check] = []

    major = desktop_runtime_major(program_files)
    checks.append(Check(
        "dotnet", major is not None and major >= MIN_DOTNET_MAJOR,
        ".NET 8 Desktop Runtime",
        "Instala «.NET Desktop Runtime 8» (x64): lo necesita el puente con la impresora.",
        DOTNET_URL, "Descargar .NET 8 Desktop Runtime",
    ))

    for cfg in entrust:
        bridge = Path(cfg.bridge_path) if cfg.bridge_path else find_bridge()
        checks.append(Check(
            f"bridge:{cfg.id}", bridge.exists(), "Puente CardBridge.exe",
            f"No está en {bridge}. Copia la carpeta «bridge» junto a CarnetPrint.exe.",
        ))
        try:
            driver = printer_driver(cfg.printer_name or "")
            detail = (
                f"Windows no tiene una impresora llamada «{cfg.printer_name}». Instala el driver XPS "
                "de Entrust, conecta y enciende la DS3, o corrige printer_name en printers.yaml."
            )
        except (OSError, subprocess.SubprocessError):
            driver, detail = None, "No se pudo consultar las impresoras de Windows (PowerShell)."
        checks.append(Check(
            f"printer:{cfg.id}", driver is not None, f"Driver e impresora de Entrust ({cfg.label})",
            detail, DRIVER_URL, "Descargar driver XPS de Entrust 8.8",
        ))
    return checks


def failed(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks if not c.ok]
