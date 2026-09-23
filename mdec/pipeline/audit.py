"""Reconciliation: does the archive on disk actually match the docket?

Three sources have to agree before an archive can be trusted:

  the docket    what the court says exists
  the database  what the app believes it downloaded
  the folder    what is really on disk right now

Anything that only downloads is blind to the ways those three drift apart: a
file deleted outside the app, a half-written PDF, a modal that offered fourteen
attachments when only nine landed, the same document fetched twice under two
names. On a case file this is not tidiness — a document you believe you have
and do not is the one you find out about in a hearing.

So this module compares all three and reports, per entry, one of:

  complete    every file the docket offered is on disk, non-empty
  partial     some of a multi-file entry arrived, not all
  missing     the docket offers a document and nothing has been fetched
  broken      recorded as downloaded, but the file is gone or zero bytes
  view_only   the portal shows this entry without any downloadable file
  none        the entry has no document at all (a text-only docket line)

plus the folder-side problems that have no entry to attach to: orphans, files
that never got catalog names, duplicate content, and unreadable dates.

Nothing here touches the docket or the portal, and nothing deletes: the one
mutating helper moves duplicates into a subfolder so the move can be undone.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from .adopt import parse_catalog_name
from .renamer import MANIFEST, date_stamp

COMPLETE = "complete"
PARTIAL = "partial"
MISSING = "missing"
BROKEN = "broken"
VIEW_ONLY = "view_only"
NONE = "none"

#: Problem states, in the order a person should deal with them.
TROUBLE = (BROKEN, MISSING, PARTIAL)

_CHUNK = 1 << 20
_DUPLICATES_DIR = "_duplicates"


def sha256_of(path: Path, chunk: int = _CHUNK) -> str:
    """Streamed, so a 400 MB exhibit does not land in memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def scan(folder: Path | str) -> list[dict]:
    """One pass over the folder: name, size, and parsed catalog fields.

    A single scandir rather than repeated globbing and stat-ing — case folders
    commonly live on a network drive, where each round trip is the expensive
    part. Bookkeeping files (the rename manifest, anything starting with "_")
    and subfolders are skipped: they are not court documents.
    """
    folder = Path(folder)
    out: list[dict] = []
    if not folder.is_dir():
        return out
    with os.scandir(folder) as it:
        for de in it:
            if not de.is_file() or de.name.startswith("_") or de.name == MANIFEST:
                continue
            if not de.name.lower().endswith(".pdf"):
                continue
            try:
                size = de.stat().st_size
            except OSError:
                continue
            parsed = parse_catalog_name(de.name)
            out.append({
                "name": de.name,
                "path": Path(de.path),
                "size": size,
                "catalog": parsed,
                "seq": parsed["seq"] if parsed else None,
                "dupe_suffix": "~" in Path(de.name).stem,
                "undated": bool(parsed) and parsed["date"].upper() == "XXXXXXXX",
            })
    out.sort(key=lambda f: f["name"])
    return out


def duplicate_groups(files: list[dict]) -> list[dict]:
    """Files with byte-identical content, grouped and classified by scope.

    Hashing is confined to files that already share an exact size, so a folder
    of uniquely-sized PDFs costs no reads at all. Zero-byte files are excluded —
    they are all "identical" and are reported separately as failed downloads.

    Identical content is not automatically redundant, and the distinction
    decides whether a copy is safe to remove:

      scope "entry"    every copy belongs to the SAME docket sequence — the
                       entry was fetched twice, so the extra copies are waste
      scope "cross"    the copies belong to DIFFERENT entries — one exhibit
                       genuinely attached to two filings. Each entry keeps its
                       own copy; deleting one would leave a docket entry
                       pointing at a file filed under another entry's number
      scope "unfiled"  at least one copy has no catalog name yet, so which
                       entry owns it is not yet known

    Only "entry" groups are ever offered for removal.
    """
    by_size: dict[int, list[dict]] = defaultdict(list)
    for f in files:
        if f["size"] > 0:
            by_size[f["size"]].append(f)

    groups: list[dict] = []
    for size, same_size in by_size.items():
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[dict]] = defaultdict(list)
        for f in same_size:
            try:
                by_hash[sha256_of(f["path"])].append(f)
            except OSError:
                continue
        for sha, same in by_hash.items():
            if len(same) < 2:
                continue
            seqs = {f["seq"] for f in same}
            if None in seqs:
                scope = "unfiled"
            elif len(seqs) == 1:
                scope = "entry"
            else:
                scope = "cross"
            groups.append({
                "sha256": sha,
                "size": size,
                "count": len(same),
                "scope": scope,
                "seqs": sorted(s for s in seqs if s is not None),
                # Only redundant copies waste space; a cross-entry duplicate is
                # a file each entry is entitled to.
                "wasted_bytes": size * (len(same) - 1) if scope == "entry" else 0,
                "files": sorted(f["name"] for f in same),
            })
    groups.sort(key=lambda g: (-g["wasted_bytes"], -g["size"]))
    return groups


