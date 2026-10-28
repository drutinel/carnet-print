from fastapi import APIRouter, Depends, HTTPException

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_admin, require_user
from ..schemas import ItemId, TemplateIn

router = APIRouter()


@router.get("/templates")
def list_templates(ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> dict:
    """`{active, templates}`; `active` es la plantilla que usa el API por defecto.
    Un kiosko solo ve la de su perfil."""
    data = ctx.store.list_templates()
    if principal.is_admin:
        return data
    own = principal.client["template_id"]
    return {"active": own, "templates": {k: v for k, v in data["templates"].items() if k == own}}


@router.get("/templates/{template_id}")
def get_template(template_id: ItemId, ctx: Ctx = Depends(get_ctx), principal: Principal = Depends(require_user)) -> dict:
    if not principal.is_admin and template_id != principal.client["template_id"]:
        raise HTTPException(status_code=403, detail="Este perfil solo ve su plantilla")
    return ctx.store.get_template(template_id)


@router.put("/templates/{template_id}")
def put_template(
    template_id: ItemId, body: TemplateIn, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)
) -> dict:
    return ctx.store.put_template(template_id, body.model_dump())


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: ItemId, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)) -> None:
    ctx.store.delete_template(template_id)


@router.post("/templates/{template_id}/activate")
def activate_template(template_id: ItemId, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)) -> dict:
    ctx.store.activate_template(template_id)
    return ctx.store.list_templates()
