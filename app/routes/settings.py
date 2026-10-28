from fastapi import APIRouter, Depends

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_admin, require_user
from ..schemas import SettingsIn

router = APIRouter()


@router.get("/settings")
def get_settings(ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_user)) -> dict:
    return ctx.store.get_settings()


@router.put("/settings")
def put_settings(body: SettingsIn, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)) -> dict:
    return ctx.store.put_settings(body.model_dump())
