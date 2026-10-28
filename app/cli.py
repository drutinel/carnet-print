"""Línea de comandos: imprimir sin abrir la web.

    CarnetPrint.exe print --front f.png --back b.png [--front-k fk.png --back-k bk.png]
    CarnetPrint.exe print --png-dir png\\20261028-131500_C-000001      (reimprime un trabajo archivado)
    CarnetPrint.exe print --card C-000001                              (reimprime un carnet registrado)
    CarnetPrint.exe printers [--json]

Si el programa ya está abierto, el trabajo pasa por su cola (así dos impresiones nunca se pisan);
si no, imprime directo con el mismo código del API. Códigos de salida: 0 impreso, 1 falló, 2 petición inválida.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .bootstrap import ensure_config
from .config import Settings
from .deps import Principal
from .main import build_ctx
from .paths import app_dir
from .services import MAX_COPIES, PrintRejected, control_tag, submit_print
from .version import VERSION

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2
FACES = ("front", "back", "front_k", "back_k")
WAIT_S = 480   # un poco más que lo que espera el puente (PRINT_TIMEOUT_S)
POLL_S = 1.0
HEALTH_TIMEOUT_S = 0.7


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="CarnetPrint", description="CarnetPrint por línea de comandos")
    sub = parser.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("print", help="imprime PNG ya hechos (sin abrir la web)")
    pr.add_argument("--front", type=Path, help="PNG del frente (con --back)")
    pr.add_argument("--back", type=Path, help="PNG del reverso (con --front)")
    pr.add_argument("--front-k", type=Path, help="capa negra del frente (1 bit, mismo tamaño)")
    pr.add_argument("--back-k", type=Path, help="capa negra del reverso")
    pr.add_argument("--png-dir", type=Path, help="carpeta de un trabajo archivado (front.png, back.png, …)")
    pr.add_argument("--card", metavar="C-000001", help="reimprime ese carnet con su PNG archivado en png/")
    pr.add_argument("--printer", help="id de la impresora (por omisión, la única o la de Avanzado)")
    pr.add_argument("--copies", type=int, default=1, help=f"1-{MAX_COPIES}")
    pr.add_argument("--option", action="append", default=[], metavar="CLAVE=VALOR",
                    help="opción de la impresora (repetible); con ella se usan SOLO las indicadas, no las de Avanzado")
    pr.add_argument("--template", help="id de la plantilla con la que se hizo (por omisión, la activa)")
    pr.add_argument("--control", help="número de control para nombrar la carpeta de PNG")
    pr.add_argument("--timeout", type=int, default=WAIT_S, help="segundos máximos de espera")
    pr.add_argument("--json", action="store_true", help="resultado en JSON (una línea) en vez de texto")
    pr.add_argument("--quiet", action="store_true", help="sin avances en pantalla")

    pl = sub.add_parser("printers", help="lista las impresoras y su estado")
    pl.add_argument("--json", action="store_true")
    return parser


# ---------- entradas ----------
def _read(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise CliError(f"No existe el archivo {path}")
    if path.stat().st_size > limit:
        raise CliError(f"{path} es demasiado grande (máximo {limit // 1_000_000} MB)")
    return path.read_bytes()


def latest_archive(png_root: Path, control: str) -> Path:
    """La carpeta de PNG más reciente de ese carnet (`AAAAMMDD-HHMMSS_<control>`)."""
    folders = sorted(p for p in png_root.glob(f"*_{control_tag(control)}") if p.is_dir())
    if not folders:
        raise CliError(f"No hay PNG archivados de {control} en {png_root}. Imprímelo desde la web o usa --front/--back")
    return folders[-1]


def collect_faces(args, png_root: Path, limit: int) -> tuple[dict[str, bytes], str | None]:
    """Los PNG a imprimir y el control con el que se archivan."""
    sources = [bool(args.card), bool(args.png_dir), bool(args.front or args.back)]
    if sum(sources) != 1:
        raise CliError("Indica una sola fuente: --front y --back, o --png-dir, o --card")
    control = args.control
    if args.card:
        folder, control = latest_archive(png_root, args.card), control or args.card
    elif args.png_dir:
        folder = args.png_dir
        if not folder.is_dir():
            raise CliError(f"No existe la carpeta {folder}")
    else:
        if not (args.front and args.back):
            raise CliError("--front y --back van juntos")
        files = {"front": args.front, "back": args.back, "front_k": args.front_k, "back_k": args.back_k}
        return {k: _read(p, limit) for k, p in files.items() if p}, control
    raw = {k: _read(folder / f"{k}.png", limit) for k in FACES if (folder / f"{k}.png").is_file()}
    if not {"front", "back"} <= set(raw):
        raise CliError(f"En {folder} deben estar front.png y back.png")
    return raw, control


def parse_option_args(items: list[str]) -> dict[str, str] | None:
    if not items:
        return None
    options = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise CliError(f"--option espera CLAVE=VALOR, no «{item}»")
        options[key.strip()] = value.strip()
    return options


def pick_printer(printers: list[dict], wanted: str | None, preferred: str = "") -> str:
    ids = [p["id"] for p in printers]
    if wanted:
        if wanted not in ids:
            raise CliError(f"La impresora «{wanted}» no existe. Disponibles: {', '.join(ids) or '(ninguna)'}")
        return wanted
    if preferred in ids:
        return preferred
    if len(ids) == 1:
        return ids[0]
    raise CliError("Hay varias impresoras: indica --printer. Disponibles: " + (", ".join(ids) or "(ninguna)"))


# ---------- servidor ya abierto ----------
def _http(method: str, url: str, key: str, body: bytes | None = None, content_type: str | None = None, timeout: float = 30):
    request = urllib.request.Request(url, data=body, method=method, headers={"X-API-Key": key})
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise CliError(f"El programa respondió {exc.code}: {detail}", EXIT_INVALID if exc.code < 500 else EXIT_FAILED) from exc


def encode_multipart(fields: dict[str, str], files: dict[str, bytes]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, data in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}.png"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def server_running(settings: Settings) -> bool:
    """¿Está CarnetPrint abierto en este puerto? (se comprueba que sea él, no cualquier servicio)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{settings.port}/health", timeout=HEALTH_TIMEOUT_S) as response:
            data = json.loads(response.read())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("status") == "ok" and "version" in data


