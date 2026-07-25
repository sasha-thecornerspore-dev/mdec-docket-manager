"""Adopt documents that are already on disk.

Two situations this handles:

1. **Resuming.** A previous run was interrupted, or the database was rebuilt,
   but the PDFs are still in the folder. Re-downloading hundreds of documents
   the portal already gave us is slow and rude, so before downloading anything
   the app looks for a file that already satisfies the entry.

2. **Importing an existing archive.** You already have a folder named by this
   app's convention (from an earlier install, a backup, or the legacy rename
   script) and want the app to take ownership of it without a fresh harvest.

Matching is by the sequence number in the filename, which is the docket
sequence — the same key the app assigns when it names a file. Legacy names
(`Title-CASEID.pdf`) carry no sequence, so they are *not* adopted here; run the
repair rename first (Settings → Repair a legacy folder) to give them sequences.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# 0004_20260720_Motion for Summary Judgment_2of14.pdf
CATALOG_RE = re.compile(
    r"^(?P<seq>\d{4,})_(?P<date>\d{8}|X{8})_(?P<desc>.+?)"
    r"(?:_(?P<part>\d+)of(?P<total>\d+))?"
    r"(?:~(?P<dupe>\d+))?\.pdf$",
    re.IGNORECASE,
)


def parse_catalog_name(filename: str) -> dict | None:
    """Pull the docket sequence back out of a catalog filename."""
    m = CATALOG_RE.match(Path(filename).name)
    if not m:
        return None
    return {
        "seq": int(m.group("seq")),
        "date": m.group("date"),
        "description": m.group("desc"),
        "part": int(m.group("part")) if m.group("part") else None,
        "total_parts": int(m.group("total")) if m.group("total") else 1,
    }


def scan_folder(folder: Path | str) -> dict[int, list[dict]]:
    """Map docket sequence -> catalog-named files present in `folder`.

    Files that don't match the convention are ignored, so a stray PDF can never
    be adopted as a court document.
    """
    folder = Path(folder)
    found: dict[int, list[dict]] = {}
    if not folder.is_dir():
        return found
    for p in sorted(folder.glob("*.pdf")):
        if p.name.startswith("_"):
            continue
        parsed = parse_catalog_name(p.name)
        if not parsed:
            continue
        parsed["path"] = p
        found.setdefault(parsed["seq"], []).append(parsed)
    for files in found.values():
        files.sort(key=lambda f: (f["part"] or 0, f["path"].name))
    return found


def file_facts(path: Path) -> tuple[str, int]:
    """(sha256, size) — the same identity the downloader records."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def adopt_entry(db, entry: dict, files: list[dict],
                already: set[str]) -> list[int]:
    """Record `files` as documents of `entry`. Returns new document ids."""
    ids = []
    for f in files:
        path: Path = f["path"]
        if str(path).lower() in already:
            continue
        try:
            sha, size = file_facts(path)
        except OSError:
            continue
        if size == 0:
            continue          # a zero-byte file is a failed download, not a document
        ids.append(db.insert_document(
            entry["id"], f["description"], path.name, str(path), sha, size))
        already.add(str(path).lower())
    return ids


def adopt_folder(db, case_id: int, folder: Path | str,
                 entries: list[dict] | None = None) -> dict:
    """Link every catalog-named file in `folder` to its docket entry.

    Idempotent: files already recorded are skipped, so running it twice adopts
    nothing the second time. Returns a summary for the UI.
    """
    entries = entries if entries is not None else db.list_entries(case_id)
    by_seq = {e["seq"]: e for e in entries}
    on_disk = scan_folder(folder)
    already = db.known_paths(case_id)

    adopted = 0
    entries_touched = 0
    orphans: list[str] = []
    for seq, files in sorted(on_disk.items()):
        entry = by_seq.get(seq)
        if not entry:
            orphans.extend(f["path"].name for f in files)
            continue
        new_ids = adopt_entry(db, entry, files, already)
        if new_ids:
            adopted += len(new_ids)
            entries_touched += 1
            db.set_entry_doc_status(entry["id"], "ok")
    return {
        "adopted": adopted,
        "entries": entries_touched,
        "files_seen": sum(len(v) for v in on_disk.values()),
        "orphans": orphans[:50],
        "orphan_count": len(orphans),
    }
