"""Punto de entrada del .exe: crea la config la primera vez, levanta el API y abre la UI."""
import argparse
import sys
import threading
import webbrowser

import uvicorn

from .bootstrap import ensure_config
from .config import Settings, load_printers
from .main import create_app
from .paths import app_dir
from .preflight import failed, run_checks
from .version import VERSION


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("print", "printers"):   # línea de comandos: imprime sin abrir la web
        from . import cli
        return cli.main(argv)
    parser = argparse.ArgumentParser(
        description="CarnetPrint. Sin argumentos abre el programa. Por línea de comandos: "
                    "«print» (imprime PNG) y «printers»; ver «CarnetPrint.exe print --help».")
    parser.add_argument("--client", help="abre el generador preconfigurado de ese cliente (modo kiosko)")
    parser.add_argument("--version", action="version", version=f"CarnetPrint {VERSION}")
    args = parser.parse_args(argv)
    new_key = ensure_config(app_dir())
    settings = Settings()
    if new_key:
        print(f"Primera ejecución. API key (también en {app_dir() / '.env'}): {new_key}")
    base = f"http://localhost:{settings.port}"
    url = f"{base}/c/{args.client}" if args.client else f"{base}/ui/generador-carnets.html"
    print(f"CarnetPrint {VERSION} en {url}\nDatos en {settings.data_dir} (templates.json, carnets.json)")
    app = create_app(settings)
    for problem in failed(run_checks(load_printers(settings.printers_file))):
        print(f"\n[FALTA] {problem['title']}\n  {problem['detail']}\n  {problem['url']}", file=sys.stderr)
    if settings.open_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    except OSError as exc:
        print(f"No se pudo abrir el puerto {settings.port}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
