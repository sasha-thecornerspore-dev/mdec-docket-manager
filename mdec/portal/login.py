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


SIGNED_OUT_HELP = (
    "You are not signed in to the Maryland Judiciary portal, so the case page "
    "has no docket on it.\n\n"
    "Click \"Open portal window\", sign in there (the app never handles your "
    "password in attach mode), wait until you can see the case, then run the "
    "check again. The session is remembered afterwards."
)


CAPTCHA_HELP = (
    "The portal is showing a security check (bot detection) instead of your "
    "case, so there is no docket to read.\n\n"
    "This app will not answer that challenge for you — it is the site asking a "
    "human to confirm they are one. Click \"Open portal window\" and complete "
    "it yourself, then run the check again.\n\n"
    "If the challenge comes back every time, the portal is refusing automated "
    "browsing for your connection, and checks cannot run until that changes."
)


async def ensure_logged_in(cfg: dict, case_number: str, log=print) -> None:
    """Make sure the persistent session can see the case page. Raises otherwise."""
    page = await br.browser.page()
    state, signals = await br.goto_case(page, case_number)
    if state == br.READY:
        return
    if state == br.CAPTCHA:
        raise br.NotLoggedIn(CAPTCHA_HELP)
    if state == br.EMPTY:
        raise br.NotLoggedIn(
            "The case page loaded but contains no docket entries.\n\n"
            "Check the case number in Settings → Cases is exactly as printed on "
            "the docket. If it is right, you may not be signed in — click "
            "\"Open portal window\" and confirm you can see the case there.")
    if cfg["login"]["mode"] != "managed":
        raise br.NotLoggedIn(SIGNED_OUT_HELP)

    log("Not signed in — attempting managed login")
    await _managed_login(page, cfg, log)
    state, _ = await br.goto_case(page, case_number)
    if state != br.READY:
        raise LoginFailed(
            "Managed login ran but the case page still shows no docket. "
            "Either the credentials were rejected or the sign-in selectors in "
            "Settings no longer match the portal. Watch the browser window "
            "during a check to see where it stops.")


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
