# Architecture

## Shape

A FastAPI process serving a JSON API plus a static vanilla-JS UI, driving a
Playwright browser, persisting to SQLite. One process, one user, localhost only,
no build step.

```
run.py ──► uvicorn on 127.0.0.1:8674 ──► mdec/server/app.py (API + static UI)
                                             │
        ┌────────────────────────────────────┼───────────────────────────────┐
        ▼                                    ▼                               ▼
  mdec/portal/                        mdec/monitor.py                 mdec/pipeline/
  browser.py   persistent Chromium    scheduler + the check:          renamer.py   catalog naming
  login.py     attach / managed       ensure login → parse →          ocr.py       text + OCR
  email_code.py IMAP code reader        diff → download → rename      rag_export.py folder/webhook/chroma
  docket.py    in-page parser           → OCR → RAG → analyze         analyzer.py  Claude (API or CLI)
  downloader.py paced download loop      → record run
        │                                    │                               │
        └──────────► mdec/db.py (SQLite) ◄────┴───── mdec/config.py ──────────┘
                                                   (JSON + Credential Manager)
```

Why this shape: HTML renders the dense docket tables far better than a native
toolkit would, Playwright/ocrmypdf/anthropic are all first-class in Python, and
skipping a frontend build means the UI is editable with a text editor forever.

## Modules

### `config.py`
Settings JSON at `%APPDATA%\MDECDocketManager\config.json`, merged against
`DEFAULTS` on every load so a new release's settings appear with sane values and
existing ones survive.

Secrets never enter the JSON. Three named slots — `portal_password`,
`imap_password`, `anthropic_api_key` — go to Windows Credential Manager via
`keyring` under service `mdec-docket-manager`. `save_config()` defensively strips
those keys from any dict handed to it, and `secret_status()` returns booleans
only. Any other slot name raises.

`normalize_case_id()` turns `C-03-CV-24-003218` into the portal's `C03cv24003218`.

### `db.py`
SQLite at `%APPDATA%\MDECDocketManager\mdec.db`. The schema runs with
`IF NOT EXISTS` on every connection, which is the whole migration story.

| Table | Holds |
|---|---|
| `cases` | case number, caption, court |
| `entries` | docket entries: `seq`, section, file date, name, comment, `raw_text`, `fingerprint`, `has_documents`, `first_seen`. Unique on `(case_id, fingerprint)` |
| `documents` | per file: title, filename, path, `sha256`, size, `ocr_done`, `rag_exported` |
| `notes` | body + optional `entry_id` / `document_id` |
| `analyses` | `kind` (`document`/`case`), model, summary, `deadlines` JSON, recommendations |
| `runs` | the activity log: kind, status, counts, log text |

### `portal/docket.py`
Parses the case page. Parsing runs **inside the page** via `page.evaluate` — the
accessibility tree blows past 50k characters on this page (the reference case had
~1,944 `<article>` and ~2,885 row elements), so JS is the only reliable route.

Two jobs beyond extraction:

**Button tagging.** Every `<button>` whose text is exactly `Document` or
`Documents` gets `data-mdec-idx="N"`. The downloader then targets buttons by that
attribute rather than by list position, so a re-render can't shift its aim.

**Graceful degradation.** Field extraction is heuristic (labeled fields first,
then positional fallback), and each entry keeps `raw_text`. A DOM change
downgrades field quality instead of dropping entries. Any `Document` button not
matched to a recognized row still becomes an entry.

**Fingerprints** are the diff key:

```
sha1(section | file_date | name | comment)[:16] + "#" + occurrence_index
```

The occurrence index is what makes this safe. A title can legitimately repeat
hundreds of times (146× in the reference case). Hashing content alone would
collapse them; adding the ordinal means going from 3 copies to 5 yields exactly
the two new ones. `fingerprint()` returns copies rather than mutating its input,
so an aliased dict can't silently collapse every occurrence onto one value.

### `portal/browser.py`
One persistent Chromium context per install, profile under `%APPDATA%`, always
headful. Persistence is what makes attach-mode login survive restarts. Module
singleton — one visible window for the whole app.

### `portal/login.py`
`ensure_logged_in()` navigates to the case page and checks whether we look signed
in. *Attach mode* raises `NotLoggedIn` with instructions. *Managed mode* fills
credentials from Credential Manager, and if the portal asks for an emailed code,
polls IMAP for it. Every selector is config-overridable, so a portal redesign is
a settings edit rather than a code change.

### `portal/email_code.py`
Blocking `imap-tools` reader, run in a thread executor. Scans the newest 25
messages, stops at the age cutoff, only considers allowed senders, extracts the
first regex match. Read-only: never sends, deletes, or marks read.

### `portal/downloader.py`
The heart of it, and the part shaped entirely by the reference run's failures:

- **Pacing** — 300 ms after each document, batches of 10 with a pause between.
  Faster tripped a session refresh around the 475th rapid download.
- **Multi-file modals** — clicks *every* `[aria-label*="Download document"]` in
  the dialog. One popup in the reference case held 14 files.
- **Close/next race** — waits for `[role="dialog"]` to disappear before touching
  the next button, or the next modal gets mistaken for the old one.
- **View-only entries** — a dialog with no download button is logged, not an
  error.
- **Throttle recovery** — detects the "Please wait. Do not select refresh…"
  spinner, raises `SessionRefresh`, waits ~20 s, re-parses (re-tagging buttons),
  and resumes. It is not a logout.
- **Landing verification** — a download only counts once the file exists on disk
  with non-zero size, and its SHA-256 is recorded. This is the manual "early
  checkpoint" from the field notes, automated per file.

Playwright's `expect_download` replaces Chrome's download bar, so the old
"allow multiple downloads?" prompt doesn't arise.

