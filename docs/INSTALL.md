# Install

## Prerequisites

**Python 3.11 or newer** — the only thing you install yourself. Check with
`python --version`. If Windows opens the Microsoft Store instead, install from
[python.org](https://www.python.org/downloads/) and tick **"Add python.exe to
PATH"**; without that the installer can't find it.

**Edge or Chrome**, for the app window. Windows 11 ships Edge, so this is
normally already true.

**Portal access.** You need to be able to sign in to the Maryland Judiciary case
portal and see your case's documents. The app automates the browser you already
use; it cannot grant access you don't have.

## Install — the easy way (no Python needed)

Download **`MDEC-Docket-Manager-<version>-Setup.exe`** from
[Releases](https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases)
and run it.

It installs per-user under `%LOCALAPPDATA%\Programs`, so there is **no
administrator prompt**, and it creates Desktop and Start Menu shortcuts. Python
is bundled — you don't need it installed. Uninstall from Settings → Apps like
any other program.

On first run the app downloads the private Chromium it drives (~130 MB, once) —
the Dashboard has a **Download browser** button for it.

> Windows SmartScreen will warn about an unrecognized publisher, because the
> installer isn't code-signed (a certificate costs money). Choose **More info →
> Run anyway**, or use the source install below if you'd rather not.

There is also a `-portable.zip` of the same app if you prefer to unzip and run
`MDECDocketManager.exe` without installing.

## Install — from source

Better if you want OCR (excluded from the packaged build) or want to modify the
app. Needs Python 3.11+.

1. Download the latest `MDEC-Docket-Manager-<version>.zip` (the small one, not
   `-portable`) from Releases.
2. Unzip it wherever you want to keep it. The app runs from that folder — moving
   it later means running `Install.cmd` again to fix the shortcuts.
3. Double-click **`Install.cmd`** and follow it.

It installs the Python packages, downloads the private Chromium the app drives
(~130 MB, once), generates the icon, and creates Desktop and Start Menu
shortcuts. Nothing goes into system directories and nothing is sent anywhere.

Then open **MDEC Docket Manager** from your Desktop.

### From a git clone

Same thing — `Install.cmd` works in a clone and is still the easiest path:

```bash
git clone https://github.com/sasha-thecornerspore-dev/mdec-docket-manager.git
cd mdec-docket-manager
Install.cmd
```

Or by hand, if you'd rather not have shortcuts:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

### Running it from a terminal

| Command | Effect |
|---|---|
| `python run.py` | Serve and open the UI in your default browser |
| `python run.py --app` | Open the chromeless app window (what the icon does) |
| `python run.py --no-open` | Serve only; open <http://127.0.0.1:8674> yourself |
| `python run.py --port 8675` | Use a different port |

## How launching works

The Desktop icon runs `MDEC Docket Manager.pyw` through `pythonw.exe`, so there
is no console window. It starts the service, waits for it to answer, then opens
the UI as an Edge or Chrome **app window** — chromeless, its own taskbar button,
no address bar. That avoids depending on a GUI toolkit that would be one more
thing to install and go wrong.

Three behaviors worth knowing:

- **Closing the window leaves the service running**, so scheduled checks
  continue. Clicking the icon again reopens the window immediately.
- **Launching twice reuses the running service** — you can't accidentally start
  two monitors pointed at the same case.
- **If port 8674 is taken** the app moves to the next free port and records it in
  `%APPDATA%\MDECDocketManager\runtime.json`, so the icon still finds it.

To stop the service, use **Settings → Quit app**.

## The one-time browser download

The app drives its own private copy of Chromium, separate from your everyday
browser. `Install.cmd` downloads it (~130 MB). If that step was skipped or
failed — you were offline, say — the Dashboard shows **Browser installed ✗** and
a **Download browser** button that fetches it without needing a terminal.

Checks cannot run until it's present; the app says so plainly rather than
failing at the first click.

## Building a release zip

```bash
python tools/make_release.py
```

Writes `dist/MDEC-Docket-Manager-<version>.zip` containing the app, icon, docs,
and installer — no runtime data, no case data.

## Building the installer

Build from a virtual environment. The build refuses to run otherwise:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install pyinstaller
winget install JRSoftware.InnoSetup
.venv\Scripts\python tools/build_installer.py
```

PyInstaller bundles whatever it can import, so freezing from the interpreter on
PATH means the binary inherits everything ever `pip install`ed on that machine.
`require_clean_build_env()` in `tools/build_installer.py` refuses to freeze from
a non-venv interpreter, or from any environment where an AGPL package such as
PyMuPDF is importable — a licence that cannot ship inside a redistributed
binary. "Nothing imports it today" is not a control: one `hiddenimport`, or a
`--collect-all` added to the spec for an unrelated reason, would sweep it in
and no manifest in this repo would show it.

Creating the venv with the contaminated interpreter is fine — a venv does not
inherit user site-packages, so the offending package is not visible inside it.

Produces in `dist/`:

| File | What it is |
|---|---|
| `MDEC-Docket-Manager-<ver>-Setup.exe` | The installer. Per-user, no admin prompt. |
| `MDEC-Docket-Manager-<ver>-portable.zip` | The same app as a folder to unzip and run. |

`--skip-exe` reuses an existing PyInstaller build (much faster when you're only
iterating on the installer); `--no-installer` builds just the app.

### Two things the frozen build needs that source doesn't

Both are handled in `tools/frozen_entry.py`; they're recorded here because
neither failure is obvious when it happens.

**Playwright's browser path.** Frozen, Playwright resolves its browsers relative
to the bundled driver inside `_internal`, looks in the wrong place, and reports
Chromium as not downloaded even when it's installed. The entry point sets
`PLAYWRIGHT_BROWSERS_PATH` to the standard location (only when unset, so a
deliberate relocation still wins).

**No standard streams.** A windowed build has `sys.stdout is None`, so `print()`
and uvicorn's log handler raise `AttributeError` and the app dies with no visible
error. The entry point redirects the streams to the null device before importing
anything that logs, and writes any startup failure to
`%APPDATA%\MDECDocketManager\startup-error.log`.

### Deliberate exclusions

`torch`, `tensorflow`, `scipy`, `pandas` and friends get pulled in through
optional imports in unrelated packages and add hundreds of megabytes for
nothing — they're excluded in `tools/mdec.spec`. `ocrmypdf` is also excluded: it
drags in pikepdf and expects Ghostscript, and OCR is opt-in, so the packaged
build reports OCR as unavailable with a message pointing at the source install
rather than doubling the download.

## Where your data lives

Everything runtime is under `%APPDATA%\MDECDocketManager\`:

```
config.json      settings (never contains secrets or cases)
mdec.db          SQLite: docket, documents, notes, analyses, run log
.pw-profile\     the browser profile that holds your portal session
downloads\       default document folder (change it in Settings)
```

Nothing runtime is written into the repo, and `.gitignore` excludes PDFs,
databases, and config so case data can't be committed by accident.

## Optional: OCR

Needed only if some of your documents are scans with no text layer. Requires two
system tools plus the Python package:

```bash
python -m pip install ocrmypdf
```

**Tesseract** — install from
[UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki), or:

```powershell
winget install --id UB-Mannheim.TesseractOCR
```

**Ghostscript** — [ghostscript.com/releases](https://www.ghostscript.com/releases/gsdnld.html), or:

```powershell
winget install --id ArtifexSoftware.GhostScript
```

Both must be on `PATH` — open a new terminal and confirm `tesseract --version`
and `gs --version` both answer. Then turn OCR on in **Settings → OCR**. The
Dashboard's setup checklist tells you exactly what's still missing.

The app works fine without OCR; it just falls back to whatever text layer a PDF
already has (which most e-filed documents do have).

## Optional: Claude analysis

Pick one in **Settings → Claude analysis → Backend**.

### Your Claude subscription (no API key)

Install the Claude Code CLI and sign in once:

```bash
npm install -g @anthropic-ai/claude-code
claude          # sign in, then exit
```

The app calls `claude -p --output-format json` per document. Usage is billed
through your existing Claude plan. Confirm `claude` is found: the Dashboard
checklist will say `Claude analysis (cli)`.

### An Anthropic API key

Get a key from [platform.claude.com](https://platform.claude.com), then paste it
into **Settings → Claude analysis → Anthropic API key** and save. It goes
straight into Windows Credential Manager — the app never writes it to disk in
plain text and never shows it again.

Default model is `claude-opus-5`. Change it in Settings if you prefer a cheaper
one (`claude-sonnet-5`).

## Optional: RAG export

**Settings → RAG export.** Enable any combination:

- **Watched folder** — writes `<name>.txt` and `<name>.meta.json` per document.
  The simplest integration: point your RAG app's ingester at the folder.
- **Webhook** — POSTs `{case_number, entry, document, text, metadata}` to a URL
  you control.
- **ChromaDB** — upserts into a local collection. Needs `pip install chromadb`.

## Upgrading

From a release zip: unzip the new version over the old folder (or beside it and
re-run `Install.cmd` so the shortcuts point at the new one).

From a clone:

```bash
git pull
python -m pip install -r requirements.txt
```

The database migrates itself (the schema is created with `IF NOT EXISTS` on every
connection) and `config.json` merges against current defaults, so new settings
appear with sensible values and your existing ones are preserved.

## Uninstall

Run **`Uninstall.cmd`** — it removes the Desktop and Start Menu shortcuts and
touches nothing else.

To remove everything:

1. `Uninstall.cmd` (shortcuts)
2. Delete the app folder
3. Delete `%APPDATA%\MDECDocketManager\` (cases, notes, analyses, browser session)
4. Credentials: clear each secret field in Settings and save *before* deleting, or
   remove the `mdec-docket-manager` entries from Windows Credential Manager
   (Control Panel → Credential Manager → Windows Credentials)

Your downloaded court documents are in the folder you chose per case and are
never touched by any of this.
