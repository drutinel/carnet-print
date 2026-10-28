from fastapi import APIRouter, Depends, HTTPException

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_user
from ..schemas import PrinterOut

router = APIRouter()


@router.get("/printers", response_model=list[PrinterOut])
def list_printers(ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_user)) -> list[PrinterOut]:
    # def (no async): el estado puede lanzar el puente; FastAPI lo corre en threadpool (y va con caché)
    return [PrinterOut(id=cfg.id, label=cfg.label, status=ctx.status.get(cfg.id)) for cfg, _ in ctx.registry.values()]


@router.get("/printers/{printer_id}/options")
def printer_options(
    printer_id: str, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_user)
) -> dict[str, list[str]]:
    if printer_id not in ctx.registry:
        raise HTTPException(status_code=404, detail="Impresora no existe")
    return ctx.registry[printer_id][0].allowed_options