### `pipeline/renamer.py`
Two modes.

`place_download()` names files the app just fetched. Deterministic — the
downloader knows the entry, so no inference: `NNNN_YYYYMMDD_Description.pdf`,
with `_1ofN` for multi-file entries and `XXXXXXXX` for unknown dates.

`repair_folder()` renames a legacy dump. Sort by creation time (= download order
= docket order), strip the `" (n)"` suffix to get the stem, map the *N*th
physical copy of a stem to the *N*th docket slot expecting it. Reports
`unmatched` (extra files) and `missing` (empty slots) rather than forcing a
match, because a mislabeled court document is worse than an unlabeled one.

Both append to `_ORIGINAL_NAMES_manifest.csv`, and a collision produces `~2`
rather than an overwrite.

### `pipeline/ocr.py`
Text layer first via `pdfplumber`; if under 200 characters and OCR is enabled,
`ocrmypdf --skip-text` adds a layer in place (written to a temp file, then
atomically replaced) plus a `.txt` sidecar. `available()` reports precisely
which system tool is missing so the UI can explain instead of failing.

### `pipeline/rag_export.py`
Three independent exporters — folder, webhook, ChromaDB — each enabled
separately. Returns the list that succeeded; a failure raises for the caller to
log per-document.

### `pipeline/analyzer.py`
Claude, two backends behind one interface:

- **API** — the `anthropic` SDK. Opts into server-side refusal fallback so a
  safety decline retries on the recommended model instead of failing the run,
  and degrades to a plain call on older SDKs.
- **CLI** — `claude -p --output-format json --model <id>`, prompt over
  **stdin** (Windows command lines cap near 32k characters; document text is far
  larger), reply read from the JSON envelope's `result`. The model string is
  validated against `[A-Za-z0-9._-]+` before it reaches a command line.

`resolve_backend()` centralizes the choice and raises `AnalyzerNotConfigured`
with the exact fix, which the UI surfaces verbatim.

### `monitor.py`
The scheduler and the check. Runs are **single-flight** behind an `asyncio.Lock`
— overlapping loops were the reference run's "multiple async loops = chaos"
failure, and this makes it structurally impossible. The scheduler survives its
own exceptions; every run writes to `runs` with warnings collected per document,
so a partial failure is visible rather than silent.

### `server/app.py`
FastAPI. `/api/*` first, static UI mounted at `/` last. Settings PATCH-merge so
the UI can send a subtree. `POST /api/secrets` is write-only — an empty value
deletes the slot — and no endpoint returns a secret value.

### `server/static/`
`index.html` + `app.css` + `app.js`, no framework, no build. The visual idea is a
clerk's docket ledger as a precise instrument: a left sequence spine where new
filings get a red notch and a rotated **New** stamp, since "what changed" is the
app's whole job. Type is Windows-resident by design — Bahnschrift (DIN condensed)
for labels, Constantia for prose, Cascadia Mono for data — so the UI never
requests a font from the network. Red is reserved for two meanings only: new
filings and deadlines.

`md()` renders a small markdown subset and escapes input first (there's a test
asserting injected HTML can't execute).

## Data flow: one check

```
scheduler / "Check now"
   │
   ├─ single-flight lock ─────────► already running? return
   ├─ db.start_run()
   ├─ login.ensure_logged_in()  ──► NotLoggedIn → run status 'warning', tell the user
   ├─ docket.parse_page()       ──► entries + fingerprints, buttons tagged
   ├─ docket.diff_new()         ──► only unseen fingerprints
   │     └─ nothing new? finish 'ok', done
   ├─ assign seq = max_seq + 1…, db.insert_entry()
   ├─ downloader.download_many()──► paced; throttle → wait, re-parse, resume
   │     per file: verify on disk → renamer.place_download() → db.insert_document()
   │               → ocr.get_text() → rag_export.export_document()
   │               → analyzer.analyze_document() → db.add_analysis()
   └─ db.finish_run(status, counts, warnings)
```

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Counts, monitor state, feature readiness, recent runs |
| GET | `/api/entries` | Docket entries with their documents |
| GET | `/api/documents` | All documents |
| GET | `/api/documents/{id}/file` | The PDF |
| GET | `/api/documents/{id}/text` | Extracted text (OCRs on demand if enabled) |
| GET/POST | `/api/notes` | List / create |
| PUT/DELETE | `/api/notes/{id}` | Update / delete |
| GET | `/api/analyses` | Analyses, optionally `?entry_id=` |
| GET | `/api/runs` | Activity log |
| GET/POST | `/api/settings` | Read / merge-write settings |
| POST | `/api/secrets` | Write-only secret slot |
| POST | `/api/actions/open-portal` | Open the browser window |
| POST | `/api/actions/check-now` | Run a check |
| POST | `/api/actions/analyze-entry/{id}` | Analyze one entry |
| POST | `/api/actions/analyze-case` | Case briefing |
| POST | `/api/actions/repair-rename` | Legacy folder rename (`dry_run` flag) |
| POST | `/api/actions/close-browser` | Close the browser |

## Testing

`tests/test_core.py` covers the logic where a bug would be silent and
consequential: fingerprint/diff (including the aliasing hazard and the
repeated-title case), catalog naming, the occurrence-counted repair in all four
outcomes, verification-code extraction, the DB layer, and two safety assertions —
that saving settings can't write a secret to disk, and that unknown secret slots
are rejected. No network, no browser, no API key.

Portal automation is verified by hand against the live site; the walkthrough is
the manual test plan.

## Deliberately out of scope

Multi-user, cloud hosting, e-filing or submitting anything to the court, any case
you don't have access to, mobile, auto-update.
