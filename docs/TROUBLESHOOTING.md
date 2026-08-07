# Troubleshooting

**Start with the Activity tab.** Every check writes a run record with its status
and a per-step log. `warning` means it finished but skipped something; `error`
means it stopped. The log names the specific entry or document.

---

## Launching the app

### Nothing happens when I click the icon
Give it about three seconds on a cold start — there's no splash screen. If
nothing appears after ten:

1. Look for an error dialog behind other windows; the launcher reports failures
   that way since it has no console.
2. Open a terminal in the app folder and run `python run.py`. The same failure
   will print with a full traceback.

Most often it's missing packages — re-run `Install.cmd`.

### The icon does nothing but a background process is running
The service is up but the window didn't open, which means neither Edge nor Chrome
was found. Open <http://127.0.0.1:8674> in any browser; the app works fine there.
Installing Edge or Chrome restores the app window.

### `Install.cmd` says Python was not found
Python isn't on `PATH`. Reinstall from
[python.org](https://www.python.org/downloads/) with **"Add python.exe to PATH"**
ticked, then run `Install.cmd` again. Installing from the Microsoft Store often
doesn't set `PATH` usefully.

### `ModuleNotFoundError` on launch
Dependencies aren't installed. Run `Install.cmd`, or:
```bash
python -m pip install -r requirements.txt
```

### `Executable doesn't exist at ...ms-playwright...`
Chromium was never downloaded. Easiest fix: the **Download browser** button on
the Dashboard. From a terminal:
```bash
python -m playwright install chromium
```

### The Dashboard says the browser isn't installed, but checks used to work
Playwright pins a specific Chromium build per version, so upgrading Playwright
can leave the old build behind and require a new download. Click **Download
browser**; the previous build is left alone.

### Port already in use
Handled automatically — the app moves to the next free port and records it in
`%APPDATA%\MDECDocketManager\runtime.json`. If ports 8674–8693 are *all* taken
you'll get a dialog saying so; change the port in Settings.

### The app is running but I can't find the window
Click the icon again — it reuses the running service and brings the window back.

### How do I actually quit?
**Settings → Quit app.** Closing the window deliberately leaves the service
running so scheduled checks continue.

### I moved the app folder and the icon broke
Shortcuts point at the old path. Run `Install.cmd` in the new location to rebuild
them.

### The browser opens to a blank page
The server hadn't finished starting. Reload. If it persists, run
`python run.py --no-open` and read the console output.

---

## Login and session

### "Portal session expired" on every check
Attach mode lost the session. Click **Open portal window**, sign in, then check
again. If it expires constantly, consider managed login
([walkthrough](WALKTHROUGH.md#7-automated-login-with-an-emailed-code)).

### "Managed login completed but the case page still looks logged out"
The credentials submitted but the portal didn't accept them, or a selector is
stale. Watch the browser window during a check — it's headful for exactly this
reason. Then either fix the selectors under **Settings → Portal login** or switch
to attach mode and sign in by hand.

### "No verification code arrived by email within the timeout"
Work down this list:

1. **Gmail app password?** With 2-Step Verification on, your normal password
   fails over IMAP. Create one at
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
2. **IMAP enabled?** Gmail → Settings → Forwarding and POP/IMAP.
3. **Sender match?** Check the actual `From:` on a code email and make sure a
   substring of it is in **Allowed senders**.
4. **Code shape?** The default pattern expects six digits. Adjust **Code
   pattern** if yours differs.
5. **Age window?** Only mail from the last 10 minutes counts. If the code arrives
   slower, raise `email.max_age_minutes` in `config.json`.

### Managed login asks for a code every single time
Normal if the profile keeps getting cleared. Don't delete `.pw-profile`, and let
the app manage the browser rather than closing it forcibly.

---

## Downloading

### It's slow
By design. 300 ms per document, batches of ten, pauses between. Roughly 20
minutes per 1,000 documents on a first run. Later checks only fetch what's new.

Going faster is what triggered the portal's throttle during the reference run,
around the 475th rapid download. The settings are exposed under **Settings →
Downloader pacing** if you insist, but that's the failure mode you're buying.

### A check logged "session-refresh throttle"
The portal returned its "Please wait. Do not select refresh…" spinner. The app
waits ~20 s, re-parses the page, and resumes on its own — you'll usually just see
it in the log. It is **not** a logout. If it repeats, raise the breathing-room
and batch-pause values.

If it gives up after three attempts on the same document, run another check —
already-downloaded entries are skipped, so it resumes where it left off.

### Entries logged as `view_only` or `no file`
The portal showed a dialog with no download button. Those documents aren't
available to download; there's nothing to fix. They're logged as warnings, not
errors, and the Docket tab marks them `no file`.

### <a id="counts-dont-match"></a>Counts don't match what's on the portal
1. **Activity** — read the warnings. `view_only` entries legitimately produce no
   file.
2. **Documents tab** count vs. PDFs on disk. If disk is short, a download was
   dropped; run another check.
3. If the app found *fewer entries* than the portal shows, the page structure may
   have changed — see below.

### "button not found (page re-rendered?)"
The page re-rendered mid-run. Harmless in isolation; the entry is retried once
and then flagged. Run another check.

---

## Parsing

### Entries have blank or wrong names/dates
The parser reads labeled fields first and falls back to position, so a portal
redesign degrades field quality rather than losing entries. Each entry keeps its
raw text in the database:

```sql
SELECT seq, name, file_date, raw_text FROM entries ORDER BY seq DESC LIMIT 5;
```

(`%APPDATA%\MDECDocketManager\mdec.db`.) If `raw_text` has the right content but
the fields don't, the heuristics in `mdec/portal/docket.py` need updating — open
an issue with a `raw_text` sample, redacted.

### Far fewer entries than expected
The parser finds documents by buttons whose text is exactly `Document` or
`Documents`. If the portal renamed them, that's the fix point, in
`PARSE_JS` in `mdec/portal/docket.py`.

### Duplicate entries after a portal change
Fingerprints hash section + date + name + comment. If the portal starts rendering
a field differently, old and new hashes differ and entries look new. Confirm with
the Docket tab, then either accept the duplicates or delete the stale rows:

```sql
DELETE FROM entries WHERE case_id = 1 AND first_seen > '2026-07-01';
```

Back up the database first.

---

## Naming

### `XXXXXXXX` instead of a date
The portal gave no parseable file date for that entry. Deliberate — the app marks
unknown rather than guessing, and `XXXXXXXX` sorts predictably. Fill it in by
hand if you know the date.

### Repair dry run shows everything `unmatched`
Almost always the case ID. The app strips `-C01cv24001234` from filenames using
the normalized form of the active case's number. Check that the case number in
**Settings → Cases** matches the case ID actually in the filenames — and that the
case you mean is the active one.

Also make sure you've run a real check first — without a docket index there's
nothing to match against.

### Repair shows `missing` rows
Docket slots with no file on disk: downloads that never landed. Run a check to
fetch them, then repair again.

### Repair renamed nothing
Check the path for typos — a wrong path silently matches zero files. This bit the
original PowerShell script twice (`Forclosure` vs `Foreclosure`). Paste the path
from Explorer's address bar.

### I want to undo a rename
`_ORIGINAL_NAMES_manifest.csv` in the folder maps every original name to its
final name, in order. The app never overwrites: a collision becomes `~2`.

---

## Adopting files already on disk

### "Adopt files" found nothing, but the folder is full of PDFs
Adoption matches on the sequence number in the filename, so only
`NNNN_YYYYMMDD_…` names can be adopted. Legacy `Title-caseid (2).pdf` names carry
no sequence — run the repair rename first, then adopt.

Also check the case's **Document folder** actually points at that folder
(Dashboard shows the resolved path), and that the right case is active.

### "No docket entries recorded yet"
Adoption links files to entries, so the app needs the docket first. Run **Check
now** once. If you don't want it downloading yet, note that the check adopts
before downloading — so on a complete folder there'll be little or nothing left
to fetch.

### Everything came back as an orphan
The sequence numbers in the filenames don't match the docket the app read. Usual
cause: the files were numbered against a different case, or a previous repair run
used a different docket order. Compare a filename's `NNNN` against that entry's
sequence on the Docket tab.

### It re-downloaded documents I already had
The files weren't adoptable — wrong folder, non-catalog names, or zero-byte files
(treated as failed downloads, deliberately). The duplicates are safe: the app
never overwrites, so you'll have a `~2` copy rather than a lost original.

### "Awaiting download" never reaches zero
Those entries have a document button but no file. Each check retries them. If a
number sticks:

- **Activity** will show them as `view_only` — the portal offers no download, and
  they're excluded from future retries once marked.
- Or the warning says no download button was found for them on this page, which
  means the entry didn't render in the section the parser read. They're retried
  next check.

---

## Multiple cases

### The wrong case's data is showing
Check the case dropdown in the top bar. Every tab follows the active case.

### A case disappeared from the list
"Stop tracking" removes it. Its PDFs are still in the folder — re-add the case
with the same number and folder, run a check, and adopt the folder to restore the
archive. Notes and analyses can't be recovered.

### Scheduled checks skip a case
Its **Include in scheduled checks** box is unticked (Settings → Cases). Manual
**Check now** always runs the active case regardless.

### Two cases share a folder
Not recommended but not broken: each case adopts only files whose sequence
matches one of *its* entries, and reports the rest as orphans. Give each case its
own folder to avoid the noise.

---

## OCR

### "Missing system tools: tesseract, gs"
Install both and make sure they're on `PATH` — see
[INSTALL.md](INSTALL.md#optional-ocr). Open a **new** terminal after installing
and confirm `tesseract --version` and `gs --version` answer, then restart the app.

### OCR is on but no documents get processed
Expected for e-filed PDFs — they already have a text layer, so OCR is skipped.
Only documents yielding under 200 characters of text get OCR'd. Check a specific
document with `GET /api/documents/<id>/text`.

### OCR is very slow
Normal: seconds to minutes per scanned page. It runs in a thread so the UI stays
responsive, but a check with many scans takes a while.

---

## Analysis

### "No Claude backend available"
Either store an Anthropic API key in Settings, or install the Claude Code CLI and
sign in. The Dashboard checklist shows which is active.

### "the Claude Code CLI ('claude') was not found on PATH"
```bash
npm install -g @anthropic-ai/claude-code
claude          # sign in once, then exit
```
Restart the app afterward — `PATH` is read at process start.

### "Claude CLI failed (are you signed in?)"
Run `claude` in a terminal and complete sign-in. If it works there but not from
the app, the app is running as a different user with a different config.

### "Claude CLI timed out"
Ten-minute ceiling per document. Usually a very large document. Try a smaller
model, or use the API backend.

### Analysis says a document has no text
The PDF is a scan and OCR is off or unavailable. Turn on OCR.

### The summary looks wrong, or invents a deadline
It can. Claude is reading one document without the rest of the case's context.
Verify every date against the document. Nothing here is legal advice — that's why
the disclaimer is on the Dashboard and in every analysis view.

### "Claude declined to analyze this document"
A safety classifier declined. With the API backend the app already asks the
server to retry on a fallback model. If it still declines, read the document
yourself — this is a limitation of the classifier, not a judgment about your case.

---

## RAG export

### Nothing appears in the export folder
Check the target is enabled *and* the path is set — both are required. Documents
with no extractable text are skipped (turn on OCR). The Documents tab's **RAG**
column shows what was exported.

### Webhook exports fail
The app POSTs JSON and needs a 2xx. Check the Activity log for the status code.
A 30-second timeout applies per document.

### "chromadb is not installed"
```bash
python -m pip install chromadb
```
Or turn off the Chroma target.

---

## Data and recovery

### Where is everything?
```
%APPDATA%\MDECDocketManager\config.json    settings
%APPDATA%\MDECDocketManager\mdec.db        docket, notes, analyses, runs
%APPDATA%\MDECDocketManager\.pw-profile\   browser session
```
PDFs are wherever you set the download folder.

### Start over without losing documents
Close the app and delete `mdec.db`. The next check re-reads the whole docket.
Your PDFs and notes-in-the-database are separate — deleting the DB loses notes
and analyses, so export anything you care about first.

### Forgot which credentials are stored
Settings shows *Stored in Windows Credential Manager* under each secret field.
The values are never retrievable through the app. Control Panel → Credential
Manager → Windows Credentials, look for `mdec-docket-manager`.

### Corrupt config
Delete `config.json`; defaults are recreated on next launch. Secrets are
unaffected — they aren't in that file.

---

## Still stuck

Open an issue with: what you did, the Activity log entry (redact case details),
your OS and Python version, and whether OCR/analysis/RAG were on. Please don't
paste case documents or credentials.
