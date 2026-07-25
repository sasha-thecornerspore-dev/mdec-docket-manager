"""FastAPI app: JSON API for the UI + static file serving.

Binds to 127.0.0.1 only (see run.py). Secrets are write-only: POST /api/secrets
sends values straight to Windows Credential Manager, and no endpoint ever
returns a secret value — only booleans saying which slots are set.
"""

from __future__ import annotations

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

app = FastAPI(title="MDEC Docket Manager", version=__version__)


@app.on_event("startup")
async def _startup() -> None:
    monitor.start_scheduler()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await monitor.stop()


def _case_row() -> dict:
    cfg = config.load_config()
    number = cfg["case"]["case_number"]
    if not number:
        raise HTTPException(400, "No case configured. Open Settings first.")
    case = db.get_case(number)
    if not case:
        case = {"id": db.upsert_case(number, cfg["case"]["caption"],
                                    cfg["case"]["court"]),
                "case_number": number}
    return case


# --- status / dashboard ----------------------------------------------------

@app.get("/api/status")
async def api_status():
    cfg = config.load_config()
    number = cfg["case"]["case_number"]
    case = db.get_case(number) if number else None
    entries = db.list_entries(case["id"]) if case else []
    docs = db.list_documents(case["id"]) if case else []
    ocr_ok, ocr_why = ocr.available()
    try:
        backend, _ = analyzer.resolve_backend(cfg)
        analysis_backend, analysis_why = backend, ""
    except analyzer.AnalyzerNotConfigured as exc:
        analysis_backend, analysis_why = "none", str(exc)
    return {
        "version": __version__,
        "case": cfg["case"],
        "case_url": config.case_url(number) if number else "",
        "counts": {
            "entries": len(entries),
            "documents": len(docs),
            "ocr_done": sum(1 for d in docs if d["ocr_done"]),
            "rag_exported": sum(1 for d in docs if d["rag_exported"]),
            "notes": len(db.list_notes(case["id"])) if case else 0,
            "analyses": len(db.list_analyses(case["id"])) if case else 0,
        },
        "monitor": monitor.status,
        "schedule": cfg["schedule"],
        "login_mode": cfg["login"]["mode"],
        "browser_running": br.browser.running,
        "features": {
            "ocr_enabled": cfg["ocr"]["enabled"],
            "ocr_available": ocr_ok,
            "ocr_why": ocr_why,
            "analysis_enabled": cfg["analysis"]["enabled"],
            "analysis_backend": analysis_backend,
            "analysis_why": analysis_why,
            "rag_targets": [k for k in ("folder", "webhook", "chroma")
                            if cfg["rag"].get(f"{k}_enabled")],
        },
        "runs": db.list_runs(5),
    }


# --- docket / documents ----------------------------------------------------

@app.get("/api/entries")
async def api_entries():
    case = _case_row()
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
    return {"documents": db.list_documents(_case_row()["id"])}


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
    return {"notes": db.list_notes(_case_row()["id"], entry_id)}


@app.post("/api/notes")
async def api_add_note(note: NoteIn):
    if not note.body.strip():
        raise HTTPException(400, "Note body is empty.")
    nid = db.add_note(_case_row()["id"], note.body, note.entry_id,
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
    rows = db.list_analyses(_case_row()["id"], entry_id)
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
    if cfg["case"]["case_number"]:
        db.upsert_case(cfg["case"]["case_number"], cfg["case"]["caption"],
                       cfg["case"]["court"])
    return {"ok": True, "settings": config.load_config()}


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
async def api_check_now():
    return await monitor.run_check("manual")


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


class RepairIn(BaseModel):
    folder: str
    dry_run: bool = True


@app.post("/api/actions/repair-rename")
async def api_repair_rename(payload: RepairIn):
    """Occurrence-counted rename of a legacy dump folder against this docket."""
    case = _case_row()
    cfg = config.load_config()
    folder = Path(payload.folder)
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
        folder, config.normalize_case_id(cfg["case"]["case_number"]),
        index, dry_run=payload.dry_run)
    return {"ok": True, "dry_run": payload.dry_run, "actions": actions,
            "summary": {
                "rename": sum(1 for a in actions if a["status"] == "rename"),
                "unmatched": sum(1 for a in actions if a["status"] == "unmatched"),
                "missing": sum(1 for a in actions if a["status"] == "missing"),
            }}


# --- static UI (mounted last so /api/* wins) -------------------------------

app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
