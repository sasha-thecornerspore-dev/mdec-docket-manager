# Install

## Prerequisites

**Python 3.11 or newer.** Check with `python --version`. If Windows opens the
Microsoft Store instead, install from [python.org](https://www.python.org/downloads/)
and tick "Add python.exe to PATH".

**Portal access.** You need to be able to sign in to the Maryland Judiciary case
portal and see your case's documents. The app automates the browser you already
use; it cannot grant access you don't have.

## Core install

```bash
git clone https://github.com/<you>/mdec-docket-manager.git
cd mdec-docket-manager
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`playwright install chromium` downloads a private copy of Chromium (~130 MB).
This is separate from your everyday Chrome and keeps its own logged-in profile
under `%APPDATA%\MDECDocketManager\.pw-profile`.

Start it:

```bash
python run.py
```

| Flag | Effect |
|---|---|
| *(none)* | Serve and open the UI in your default browser |
| `--window` | Open in a native desktop window (needs `pip install pywebview`) |
| `--no-open` | Serve only; open <http://127.0.0.1:8674> yourself |
| `--port N` | Use a different port |

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

## Optional: native window

```bash
python -m pip install pywebview
python run.py --window
```

## Upgrading

```bash
git pull
python -m pip install -r requirements.txt
```

The database migrates itself (the schema is created with `IF NOT EXISTS` on every
connection) and `config.json` merges against current defaults, so new settings
appear with sensible values and your existing ones are preserved.

## Uninstall

Delete the repo folder, then delete `%APPDATA%\MDECDocketManager\`. To remove
stored credentials, clear each secret field in Settings and save before deleting,
or remove the `mdec-docket-manager` entries from Windows Credential Manager
(Control Panel → Credential Manager → Windows Credentials).
