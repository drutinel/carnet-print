import os
import subprocess
from pathlib import Path

from .base import PrintError, PrintRequest, PrinterAdapter

PRINT_TIMEOUT_S = 60
STATUS_TIMEOUT_S = 15
DEFAULT_SUMATRA = r"C:\Program Files\SumatraPDF\SumatraPDF.exe"
# PrinterStatus de Get-Printer (Normal = lista)
_READY = {"Normal", "Printing", "Idle"}


class WindowsAdapter(PrinterAdapter):
    """Imprime PDFs en una impresora instalada en Windows (driver XPS/oficial) vía SumatraPDF.

    Los ajustes del driver (cinta, overlay, dúplex) se fijan en Preferencias de impresión de
    Windows para esa impresora; aquí solo se pasan copias y el tamaño de página.
    """

    def __init__(self, printer_name: str, sumatra_path: str | None = None):
        self._printer_name = printer_name
        self._sumatra = sumatra_path or DEFAULT_SUMATRA

    def submit(self, request: PrintRequest) -> str:
        if request.options:
            raise PrintError("El conector de Windows no acepta opciones por trabajo")
        if not Path(self._sumatra).exists():
            raise PrintError(f"No se encontró SumatraPDF en {self._sumatra}")
        cmd = [
            self._sumatra,
            "-print-to", self._printer_name,
            "-print-settings", f"noscale,{request.copies}x",
            "-silent",
            str(request.pdf_path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=PRINT_TIMEOUT_S, check=True)
        except subprocess.TimeoutExpired as exc:
            raise PrintError("Timeout enviando a la impresora de Windows") from exc
        except subprocess.CalledProcessError as exc:
            raise PrintError(f"SumatraPDF falló: {exc.stderr.strip() or exc.returncode}") from exc
        return f"windows:{self._printer_name}"

    def status(self) -> str:
        # Con -Command, $args no recibe argumentos extra: el nombre va por variable de entorno
        ps = "(Get-Printer -Name $env:CARDPRINT_PRINTER -ErrorAction Stop).PrinterStatus"
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=STATUS_TIMEOUT_S,
                env={**os.environ, "CARDPRINT_PRINTER": self._printer_name},
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "unknown"
        if out.returncode != 0:
            return "offline"
        return "ready" if out.stdout.strip() in _READY else "offline"
