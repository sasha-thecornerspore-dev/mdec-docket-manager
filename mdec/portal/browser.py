"""Playwright browser lifecycle (async API).

One persistent Chromium profile per install (under %APPDATA%) so a manual login
in *attach mode* survives restarts, and managed-mode logins rarely re-trigger
the email verification step. The window is always headful — the user can watch,
and attach mode requires them to type their password themselves.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from .. import config


class NotLoggedIn(Exception):
    """Raised when the portal bounced us to a login page and we can't self-login."""


class BrowserMissing(Exception):
    """Playwright is installed but its Chromium hasn't been downloaded."""


class BrowserBusy(Exception):
    """Another Chromium already holds the app's browser profile."""


def _is_profile_locked(exc: BaseException) -> bool:
    text = str(exc).lower()
    return ("already in use" in text or
            "opening in existing browser session" in text)


def allow_automatic_downloads(profile_dir: str) -> bool:
    """Pre-approve multiple automatic downloads in the browser profile.

    This is the "get download permission first" lesson from the reference
    harvest, done up front instead of by hand: Chrome blocks the second and
    later automatic downloads from a page until the user answers a prompt, and
    during an unattended run nobody is there to answer it.

    Writes Chrome's own preference into the persistent profile, so it is in
    force from the moment the window opens.
    """
    prefs_path = Path(profile_dir) / "Default" / "Preferences"
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs = {}
        if prefs_path.is_file():
            try:
                prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                prefs = {}          # a corrupt profile shouldn't block the run
        profile = prefs.setdefault("profile", {})
        settings = profile.setdefault("default_content_setting_values", {})
        settings["automatic_downloads"] = 1        # 1 = allow, 2 = block
        # Don't ask where to save each file, either.
        prefs.setdefault("download", {})["prompt_for_download"] = False
        prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
        return True
    except OSError:
        return False


async def prepare_downloads(context, page, folder) -> dict:
    """Point the browser's downloads at `folder` and confirm it can write there.

    Belt and braces with Playwright's own download handling: if anything ever
    slips past the interception, it still lands somewhere we control rather
    than in the user's Downloads folder.
    """
    result = {"folder": str(folder), "folder_ready": False,
              "permission_set": False, "detail": ""}
    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
        probe = Path(folder) / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        result["folder_ready"] = True
    except OSError as exc:
        result["detail"] = f"Cannot write to {folder}: {exc}"
        return result

    try:
        cdp = await context.new_cdp_session(page)
        await cdp.send("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(folder),
            "eventsEnabled": True,
        })
        result["permission_set"] = True
    except Exception as exc:
        # Not fatal: Playwright still intercepts downloads itself.
        result["detail"] = f"Download behavior not set via CDP ({exc})."
    return result


def close_orphaned_browsers(profile_dir: str) -> int:
    """Close Chromium processes still holding our profile directory.

    Scoped to the exact profile path so it can only ever touch browsers this app
    started — never the user's own Chrome.
    """
    if os.name != "nt":
        return 0
    needle = str(profile_dir).lower()
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and "
        f"$_.CommandLine.ToLower().Contains('{needle.replace(chr(39), chr(39) * 2)}') "
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue; $_.ProcessId } | Measure-Object | "
        "Select-Object -ExpandProperty Count"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int((out.stdout or "0").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._lock = asyncio.Lock()

    @property
    def profile_dir(self) -> str:
        return str(config.app_dir() / ".pw-profile")

    async def start(self):
        async with self._lock:
            if self._ctx:
                return self._ctx
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise BrowserMissing(
                    "Playwright isn't available in this build, so the portal "
                    "can't be opened. Run the app from source — see "
                    "docs/INSTALL.md."
                ) from exc
            self._pw = await async_playwright().start()
            try:
                self._ctx = await self._launch()
            except Exception as exc:
                if _is_profile_locked(exc):
                    # A previous portal window outlived the app (a crash, or the
                    # app being killed). Chromium then refuses the profile and
                    # every check fails until those orphans are gone.
                    closed = close_orphaned_browsers(self.profile_dir)
                    if closed:
                        try:
                            self._ctx = await self._launch()
                            return self._ctx
                        except Exception as retry_exc:
                            exc = retry_exc
                    await self._teardown_pw()
                    raise BrowserBusy(
                        "The portal browser profile is in use by a window this "
                        "app didn't start. Close any leftover portal windows "
                        "and try again."
                    ) from exc
                await self._teardown_pw()
                from . import bootstrap
                if bootstrap.looks_like_missing_browser(exc):
                    raise BrowserMissing(
                        "The private browser this app drives hasn't been "
                        "downloaded yet (about 130 MB, once). Click \"Download "
                        "browser\" on the Dashboard."
                    ) from exc
                raise
            return self._ctx

    async def _launch(self):
        # Grant multiple-downloads before the window exists. Chrome asks
        # "Download multiple files?" the second time a page downloads without a
        # click, and a prompt that appears mid-run silently drops every file
        # behind it.
        allow_automatic_downloads(self.profile_dir)
        return await self._pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=False,
            accept_downloads=True,
            downloads_path=self._downloads_path,
            viewport={"width": 1400, "height": 950},
        )

    _downloads_path: str | None = None

    def set_downloads_path(self, path) -> None:
        """Where Chromium spools downloads before we rename them into place.

        Only takes effect on the next launch, so it is set before starting.
        """
        self._downloads_path = str(path) if path else None

    async def _teardown_pw(self) -> None:
        if self._pw:
            try:
                await self._pw.stop()
            finally:
                self._pw = None

    async def page(self):
        ctx = await self.start()
        if ctx.pages:
            return ctx.pages[0]
        return await ctx.new_page()

    async def stop(self) -> None:
        async with self._lock:
            if self._ctx:
                try:
                    await self._ctx.close()
                finally:
                    self._ctx = None
            if self._pw:
                try:
                    await self._pw.stop()
                finally:
                    self._pw = None

    @property
    def running(self) -> bool:
        return self._ctx is not None


