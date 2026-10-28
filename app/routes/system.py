from fastapi import APIRouter, Depends

from ..ctx import Ctx
from ..deps import get_ctx
from ..preflight import failed, run_checks
from ..version import VERSION

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


@router.get("/preflight")
def preflight(ctx: Ctx = Depends(get_ctx)) -> list[dict]:
    """Qué le falta a esta PC para imprimir (con enlaces de descarga). Público: no lleva secretos."""
    return failed(run_checks([cfg for cfg, _ in ctx.registry.values()]))
