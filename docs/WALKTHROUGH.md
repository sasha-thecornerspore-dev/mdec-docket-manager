# Walkthroughs

Assumes you've finished [INSTALL.md](INSTALL.md) and `python run.py` opened the
UI at <http://127.0.0.1:8674>.

- [1. First run](#1-first-run)
- [2. Reading the docket](#2-reading-the-docket)
- [3. Notes](#3-notes)
- [4. Claude analysis](#4-claude-analysis)
- [5. Automated login with an emailed code](#5-automated-login-with-an-emailed-code)
- [6. Scheduled monitoring](#6-scheduled-monitoring)
- [7. OCR and RAG export](#7-ocr-and-rag-export)
- [8. Repairing a legacy folder](#8-repairing-a-legacy-folder)
- [9. Backing up](#9-backing-up)

---

## 1. First run

### Configure the case

Go to **Settings → Case**:

| Field | Example | Notes |
|---|---|---|
| Case number | `C-03-CV-24-003218` | Type it as printed, with dashes. The app converts it to the portal's URL form (`C03cv24003218`) itself. |
| Caption | `Brenner et al. vs. Schatz` | Shown in the title bar. Cosmetic. |
| Court | `Baltimore County Circuit Court` | Cosmetic. |
| Download folder | `D:\Cases\Brenner\docket` | Where named PDFs go. Created if missing. Defaults inside `%APPDATA%`. |

Click **Save settings**. The Dashboard's setup checklist now shows *Case number
set ✓*.

### Sign in

Click **Open portal window** in the top bar. A Chromium window opens on your case
page. Sign in there yourself, the normal way, including whatever verification the
portal asks for.

This is *attach mode*, the default and the recommended setup: the app never
handles your password, and the browser profile persists, so you usually stay
signed in across restarts. When the session does expire, a check finishes with a
`warning` status telling you to sign in again.

You can leave the window open or close it — the session lives in the profile, not
the window. **Settings → Close browser window** shuts it down cleanly.

### First check

Click **Check now**.

The app reads every docket entry, records them, downloads the documents, names
them, and logs the run. The state chip next to the button narrates progress
(`parsing docket`, `downloaded 14/62`, …).

**On a case with hundreds of documents the first check takes a while** — roughly
20 minutes per 1,000 documents, because it deliberately waits 300 ms between
files and pauses between batches of ten. That pacing is what keeps the portal
from throttling you. Later checks only fetch what's new, so they take seconds.

When it finishes you'll see a summary toast, and the Dashboard counters fill in.
If anything was skipped you'll get a `warning` status — open **Activity** to read
exactly what and why. Common and harmless: entries the portal shows as view-only
have no download button, and are logged rather than treated as errors.

### Verify

Open your download folder. You should see:

```
0001_20260113_Hearing - Motion.pdf
0002_20240826_Order to Docket.pdf
0003_20240902_Writ Summons Pleading Electronic Service.pdf
...
_ORIGINAL_NAMES_manifest.csv
```

`NNNN` is the docket sequence, `YYYYMMDD` the file date (`XXXXXXXX` when the
portal didn't give one), then the document title. Entries with several files get
`_1of14`, `_2of14`, … suffixes. The manifest records every original name, so any
rename can be undone.

Cross-check the count against the Documents tab. If they disagree, see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#counts-dont-match).

---

## 2. Reading the docket

The **Docket** tab is a ledger, newest filing first. The left spine shows the
sequence number; anything that arrived since you last looked has a red notch and
a **New** stamp.

Click any row to expand it: section, the files with sizes and OCR/RAG status,
plus its notes and analysis. Chips summarize at a glance — `3 files`,
`no file` (view-only), `2 notes`, `analyzed`.

Filter by name, comment, or date with the search box, or narrow to entries that
actually have documents. Click a filename to open the PDF.

Opening the tab clears the New marks, so the next check's arrivals stand out.

---

## 3. Notes

**Notes** tab. Type, pick an entry from the dropdown (or leave it on *Case-level
note*), and **Save note**. Notes render basic markdown — `**bold**`, `- bullets`,
`` `code` `` — and appear both in the Notes list and inside the entry on the
Docket tab.

Faster route: expand an entry on the Docket tab and click **Add note** — it jumps
to the Notes tab with that entry preselected.

---

## 4. Claude analysis

### Turn it on

**Settings → Claude analysis**:

1. Tick **Analyze new filings**.
2. Tick **Analyze automatically as documents arrive** to have each check analyze
   what it downloaded. Leave it off to analyze by hand.
3. Choose a **Backend** — *Auto* uses your API key if you've stored one and
   otherwise your Claude subscription via the CLI. See
   [INSTALL.md](INSTALL.md#optional-claude-analysis) for setting either up.
4. Save. The Dashboard checklist confirms which backend is live, e.g.
   `Claude analysis (cli)`.

### Analyze one filing

Expand an entry on the Docket tab → **Analyze this entry**. The app extracts the
document's text (OCR-ing first if enabled and needed), sends it to Claude, and
stores the result.

Each analysis gives you a plain-English summary of what the filing is and what it
asks for, any **dates and deadlines** it found (listed with a red rule so they're
hard to miss), and **suggested next steps**.

### A case briefing

**Analysis → Write case briefing** synthesizes the whole docket plus every stored
summary into a "state of the case": current posture, pending motions, upcoming
deadlines, prioritized next steps.

> Treat all of this as a reading aid. Claude can misread a filing, miss a
> deadline, or invent one. Every date it reports needs checking against the
> document. Nothing here is legal advice.

---

## 5. Automated login with an emailed code

Optional, and only worth it if you want checks to keep running unattended for
weeks. Attach mode is simpler and safer; prefer it unless the session keeps
expiring on you.

In managed mode the app fills your portal username and password, and when the
portal emails a verification code, reads that code over IMAP and enters it.

### Setting it up

**Settings → Portal login**:

1. **Mode** → *Managed*.
2. **Login URL** — the portal's sign-in page (a default is prefilled).
3. **Portal username** and **Portal password**. The password goes into Windows
   Credential Manager on save; the field then reads *Stored in Windows Credential
   Manager* and stays blank.

**Settings → Email verification code**:

| Field | Value |
|---|---|
| IMAP host | `imap.gmail.com` for Gmail |
| IMAP user | the address the court emails codes to |
| IMAP app password | **not** your account password — see below |
| Allowed senders | `courts.state.md.us, mdcourts.gov` — only mail from these is read |
| Code pattern | `\b(\d{6})\b` — adjust if the code isn't six digits |

**Gmail app password:** with 2-Step Verification on, Gmail refuses your normal
password over IMAP. Create a dedicated app password at
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
and paste that. Revoke it there any time.

The app only reads messages from the allowed senders, only from the last 10
minutes, and only ever extracts the code. It never sends mail, never deletes
anything, and never marks messages read.

### Testing it

Click **Close browser window**, then **Check now**. Watch the state chip: you
should see `attempting managed login`, then `verification code requested —
polling email`, then the check proceeding. If it stalls, **Activity** has the
exact failure — usually a wrong app password or a selector the portal changed
(fix selectors under Settings → Portal login without touching code).

To go back: set **Mode** → *Attach*. To remove the stored secrets, clear each
password field and save.

---

## 6. Scheduled monitoring

**Settings → Monitoring**. Tick **Check the docket on a schedule** and set the
times, 24-hour, comma separated. Default `08:00, 17:00`.

Two checks a day is deliberate. The portal throttles rapid automation, and a
docket changes a few times a month at most. Please don't set this to every five
minutes.

Scheduled checks run while `run.py` is running. Keep the window open (minimized
is fine). To have it start with Windows, put a shortcut to
`python D:\path\to\run.py --no-open` in
`shell:startup`.

Runs are single-flight: a scheduled check can't overlap a manual one, which is
what stops the double-downloading that plagued the original script.

---

## 7. OCR and RAG export

### OCR

Once the prerequisites are installed, **Settings → OCR** → tick **OCR scanned
documents as they arrive**.

Per document the app first tries the existing text layer. If that yields under
200 characters it assumes a scan and runs `ocrmypdf --skip-text`, which adds a
text layer in place and writes a `.txt` sidecar next to the PDF. Documents with
usable text are left alone, so nothing is re-processed needlessly.

The Documents tab's **OCR** column shows what's been processed. To read the
extracted text for any document, `GET /api/documents/<id>/text`.

### RAG export

**Settings → RAG export.** Enable any combination; each is tried per document and
failures are logged per-document rather than aborting the run.

**Watched folder** — writes two files per document:

```
0004_20260720_Motion for Summary Judgment.txt
0004_20260720_Motion for Summary Judgment.meta.json
```

The `.meta.json` carries `case_number`, `seq`, `file_date`, `entry_name`,
`document_title`, `filename`, and `sha256`. Point your RAG ingester at the
folder.

**Webhook** — POSTs to your URL:

```json
{
  "case_number": "C-03-CV-24-003218",
  "entry": {"seq": 4, "file_date": "7/20/2026", "name": "Motion...", "comment": ""},
  "document": {"id": 20, "title": "Exhibit", "filename": "0004_...pdf", "sha256": "..."},
  "text": "full extracted text",
  "metadata": { }
}
```

**ChromaDB** — upserts into a local persistent collection, one document per PDF,
IDs keyed on `case_number:sha256` so re-runs update rather than duplicate.

The Dashboard shows which targets are live; the Documents tab's **RAG** column
shows which documents made it out.

---

## 8. Repairing a legacy folder

If you already have a folder from an earlier scrape — files still named
`Order to Docket-C03cv24003218.pdf`, `... (1).pdf`, `... (2).pdf` — this renames
them into the catalog.

**First run a normal check** so the app knows the docket order. Then
**Settings → Repair a legacy folder**:

1. Paste the folder path.
2. **Dry run.** Read the output. Every file shows as `rename`, `unmatched`, or
   `missing`.
3. If it looks right, **Rename for real** and confirm.

### How the matching works

Files are sorted by **creation time**, which equals download order, which equals
docket order. Each filename's `" (n)"` suffix is stripped to get its stem, and
the *N*th physical copy of a stem is matched to the *N*th docket slot expecting
that stem. That's why a title appearing 146 times doesn't scramble.

Never sort by filename or modification time — both destroy the ordering the
matching depends on.

### The two statuses that need you

- **unmatched** — more copies of a title on disk than docket slots expecting it.
  Left untouched.
- **missing** — a docket slot with no file, i.e. a download that never landed.

Both are left alone deliberately. For court documents a wrong label is worse than
no label, so review these by hand rather than forcing a match.

Every rename appends to `_ORIGINAL_NAMES_manifest.csv` in the folder, and a name
collision produces `~2` rather than an overwrite. Nothing is destroyed.

---

## 9. Backing up

Two things matter:

1. **Your download folder** — the PDFs and the rename manifest.
2. **`%APPDATA%\MDECDocketManager\mdec.db`** — the docket, notes, analyses, and
   run history.

`config.json` is worth keeping but trivially recreated. The `.pw-profile` folder
is just a browser session; deleting it means signing in again. Credentials are in
Windows Credential Manager and aren't part of a file backup — write them down
somewhere safe if you'd struggle to recreate them.

Copying the database while a check is running can catch it mid-write. Back up
when the state chip reads `idle`.
