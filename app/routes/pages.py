import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from ..ctx import Ctx
from ..deps import get_ctx
from ..paths import resource_dir
from ..schemas import ItemId

router = APIRouter()
WEB_DIR = resource_dir() / "web"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def is_local(request: Request) -> bool:
    """Navegador en esta misma PC. También se mira el Host: con DNS rebinding una web ajena
    llega por loopback pero con otro nombre de host."""
    peer = request.client.host if request.client else ""
    return peer in LOOPBACK and request.url.hostname in LOCAL_HOSTNAMES


def render_page(boot: dict, kiosk: dict | None = None) -> HTMLResponse:
    """El generador con `window.BOOT` (y `window.KIOSK` en modo kiosko) ya incrustados."""
    data = "window.BOOT=" + json.dumps(boot) + (";window.KIOSK=" + json.dumps(kiosk) if kiosk else "")
    inject = "<script>" + data.replace("</", "<\\/") + "</script>\n"
    page = (WEB_DIR / "generador-carnets.html").read_text(encoding="utf-8")
    marker = '<script src="/ui/app.js"'
    return HTMLResponse(page.replace(marker, inject + marker, 1), headers={"Cache-Control": "no-store"})


@router.get("/ui/generador-carnets.html", response_class=HTMLResponse, include_in_schema=False)
def admin_page(request: Request, ctx: Ctx = Depends(get_ctx)) -> HTMLResponse:
    """La clave del administrador solo se incrusta si el navegador está en esta PC: así la web
    que abre el programa funciona sin pegarla; desde otra máquina la página la pide."""
    return render_page({"api_key": ctx.settings.api_key if is_local(request) else ""})


@router.get("/c/{client_id}", response_class=HTMLResponse)
def kiosk_page(client_id: ItemId, ctx: Ctx = Depends(get_ctx)) -> HTMLResponse:
    """El generador ya configurado para un cliente: plantilla fija y solo sus campos editables.

    Lleva el token propio del perfil (no la API key): solo puede imprimir con su plantilla,
    crear carnets y leer lo necesario. Quien llegue a esta URL puede usar el kiosko.
    """
    client = ctx.store.get_client(client_id)
    kiosk = {"id": client_id, **{k: v for k, v in client.items() if k != "token"}, "api_key": client["token"]}
    return render_page({"api_key": ""}, kiosk)


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)
