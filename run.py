"""Run MDEC Docket Manager from a terminal (the developer path).

Day to day, use the Desktop icon instead — see Install.cmd.

    python run.py              # serve and open the UI in a browser
    python run.py --app        # serve and open the chromeless app window
    python run.py --no-open    # serve only
    python run.py --port 8675  # different port

The server binds to 127.0.0.1 only — nothing on your network can reach it.
"""

from __future__ import annotations

import argparse
import sys

from mdec import serve


def main() -> int:
    ap = argparse.ArgumentParser(description="MDEC Docket Manager")
    ap.add_argument("--app", action="store_true",
                    help="open the chromeless app window (what the icon does)")
    ap.add_argument("--no-open", action="store_true", help="serve only")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    if args.app:
        from mdec.desktop import launch
        return launch(args.port)

    argv = ["--no-open"] if args.no_open else []
    if args.port:
        argv += ["--port", str(args.port)]
    return serve.main(argv)


if __name__ == "__main__":
    sys.exit(main())
