"""Build the standalone app and the Windows installer.

    python tools/build_installer.py                 # exe + Setup.exe
    python tools/build_installer.py --skip-exe      # reuse an existing build
    python tools/build_installer.py --no-installer  # exe only

Produces, in dist/:
    MDEC-Docket-Manager-<ver>-Setup.exe   installer, no Python needed
    MDEC-Docket-Manager-<ver>-portable.zip the same app as a folder to unzip

Needs PyInstaller (pip) and Inno Setup 6 (winget install JRSoftware.InnoSetup).

Build from a virtual environment, not from the interpreter on PATH — the build
refuses to run otherwise, and prints the three commands that fix it. See
require_clean_build_env() for why.
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


# Distributions that must never be importable while we freeze, and why. These
# are licences that cannot ship inside a redistributed binary, not packages that
# are merely unused.
FORBIDDEN_WHEN_FREEZING = {
    "pymupdf": "AGPL-3.0",
    "pymupdfb": "AGPL-3.0",
    "fitz": "AGPL-3.0 (PyMuPDF)",
}


def require_clean_build_env() -> None:
    """Refuse to freeze from a shared or contaminated interpreter.

    PyInstaller bundles what it can reach. This project had no environment of
    its own, so it froze from whatever `python` resolved to — and on the
    author's machine that interpreter carries a hand-installed AGPL PyMuPDF in
    user site-packages.

    Nothing here imports it today. That is not a licence control: one
    hiddenimport, or a `--collect-all` added to the spec for an unrelated
    reason, would sweep it into a shipped binary, and no manifest in this repo
    would show it. The same class of accident already happened once in a
    sibling project, where an Apache-2.0 wheel quietly carried an LGPL FFmpeg
    binary into four public releases.

    A venv built from requirements.txt makes it impossible instead of unlikely.
    """
    problems: list[str] = []

    if sys.prefix == sys.base_prefix:
        problems.append(
            "this is not a virtual environment, so the build would freeze from "
            f"whatever is installed in {sys.prefix}")

    from importlib import metadata
    for dist in metadata.distributions():
        name = ((dist.metadata["Name"] or "") if dist.metadata else "").strip().lower()
        if name in FORBIDDEN_WHEN_FREEZING:
            problems.append(
                f"{name} {dist.version} is importable here and is "
                f"{FORBIDDEN_WHEN_FREEZING[name]}, which cannot ship in a "
                f"redistributed binary")

    if not problems:
        return

    # Creating the venv with THIS interpreter is safe even when this one is the
    # contaminated interpreter: a venv does not inherit user site-packages, so
    # the AGPL package visible here will not be visible inside it.
    venv_py = r".venv\Scripts\python" if os.name == "nt" else ".venv/bin/python"
    raise SystemExit(
        "Refusing to build.\n\n  - "
        + "\n  - ".join(problems)
        + "\n\nThis app ships as a frozen binary, so anything importable here "
          "can end up\ninside it. Build from a clean environment:\n\n"
          f"    \"{sys.executable}\" -m venv .venv\n"
          f"    {venv_py} -m pip install -r requirements.txt\n"
          f"    {venv_py} -m pip install pyinstaller\n"
          f"    {venv_py} tools/build_installer.py\n"
    )


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
        require_clean_build_env()
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
