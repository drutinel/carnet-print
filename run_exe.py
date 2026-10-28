"""Entrada para PyInstaller (el paquete `app` usa imports relativos)."""
from app.server import main

if __name__ == "__main__":
    raise SystemExit(main())
