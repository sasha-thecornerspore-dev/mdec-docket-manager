"""Entry point for the PyInstaller build.

Default (no arguments) is what the Start Menu shortcut runs: start the service if
it isn't running, then open the app window.

    MDECDocketManager.exe                 launch the app
    MDECDocketManager.exe --serve         serve only (no window)
    MDECDocketManager.exe --port 8675     use a specific port
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def _fix_streams() -> None:
    """A windowed PyInstaller build has no stdout/stderr — they are None, and
    anything that writes to them (print, uvicorn's log handler) raises. Same
    trap as pythonw.exe."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if getattr(sys, "stdin", None) is None:
        sys.stdin = open(os.devnull, encoding="utf-8")


def _log_crash(exc: BaseException) -> str:
    """Write the traceback where a user (or a bug report) can find it.

    A windowed build has nowhere to print, so without this a startup failure is
    just an app that doesn't open.
    """
    import traceback
    text = "".join(traceback.format_exception(exc))
    try:
        from mdec import config
        path = config.app_dir() / "startup-error.log"
    except Exception:
        path = Path(os.environ.get("TEMP", ".")) / "mdec-startup-error.log"
    try:
        from datetime import datetime
        path.write_text(
            f"{datetime.now().isoformat(timespec='seconds')}\n"
            f"frozen={getattr(sys, 'frozen', False)}\n"
            f"executable={sys.executable}\n\n{text}", encoding="utf-8")
    except OSError:
        pass
    return str(path)


def _alert(message: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message,
                                         "MDEC Docket Manager", 0x10)
    except Exception:
        pass


def main() -> int:
    multiprocessing.freeze_support()   # must precede anything that may spawn
    _fix_streams()

    argv = sys.argv[1:]
    port = None
    if "--port" in argv:
        i = argv.index("--port")
        if i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                port = None

    if "--serve" in argv:
        from mdec import serve
        args = ["--no-open"]
        if port:
            args += ["--port", str(port)]
        return serve.main(args)

    from mdec.desktop import launch
    return launch(port)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:                      # noqa: BLE001
        log = _log_crash(exc)
        _alert(f"MDEC Docket Manager could not start.\n\n"
               f"{type(exc).__name__}: {exc}\n\n"
               f"Full details were written to:\n{log}")
        sys.exit(1)
