"""Serve the app. `python -m mdec.serve` — used by the desktop launcher.

Split from run.py so the launcher can start a bare server process without
inheriting run.py's browser-opening behavior.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import threading
import time
import webbrowser

from . import config


def _write_runtime(port: int) -> None:
    """Record where we're listening so the desktop launcher can find us even if
    the configured port was taken and we moved to another one."""
    path = config.app_dir() / "runtime.json"
    try:
        path.write_text(json.dumps({"port": port, "pid": os.getpid()}),
                        encoding="utf-8")
    except OSError:
        return
    atexit.register(_clear_runtime, path, os.getpid())


def _clear_runtime(path, owner_pid: int) -> None:
    """Only remove the file if it's still ours — a newer instance may own it."""
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if current.get("pid") == owner_pid:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MDEC Docket Manager server")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-open", action="store_true",
                    help="serve without opening a browser")
    ap.add_argument("--app", action="store_true",
                    help="open the chromeless app window when ready")
    args = ap.parse_args(argv)

    cfg = config.load_config()
    host = cfg["server"]["host"]
    port = args.port or cfg["server"]["port"]
    url = f"http://{host}:{port}/"

    try:
        import uvicorn
        from .server.app import app
    except ImportError as exc:
        print(f"Missing dependency: {exc}\n\nRun Install.cmd, or:\n"
              f"    pip install -r requirements.txt\n"
              f"    python -m playwright install chromium", file=sys.stderr)
        return 1

    _write_runtime(port)
    # Quieter when there's no console to read it (the desktop launcher path).
    headless = not sys.stdout or not sys.stdout.isatty()
    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port,
        log_level="warning" if headless else "info"))
    if not args.no_open:
        def _open() -> None:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not getattr(server, "started", False):
                time.sleep(0.1)
            if args.app:
                from .desktop import open_window
                open_window(url)
            else:
                webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    print(f"MDEC Docket Manager — {url}")
    print(f"Settings and database: {config.app_dir()}")
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
