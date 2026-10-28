from dataclasses import dataclass
from pathlib import Path

from .config import PrinterConfig, Settings
from .jobs import JobService
from .printers.base import PrinterAdapter
from .status import StatusCache
from .store import Store


@dataclass(frozen=True)
class Ctx:
    """Todo lo que comparten las rutas; vive en `app.state.ctx`."""

    settings: Settings
    registry: dict[str, tuple[PrinterConfig, PrinterAdapter]]
    jobs: JobService
    store: Store
    status: StatusCache
    png_root: Path
