"""Launch MDEC Docket Manager.

    python run.py              # start the server and open the UI in a browser
    python run.py --window     # open in a native desktop window (needs pywebview)
    python run.py --no-open    # just serve; open the URL yourself

The server binds to 127.0.0.1 only — nothing on your network can reach it.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

from mdec import config


def main() -> int:
    ap = argparse.ArgumentParser(description="MDEC Docket Manager")
    ap.add_argument("--window", action="store_true",
                    help="open in a native window instead of a browser tab")
    ap.add_argument("--no-open", action="store_true",
                    help="do not open any window; just serve")
    ap.add_argument("--port", type=int, default=None, help="override the port")
    args = ap.parse_args()

    cfg = config.load_config()
    host = cfg["server"]["host"]          # 127.0.0.1
    port = args.port or cfg["server"]["port"]
    url = f"http://{host}:{port}/"

    try:
        import uvicorn
        from mdec.server.app import app
    except ImportError as exc:
        print(f"Missing dependency: {exc}\n\nInstall with:\n"
              f"    pip install -r requirements.txt\n"
              f"    python -m playwright install chromium", file=sys.stderr)
        return 1

    print(f"MDEC Docket Manager — {url}")
    print(f"Settings and database: {config.app_dir()}")

    if args.window:
        try:
            import webview
        except ImportError:
            print("pywebview is not installed; falling back to a browser tab.\n"
                  "    pip install pywebview", file=sys.stderr)
            args.window = False

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port,
                                           log_level="info"))

    if args.window:
        import webview
        threading.Thread(target=server.run, daemon=True).start()
        _wait_for(server)
        webview.create_window("MDEC Docket Manager", url, width=1440, height=960)
        webview.start()
        return 0

    if not args.no_open:
        threading.Thread(target=lambda: (_wait_for(server), webbrowser.open(url)),
                         daemon=True).start()
    server.run()
    return 0


def _wait_for(server, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            return
        time.sleep(0.15)


if __name__ == "__main__":
    raise SystemExit(main())
