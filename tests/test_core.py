"""Tests for the pure-logic pieces: fingerprint/diff, catalog naming, the
occurrence-counted repair rename, email-code extraction, and the DB layer.

These run with no network, no browser, and no API key:
    python -m pytest tests -q
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from mdec import config
from mdec.portal import docket, email_code
from mdec.pipeline import renamer


# --- fingerprint / diff ----------------------------------------------------

def _e(name, date="1/2/2024", comment="", section="Docket Entries"):
    return {"name": name, "file_date": date, "comment": comment,
            "section": section}


def test_identical_entries_get_distinct_fingerprints():
    rows = docket.fingerprint([_e("Writ"), _e("Writ"), _e("Writ")])
    assert len({r["fingerprint"] for r in rows}) == 3
    assert [r["fingerprint"].split("#")[1] for r in rows] == ["0", "1", "2"]


def test_diff_returns_only_the_new_copies_of_a_repeated_entry():
    """The reference case had one title 146 times. Going 3 -> 5 must yield 2."""
    before = docket.fingerprint([_e("Writ") for _ in range(3)])
    known = {r["fingerprint"] for r in before}
    after = docket.fingerprint([_e("Writ") for _ in range(5)])
    new = docket.diff_new(after, known)
    assert len(new) == 2
    assert [n["fingerprint"].split("#")[1] for n in new] == ["3", "4"]


def test_fingerprint_is_not_confused_by_aliased_input():
    """Same dict object repeated must still yield distinct fingerprints."""
    shared = _e("Writ")
    rows = docket.fingerprint([shared, shared, shared])
    assert len({r["fingerprint"] for r in rows}) == 3
    assert "fingerprint" not in shared          # input left untouched


def test_diff_is_empty_when_nothing_changed():
    rows = docket.fingerprint([_e("A"), _e("B"), _e("C")])
    assert docket.diff_new(rows, {r["fingerprint"] for r in rows}) == []


def test_fingerprint_distinguishes_on_every_field():
    a = docket.fingerprint([_e("Order")])[0]["fingerprint"]
    b = docket.fingerprint([_e("Order", date="1/3/2024")])[0]["fingerprint"]
    c = docket.fingerprint([_e("Order", comment="x")])[0]["fingerprint"]
    d = docket.fingerprint([_e("Order", section="Other")])[0]["fingerprint"]
    assert len({a, b, c, d}) == 4


# --- catalog naming --------------------------------------------------------

def test_catalog_name_format():
    assert renamer.catalog_name(2, "8/26/2024", "Order to Docket") == \
        "0002_20240826_Order to Docket.pdf"


def test_unknown_date_is_marked_not_guessed():
    assert renamer.catalog_name(7, "", "Thing") == "0007_XXXXXXXX_Thing.pdf"
    assert renamer.catalog_name(7, "13/45/2024", "Thing").startswith(
        "0007_XXXXXXXX_")


def test_multi_file_entries_get_part_suffixes():
    assert renamer.catalog_name(555, "1/2/2024", "Exhibit", part=3,
                                total_parts=14) == \
        "0555_20240102_Exhibit_3of14.pdf"


def test_illegal_characters_are_stripped():
    name = renamer.catalog_name(1, "1/2/2024", 'Mot: "Strike"/Deny?')
    assert not any(ch in name[:-4] for ch in '<>:"/\\|?*')


def test_stem_of_strips_case_id_and_duplicate_suffix():
    assert renamer.stem_of("Order to Docket-C03cv24003218 (3).pdf",
                           "C03cv24003218") == "Order to Docket"
    assert renamer.stem_of("Order to Docket-C03cv24003218.pdf",
                           "C03cv24003218") == "Order to Docket"


# --- occurrence-counted repair --------------------------------------------

@pytest.fixture
def dump():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _touch(folder: Path, name: str, order: int) -> Path:
    p = folder / name
    p.write_bytes(b"%PDF-1.4\n")
    # Make sort order deterministic without depending on filesystem ctime.
    os.utime(p, (1_700_000_000 + order, 1_700_000_000 + order))
    return p


def test_repair_maps_nth_copy_to_nth_docket_slot(dump):
    """Three files sharing a title must land in the three slots that expect it,
    in download order — never scrambled by the (1)/(2) suffix."""
    cid = "C03cv24003218"
    _touch(dump, f"Writ-{cid}.pdf", 1)
    _touch(dump, f"Writ-{cid} (1).pdf", 2)
    _touch(dump, f"Writ-{cid} (2).pdf", 3)
    index = [
        {"seq": 10, "file_date": "1/1/2024", "title": "Writ"},
        {"seq": 11, "file_date": "2/2/2024", "title": "Writ"},
        {"seq": 12, "file_date": "3/3/2024", "title": "Writ"},
    ]
    actions = renamer.repair_folder(dump, cid, index, dry_run=True,
                                   sort_key=lambda p: p.stat().st_mtime)
    targets = [a["target"] for a in actions if a["status"] == "rename"]
    assert targets == [
        "0010_20240101_Writ.pdf",
        "0011_20240202_Writ.pdf",
        "0012_20240303_Writ.pdf",
    ]


def test_repair_actually_renames_and_writes_a_manifest(dump):
    cid = "C03cv24003218"
    _touch(dump, f"Order-{cid}.pdf", 1)
    index = [{"seq": 4, "file_date": "5/6/2024", "title": "Order"}]
    renamer.repair_folder(dump, cid, index, dry_run=False,
                          sort_key=lambda p: p.stat().st_mtime)
    assert (dump / "0004_20240506_Order.pdf").exists()
    manifest = (dump / renamer.MANIFEST).read_text(encoding="utf-8")
    assert f"Order-{cid}.pdf" in manifest      # reversible


def test_repair_flags_extra_files_instead_of_mislabeling(dump):
    cid = "C03cv24003218"
    _touch(dump, f"Writ-{cid}.pdf", 1)
    _touch(dump, f"Writ-{cid} (1).pdf", 2)
    index = [{"seq": 10, "file_date": "1/1/2024", "title": "Writ"}]
    actions = renamer.repair_folder(dump, cid, index, dry_run=True,
                                    sort_key=lambda p: p.stat().st_mtime)
    assert sum(1 for a in actions if a["status"] == "unmatched") == 1


def test_repair_flags_docket_slots_with_no_file(dump):
    cid = "C03cv24003218"
    _touch(dump, f"Writ-{cid}.pdf", 1)
    index = [{"seq": 10, "file_date": "1/1/2024", "title": "Writ"},
             {"seq": 11, "file_date": "2/2/2024", "title": "Writ"}]
    actions = renamer.repair_folder(dump, cid, index, dry_run=True,
                                    sort_key=lambda p: p.stat().st_mtime)
    missing = [a for a in actions if a["status"] == "missing"]
    assert len(missing) == 1 and "0011" in missing[0]["target"]


def test_repair_never_overwrites_an_existing_target(dump):
    cid = "C03cv24003218"
    (dump / "0010_20240101_Writ.pdf").write_bytes(b"%PDF-1.4\nexisting")
    _touch(dump, f"Writ-{cid}.pdf", 1)
    index = [{"seq": 10, "file_date": "1/1/2024", "title": "Writ"}]
    renamer.repair_folder(dump, cid, index, dry_run=False,
                          sort_key=lambda p: p.stat().st_mtime)
    assert (dump / "0010_20240101_Writ.pdf").read_bytes().endswith(b"existing")
    assert (dump / "0010_20240101_Writ~2.pdf").exists()


# --- case id / url ---------------------------------------------------------

def test_case_id_normalization():
    assert config.normalize_case_id("C-03-CV-24-003218") == "C03cv24003218"
    assert config.normalize_case_id("c03cv24003218") == "C03cv24003218"


def test_case_url_contains_normalized_id():
    assert "caseId=C03cv24003218" in config.case_url("C-03-CV-24-003218")


# --- email verification code ---------------------------------------------

def test_extracts_six_digit_code():
    body = "Your Maryland Judiciary verification code is 481902. It expires."
    assert email_code.extract_code(body, r"\b(\d{6})\b") == "481902"


def test_no_code_returns_none():
    assert email_code.extract_code("no digits here", r"\b(\d{6})\b") is None
    assert email_code.extract_code("", r"\b(\d{6})\b") is None


def test_short_numbers_are_not_mistaken_for_a_code():
    assert email_code.extract_code("case 12345 filed", r"\b(\d{6})\b") is None


# --- database -------------------------------------------------------------

@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(config, "app_dir", lambda: Path(d))
        from mdec import db
        monkeypatch.setattr(db.config, "app_dir", lambda: Path(d))
        yield db


def test_entry_insert_is_idempotent_on_fingerprint(temp_db):
    db = temp_db
    cid = db.upsert_case("C-03-CV-24-003218", "Caption", "Court")
    e = {"seq": 1, "name": "Order", "fingerprint": "abc#0", "has_documents": True}
    first = db.insert_entry(cid, e)
    assert db.insert_entry(cid, e) == first          # re-check doesn't duplicate
    assert len(db.list_entries(cid)) == 1


def test_known_fingerprints_round_trip(temp_db):
    db = temp_db
    cid = db.upsert_case("C-03-CV-24-003218")
    for i in range(3):
        db.insert_entry(cid, {"seq": i, "name": "X", "fingerprint": f"f#{i}"})
    assert db.known_fingerprints(cid) == {"f#0", "f#1", "f#2"}
    assert db.max_seq(cid) == 2


def test_notes_and_documents_attach_to_entries(temp_db):
    db = temp_db
    cid = db.upsert_case("C-03-CV-24-003218")
    eid = db.insert_entry(cid, {"seq": 1, "name": "Order", "fingerprint": "a#0"})
    did = db.insert_document(eid, "Order", "0001_x.pdf", "C:/x.pdf", "sha", 100)
    nid = db.add_note(cid, "check this", entry_id=eid)
    assert db.list_documents(cid)[0]["id"] == did
    assert db.list_notes(cid, eid)[0]["body"] == "check this"
    db.update_note(nid, "revised")
    assert db.list_notes(cid, eid)[0]["body"] == "revised"
    db.delete_note(nid)
    assert db.list_notes(cid, eid) == []


def test_runs_record_status_and_log(temp_db):
    db = temp_db
    cid = db.upsert_case("C-03-CV-24-003218")
    rid = db.start_run(cid, "check")
    db.append_run_log(rid, "opened portal")
    db.finish_run(rid, "warning", new_entries=2, new_documents=3, log="one issue")
    run = db.list_runs(1)[0]
    assert run["status"] == "warning"
    assert run["new_entries"] == 2 and run["new_documents"] == 3


# --- config safety --------------------------------------------------------

def test_saving_settings_never_writes_a_secret_to_disk(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(config, "app_dir", lambda: Path(d))
        cfg = config.load_config()
        cfg["login"]["portal_password"] = "hunter2"      # simulate a bad payload
        cfg["analysis"]["anthropic_api_key"] = "sk-ant-oops"
        config.save_config(cfg)
        written = config.config_path().read_text(encoding="utf-8")
        assert "hunter2" not in written
        assert "sk-ant-oops" not in written


def test_unknown_secret_slots_are_rejected():
    with pytest.raises(ValueError):
        config.set_secret("not_a_real_slot", "x")
