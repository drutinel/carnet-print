import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from .ctx import Ctx


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


@dataclass(frozen=True)
class Principal:
    """Quién llama: el administrador (API key) o un kiosko (token propio de su perfil)."""

    client_id: str | None = None
    client: dict | None = None

    @property
    def is_admin(self) -> bool:
        return self.client_id is None


def get_principal(x_api_key: str = Header(default=""), ctx: Ctx = Depends(get_ctx)) -> Principal:
    if hmac.compare_digest(x_api_key.encode(), ctx.settings.api_key.encode()):
        return Principal()
    found = ctx.store.client_for_token(x_api_key)
    if found is None:
        raise HTTPException(status_code=401, detail="API key inválida")
    return Principal(client_id=found[0], client=found[1])


def require_user(principal: Principal = Depends(get_principal)) -> Principal:
    """Administrador o kiosko."""
    return principal


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Solo el administrador puede hacer esto")
    return principal


def require_registry(principal: Principal = Depends(get_principal)) -> Principal:
    """El administrador, o un kiosko cuyo perfil muestra el registro."""
    if not principal.is_admin and not principal.client.get("show_registry"):
        raise HTTPException(status_code=403, detail="Este perfil no tiene acceso al registro")
    return principal
