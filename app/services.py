"""Imprimir un carnet: la misma lógica para el API (POST /jobs) y para la línea de comandos."""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from .ctx import Ctx
from .deps import Principal
from .jobs import Job
from .render import ImageError, normalize_faces

MAX_COPIES = 10


class PrintRejected(Exception):
    """La petición no se puede imprimir; `status` es el código HTTP equivalente."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def control_tag(control: str) -> str:
    """El control como se escribe en el nombre de la carpeta de PNG (sin caracteres raros)."""
    return re.sub(r"[^\w\-.]", "_", control)[:64]


def png_stem(control: str | None) -> str:
    """`20261028-131500_C-000001`: carpeta del trabajo; sin control, un id corto."""
    tag = control_tag(control or "") or uuid.uuid4().hex[:8]
    return f"{datetime.now():%Y%m%d-%H%M%S}_{tag}"


_FINE = {"print_mode": "custom", "color_dpi": "300x300", "mono_dpi": "300x600"}
_STANDARD = {"print_mode": "standard"}


def default_options(ctx: Ctx, printer_id: str) -> dict[str, str]:
    """Opciones de «Avanzado» (calidad, tolva, split ribbon) tal como están en settings.json,
    limitadas a las que `printers.yaml` permite para esa impresora."""
    saved = ctx.store.get_settings()
    wanted = dict(_FINE if saved.get("quality", "fine") == "fine" else _STANDARD)
    if saved.get("hopper"):
        wanted["hopper"] = str(saved["hopper"])
    if saved.get("cal", {}).get(printer_id, {}).get("split"):
        wanted["split_ribbon"] = "ymct_k"
    allowed = ctx.registry[printer_id][0].allowed_options
    return {k: v for k, v in wanted.items() if k in allowed and (not allowed[k] or v in allowed[k])}


def _save_pngs(folder: Path, faces: dict[str, bytes]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for key, data in faces.items():
        (folder / f"{key}.png").write_bytes(data)


def resolve_template(ctx: Ctx, principal: Principal, template_id: str | None) -> str | None:
    if not principal.is_admin:  # un kiosko solo imprime con la plantilla de su perfil
        own = principal.client["template_id"]
        if template_id not in (None, own):
            raise PrintRejected(403, "Este perfil solo imprime con su plantilla")
        return own
    if template_id is None:
        return ctx.store.active_template_id()
    if template_id not in ctx.store.template_ids():
        raise PrintRejected(422, "Plantilla no existe")
    return template_id


def check_options(ctx: Ctx, printer_id: str, options: dict) -> dict[str, str]:
    """Solo opciones y valores que `printers.yaml` permite para esa impresora."""
    allowed = ctx.registry[printer_id][0].allowed_options
    rejected = [
        k for k, v in options.items()
        if k not in allowed or (allowed[k] and str(v) not in allowed[k])
    ]
    if rejected:
        raise PrintRejected(422, f"Opciones o valores no permitidos: {rejected}")
    return {k: str(v) for k, v in options.items()}


def parse_options(text: str) -> dict:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PrintRejected(422, "options no es JSON válido") from exc
    if not isinstance(parsed, dict):
        raise PrintRejected(422, "options debe ser un objeto")
    return parsed


def submit_print(
    ctx: Ctx,
    principal: Principal,
    *,
    printer_id: str,
    raw_faces: dict[str, bytes],
    copies: int,
    options: dict | None = None,   # None = las de «Avanzado» (settings.json)
    template_id: str | None = None,
    control: str | None = None,
) -> tuple[Job, str]:
    """Valida, archiva los PNG y encola el trabajo. Devuelve (trabajo, carpeta dentro de png/)."""
    if printer_id not in ctx.registry:
        raise PrintRejected(404, "Impresora no existe")
    if not 1 <= copies <= MAX_COPIES:
        raise PrintRejected(422, f"Las copias deben estar entre 1 y {MAX_COPIES}")
    template_id = resolve_template(ctx, principal, template_id)
    try:
        faces = normalize_faces(raw_faces)
    except ImageError as exc:
        raise PrintRejected(422, str(exc)) from exc
    clean = check_options(ctx, printer_id, default_options(ctx, printer_id) if options is None else options)

    # Archivo de lo que se manda a imprimir; si no se puede guardar, no se imprime
    png_dir = ctx.png_root / png_stem(control)
    try:
        _save_pngs(png_dir, faces)
    except OSError as exc:
        raise PrintRejected(500, f"No se pudo guardar el PNG: {exc}") from exc

    job = ctx.jobs.enqueue(printer_id, faces, copies, clean, template_id=template_id)
    return job, png_dir.name
