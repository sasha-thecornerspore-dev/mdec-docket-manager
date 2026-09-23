"""End-to-end test of the harvest pipeline with the browser taken out.

Everything between "the portal handed us a docket" and "the folder is correct"
runs here for real: fingerprinting, chronological numbering, catalog naming and
dating, multi-file entries, duplicate content, adoption, and the three-way
audit. Only the Playwright calls are stubbed, because they are the one part
that needs a live court session.

The docket fixture is modelled on the awkward parts of the reference case: a
title that repeats, a day-first date with a time on it, an entry with no
readable date at all, a fourteen-attachment filing, a view-only entry, and a
docket line with no document.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mdec import config
from mdec.pipeline import adopt, audit, renamer
from mdec.portal import docket


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(config, "app_dir", lambda: Path(d))
        from mdec import db
        monkeypatch.setattr(db.config, "app_dir", lambda: Path(d))
        yield db


@pytest.fixture
def folder():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def raw_docket() -> list[dict]:
    """Page order, deliberately not chronological."""
    return [
        # The portal lists scheduled hearings first, dated in the future.
        {"section": "Court Scheduling", "file_date": "15/03/2026, 09:30:00",
         "name": "Merits Hearing", "comment": "", "button_index": None},
        {"section": "Docket Entries", "file_date": "6/17/2025",
         "name": "Request - Waiver of Prepaid Costs", "comment": "",
         "button_index": 0},
        {"section": "Docket Entries", "file_date": "10/30/2019",
         "name": "Motion to Waive Filing Fee Prepayment", "comment": "",
         "button_index": 1},
        {"section": "Docket Entries", "file_date": "3/11/2025",
         "name": "Supporting Exhibit", "comment": "filed with motion",
         "button_index": 2},
        {"section": "Docket Entries", "file_date": "3/11/2025",
         "name": "Supporting Exhibit", "comment": "second copy",
         "button_index": 3},
        # Fourteen attachments behind one button.
        {"section": "Docket Entries", "file_date": "1/8/2021",
         "name": "Answer to Complaint", "comment": "", "button_index": 4},
        # Visible on the docket, but the portal offers nothing to download.
        {"section": "Docket Entries", "file_date": "2/2/2022",
         "name": "Notice of Hearing", "comment": "", "button_index": 5},
        # No document at all, and a date the parser cannot read.
        {"section": "Docket Entries", "file_date": "n/a",
         "name": "Case Reassigned", "comment": "", "button_index": None},
    ]


def ingest(db, case_id: int, rows: list[dict]) -> list[dict]:
    """The database half of a check: fingerprint, diff, number, insert."""
    entries = docket.fingerprint(rows)
    new = docket.diff_new(entries, db.known_fingerprints(case_id))
    base = db.max_seq(case_id)
    for i, e in enumerate(renamer.filing_order(new)):
        e["seq"] = base + 1 + i
        e["has_documents"] = e.get("button_index") is not None
        e["id"] = db.insert_entry(case_id, e)
    return new


def deliver(db, folder: Path, entry: dict, titles: list[str],
            payloads: list[bytes] | None = None) -> list[Path]:
    """Stand in for a download: write files, name them, record them."""
    out = []
    total = len(titles)
    for j, title in enumerate(titles):
        tmp = folder / f"__incoming__{entry['seq']}_{j}.pdf"
        tmp.write_bytes(payloads[j] if payloads
                        else f"{entry['seq']}-{j}".encode() * 64)
        final = renamer.place_download(
            tmp, folder, entry["seq"], entry.get("file_date", ""), title,
            part=(j + 1) if total > 1 else None, total_parts=total)
        db.insert_document(entry["id"], title, final.name, str(final),
                           audit.sha256_of(final), final.stat().st_size)
        out.append(final)
    db.set_entry_doc_status(entry["id"], "ok")
    return out


# --- numbering and naming --------------------------------------------------

def test_entries_are_numbered_chronologically_not_in_page_order(temp_db):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    rows = db.list_entries(cid)

    assert rows[0]["name"] == "Motion to Waive Filing Fee Prepayment"  # 2019
    assert rows[1]["name"] == "Answer to Complaint"                    # 2021
    assert rows[-1]["name"] == "Case Reassigned"      # unreadable date sorts last
    # The future hearing is still ahead of the undated line.
    assert rows[-2]["name"] == "Merits Hearing"


def test_filenames_carry_a_date_that_agrees_with_the_sequence(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    for e in db.list_entries(cid):
        if e["has_documents"]:
            deliver(db, folder, e, [e["name"]])

    names = sorted(p.name for p in folder.glob("*.pdf"))
    dates = [n.split("_")[1] for n in names]
    assert dates == sorted(dates), "name order must equal date order"
    assert "0001_20191030_Motion to Waive Filing Fee Prepayment.pdf" in names


def test_a_day_first_date_with_a_time_still_parses(temp_db):
    """The scheduling section writes 15/03/2026, 09:30:00."""
    assert renamer.date_stamp("15/03/2026, 09:30:00") == "20260315"


def test_an_unreadable_date_never_blocks_a_filename(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    e = {"seq": 1, "name": "Case Reassigned", "file_date": "n/a",
         "fingerprint": "z#0", "has_documents": True}
    e["id"] = db.insert_entry(cid, e)
    [path] = deliver(db, folder, e, ["Case Reassigned"])
    assert path.name == "0001_XXXXXXXX_Case Reassigned.pdf"


def test_multi_file_entries_are_numbered_within_the_entry(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    e = {"seq": 7, "name": "Answer to Complaint", "file_date": "1/8/2021",
         "fingerprint": "m#0", "has_documents": True}
    e["id"] = db.insert_entry(cid, e)
    paths = deliver(db, folder, e, [f"Exhibit {i}" for i in range(1, 15)])
    assert len(paths) == 14
    assert paths[0].name == "0007_20210108_Exhibit 1_1of14.pdf"
    assert paths[13].name == "0007_20210108_Exhibit 14_14of14.pdf"


def test_a_repeated_title_never_overwrites_the_earlier_file(temp_db, folder):
    """Same entry delivered twice: the second copy is kept, not clobbered."""
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    e = {"seq": 3, "name": "Supporting Exhibit", "file_date": "3/11/2025",
         "fingerprint": "s#0", "has_documents": True}
    e["id"] = db.insert_entry(cid, e)
    first = deliver(db, folder, e, ["Supporting Exhibit"])[0]
    second = deliver(db, folder, e, ["Supporting Exhibit"])[0]
    assert first.name == "0003_20250311_Supporting Exhibit.pdf"
    assert second.name == "0003_20250311_Supporting Exhibit~2.pdf"
    assert first.exists() and second.exists()


# --- the audit -------------------------------------------------------------

def _harvest_everything(db, cid, folder) -> None:
    for e in db.list_entries(cid):
        if not e["has_documents"]:
            continue
        if e["name"] == "Notice of Hearing":
            db.set_entry_doc_status(e["id"], "view_only")
            continue
        if e["name"] == "Answer to Complaint":
            db.set_entry_expected_docs(e["id"], 14)
            deliver(db, folder, e, [f"Exhibit {i}" for i in range(1, 15)])
            continue
        deliver(db, folder, e, [e["name"]])


def test_a_finished_harvest_reports_complete(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    _harvest_everything(db, cid, folder)

    r = audit.reconcile(db, cid, folder)
    s = r["summary"]
    assert s[audit.MISSING] == 0
    assert s[audit.PARTIAL] == 0
    assert s[audit.BROKEN] == 0
    assert s[audit.VIEW_ONLY] == 1
    assert s["coverage"] == 100
    assert r["verdict"].startswith("Complete:")
    assert r["trouble"] == []


def test_an_entry_that_was_never_downloaded_is_reported_missing(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    _harvest_everything(db, cid, folder)

    skipped = [e for e in db.list_entries(cid)
               if e["name"] == "Request - Waiver of Prepaid Costs"][0]
    for d in db.list_documents(cid):
        if d["entry_id"] == skipped["id"]:
            Path(d["path"]).unlink()

    r = audit.reconcile(db, cid, folder)
    assert r["summary"][audit.BROKEN] == 1
    assert "Incomplete" in r["verdict"]
    assert [t["seq"] for t in r["trouble"]] == [skipped["seq"]]


def test_a_half_delivered_multi_file_entry_is_reported_partial(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    answer = [e for e in db.list_entries(cid)
              if e["name"] == "Answer to Complaint"][0]
    # The popup offered fourteen; nine arrived.
    db.set_entry_expected_docs(answer["id"], 14)
    deliver(db, folder, answer, [f"Exhibit {i}" for i in range(1, 10)])

    r = audit.reconcile(db, cid, folder)
    row = [x for x in r["entries"] if x["entry_id"] == answer["id"]][0]
    assert row["state"] == audit.PARTIAL
    assert "9 of 14" in row["detail"]


def test_a_zero_byte_file_does_not_count_as_a_document(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    e = {"seq": 1, "name": "Order", "file_date": "1/2/2024",
         "fingerprint": "o#0", "has_documents": True}
    e["id"] = db.insert_entry(cid, e)
    [path] = deliver(db, folder, e, ["Order"])
    path.write_bytes(b"")

    r = audit.reconcile(db, cid, folder)
    assert r["summary"][audit.BROKEN] == 1
    assert r["inventory"]["zero_byte"] == [path.name]


def test_an_empty_docket_says_so_rather_than_claiming_completeness(temp_db,
                                                                  folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    r = audit.reconcile(db, cid, folder)
    assert "No docket has been read yet" in r["verdict"]


def test_a_catalog_file_with_no_docket_entry_is_an_orphan(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    (folder / "9999_20240101_Something Else.pdf").write_bytes(b"x" * 10)

    r = audit.reconcile(db, cid, folder)
    assert r["orphans"] == ["9999_20240101_Something Else.pdf"]


def test_legacy_names_are_counted_as_unfiled_not_ignored(folder):
    (folder / "Answer to Complaint-24D19003791 (3).pdf").write_bytes(b"x" * 10)
    (folder / "0001_20240101_Answer.pdf").write_bytes(b"y" * 10)

    inv = audit.inventory(folder)
    assert inv["catalog_named"] == 1
    assert inv["unfiled_count"] == 1
    assert inv["unfiled"] == ["Answer to Complaint-24D19003791 (3).pdf"]


def test_the_manifest_and_dot_files_are_not_mistaken_for_documents(folder):
    (folder / renamer.MANIFEST).write_text("x")
    (folder / "_notes.pdf").write_bytes(b"x" * 10)
    (folder / "0001_20240101_Real.pdf").write_bytes(b"y" * 10)
    assert audit.inventory(folder)["files"] == 1


# --- duplicates ------------------------------------------------------------

def test_identical_files_under_one_entry_are_redundant(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    e = {"seq": 3, "name": "Supporting Exhibit", "file_date": "3/11/2025",
         "fingerprint": "s#0", "has_documents": True}
    e["id"] = db.insert_entry(cid, e)
    same = b"identical bytes " * 100
    deliver(db, folder, e, ["Supporting Exhibit"], payloads=[same])
    deliver(db, folder, e, ["Supporting Exhibit"], payloads=[same])

    [group] = audit.inventory(folder)["duplicates"]
    assert group["scope"] == "entry"
    assert group["count"] == 2
    assert group["wasted_bytes"] == len(same)

    actions = audit.quarantine_duplicates(folder, [group], dry_run=True)
    assert [a["file"] for a in actions] == \
        ["0003_20250311_Supporting Exhibit~2.pdf"]
    assert (folder / "0003_20250311_Supporting Exhibit~2.pdf").exists(), \
        "a dry run must not move anything"

    audit.quarantine_duplicates(folder, [group], dry_run=False)
    assert (folder / "_duplicates" /
            "0003_20250311_Supporting Exhibit~2.pdf").is_file()
    assert (folder / "0003_20250311_Supporting Exhibit.pdf").is_file()


def test_one_exhibit_filed_under_two_entries_is_never_quarantined(temp_db,
                                                                 folder):
    """Both entries are entitled to their own copy of the same exhibit."""
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    same = b"one exhibit, two filings " * 50
    for seq, fp in ((3, "a#0"), (4, "b#0")):
        e = {"seq": seq, "name": "Supporting Exhibit", "file_date": "3/11/2025",
             "fingerprint": fp, "has_documents": True}
        e["id"] = db.insert_entry(cid, e)
        deliver(db, folder, e, ["Supporting Exhibit"], payloads=[same])

    [group] = audit.inventory(folder)["duplicates"]
    assert group["scope"] == "cross"
    assert group["seqs"] == [3, 4]
    assert group["wasted_bytes"] == 0
    assert audit.quarantine_duplicates(folder, [group], dry_run=False) == []
    assert len(list(folder.glob("*.pdf"))) == 2


def test_uniquely_sized_files_are_never_hashed(folder, monkeypatch):
    for i in range(1, 6):
        (folder / f"000{i}_20240101_Doc {i}.pdf").write_bytes(b"x" * (100 + i))
    monkeypatch.setattr(audit, "sha256_of",
                        lambda *a, **k: pytest.fail("hashed a unique size"))
    assert audit.inventory(folder)["duplicates"] == []


# --- repairing a legacy folder ---------------------------------------------

def test_a_repeated_title_marks_its_renames_as_order_dependent(folder):
    """A unique title cannot be placed wrongly; a repeated one can, silently."""
    names = ["Order-C01cv24001234.pdf",
             "Supporting Exhibit-C01cv24001234.pdf",
             "Supporting Exhibit-C01cv24001234 (1).pdf"]
    for i, n in enumerate(names):
        (folder / n).write_bytes(b"x" * (10 + i))

    index = [
        {"seq": 1, "file_date": "1/2/2024", "title": "Order"},
        {"seq": 2, "file_date": "3/4/2024", "title": "Supporting Exhibit"},
        {"seq": 3, "file_date": "5/6/2024", "title": "Supporting Exhibit"},
    ]
    actions = renamer.repair_folder(folder, "C01cv24001234", index,
                                    dry_run=True, sort_key=lambda p: p.name)
    by_file = {a["file"]: a for a in actions if a["status"] == "rename"}
    assert by_file["Order-C01cv24001234.pdf"]["ambiguous"] is False
    assert by_file["Supporting Exhibit-C01cv24001234.pdf"]["ambiguous"] is True
    assert sum(1 for a in actions if a.get("ambiguous")) == 2


def test_an_extra_physical_copy_is_left_alone_rather_than_guessed_at(folder):
    for n in ("Order-C01cv24001234.pdf", "Order-C01cv24001234 (1).pdf"):
        (folder / n).write_bytes(b"x" * 10)
    index = [{"seq": 1, "file_date": "1/2/2024", "title": "Order"}]
    actions = renamer.repair_folder(folder, "C01cv24001234", index,
                                    dry_run=True, sort_key=lambda p: p.name)
    assert [a["status"] for a in actions] == ["rename", "unmatched"]


# --- resuming --------------------------------------------------------------

def test_a_rebuilt_database_re_adopts_the_folder_instead_of_refetching(
        temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    _harvest_everything(db, cid, folder)
    before = audit.reconcile(db, cid, folder, hash_duplicates=False)

    # Wipe what the app believes about downloads, keep the files.
    with db.conn() as c:
        c.execute("DELETE FROM documents")
        c.execute("UPDATE entries SET doc_status='pending' WHERE doc_status='ok'")
    assert audit.reconcile(db, cid, folder,
                           hash_duplicates=False)["summary"][audit.MISSING] > 0

    adopt.adopt_folder(db, cid, folder)
    after = audit.reconcile(db, cid, folder, hash_duplicates=False)
    assert after["summary"][audit.COMPLETE] == before["summary"][audit.COMPLETE]
    assert after["summary"][audit.MISSING] == 0
    assert db.entries_missing_documents(cid) == []


def test_losing_the_view_only_flag_requeues_only_that_entry(temp_db, folder):
    """Adoption cannot restore "the portal offers no file" — only the portal can.

    So a database rebuilt from nothing re-queues the view-only entries, and
    nothing else. That is the cheap, correct outcome: one popup re-opened rather
    than a whole docket re-downloaded.
    """
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    _harvest_everything(db, cid, folder)
    with db.conn() as c:
        c.execute("DELETE FROM documents")
        c.execute("UPDATE entries SET doc_status='pending'")
    adopt.adopt_folder(db, cid, folder)

    requeued = db.entries_missing_documents(cid)
    assert [e["name"] for e in requeued] == ["Notice of Hearing"]


def test_adopting_twice_adopts_nothing_the_second_time(temp_db, folder):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    ingest(db, cid, raw_docket())
    _harvest_everything(db, cid, folder)
    with db.conn() as c:
        c.execute("DELETE FROM documents")
    assert adopt.adopt_folder(db, cid, folder)["adopted"] > 0
    assert adopt.adopt_folder(db, cid, folder)["adopted"] == 0
