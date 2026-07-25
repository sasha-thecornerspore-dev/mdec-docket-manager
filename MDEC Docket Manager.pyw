"""Desktop entry point. Double-click, or launch from the Start Menu shortcut.

The .pyw extension means Windows runs this with pythonw.exe — no console window.
Starts the service if it isn't already running, then opens the app window.
"""

import os
import sys
from pathlib import Path

# pythonw.exe gives us no standard streams at all: sys.stdout and sys.stderr are
# None. Anything that writes to them — print(), uvicorn's log handler — then dies
# with "NoneType has no attribute write", invisibly. Point them at the null
# device before importing anything that logs.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name, None) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
if getattr(sys, "stdin", None) is None:
    sys.stdin = open(os.devnull, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mdec.desktop import launch  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(launch())