class Remote:
    def __init__(self, settings: Settings):
        self.base, self.key = f"http://127.0.0.1:{settings.port}", settings.api_key

    def printers(self) -> list[dict]:
        return _http("GET", self.base + "/printers", self.key)

    def settings(self) -> dict:
        return _http("GET", self.base + "/settings", self.key)

    def submit(self, printer_id, faces, copies, options, template, control) -> dict:
        fields = {"printer_id": printer_id, "copies": str(copies)}
        if options is not None:
            fields["options"] = json.dumps(options)
        if template:
            fields["template_id"] = template
        if control:
            fields["control"] = control
        body, ctype = encode_multipart(fields, faces)
        return _http("POST", self.base + "/jobs", self.key, body, ctype)

    def job(self, job_id: str) -> dict:
        return _http("GET", f"{self.base}/jobs/{job_id}", self.key)

    def reprint(self, control: str) -> None:
        _http("POST", f"{self.base}/cards/{control}/reprint", self.key, b"{}", "application/json")


# ---------- imprimir ----------
def wait_for(fetch, timeout: int, say) -> dict:
    """Espera a que el trabajo salga de la cola; avisa cada 5 s (la DS3 tarda 30-60 s por tarjeta)."""
    start, last = time.monotonic(), -5
    while True:
        job = fetch()
        if job["state"] != "queued":
            return job
        elapsed = int(time.monotonic() - start)
        if elapsed >= timeout:
            raise CliError(f"El trabajo sigue en cola tras {timeout} s: revisa la impresora", EXIT_FAILED)
        if elapsed - last >= 5:
            say(f"Imprimiendo… {elapsed} s (es normal que tarde 30-60 s por tarjeta)")
            last = elapsed
        time.sleep(POLL_S)


