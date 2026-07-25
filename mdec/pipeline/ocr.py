"""Text extraction and OCR.

Strategy per document:
1. Try the existing text layer (pdfplumber) — most e-filed PDFs have one.
2. If the text layer is thin and OCR is enabled, run ocrmypdf --skip-text to
   add a text layer in place (plus a .txt sidecar) and re-extract.

ocrmypdf needs Tesseract and Ghostscript on PATH; `available()` reports what's
missing so the UI can explain instead of failing cryptically. All functions are
blocking — callers use a thread executor.
"""

from __future__ import annotations

import shutil
from pathlib import Path

MIN_TEXT_CHARS = 200   # below this we assume a scan with no useful text layer


def available() -> tuple[bool, str]:
    try:
        import ocrmypdf  # noqa: F401
    except ImportError:
        return False, "Python package 'ocrmypdf' is not installed (pip install ocrmypdf)."
    missing = [t for t in ("tesseract", "gs") if shutil.which(t) is None]
    if missing:
        return False, ("Missing system tools: " + ", ".join(missing) +
                       ". See docs/INSTALL.md → OCR prerequisites.")
    return True, ""


def extract_text(pdf_path: Path) -> str:
    import pdfplumber
    out: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n\n".join(out).strip()


def ocr_in_place(pdf_path: Path, language: str = "eng") -> Path:
    """Add a text layer to pdf_path (atomically) and write a .txt sidecar."""
    import ocrmypdf
    sidecar = pdf_path.with_suffix(".txt")
    tmp = pdf_path.with_suffix(".ocr.tmp.pdf")
    ocrmypdf.ocr(str(pdf_path), str(tmp), skip_text=True,
                 sidecar=str(sidecar), language=language, progress_bar=False)
    tmp.replace(pdf_path)
    return sidecar


def get_text(pdf_path: Path, ocr_enabled: bool, language: str = "eng") -> tuple[str, bool]:
    """Return (text, ocr_was_run). Never raises for a thin/empty result."""
    pdf_path = Path(pdf_path)
    sidecar = pdf_path.with_suffix(".txt")
    if sidecar.exists():
        return sidecar.read_text(encoding="utf-8", errors="replace").strip(), False
    try:
        text = extract_text(pdf_path)
    except Exception:
        text = ""
    if len(text) >= MIN_TEXT_CHARS or not ocr_enabled:
        return text, False
    ok, _why = available()
    if not ok:
        return text, False
    try:
        ocr_in_place(pdf_path, language)
        return extract_text(pdf_path), True
    except Exception:
        return text, False
