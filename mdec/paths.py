"""Where files live, whether running from source or from a PyInstaller bundle.

Frozen, `__file__` points inside the bundle and the repo layout is gone, so any
code reaching for `static/` or `assets/` has to ask here instead of walking up
from its own path.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_root() -> Path:
    """Root that bundled data files were unpacked to (or the repo root)."""
    if is_frozen():
        # onedir: files sit next to the exe; onefile: in the _MEIPASS temp dir.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    p = bundle_root() / "mdec" / "server" / "static"
    if p.is_dir():
        return p
    return Path(__file__).resolve().parent / "server" / "static"


def assets_dir() -> Path:
    return bundle_root() / "assets"
