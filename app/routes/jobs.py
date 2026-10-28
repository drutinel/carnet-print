import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_user
from ..render import ImageError, normalize_faces
from ..schemas import JobOut

router = APIRouter()
MAX_COPIES = 10


def _png_stem(control: str | None) -> str:
    """`20261028-131500_C-000001`: carpeta del trabajo; sin control, un id corto."""
    tag = re.sub(r"[^\w\-.]", "_", control or "")[:64] or uuid.uuid4().hex[:8]
    return f"{datetime.now():%Y%m%d-%H%M%S}_{tag}"


def _save_pngs(folder: Path, faces: dict[str, bytes]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for key, data in faces.items():
        (folder / f"{key}.png").write_bytes(data)


def _resolve_template(ctx: Ctx, principal: Principal, template_id: str | None) -> str | None:
    if not principal.is_admin:  # un kiosko solo imprime con la plantilla de su perfil
        own = principal.client["template_id"]
        if template_id not in (None, own):
            raise HTTPException(status_code=403, detail="Este perfil solo imprime con su plantilla")
        return own
    if template_id is None:
        return ctx.store.active_template_id()
    if template_id not in ctx.store.template_ids():
        raise HTTPException(status_code=422, detail="Plantilla no existe")
    return template_id


@router.post("/jobs", response_model=JobOut, status_code=202)
async def create_job(
    printer_id: str = Form(...),
    front: UploadFile = File(...),
    back: UploadFile = File(...),
    front_k: UploadFile | None = File(None),
    back_k: UploadFile | None = File(None),
    copies: int = Form(1, ge=1, le=MAX_COPIES),
    options: str = Form("{}", max_length=4000),
    template_id: str | None = Form(None, max_length=64),
    control: str | None = Form(None, max_length=64),
    ctx: Ctx = Depends(get_ctx),
    principal: Principal = Depends(require_user),
) -> JobOut:
    """Imprime directo: `front` y `back` en PNG, más `front_k` / `back_k` opcionales (capa negra,
    panel K, mismo tamaño que su cara). `template_id` es la plantilla con la que se armó el carnet;
    si no viene, se usa la activa (ver `/templates`)."""
    if printer_id not in ctx.registry:
        raise HTTPException(status_code=404, detail="Impresora no existe")
    cfg, _ = ctx.registry[printer_id]
    template_id = _resolve_template(ctx, principal, template_id)

    async def read_limited(upload: UploadFile) -> bytes:
        data = await upload.read(ctx.settings.max_upload_bytes + 1)
        if len(data) > ctx.settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Archivo demasiado grande")
        return data

    raw = {"front": await read_limited(front), "back": await read_limited(back)}
    for key, upload in (("front_k", front_k), ("back_k", back_k)):
        if upload is not None:
            raw[key] = await read_limited(upload)
    try:
        faces = await run_in_threadpool(normalize_faces, raw)
    except ImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        parsed = json.loads(options)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="options no es JSON válido") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="options debe ser un objeto")
    rejected = [
        k for k, v in parsed.items()
        if k not in cfg.allowed_options or (cfg.allowed_options[k] and str(v) not in cfg.allowed_options[k])
    ]
    if rejected:
        raise HTTPException(status_code=422, detail=f"Opciones o valores no permitidos: {rejected}")

    # Archivo de lo que se manda a imprimir; si no se puede guardar, no se imprime
    png_dir = ctx.png_root / _png_stem(control)
    try:
        await run_in_threadpool(_save_pngs, png_dir, faces)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo guardar el PNG: {exc}") from exc

    job = ctx.jobs.enqueue(
        printer_id, faces, copies, {k: str(v) for k, v in parsed.items()}, template_id=template_id
    )
    return JobOut(**job.__dict__, png_dir=png_dir.name)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_user)) -> JobOut:
    job = ctx.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no existe")
    return JobOut(**job.__dict__)
