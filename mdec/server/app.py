"""FastAPI app: JSON API for the UI + static file serving.

Binds to 127.0.0.1 only (see run.py). Secrets are write-only: POST /api/secrets
sends values straight to Windows Credential Manager, and no endpoint ever
returns a secret value — only booleans saying which slots are set.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__, config, db
from ..monitor import monitor
from ..pipeline import analyzer, ocr, renamer
from ..portal import browser as br

STATIC = Path(__file__).parent / "static"
ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"

app = FastAPI(title="MDEC Docket Manager", version=__version__)


@app.on_event("startup")
async def _startup() -> None:
    # Adopt a pre-multi-case config into the cases table, once.
    pending = config.consume_case_migration()
    if pending:
        db.upsert_case(pending["case_number"], pending.get("caption", ""),
                       pending.get("court", ""), pending.get("downloads", ""))
    monitor.start_scheduler()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await monitor.stop()


def _active_case() -> dict:
    """The case the UI is looking at. 400s with an actionable message if none."""
    number = config.load_config()["active_case_number"]
    case = db.get_case(number) if number else None
    if case:
        return case
    cases = db.list_cases()
    if cases:                       # config drifted — fall back to the first case
        _set_active(cases[0]["case_number"])
        return cases[0]
    raise HTTPException(400, "No case yet. Add one in Settings → Cases.")


def _set_active(case_number: str) -> None:
    cfg = config.load_config()
    cfg["active_case_number"] = case_number
    config.save_config(cfg)


def _case_folder(case: dict) -> Path:
    return Path(case.get("downloads") or
                config.default_case_folder(case["case_number"]))


# --- readiness -------------------------------------------------------------

@app.get("/api/ping")
async def api_ping():
    """Cheapest possible liveness check. The desktop launcher polls this to know
    when to open the window — it must not touch keyring, OCR, or the database,
    or the window waits on feature detection instead of on the server."""
    return {"ok": True, "version": __version__}


# --- status / dashboard ----------------------------------------------------

@app.get("/api/status")
async def api_status():
    cfg = config.load_config()
    cases = db.list_cases()
    number = cfg["active_case_number"]
    case = db.get_case(number) if number else None
    if not case and cases:
        case = cases[0]
        _set_active(case["case_number"])
    entries = db.list_entries(case["id"]) if case else []
    docs = db.list_documents(case["id"]) if case else []
    folder = _case_folder(case) if case else None
    return {
        "version": __version__,
        "cases": cases,
        "case": case or {},
        "case_folder": str(folder) if folder else "",
        "case_folder_exists": bool(folder and folder.is_dir()),
        "case_url": config.case_url(number) if number else "",
        "counts": {
            "entries": len(entries),
            "documents": len(docs),
            "missing": len(db.entries_missing_documents(case["id"])) if case else 0,
            "ocr_done": sum(1 for d in docs if d["ocr_done"]),
            "rag_exported": sum(1 for d in docs if d["rag_exported"]),
            "notes": len(db.list_notes(case["id"])) if case else 0,
            "analyses": len(db.list_analyses(case["id"])) if case else 0,
        },
        "monitor": monitor.status,
        "schedule": cfg["schedule"],
        "login_mode": cfg["login"]["mode"],
        "browser_running": br.browser.running,
        "runs": db.list_runs(5),
    }


@app.get("/api/features")
async def api_features():
    """Feature readiness, split out of /api/status because detecting it imports
    keyring and probes PATH — seconds on a cold process. The UI paints the
    dashboard from /api/status first, then fills the checklist from here."""
    cfg = config.load_config()
    ocr_ok, ocr_why = ocr.available()
    try:
        backend, _ = analyzer.resolve_backend(cfg)
        analysis_backend, analysis_why = backend, ""
    except analyzer.AnalyzerNotConfigured as exc:
        analysis_backend, analysis_why = "none", str(exc)
    return {
        "ocr_enabled": cfg["ocr"]["enabled"],
        "ocr_available": ocr_ok,
        "ocr_why": ocr_why,
        "analysis_enabled": cfg["analysis"]["enabled"],
        "analysis_backend": analysis_backend,
        "analysis_why": analysis_why,
        "rag_targets": [k for k in ("folder", "webhook", "chroma")
                        if cfg["rag"].get(f"{k}_enabled")],
    }


# --- docket / documents ----------------------------------------------------

@app.get("/api/entries")
async def api_entries():
    case = _active_case()
    entries = db.list_entries(case["id"])
    docs = db.list_documents(case["id"])
    by_entry: dict[int, list] = {}
    for d in docs:
        by_entry.setdefault(d["entry_id"], []).append(d)
    for e in entries:
        e["documents"] = by_entry.get(e["id"], [])
    return {"entries": entries}


@app.get("/api/documents")
async def api_documents():
    return {"documents": db.list_documents(_active_case()["id"])}


@app.get("/api/documents/{doc_id}/file")
async def api_document_file(doc_id: int):
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "No such document.")
    p = Path(doc["path"])
    if not p.exists():
        raise HTTPException(404, f"File missing on disk: {p}")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@app.get("/api/documents/{doc_id}/text")
async def api_document_text(doc_id: int):
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "No such document.")
    cfg = config.load_config()
    text, ran = ocr.get_text(Path(doc["path"]), cfg["ocr"]["enabled"],
                             cfg["ocr"]["language"])
    if ran:
        db.update_document(doc_id, ocr_done=1)
    return {"text": text, "ocr_ran": ran}


# --- notes -----------------------------------------------------------------

class NoteIn(BaseModel):
    body: str
    entry_id: int | None = None
    document_id: int | None = None


@app.get("/api/notes")
async def api_notes(entry_id: int | None = None):
    return {"notes": db.list_notes(_active_case()["id"], entry_id)}


@app.post("/api/notes")
async def api_add_note(note: NoteIn):
    if not note.body.strip():
        raise HTTPException(400, "Note body is empty.")
    nid = db.add_note(_active_case()["id"], note.body, note.entry_id,
                      note.document_id)
    return {"ok": True, "id": nid}


@app.put("/api/notes/{note_id}")
async def api_update_note(note_id: int, note: NoteIn):
    db.update_note(note_id, note.body)
    return {"ok": True}


@app.delete("/api/notes/{note_id}")
async def api_delete_note(note_id: int):
    db.delete_note(note_id)
    return {"ok": True}


# --- analyses --------------------------------------------------------------

@app.get("/api/analyses")
async def api_analyses(entry_id: int | None = None):
    rows = db.list_analyses(_active_case()["id"], entry_id)
    for r in rows:
        try:
            r["deadlines"] = json.loads(r["deadlines"] or "[]")
        except json.JSONDecodeError:
            r["deadlines"] = []
    return {"analyses": rows}


# --- runs / activity -------------------------------------------------------

@app.get("/api/runs")
async def api_runs(limit: int = 50):
    return {"runs": db.list_runs(limit)}


# --- settings & secrets ----------------------------------------------------

@app.get("/api/settings")
async def api_get_settings():
    return {"settings": config.load_config(), "secrets": config.secret_status()}


@app.post("/api/settings")
async def api_save_settings(payload: dict):
    cfg = config.load_config()

    def merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                merge(dst[k], v)
            elif k in dst:
                dst[k] = v

    merge(cfg, payload)
    config.save_config(cfg)
    return {"ok": True, "settings": config.load_config()}


# --- cases -----------------------------------------------------------------

class CaseIn(BaseModel):
    case_number: str
    caption: str = ""
    court: str = ""
    downloads: str = ""
    monitor_enabled: bool = True


@app.get("/api/cases")
async def api_list_cases():
    cases = db.list_cases()
    for c in cases:
        c["resolved_folder"] = str(_case_folder(c))
    return {"cases": cases,
            "active": config.load_config()["active_case_number"]}


@app.post("/api/cases")
async def api_add_case(c: CaseIn):
    number = c.case_number.strip()
    if not config.normalize_case_id(number):
        raise HTTPException(400, "Enter a case number, e.g. C-01-CV-24-001234.")
    if db.get_case(number):
        raise HTTPException(400, f"{number} is already being tracked.")
    folder = c.downloads.strip() or config.default_case_folder(number)
    case_id = db.upsert_case(number, c.caption.strip(), c.court.strip(), folder)
    db.update_case(case_id, monitor_enabled=int(c.monitor_enabled))
    _set_active(number)             # a freshly added case becomes the active one
    return {"ok": True, "id": case_id, "folder": folder}


@app.put("/api/cases/{case_id}")
async def api_update_case(case_id: int, c: CaseIn):
    if not db.get_case_by_id(case_id):
        raise HTTPException(404, "No such case.")
    db.update_case(case_id, caption=c.caption.strip(), court=c.court.strip(),
                   downloads=c.downloads.strip(),
                   monitor_enabled=int(c.monitor_enabled))
    return {"ok": True}


@app.post("/api/cases/{case_id}/activate")
async def api_activate_case(case_id: int):
    case = db.get_case_by_id(case_id)
    if not case:
        raise HTTPException(404, "No such case.")
    _set_active(case["case_number"])
    return {"ok": True, "case": case}


@app.delete("/api/cases/{case_id}")
async def api_delete_case(case_id: int):
    """Forget a case. Downloaded files are never touched."""
    case = db.get_case_by_id(case_id)
    if not case:
        raise HTTPException(404, "No such case.")
    db.delete_case(case_id)
    remaining = db.list_cases()
    _set_active(remaining[0]["case_number"] if remaining else "")
    return {"ok": True, "message":
            f"Stopped tracking {case['case_number']}. Files in "
            f"{case.get('downloads') or 'its folder'} were left alone."}


class SecretIn(BaseModel):
    name: str
    value: str


@app.post("/api/secrets")
async def api_set_secret(s: SecretIn):
    """Write-only. Empty value deletes the slot. Values are never read back."""
    try:
        if s.value == "":
            config.delete_secret(s.name)
        else:
            config.set_secret(s.name, s.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "secrets": config.secret_status()}


# --- actions ---------------------------------------------------------------

@app.post("/api/actions/open-portal")
async def api_open_portal():
    try:
        return {"ok": True, "message": await monitor.open_portal()}
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"{type(exc).__name__}: {exc}"},
                            status_code=500)


@app.post("/api/actions/check-now")
async def api_check_now(case_id: int | None = None):
    return await monitor.run_check("manual", case_id)


@app.post("/api/actions/check-all")
async def api_check_all():
    return await monitor.run_all_cases()


@app.post("/api/actions/adopt")
async def api_adopt(case_id: int | None = None):
    """Link files already in the folder to docket entries instead of
    re-downloading them."""
    return await monitor.adopt_now(case_id)


@app.post("/api/actions/pick-folder")
async def api_pick_folder(payload: dict | None = None):
    """Open the OS folder picker. Server and browser are the same machine, so
    this is the only way a web UI can offer a real directory chooser."""
    initial = (payload or {}).get("initial") or ""
    try:
        path = await asyncio.get_running_loop().run_in_executor(
            None, _ask_directory, initial)
    except Exception as exc:
        raise HTTPException(500, f"Could not open the folder picker ({exc}). "
                                 f"Type the path instead.")
    return {"ok": True, "path": path or ""}


def _ask_directory(initial: str) -> str:
    """Blocking native directory dialog via tkinter (stdlib)."""
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        return filedialog.askdirectory(
            title="Choose the folder for this case's documents",
            initialdir=initial or str(Path.home()), mustexist=False) or ""
    finally:
        root.destroy()


@app.post("/api/actions/analyze-entry/{entry_id}")
async def api_analyze_entry(entry_id: int):
    return await monitor.analyze_entry_now(entry_id)


@app.post("/api/actions/analyze-case")
async def api_analyze_case():
    return await monitor.analyze_case_now()


@app.post("/api/actions/close-browser")
async def api_close_browser():
    await br.browser.stop()
    return {"ok": True, "message": "Browser closed."}


@app.post("/api/actions/quit")
async def api_quit():
    """Stop the service. Closing the app window leaves it running on purpose
    (scheduled checks need it), so this is the way to actually shut down."""
    if monitor.status.get("busy"):
        return {"ok": False, "message":
                "A check is running. Wait for it to finish before quitting — "
                "stopping mid-download leaves the run incomplete."}
    asyncio.get_running_loop().call_later(0.3, _hard_exit)
    return {"ok": True, "message": "Shutting down. You can close this window."}


def _hard_exit() -> None:
    import os
    import signal
    # Terminating skips atexit on Windows, so clear the runtime marker here or
    # the next launch reads a port nothing is listening on.
    try:
        (config.app_dir() / "runtime.json").unlink(missing_ok=True)
    except OSError:
        pass
    os.kill(os.getpid(), signal.SIGTERM)


# --- icon ------------------------------------------------------------------

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Also what Edge/Chrome use for the app window's taskbar icon."""
    ico = ASSETS / "mdec.ico"
    if not ico.is_file():
        raise HTTPException(404, "Icon not generated. Run tools/make_icon.py.")
    return FileResponse(ico, media_type="image/x-icon")


