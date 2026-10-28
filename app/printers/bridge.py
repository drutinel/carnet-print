import json
import subprocess
from pathlib import Path

from .base import PrintError, PrintRequest, PrinterAdapter
from .errors import operator_message

BRIDGE_DIR = Path(__file__).resolve().parents[2] / "bridge"
# Espera al operador ante un error leve (sin tarjetas, tapa abierta, cinta) antes de
# cancelar la tarjeta; el tiempo total del trabajo la incluye.
RECOVER_WAIT_S = 120
PRINT_TIMEOUT_S = 300 + RECOVER_WAIT_S
STATUS_TIMEOUT_S = 30


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
        if not request.faces:
            raise PrintError("El puente imprime directo: faltan las imágenes front/back")
        for key in ("front", "back", "front_k", "back_k"):
            if key in request.faces:
                args += [f"--{key.replace('_', '-')}", str(request.faces[key])]

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
