from fastapi import APIRouter, Depends, HTTPException

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_admin, require_registry, require_user
from ..schemas import CardIn, CardRestore, ItemId

router = APIRouter()


@router.get("/cards")
def list_cards(
    full: bool = False, ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_registry)
) -> list[dict]:
    """Registro sin imágenes (liviano). `full=true` las incluye (respaldo; solo administrador)."""
    if full and not principal.is_admin:
        raise HTTPException(status_code=403, detail="Solo el administrador puede pedir los carnets completos")
    return ctx.store.list_cards(full=full)


@router.get("/cards/last")
def last_card(ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> dict:
    """El último carnet emitido por este usuario (el administrador ve el último de todos)."""
    return ctx.store.last_card(None if principal.is_admin else principal.client_id)


@router.get("/cards/{control}")
def get_card(control: ItemId, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_registry)) -> dict:
    return ctx.store.get_card(control)


@router.post("/cards", status_code=201)
def create_card(body: CardIn, ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> dict:
    """Alta: el servidor asigna el control (C-000001…) y el código si viene vacío."""
    if principal.is_admin:
        template_id = body.templateId
        if template_id and template_id not in ctx.store.template_ids():
            raise HTTPException(status_code=422, detail="Plantilla no existe")
    else:
        template_id = principal.client["template_id"]
    return ctx.store.create_card(body.model_dump(exclude={"templateId"}), template_id, principal.client_id or "admin")


@router.put("/cards/{control}")
def restore_card(
    control: ItemId, body: CardRestore, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)
) -> dict:
    """Restaura un carnet de un respaldo con su control original."""
    return ctx.store.put_card(control, body.model_dump())


@router.post("/cards/{control}/reprint")
def reprint_card(control: ItemId, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_registry)) -> dict:
    return ctx.store.reprint_card(control)


@router.post("/cards/{control}/void")
def void_card(control: ItemId, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)) -> dict:
    return ctx.store.void_card(control)
