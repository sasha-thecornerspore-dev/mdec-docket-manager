"""Desktop launch: start the server if it isn't running, open an app window.

The window is Edge or Chrome in `--app=` mode — a real chromeless window with its
own taskbar button and our favicon, and no browser UI. That needs no extra
dependency, which matters: the alternative (pywebview + a GUI toolkit) is another
install to go wrong on a machine that just wants to read its docket.

Reopening the icon while the app is already running reuses the running server and
just opens a fresh window, so double-clicking twice can't start two monitors.

Closing the window does **not** stop the server, deliberately — scheduled checks
should keep running. "Quit" in Settings shuts it down.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

APP_NAME = "MDEC Docket Manager"

BROWSER_CANDIDATES = (
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
)


def base_url(port: int | None = None) -> str:
    cfg = config.load_config()
    return f"http://{cfg['server']['host']}:{port or cfg['server']['port']}/"


def runtime_path():
    return config.app_dir() / "runtime.json"


def read_runtime() -> dict | None:
    """Where a running instance said it was listening."""
    import json
    try:
        return json.loads(runtime_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def server_is_up(url: str, timeout: float = 1.5) -> bool:
    """Probe /api/ping, not /api/status — status does feature detection
    (keyring, OCR) that can take seconds on a cold process, and the window
    should open when the server is ready, not when detection finishes."""
    try:
        with urllib.request.urlopen(url + "api/ping", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def port_is_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host: str, preferred: int) -> int | None:
    """The configured port, or the next free one after it.

    Without this, an unrelated program holding 8674 makes the app look broken —
    it would start, fail to bind, and die with no console to say why.
    """
    for candidate in range(preferred, preferred + 20):
        if port_is_free(host, candidate):
            return candidate
    return None


def wait_for_server(url: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_up(url):
            return True
        time.sleep(0.25)
    return False


def find_running() -> str | None:
    """URL of an instance that's already serving, if any."""
    cfg = config.load_config()
    host = cfg["server"]["host"]
    candidates = []
    rt = read_runtime()
    if rt and rt.get("port"):
        candidates.append(int(rt["port"]))
    if cfg["server"]["port"] not in candidates:
        candidates.append(cfg["server"]["port"])
    for port in candidates:
        url = f"http://{host}:{port}/"
        if server_is_up(url, timeout=1.0):
            return url
    return None


def find_browser() -> str | None:
    for raw in BROWSER_CANDIDATES:
        p = Path(os.path.expandvars(raw))
        if p.is_file():
            return str(p)
    return None


def spawn_server(port: int | None = None) -> subprocess.Popen | None:
    """Start the service as a separate detached process.

    Only needed when the caller has a console it wants to keep (`run.py --app`).
    The desktop icon runs the server in-process instead — see `launch()` — which
    avoids paying Python's start-up cost twice.
    """
    root = Path(__file__).resolve().parent.parent
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    cmd = [str(pythonw if pythonw.is_file() else exe), "-m", "mdec.serve", "--no-open"]
    if port:
        cmd += ["--port", str(port)]

    # pythonw is a GUI-subsystem binary so no console appears anyway; DETACHED
    # lets the service outlive this launcher. Don't also pass CREATE_NO_WINDOW —
    # Windows treats the combination as invalid.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
    try:
        return subprocess.Popen(cmd, cwd=str(root), creationflags=flags,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError:
        return None


def open_window(url: str) -> bool:
    """Chromeless app window. Falls back to the default browser."""
    browser = find_browser()
    if browser:
        profile = config.app_dir() / ".appwindow"
        profile.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen([
                browser,
                f"--app={url}",
                f"--user-data-dir={profile}",   # own window, own taskbar button
                "--window-size=1440,960",
                "--no-first-run",
                "--no-default-browser-check",
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    import webbrowser
    return webbrowser.open(url)


def alert(message: str) -> None:
    """Say something when there's no console to print to."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def launch(port: int | None = None) -> int:
    cfg = config.load_config()
    host = cfg["server"]["host"]

    # Already running? Just show it. Double-clicking the icon twice must not
    # start a second monitor.
    if port is None:
        running = find_running()
        if running:
            open_window(running)
            return 0
    elif server_is_up(base_url(port)):
        open_window(base_url(port))
        return 0

    chosen = port or pick_port(host, cfg["server"]["port"])
    if chosen is None:
        alert(f"Ports {cfg['server']['port']}–{cfg['server']['port'] + 19} are all "
              f"in use, so {APP_NAME} has nowhere to listen.\n\n"
              f"Close whatever is using them, or set a different port in "
              f"Settings.")
        return 1

    # Become the service. Running it here rather than spawning a second Python
    # halves cold-start time, and this process is already invisible (pythonw).
    # serve() opens the app window itself once the port is accepting.
    from . import serve
    try:
        return serve.main(["--port", str(chosen), "--app"])
    except Exception as exc:
        alert(f"{APP_NAME} could not start.\n\n{type(exc).__name__}: {exc}\n\n"
              f"To see the full error, open a terminal in\n"
              f"{Path(__file__).resolve().parent.parent}\nand run:\n"
              f"    python run.py\n\n"
              f"Missing packages are the usual cause; Install.cmd fixes those.")
        return 1
