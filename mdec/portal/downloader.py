"""Document downloader — a Playwright port of the field-tested harvest loop.

Every hard lesson from the 950-document reference run is enforced here:

1. Pacing: 300 ms breathing room per document, small batches with pauses —
   going faster trips the portal's session-refresh throttle around the 475th
   rapid download.
2. Multi-file modals: ONE popup can hold many files (14 in the reference run);
   every `[aria-label*="Download document"]` button in the modal gets clicked.
3. Close/next-click race: always wait for `[role="dialog"]` to disappear
   before touching the next button.
4. View-only entries: a modal with no download buttons is logged, not an error.
5. Session-refresh spinner ("Please wait. Do not select refresh…"): detected,
   waited out, and the caller re-parses the page (buttons are re-tagged) and
   resumes — it is NOT a logout.
6. Verification: a download isn't "done" until the file exists on disk with
   non-zero size (the early-checkpoint lesson, automated for every file).

Playwright's expect_download replaces Chrome's download bar, so the old
"multi-download permission" prompt does not apply here.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path


class SessionRefresh(Exception):
    """The portal threw its 'Please wait…' throttle spinner. Wait and re-parse."""


@dataclass
class EntryDownload:
    button_index: int
    status: str = "ok"            # 'ok' | 'view_only' | 'no_modal' | 'error'
    files: list[dict] = field(default_factory=list)  # {title, path, sha256, size}
    error: str = ""


async def _dialog(frame):
    return await frame.query_selector('[role="dialog"]')


async def _close_any_dialog(frame) -> None:
    for _ in range(15):
        dlg = await _dialog(frame)
        if not dlg:
            return
        btn = await dlg.query_selector("button:has-text('Close')")
        if btn:
            await btn.click()
        await frame.wait_for_timeout(200)


async def _check_throttle(frame) -> None:
    try:
        body = (await frame.inner_text("body", timeout=3000)).lower()
    except Exception:
        return
    if "please wait" in body and "refresh" in body:
        raise SessionRefresh()


async def _click_and_watch(page, frame, button, watch_dir: Path,
                           timeout_s: float = 60.0) -> Path:
    """Click, then wait for a finished file to appear in `watch_dir`.

    Used when driving the user's own Chrome: that browser does its own
    downloading, so there is no Playwright download event to await — we watch
    where we told Chrome to put the files instead.
    """
    watch_dir = Path(watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in watch_dir.iterdir() if p.is_file()}
    await button.click()

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        await frame.wait_for_timeout(250)
        current = [p for p in watch_dir.iterdir() if p.is_file()]
        fresh = [p for p in current if p.name not in before]
        # .crdownload means Chrome is still writing it.
        done = [p for p in fresh if p.suffix.lower() != ".crdownload"]
        if done and not any(p.suffix.lower() == ".crdownload" for p in fresh):
            newest = max(done, key=lambda p: p.stat().st_mtime)
            size = newest.stat().st_size
            await frame.wait_for_timeout(200)      # let the last block flush
            if newest.stat().st_size == size and size > 0:
                return newest
    raise RuntimeError("no file appeared in the download folder within "
                       f"{int(timeout_s)}s")


async def download_entry(page, button_index: int, dest_dir: Path,
                         breathing_ms: int = 300, frame=None,
                         watch_dir: Path | None = None) -> EntryDownload:
    """Open one entry's modal, download every file in it, close, pace.

    `frame` is where the elements live (the docket can be inside an iframe);
    `page` stays the download source, because downloads are a page-level event
    no matter which frame triggered them.
    """
    frame = frame or page
    result = EntryDownload(button_index=button_index)
    dest_dir.mkdir(parents=True, exist_ok=True)
    await _close_any_dialog(frame)

    btn = await frame.query_selector(f'button[data-mdec-idx="{button_index}"]')
    if not btn:
        await _check_throttle(frame)
        result.status, result.error = "error", "button not found (page re-rendered?)"
        return result

    await btn.scroll_into_view_if_needed()
    await frame.wait_for_timeout(100)
    await btn.click()

    modal = None
    for _ in range(30):
        dlg = await _dialog(frame)
        if dlg and await dlg.query_selector('[aria-label*="Download document"]'):
            modal = dlg
            break
        await frame.wait_for_timeout(100)

    if not modal:
        stray = await _dialog(frame)
        if stray:
            result.status = "view_only"
            await _close_any_dialog(frame)
        else:
            await _check_throttle(frame)
            result.status = "no_modal"
        return result

    dl_buttons = await modal.query_selector_all('[aria-label*="Download document"]')
    for b in dl_buttons:
        label = (await b.get_attribute("aria-label")) or ""
        title = label.replace("Download document", "").strip()
        try:
            if watch_dir is not None:
                landed = await _click_and_watch(page, frame, b, watch_dir)
                tmp_path = dest_dir / f"__incoming__{button_index}_{len(result.files)}.pdf"
                dest_dir.mkdir(parents=True, exist_ok=True)
                landed.replace(tmp_path)
                suggested = landed.name
            else:
                async with page.expect_download(timeout=30000) as dl_info:
                    await b.click()
                download = await dl_info.value
                suggested = download.suggested_filename or f"{title or 'document'}.pdf"
                tmp_path = dest_dir / f"__incoming__{button_index}_{len(result.files)}.pdf"
                await download.save_as(str(tmp_path))
            size = tmp_path.stat().st_size
            if size == 0:
                raise RuntimeError("zero-byte download")
            sha = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
            result.files.append({
                "title": title or suggested,
                "suggested_filename": suggested,
                "path": str(tmp_path),
                "sha256": sha,
                "size": size,
            })
        except Exception as exc:  # keep going; caller sees partial + error
            result.status = "error"
            result.error = f"{title}: {exc}"
        await frame.wait_for_timeout(100)

    await _close_any_dialog(frame)
    for _ in range(25):
        if not await _dialog(frame):
            break
        await frame.wait_for_timeout(100)
    await frame.wait_for_timeout(breathing_ms)  # DO NOT REMOVE — throttle protection
    return result


async def download_many(page, button_indices: list[int], dest_dir: Path,
                        breathing_ms: int = 300, batch_size: int = 10,
                        batch_pause_s: float = 3.0, on_progress=None,
                        reparse=None, frame=None,
                        watch_dir: Path | None = None) -> list[EntryDownload]:
    """Download a list of entries with batch pacing and throttle recovery.

    `reparse` is an async callable that re-parses the page (re-tagging buttons)
    after a session-refresh spinner; without it a throttle aborts the run. It
    returns the frame to keep using, since a re-render can replace it.
    """
    frame = frame or page
    results: list[EntryDownload] = []
    for pos, idx in enumerate(button_indices):
        attempts = 0
        while True:
            try:
                res = await download_entry(page, idx, dest_dir, breathing_ms,
                                           frame=frame, watch_dir=watch_dir)
                break
            except SessionRefresh:
                attempts += 1
                if attempts > 3 or reparse is None:
                    res = EntryDownload(button_index=idx, status="error",
                                        error="session-refresh throttle, gave up")
                    break
                await asyncio.sleep(20)   # let the portal settle — field-tested ~15s
                refreshed = await reparse()
                if refreshed is not None:
                    frame = refreshed
        if res.status == "error" and attempts == 0:
            # one retry for transient failures (dropped download etc.)
            retry = await download_entry(page, idx, dest_dir, breathing_ms,
                                         frame=frame, watch_dir=watch_dir)
            if retry.status == "ok" and retry.files:
                res = retry
        results.append(res)
        if on_progress:
            await on_progress(pos + 1, len(button_indices), res)
        if (pos + 1) % batch_size == 0 and pos + 1 < len(button_indices):
            await asyncio.sleep(batch_pause_s)   # don't get greedy
    return results
