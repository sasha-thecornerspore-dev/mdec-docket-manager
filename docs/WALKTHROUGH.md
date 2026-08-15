# Walkthroughs

Assumes you've finished [INSTALL.md](INSTALL.md) and `python run.py` opened the
UI at <http://127.0.0.1:8674>.

- [1. First run](#1-first-run)
- [2. Reading the docket](#2-reading-the-docket)
- [3. Tracking several cases](#3-tracking-several-cases)
- [4. Importing an archive you already have](#4-importing-an-archive-you-already-have)
- [5. Notes](#5-notes)
- [6. Claude analysis](#6-claude-analysis)
- [7. Automated login with an emailed code](#7-automated-login-with-an-emailed-code)
- [8. Scheduled monitoring](#8-scheduled-monitoring)
- [9. OCR and RAG export](#9-ocr-and-rag-export)
- [10. Repairing a legacy folder](#10-repairing-a-legacy-folder)
- [11. Backing up](#11-backing-up)

---

## 1. First run

### Add your case

Go to **Settings → Cases → Add a case**:

| Field | Example | Notes |
|---|---|---|
| Case number | `C-01-CV-24-001234` | Type it as printed, with dashes. The app converts it to the portal's URL form (`C01cv24001234`) itself. |
| Caption | `Smith v. Jones` | Shown in the title bar. Cosmetic. |
| Court | `Circuit Court for Anne Arundel County` | Cosmetic. |
| Document folder | `D:\Cases\smith-v-jones` | Where named PDFs go. **Browse…** opens a real folder picker. Leave blank for a subfolder named after the case under the folder root. |
| Include in scheduled checks | on | Untick to keep the case but stop auto-checking it. |

Click **Add case**. It becomes the active case, and the Dashboard shows its
folder plus whether that folder exists yet.

If you point the folder at an archive you already have, see
[section 4](#4-importing-an-archive-you-already-have) — the app will adopt those
files instead of downloading them again.

### Get to the docket yourself, then hand over

The portal challenges automated browsing, so the app does not try to drive its
way in. You take it to the docket; it takes over from there. On the Dashboard,
under **Harvest the docket**:

**1. Open Chrome for harvesting.** This opens **your real Chrome** — not the
app's bundled browser — on your case page.

That distinction is the whole point. The app's Playwright browser announces
itself as automation, and the portal's bot detection serves it a "Verification
Required" challenge that you often can't get past even as the rightful account
holder. Real Chrome carries an ordinary fingerprint and loads the site normally.

It uses a dedicated Chrome profile (`.chrome-harvest`), because Chrome refuses
to open a debug port on your everyday profile. So **sign in once in that
window** — the session persists there afterwards. Clear any verification
challenge yourself; the app will never answer one for you.

> While that window is open it listens on a local debug port, which lets any
> program on your computer drive it. Close it when you're done. Your everyday
> Chrome profile is never touched.

**2. Attach.** The app takes hold of whichever tab is showing the docket. It
never navigates that tab — navigating would discard the session you just
established and can re-trigger the challenge.

**3. Check readiness.** This verifies the three things that otherwise fail
silently halfway through a long run:

| Check | Why it matters |
|---|---|
| Download folder writable | A folder it can't write to loses every file |
| Multiple downloads pre-approved | Chrome blocks the 2nd and later automatic downloads behind a prompt; mid-run, nobody answers it |
| Browser is on the docket | Confirms the page really parses, and reports how many entries and documents it can see |

**Harvest** stays disabled until all of them pass.

**4. Harvest.** The app works from the page you left open — it
does not navigate, because navigating would discard the session you just
established and can re-trigger the challenge.

It downloads every entry that has no file yet, names them, and logs the run. The
state chip narrates progress (`Downloaded 14/62 …`).

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

## 3. Tracking several cases

Add as many cases as you like in **Settings → Cases**. Each one keeps its own
docket, documents, folder, notes, and analyses — nothing crosses over.

**Switching:** use the dropdown in the top bar, or **Make active** on a case row.
Every tab follows the active case.

**Per-case settings** live on the case row: caption, court, document folder, and
whether it's included in scheduled checks. Edit and click **Save**.

**Everything else is shared** — login, email, OCR, RAG export, analysis, and
pacing apply to all cases. One portal account, one set of preferences.

**Scheduled checks** run through every case marked *Include in scheduled checks*,
one at a time, never in parallel. That's deliberate: two cases hammering the
portal at once is exactly what the pacing exists to prevent.

**Stop tracking** forgets a case's docket, notes, and analyses. It never deletes
downloaded PDFs — those stay in the folder, and re-adding the case plus
[adopting the folder](#4-importing-an-archive-you-already-have) restores the
archive.

---

## 4. Importing an archive you already have

If the PDFs already exist, the app should not download them again. Two paths
depending on how they're named.

### Already named by this app's convention

Files like `0002_20240826_Order to Docket.pdf` carry their docket sequence, which
is all the app needs.

1. Point the case's **Document folder** at that folder.
2. Run **Check now** once so the app learns the docket and which sequence each
   entry has.
3. That same check adopts every matching file it finds — the toast reports
   *"N adopted from disk"* and those documents are never re-downloaded.

To adopt without checking (say you restored a backup and don't want to touch the
portal yet), use **Dashboard → Adopt files already in this folder**. It's
read-only with respect to the portal and safe to run repeatedly — files already
recorded are skipped, so a second run adopts nothing.

Files whose sequence matches no docket entry are reported as **orphans** and left
completely alone.

### Named the old way (`Title-caseid (2).pdf`)

Those carry no sequence, so they can't be adopted directly. Run
[the repair rename](#10-repairing-a-legacy-folder) first to give them catalog
names, then adopt.

### Resuming an interrupted harvest

This needs no action at all. Every check begins by adopting what's on disk, then
downloads only the entries still missing a file. So if a 950-document first run
dies at document 400, the next check picks up around 400 rather than starting
over — and the Dashboard's **Awaiting download** counter tells you how many
entries are still outstanding.

Entries the portal offers as view-only are marked as such and not retried
forever; entries whose download genuinely failed are retried on the next check.

---

## 5. Notes

**Notes** tab. Type, pick an entry from the dropdown (or leave it on *Case-level
note*), and **Save note**. Notes render basic markdown — `**bold**`, `- bullets`,
`` `code` `` — and appear both in the Notes list and inside the entry on the
Docket tab.

Faster route: expand an entry on the Docket tab and click **Add note** — it jumps
to the Notes tab with that entry preselected.

---

## 6. Claude analysis

### Turn it on

**Settings → Claude analysis**:

1. Tick **Analyze new filings**.
2. Tick **Analyze automatically as documents arrive** to have each check analyze
   what it downloaded. Leave it off to analyze by hand.
3. Choose a **Backend** — *Auto* uses your Claude subscription through the
   signed-in Claude Code CLI, and falls back to a stored Anthropic API key only
   if the CLI isn't available. Your subscription is already paid for; the API
   bills per token, so it's the option rather than the default. See
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

## 7. Automated login with an emailed code

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

## 8. Scheduled monitoring

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

## 9. OCR and RAG export

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
  "case_number": "C-01-CV-24-001234",
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

## 10. Repairing a legacy folder

If you already have a folder from an earlier scrape — files still named
`Order to Docket-C01cv24001234.pdf`, `... (1).pdf`, `... (2).pdf` — this renames
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

## 11. Backing up

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
