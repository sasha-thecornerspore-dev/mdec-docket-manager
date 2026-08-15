"""AI analysis of filings via Claude — works with EITHER:

- **api**: an Anthropic API key (stored in Windows Credential Manager), via the
  official `anthropic` SDK; or
- **subscription**: the user's claude.ai subscription (Pro/Max), by shelling
  out to the logged-in Claude Code CLI in non-interactive print mode
  (`claude -p --output-format json`). No API key needed — just `claude` on
  PATH and signed in.

`analysis.backend` in Settings picks: "auto", "api", or "subscription".

**"auto" prefers the subscription.** If the Claude Code CLI is on PATH and
signed in, it is used even when an API key happens to be stored — the
subscription is already paid for, while the API bills per token. The stored
key is the fallback, not the first choice. Force either with "api" /
"subscription" if you want the other one.

Everything produced here is INFORMATIONAL, NOT LEGAL ADVICE, and the prompt +
UI + docs all say so.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
import shutil

from .. import config

MAX_DOC_CHARS = 150_000   # keep well inside the context window
CLI_TIMEOUT_S = 600       # print-mode turns on hard docs can run minutes

SYSTEM = (
    "You are a meticulous litigation-support assistant helping a self-represented "
    "party track their own court case. You summarize filings, extract dates and "
    "deadlines, and suggest procedural next steps to discuss with a lawyer. "
    "You are not a lawyer and your output is informational, not legal advice — "
    "when a filing has significant legal consequences, say so and recommend "
    "consulting counsel. Be concrete and cite the document's own language where "
    "it matters."
)

DOC_PROMPT = """Case: {case_number} ({caption})
Docket entry #{seq} — filed {file_date} — "{entry_name}"
Document title: "{title}"

Analyze the document text below. Respond with ONLY a JSON object:
{{
  "summary": "3-6 sentence plain-English summary: what this filing is, who filed it, what it asks for or orders, and its procedural significance",
  "deadlines": [{{"date": "YYYY-MM-DD or empty if unknown", "description": "what is due/happening"}}],
  "recommendations": "concrete suggested next steps for the case owner, as a short bulleted list in markdown; note anything time-sensitive first"
}}

DOCUMENT TEXT:
{text}
"""

CASE_PROMPT = """Case: {case_number} ({caption})


Below is the docket (sequence, date, entry name) and stored summaries of analyzed
documents. Write a "state of the case" briefing in markdown: current procedural
posture, active disputes/pending motions, upcoming or likely deadlines, and a
prioritized list of suggested next steps. Flag anything time-sensitive at the top.

