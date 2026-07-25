# Security and privacy

## Threat model

One person, their own machine, their own court case. The app is not multi-user,
not hosted, and not exposed to a network. The risks worth designing against are:
credentials leaking into files or version control, case documents leaving the
machine unintentionally, and the app being reachable by something other than you.

## What runs where

The web server binds to **`127.0.0.1` only**. Nothing on your LAN or the internet
can reach it. There is no authentication because there is no remote access — if
you change the bind address, you are on your own.

## Credentials

Three secrets can be stored, all in **Windows Credential Manager** via `keyring`,
under service name `mdec-docket-manager`:

| Slot | Used for |
|---|---|
| `portal_password` | Managed portal login |
| `imap_password` | Reading the emailed verification code |
| `anthropic_api_key` | API-backed analysis |

Properties of the design:

- `config.json` **never** contains a secret. `save_config()` strips those keys
  from any dict handed to it, and a test asserts a secret can't reach disk.
- The API is **write-only** for secrets. `POST /api/secrets` accepts a value;
  nothing returns one. `GET /api/settings` reports booleans only.
- Slot names are allow-listed. An unknown name raises.
- Sending an empty value deletes the slot.
- Secret input fields never render a stored value and clear themselves after
  save.

None of the three is required. Attach-mode login needs no stored password at all,
and subscription-based analysis needs no API key.

## What leaves your machine

| Feature | Sends what, where | Default |
|---|---|---|
| Docket checks | Ordinary authenticated requests to the Maryland Judiciary portal | On |
| Email code | IMAP connection to your mail provider, read-only | Off |
| Analysis (API) | Document text + docket metadata to the Anthropic API | Off |
| Analysis (subscription) | Same, via the Claude Code CLI under your Claude plan | Off |
| RAG webhook | Document text + metadata to the URL you configure | Off |
| RAG folder / ChromaDB | Nothing — local writes | Off |

Everything except the docket check itself is off until you turn it on. With
analysis and the webhook off, no case content leaves the machine.

Note what analysis means: **the text of your court filings is sent to Anthropic**
for summarization. That's the feature. If your case involves material you don't
want to send to a third party, leave analysis off and use notes instead.

## Email access

The IMAP reader is deliberately narrow: it connects read-only, scans only the 25
newest messages, ignores anything older than the age window (10 minutes by
default), only considers senders you allow-listed, and extracts a regex match.
It never sends, deletes, moves, or marks messages read.

Use a **Gmail app password**, not your account password — it's scoped to this one
use and revocable at
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

## Version control

`.gitignore` excludes `*.pdf`, `*.db`, `config.json`, `_ORIGINAL_NAMES_manifest.csv`,
`downloads/`, `.pw-profile/`, and log files. All runtime data lives outside the
repo under `%APPDATA%`, so a `git add -A` cannot pick up case documents.

Before pushing, sanity-check with `git status`.

The published code is generic — it carries no case number, caption, party, or
folder path. Your case lives entirely in `%APPDATA%` and your document folder,
neither of which is in the repository. If you fork it, keep it that way: put
nothing case-specific in code, commit messages, issues, or branch names.

## Documents on disk

PDFs are stored unencrypted in your download folder. If the machine is shared or
portable, use BitLocker or an encrypted volume. The app does not manage
encryption.

`.txt` sidecars from OCR and RAG folder exports contain full document text in
plain text. Include those folders in whatever protection you apply.

## Browser profile

`%APPDATA%\MDECDocketManager\.pw-profile` holds an authenticated portal session.
Treat it like a password: anyone with your user account and that folder can reach
your case. Delete it to force a fresh sign-in.

## Using this lawfully

Use it only for a case you have lawful access to. The app automates the browser
you already sign into; it doesn't circumvent access controls, and it can't reach
documents your account can't. Pacing is set to be gentle on a public court
system's servers — please leave it that way.

## Reporting a problem

Open an issue for anything security-relevant. Don't include case documents,
credentials, or your case number.
