import json
import subprocess
import tempfile
from pathlib import Path

from .base import PrintError, PrintRequest, PrinterAdapter
from .errors import operator_message

BRIDGE_DIR = Path(__file__).resolve().parents[2] / "bridge"
RENDER_DPI = 300
# Espera al operador ante un error leve (sin tarjetas, tapa abierta, cinta) antes de
# cancelar la tarjeta; el tiempo total del trabajo la incluye.
RECOVER_WAIT_S = 120
PRINT_TIMEOUT_S = 300 + RECOVER_WAIT_S
STATUS_TIMEOUT_S = 30


def render_pages(pdf_path: Path, out_dir: Path) -> list[Path]:
    """PDF -> un PNG por página a 300 ppp (pág. 1 = frente, pág. 2 = reverso)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        if len(pdf) not in (1, 2):
            raise PrintError(f"El PDF debe tener 1 o 2 páginas (tiene {len(pdf)})")
        paths = []
        for i, page in enumerate(pdf):
            image = page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
            path = out_dir / f"page{i + 1}.png"
            image.save(path, dpi=(RENDER_DPI, RENDER_DPI))
            paths.append(path)
        return paths
    finally:
        pdf.close()


class BridgeAdapter(PrinterAdapter):
    """Impresora manejada por un puente .exe del SDK del fabricante (CLI con salida JSON).

    Convención del puente: `status` y `print --front F [--back B] ...`; una línea JSON en
    stdout con `ok`, y en `print` `printerJobId`. El trabajo vuelve cuando la tarjeta salió.
    """

    confirms_completion = True
    accepts_faces = True
    vendor = "SDK"
    default_bridge: Path
    # Opciones por trabajo -> argumento del puente. Banderas: "true"/"false".
    flag_options: dict[str, str] = {}
    value_options: dict[str, str] = {}
    # Código de error del SDK -> instrucción para el operador (ver errors.py)
    error_messages: dict[int, str] = {}

    def __init__(self, printer_name: str, bridge_path: str | None = None):
        self._printer_name = printer_name
        self._bridge = Path(bridge_path) if bridge_path else self.default_bridge

    def _call(self, args: list[str], timeout: int) -> dict:
        if not self._bridge.exists():
            raise PrintError(f"No se encontró {self.default_bridge.name} en {self._bridge}")
        try:
            out = subprocess.run(
                [str(self._bridge), *args, "--printer", self._printer_name, "--timeout", str(timeout),
                 *(["--recover-wait", str(RECOVER_WAIT_S)] if args[:1] == ["print"] else [])],
                capture_output=True, text=True, encoding="utf-8", timeout=timeout + 15,
            )
        except subprocess.TimeoutExpired as exc:
            raise PrintError(f"{self._bridge.stem} no respondió") from exc
        line = out.stdout.strip().splitlines()[-1:] or [""]
        try:
            return json.loads(line[0])
        except json.JSONDecodeError as exc:
            detail = (out.stderr or out.stdout).strip()[-300:] or f"código {out.returncode}"
            raise PrintError(f"{self._bridge.stem} falló: {detail}") from exc

    def _option_args(self, options: dict[str, str]) -> list[str]:
        args: list[str] = []
        for key, value in options.items():
            if key in self.flag_options:
                if value.lower() == "true":
                    args.append(self.flag_options[key])
            elif key in self.value_options:
                args += [self.value_options[key], value]
            else:
                raise PrintError(f"Opción no soportada por el {self.vendor}: {key}")
        return args

    def submit(self, request: PrintRequest) -> str:
        args = self._option_args(request.options)
        with tempfile.TemporaryDirectory() as tmp:
            if request.faces:
                # PNG nativos tal cual: sin PDF ni remuestreo; capas K solo si vienen
                for key in ("front", "back", "front_k", "back_k"):
                    if key in request.faces:
                        args += [f"--{key.replace('_', '-')}", str(request.faces[key])]
            else:
                pages = render_pages(request.pdf_path, Path(tmp))
                args += ["--front", str(pages[0])]
                if len(pages) == 2:
                    args += ["--back", str(pages[1])]

            job_ids = []
            for _ in range(request.copies):
                result = self._call(["print", *args], PRINT_TIMEOUT_S)
                if not result.get("ok"):
                    raise PrintError(operator_message(self.vendor, self.error_messages, result))
                job_ids.append(str(result.get("printerJobId", "?")))
        return f"{self.job_prefix}:" + ",".join(job_ids)

    job_prefix = "sdk"

    def status(self) -> str:
        try:
            result = self._call(["status"], STATUS_TIMEOUT_S)
        except PrintError:
            return "unknown"
        return "ready" if result.get("ok") and result.get("ready") else "offline"

    def details(self) -> dict:
        """Estado completo (modelo, cinta restante, errores) tal como lo da el SDK."""
        try:
            return self._call(["status"], STATUS_TIMEOUT_S)
        except PrintError as exc:
            return {"ok": False, "error": str(exc)}
