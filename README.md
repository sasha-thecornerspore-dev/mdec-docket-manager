# MDEC Docket Manager

A local desktop app that watches a Maryland Judiciary (MDEC) case docket, keeps a
complete and correctly-named document archive, and helps you understand each new
filing as it lands.

Built for a party to their own case who needs to track it closely. It runs
entirely on your machine: the web server binds to `127.0.0.1`, credentials live
in Windows Credential Manager, and nothing about your case leaves your computer
except the API calls you explicitly enable.

> **Not legal advice.** The analysis features summarize filings and suggest
> things to look into. They are informational only. Verify every date and
> deadline against the docket and the filings themselves, and talk to a lawyer
> about anything consequential.

---

## What it does

| | |
|---|---|
| **Monitors** | Checks the docket on a schedule (default 08:00 and 17:00) and on demand. Detects new entries by fingerprint, so a title that repeats 146 times still diffs correctly. |
| **Handles many cases** | Track as many as you like, each with its own folder, docket, notes, and analyses. Switch from the top bar; scheduled checks walk every monitored case in turn. |
| **Downloads** | Pulls every document from new entries, including multi-file popups. Paced to stay under the portal's throttle. |
| **Never starts over** | Every check first adopts files already on disk, then downloads only what's genuinely missing. An interrupted 950-document harvest resumes where it stopped; a rebuilt database re-adopts the folder instead of re-fetching it. |
| **Names** | Files land as `NNNN_YYYYMMDD_Description.pdf` where `NNNN` is the docket sequence. Naming is deterministic — the app knows which entry each file came from. |
| **Repairs** | Renames a legacy dump folder into the same catalog using occurrence-counted matching, with a dry run and a reversible manifest. |
| **Notes** | Per-entry and case-level notes, kept alongside the docket. |
| **Analyzes** | Claude summarizes each new filing, extracts dates and deadlines, and suggests next steps. Works with an **API key or your Claude subscription**. |
| **OCR** | Optional: adds a text layer to scanned PDFs and writes a `.txt` sidecar. |
| **Feeds your RAG app** | Optional: exports document text to a watched folder, an HTTP webhook, and/or a local ChromaDB collection. |
| **Logs everything** | Every check is recorded with its warnings. Nothing fails silently. |

## Screens

Seven tabs: **Dashboard** (counts, setup checklist, document folder, recent
activity), **Docket** (the ledger — new filings are stamped and notched in the
sequence spine), **Documents** (file table), **Notes**, **Analysis**,
**Activity** (run log), **Settings** (cases and everything else).

## Quick start

```bash
git clone https://github.com/<you>/mdec-docket-manager.git
cd mdec-docket-manager
python -m pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

The UI opens at <http://127.0.0.1:8674>. Then:

1. **Settings → Cases** — add your case number (e.g. `C-01-CV-24-001234`) and
   pick a document folder with **Browse…**. Add as many cases as you track.
2. **Open portal window** — a browser window opens on your case page. Sign in
   yourself. The session is remembered for later runs.
3. **Check now** — the app reads the docket, adopts anything already in the
   folder, downloads the rest, names it, and records the run.

That's the whole loop. Everything else — automated login, OCR, RAG export,
analysis — is optional and off by default.

**Already have the PDFs?** Point the case's folder at them. If they follow the
`NNNN_YYYYMMDD_…` convention the app adopts them instead of re-downloading; if
they're named the old `Title-caseid (2).pdf` way, run the repair rename first.

For the full first-run walkthrough see **[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)**.

## Documentation

| Document | What's in it |
|---|---|
| **[docs/INSTALL.md](docs/INSTALL.md)** | Prerequisites, install, optional features, upgrading |
| **[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)** | Step-by-step first run, plus a walkthrough per feature |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Module map, data flow, database schema, API reference |
| **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | Every failure mode we know about and what to do |
| **[docs/FIELD_NOTES.md](docs/FIELD_NOTES.md)** | The 950-document run this was built from, and the seven lessons that shaped the downloader |
| **[docs/SECURITY.md](docs/SECURITY.md)** | Where credentials live, what leaves your machine, threat model |

## Two ways to run Claude analysis

Set **Settings → Claude analysis → Backend**:

- **Claude subscription** — shells out to the Claude Code CLI in non-interactive
  mode. No API key; you just need `claude` installed and signed in. Billed
  through your existing Pro/Max plan.
- **Anthropic API key** — uses the `anthropic` SDK directly. Key is stored in
  Windows Credential Manager.
- **Auto** (default) — uses the API key if one is stored, otherwise the CLI.

## Being a good citizen of the portal

The Maryland portal throttles aggressive automation. This app is deliberately
polite: two scheduled checks a day, 300 ms between documents, small batches with
pauses, and automatic backoff when the portal returns its session-refresh
spinner. Those defaults were tuned during a 950-document run — see the field
notes. Please don't crank them up.

Use this only for a case you have lawful access to.

## Requirements

- Windows 10/11 (the app is cross-platform Python, but credential storage and
  the default paths assume Windows)
- Python 3.11+
- Playwright's Chromium (`python -m playwright install chromium`)
- Optional, for OCR: Tesseract and Ghostscript
- Optional, for subscription analysis: the Claude Code CLI, signed in

## Tests

```bash
python -m pytest tests -q
```

44 tests cover the diffing logic, catalog naming, the occurrence-counted repair
rename, adopting files already on disk, resume/gap tracking, case isolation,
verification-code extraction, and the database layer. They need no network, no
browser, and no API key.

## License

MIT — see [LICENSE](LICENSE).
