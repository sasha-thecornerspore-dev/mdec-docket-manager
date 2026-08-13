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
from mdec.pipeline import adopt, renamer


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
    assert renamer.stem_of("Order to Docket-C01cv24001234 (3).pdf",
                           "C01cv24001234") == "Order to Docket"
    assert renamer.stem_of("Order to Docket-C01cv24001234.pdf",
                           "C01cv24001234") == "Order to Docket"


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
    cid = "C01cv24001234"
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
    cid = "C01cv24001234"
    _touch(dump, f"Order-{cid}.pdf", 1)
    index = [{"seq": 4, "file_date": "5/6/2024", "title": "Order"}]
    renamer.repair_folder(dump, cid, index, dry_run=False,
                          sort_key=lambda p: p.stat().st_mtime)
    assert (dump / "0004_20240506_Order.pdf").exists()
    manifest = (dump / renamer.MANIFEST).read_text(encoding="utf-8")
    assert f"Order-{cid}.pdf" in manifest      # reversible


def test_repair_flags_extra_files_instead_of_mislabeling(dump):
    cid = "C01cv24001234"
    _touch(dump, f"Writ-{cid}.pdf", 1)
    _touch(dump, f"Writ-{cid} (1).pdf", 2)
    index = [{"seq": 10, "file_date": "1/1/2024", "title": "Writ"}]
    actions = renamer.repair_folder(dump, cid, index, dry_run=True,
                                    sort_key=lambda p: p.stat().st_mtime)
    assert sum(1 for a in actions if a["status"] == "unmatched") == 1


def test_repair_flags_docket_slots_with_no_file(dump):
    cid = "C01cv24001234"
    _touch(dump, f"Writ-{cid}.pdf", 1)
    index = [{"seq": 10, "file_date": "1/1/2024", "title": "Writ"},
             {"seq": 11, "file_date": "2/2/2024", "title": "Writ"}]
    actions = renamer.repair_folder(dump, cid, index, dry_run=True,
                                    sort_key=lambda p: p.stat().st_mtime)
    missing = [a for a in actions if a["status"] == "missing"]
    assert len(missing) == 1 and "0011" in missing[0]["target"]


def test_repair_never_overwrites_an_existing_target(dump):
    cid = "C01cv24001234"
    (dump / "0010_20240101_Writ.pdf").write_bytes(b"%PDF-1.4\nexisting")
    _touch(dump, f"Writ-{cid}.pdf", 1)
    index = [{"seq": 10, "file_date": "1/1/2024", "title": "Writ"}]
    renamer.repair_folder(dump, cid, index, dry_run=False,
                          sort_key=lambda p: p.stat().st_mtime)
    assert (dump / "0010_20240101_Writ.pdf").read_bytes().endswith(b"existing")
    assert (dump / "0010_20240101_Writ~2.pdf").exists()


# --- case id / url ---------------------------------------------------------

def test_case_id_normalization():
    assert config.normalize_case_id("C-01-CV-24-001234") == "C01cv24001234"
    assert config.normalize_case_id("C01cv24001234") == "C01cv24001234"


def test_case_url_contains_normalized_id():
    assert "caseId=C01cv24001234" in config.case_url("C-01-CV-24-001234")


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
    cid = db.upsert_case("C-01-CV-24-001234", "Caption", "Court")
    e = {"seq": 1, "name": "Order", "fingerprint": "abc#0", "has_documents": True}
    first = db.insert_entry(cid, e)
    assert db.insert_entry(cid, e) == first          # re-check doesn't duplicate
    assert len(db.list_entries(cid)) == 1


def test_known_fingerprints_round_trip(temp_db):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    for i in range(3):
        db.insert_entry(cid, {"seq": i, "name": "X", "fingerprint": f"f#{i}"})
    assert db.known_fingerprints(cid) == {"f#0", "f#1", "f#2"}
    assert db.max_seq(cid) == 2


def test_notes_and_documents_attach_to_entries(temp_db):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
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
    cid = db.upsert_case("C-01-CV-24-001234")
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


