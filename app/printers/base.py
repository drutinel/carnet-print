from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class PrintError(Exception):
    """Fallo al enviar el trabajo a la impresora."""


@dataclass(frozen=True)
class PrintRequest:
    pdf_path: Path | None
    copies: int
    options: dict[str, str]
    # PNG por cara (front, back, front_k, back_k) para adaptadores con accepts_faces;
    # si viene, pdf_path es None
    faces: dict[str, Path] | None = None


class PrinterAdapter(ABC):
    # True si submit() vuelve cuando la tarjeta ya se imprimió, no solo cuando se encoló
    confirms_completion = False
    # True si submit() acepta request.faces (PNG nativos) en vez de un PDF
    accepts_faces = False

    @abstractmethod
    def submit(self, request: PrintRequest) -> str:
        """Envía el trabajo y devuelve un id de trabajo del backend."""

    @abstractmethod
    def status(self) -> str:
        """'ready' | 'offline' | 'unknown'."""
