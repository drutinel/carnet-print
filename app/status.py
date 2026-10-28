import threading
import time

from .jobs import JobService
from .printers.base import PrinterAdapter


class StatusCache:
    """Estado de cada impresora con caché: consultarla lanza el puente (hasta 30 s), así que no
    se hace por cada petición ni mientras hay un trabajo en curso.

    - Con trabajo en cola o imprimiendo responde `busy` sin tocar el puente.
    - Si otra consulta ya está en marcha, devuelve el último valor conocido.
    - Al terminar un trabajo se vuelve a consultar aunque no haya vencido el tiempo.
    """

    def __init__(self, adapters: dict[str, PrinterAdapter], jobs: JobService, ttl: float = 20.0, clock=time.monotonic):
        self._adapters = adapters
        self._jobs = jobs
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[str, tuple[float, int, str]] = {}  # id -> (cuándo, generación, estado)
        self._locks = {pid: threading.Lock() for pid in adapters}

    def get(self, printer_id: str) -> str:
        if self._jobs.is_busy(printer_id):
            return "busy"
        generation = self._jobs.generation(printer_id)
        cached = self._cache.get(printer_id)
        if cached and cached[1] == generation and self._clock() - cached[0] < self._ttl:
            return cached[2]
        lock = self._locks[printer_id]
        if not lock.acquire(blocking=False):
            return cached[2] if cached else "unknown"
        try:
            status = self._adapters[printer_id].status()
            self._cache[printer_id] = (self._clock(), generation, status)
            return status
        finally:
            lock.release()
