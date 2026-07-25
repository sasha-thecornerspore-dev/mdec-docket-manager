"""Build the distributable zip.

    python tools/make_release.py            # -> dist/MDEC-Docket-Manager-<ver>.zip
    python tools/make_release.py --version 1.2.0

What the user gets: unzip anywhere, double-click Install.cmd, done. The zip
carries the app, the generated icon, and the installer — but no runtime data, no
virtualenv, and nothing case-specific.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Everything the installed app needs, and nothing else.
INCLUDE_FILES = [
    "Install.cmd",
    "Uninstall.cmd",
    "MDEC Docket Manager.pyw",
    "run.py",
    "requirements.txt",
    "requirements-optional.txt",
    "README.md",
    "LICENSE",
    "assets/mdec.ico",
    "assets/mdec-256.png",
    "tools/make_icon.py",
    "tools/make_shortcuts.ps1",
]
INCLUDE_TREES = ["mdec", "docs", "tests"]

EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "dist",
                 "build", ".pw-profile", ".appwindow", ".incoming"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".pdf", ".db", ".sqlite3", ".log"}


def app_version() -> str:
    text = (ROOT / "mdec" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def wanted(path: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if path.name in ("config.json", "runtime.json",
                     "_ORIGINAL_NAMES_manifest.csv"):
        return False
    return True


def collect() -> list[Path]:
    files: list[Path] = []
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if p.is_file():
            files.append(p)
        else:
            print(f"  ! missing, skipped: {rel}", file=sys.stderr)
    for tree in INCLUDE_TREES:
        for p in sorted((ROOT / tree).rglob("*")):
            if p.is_file() and wanted(p):
                files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None)
    args = ap.parse_args()
    version = args.version or app_version()

    icon = ROOT / "assets" / "mdec.ico"
    if not icon.is_file():
        print("Icon missing — generating it first.")
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")],
                       check=True)

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    name = f"MDEC-Docket-Manager-{version}"
    out = dist / f"{name}.zip"

    files = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            z.write(f, arcname=f"{name}/{f.relative_to(ROOT).as_posix()}")

    size_mb = out.stat().st_size / 1_048_576
    print(f"\n{out}")
    print(f"{len(files)} files, {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
