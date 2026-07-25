"""Settings and secret storage.

Settings live in %APPDATA%\\MDECDocketManager\\config.json.
Secrets never touch the JSON: they go to Windows Credential Manager via `keyring`
under the service name `mdec-docket-manager`, and the API never echoes them back.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

APP_NAME = "MDECDocketManager"
KEYRING_SERVICE = "mdec-docket-manager"

# The only secret slots that exist. Anything else is rejected.
SECRET_NAMES = ("portal_password", "imap_password", "anthropic_api_key")

CASESEARCH_URL = (
    "https://casesearch.courts.state.md.us/casesearch/case-detail-page?caseId={case_id}"
)

DEFAULTS: dict = {
    # Cases live in the database (one row each, with their own download folder).
    # Config only remembers which one the UI is looking at.
    "active_case_number": "",
    "folders": {
        # Parent folder for new cases: each gets <root>\<case-id>\ unless you
        # point it somewhere else.
        "downloads_root": "",
    },
    "schedule": {
        "enabled": True,
        "times": ["08:00", "17:00"],   # deliberately polite: 2x/day
    },
    "login": {
        "mode": "attach",         # "attach" (manual login, persistent session) | "managed"
        "portal_username": "",
        "login_url": "https://mdecportal.courts.state.md.us/MDEC/login.htm",
        # Selector overrides for managed login; portal UI changes shouldn't need a code change.
        "selectors": {
            "username": "input[name='username'], #username",
            "password": "input[type='password']",
            "submit": "button[type='submit'], input[type='submit']",
            "code": "input[name*='code' i], input[id*='code' i], input[autocomplete='one-time-code']",
            "code_submit": "button[type='submit'], input[type='submit']",
        },
    },
    "email": {
        "imap_host": "imap.gmail.com",
        "imap_user": "",
        "senders": ["courts.state.md.us", "mdcourts.gov"],
        "code_regex": r"\b(\d{6})\b",
        "max_age_minutes": 10,
    },
    "ocr": {"enabled": False, "language": "eng"},
    "rag": {
        "folder_enabled": False,
        "folder_path": "",
        "webhook_enabled": False,
        "webhook_url": "",
        "chroma_enabled": False,
        "chroma_path": "",
        "chroma_collection": "mdec-docket",
    },
    "analysis": {
        "enabled": False,
        # "auto": use the stored API key if present, else the logged-in Claude
        # Code CLI (Claude subscription). Or force "api" / "subscription".
        "backend": "auto",
        "model": "claude-opus-5",
        "auto_analyze_new": True,
    },
    "server": {"host": "127.0.0.1", "port": 8674},
    "downloader": {
        # Field-tested pacing — see docs/TROUBLESHOOTING.md before changing.
        "breathing_ms": 300,
        "batch_size": 10,
        "batch_pause_s": 3.0,
    },
}


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return app_dir() / "config.json"


def _merge(defaults: dict, loaded: dict) -> dict:
    out = copy.deepcopy(defaults)
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    p = config_path()
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            cfg = _merge(DEFAULTS, loaded)
            _carry_forward_single_case(cfg, loaded)
            if not cfg["folders"]["downloads_root"]:
                cfg["folders"]["downloads_root"] = str(app_dir() / "downloads")
            return cfg
        except (json.JSONDecodeError, OSError):
            pass  # fall through to defaults; a corrupt file shouldn't brick the app
    cfg = copy.deepcopy(DEFAULTS)
    cfg["folders"]["downloads_root"] = str(app_dir() / "downloads")
    return cfg


def _carry_forward_single_case(cfg: dict, loaded: dict) -> None:
    """Adopt a pre-multi-case config: the old single `case` block becomes the
    active case, and its `folders.downloads` becomes that case's folder."""
    old = loaded.get("case") or {}
    number = old.get("case_number", "")
    if number and not cfg.get("active_case_number"):
        cfg["active_case_number"] = number
    cfg.pop("case", None)
    old_folder = (loaded.get("folders") or {}).get("downloads", "")
    if old_folder and not cfg["folders"]["downloads_root"]:
        cfg["folders"]["downloads_root"] = str(Path(old_folder).parent)
    if number and old_folder:
        # Recorded so the DB can pick it up on next load without losing it.
        cfg["_migrate_case"] = {
            "case_number": number, "caption": old.get("caption", ""),
            "court": old.get("court", ""), "downloads": old_folder,
        }


def default_case_folder(case_number: str, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    root = cfg["folders"]["downloads_root"] or str(app_dir() / "downloads")
    return str(Path(root) / normalize_case_id(case_number))


def save_config(cfg: dict) -> None:
    for name in SECRET_NAMES:  # belt-and-suspenders: secrets must never land in JSON
        _strip_key(cfg, name)
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def consume_case_migration() -> dict | None:
    """Return (once) the pre-multi-case case block so the DB can adopt it."""
    cfg = load_config()
    pending = cfg.pop("_migrate_case", None)
    if pending:
        save_config(cfg)
    return pending


def _strip_key(d: dict, key: str) -> None:
    d.pop(key, None)
    for v in d.values():
        if isinstance(v, dict):
            _strip_key(v, key)


def normalize_case_id(case_number: str) -> str:
    """'C-01-CV-24-001234' -> 'C01cv24001234' (portal URL format)."""
    s = re.sub(r"[^A-Za-z0-9]", "", case_number.strip())
    if not s:
        return ""
    return s[0].upper() + s[1:].lower()


def case_url(case_number: str) -> str:
    return CASESEARCH_URL.format(case_id=normalize_case_id(case_number))


# --- secrets ---------------------------------------------------------------

def set_secret(name: str, value: str) -> None:
    if name not in SECRET_NAMES:
        raise ValueError(f"Unknown secret slot: {name}")
    import keyring
    keyring.set_password(KEYRING_SERVICE, name, value)


def get_secret(name: str) -> str | None:
    if name not in SECRET_NAMES:
        raise ValueError(f"Unknown secret slot: {name}")
    import keyring
    return keyring.get_password(KEYRING_SERVICE, name)


def delete_secret(name: str) -> None:
    if name not in SECRET_NAMES:
        raise ValueError(f"Unknown secret slot: {name}")
    import keyring
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass


def secret_status() -> dict[str, bool]:
    """Which secrets are set — booleans only, values are never returned."""
    return {name: get_secret(name) is not None for name in SECRET_NAMES}