{docket}
"""


class AnalyzerNotConfigured(Exception):
    """No usable Claude backend. The message explains exactly what to set up."""


@functools.lru_cache(maxsize=1)
def _claude_cli() -> str | None:
    """Cached PATH lookup — the UI polls status, and `which` walks PATH."""
    return shutil.which("claude")


def resolve_backend(cfg: dict) -> tuple[str, str]:
    """Return ('api', key) or ('cli', path-to-claude). Raises with a clear fix."""
    pref = cfg["analysis"].get("backend", "auto")
    api_key = config.get_secret("anthropic_api_key")
    cli = _claude_cli()
    if pref == "api":
        if api_key:
            return "api", api_key
        raise AnalyzerNotConfigured(
            "Backend is set to 'api' but no Anthropic API key is stored — add it "
            "in Settings, or switch the backend to 'subscription'.")
    if pref == "subscription":
        if cli:
            return "cli", cli
        raise AnalyzerNotConfigured(
            "Backend is set to 'subscription' but the Claude Code CLI ('claude') "
            "was not found on PATH. Install Claude Code and sign in with your "
            "Claude subscription (run: claude), or switch the backend to 'api'.")
    # auto: prefer the subscription the user already pays for, and fall back to
    # the metered API key only when the CLI is unavailable. Choosing the key
    # first would silently bill per token for work a Pro/Max plan already
    # covers, which is a surprising default for a desktop app.
    if cli:
        return "cli", cli
    if api_key:
        return "api", api_key
    raise AnalyzerNotConfigured(
        "No Claude backend available. Install the Claude Code CLI and sign in "
        "with your Claude subscription (run: claude), or store an Anthropic "
        "API key in Settings.")


async def _complete(cfg: dict, prompt: str, max_tokens: int) -> str:
    backend, cred = resolve_backend(cfg)
    model = cfg["analysis"]["model"]
    if backend == "api":
        return await _complete_api(cred, model, prompt, max_tokens)
    return await _complete_cli(cred, model, prompt)


async def _complete_api(api_key: str, model: str, prompt: str,
                        max_tokens: int) -> str:
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=api_key)
    kwargs = dict(model=model, max_tokens=max_tokens, system=SYSTEM,
                  messages=[{"role": "user", "content": prompt}])
    try:
        # Server-side refusal fallback (beta): if the model's safety classifiers
        # decline (possible on Opus 5-family), re-run on the recommended model
        # automatically instead of failing the analysis.
        msg = await client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            **kwargs)
    except Exception:
        msg = await client.messages.create(**kwargs)  # older SDK / non-beta org
    if getattr(msg, "stop_reason", None) == "refusal":
        raise RuntimeError("Claude declined to analyze this document "
                           "(safety refusal).")
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", "") == "text")


async def _complete_cli(cli_path: str, model: str, prompt: str) -> str:
    """Claude Code CLI print mode. Prompt goes over stdin (Windows command
    lines cap at ~32K chars; document text is far larger). The system framing
    is prepended to the prompt. `--output-format json` returns an envelope
    whose `result` field is the reply text."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model or ""):
        raise RuntimeError(f"Refusing to pass unusual model string to the CLI: "
                           f"{model!r}")
    proc = await asyncio.create_subprocess_shell(
        f'"{cli_path}" -p --output-format json --model {model}',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = (SYSTEM + "\n\n---\n\n" + prompt).encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload), timeout=CLI_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Claude CLI timed out after {CLI_TIMEOUT_S}s.")
    if proc.returncode != 0:
        raise RuntimeError(
            "Claude CLI failed (are you signed in? run `claude` once "
            f"interactively): {stderr.decode('utf-8', 'replace')[:500]}")
    try:
        data = json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise RuntimeError("Claude CLI returned unparseable output: "
                           f"{stdout[:300]!r}")
    if data.get("is_error") or "result" not in data:
        raise RuntimeError(f"Claude CLI error: {str(data)[:500]}")
    return data["result"]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("model returned no JSON object")
    return json.loads(m.group(0))


async def analyze_document(cfg: dict, case: dict, entry: dict,
                           title: str, text: str) -> dict:
    """Returns {summary, deadlines: [...], recommendations, model}."""
    prompt = DOC_PROMPT.format(
        case_number=case.get("case_number", ""), caption=case.get("caption", ""),
        seq=entry.get("seq", "?"), file_date=entry.get("file_date", "?"),
        entry_name=entry.get("name", ""), title=title,
        text=(text or "(no extractable text — likely a scan; enable OCR)")[:MAX_DOC_CHARS],
    )
    raw = await _complete(cfg, prompt, max_tokens=3000)
    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        data = {"summary": raw.strip()[:4000], "deadlines": [],
                "recommendations": ""}
    data.setdefault("summary", "")
    data.setdefault("deadlines", [])
    data.setdefault("recommendations", "")
    data["model"] = cfg["analysis"]["model"]
    return data


async def analyze_case(cfg: dict, case: dict, entries: list[dict],
                       analyses: list[dict]) -> str:
    summaries = {a["entry_id"]: a["summary"] for a in reversed(analyses)
                 if a.get("entry_id")}
    lines = []
    for e in entries:
        line = f'#{e["seq"]:04d} {e.get("file_date", ""):>10} {e.get("name", "")}'
        if e.get("comment"):
            line += f' — {e["comment"][:160]}'
        if e["id"] in summaries:
            line += f'\n    summary: {summaries[e["id"]][:400]}'
        lines.append(line)
    docket = "\n".join(lines)[-200_000:]
    prompt = CASE_PROMPT.format(case_number=case.get("case_number", ""),
                                caption=case.get("caption", ""), docket=docket)
    return await _complete(cfg, prompt, max_tokens=6000)
