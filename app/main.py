import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, load_printers
from .jobs import Job, JobService
from .printers.registry import build_registry
from .render import ImageError, faces_to_pdf, normalize_faces

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PDF_MAGIC = b"%PDF-"
MAX_COPIES = 10


class PrinterOut(BaseModel):
    id: str
    label: str
    status: str


class JobOut(BaseModel):
    id: str
    printer_id: str
    copies: int
    state: str
    backend_job_id: str | None = None
    error: str | None = None


def _job_out(job: Job) -> JobOut:
    return JobOut(**job.__dict__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    registry = build_registry(load_printers(settings.printers_file))
    jobs = JobService({pid: adapter for pid, (_, adapter) in registry.items()})

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="Card Print Middleware", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key"],
    )

    def require_key(x_api_key: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=401, detail="API key inválida")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/printers", response_model=list[PrinterOut], dependencies=[Depends(require_key)])
    def list_printers() -> list[PrinterOut]:
        # def (no async): lpstat bloquea, FastAPI lo corre en threadpool
        return [
            PrinterOut(id=cfg.id, label=cfg.label, status=adapter.status())
            for cfg, adapter in registry.values()
        ]

    @app.get("/printers/{printer_id}/options", dependencies=[Depends(require_key)])
    def printer_options(printer_id: str) -> dict[str, list[str]]:
        if printer_id not in registry:
            raise HTTPException(status_code=404, detail="Impresora no existe")
        return registry[printer_id][0].allowed_options

    @app.post("/jobs", response_model=JobOut, status_code=202, dependencies=[Depends(require_key)])
    async def create_job(
        printer_id: str = Form(...),
        pdf: UploadFile | None = File(None),
        front: UploadFile | None = File(None),
        back: UploadFile | None = File(None),
        front_k: UploadFile | None = File(None),
        back_k: UploadFile | None = File(None),
        copies: int = Form(1, ge=1, le=MAX_COPIES),
        options: str = Form("{}"),
    ) -> JobOut:
        """Un `pdf` ya renderizado (pág. 1 = frente, pág. 2 = reverso) o `front` + `back` en PNG.

        Con PNG, `front_k` / `back_k` opcionales: capa negra (panel K) del mismo tamaño que su
        cara. A un adaptador con SDK los PNG le llegan tal cual (sin PDF ni remuestreo); al resto,
        en un PDF sin pérdida.
        """
        if printer_id not in registry:
            raise HTTPException(status_code=404, detail="Impresora no existe")
        cfg, adapter = registry[printer_id]

        async def read_limited(upload: UploadFile) -> bytes:
            data = await upload.read(settings.max_pdf_bytes + 1)
            if len(data) > settings.max_pdf_bytes:
                raise HTTPException(status_code=413, detail="Archivo demasiado grande")
            return data

        data: bytes | None = None
        faces: dict[str, bytes] | None = None
        if pdf is not None:
            data = await read_limited(pdf)
            if not data.startswith(PDF_MAGIC):
                raise HTTPException(status_code=422, detail="El archivo no es un PDF")
        elif front is not None and back is not None:
            raw = {"front": await read_limited(front), "back": await read_limited(back)}
            for key, upload in (("front_k", front_k), ("back_k", back_k)):
                if upload is not None:
                    raw[key] = await read_limited(upload)
            try:
                faces = await run_in_threadpool(normalize_faces, raw)
                if not adapter.accepts_faces:  # capas K solo las usa un SDK
                    data = await run_in_threadpool(
                        faces_to_pdf, faces["front"], faces["back"]
                    )
                    faces = None
            except ImageError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        else:
            raise HTTPException(status_code=422, detail="Envía `pdf` o `front` y `back`")

        try:
            parsed = json.loads(options)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="options no es JSON válido") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=422, detail="options debe ser un objeto")
        rejected = [
            k
            for k, v in parsed.items()
            if k not in cfg.allowed_options
            or (cfg.allowed_options[k] and str(v) not in cfg.allowed_options[k])
        ]
        if rejected:
            raise HTTPException(
                status_code=422, detail=f"Opciones o valores no permitidos: {rejected}"
            )

        job = jobs.enqueue(
            printer_id, data, copies, {k: str(v) for k, v in parsed.items()}, faces=faces
        )
        return _job_out(job)

    @app.get("/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_key)])
    def get_job(job_id: str) -> JobOut:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabajo no existe")
        return _job_out(job)

    if WEB_DIR.is_dir():  # UI mismo origen: sin CORS ni API URL manual
        app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    return app
