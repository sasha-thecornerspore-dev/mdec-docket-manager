# Field notes: the 950-document run

This app exists because someone downloaded a complete 950-document docket by hand
first, in a browser-automation session, and wrote down everything that broke.
Every lesson below is now enforced in code. Keeping the notes means the next
person to touch the downloader knows *why* the pacing looks paranoid.

Reference case: a residential foreclosure in a Maryland circuit court, 950
documents, ~16 minutes of automated runtime once it worked and about 45 minutes
including the debugging.

---

## What the page looks like

- Every document sits behind a `<button>` whose text is exactly `Document` or
  `Documents`. Plural means several files in one popup.
- Button 0 is typically the court-scheduling document; the rest are docket
  entries in chronological order. An "Other Documents" section at the bottom uses
  a different layout but the same buttons.
- The modal is `[role="dialog"]`, download buttons are
  `[aria-label*="Download document"]`, and the closer is a button reading
  `Close`.
- Downloaded names arrive as `{Document Title}-{CASEID}.pdf`. The same title
  repeats constantly — one appeared **146 times** — so the browser appends
  ` (1)`, ` (2)`, … That single fact is why the repair rename has to be
  occurrence-counted rather than positional.
- The page is heavy: roughly 1,944 `<article>` and 2,885 row elements. The
  accessibility tree exceeds a 50k-character read limit even at shallow depth, so
  in-page JS is the only workable way to read it.

## The seven lessons

### 1. Going too fast gets you throttled
Batches of 30 with ~50 ms gaps died around document 475 — the halfway mark. The
page reloaded into a spinner reading *"Please wait. Do not select refresh or the
back button."*

It is **not** a logout. Waiting about 15 seconds and resuming from where it
stopped worked fine.

**Now:** 300 ms after every document, batches of 10, a pause between batches, and
automatic detect-wait-reparse-resume when the spinner appears.

### 2. Don't mass-clear timers
`for (let i = 0; i <= id; i++) { clearTimeout(i); clearInterval(i); }` killed
every scheduled timer in the page, including the automation's own loop.

**Now:** no timer sweeping anywhere. Cancellation is explicit.

### 3. One loop at a time
Restarting the loop without stopping the previous one left three-plus async loops
racing: double downloads, interleaved modals, unpredictable state.

**Now:** an `asyncio.Lock` makes runs single-flight. A scheduled check cannot
overlap a manual one.

### 4. Background tabs throttle timers
Browsers clamp `setTimeout` in inactive tabs, so a 100 ms sleep really takes
300–1500 ms. Loops appeared frozen and hit the 45-second CDP ceiling.

The workaround in the original run was a `MessageChannel`-based sleep, which runs
at true wall-clock speed regardless of tab visibility:

```js
window.sleepMC = ms => new Promise(resolve => {
  const start = performance.now();
  const ch = new MessageChannel();
  ch.port1.onmessage = () => {
    if (performance.now() - start >= ms) resolve();
    else ch.port2.postMessage(null);
  };
  ch.port2.postMessage(null);
});
```

**Now:** moot. Playwright drives the browser from Python, so waits happen in
Python and no in-page timer is involved. The technique is recorded here because
it's the right answer for anyone doing this from the devtools console.

### 5. The close/next-click race
Clicking `Close` and immediately clicking the next `Document` button opened the
new modal before the old one finished closing. The "did it close?" check then saw
the *new* modal and concluded the old one was stuck.

**Now:** the downloader waits for `[role="dialog"]` to disappear before touching
the next button.

### 6. The 45-second CDP ceiling
Each in-page evaluation had a hard 45-second timeout. With throttled timers, even
five documents could exceed it, which is why the original loop was capped at ten
documents per call.

**Now:** each document is its own set of Playwright calls, so there's no
per-batch ceiling to bump into. Batch size survives as a pacing knob, not a
workaround.

### 7. Some documents are view-only
A few entries open a dialog with no download button at all. These are not errors.
The original run logged them and moved on.

**Now:** logged as `view_only`, surfaced in the run's warnings, and shown as
`no file` on the Docket tab.

## Two safeguards added by the user, kept in the design

**Get download permission first.** The original approach had to trigger one
download and approve Chrome's *"Download multiple files?"* prompt before mass
downloading, and check with a human before starting hundreds of files.

Playwright's `expect_download` removes that prompt entirely, so the app doesn't
need the approval — but the spirit survives: the first check is explicitly
user-initiated, and the UI tells you how many documents it's about to fetch.

**Early checkpoint.** After the first 10–20 files, stop and verify they actually
landed on disk — count files against the loop's log — before running the full
job.

**Now:** automated per file. A download isn't recorded until the file exists with
non-zero size, and its SHA-256 is stored. Every file is its own checkpoint.

## Naming, then and now

The original run produced `{Title}-{CASEID}.pdf` files plus ` (n)` suffixes, and
a PowerShell script renamed them to `NNNN_YYYYMMDD_Description.pdf` afterward.
Two rules made that work:

- **Sort by file creation time.** Creation time equals download order equals page
  order. Sorting by filename or modification time destroys the mapping.
- **Occurrence-counted stem matching.** Strip the ` (n)` suffix to get the stem;
  the *N*th physical copy of a stem belongs in the *N*th docket slot expecting
  that stem.

`pipeline/renamer.py` keeps both rules for the repair path. For documents the app
downloads itself, neither is needed — it knows which entry each file came from,
so naming is deterministic.

The script also taught a mundane lesson worth repeating: **a wrong path silently
renames nothing**. Two runs were lost to a misspelled folder
(`Forclosure` for `Foreclosure`). The app takes the folder from the UI and
reports a count, so silence isn't possible.

## Verification is not optional

The original notes end on the right point: for legal documents, a mislabel is
worse than no label. Cross-check the renamed result against an independent index,
confirm no docket slot is empty, and flag any title whose file count is short —
that's the one place occurrence-counting can still mis-slot when files are
missing.

The repair tool reports `unmatched` and `missing` and refuses to guess for exactly
this reason.