def inventory(folder: Path | str, *, hash_duplicates: bool = True) -> dict:
    """What is in the folder, with no reference to any docket.

    Useful before a case has ever been checked: it still says how many files
    follow the catalog convention, which are legacy names awaiting a repair
    rename, and which are duplicates.
    """
    folder = Path(folder)
    files = scan(folder)
    catalog = [f for f in files if f["catalog"]]
    unfiled = [f for f in files if not f["catalog"]]
    empty = [f for f in files if f["size"] == 0]
    dupes = duplicate_groups(files) if hash_duplicates else []
    redundant = [g for g in dupes if g["scope"] == "entry"]
    return {
        "folder": str(folder),
        "exists": folder.is_dir(),
        "files": len(files),
        "bytes": sum(f["size"] for f in files),
        "catalog_named": len(catalog),
        "unfiled": [f["name"] for f in unfiled[:50]],
        "unfiled_count": len(unfiled),
        "undated": [f["name"] for f in catalog if f["undated"]][:50],
        "undated_count": sum(1 for f in catalog if f["undated"]),
        "collisions": [f["name"] for f in catalog if f["dupe_suffix"]][:50],
        "collision_count": sum(1 for f in catalog if f["dupe_suffix"]),
        "zero_byte": [f["name"] for f in empty],
        "duplicates": dupes,
        "duplicate_groups": len(dupes),
        "redundant_groups": len(redundant),
        "redundant_bytes": sum(g["wasted_bytes"] for g in redundant),
    }


def _entry_state(entry: dict, docs: list[dict], present: dict[str, bool]) -> dict:
    """Classify one docket entry against what the database and disk hold."""
    expected = entry.get("expected_docs")
    on_disk = [d for d in docs if present.get(str(d["path"]).lower())]
    lost = [d for d in docs if not present.get(str(d["path"]).lower())]

    if not entry.get("has_documents"):
        state, detail = NONE, "no document on this docket line"
    elif lost:
        state = BROKEN
        detail = (f"{len(lost)} recorded file(s) are gone from the folder or "
                  f"empty: {', '.join(d['filename'] for d in lost[:3])}")
    elif not docs:
        if (entry.get("doc_status") or "") == "view_only":
            state, detail = VIEW_ONLY, "the portal offers no file for this entry"
        else:
            state, detail = MISSING, "the docket offers a document; none fetched"
    elif expected and len(on_disk) < expected:
        state = PARTIAL
        detail = f"{len(on_disk)} of {expected} attachment(s) downloaded"
    else:
        state = COMPLETE
        detail = f"{len(on_disk)} file(s)"

    return {
        "entry_id": entry["id"],
        "seq": entry["seq"],
        "name": entry.get("name", ""),
        "file_date": entry.get("file_date", ""),
        "section": entry.get("section", ""),
        "has_documents": bool(entry.get("has_documents")),
        "expected_docs": expected,
        "recorded": len(docs),
        "on_disk": len(on_disk),
        "state": state,
        "detail": detail,
        "undated": date_stamp(entry.get("file_date", "")) == "XXXXXXXX",
    }


