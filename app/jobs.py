import logging
import tempfile
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from .printers.base import PrintError, PrintRequest, PrinterAdapter

logger = logging.getLogger("cardprint.jobs")
MAX_JOBS = 500  # trabajos recordados en memoria; se descartan los terminados más viejos


@dataclass(frozen=True)
class Job:
    id: str
    printer_id: str
    copies: int
    state: str  # queued | submitted | printed | failed
    backend_job_id: str | None = None
    error: str | None = None
    template_id: str | None = None


class JobService:
    """Una cola serial por impresora: una impresora de carnets imprime un trabajo a la vez."""

    def __init__(self, adapters: dict[str, PrinterAdapter], max_jobs: int | None = None):
        self._adapters = adapters
        self._max_jobs = MAX_JOBS if max_jobs is None else max_jobs
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._pending = {pid: 0 for pid in adapters}  # trabajos en cola o imprimiendo
        self._generation = {pid: 0 for pid in adapters}  # sube al terminar cada trabajo
        self._lock = threading.Lock()
        self._executors = {pid: ThreadPoolExecutor(max_workers=1) for pid in adapters}

    def enqueue(
        self,
        printer_id: str,
        faces: dict[str, bytes],
        copies: int,
        options: dict[str, str],
        template_id: str | None = None,
    ) -> Job:
        """`faces`: PNG por cara (front, back, front_k, back_k)."""
        job = Job(
            id=uuid.uuid4().hex, printer_id=printer_id, copies=copies, state="queued",
            template_id=template_id,
        )
        face_paths: dict[str, Path] = {}
        for key, data in faces.items():
            with tempfile.NamedTemporaryFile(suffix=f"-{key}.png", delete=False) as tmp:
                tmp.write(data)
            face_paths[key] = Path(tmp.name)
        with self._lock:
            self._pending[printer_id] += 1
        self._set(job)
        request = PrintRequest(copies=copies, options=options, faces=face_paths)
        self._executors[printer_id].submit(self._run, job, request)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def is_busy(self, printer_id: str) -> bool:
        with self._lock:
            return self._pending[printer_id] > 0

    def generation(self, printer_id: str) -> int:
        with self._lock:
            return self._generation[printer_id]

    def shutdown(self) -> None:
        for ex in self._executors.values():
            ex.shutdown(wait=True)

    def _set(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._jobs.move_to_end(job.id)
            if len(self._jobs) > self._max_jobs:
                for old_id in [k for k, j in self._jobs.items() if j.state != "queued"]:
                    del self._jobs[old_id]
                    if len(self._jobs) <= self._max_jobs:
                        break

    def _run(self, job: Job, request: PrintRequest) -> None:
        try:
            adapter = self._adapters[job.printer_id]
            backend_id = adapter.submit(request)
            # "printed" solo si el backend confirma que la tarjeta salió (SDK)
            state = "printed" if adapter.confirms_completion else "submitted"
            self._set(replace(job, state=state, backend_job_id=backend_id))
        except PrintError as exc:
            logger.error("job %s falló: %s", job.id, exc)
            self._set(replace(job, state="failed", error=str(exc)))
        except Exception:  # noqa: BLE001 - el worker nunca debe morir en silencio
            logger.exception("job %s error inesperado", job.id)
            self._set(replace(job, state="failed", error="error interno"))
        finally:
            with self._lock:
                self._pending[job.printer_id] -= 1
                self._generation[job.printer_id] += 1
            for path in (request.faces or {}).values():
                path.unlink(missing_ok=True)
