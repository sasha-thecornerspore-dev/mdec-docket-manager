"""SQLite persistence. One DB at %APPDATA%\\MDECDocketManager\\mdec.db.

Schema notes:
- `entries.fingerprint` is the diff key: sha1(section|file_date|name|comment) plus
  an occurrence counter, because the same docket title can legitimately repeat
  hundreds of times (146x in the reference case).
- `runs` is the activity log every monitor check writes to; the UI reads it, so
  nothing fails silently.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY,
    case_number TEXT NOT NULL UNIQUE,
    caption TEXT DEFAULT '',
    court TEXT DEFAULT '',
    downloads TEXT DEFAULT '',
    monitor_enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    seq INTEGER NOT NULL,
    section TEXT DEFAULT '',
    file_date TEXT DEFAULT '',
    name TEXT DEFAULT '',
    comment TEXT DEFAULT '',
    raw_text TEXT DEFAULT '',
    fingerprint TEXT NOT NULL,
    has_documents INTEGER DEFAULT 0,
    doc_status TEXT DEFAULT 'pending',
    first_seen TEXT NOT NULL,
    UNIQUE(case_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    title TEXT DEFAULT '',
    filename TEXT DEFAULT '',
    path TEXT DEFAULT '',
    sha256 TEXT DEFAULT '',
    size_bytes INTEGER DEFAULT 0,
    downloaded_at TEXT NOT NULL,
    ocr_done INTEGER DEFAULT 0,
    rag_exported INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    entry_id INTEGER REFERENCES entries(id),
    document_id INTEGER REFERENCES documents(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    entry_id INTEGER REFERENCES entries(id),
    document_id INTEGER REFERENCES documents(id),
    kind TEXT NOT NULL,               -- 'document' | 'case'
    model TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    deadlines TEXT DEFAULT '[]',      -- JSON list of {date, description}
    recommendations TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    case_id INTEGER REFERENCES cases(id),
    kind TEXT NOT NULL,               -- 'check' | 'harvest' | 'manual'
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT DEFAULT 'running',    -- 'running' | 'ok' | 'error' | 'warning'
    new_entries INTEGER DEFAULT 0,
    new_documents INTEGER DEFAULT 0,
    log TEXT DEFAULT ''
);
"""


def db_path() -> Path:
    return config.app_dir() / "mdec.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Columns added after the first release. CREATE TABLE IF NOT EXISTS won't add
# them to an existing database, so they're applied by ALTER on every connect.
_ADDED_COLUMNS = (
    ("cases", "downloads", "TEXT DEFAULT ''"),
    ("cases", "monitor_enabled", "INTEGER DEFAULT 1"),
    ("entries", "doc_status", "TEXT DEFAULT 'pending'"),
)


