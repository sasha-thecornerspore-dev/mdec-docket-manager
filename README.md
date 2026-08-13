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

## Install

Download **`MDEC-Docket-Manager-<version>-Setup.exe`** from
[Releases](https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases)
and run it. **No Python needed** — it's bundled. Installs per-user, so no
administrator prompt, and puts a **MDEC Docket Manager** icon on your Desktop and
in the Start Menu.

From then on it's just the icon. No terminal, no console window.

> SmartScreen will warn about an unrecognized publisher — the installer isn't
> code-signed. **More info → Run anyway**, or install from source instead.

On first run, click **Download browser** on the Dashboard to fetch the private
Chromium the app drives (~130 MB, once).

<details>
<summary>Install from source instead (needed for OCR)</summary>

Download the small `MDEC-Docket-Manager-<version>.zip` from Releases, unzip, and
double-click `Install.cmd`. Needs [Python 3.11+](https://www.python.org/downloads/)
with *"Add python.exe to PATH"* ticked.

Or from a clone:

```bash
git clone https://github.com/sasha-thecornerspore-dev/mdec-docket-manager.git
cd mdec-docket-manager
python -m pip install -r requirements.txt
python -m playwright install chromium
python run.py            # or: python run.py --app   for the app window
```

The source install starts faster (~3 s vs ~12 s) and is the only way to get OCR.
</details>

## First run

Open the app from its icon, then:

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

## How the app behaves

**Closing the window doesn't quit it.** The service keeps running so scheduled
checks still happen — that's the point of monitoring. Clicking the icon again
brings the window back instantly. To actually stop it, use **Settings → Quit
app**.

**One instance, whatever you click.** Launching twice reuses the running service
instead of starting a second monitor.

**It finds a free port.** If something else is using 8674 it moves to the next
one available and remembers where it went.

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

## Read this before you rely on the automatic downloading

As of August 2026 the Maryland portal ("Case Portal 1.1") sits behind **DataDome
bot detection**. It serves a "Verification Required" challenge to the automated
browser instead of the case page, citing *automated activity* and *use of
developer or inspection tools* — Playwright drives Chromium over the DevTools
protocol, which is exactly what that fingerprints.

**This is detection by signature, not by volume.** Pacing does not avoid it, and
a handful of page loads is enough to be flagged.

The app detects the challenge, names it, and stops. It does **not** answer it,
and it deliberately contains no fingerprint spoofing or other evasion — that is
the thing the check exists to prevent. If you see the challenge, complete it
yourself in your normal browser; the flag is per-connection and usually clears.

**Scheduled checks ship disabled** for this reason. Turn them on only after a
manual check has actually read your docket.

### What still works regardless

Everything that doesn't touch the portal, which is most of the value on a large
case file: **Adopt files** you downloaded yourself, catalog naming, the
occurrence-counted repair of a legacy folder, per-entry notes, OCR, Claude
analysis, and RAG export. Fetch the documents by hand, point a case at the
folder, and the app takes it from there.

Use **"Why did my check find nothing?"** on the Dashboard to see which state
you're in: bot challenge, not signed in, or a portal markup change.

## Being a good citizen of the portal

The Maryland portal throttles aggressive automation. This app is deliberately
polite: two scheduled checks a day, 300 ms between documents, small batches with
pauses, and automatic backoff when the portal returns its session-refresh
spinner. Those defaults were tuned during a 950-document run — see the field
notes. Please don't crank them up.

Use this only for a case you have lawful access to.

## Requirements

- Windows 10/11 (the app is cross-platform Python, but credential storage, the
  installer, and the default paths assume Windows)
- Python 3.11+ — the one thing you install yourself
- Edge or Chrome, for the app window (Windows 11 has Edge already)
- Everything else `Install.cmd` handles: Python packages and Playwright's Chromium
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
