import hmac
import json
from typing import Annotated
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Path as PathParam, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, load_printers
from .jobs import Job, JobService
from .paths import resource_dir
from .printers.registry import build_registry
from .render import ImageError, faces_to_pdf, normalize_faces
from .store import NotFound, Store, StoreError

WEB_DIR = resource_dir() / "web"
MAX_COPIES = 10
# id de plantilla / número de control: se usan como clave en el JSON y en la URL
ItemId = Annotated[str, PathParam(pattern=r"^[\w\-. ]{1,64}$")]


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
    template_id: str | None = None


def _job_out(job: Job) -> JobOut:
    return JobOut(**job.__dict__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    registry = build_registry(load_printers(settings.printers_file))
    jobs = JobService({pid: adapter for pid, (_, adapter) in registry.items()})
    store = Store(settings.data_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="Card Print Middleware", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
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
        front: UploadFile = File(...),
        back: UploadFile = File(...),
        front_k: UploadFile | None = File(None),
        back_k: UploadFile | None = File(None),
        copies: int = Form(1, ge=1, le=MAX_COPIES),
        options: str = Form("{}"),
        template_id: str | None = Form(None),
    ) -> JobOut:
        """Imprime directo: `front` y `back` en PNG (sin PDF), más `front_k` / `back_k`
        opcionales (capa negra, panel K, mismo tamaño que su cara).

        `template_id` es la plantilla con la que se armó el carnet; si no viene, se usa la
        plantilla activa del API (ver `/templates`).
        """
        if printer_id not in registry:
            raise HTTPException(status_code=404, detail="Impresora no existe")
        cfg, adapter = registry[printer_id]

        if template_id is None:
            template_id = store.active_template_id()
        elif template_id not in store.list_templates()["templates"]:
            raise HTTPException(status_code=422, detail="Plantilla no existe")

        async def read_limited(upload: UploadFile) -> bytes:
            data = await upload.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Archivo demasiado grande")
            return data

        raw = {"front": await read_limited(front), "back": await read_limited(back)}
        for key, upload in (("front_k", front_k), ("back_k", back_k)):
            if upload is not None:
                raw[key] = await read_limited(upload)
        data: bytes | None = None
        try:
            faces: dict[str, bytes] | None = await run_in_threadpool(normalize_faces, raw)
            if not adapter.accepts_faces:  # CUPS/Windows imprimen un PDF armado aquí
                data = await run_in_threadpool(faces_to_pdf, faces["front"], faces["back"])
                faces = None
        except ImageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            printer_id, data, copies, {k: str(v) for k, v in parsed.items()},
            faces=faces, template_id=template_id,
        )
        return _job_out(job)

    # --- plantillas y carnets generados: JSON junto al .exe (templates.json, carnets.json) ---
    def store_call(fn, *args):
        try:
            return fn(*args)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/templates", dependencies=[Depends(require_key)])
    def list_templates() -> dict:
        """`{active, templates}`; `active` es la plantilla que usa el API por defecto."""
        return store_call(store.list_templates)

    @app.get("/templates/{template_id}", dependencies=[Depends(require_key)])
    def get_template(template_id: ItemId) -> dict:
        return store_call(store.get_template, template_id)

    @app.put("/templates/{template_id}", dependencies=[Depends(require_key)])
    def put_template(template_id: ItemId, body: dict = Body(...)) -> dict:
        return store_call(store.put_template, template_id, body)

    @app.delete("/templates/{template_id}", status_code=204, dependencies=[Depends(require_key)])
    def delete_template(template_id: ItemId) -> None:
        store_call(store.delete_template, template_id)

    @app.post("/templates/{template_id}/activate", dependencies=[Depends(require_key)])
    def activate_template(template_id: ItemId) -> dict:
        store_call(store.activate_template, template_id)
        return store.list_templates()

    @app.get("/cards", dependencies=[Depends(require_key)])
    def list_cards() -> list[dict]:
        return store_call(store.list_cards)

    @app.put("/cards/{control}", dependencies=[Depends(require_key)])
    def put_card(control: ItemId, body: dict = Body(...)) -> dict:
        return store_call(store.put_card, control, body)

    @app.get("/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_key)])
    def get_job(job_id: str) -> JobOut:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabajo no existe")
        return _job_out(job)

    if WEB_DIR.is_dir():  # UI mismo origen: sin CORS ni API URL manual
        app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    return app
