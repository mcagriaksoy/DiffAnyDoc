# PyInstaller spec: one folder with DiffAnyDoc (windowed) + diffanydoc-cli.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
WIN = sys.platform == "win32"
STATIC = ROOT / "src" / "diffanydoc" / "web" / "static"

datas, binaries, hiddenimports = [], [], []
for package in ("rapidocr_onnxruntime", "onnxruntime", "pypdfium2", "pypdfium2_raw", "pdfminer"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
# diffanydoc ships locales/*.json and web/static/*
d, b, h = collect_all("diffanydoc")
datas += d
binaries += b
hiddenimports += h
hiddenimports += collect_submodules("uvicorn") + collect_submodules("webview")

analysis = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(analysis.pure)

# Icon and version resource apply to Windows only.
win_only = (
    {"icon": str(STATIC / "icon.ico"), "version": str(ROOT / "build" / "version_info.txt")}
    if WIN
    else {}
)
gui = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="DiffAnyDoc", console=False, **win_only,
)
cli = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="diffanydoc-cli", console=True, **win_only,
)
COLLECT(gui, cli, analysis.binaries, analysis.datas, name="DiffAnyDoc")

# Single-file standalone portable executable for 64-bit Windows
if WIN:
    portable = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.zipfiles,
        analysis.datas,
        [],
        name="DiffAnyDoc-portable",
        console=False,
        upx=False,
        **win_only,
    )
