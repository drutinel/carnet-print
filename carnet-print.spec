# PyInstaller: un solo CarnetPrint.exe con la UI (web/) incluida.
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["run_exe.py"],
    pathex=["."],
    datas=[(f"web/{name}", "web") for name in ("generador-carnets.html", "app.css", "app.js", "lib.js")],
    hiddenimports=collect_submodules("uvicorn") + ["multipart", "python_multipart", "pydantic_settings", "app._build_version"],
    excludes=["pypdfium2", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="CarnetPrint",
    console=True,  # el operador ve la API key de la primera vez y los logs
    upx=False,
)
