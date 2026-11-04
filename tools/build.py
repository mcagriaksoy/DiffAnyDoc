"""Build a release bundle with PyInstaller.

    pip install -e ".[web,desktop]" pyinstaller
    python tools/build.py            # -> dist/DiffAnyDoc-<version>-<os>-<arch>...

The bundle is a folder ("onedir"), not a single self-extracting file: it
starts faster, antivirus tools flag it less often and code signing covers
every binary. Windows gets a portable .zip and an Inno Setup installer (needs
``ISCC``); Linux gets a .tar.gz with an ``install.sh`` and an AppImage (needs
``appimagetool``). The sdist and wheel come from ``python -m build``.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from diffanydoc import __version__  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP = DIST / "DiffAnyDoc"
WINDOWS = sys.platform == "win32"
STATIC = ROOT / "src" / "diffanydoc" / "web" / "static"
SUFFIX = {
    "zip": "-portable.zip",
    "installer": "-installer.exe",
    "tar": ".tar.gz",
    "appimage": ".AppImage",
}
TARGETS = {"windows": ("zip", "installer"), "linux": ("tar", "appimage")}
# kind -> (program, install hint); only kinds that need an external tool.
TOOLS = {
    "installer": ("ISCC", "install Inno Setup 6 (https://jrsoftware.org/isdl.php)"),
    "appimage": (
        "appimagetool",
        "get it from https://github.com/AppImage/appimagetool/releases",
    ),
}
INNO_DIRS = [
    os.path.join(os.environ[var], "Inno Setup 6")
    for var in ("ProgramFiles(x86)", "ProgramFiles")
    if var in os.environ
]


def _arch() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def _platform() -> str:
    if WINDOWS:
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def artifact_name(version: str, plat: str, arch: str, kind: str) -> str:
    return f"DiffAnyDoc-{version}-{plat}-{arch}{SUFFIX[kind]}"


def artifact(kind: str) -> Path:
    return DIST / artifact_name(__version__, _platform(), _arch(), kind)


def targets(plat: str) -> tuple[str, ...]:
    if plat not in TARGETS:
        raise SystemExit(f"unsupported platform: {plat}")
    return TARGETS[plat]


def find_tool(kind: str) -> str:
    name, hint = TOOLS[kind]
    path = os.pathsep.join([os.environ.get("PATH", ""), *INNO_DIRS])
    tool = shutil.which(name, path=path)
    if tool is None:
        raise SystemExit(f"{name} not found on PATH: {hint}")
    return tool


def write_version_info() -> Path:
    """Windows version resource (shown in Explorer -> Properties -> Details)."""
    numbers = [int(part) for part in __version__.split(".")[:3] if part.isdigit()]
    numbers += [0] * (4 - len(numbers))
    tuple_text = ", ".join(str(n) for n in numbers)
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tuple_text}), prodvers=({tuple_text})),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'DiffAnyDoc'),
      StringStruct('FileDescription', 'DiffAnyDoc document comparison'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductName', 'DiffAnyDoc'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('OriginalFilename', 'DiffAnyDoc.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return path


def run_pyinstaller() -> None:
    write_version_info()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "pyinstaller"),
            str(ROOT / "packaging" / "diffanydoc.spec"),
        ],
        check=True,
        cwd=ROOT,
    )


def smoke_test() -> None:
    """The bundle must at least start, list formats and diff two files."""
    cli = APP / ("diffanydoc-cli.exe" if WINDOWS else "diffanydoc-cli")
    subprocess.run([str(cli), "--version"], check=True)
    subprocess.run([str(cli), "formats"], check=True)
    sample = ROOT / "samples"
    result = subprocess.run(
        [str(cli), "diff", str(sample / "sozlesme-v1.pdf"), str(sample / "sozlesme-v2.pdf")],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    if "sozlesme" not in result.stdout:
        raise SystemExit("smoke test: unexpected diff output\n" + result.stdout)
    print("smoke test passed")


def archive_zip() -> Path:
    target = artifact("zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in APP.rglob("*"):
            bundle.write(path, Path("DiffAnyDoc") / path.relative_to(APP))
    return target


def archive_tar() -> Path:
    linux = ROOT / "packaging" / "linux"
    shutil.copy2(linux / "diffanydoc.desktop", APP / "diffanydoc.desktop")
    shutil.copy2(linux / "install.sh", APP / "install.sh")
    os.chmod(APP / "install.sh", 0o755)
    shutil.copy2(STATIC / "icon.png", APP / "diffanydoc.png")
    target = artifact("tar")
    with tarfile.open(target, "w:gz") as bundle:
        bundle.add(APP, arcname="DiffAnyDoc")
    return target


def installer() -> Path:
    target = artifact("installer")
    defines = {
        "AppVersion": __version__,
        "SourceDir": APP,
        "OutputDir": target.parent,
        "OutputName": target.stem,
        "IconFile": STATIC / "icon.ico",
    }
    command = [find_tool("installer")]
    command += [f"/D{key}={value}" for key, value in defines.items()]
    command.append(str(ROOT / "packaging" / "windows" / "installer.iss"))
    subprocess.run(command, check=True)
    return target


def appimage() -> Path:
    tool = find_tool("appimage")
    appdir = BUILD / "DiffAnyDoc.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(APP, appdir / "usr" / "lib" / "DiffAnyDoc")
    shutil.copy2(ROOT / "packaging" / "linux" / "diffanydoc.desktop", appdir / "diffanydoc.desktop")
    shutil.copy2(STATIC / "icon.png", appdir / "diffanydoc.png")
    apprun = appdir / "AppRun"
    apprun.write_text(
        "#!/bin/sh\n"
        'HERE="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$HERE/usr/lib/DiffAnyDoc/DiffAnyDoc" "$@"\n',
        encoding="utf-8",
    )
    os.chmod(apprun, 0o755)
    target = artifact("appimage")
    env = dict(os.environ, ARCH=_arch())
    subprocess.run([tool, str(appdir), str(target)], check=True, env=env)
    return target


BUILDERS = {
    "zip": archive_zip,
    "installer": installer,
    "tar": archive_tar,
    "appimage": appimage,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-build", action="store_true", help="only test and archive dist/")
    parser.add_argument("--no-smoke-test", action="store_true")
    args = parser.parse_args()
    kinds = targets(_platform())
    for kind in kinds:  # fail before the long build
        if kind in TOOLS:
            find_tool(kind)
    if not args.skip_build:
        run_pyinstaller()
    if not args.no_smoke_test:
        smoke_test()
    outputs = [BUILDERS[kind]() for kind in kinds]
    for output in outputs:
        print(f"built {output.relative_to(ROOT)} ({output.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