def run_print(args, settings: Settings, say) -> dict:
    options = parse_option_args(args.option)
    if not 1 <= args.copies <= MAX_COPIES:
        raise CliError(f"--copies debe estar entre 1 y {MAX_COPIES}")
    png_root = settings.png_dir or settings.data_dir / "png"
    faces, control = collect_faces(args, png_root, settings.max_upload_bytes)
    remote = Remote(settings) if server_running(settings) else None
    ctx = None if remote else build_ctx(settings)
    try:
        if remote:
            say("Usando el programa que ya está abierto (su cola de impresión).")
            printers = remote.printers()
            preferred = remote.settings().get("printer", "")
        else:
            printers = [{"id": pid, "label": cfg.label} for pid, (cfg, _) in ctx.registry.items()]
            preferred = ctx.store.get_settings().get("printer", "")
        printer_id = pick_printer(printers, args.printer, preferred)
        label = next(p["label"] for p in printers if p["id"] == printer_id)
        say(f"Enviando a {label}…")
        if remote:
            job = remote.submit(printer_id, faces, args.copies, options, args.template, control)
            png_dir, final = job.get("png_dir"), wait_for(lambda: remote.job(job["id"]), args.timeout, say)
        else:
            try:
                queued, png_dir = submit_print(ctx, Principal(), printer_id=printer_id, raw_faces=faces,
                                               copies=args.copies, options=options, template_id=args.template, control=control)
            except PrintRejected as exc:
                raise CliError(exc.detail, EXIT_INVALID if exc.status < 500 else EXIT_FAILED) from exc
            final = wait_for(lambda: ctx.jobs.get(queued.id).__dict__, args.timeout, say)
        ok = final["state"] in ("printed", "submitted")
        if ok and args.card:   # una reimpresión cuenta solo si salió bien
            remote.reprint(args.card) if remote else ctx.store.reprint_card(args.card)
        return {
            "ok": ok, "state": final["state"], "printer": printer_id, "printerLabel": label, "copies": args.copies,
            "control": control, "job": final.get("backend_job_id") or final["id"], "pngDir": png_dir,
            "error": final.get("error"), "via": "programa abierto" if remote else "directo",
        }
    finally:
        if ctx:
            ctx.jobs.shutdown()


def print_text(result: dict) -> None:
    if result["ok"]:
        where = f" (PNG en png/{result['pngDir']})" if result["pngDir"] else ""
        what = "Impreso en" if result["state"] == "printed" else "Enviado a"
        card = f" Carnet {result['control']}." if result["control"] else ""
        print(f"✔ {what} {result['printerLabel']}.{card}{where}")
        if result["state"] != "printed":
            print("  (La impresora no confirma que la tarjeta salió: revisa la bandeja de salida.)")
    else:
        print(f"✘ La impresión falló: {result['error'] or 'error desconocido'}", file=sys.stderr)


def run_printers(args, settings: Settings) -> list[dict]:
    if server_running(settings):
        return Remote(settings).printers()
    ctx = build_ctx(settings)
    try:
        return [{"id": cfg.id, "label": cfg.label, "status": ctx.status.get(cfg.id)} for cfg, _ in ctx.registry.values()]
    finally:
        ctx.jobs.shutdown()


def main(argv: list[str], settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    if settings is None:
        new_key = ensure_config(app_dir())
        if new_key:
            print(f"Primera ejecución: se creó {app_dir() / '.env'}", file=sys.stderr)
        settings = Settings()
    quiet = getattr(args, "quiet", False) or getattr(args, "json", False)
    say = (lambda _msg: None) if quiet else (lambda msg: print(msg, file=sys.stderr))
    try:
        if args.command == "printers":
            printers = run_printers(args, settings)
            if args.json:
                print(json.dumps(printers, ensure_ascii=False))
            else:
                for p in printers:
                    print(f"{p['id']:<24} {p['label']:<28} {p['status']}")
            return EXIT_OK
        result = run_print(args, settings, say)
    except CliError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"✘ {exc}", file=sys.stderr)
        return exc.code
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print_text(result)
    return EXIT_OK if result["ok"] else EXIT_FAILED
