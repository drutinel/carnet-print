from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_user
from ..schemas import JobOut
from ..services import MAX_COPIES, PrintRejected, parse_options, submit_print

router = APIRouter()


@router.post("/jobs", response_model=JobOut, status_code=202)
async def create_job(
    printer_id: str = Form(...),
    front: UploadFile = File(...),
    back: UploadFile = File(...),
    front_k: UploadFile | None = File(None),
    back_k: UploadFile | None = File(None),
    copies: int = Form(1, ge=1, le=MAX_COPIES),
    options: str | None = Form(None, max_length=4000),   # sin él: las de «Avanzado» (settings.json)
    template_id: str | None = Form(None, max_length=64),
    control: str | None = Form(None, max_length=64),
    ctx: Ctx = Depends(get_ctx),
    principal: Principal = Depends(require_user),
) -> JobOut:
    """Imprime directo: `front` y `back` en PNG, más `front_k` / `back_k` opcionales (capa negra,
    panel K, mismo tamaño que su cara). `template_id` es la plantilla con la que se armó el carnet;
    si no viene, se usa la activa (ver `/templates`)."""
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
        job, png_dir = await run_in_threadpool(
            submit_print, ctx, principal, printer_id=printer_id, raw_faces=raw, copies=copies,
            options=None if options is None else parse_options(options), template_id=template_id, control=control,
        )
    except PrintRejected as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return JobOut(**job.__dict__, png_dir=png_dir)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_user)) -> JobOut:
    job = ctx.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no existe")
    return JobOut(**job.__dict__)
