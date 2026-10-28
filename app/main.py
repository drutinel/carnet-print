from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, load_printers
from .ctx import Ctx
from .jobs import JobService
from .printers.registry import build_registry
from .routes import cards, clients, draft, jobs, pages, printers, settings as settings_routes, system, templates
from .status import StatusCache
from .store import Conflict, NotFound, Store, StoreError


class RevalidatedStatic(StaticFiles):
    """Archivos de la web que el navegador revalida siempre (ETag): tras actualizar el programa no
    se queda con un app.js viejo en caché mezclado con un HTML nuevo."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def build_ctx(settings: Settings) -> Ctx:
    """Impresoras, cola de trabajos y almacén: lo comparten el servidor y la línea de comandos."""
    registry = build_registry(load_printers(settings.printers_file))
    adapters = {pid: adapter for pid, (_, adapter) in registry.items()}
    job_service = JobService(adapters)
    store = Store(settings.data_dir)
    store.compact()  # imágenes de JSON antiguos -> carpeta images/
    return Ctx(
        settings=settings,
        registry=registry,
        jobs=job_service,
        store=store,
        status=StatusCache(adapters, job_service),
        png_root=settings.png_dir or settings.data_dir / "png",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    ctx = build_ctx(settings)
    job_service = ctx.jobs

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        job_service.shutdown()

    app = FastAPI(title="CarnetPrint", lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["X-API-Key"],
    )

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(StoreError)
    async def store_error(_: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    for module in (system, printers, jobs, templates, cards, clients, draft, settings_routes, pages):
        app.include_router(module.router)

    web_dir = pages.WEB_DIR
    if web_dir.is_dir():  # css y js de la UI, mismo origen: sin CORS ni API URL manual
        app.mount("/ui", RevalidatedStatic(directory=web_dir), name="ui")
    return app
