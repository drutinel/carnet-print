import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Carpeta de datos: junto al .exe empaquetado, o la raíz del repo en desarrollo."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Recursos de solo lectura (web/): dentro del paquete PyInstaller, o la raíz del repo."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return Path(__file__).resolve().parent.parent
