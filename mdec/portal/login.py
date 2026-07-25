"""Login management.

Two modes (config: login.mode):

- "attach": the app opens the portal window and the USER logs in manually; the
  persistent profile keeps the session alive across runs. If a check finds the
  session expired, the run is marked 'warning' and the UI tells the user to
  click "Open portal window" and log in again.

- "managed": credentials come from Windows Credential Manager; if the portal
  asks for an emailed verification code, we poll IMAP for it and type it in.
  Selectors are config-overridable (login.selectors) so portal UI changes are a
  settings tweak, not a code change.
"""

from __future__ import annotations

import asyncio

from .. import config
from . import browser as br
from . import email_code


class LoginFailed(Exception):
    pass


async def ensure_logged_in(cfg: dict, case_number: str, log=print) -> None:
    """Make sure the persistent session can see the case page. Raises otherwise."""
    page = await br.browser.page()
    ok = await br.goto_case(page, case_number)
    if ok:
        return
    if cfg["login"]["mode"] != "managed":
        raise br.NotLoggedIn(
            "Portal session expired. Click \"Open portal window\" and sign in "
            "(attach mode), or switch to managed login in Settings."
        )
    log("Session expired — attempting managed login")
    await _managed_login(page, cfg, log)
    ok = await br.goto_case(page, case_number)
    if not ok:
        raise LoginFailed("Managed login completed but the case page still "
                          "looks signed out. Check the selectors in Settings.")


async def _managed_login(page, cfg: dict, log=print) -> None:
    sel = cfg["login"]["selectors"]
    username = cfg["login"]["portal_username"]
    password = config.get_secret("portal_password")
    if not username or not password:
        raise LoginFailed("Managed login needs a portal username (Settings) and "
                          "portal password (stored in Credential Manager).")

    await page.goto(cfg["login"]["login_url"], wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)
    await page.fill(sel["username"], username)
    await page.fill(sel["password"], password)
    await page.click(sel["submit"])
    log("Submitted credentials")

    # Does the portal want an emailed verification code?
    try:
        await page.wait_for_selector(sel["code"], timeout=15000)
    except Exception:
        return  # no code step this time (recent session) — done

    log("Verification code requested — polling email")
    code = await _get_code(cfg)
    if not code:
        raise LoginFailed("No verification code arrived by email within the "
                          "timeout. Check the email settings (IMAP user/app "
                          "password, allowed senders).")
    await page.fill(sel["code"], code)
    await page.click(sel["code_submit"])
    await page.wait_for_timeout(2000)
    log("Verification code submitted")


async def _get_code(cfg: dict) -> str | None:
    em = cfg["email"]
    imap_password = config.get_secret("imap_password")
    if not em["imap_user"] or not imap_password:
        raise LoginFailed("Email code retrieval needs an IMAP user (Settings) and "
                          "an IMAP app password (stored in Credential Manager).")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: email_code.poll_for_code(
            em["imap_host"], em["imap_user"], imap_password,
            em["senders"], em["code_regex"], em["max_age_minutes"],
        ),
    )