class RepairIn(BaseModel):
    folder: str = ""
    dry_run: bool = True


@app.post("/api/actions/repair-rename")
async def api_repair_rename(payload: RepairIn):
    """Occurrence-counted rename of a legacy dump folder against this docket."""
    case = _active_case()
    folder = Path(payload.folder) if payload.folder.strip() else _case_folder(case)
    if not folder.is_dir():
        raise HTTPException(400, f"Not a folder: {folder}")
    by_entry: dict[int, list] = {}
    for d in db.list_documents(case["id"]):
        by_entry.setdefault(d["entry_id"], []).append(d)
    index = []
    for e in db.list_entries(case["id"]):
        docs = by_entry.get(e["id"], [])
        for d in docs:
            index.append({"seq": e["seq"], "file_date": e["file_date"],
                          "title": d["title"] or e["name"]})
        if not docs and e["has_documents"]:
            index.append({"seq": e["seq"], "file_date": e["file_date"],
                          "title": e["name"]})
    if not index:
        raise HTTPException(400, "No docket index yet — run a check first so the "
                                 "app knows the entry order.")
    actions = renamer.repair_folder(
        folder, config.normalize_case_id(case["case_number"]),
        index, dry_run=payload.dry_run)
    return {"ok": True, "dry_run": payload.dry_run, "folder": str(folder),
            "actions": actions,
            "summary": {
                "rename": sum(1 for a in actions if a["status"] == "rename"),
                "unmatched": sum(1 for a in actions if a["status"] == "unmatched"),
                "missing": sum(1 for a in actions if a["status"] == "missing"),
            }}


# --- static UI (mounted last so /api/* wins) -------------------------------

app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