def test_pre_multi_case_config_is_carried_forward(monkeypatch):
    """An old single-case config must not lose the case or its folder."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(config, "app_dir", lambda: Path(d))
        old = {"case": {"case_number": "C-01-CV-24-001234", "caption": "Smith",
                        "court": "Circuit"},
               "folders": {"downloads": r"D:\Cases\smith\docket"}}
        config.config_path().write_text(__import__("json").dumps(old),
                                        encoding="utf-8")
        cfg = config.load_config()
        assert cfg["active_case_number"] == "C-01-CV-24-001234"
        assert "case" not in cfg
        assert cfg["_migrate_case"]["downloads"] == r"D:\Cases\smith\docket"
        # consuming it clears the marker so it only happens once
        assert config.consume_case_migration()["caption"] == "Smith"
        assert config.consume_case_migration() is None


# --- adopting files already on disk --------------------------------------

def test_parse_catalog_name_recovers_the_sequence():
    p = adopt.parse_catalog_name("0042_20240826_Order to Docket.pdf")
    assert p["seq"] == 42 and p["description"] == "Order to Docket"
    assert p["total_parts"] == 1


def test_parse_catalog_name_handles_parts_unknown_dates_and_dupes():
    assert adopt.parse_catalog_name("0555_XXXXXXXX_Exhibit_3of14.pdf") == {
        "seq": 555, "date": "XXXXXXXX", "description": "Exhibit",
        "part": 3, "total_parts": 14}
    assert adopt.parse_catalog_name("0010_20240101_Writ~2.pdf")["seq"] == 10


def test_parse_catalog_name_rejects_non_catalog_files():
    for name in ("Order to Docket-C01cv24001234.pdf", "scan.pdf",
                 "notes.txt", "_ORIGINAL_NAMES_manifest.csv"):
        assert adopt.parse_catalog_name(name) is None


def test_scan_folder_groups_by_sequence_and_ignores_strays(dump):
    for n in ("0001_20240101_Order.pdf", "0002_20240202_Writ_1of2.pdf",
              "0002_20240202_Writ_2of2.pdf", "random-scan.pdf",
              "_ORIGINAL_NAMES_manifest.csv"):
        (dump / n).write_bytes(b"%PDF-1.4\n")
    found = adopt.scan_folder(dump)
    assert sorted(found) == [1, 2]
    assert len(found[2]) == 2
    assert [f["part"] for f in found[2]] == [1, 2]      # ordered by part


def test_scan_folder_on_a_missing_folder_is_empty():
    assert adopt.scan_folder(Path("Z:/definitely/not/here")) == {}


def test_adopt_links_existing_files_and_is_idempotent(temp_db, dump):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234", downloads=str(dump))
    e1 = db.insert_entry(cid, {"seq": 1, "name": "Order", "fingerprint": "a#0",
                               "has_documents": True})
    db.insert_entry(cid, {"seq": 2, "name": "Writ", "fingerprint": "b#0",
                          "has_documents": True})
    (dump / "0001_20240101_Order.pdf").write_bytes(b"%PDF-1.4\norder")
    (dump / "0002_20240202_Writ.pdf").write_bytes(b"%PDF-1.4\nwrit")

    first = adopt.adopt_folder(db, cid, dump)
    assert first["adopted"] == 2 and first["entries"] == 2
    assert len(db.list_documents(cid)) == 2

    again = adopt.adopt_folder(db, cid, dump)
    assert again["adopted"] == 0            # nothing re-adopted
    assert len(db.list_documents(cid)) == 2

    doc = [d for d in db.list_documents(cid) if d["entry_id"] == e1][0]
    assert doc["size_bytes"] == len(b"%PDF-1.4\norder")
    assert doc["sha256"]


def test_adopt_reports_files_with_no_matching_entry(temp_db, dump):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234", downloads=str(dump))
    db.insert_entry(cid, {"seq": 1, "name": "Order", "fingerprint": "a#0",
                          "has_documents": True})
    (dump / "0001_20240101_Order.pdf").write_bytes(b"%PDF-1.4\n")
    (dump / "0099_20250101_Mystery.pdf").write_bytes(b"%PDF-1.4\n")
    r = adopt.adopt_folder(db, cid, dump)
    assert r["adopted"] == 1
    assert r["orphan_count"] == 1 and "0099_20250101_Mystery.pdf" in r["orphans"]


def test_adopt_skips_zero_byte_files(temp_db, dump):
    """A zero-byte file is a failed download, not a document."""
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234", downloads=str(dump))
    db.insert_entry(cid, {"seq": 1, "name": "Order", "fingerprint": "a#0",
                          "has_documents": True})
    (dump / "0001_20240101_Order.pdf").write_bytes(b"")
    assert adopt.adopt_folder(db, cid, dump)["adopted"] == 0


def test_adopt_marks_the_entry_satisfied(temp_db, dump):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234", downloads=str(dump))
    db.insert_entry(cid, {"seq": 1, "name": "Order", "fingerprint": "a#0",
                          "has_documents": True})
    assert len(db.entries_missing_documents(cid)) == 1
    (dump / "0001_20240101_Order.pdf").write_bytes(b"%PDF-1.4\n")
    adopt.adopt_folder(db, cid, dump)
    assert db.entries_missing_documents(cid) == []


# --- resume / gap tracking ------------------------------------------------

def test_view_only_entries_are_not_retried_forever(temp_db):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    eid = db.insert_entry(cid, {"seq": 1, "name": "Hearing", "fingerprint": "a#0",
                                "has_documents": True})
    assert len(db.entries_missing_documents(cid)) == 1
    db.set_entry_doc_status(eid, "view_only")
    assert db.entries_missing_documents(cid) == []


def test_failed_downloads_are_retried(temp_db):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    eid = db.insert_entry(cid, {"seq": 1, "name": "Order", "fingerprint": "a#0",
                                "has_documents": True})
    db.set_entry_doc_status(eid, "error")
    assert len(db.entries_missing_documents(cid)) == 1


def test_entries_without_documents_are_not_chased(temp_db):
    """A docket entry with no Document button should never be a download gap."""
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234")
    db.insert_entry(cid, {"seq": 1, "name": "Text-only entry",
                          "fingerprint": "a#0", "has_documents": False})
    assert db.entries_missing_documents(cid) == []


# --- multiple cases -------------------------------------------------------

def test_cases_are_isolated_from_each_other(temp_db):
    db = temp_db
    a = db.upsert_case("C-01-CV-24-001111", "Case A", downloads="A:/a")
    b = db.upsert_case("C-02-CV-24-002222", "Case B", downloads="B:/b")
    db.insert_entry(a, {"seq": 1, "name": "Order A", "fingerprint": "x#0"})
    db.insert_entry(b, {"seq": 1, "name": "Order B", "fingerprint": "x#0"})
    db.add_note(a, "note for A")
    assert len(db.list_entries(a)) == 1
    assert db.list_entries(a)[0]["name"] == "Order A"
    assert len(db.list_notes(b)) == 0
    # the same fingerprint in two cases is fine — uniqueness is per case
    assert db.known_fingerprints(a) == db.known_fingerprints(b) == {"x#0"}


def test_list_cases_reports_counts(temp_db):
    db = temp_db
    a = db.upsert_case("C-01-CV-24-001111", "Case A")
    db.upsert_case("C-02-CV-24-002222", "Case B")
    eid = db.insert_entry(a, {"seq": 1, "name": "Order", "fingerprint": "x#0"})
    db.insert_document(eid, "Order", "0001_x.pdf", "C:/x.pdf", "sha", 10)
    rows = {c["case_number"]: c for c in db.list_cases()}
    assert rows["C-01-CV-24-001111"]["entry_count"] == 1
    assert rows["C-01-CV-24-001111"]["doc_count"] == 1
    assert rows["C-02-CV-24-002222"]["entry_count"] == 0


def test_deleting_a_case_removes_only_its_data(temp_db):
    db = temp_db
    a = db.upsert_case("C-01-CV-24-001111")
    b = db.upsert_case("C-02-CV-24-002222")
    ea = db.insert_entry(a, {"seq": 1, "name": "A", "fingerprint": "x#0"})
    db.insert_document(ea, "A", "a.pdf", "C:/a.pdf", "sha", 10)
    db.add_note(a, "note A")
    db.insert_entry(b, {"seq": 1, "name": "B", "fingerprint": "y#0"})
    db.add_note(b, "note B")

    db.delete_case(a)
    assert db.get_case("C-01-CV-24-001111") is None
    assert db.list_entries(a) == [] and db.list_documents(a) == []
    assert db.list_notes(a) == []
    assert len(db.list_entries(b)) == 1 and len(db.list_notes(b)) == 1


def test_case_folder_defaults_to_a_subfolder_per_case(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(config, "app_dir", lambda: Path(d))
        cfg = config.load_config()
        cfg["folders"]["downloads_root"] = r"D:\Cases"
        folder = config.default_case_folder("C-01-CV-24-001234", cfg)
        assert folder == str(Path(r"D:\Cases") / "C01cv24001234")


# --- portal page state ----------------------------------------------------
#
# The signed-out case page is the failure that made the app look functional
# while doing nothing: it shows a "Sign In / Register" link, no password field,
# and sits on the "Please wait…" spinner. A check that treats that as signed-in
# parses an empty page and reports success.

class _FakePage:
    """Stands in for a Playwright page: `url` plus a scripted evaluate()."""

    def __init__(self, url, signals):
        self.url = url
        self._signals = signals

    async def evaluate(self, _js):
        return self._signals

    async def wait_for_timeout(self, _ms):
        return None


def _signals(**over):
    base = {"docButtons": 0, "rows": 0, "chars": 0, "spinner": False,
            "signInText": False, "signInLink": False, "hasDocketWord": False,
            "sample": ""}
    base.update(over)
    return base


def _state(page):
    import asyncio
    from mdec.portal import browser as br
    return asyncio.run(br.page_state(page))[0]


def test_signed_out_case_page_is_not_mistaken_for_signed_in():
    """The real regression, with the exact signals the live page produced:
    'Sign In / Register' text, the spinner, 459 characters, no rows."""
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/casesearch/"
                     "case-detail-page?caseId=C01cv24001234",
                     _signals(signInText=True, signInLink=True, spinner=True,
                              chars=459))
    assert _state(page) == br.SIGNED_OUT


def test_a_login_link_alone_does_not_override_a_loading_page():
    """Header login links exist on healthy pages — only the explicit
    'Sign In / Register' offer is decisive while the page is still loading."""
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/x",
                     _signals(spinner=True, signInLink=True))
    assert _state(page) == br.LOADING


def test_docket_content_means_ready():
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/x",
                     _signals(docButtons=950, rows=2885, hasDocketWord=True))
    assert _state(page) == br.READY


def test_docket_rows_without_buttons_still_count_as_ready():
    """A case with no downloadable documents is still a loaded docket."""
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/x",
                     _signals(rows=40, hasDocketWord=True))
    assert _state(page) == br.READY


def test_spinner_alone_is_loading_not_signed_out():
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/x",
                     _signals(spinner=True))
    assert _state(page) == br.LOADING


def test_sign_in_url_is_signed_out_without_reading_the_body():
    from mdec.portal import browser as br
    page = _FakePage("https://mdecportal.courts.state.md.us/MDEC/login.htm",
                     _signals(docButtons=99))
    assert _state(page) == br.SIGNED_OUT


def test_settled_page_with_nothing_recognizable_is_empty():
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/x",
                     _signals(chars=800))
    assert _state(page) == br.EMPTY


def test_stuck_spinner_resolves_to_signed_out():
    """A signed-in page resolves in seconds; an endless spinner means no session."""
    import asyncio
    from mdec.portal import browser as br
    page = _FakePage("https://casesearch.courts.state.md.us/x",
                     _signals(spinner=True))
    state, signals = asyncio.run(br.wait_for_case_page(page, timeout_ms=50))
    assert state == br.SIGNED_OUT
    assert "spinner" in signals.get("reason", "")


class _FakeFrame:
    def __init__(self, url, score, state=None):
        self.url = url
        self._score = score
        self._state = state

    async def evaluate(self, js):
        # The two scripts are told apart by what they return.
        if "btns * 10" in js:
            return self._score
        return self._state if self._state is not None else _signals()


def test_content_frame_picks_the_frame_holding_the_docket():
    """The portal renders in iframes; parsing only the top document finds
    nothing even when the docket is on screen."""
    import asyncio
    from mdec.portal import docket

    main = _FakeFrame("https://portal/case", 0)
    chrome = _FakeFrame("https://portal/nav", 2)
    content = _FakeFrame("https://portal/docket-grid", 9500)

    class P:
        main_frame = main
        frames = [main, chrome, content]

    assert asyncio.run(docket.content_frame(P())) is content


def test_content_frame_falls_back_to_the_main_frame():
    import asyncio
    from mdec.portal import docket

    main = _FakeFrame("https://portal/case", 120)

    class P:
        main_frame = main
        frames = [main]

    assert asyncio.run(docket.content_frame(P())) is main


def test_content_frame_survives_a_cross_origin_frame():
    import asyncio
    from mdec.portal import docket

    class Hostile(_FakeFrame):
        async def evaluate(self, js):
            raise RuntimeError("cross-origin frame access denied")

    main = _FakeFrame("https://portal/case", 5)
    bad = Hostile("https://ads.example/x", 0)

    class P:
        main_frame = main
        frames = [main, bad]

    assert asyncio.run(docket.content_frame(P())) is main


def test_docket_inside_an_iframe_is_seen_as_ready():
    """Regression guard: content in a child frame must not read as empty."""
    import asyncio
    from mdec.portal import browser as br

    main = _FakeFrame("https://portal/case", 0, _signals(chars=400))
    inner = _FakeFrame("https://portal/grid", 9000,
                       _signals(docButtons=900, rows=2800, hasDocketWord=True))

    class P:
        url = "https://casesearch.courts.state.md.us/casesearch/case-detail-page"
        main_frame = main
        frames = [main, inner]

        async def evaluate(self, js):
            return await main.evaluate(js)

    state, _ = asyncio.run(br.page_state(P()))
    assert state == br.READY


def test_bot_challenge_frame_is_reported_as_captcha():
    """The portal serves a DataDome challenge to the automated browser. The app
    must name that state, not mislabel it as 'empty' or try to get past it."""
    import asyncio
    from mdec.portal import browser as br

    main = _FakeFrame("https://casesearch.courts.state.md.us/x", 0,
                      _signals(chars=239))
    challenge = _FakeFrame(
        "https://geo.captcha-delivery.com/captcha/?initialCid=AHrlqAA", 0,
        _signals())

    class P:
        url = "https://casesearch.courts.state.md.us/casesearch/case-detail-page"
        main_frame = main
        frames = [main, challenge]

        async def evaluate(self, js):
            return await main.evaluate(js)

    state, signals = asyncio.run(br.page_state(P()))
    assert state == br.CAPTCHA
    assert "captcha-delivery.com" in signals["captchaUrl"]


def test_a_challenge_frame_does_not_block_an_already_loaded_docket():
    """If the docket rendered, a leftover challenge frame must not stop a run."""
    import asyncio
    from mdec.portal import browser as br

    main = _FakeFrame("https://casesearch.courts.state.md.us/x", 0,
                      _signals(docButtons=900, rows=2800, hasDocketWord=True))
    challenge = _FakeFrame("https://geo.captcha-delivery.com/captcha/", 0,
                           _signals())

    class P:
        url = "https://casesearch.courts.state.md.us/casesearch/case-detail-page"
        main_frame = main
        frames = [main, challenge]

        async def evaluate(self, js):
            return await main.evaluate(js)

    assert asyncio.run(br.page_state(P()))[0] == br.READY


def test_profile_lock_errors_are_recognized():
    from mdec.portal import browser as br
    assert br._is_profile_locked(
        Exception("Opening in existing browser session.")) is True
    assert br._is_profile_locked(
        Exception("profile is already in use by another instance")) is True
    assert br._is_profile_locked(Exception("net::ERR_CONNECTION_REFUSED")) is False


def test_desktop_picks_the_configured_port_when_free():
    from mdec import desktop
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    # the port closed with the `with` block, so it should be pickable
    assert desktop.pick_port("127.0.0.1", free) == free


def test_desktop_falls_back_when_the_port_is_taken():
    """An unrelated program on the default port must not make the app unstartable."""
    from mdec import desktop
    import socket
    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    taken = squatter.getsockname()[1]
    try:
        chosen = desktop.pick_port("127.0.0.1", taken)
        assert chosen is not None and chosen != taken
        assert chosen > taken
    finally:
        squatter.close()


def test_chromium_on_disk_detects_an_installed_browser(monkeypatch, dump):
    """The filesystem fallback keeps the app from claiming the browser is
    missing (and pushing a 130 MB download) when the driver won't start."""
    from mdec.portal import bootstrap
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(dump))
    assert bootstrap._chromium_on_disk() is False
    exe = dump / "chromium-1228" / "chrome-win" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert bootstrap._chromium_on_disk() is True


