"""The monitor: scheduled docket checks and the full processing pipeline.

A check:
  ensure logged in → parse docket → diff fingerprints → download new documents
  (paced) → catalog-rename → OCR → RAG export → AI analysis → record run.

Runs are single-flight (an asyncio lock) — overlapping checks caused the
"multiple async loops = chaos" failure in the reference run, so it is
structurally impossible here. Every run writes to the `runs` table; the UI
surfaces failures, nothing is silent.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from . import config, db
from .pipeline import analyzer, ocr, rag_export, renamer
from .portal import browser as br
from .portal import docket, downloader, login


class Monitor:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sched_task: asyncio.Task | None = None
        self._fired: set[str] = set()          # "YYYY-MM-DD HH:MM" already run
        self.status: dict = {"busy": False, "message": "idle", "last_check": None}

    # --- scheduling --------------------------------------------------------

    def start_scheduler(self) -> None:
        if not self._sched_task:
            self._sched_task = asyncio.create_task(self._scheduler())

    async def stop(self) -> None:
        if self._sched_task:
            self._sched_task.cancel()
            self._sched_task = None
        await br.browser.stop()

    async def _scheduler(self) -> None:
        while True:
            try:
                cfg = config.load_config()
                if cfg["schedule"]["enabled"] and cfg["case"]["case_number"]:
                    now = datetime.now()
                    stamp = now.strftime("%Y-%m-%d %H:%M")
                    if now.strftime("%H:%M") in cfg["schedule"]["times"] \
                            and stamp not in self._fired:
                        self._fired.add(stamp)
                        await self.run_check("check")
                if len(self._fired) > 100:
                    self._fired = set(list(self._fired)[-10:])
            except asyncio.CancelledError:
                raise
            except Exception as exc:                      # scheduler must survive
                self.status["message"] = f"scheduler error: {exc}"
            await asyncio.sleep(30)

    # --- the check ---------------------------------------------------------

    async def run_check(self, kind: str = "manual") -> dict:
        if self._lock.locked():
            return {"ok": False, "message": "A run is already in progress."}
        async with self._lock:
            self.status.update(busy=True, message=f"{kind}: starting")
            try:
                return await self._do_check(kind)
            finally:
                self.status.update(busy=False)
                self.status["last_check"] = db.now()

    async def _do_check(self, kind: str) -> dict:
        cfg = config.load_config()
        case_number = cfg["case"]["case_number"]
        if not case_number:
            self.status["message"] = "no case configured"
            return {"ok": False, "message": "No case configured in Settings."}

        case_id = db.upsert_case(case_number, cfg["case"]["caption"],
                                 cfg["case"]["court"])
        run_id = db.start_run(case_id, kind)
        warnings: list[str] = []

        def log(line: str) -> None:
            db.append_run_log(run_id, line)
            self.status["message"] = f"{kind}: {line}"

        try:
            log("Opening portal")
            await login.ensure_logged_in(cfg, log)
            page = await br.browser.page()

            log("Parsing docket")
            entries = await docket.parse_page(page)
            log(f"Parsed {len(entries)} entries")
            known = db.known_fingerprints(case_id)
            new = docket.diff_new(entries, known)
            if not new:
                log("No new docket entries")
                db.finish_run(run_id, "ok")
                return {"ok": True, "new_entries": 0, "new_documents": 0}

            log(f"{len(new)} new entries")
            base = db.max_seq(case_id)
            for i, e in enumerate(new):
                e["seq"] = base + 1 + i
                e["has_documents"] = e.get("button_index") is not None
                e["db_id"] = db.insert_entry(case_id, e)

            to_dl = [e for e in new if e.get("button_index") is not None]
            new_docs = 0
            if to_dl:
                folder = Path(cfg["folders"]["downloads"] or
                              (config.app_dir() / "downloads"))
                tmp = folder / ".incoming"
                dl_cfg = cfg["downloader"]

                async def reparse():
                    log("Session refresh hit — re-parsing page")
                    await docket.parse_page(page)   # re-tags data-mdec-idx

                async def progress(done, total, res):
                    log(f"Downloaded {done}/{total} "
                        f"(entry btn {res.button_index}: {res.status})")

                results = await downloader.download_many(
                    page, [e["button_index"] for e in to_dl], tmp,
                    breathing_ms=dl_cfg["breathing_ms"],
                    batch_size=dl_cfg["batch_size"],
                    batch_pause_s=dl_cfg["batch_pause_s"],
                    on_progress=progress, reparse=reparse,
                )
                for entry, res in zip(to_dl, results):
                    if res.status in ("view_only", "no_modal"):
                        warnings.append(f"#{entry['seq']:04d} {entry['name']}: "
                                        f"{res.status} (no file — normal for "
                                        f"view-only entries)")
                        continue
                    if res.status == "error" and not res.files:
                        warnings.append(f"#{entry['seq']:04d} {entry['name']}: "
                                        f"download failed — {res.error}")
                        continue
                    total = len(res.files)
                    for j, f in enumerate(res.files):
                        desc = f["title"] or entry["name"] or "Document"
                        final = renamer.place_download(
                            Path(f["path"]), folder, entry["seq"],
                            entry.get("file_date", ""), desc,
                            part=(j + 1) if total > 1 else None,
                            total_parts=total,
                            original_name=f.get("suggested_filename", ""),
                        )
                        doc_id = db.insert_document(
                            entry["db_id"], f["title"], final.name,
                            str(final), f["sha256"], f["size"])
                        new_docs += 1
                        await self._post_process(cfg, case_number, case_id,
                                                 entry, doc_id, final,
                                                 log, warnings)
                    if res.status == "error":
                        warnings.append(f"#{entry['seq']:04d}: partial — {res.error}")

            status = "warning" if warnings else "ok"
            db.finish_run(run_id, status, len(new), new_docs,
                          "\n".join(warnings) if warnings else "")
            log(f"Done: {len(new)} new entries, {new_docs} new documents")
            return {"ok": True, "new_entries": len(new), "new_documents": new_docs,
                    "warnings": warnings}

        except (br.NotLoggedIn, login.LoginFailed) as exc:
            db.finish_run(run_id, "warning", log=str(exc))
            self.status["message"] = str(exc)
            return {"ok": False, "message": str(exc)}
        except Exception as exc:
            db.finish_run(run_id, "error", log=f"{type(exc).__name__}: {exc}")
            self.status["message"] = f"error: {exc}"
            return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}

    # --- per-document pipeline ---------------------------------------------

    async def _post_process(self, cfg, case_number, case_id, entry, doc_id,
                            pdf_path: Path, log, warnings: list[str]) -> None:
        loop = asyncio.get_running_loop()
        text = ""
        try:
            text, ocr_ran = await loop.run_in_executor(
                None, lambda: ocr.get_text(pdf_path, cfg["ocr"]["enabled"],
                                           cfg["ocr"]["language"]))
            if ocr_ran:
                db.update_document(doc_id, ocr_done=1)
        except Exception as exc:
            warnings.append(f"OCR/text extraction failed for {pdf_path.name}: {exc}")

        doc = db.get_document(doc_id) or {}
        if text:
            try:
                targets = await loop.run_in_executor(
                    None, lambda: rag_export.export_document(
                        cfg, case_number, entry, doc, text))
                if targets:
                    db.update_document(doc_id, rag_exported=1)
                    log(f"RAG export ({', '.join(targets)}): {pdf_path.name}")
            except Exception as exc:
                warnings.append(f"RAG export failed for {pdf_path.name}: {exc}")

        if cfg["analysis"]["enabled"] and cfg["analysis"]["auto_analyze_new"]:
            await self.analyze_document(cfg, case_id, entry, doc_id,
                                        doc.get("title", ""), text,
                                        warnings, log)

    async def analyze_document(self, cfg, case_id, entry, doc_id, title,
                               text, warnings, log) -> None:
        try:
            case = {"case_number": cfg["case"]["case_number"],
                    "caption": cfg["case"]["caption"]}
            result = await analyzer.analyze_document(cfg, case, entry,
                                                     title, text)
            db.add_analysis(case_id, "document", result["model"],
                            result["summary"],
                            json.dumps(result["deadlines"]),
                            result["recommendations"],
                            entry_id=entry.get("db_id") or entry.get("id"),
                            document_id=doc_id)
            log(f"Analyzed #{entry.get('seq', '?')}")
        except analyzer.AnalyzerNotConfigured as exc:
            warnings.append(str(exc))
        except Exception as exc:
            warnings.append(f"Analysis failed for entry "
                            f"#{entry.get('seq', '?')}: {exc}")

    # --- on-demand actions ---------------------------------------------------

    async def open_portal(self) -> str:
        """Open the visible portal window on the case page (attach-mode login)."""
        cfg = config.load_config()
        page = await br.browser.page()
        if cfg["case"]["case_number"]:
            ok = await br.goto_case(page, cfg["case"]["case_number"])
            return ("Portal window open — you appear to be logged in." if ok else
                    "Portal window open — please log in; the session will be "
                    "remembered.")
        await page.goto(cfg["login"]["login_url"])
        return "Portal window open at the login page."

    async def analyze_entry_now(self, entry_id: int) -> dict:
        cfg = config.load_config()
        case_number = cfg["case"]["case_number"]
        case = db.get_case(case_number)
        if not case:
            return {"ok": False, "message": "No case in database yet."}
        entries = {e["id"]: e for e in db.list_entries(case["id"])}
        entry = entries.get(entry_id)
        if not entry:
            return {"ok": False, "message": f"Entry {entry_id} not found."}
        docs = [d for d in db.list_documents(case["id"])
                if d["entry_id"] == entry_id]
        if not docs:
            return {"ok": False, "message": "Entry has no downloaded documents."}
        warnings: list[str] = []
        loop = asyncio.get_running_loop()
        for d in docs:
            text, _ = await loop.run_in_executor(
                None, lambda d=d: ocr.get_text(Path(d["path"]),
                                               cfg["ocr"]["enabled"],
                                               cfg["ocr"]["language"]))
            await self.analyze_document(cfg, case["id"], entry, d["id"],
                                        d["title"], text, warnings,
                                        lambda s: None)
        return {"ok": not warnings, "message": "; ".join(warnings) or
                f"Analyzed {len(docs)} document(s)."}

    async def analyze_case_now(self) -> dict:
        cfg = config.load_config()
        case = db.get_case(cfg["case"]["case_number"])
        if not case:
            return {"ok": False, "message": "No case in database yet."}
        entries = db.list_entries(case["id"])
        analyses = db.list_analyses(case["id"])
        try:
            text = await analyzer.analyze_case(cfg, case, entries, analyses)
        except analyzer.AnalyzerNotConfigured as exc:
            return {"ok": False, "message": str(exc)}
        db.add_analysis(case["id"], "case", cfg["analysis"]["model"],
                        text, "[]", "")
        return {"ok": True, "message": "Case analysis complete."}


monitor = Monitor()
