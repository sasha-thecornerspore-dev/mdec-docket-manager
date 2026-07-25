"""Fetch the MDEC login verification code from the user's mailbox over IMAP.

Gmail users need an App Password (regular passwords don't work with IMAP when
2-Step Verification is on) — see docs/WALKTHROUGH.md. The password is read from
Windows Credential Manager, never from config.

All functions here are blocking (imap-tools is sync); callers run them in a
thread executor.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone


def extract_code(text: str, code_regex: str) -> str | None:
    m = re.search(code_regex, text or "")
    return m.group(1) if m else None


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_latest_code(host: str, user: str, password: str, senders: list[str],
                      code_regex: str, max_age_minutes: int = 10) -> str | None:
    """Newest verification code from an allowed sender within the age window."""
    from imap_tools import MailBox

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    senders_l = [s.lower() for s in senders]
    with MailBox(host).login(user, password, "INBOX") as mb:
        # Newest first; cap the scan — the code email is always recent.
        for msg in mb.fetch(reverse=True, limit=25, mark_seen=False,
                            headers_only=False):
            if _aware(msg.date) < cutoff:
                break
            frm = (msg.from_ or "").lower()
            if not any(s in frm for s in senders_l):
                continue
            body = f"{msg.subject or ''}\n{msg.text or ''}\n{msg.html or ''}"
            code = extract_code(body, code_regex)
            if code:
                return code
    return None


def poll_for_code(host: str, user: str, password: str, senders: list[str],
                  code_regex: str, max_age_minutes: int = 10,
                  timeout_s: int = 120, interval_s: int = 5) -> str | None:
    """Poll until the code email arrives or timeout_s elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        code = fetch_latest_code(host, user, password, senders,
                                 code_regex, max_age_minutes)
        if code:
            return code
        time.sleep(interval_s)
    return None
