# PyInstaller spec for MDEC Docket Manager.
#
#   python -m PyInstaller tools/mdec.spec --noconfirm
#
# onedir, not onefile: onefile unpacks the whole bundle to a temp directory on
# every launch, which would undo the 3-second start-up this app was tuned for.
# The installer hides the directory anyway.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "mdec" / "server" / "static"), "mdec/server/static"),
    (str(ROOT / "assets" / "mdec.ico"), "assets"),
    (str(ROOT / "assets" / "mdec-256.png"), "assets"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "docs"), "docs"),
]
binaries = []
hiddenimports = []

# These resolve modules at run time, so static analysis misses them.
#   uvicorn   — loads its loop/protocol/lifespan implementations by string
#   keyring   — backends are entry points; the Windows one is what we need
#   playwright— ships a node driver + package as package data
for pkg in ("uvicorn", "keyring", "playwright", "anthropic"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("mdec")
hiddenimports += [
    "encodings.idna",
    "email.mime.text",           # imap-tools
    "imap_tools",
    "pdfplumber",
    "PIL.Image",
    "tkinter", "tkinter.filedialog",   # the folder picker
]

# keyring picks its backend through entry points, so the one for THIS platform
# has to be named explicitly. Naming the Windows backend unconditionally, as
# this spec used to, means a macOS or Linux build asks PyInstaller for modules
# that cannot exist there — a warning, not an error, so it fails later and
# quietly, at the point the app first tries to read a credential.
if sys.platform == "win32":
    hiddenimports += ["keyring.backends.Windows", "win32ctypes.core"]
elif sys.platform == "darwin":
    hiddenimports += ["keyring.backends.macOS"]
else:
    hiddenimports += ["keyring.backends.SecretService", "keyring.backends.chainer"]

a = Analysis(
    [str(ROOT / "tools" / "frozen_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Weight we never use. ocrmypdf stays out on purpose: it drags in pikepdf and
    # a Ghostscript/Tesseract expectation, and OCR is opt-in — the app degrades
    # to "OCR unavailable" with a clear message instead.
    # Weight we never use. torch/tensorflow get dragged in through optional
    # imports in unrelated packages and add hundreds of MB for nothing, which
    # also slows launch (Windows scans every file).
    excludes=["ocrmypdf", "pikepdf", "matplotlib", "numpy.testing",
              "pytest", "PyInstaller", "IPython", "notebook",
              "torch", "tensorflow", "tensorboard", "scipy", "pandas",
              "sklearn", "transformers"],
    noarchive=False,
    optimize=0,
)

def _icon():
    name = "mdec.icns" if sys.platform == "darwin" else "mdec.ico"
    path = ROOT / "assets" / name
    return str(path) if path.is_file() else None


pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MDECDocketManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # .ico is a Windows format. macOS wants .icns and rejects the rest, so use
    # one if it has been generated and go iconless rather than failing the
    # build over decoration.
    icon=_icon(),
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MDECDocketManager",
)