def test_chromium_on_disk_ignores_unrelated_folders(monkeypatch, dump):
    from mdec.portal import bootstrap
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(dump))
    (dump / "ffmpeg-1011").mkdir()
    (dump / "chromium_headless_shell-1228").mkdir()
    assert bootstrap._chromium_on_disk() is False


def test_missing_browser_markers_are_narrow():
    """'browsertype.launch' appears in nearly every Playwright launch error;
    matching it would misreport a crash as a missing download."""
    from mdec.portal import bootstrap
    real = Exception("Executable doesn't exist at C:\\...\\chrome.exe")
    assert bootstrap.looks_like_missing_browser(real) is True
    crash = Exception("BrowserType.launch: Target page, context or browser "
                      "has been closed")
    assert bootstrap.looks_like_missing_browser(crash) is False


def test_desktop_reports_a_dead_server_as_down():
    from mdec import desktop
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert desktop.server_is_up(f"http://127.0.0.1:{port}/", timeout=0.5) is False


def test_updating_a_case_folder_sticks(temp_db):
    db = temp_db
    cid = db.upsert_case("C-01-CV-24-001234", downloads="A:/old")
    db.update_case(cid, downloads="B:/new", monitor_enabled=0)
    case = db.get_case_by_id(cid)
    assert case["downloads"] == "B:/new" and case["monitor_enabled"] == 0
