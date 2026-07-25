# MDEC Docket Manager — Design Spec

**Date:** 2026-07-25
**Status:** Approved-by-default (autonomous session — user requested end-to-end build; decisions documented here for async review)

## Purpose

A local GUI application that monitors and maintains a complete docket for a Maryland
Judiciary (MDEC) case: detects new docket entries, downloads new documents, renames
them into the `NNNN_YYYYMMDD_Description.pdf` catalog convention, supports per-entry
notes, runs AI analysis + recommendations on new filings, optionally OCRs documents
and feeds them to an external RAG app, and can manage portal login (including
retrieving the emailed verification code) or work from a manually-logged-in session.

Built from the field-tested harvest method in the `mdec-docket-harvester` skill
(950-document reference run, case C-03-CV-24-003218). All seven "hard lessons" from
that run are baked into the downloader.

## Users & constraints

- Single user, party to the case with legitimate portal access, running on their own
  Windows machine. Credentials never leave the machine (Windows Credential Manager).
- The Maryland portal throttles aggressive automation (~475 rapid downloads triggers
  a session refresh). All automation is paced politely; monitoring checks run a few
  times per day, not continuously.
- AI analysis is **informational only, not legal advice** — stated in the UI and docs.

## Approaches considered

1. **PySide6 native desktop app** — real desktop feel, but slow to build/maintain,
   poor at rendering docket tables/PDFs compared to HTML.
2. **Electron/Tauri** — heavy toolchain; Node OCR story is weaker; user's prior
   tooling (rename script, field notes) is PowerShell/Python-adjacent.
3. **Python FastAPI backend + local web UI (no build step), opened in the browser
   (optionally wrapped in a pywebview native window)** — fastest to build, easiest
   to maintain, best table/PDF rendering, Playwright + ocrmypdf + anthropic are all
   first-class in Python. **← Chosen.**

## Architecture

```
run.py ── starts Uvicorn (127.0.0.1 only) ── serves mdec/server (FastAPI + static UI)
                                   │
        ┌──────────────────────────┼───────────────────────────┐
   mdec/portal                mdec/monitor                mdec/pipeline
   browser.py  ← Playwright   scheduler: check →          renamer.py  (catalog naming,
   login.py      persistent   diff → download →           manifest, occurrence-counted
   email_code.py context      pipeline → notify           repair mode for legacy folders)
   docket.py   (attach or                                 ocr.py      (ocrmypdf + sidecar)
   downloader.py managed)                                 rag_export.py (folder/webhook/chroma)
                                                          analyzer.py (Claude API)
                       mdec/db.py (SQLite) ── mdec/config.py (JSON in %APPDATA%, secrets in keyring)
```

### Components

**config.py** — settings JSON at `%APPDATA%\MDECDocketManager\config.json` (case id,
folders, schedule, login mode, OCR/RAG/analysis toggles). Secrets (portal password,
IMAP app password, Anthropic API key) go in Windows Credential Manager via `keyring`
under service `mdec-docket-manager`; the JSON stores only which secrets exist.

**db.py** — SQLite at `%APPDATA%\MDECDocketManager\mdec.db`. Tables: `cases`,
`entries` (docket entries w/ fingerprint), `documents`, `notes`, `analyses`, `runs`
(activity log). Entry fingerprint = `sha1(section|file_date|name|comment) + "#" +
occurrence-index` — robust to the same title repeating 146× and to entries being
appended anywhere.

**portal/browser.py** — one Playwright *persistent* Chromium context per install
(profile dir under %APPDATA%), headful. Two modes:
- *Attach mode:* app opens the portal window; the user logs in by hand; the
  persistent profile keeps the session for later runs. (Fallback the user asked for.)
- *Managed mode:* login.py fills username/password from keyring; when the portal
  emails a verification code, email_code.py polls IMAP (Gmail app password) for the
  newest code from a courts.state.md.us / mdcourts sender in the last 10 minutes,
  and login.py enters it. Selectors are config-overridable because the portal UI
  can change.

