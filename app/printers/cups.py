import re
import subprocess

from .base import PrintError, PrintRequest, PrinterAdapter

CUPS_TIMEOUT_S = 30
_JOB_RE = re.compile(r"request id is (\S+)")


class CupsAdapter(PrinterAdapter):
    def __init__(self, queue: str):
        self._queue = queue

    def submit(self, request: PrintRequest) -> str:
        cmd = ["lp", "-d", self._queue, "-n", str(request.copies)]
        for key, value in request.options.items():
            cmd += ["-o", f"{key}={value}"]
        cmd.append(str(request.pdf_path))
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=CUPS_TIMEOUT_S, check=True
            )
        except FileNotFoundError as exc:
            raise PrintError("CUPS no está instalado (falta el comando 'lp')") from exc
        except subprocess.TimeoutExpired as exc:
            raise PrintError("Timeout enviando a CUPS") from exc
        except subprocess.CalledProcessError as exc:
            raise PrintError(f"CUPS rechazó el trabajo: {exc.stderr.strip()}") from exc
        match = _JOB_RE.search(out.stdout)
        return match.group(1) if match else "unknown"

    def status(self) -> str:
        try:
            out = subprocess.run(
                ["lpstat", "-p", self._queue],
                capture_output=True,
                text=True,
                timeout=CUPS_TIMEOUT_S,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "unknown"
        if out.returncode != 0:
            return "offline"
        return "ready" if "idle" in out.stdout or "printing" in out.stdout else "offline"