def _verdict(s: dict) -> str:
    """One plain sentence a person can act on."""
    if not s["entries"]:
        return ("No docket has been read yet, so completeness is unknown. Run a "
                "check while the portal is on your case.")
    if s["expected"] == 0:
        return "This docket has no downloadable documents on it."
    if s[MISSING] == 0 and s[PARTIAL] == 0 and s[BROKEN] == 0:
        return (f"Complete: all {s[COMPLETE]} document-bearing entries are on "
                f"disk, named and dated.")
    bits = []
    if s[MISSING]:
        bits.append(f"{s[MISSING]} entry(ies) never downloaded")
    if s[PARTIAL]:
        bits.append(f"{s[PARTIAL]} partly downloaded")
    if s[BROKEN]:
        bits.append(f"{s[BROKEN]} recorded but missing from the folder")
    return (f"Incomplete: {'; '.join(bits)}. "
            f"{s[COMPLETE]} of {s['expected']} entries are accounted for "
            f"({s['coverage']}%). Run a check to fetch the rest.")


def reconcile(db, case_id: int, folder: Path | str, *,
              hash_duplicates: bool = True) -> dict:
    """Full three-way audit: docket vs database vs folder."""
    folder = Path(folder)
    entries = db.list_entries(case_id)
    documents = db.list_documents(case_id)

    files = scan(folder)
    # A recorded file counts as present only if it is on disk AND non-empty;
    # a zero-byte PDF is a failed download wearing a document's name.
    present = {str(f["path"]).lower(): f["size"] > 0 for f in files}

    by_entry: dict[int, list[dict]] = defaultdict(list)
    for d in documents:
        by_entry[d["entry_id"]].append(d)

    rows = [_entry_state(e, by_entry.get(e["id"], []), present) for e in entries]

    summary = {
        "entries": len(entries),
        "expected": sum(1 for r in rows if r["has_documents"]),
        "documents": len(documents),
        COMPLETE: sum(1 for r in rows if r["state"] == COMPLETE),
        PARTIAL: sum(1 for r in rows if r["state"] == PARTIAL),
        MISSING: sum(1 for r in rows if r["state"] == MISSING),
        BROKEN: sum(1 for r in rows if r["state"] == BROKEN),
        VIEW_ONLY: sum(1 for r in rows if r["state"] == VIEW_ONLY),
        NONE: sum(1 for r in rows if r["state"] == NONE),
        "undated_entries": sum(1 for r in rows if r["has_documents"] and r["undated"]),
    }
    accounted = summary[COMPLETE] + summary[VIEW_ONLY]
    summary["coverage"] = (
        round(100 * accounted / summary["expected"]) if summary["expected"] else 100
    )

    known_seqs = {e["seq"] for e in entries}
    orphans = [f["name"] for f in files
               if f["seq"] is not None and f["seq"] not in known_seqs]

    return {
        "case_id": case_id,
        "folder": str(folder),
        "summary": summary,
        "verdict": _verdict(summary),
        "trouble": [r for r in rows if r["state"] in TROUBLE],
        "entries": rows,
        "orphans": orphans[:50],
        "orphan_count": len(orphans),
        "inventory": inventory(folder, hash_duplicates=hash_duplicates),
    }


def quarantine_duplicates(folder: Path | str, groups: list[dict],
                          dry_run: bool = True) -> list[dict]:
    """Move redundant copies of the SAME entry into `_duplicates`.

    Only scope "entry" groups are touched — copies of one docket entry fetched
    more than once. Cross-entry duplicates are skipped however identical they
    are, because both entries are entitled to their own copy and removing one
    would leave a docket entry pointing at a file named for a different one.

    Moves, never deletes, and keeps the copy whose name sorts first. A court
    file is the wrong place to be clever about what is safe to throw away.
    """
    folder = Path(folder)
    dest = folder / _DUPLICATES_DIR
    actions: list[dict] = []
    for g in groups:
        if g.get("scope") != "entry":
            continue
        for name in g["files"][1:]:
            src = folder / name
            actions.append({"file": name, "keep": g["files"][0],
                            "target": f"{_DUPLICATES_DIR}/{name}"})
            if not dry_run and src.is_file():
                dest.mkdir(exist_ok=True)
                target = dest / name
                n = 2
                while target.exists():
                    target = dest / f"{Path(name).stem}~{n}{Path(name).suffix}"
                    n += 1
                src.replace(target)
    return actions