**portal/docket.py** — parses the case-detail page in-page (JS via
`page.evaluate`), returning every docket entry (file date, name, comment, section,
whether it has a Document/Documents button and that button's global index). Raw row
text is kept as a fallback field so parsing degrades gracefully if the DOM shifts.

**portal/downloader.py** — Playwright port of the harvester loop with every field
lesson intact: click ALL `[aria-label*="Download document"]` buttons in a modal
(multi-file popups), wait for `[role="dialog"]` to disappear before the next click,
300 ms breathing room per document, batch pacing, view-only entries logged not
errored, session-refresh spinner detected → wait → resume. Uses Playwright's
`expect_download` (no reliance on Chrome's download prompt). Monitoring mode
downloads only the buttons belonging to NEW fingerprints.

**pipeline/renamer.py** — names new files `NNNN_YYYYMMDD_Description.pdf` where
NNNN is the docket sequence. Because the app downloads each file knowing its entry,
naming is deterministic (no inference). Writes `_ORIGINAL_NAMES_manifest.csv` for
reversibility. Also includes the occurrence-counted *repair mode* (port of the
original PowerShell logic, incl. dry-run) for renaming a legacy dump folder.

**pipeline/ocr.py** — `ocrmypdf --skip-text` producing text-layer PDF + sidecar
`.txt`; falls back to `pdfplumber` text extraction when a text layer already
exists. Requires Tesseract + Ghostscript (documented; runtime check with a clear
error, feature is optional).

**pipeline/rag_export.py** — pluggable exporters, any combination: (a) export
folder of `.txt` + `.json` metadata (watched-folder ingestion), (b) HTTP POST
webhook `{case_id, entry, document, text, metadata}`, (c) ChromaDB collection
(optional dependency). Configured in Settings.

**pipeline/analyzer.py** — Claude API (`claude-sonnet-5` default, configurable).
Per-document analysis: what the filing is, procedural posture, deadlines/dates
detected, suggested next steps ("recommendations"), stored in `analyses` and shown
on the entry. Case-level "state of the case" synthesis on demand. Every output is
labeled *informational, not legal advice*.

**monitor.py** — async scheduler inside the server process. Default: checks at
08:00 and 17:00 local (configurable cron-ish times + manual "Check now"). A check:
open portal → verify logged in (else notify/attempt managed login) → parse docket →
diff fingerprints → download new docs (paced) → rename → OCR → RAG export →
analyze → record run + surface notifications in the UI.

**server/** — FastAPI on `127.0.0.1:8674`. REST endpoints for case setup, docket
list, documents, notes CRUD, analyses, runs, settings, secrets (write-only —
values go straight to keyring, never echoed back), actions (check-now, full
harvest, repair-rename, analyze). Static UI: vanilla HTML/JS/CSS tabs — Dashboard,
Docket, Documents, Notes, Analysis, Activity, Settings. No frontend build step.

## Error handling

- Every run is recorded in `runs` with a status + log; failures surface as UI
  notifications, never silent.
- Portal DOM drift: parser keeps raw text; selector overrides in config; downloader
  verifies files landed on disk (count + non-zero size) before recording them —
  the "early checkpoint" lesson, automated.
- Missing optional deps (Tesseract, chromadb, pywebview) → feature disabled with a
  clear message, app still runs.
- Downloads that don't land are retried once, then flagged in the run log.

## Testing

Pure-logic modules get pytest coverage that runs with stdlib only: fingerprint/diff
logic, renamer (incl. occurrence-counted repair on synthetic duplicate sets),
email-code extraction, db CRUD. Portal automation is exercised against fixture HTML
for the parser; live-portal behavior is documented as a manual walkthrough.

## Security posture

- Server binds 127.0.0.1 only. Secrets only in Windows Credential Manager;
  config.json and the DB contain no secrets; `.gitignore` excludes all runtime data.
- Repo contains no case-specific data. Pushed to GitHub as a **private** repo
  (user can flip visibility; chosen private because the project is tied to a
  personal legal matter).

## Out of scope (YAGNI)

Multi-user, cloud hosting, e-filing/submitting anything to the court, scraping
cases the user has no access to, mobile app, auto-update.

## Decisions the user may want to revisit

1. Local web GUI (browser tab / optional pywebview window) instead of a native
   desktop toolkit.
2. Private GitHub repo.
3. Default check schedule 2×/day (deliberately polite to the portal).
4. Default analysis model `claude-sonnet-5`.
