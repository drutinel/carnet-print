from fastapi import APIRouter, Depends, HTTPException

from ..ctx import Ctx
from ..deps import Principal, get_ctx, require_admin
from ..schemas import ClientIn, ItemId

router = APIRouter()


@router.get("/clients")
def list_clients(ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)) -> dict:
    return ctx.store.list_clients()


@router.put("/clients/{client_id}")
def put_client(
    client_id: ItemId, body: ClientIn, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)
) -> dict:
    if body.template_id not in ctx.store.template_ids():
        raise HTTPException(status_code=422, detail="Plantilla no existe")
    return ctx.store.put_client(
        client_id, {**body.model_dump(exclude={"editable"}), "editable": sorted(set(body.editable))}
    )


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: ItemId, ctx: Ctx = Depends(get_ctx), _: Principal = Depends(require_admin)) -> None:
    ctx.store.delete_client(client_id)
