import hmac
import json
import re
import uuid
from datetime import datetime
from typing import Annotated
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Request, Depends, FastAPI, File, Form, Header, HTTPException, Path as PathParam, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, load_printers
from .jobs import Job, JobService
from .paths import resource_dir
from .preflight import failed, run_checks
from .printers.registry import build_registry
from .render import ImageError, faces_to_pdf, normalize_faces
from .store import NotFound, Store, StoreError

WEB_DIR = resource_dir() / "web"
MAX_COPIES = 10
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
# Campos del titular que un perfil de cliente puede dejar editables
KIOSK_FIELDS = {"name", "ced", "cat", "extra", "code", "issue", "photo"}
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
    png_dir: str | None = None  # carpeta (dentro de png/) con las imágenes de este trabajo


def _png_stem(control: str | None) -> str:
    """`20261028-131500_C-000001`: carpeta del trabajo; sin control, un id corto."""
    tag = re.sub(r"[^\w\-.]", "_", control or "")[:64] or uuid.uuid4().hex[:8]
    return f"{datetime.now():%Y%m%d-%H%M%S}_{tag}"


def _save_pngs(folder: Path, faces: dict[str, bytes]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for key, data in faces.items():
        (folder / f"{key}.png").write_bytes(data)


def _job_out(job: Job) -> JobOut:
    return JobOut(**job.__dict__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    registry = build_registry(load_printers(settings.printers_file))
    jobs = JobService({pid: adapter for pid, (_, adapter) in registry.items()})
    store = Store(settings.data_dir)
    png_root = settings.png_dir or settings.data_dir / "png"

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

    @app.get("/preflight")
    def preflight() -> list[dict]:
        """Qué le falta a esta PC para imprimir (con enlaces de descarga). Público: no lleva secretos."""
        return failed(run_checks([cfg for cfg, _ in registry.values()]))

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
        control: str | None = Form(None),
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
            normalized = await run_in_threadpool(normalize_faces, raw)
        except ImageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        faces: dict[str, bytes] | None = normalized
        if not adapter.accepts_faces:  # CUPS/Windows imprimen un PDF armado aquí
            data = await run_in_threadpool(faces_to_pdf, normalized["front"], normalized["back"])
            faces = None

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

        # Archivo de lo que se manda a imprimir; si no se puede guardar, no se imprime
        png_dir = png_root / _png_stem(control)
        try:
            await run_in_threadpool(_save_pngs, png_dir, normalized)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo guardar el PNG: {exc}") from exc

        job = jobs.enqueue(
            printer_id, data, copies, {k: str(v) for k, v in parsed.items()},
            faces=faces, template_id=template_id,
        )
        return JobOut(**job.__dict__, png_dir=png_dir.name)

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

    def validate_client(body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=422, detail="Falta el nombre del cliente")
        if body.get("template_id") not in store.list_templates()["templates"]:
            raise HTTPException(status_code=422, detail="Plantilla no existe")
        editable = body.get("editable", [])
        if not isinstance(editable, list) or not set(editable) <= KIOSK_FIELDS:
            raise HTTPException(
                status_code=422, detail=f"editable debe ser una lista de {sorted(KIOSK_FIELDS)}"
            )
        return {
            "name": name,
            "template_id": body["template_id"],
            "editable": sorted(set(editable)),
            "show_registry": bool(body.get("show_registry", False)),
        }

    @app.get("/clients", dependencies=[Depends(require_key)])
    def list_clients() -> dict:
        return store_call(store.list_clients)

    @app.put("/clients/{client_id}", dependencies=[Depends(require_key)])
    def put_client(client_id: ItemId, body: dict = Body(...)) -> dict:
        return store_call(store.put_client, client_id, validate_client(body))

    @app.delete("/clients/{client_id}", status_code=204, dependencies=[Depends(require_key)])
    def delete_client(client_id: ItemId) -> None:
        store_call(store.delete_client, client_id)

    def is_local(request: Request) -> bool:
        """Navegador en esta misma PC. También se mira el Host: con DNS rebinding una web ajena
        llega por loopback pero con otro nombre de host."""
        peer = request.client.host if request.client else ""
        return peer in LOOPBACK and request.url.hostname in LOCAL_HOSTNAMES

    def render_page(request: Request, kiosk: dict | None = None) -> HTMLResponse:
        """El generador con `window.BOOT` (y `window.KIOSK` en modo kiosko) ya incrustados.

        La API key solo se incrusta si el navegador está en esta PC: así la web abierta por el
        programa funciona sin pegar la clave; desde otra máquina la página la pide.
        """
        key = settings.api_key if is_local(request) else ""
        boot = {"api_key": key}
        if kiosk is not None:
            kiosk = {**kiosk, "api_key": key}
        data = "window.BOOT=" + json.dumps(boot) + (";window.KIOSK=" + json.dumps(kiosk) if kiosk else "")
        inject = "<script>" + data.replace("</", "<\\/") + "</script>\n"
        page = (WEB_DIR / "generador-carnets.html").read_text(encoding="utf-8")
        return HTMLResponse(
            page.replace("<script>\n(() => {", inject + "<script>\n(() => {", 1),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/c/{client_id}", response_class=HTMLResponse)
    def kiosk_page(client_id: ItemId, request: Request) -> HTMLResponse:
        """El generador ya configurado para un cliente: plantilla fija y solo sus campos editables."""
        client = store_call(store.get_client, client_id)
        return render_page(request, {"id": client_id, **client})

    @app.get("/ui/generador-carnets.html", response_class=HTMLResponse, include_in_schema=False)
    def admin_page(request: Request) -> HTMLResponse:
        return render_page(request)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/settings", dependencies=[Depends(require_key)])
    def get_settings() -> dict:
        return store_call(store.get_settings)

    @app.put("/settings", dependencies=[Depends(require_key)])
    def put_settings(body: dict = Body(...)) -> dict:
        return store_call(store.put_settings, body)

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
