"""The monitor: scheduled docket checks and the per-document pipeline.

A check, for one case:
  ensure logged in → parse docket → diff fingerprints → adopt files already on
  disk → download only what's still missing (paced) → catalog-rename → OCR →
  RAG export → AI analysis → record run.

Two properties worth knowing:

**Resumable.** Before downloading anything the app looks for a file on disk that
already satisfies the entry, and it separately tracks entries that *should* have
a document but don't (`doc_status`). An interrupted 950-document harvest picks up
where it stopped instead of starting over, and a rebuilt database re-adopts the
folder rather than re-downloading it.

**Single-flight.** Overlapping runs caused the "multiple async loops = chaos"
failure in the reference harvest, so one asyncio lock covers every case. A
scheduled check cannot overlap a manual one.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from . import config, db
from .pipeline import adopt, analyzer, ocr, rag_export, renamer
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
                if cfg["schedule"]["enabled"]:
                    now = datetime.now()
                    stamp = now.strftime("%Y-%m-%d %H:%M")
                    if now.strftime("%H:%M") in cfg["schedule"]["times"] \
                            and stamp not in self._fired:
                        self._fired.add(stamp)
                        await self.run_all_cases()
                if len(self._fired) > 100:
                    self._fired = set(list(self._fired)[-10:])
            except asyncio.CancelledError:
                raise
            except Exception as exc:                      # scheduler must survive
                self.status["message"] = f"scheduler error: {exc}"
            await asyncio.sleep(30)

    async def run_all_cases(self) -> dict:
        """Check every case with monitoring on, one at a time."""
        cases = [c for c in db.list_cases() if c["monitor_enabled"]]
        if not cases:
            return {"ok": False, "message": "No cases have monitoring enabled."}
        results = []
        for case in cases:
            results.append({"case": case["case_number"],
                            **await self.run_check("check", case["id"])})
        return {"ok": True, "results": results}

    # --- the check ---------------------------------------------------------

    async def run_check(self, kind: str = "manual",
                        case_id: int | None = None) -> dict:
        if self._lock.locked():
            return {"ok": False, "message": "A run is already in progress."}
        async with self._lock:
            self.status.update(busy=True, message=f"{kind}: starting")
            try:
                return await self._do_check(kind, case_id)
            finally:
                self.status.update(busy=False)
                self.status["last_check"] = db.now()

    def _resolve_case(self, case_id: int | None) -> dict | None:
        if case_id is not None:
            return db.get_case_by_id(case_id)
        number = config.load_config()["active_case_number"]
        return db.get_case(number) if number else None

    async def _do_check(self, kind: str, case_id: int | None) -> dict:
        cfg = config.load_config()
        case = self._resolve_case(case_id)
        if not case:
            self.status["message"] = "no case configured"
            return {"ok": False, "message": "No case selected. Add one in Settings."}

        case_number = case["case_number"]
        run_id = db.start_run(case["id"], kind)
        warnings: list[str] = []

        def log(line: str) -> None:
            db.append_run_log(run_id, line)
            self.status["message"] = f"{case_number}: {line}"

        try:
            folder = Path(case["downloads"] or
                          config.default_case_folder(case_number, cfg))

            log("Opening portal")
            await login.ensure_logged_in(cfg, case_number, log)
            page = await br.browser.page()

            log("Parsing docket")
            entries = await docket.parse_page(page)
            log(f"Parsed {len(entries)} entries")
            known = db.known_fingerprints(case["id"])
            new = docket.diff_new(entries, known)

            base = db.max_seq(case["id"])
            for i, e in enumerate(new):
                e["seq"] = base + 1 + i
                e["has_documents"] = e.get("button_index") is not None
                e["id"] = db.insert_entry(case["id"], e)
            if new:
                log(f"{len(new)} new docket entries")

            # Adopt anything already on disk before spending a download on it.
            adopted = adopt.adopt_folder(db, case["id"], folder)
            if adopted["adopted"]:
                log(f"Adopted {adopted['adopted']} file(s) already in the folder "
                    f"across {adopted['entries']} entries — not re-downloading")
            if adopted["orphan_count"]:
                warnings.append(
                    f"{adopted['orphan_count']} catalog-named file(s) in the "
                    f"folder have no matching docket entry (e.g. "
                    f"{', '.join(adopted['orphans'][:3])}). Left alone.")

            # Work list: new entries plus any earlier entry still missing a file.
            todo = db.entries_missing_documents(case["id"])
            by_button = {e["seq"]: e.get("button_index") for e in new}
            for e in todo:
                if e.get("button_index") is None:
                    e["button_index"] = by_button.get(e["seq"])

            fresh = [e for e in todo if e.get("button_index") is not None]
            stale = [e for e in todo if e.get("button_index") is None]
            if stale:
                # Known from an earlier run, but this page render didn't give us a
                # button for it — usually the entry scrolled out of the section we
                # parsed. Flag rather than guess at an index.
                warnings.append(
                    f"{len(stale)} entry(ies) are missing documents but no "
                    f"download button was found for them on this page "
                    f"(seq {', '.join(str(e['seq']) for e in stale[:5])}). "
                    f"They will be retried on the next check.")

            new_docs = 0
            if fresh:
                log(f"{len(fresh)} entry(ies) need documents")
                tmp = folder / ".incoming"
                dl_cfg = cfg["downloader"]

                async def reparse():
                    log("Session refresh hit — re-parsing page")
                    await docket.parse_page(page)   # re-tags data-mdec-idx

                async def progress(done, total, res):
                    log(f"Downloaded {done}/{total} "
                        f"(entry btn {res.button_index}: {res.status})")

                results = await downloader.download_many(
                    page, [e["button_index"] for e in fresh], tmp,
                    breathing_ms=dl_cfg["breathing_ms"],
                    batch_size=dl_cfg["batch_size"],
                    batch_pause_s=dl_cfg["batch_pause_s"],
                    on_progress=progress, reparse=reparse,
                )
                for entry, res in zip(fresh, results):
                    if res.status in ("view_only", "no_modal"):
                        db.set_entry_doc_status(entry["id"], "view_only")
                        warnings.append(f"#{entry['seq']:04d} {entry['name']}: "
                                        f"{res.status} (no file to download — "
                                        f"normal for view-only entries)")
                        continue
                    if res.status == "error" and not res.files:
                        db.set_entry_doc_status(entry["id"], "error")
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
                            entry["id"], f["title"], final.name,
                            str(final), f["sha256"], f["size"])
                        new_docs += 1
                        await self._post_process(cfg, case, entry, doc_id,
                                                 final, log, warnings)
                    db.set_entry_doc_status(
                        entry["id"], "error" if res.status == "error" else "ok")
                    if res.status == "error":
                        warnings.append(f"#{entry['seq']:04d}: partial — {res.error}")

            status = "warning" if warnings else "ok"
            db.finish_run(run_id, status, len(new), new_docs,
                          "\n".join(warnings) if warnings else "")
            log(f"Done: {len(new)} new entries, {new_docs} downloaded, "
                f"{adopted['adopted']} adopted")
            return {"ok": True, "new_entries": len(new), "new_documents": new_docs,
                    "adopted": adopted["adopted"], "warnings": warnings}

        except (br.NotLoggedIn, login.LoginFailed) as exc:
            db.finish_run(run_id, "warning", log=str(exc))
            self.status["message"] = str(exc)
            return {"ok": False, "message": str(exc)}
        except Exception as exc:
            db.finish_run(run_id, "error", log=f"{type(exc).__name__}: {exc}")
            self.status["message"] = f"error: {exc}"
            return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}

    # --- per-document pipeline ---------------------------------------------

    async def _post_process(self, cfg, case, entry, doc_id, pdf_path: Path,
                            log, warnings: list[str]) -> None:
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
                        cfg, case["case_number"], entry, doc, text))
                if targets:
                    db.update_document(doc_id, rag_exported=1)
                    log(f"RAG export ({', '.join(targets)}): {pdf_path.name}")
            except Exception as exc:
                warnings.append(f"RAG export failed for {pdf_path.name}: {exc}")

        if cfg["analysis"]["enabled"] and cfg["analysis"]["auto_analyze_new"]:
            await self.analyze_document(cfg, case, entry, doc_id,
                                        doc.get("title", ""), text,
                                        warnings, log)

    async def analyze_document(self, cfg, case, entry, doc_id, title,
                               text, warnings, log) -> None:
        try:
            result = await analyzer.analyze_document(cfg, case, entry,
                                                     title, text)
            db.add_analysis(case["id"], "document", result["model"],
                            result["summary"],
                            json.dumps(result["deadlines"]),
                            result["recommendations"],
                            entry_id=entry["id"], document_id=doc_id)
            log(f"Analyzed #{entry.get('seq', '?')}")
        except analyzer.AnalyzerNotConfigured as exc:
            warnings.append(str(exc))
        except Exception as exc:
            warnings.append(f"Analysis failed for entry "
                            f"#{entry.get('seq', '?')}: {exc}")

    # --- on-demand actions ---------------------------------------------------

    async def open_portal(self, case_id: int | None = None) -> str:
        """Open the visible portal window on the case page (attach-mode login)."""
        cfg = config.load_config()
        case = self._resolve_case(case_id)
        page = await br.browser.page()
        if case:
            ok = await br.goto_case(page, case["case_number"])
            return ("Portal window open — you appear to be signed in."
                    if ok else "Portal window open — please sign in. The session "
                               "will be remembered.")
        await page.goto(cfg["login"]["login_url"])
        return "Portal window open at the sign-in page."

    async def adopt_now(self, case_id: int | None = None) -> dict:
        """Link files already in the folder to docket entries, no downloading."""
        case = self._resolve_case(case_id)
        if not case:
            return {"ok": False, "message": "No case selected."}
        folder = Path(case["downloads"] or
                      config.default_case_folder(case["case_number"]))
        if not folder.is_dir():
            return {"ok": False, "message": f"Folder does not exist: {folder}"}
        entries = db.list_entries(case["id"])
        if not entries:
            return {"ok": False, "message":
                    "No docket entries recorded yet. Run a check first so the "
                    "app knows the sequence each file belongs to."}
        r = adopt.adopt_folder(db, case["id"], folder, entries)
        msg = (f"Adopted {r['adopted']} file(s) across {r['entries']} entries "
               f"from {r['files_seen']} catalog-named file(s) found.")
        if r["orphan_count"]:
            msg += (f" {r['orphan_count']} file(s) had no matching docket entry "
                    f"and were left alone.")
        if not r["adopted"] and r["files_seen"]:
            msg = (f"Nothing new to adopt — all {r['files_seen']} catalog-named "
                   f"file(s) are already recorded.")
        return {"ok": True, "message": msg, **r}

    async def analyze_entry_now(self, entry_id: int) -> dict:
        cfg = config.load_config()
        case = self._resolve_case(None)
        if not case:
            return {"ok": False, "message": "No case selected."}
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
            await self.analyze_document(cfg, case, entry, d["id"],
                                        d["title"], text, warnings,
                                        lambda s: None)
        return {"ok": not warnings, "message": "; ".join(warnings) or
                f"Analyzed {len(docs)} document(s)."}

    async def analyze_case_now(self) -> dict:
        cfg = config.load_config()
        case = self._resolve_case(None)
        if not case:
            return {"ok": False, "message": "No case selected."}
        entries = db.list_entries(case["id"])
        analyses = db.list_analyses(case["id"])
        try:
            text = await analyzer.analyze_case(cfg, case, entries, analyses)
        except analyzer.AnalyzerNotConfigured as exc:
            return {"ok": False, "message": str(exc)}
        db.add_analysis(case["id"], "case", cfg["analysis"]["model"],
                        text, "[]", "")
        return {"ok": True, "message": "Case briefing written."}


monitor = Monitor()