def _migrate(c: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


@contextmanager
def conn():
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _migrate(c)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# --- cases -----------------------------------------------------------------

def upsert_case(case_number: str, caption: str = "", court: str = "",
                downloads: str = "") -> int:
    """Create or update a case. Empty strings leave existing values alone."""
    with conn() as c:
        cur = c.execute("SELECT id FROM cases WHERE case_number=?", (case_number,))
        row = cur.fetchone()
        if row:
            c.execute(
                "UPDATE cases SET caption=COALESCE(NULLIF(?,''),caption),"
                " court=COALESCE(NULLIF(?,''),court),"
                " downloads=COALESCE(NULLIF(?,''),downloads) WHERE id=?",
                (caption, court, downloads, row["id"]),
            )
            return row["id"]
        cur = c.execute(
            "INSERT INTO cases (case_number, caption, court, downloads, created_at)"
            " VALUES (?,?,?,?,?)",
            (case_number, caption, court, downloads, now()),
        )
        return cur.lastrowid


def get_case(case_number: str) -> dict | None:
    with conn() as c:
        cur = c.execute("SELECT * FROM cases WHERE case_number=?", (case_number,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_case_by_id(case_id: int) -> dict | None:
    with conn() as c:
        cur = c.execute("SELECT * FROM cases WHERE id=?", (case_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_cases() -> list[dict]:
    """Every tracked case with its counts, for the case switcher."""
    with conn() as c:
        cur = c.execute(
            "SELECT c.*, "
            " (SELECT COUNT(*) FROM entries e WHERE e.case_id=c.id) AS entry_count,"
            " (SELECT COUNT(*) FROM documents d JOIN entries e ON e.id=d.entry_id"
            "   WHERE e.case_id=c.id) AS doc_count "
            "FROM cases c ORDER BY c.case_number")
        return _rows(cur)


def update_case(case_id: int, **fields) -> None:
    allowed = {"caption", "court", "downloads", "monitor_enabled"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with conn() as c:
        q = ", ".join(f"{k}=?" for k in sets)
        c.execute(f"UPDATE cases SET {q} WHERE id=?", (*sets.values(), case_id))


def delete_case(case_id: int) -> None:
    """Forget a case and everything recorded about it. Files on disk stay."""
    with conn() as c:
        c.execute("DELETE FROM documents WHERE entry_id IN "
                  "(SELECT id FROM entries WHERE case_id=?)", (case_id,))
        c.execute("DELETE FROM notes WHERE case_id=?", (case_id,))
        c.execute("DELETE FROM analyses WHERE case_id=?", (case_id,))
        c.execute("DELETE FROM entries WHERE case_id=?", (case_id,))
        c.execute("DELETE FROM runs WHERE case_id=?", (case_id,))
        c.execute("DELETE FROM cases WHERE id=?", (case_id,))


# --- entries ---------------------------------------------------------------

def known_fingerprints(case_id: int) -> set[str]:
    with conn() as c:
        cur = c.execute("SELECT fingerprint FROM entries WHERE case_id=?", (case_id,))
        return {r["fingerprint"] for r in cur.fetchall()}


def insert_entry(case_id: int, e: dict) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO entries "
            "(case_id, seq, section, file_date, name, comment, raw_text,"
            " fingerprint, has_documents, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (case_id, e.get("seq", 0), e.get("section", ""), e.get("file_date", ""),
             e.get("name", ""), e.get("comment", ""), e.get("raw_text", ""),
             e["fingerprint"], int(bool(e.get("has_documents"))), now()),
        )
        if cur.lastrowid:
            return cur.lastrowid
        cur = c.execute(
            "SELECT id FROM entries WHERE case_id=? AND fingerprint=?",
            (case_id, e["fingerprint"]),
        )
        return cur.fetchone()["id"]


def list_entries(case_id: int) -> list[dict]:
    with conn() as c:
        cur = c.execute(
            "SELECT e.*, "
            " (SELECT COUNT(*) FROM documents d WHERE d.entry_id=e.id) AS doc_count,"
            " (SELECT COUNT(*) FROM notes n WHERE n.entry_id=e.id) AS note_count,"
            " (SELECT COUNT(*) FROM analyses a WHERE a.entry_id=e.id) AS analysis_count "
            "FROM entries e WHERE e.case_id=? ORDER BY e.seq", (case_id,),
        )
        return _rows(cur)


def set_entry_doc_status(entry_id: int, status: str) -> None:
    """'pending' | 'ok' | 'view_only' | 'error' — drives gap-filling."""
    with conn() as c:
        c.execute("UPDATE entries SET doc_status=? WHERE id=?", (status, entry_id))


def entries_missing_documents(case_id: int) -> list[dict]:
    """Entries that should have a file but don't yet — the resume work list.

    Excludes 'view_only' (the portal offers no download) so a check doesn't
    retry them forever, and 'ok' (already satisfied).
    """
    with conn() as c:
        cur = c.execute(
            "SELECT e.* FROM entries e WHERE e.case_id=? AND e.has_documents=1 "
            "AND COALESCE(e.doc_status,'pending') IN ('pending','error') "
            "AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.entry_id=e.id) "
            "ORDER BY e.seq", (case_id,))
        return _rows(cur)


# --- documents -------------------------------------------------------------

def insert_document(entry_id: int, title: str, filename: str, path: str,
                    sha256: str, size_bytes: int) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO documents (entry_id, title, filename, path, sha256,"
            " size_bytes, downloaded_at) VALUES (?,?,?,?,?,?,?)",
            (entry_id, title, filename, path, sha256, size_bytes, now()),
        )
        return cur.lastrowid


def update_document(doc_id: int, **fields) -> None:
    allowed = {"filename", "path", "ocr_done", "rag_exported", "sha256", "size_bytes"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with conn() as c:
        q = ", ".join(f"{k}=?" for k in sets)
        c.execute(f"UPDATE documents SET {q} WHERE id=?", (*sets.values(), doc_id))


def list_documents(case_id: int) -> list[dict]:
    with conn() as c:
        cur = c.execute(
            "SELECT d.*, e.seq, e.file_date, e.name AS entry_name FROM documents d "
            "JOIN entries e ON e.id=d.entry_id WHERE e.case_id=? ORDER BY e.seq, d.id",
            (case_id,),
        )
        return _rows(cur)


def get_document(doc_id: int) -> dict | None:
    with conn() as c:
        cur = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def known_paths(case_id: int) -> set[str]:
    """Absolute paths already recorded, so adopting a folder twice is a no-op."""
    with conn() as c:
        cur = c.execute(
            "SELECT d.path FROM documents d JOIN entries e ON e.id=d.entry_id "
            "WHERE e.case_id=?", (case_id,))
        return {str(r["path"]).lower() for r in cur.fetchall()}


def max_seq(case_id: int) -> int:
    with conn() as c:
        cur = c.execute("SELECT COALESCE(MAX(seq),0) AS m FROM entries WHERE case_id=?",
                        (case_id,))
        return cur.fetchone()["m"]


# --- notes -----------------------------------------------------------------

def add_note(case_id: int, body: str, entry_id: int | None = None,
             document_id: int | None = None) -> int:
    t = now()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO notes (case_id, entry_id, document_id, body, created_at,"
            " updated_at) VALUES (?,?,?,?,?,?)",
            (case_id, entry_id, document_id, body, t, t),
        )
        return cur.lastrowid


def update_note(note_id: int, body: str) -> None:
    with conn() as c:
        c.execute("UPDATE notes SET body=?, updated_at=? WHERE id=?",
                  (body, now(), note_id))


def delete_note(note_id: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM notes WHERE id=?", (note_id,))


def list_notes(case_id: int, entry_id: int | None = None) -> list[dict]:
    with conn() as c:
        if entry_id is not None:
            cur = c.execute(
                "SELECT * FROM notes WHERE case_id=? AND entry_id=? ORDER BY id DESC",
                (case_id, entry_id))
        else:
            cur = c.execute(
                "SELECT n.*, e.seq, e.name AS entry_name FROM notes n "
                "LEFT JOIN entries e ON e.id=n.entry_id "
                "WHERE n.case_id=? ORDER BY n.id DESC", (case_id,))
        return _rows(cur)


# --- analyses --------------------------------------------------------------

def add_analysis(case_id: int, kind: str, model: str, summary: str,
                 deadlines_json: str, recommendations: str,
                 entry_id: int | None = None, document_id: int | None = None) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO analyses (case_id, entry_id, document_id, kind, model,"
            " summary, deadlines, recommendations, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (case_id, entry_id, document_id, kind, model, summary, deadlines_json,
             recommendations, now()),
        )
        return cur.lastrowid


def list_analyses(case_id: int, entry_id: int | None = None) -> list[dict]:
    with conn() as c:
        if entry_id is not None:
            cur = c.execute(
                "SELECT * FROM analyses WHERE case_id=? AND entry_id=? ORDER BY id DESC",
                (case_id, entry_id))
        else:
            cur = c.execute(
                "SELECT a.*, e.seq, e.name AS entry_name FROM analyses a "
                "LEFT JOIN entries e ON e.id=a.entry_id "
                "WHERE a.case_id=? ORDER BY a.id DESC", (case_id,))
        return _rows(cur)


# --- runs ------------------------------------------------------------------

def start_run(case_id: int | None, kind: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO runs (case_id, kind, started_at) VALUES (?,?,?)",
            (case_id, kind, now()),
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, new_entries: int = 0,
               new_documents: int = 0, log: str = "") -> None:
    with conn() as c:
        c.execute(
            "UPDATE runs SET finished_at=?, status=?, new_entries=?,"
            " new_documents=?, log=? WHERE id=?",
            (now(), status, new_entries, new_documents, log, run_id),
        )


def append_run_log(run_id: int, line: str) -> None:
    with conn() as c:
        c.execute("UPDATE runs SET log = log || ? WHERE id=?", (line + "\n", run_id))


def list_runs(limit: int = 50) -> list[dict]:
    with conn() as c:
        cur = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        return _rows(cur)
