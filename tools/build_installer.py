"""Build the standalone app and the Windows installer.

    python tools/build_installer.py                 # exe + Setup.exe
    python tools/build_installer.py --skip-exe      # reuse an existing build
    python tools/build_installer.py --no-installer  # exe only

Produces, in dist/:
    MDEC-Docket-Manager-<ver>-Setup.exe   installer, no Python needed
    MDEC-Docket-Manager-<ver>-portable.zip the same app as a folder to unzip

Needs PyInstaller (pip) and Inno Setup 6 (winget install JRSoftware.InnoSetup).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIST = ROOT / "build_dist"
BUILD_WORK = ROOT / "build_work"
DIST = ROOT / "dist"
APP_DIR = BUILD_DIST / "MDECDocketManager"

ISCC_CANDIDATES = (
    r"%LocalAppData%\Programs\Inno Setup 6\ISCC.exe",
    r"%ProgramFiles%\Inno Setup 6\ISCC.exe",
    r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe",
)


def version() -> str:
    for line in (ROOT / "mdec" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def find_iscc() -> str | None:
    for raw in ISCC_CANDIDATES:
        p = Path(os.path.expandvars(raw))
        if p.is_file():
            return str(p)
    return shutil.which("ISCC")


def build_exe() -> None:
    print("== PyInstaller ==")
    icon = ROOT / "assets" / "mdec.ico"
    if not icon.is_file():
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")],
                       check=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "tools" / "mdec.spec"),
         "--noconfirm", "--distpath", str(BUILD_DIST), "--workpath", str(BUILD_WORK)],
        cwd=str(ROOT), check=True)
    exe = APP_DIR / "MDECDocketManager.exe"
    if not exe.is_file():
        raise SystemExit(f"build produced no exe at {exe}")
    total = sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file())
    print(f"   {exe}  (tree: {total / 1_048_576:.0f} MB)")


def build_portable(ver: str) -> Path:
    """The same app as a zip, for people who don't want an installer."""
    DIST.mkdir(exist_ok=True)
    out = DIST / f"MDEC-Docket-Manager-{ver}-portable.zip"
    name = f"MDEC-Docket-Manager-{ver}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(APP_DIR.rglob("*")):
            if f.is_file():
                z.write(f, arcname=f"{name}/{f.relative_to(APP_DIR).as_posix()}")
    print(f"   {out}  ({out.stat().st_size / 1_048_576:.0f} MB)")
    return out


def build_installer(ver: str) -> Path | None:
    iscc = find_iscc()
    if not iscc:
        print("!! Inno Setup not found — skipping the installer.\n"
              "   winget install JRSoftware.InnoSetup")
        return None
    print("== Inno Setup ==")
    subprocess.run([iscc, f"/DAppVersion={ver}",
                    str(ROOT / "tools" / "installer.iss")],
                   cwd=str(ROOT / "tools"), check=True,
                   stdout=subprocess.DEVNULL)
    out = DIST / f"MDEC-Docket-Manager-{ver}-Setup.exe"
    if not out.is_file():
        raise SystemExit(f"Inno Setup produced no file at {out}")
    print(f"   {out}  ({out.stat().st_size / 1_048_576:.0f} MB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-exe", action="store_true")
    ap.add_argument("--no-installer", action="store_true")
    args = ap.parse_args()

    ver = version()
    print(f"MDEC Docket Manager {ver}\n")
    if not args.skip_exe:
        build_exe()
    elif not APP_DIR.is_dir():
        raise SystemExit("--skip-exe given but build_dist/ has no build")

    print("== portable zip ==")
    build_portable(ver)
    if not args.no_installer:
        build_installer(ver)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
