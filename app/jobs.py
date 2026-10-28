import logging
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from .printers.base import PrintError, PrintRequest, PrinterAdapter

logger = logging.getLogger("cardprint.jobs")


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

    def __init__(self, adapters: dict[str, PrinterAdapter]):
        self._adapters = adapters
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executors = {pid: ThreadPoolExecutor(max_workers=1) for pid in adapters}

    def enqueue(
        self,
        printer_id: str,
        pdf: bytes | None,
        copies: int,
        options: dict[str, str],
        faces: dict[str, bytes] | None = None,
        template_id: str | None = None,
    ) -> Job:
        """`faces` (PNG por cara: front, back, front_k, back_k); `pdf` solo para adaptadores
        sin SDK (CUPS/Windows), que lo arma el API a partir de las caras."""
        job = Job(
            id=uuid.uuid4().hex, printer_id=printer_id, copies=copies, state="queued",
            template_id=template_id,
        )
        pdf_path = None
        face_paths = None
        if faces:
            face_paths = {}
            for key, data in faces.items():
                with tempfile.NamedTemporaryFile(suffix=f"-{key}.png", delete=False) as tmp:
                    tmp.write(data)
                face_paths[key] = Path(tmp.name)
        else:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf)
            pdf_path = Path(tmp.name)
        self._set(job)
        request = PrintRequest(
            pdf_path=pdf_path, copies=copies, options=options, faces=face_paths
        )
        self._executors[printer_id].submit(self._run, job, request)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        for ex in self._executors.values():
            ex.shutdown(wait=True)

    def _set(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

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
            for path in [request.pdf_path, *(request.faces or {}).values()]:
                if path is not None:
                    path.unlink(missing_ok=True)
