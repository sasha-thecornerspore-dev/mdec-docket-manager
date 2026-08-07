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


def _log_to_file() -> None:
    """Send app and uvicorn logs to %APPDATA%\\MDECDocketManager\\app.log."""
    import logging
    import logging.handlers
    path = config.app_dir() / "app.log"
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "mdec"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.propagate = True

    def _hook(exc_type, exc, tb):
        logging.getLogger("mdec").critical("unhandled exception",
                                           exc_info=(exc_type, exc, tb))
    sys.excepthook = _hook


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
    # Without a console there is nowhere for a failure to show up, so log to a
    # file. It is also the thing to ask for in a bug report.
    headless = not sys.stdout or not sys.stdout.isatty()
    if headless:
        _log_to_file()
    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port,
        log_level="info" if headless else "info"))
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

    import logging
    log = logging.getLogger("mdec.serve")
    log.info("starting on %s (frozen=%s, pid=%s)", url,
             getattr(sys, "frozen", False), os.getpid())
    print(f"MDEC Docket Manager — {url}")
    print(f"Settings and database: {config.app_dir()}")
    try:
        server.run()
    except BaseException:
        log.critical("server.run() raised", exc_info=True)
        raise
    # Reaching here means uvicorn stopped. On the desktop path that is a bug
    # unless the user asked to quit, so record why.
    log.warning("server.run() returned — should_exit=%s force_exit=%s",
                getattr(server, "should_exit", "?"),
                getattr(server, "force_exit", "?"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
