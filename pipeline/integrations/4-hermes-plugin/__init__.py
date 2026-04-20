"""kairos-obsidian-bridge — Hermes plugin replacing agent-worker's post-Hermes hook.

Registers:
  - on_session_end → writes critique + extracts learnings to Obsidian vault
  - on_session_start → logs trace start
  - post_tool_call → tallies tool_use_events for code-review-graph rubric
  - /vault-search, /vault-recent, /vault-write slash commands

Replaces /usr/local/bin/agent-worker's monkey-patched post-run logic with proper
Hermes lifecycle hooks. Cleaner, plugin-managed (enable/disable/audit), and
opt-in per Hermes plugin security model.

Activation:
    hermes plugins install /pipeline/hermes/plugins/kairos-obsidian-bridge
    hermes plugins enable kairos-obsidian-bridge

Per-profile activation (set in profile config.yaml):
    plugins:
      enabled:
        - kairos-obsidian-bridge
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


VAULT_PATH = Path("/opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline")
AGENT_ENV = "AGENT"
TRACE_ENV = "KAIROS_TRACE_ID"
GAP_ENV = "KAIROS_GAP_ID"
PHASE_ENV = "KAIROS_PHASE"

# Secret patterns to redact before writing to Obsidian
SECRET_PATTERNS = [
    re.compile(r"sk-cp-[A-Za-z0-9_\-]{50,}"),
    re.compile(r"\b\d{10}:[A-Za-z0-9_\-]{30,}\b"),  # Telegram tokens
    re.compile(r"Adminadmin@\d+"),
    re.compile(r"karios@\d+"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub PATs
]


def _redact(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text = pat.sub("<REDACTED>", text)
    return text


def _agent() -> str:
    return os.environ.get(AGENT_ENV, "unknown")


def _trace() -> str:
    return os.environ.get(TRACE_ENV, "")


def _gap() -> str:
    return os.environ.get(GAP_ENV, "")


def _phase() -> str:
    return os.environ.get(PHASE_ENV, "")


# ─── Hermes lifecycle hooks ──────────────────────────────────────────────────

def on_session_start(context: Dict[str, Any]) -> None:
    """Called when a new Hermes session begins. Light log to Obsidian."""
    if not VAULT_PATH.exists():
        return
    agent = _agent()
    trace = _trace()
    gap = _gap()
    phase = _phase()
    log_dir = VAULT_PATH / "session-starts"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    log_dir / f"{ts}-{agent}-{gap or 'no-gap'}.md"
    (log_dir / f"{ts}-{agent}-{gap or 'no-gap'}.md").write_text(
        f"---\ntype: session-start\nagent: {agent}\ngap_id: {gap}\nphase: {phase}\n"
        f"trace_id: {trace}\ntimestamp: {ts}\n---\n"
    )


def post_tool_call(context: Dict[str, Any]) -> None:
    """Called after every tool call. Tracks tool_use_events for code-review-graph rubric."""
    # context typically has: tool_name, tool_args, tool_result, duration_ms
    counter_path = VAULT_PATH / f"_tool_counters/{_agent()}-{_trace()}.json"
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if counter_path.exists():
            counters = json.loads(counter_path.read_text())
        else:
            counters = {"total": 0, "by_tool": {}}
    except Exception:
        counters = {"total": 0, "by_tool": {}}
    tool_name = context.get("tool_name", "unknown")
    counters["total"] += 1
    counters["by_tool"][tool_name] = counters["by_tool"].get(tool_name, 0) + 1
    counter_path.write_text(json.dumps(counters, indent=2))


def on_session_end(context: Dict[str, Any]) -> None:
    """Called when Hermes session ends. Writes critique to vault.

    Replaces agent-worker's existing post-Hermes hook that writes to:
      /opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/critiques/<date>-<agent>-<gap>-<phase>-<n>.md
    """
    if not VAULT_PATH.exists():
        return
    agent = _agent()
    trace = _trace()
    gap = _gap()
    phase = _phase()

    output = context.get("output", "")
    duration_ms = context.get("duration_ms", 0)
    tool_calls = context.get("tool_calls", 0)  # may be in context, else read counters
    if not tool_calls:
        try:
            counter_path = VAULT_PATH / f"_tool_counters/{agent}-{trace}.json"
            if counter_path.exists():
                tool_calls = json.loads(counter_path.read_text()).get("total", 0)
        except Exception:
            pass

    # Extract critique
    critique_dir = VAULT_PATH / "critiques"
    critique_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    date = datetime.utcnow().strftime("%Y-%m-%d")
    safe_gap = (gap or "no-gap")[:60]
    safe_phase = (phase or "no-phase")[:30]
    n_id = format(int(time.time() * 1000) % 1000000, "06d")
    critique_path = critique_dir / f"{date}-{agent}-{safe_gap}-{safe_phase}-{n_id}.md"

    redacted_preview = _redact(output[:500])
    body = (
        f"---\n"
        f"type: critique\n"
        f"created: {datetime.utcnow().isoformat()}+00:00\n"
        f"agent: {agent}\n"
        f"task_id: {safe_gap}-{safe_phase}-{n_id}\n"
        f"trace_id: {trace}\n"
        f"tool_calls: {tool_calls}\n"
        f"duration_ms: {duration_ms}\n"
        f"output_chars: {len(output)}\n"
        f'tags: ["critique", "{agent}", "kairos-obsidian-bridge-plugin"]\n'
        f"---\n\n"
        f"# Self-Critique: {safe_gap} {safe_phase}\n\n"
        f"## What Worked\n"
        f"- Hermes session ran for {duration_ms}ms producing {len(output)} chars across {tool_calls} tool calls\n"
        f"- trace_id={trace}\n\n"
        f"## What Failed\n"
        f"\n\n"
        f"## To Improve\n"
        f"\n\n"
        f"## For Next Agent\n"
        f"- Phase={safe_phase}, output preview:\n"
        f"```\n{redacted_preview}\n```\n"
    )
    critique_path.write_text(body)

    # If tool_calls == 0 → write a critique-flagged "prose-mode" learning
    if tool_calls == 0:
        learning_dir = VAULT_PATH / "learnings"
        learning_dir.mkdir(parents=True, exist_ok=True)
        learning_path = learning_dir / f"{date}-{agent}-{safe_gap}-prose-mode-{n_id}.md"
        learning_path.write_text(
            f"---\ntype: learning\ncreated: {datetime.utcnow().isoformat()}+00:00\n"
            f"agent: {agent}\ngap_id: {safe_gap}\ntrace_id: {trace}\n"
            f"severity: HIGH\ncategory: prose-vs-tool-use\n"
            f'tags: ["learning", "{agent}", "prose-mode", "tool_use_enforcement-failed"]\n'
            f"---\n\n"
            f"# Prose-mode learning: {agent} on {safe_gap}\n\n"
            f"Hermes session produced {len(output)} chars with **0 tool_use events**.\n"
            f"This violates v7.16 hard tool_choice=required policy. Possible causes:\n"
            f"- Hermes provider patch not active (check /root/.hermes/hermes-agent/run_agent.py:6242)\n"
            f"- Profile's tool_use_enforcement set to false\n"
            f"- Prompt too long → MiniMax drift (sweet spot 32-64K, hard cap >100K)\n"
            f"- Tools mis-registered (check --toolsets terminal,file,web on hermes chat invocation)\n\n"
            f"## Output preview (redacted)\n```\n{redacted_preview}\n```\n"
        )

    # Cleanup tool_counters
    try:
        counter_path = VAULT_PATH / f"_tool_counters/{agent}-{trace}.json"
        if counter_path.exists():
            counter_path.unlink()
    except Exception:
        pass


# ─── Slash commands ───────────────────────────────────────────────────────────

def cmd_vault_search(args: str) -> str:
    """/vault-search <query> — wraps karios-vault search"""
    import subprocess
    r = subprocess.run(["/usr/local/bin/karios-vault", "search", args], capture_output=True, text=True, timeout=10)
    return r.stdout[:2000] if r.returncode == 0 else f"❌ {r.stderr[:300]}"


def cmd_vault_recent(args: str) -> str:
    """/vault-recent [--kind X] [--limit N] — wraps karios-vault recent"""
    import subprocess
    cmd = ["/usr/local/bin/karios-vault", "recent"] + args.split()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return r.stdout[:2000] if r.returncode == 0 else f"❌ {r.stderr[:300]}"


def cmd_vault_write(args: str) -> str:
    """/vault-write <kind> [--agent X] --title T --body B — wraps karios-vault <kind>"""
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: /vault-write <learning|critique|rca|bug|fix|decision|memory> --title T --body B"
    import subprocess
    cmd = ["/usr/local/bin/karios-vault", parts[0]] + parts[1].split()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return r.stdout[:2000] if r.returncode == 0 else f"❌ {r.stderr[:300]}"


# ─── Plugin registration entry-point ──────────────────────────────────────────

def register(api):
    """Hermes plugin entry point. `api` is the Hermes plugin API surface."""
    api.register_hook("on_session_start", on_session_start)
    api.register_hook("on_session_end", on_session_end)
    api.register_hook("post_tool_call", post_tool_call)
    api.register_command("/vault-search", cmd_vault_search)
    api.register_command("/vault-recent", cmd_vault_recent)
    api.register_command("/vault-write", cmd_vault_write)
    return {"status": "registered", "name": "kairos-obsidian-bridge", "version": "1.0.0"}
