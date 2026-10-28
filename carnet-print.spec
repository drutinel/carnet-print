# PyInstaller: un solo CarnetPrint.exe con la UI (web/) incluida.
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["run_exe.py"],
    pathex=["."],
    datas=[("web/generador-carnets.html", "web")],
    hiddenimports=collect_submodules("uvicorn") + ["multipart", "python_multipart", "pydantic_settings"],
    excludes=["pypdfium2", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="CarnetPrint",
    console=True,  # el operador ve la API key de la primera vez y los logs
    upx=False,
)
