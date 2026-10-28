from fastapi import APIRouter, Depends

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_user
from ..schemas import DraftIn

router = APIRouter()


def _key(principal: Principal) -> str:
    return principal.client_id or "admin"


@router.get("/draft")
def get_draft(ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> dict:
    """El carnet que se estaba llenando (vacío si no hay). Cada kiosko tiene el suyo."""
    return ctx.store.get_draft(_key(principal))


@router.put("/draft")
def put_draft(body: DraftIn, ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> dict:
    return ctx.store.put_draft(_key(principal), body.model_dump())


@router.delete("/draft", status_code=204)
def delete_draft(ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> None:
    ctx.store.delete_draft(_key(principal))
