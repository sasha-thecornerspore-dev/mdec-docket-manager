"""Catalog naming: NNNN_YYYYMMDD_Description.pdf

Two jobs:

1. `place_download` — name files the app just downloaded. Deterministic: the
   downloader knows exactly which docket entry each file belongs to, so no
   inference is needed. Multi-file entries get `_1ofN` suffixes.

2. `repair_folder` — rename a LEGACY dump folder (files still named
   "{Title}-{caseid}.pdf", "{Title}-{caseid} (1).pdf", …) against a docket
   index. This is the occurrence-counted algorithm from the original PowerShell
   script: sort by file creation time (= download order = page order), strip
   the " (n)" suffix to get the stem, and map the Nth physical copy of a stem
   to the Nth docket slot expecting that stem. Duplicated titles (146x in the
   reference case) cannot scramble under this scheme.

Every rename appends to `_ORIGINAL_NAMES_manifest.csv` so it is reversible.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

MANIFEST = "_ORIGINAL_NAMES_manifest.csv"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SUFFIX = re.compile(r"\s*\((\d+)\)$")


def sanitize(name: str, max_len: int = 120) -> str:
    s = _ILLEGAL.sub(" ", name).strip(" .")
    s = re.sub(r"\s+", " ", s)
    return s[:max_len].strip(" .") or "Untitled"


def date_stamp(file_date: str) -> str:
    """'8/26/2024' -> '20240826'; unknown dates -> 'XXXXXXXX' (sorts predictably).

    Some portal sections append a time ("29/09/2025, 15:06:37") and use
    day-first order, so trailing time is dropped and an impossible month is
    read as day-first rather than thrown away.
    """
    text = (file_date or "").split(",")[0].strip()
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", text)
    if not m:
        return "XXXXXXXX"
    mm, dd, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if mm > 12 and dd <= 12:
        mm, dd = dd, mm
    try:
        return datetime(yyyy, mm, dd).strftime("%Y%m%d")
    except ValueError:
        return "XXXXXXXX"


def catalog_name(seq: int, file_date: str, description: str,
                 part: int | None = None, total_parts: int = 1) -> str:
    base = f"{seq:04d}_{date_stamp(file_date)}_{sanitize(description)}"
    if total_parts > 1 and part is not None:
        base += f"_{part}of{total_parts}"
    return base + ".pdf"


def _record(folder: Path, original: str, final: str) -> None:
    manifest = folder / MANIFEST
    new_file = not manifest.exists()
    with manifest.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["renamed_at", "original_name", "final_name"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), original, final])


def _dedupe(folder: Path, name: str) -> str:
    """If the target name exists, add ~2, ~3… — never overwrite a court document."""
    p = folder / name
    if not p.exists():
        return name
    stem, ext = p.stem, p.suffix
    n = 2
    while (folder / f"{stem}~{n}{ext}").exists():
        n += 1
    return f"{stem}~{n}{ext}"


def place_download(tmp_path: Path, folder: Path, seq: int, file_date: str,
                   description: str, part: int | None = None,
                   total_parts: int = 1, original_name: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    name = _dedupe(folder, catalog_name(seq, file_date, description, part, total_parts))
    final = folder / name
    tmp_path.replace(final)
    _record(folder, original_name or tmp_path.name, name)
    return final


# --- legacy repair mode ----------------------------------------------------

def stem_of(filename: str, case_id: str) -> str:
    """'Order to Docket-C01cv24001234 (3).pdf' -> 'Order to Docket'."""
    s = Path(filename).stem
    s = _SUFFIX.sub("", s)
    tail = f"-{case_id}"
    if s.lower().endswith(tail.lower()):
        s = s[: -len(tail)]
    return s.strip()


def repair_folder(folder: Path, case_id: str, docket_index: list[dict],
                  dry_run: bool = True, sort_key=None) -> list[dict]:
    """Occurrence-counted rename of a legacy dump folder.

    docket_index: [{seq, file_date, title}] in docket order — one row per
    EXPECTED file (an entry with 14 files contributes 14 rows).
    sort_key: override for tests; default = file creation time (st_ctime),
    which equals download order. Never sort by name or mtime.

    Returns action rows: {file, target, status}. status 'unmatched' means the
    stem had more physical copies than docket slots (or vice versa) — those are
    left untouched and MUST be reviewed by hand; for legal documents a mislabel
    is worse than no label.
    """
    folder = Path(folder)
    files = [p for p in folder.glob("*.pdf") if not p.name.startswith("_")]
    files.sort(key=sort_key or (lambda p: p.stat().st_ctime))

    # Docket slots per stem, in order.
    slots: dict[str, list[dict]] = {}
    for row in docket_index:
        slots.setdefault(sanitize(row["title"]).lower(), []).append(row)

    seen: dict[str, int] = {}
    actions: list[dict] = []
    for p in files:
        stem = sanitize(stem_of(p.name, case_id)).lower()
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        stem_slots = slots.get(stem, [])
        if n >= len(stem_slots):
            actions.append({"file": p.name, "target": "", "status": "unmatched"})
            continue
        row = stem_slots[n]
        target = catalog_name(row["seq"], row.get("file_date", ""), row["title"])
        actions.append({"file": p.name, "target": target, "status": "rename"})
        if not dry_run:
            target = _dedupe(folder, target)
            p.rename(folder / target)
            _record(folder, p.name, target)

    # Flag docket slots that never got a file (missing downloads).
    for stem, rows in slots.items():
        have = seen.get(stem, 0)
        for row in rows[have:]:
            actions.append({
                "file": "", "status": "missing",
                "target": catalog_name(row["seq"], row.get("file_date", ""), row["title"]),
            })
    return actions
