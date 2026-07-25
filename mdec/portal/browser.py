"""Playwright browser lifecycle (async API).

One persistent Chromium profile per install (under %APPDATA%) so a manual login
in *attach mode* survives restarts, and managed-mode logins rarely re-trigger
the email verification step. The window is always headful — the user can watch,
and attach mode requires them to type their password themselves.
"""

from __future__ import annotations

import asyncio

from .. import config


class NotLoggedIn(Exception):
    """Raised when the portal bounced us to a login page and we can't self-login."""


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
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                self.profile_dir,
                headless=False,
                accept_downloads=True,
                viewport={"width": 1400, "height": 950},
            )
            return self._ctx

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


async def looks_logged_in(page) -> bool:
    """Heuristic: on a case page we're fine; on a login/signin URL we're not."""
    url = (page.url or "").lower()
    if "login" in url or "signin" in url or "sign-in" in url:
        return False
    try:
        body = await page.inner_text("body", timeout=5000)
    except Exception:
        return False
    lowered = body.lower()
    if "sign in" in lowered and "password" in lowered:
        return False
    return True


async def goto_case(page, case_number: str, timeout_ms: int = 45000) -> bool:
    """Navigate to the case detail page. Returns whether we appear logged in."""
    await page.goto(config.case_url(case_number), timeout=timeout_ms,
                    wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)  # let the SPA settle
    return await looks_logged_in(page)


# Module-level singleton — one visible browser window for the whole app.
browser = Browser()
