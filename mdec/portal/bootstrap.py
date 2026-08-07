"""Make sure Playwright's Chromium is present, and fetch it if not.

From source you'd run `python -m playwright install chromium`. The installed
build has no interpreter and no pip, so it drives Playwright's bundled node
driver directly — otherwise a packaged app could never do its one job.

The download is ~130 MB, so it is never silent: the UI has an explicit button,
and a check that finds the browser missing says so rather than failing obscurely.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Playwright's specific wording when the browser binaries aren't downloaded.
# Keep these narrow: "browsertype.launch" appears in almost every Playwright
# launch error, so matching it would report a crashed or sandboxed browser as
# "not downloaded" and send the user off to re-download 130 MB for nothing.
MISSING_MARKERS = (
    "executable doesn't exist",
    "please run the following command to download new browsers",
    "browser has not been downloaded",
)


def looks_like_missing_browser(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(m in text for m in MISSING_MARKERS)


def chromium_present() -> bool:
    """Is Playwright's Chromium downloaded?

    Blocking, and it must NOT be called from inside a running event loop —
    Playwright's sync API refuses to start there, which previously made the app
    report the browser as missing while it was happily driving it. Callers in
    async code use a thread executor (see `chromium_present_async`).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
            return bool(path) and os.path.exists(path)
    except Exception:
        # Starting the driver can fail for reasons that have nothing to do with
        # whether the browser is downloaded (notably inside a frozen build).
        # Falling back to the filesystem stops the app claiming the browser is
        # missing and pushing a pointless 130 MB download.
        return _chromium_on_disk()


def _chromium_on_disk() -> bool:
    """Is there a Chromium under Playwright's browsers directory?"""
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not base:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return False
        base = str(Path(local) / "ms-playwright")
    root = Path(base)
    if not root.is_dir():
        return False
    return any(root.glob("chromium-*/chrome-win/chrome.exe"))


async def chromium_present_async() -> bool:
    """Thread-safe version for request handlers."""
    import asyncio
    return await asyncio.get_running_loop().run_in_executor(
        None, chromium_present)


def _driver_command() -> list[str] | None:
    """The node + cli.js pair Playwright ships, so we can run its CLI frozen."""
    try:
        from playwright._impl._driver import compute_driver_executable
    except ImportError:
        return None
    try:
        result = compute_driver_executable()
    except Exception:
        return None
    # Newer Playwright returns (node, cli.js); older returns a single path.
    if isinstance(result, (tuple, list)):
        return [str(x) for x in result]
    return [str(result)]


def install_chromium(timeout_s: int = 1800) -> tuple[bool, str]:
    """Download Chromium. Returns (ok, message). Blocking — run in a thread."""
    base = _driver_command()
    if base is None:
        return False, ("Playwright is not available in this build, so the "
                       "browser cannot be installed. Run the app from source.")
    try:
        from playwright._impl._driver import get_driver_env
        env = get_driver_env()
    except Exception:
        env = os.environ.copy()

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(base + ["install", "chromium"], env=env,
                              capture_output=True, text=True,
                              timeout=timeout_s, creationflags=flags)
    except subprocess.TimeoutExpired:
        return False, f"The browser download timed out after {timeout_s // 60} minutes."
    except OSError as exc:
        return False, f"Could not run the Playwright installer: {exc}"

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return False, f"The browser download failed: {tail}"
    if not chromium_present():
        return False, ("The download reported success but Chromium still isn't "
                       "where Playwright expects it.")
    return True, "Browser installed. Checks can run now."
