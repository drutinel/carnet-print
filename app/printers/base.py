from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class PrintError(Exception):
    """Fallo al enviar el trabajo a la impresora."""


@dataclass(frozen=True)
class PrintRequest:
    copies: int
    options: dict[str, str]
    # PNG por cara: front, back y, opcionales, front_k / back_k (capa negra, panel K)
    faces: dict[str, Path]


class PrinterAdapter(ABC):
    # True si submit() vuelve cuando la tarjeta ya se imprimió, no solo cuando se encoló
    confirms_completion = False

    @abstractmethod
    def submit(self, request: PrintRequest) -> str:
        """Envía el trabajo y devuelve un id de trabajo del backend."""

    @abstractmethod
    def status(self) -> str:
        """'ready' | 'offline' | 'unknown'."""