# What the case page can be showing.
READY = "ready"            # docket content is present
SIGNED_OUT = "signed_out"  # portal is offering Sign In, no case data
LOADING = "loading"        # the "Please wait…" spinner
CAPTCHA = "captcha"        # the portal is challenging us as a bot
EMPTY = "empty"            # signed in, page settled, but nothing recognizable
UNKNOWN = "unknown"

# Hosts and phrases that mean a bot-detection challenge is on screen. The app
# only ever *reports* this — a challenge is the site asking a human to prove
# they are one, so it is for the person at the keyboard to answer, in the
# visible window, or not at all.
CAPTCHA_HOSTS = ("captcha-delivery.com", "datadome", "hcaptcha.com",
                 "recaptcha", "challenges.cloudflare.com", "perimeterx",
                 "px-cdn", "arkoselabs.com")

# Read positively — does the page actually contain docket content — rather than
# looking for a login form. The signed-out case page shows a "Sign In / Register"
# link and no password field at all, so a form-based check calls it logged in and
# the app then parses an empty page and reports success.
STATE_JS = r"""
() => {
  const text = (document.body.innerText || '');
  const low = text.toLowerCase();
  const isDocBtn = (b) => {
    const t = (b.textContent || '').trim();
    return t === 'Document' || t === 'Documents';
  };
  const docButtons = [...document.querySelectorAll('button')].filter(isDocBtn).length;
  const rows = document.querySelectorAll('article, tr, [role="row"]').length;
  return {
    docButtons,
    rows,
    chars: text.length,
    spinner: low.includes('please wait') &&
             (low.includes('do not select refresh') || low.includes('back button')),
    // Decisive: the portal only offers this when there is no session.
    signInText: low.includes('sign in / register') || low.includes('sign in/register'),
    // Weak: a login link can sit in a header on pages that are perfectly fine.
    signInLink: !!document.querySelector('a[href*="login" i], a[href*="signin" i]'),
    hasDocketWord: low.includes('docket'),
    sample: text.replace(/\s+/g, ' ').trim().slice(0, 300),
  };
}
"""


async def page_state(page) -> tuple[str, dict]:
    """Classify the current case page. Returns (state, signals).

    Content signals are taken across all frames, because the portal renders
    parts of the page in iframes and a top-level-only read reports a perfectly
    good docket as empty.
    """
    url = (page.url or "").lower()
    if "login" in url or "signin" in url or "sign-in" in url:
        return SIGNED_OUT, {"reason": "redirected to a sign-in URL"}
    try:
        s = await page.evaluate(STATE_JS)
    except Exception as exc:
        return UNKNOWN, {"reason": str(exc)[:200]}

    frames = getattr(page, "frames", None) or []
    challenge = [f for f in frames
                 if any(h in (getattr(f, "url", "") or "").lower()
                        for h in CAPTCHA_HOSTS)]
    for frame in frames:
        if frame is getattr(page, "main_frame", None):
            continue
        try:
            fs = await frame.evaluate(STATE_JS)
        except Exception:
            continue        # cross-origin or torn down; not fatal
        s["docButtons"] = max(s["docButtons"], fs["docButtons"])
        s["rows"] = max(s["rows"], fs["rows"])
        s["chars"] = max(s["chars"], fs["chars"])
        s["hasDocketWord"] = s["hasDocketWord"] or fs["hasDocketWord"]

    # A challenge only matters when the docket isn't already there; a stray
    # challenge frame on a fully rendered page shouldn't block a good run.
    if challenge and not s["docButtons"]:
        s["captchaUrl"] = (getattr(challenge[0], "url", "") or "")[:200]
        return CAPTCHA, s

    if s["docButtons"] or (s["hasDocketWord"] and s["rows"] > 5):
        return READY, s
    # "Sign In / Register" outranks the spinner: the signed-out case page shows
    # both at once, and waiting out the spinner there just burns the timeout
    # before reaching the same conclusion.
    if s.get("signInText"):
        return SIGNED_OUT, s
    if s["spinner"]:
        return LOADING, s
    if s.get("signInLink"):
        return SIGNED_OUT, s
    return EMPTY, s


async def wait_for_case_page(page, timeout_ms: int = 45000) -> tuple[str, dict]:
    """Poll until the page settles into a definite state.

    The portal shows its "Please wait…" spinner both while loading and while
    signed out, so a single early read cannot tell the two apart — it has to be
    given time to resolve one way or the other.
    """
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    state, signals = UNKNOWN, {}
    while time.monotonic() < deadline:
        state, signals = await page_state(page)
        if state in (READY, SIGNED_OUT, CAPTCHA):
            return state, signals
        await page.wait_for_timeout(1000)
    # Still spinning when the clock ran out: on this portal that means the
    # session isn't valid, because a signed-in page resolves in seconds.
    if state == LOADING:
        return SIGNED_OUT, {**signals, "reason": "stuck on the loading spinner"}
    return state, signals


async def goto_case(page, case_number: str,
                   timeout_ms: int = 45000) -> tuple[str, dict]:
    """Navigate to the case detail page and report what state it settled into."""
    await page.goto(config.case_url(case_number), timeout=timeout_ms,
                    wait_until="domcontentloaded")
    return await wait_for_case_page(page, timeout_ms)


# Module-level singleton — one visible browser window for the whole app.
browser = Browser()
