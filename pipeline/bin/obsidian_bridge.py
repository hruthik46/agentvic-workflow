#!/usr/bin/env python3
"""
obsidian_bridge — Persistent memory layer for all 9 KAIROS agents.

Every agent reads/writes to the Obsidian vault for:
  - Learnings (RCA, lessons, fixes)
  - Critiques (Reflexion-style self-reflection)
  - Decisions (ADRs)
  - Bugs (reproducible reports)
  - Memory (per-agent persistent state)
  - Context packets (handoff history)

Vault layout on .106:    /var/lib/karios/obsidian-vault/
Mirror on Mac:           ~/Documents/claude-notes/My-LLM-Wiki/  (sync'd by obsidian-sync.timer)

API:
    bridge = ObsidianBridge()
    bridge.write_learning(agent='backend', title='...', body='...', severity='HIGH', category='orchestration')
    bridge.write_critique(agent='architect', task_id='ARCH-IT-X', what_worked=[...], what_failed=[...])
    bridge.write_rca(incident_id='inc_001', symptom='...', root_cause='...', fix='...')
    bridge.write_bug(reporter='code-blind-tester', summary='...', repro_steps=[...])
    bridge.write_fix(file='event_dispatcher.py', commit='abc123', description='...')
    bridge.write_decision(decision_id='DEC-11', title='...', context='...', decision='...', consequences='...')
    bridge.write_memory(agent='orchestrator', key='last_dispatched_gap', value={...})
    bridge.write_context_packet(packet_dict)

    # Read
    matches = bridge.read_relevant('wave orchestration BG-06', kind='learning', limit=5)
    memory = bridge.read_memory(agent='orchestrator', key='last_dispatched_gap')
    bridge.list_recent(kind='rca', limit=10)

Concurrency: file-level fcntl lock per write; reads are lock-free.
Schema: every write produces a YAML-frontmatter markdown file with deterministic naming.
"""
import os
import sys
import json
import time
import fcntl
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

# Default = Relay-synced vault on .106 (auto-syncs to Mac via Obsidian Relay plugin).
# Override with KARIOS_VAULT_ROOT env if needed.
VAULT_ROOT = Path(os.environ.get("KARIOS_VAULT_ROOT", "/opt/obsidian/config/vaults/My-LLM-Wiki"))
KARIOS_SUBDIR = "raw/karios-pipeline"  # all agent writes land under this subtree

# Subdirectories per content kind (relative to KARIOS_SUBDIR)
KIND_DIRS = {
    "learning":       "learnings",
    "critique":       "critiques",
    "rca":            "rca",
    "bug":            "bugs",
    "fix":            "fixes",
    "decision":       "decisions",
    "memory":         "memory",
    "context_packet": "context-packets",
}

# Valid agent names — keep in sync with watchdog
VALID_AGENTS = {
    "orchestrator", "architect", "backend", "frontend", "devops",
    "tester", "monitor", "architect-blind-tester", "code-blind-tester",
    "watchdog", "system",  # also allow watchdog and system events
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9-_]+", "-", s.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:maxlen] or "untitled"


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:12]


class ObsidianBridge:
    def __init__(self, vault_root: Optional[Path] = None):
        self.vault_root = Path(vault_root) if vault_root else VAULT_ROOT
        self.base = self.vault_root / KARIOS_SUBDIR
        self.base.mkdir(parents=True, exist_ok=True)
        for d in KIND_DIRS.values():
            (self.base / d).mkdir(parents=True, exist_ok=True)

    # ── Internal write primitive ─────────────────────────────────────────────
    def _write(self, kind: str, name: str, frontmatter: Dict[str, Any], body: str) -> Path:
        if kind not in KIND_DIRS:
            raise ValueError(f"Unknown kind: {kind}; valid: {list(KIND_DIRS)}")
        agent = frontmatter.get("agent", "system")
        if agent not in VALID_AGENTS:
            raise ValueError(f"Unknown agent: {agent}; valid: {sorted(VALID_AGENTS)}")
        target_dir = self.base / KIND_DIRS[kind]
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{name}.md"

        # YAML frontmatter
        front_lines = ["---"]
        front_lines.append(f"type: {kind}")
        front_lines.append(f"created: {_now_iso()}")
        for k, v in frontmatter.items():
            if isinstance(v, (list, dict)):
                front_lines.append(f"{k}: {json.dumps(v)}")
            elif v is None:
                continue
            else:
                vstr = str(v).replace("\n", " ").strip()
                if any(c in vstr for c in [':', '#', '"', "'"]):
                    vstr = json.dumps(vstr)
                front_lines.append(f"{k}: {vstr}")
        front_lines.append("---")
        full = "\n".join(front_lines) + "\n\n" + body.rstrip() + "\n"

        # Idempotency: if a file with same fingerprint exists, skip
        fp = _fingerprint(full)
        existing = list(target_dir.glob(f"*.{fp}.md"))
        if existing:
            return existing[0]

        # Write with lock, append fingerprint to filename for dedup
        path = target_dir / f"{name}.{fp}.md"
        with open(path, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(full)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return path

    # ── Typed write APIs (one per kind) ───────────────────────────────────────

    def write_learning(self, *, agent: str, title: str, body: str,
                       severity: str = "MEDIUM", category: str = "general",
                       gap_id: Optional[str] = None, trace_id: Optional[str] = None,
                       tags: Optional[List[str]] = None) -> Path:
        """Write a learning (RCA, lesson, fix-pattern). Severity: CRITICAL|HIGH|MEDIUM|LOW."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{date}-{agent}-{_slug(title)}"
        fm = {
            "agent": agent, "severity": severity, "category": category,
            "gap_id": gap_id, "trace_id": trace_id,
            "title": title,
            "tags": (tags or []) + ["learning", agent, category],
        }
        return self._write("learning", name, fm, body)

    def write_critique(self, *, agent: str, task_id: str,
                       what_worked: List[str], what_failed: List[str],
                       to_improve: List[str], for_next_agent: List[str],
                       trace_id: Optional[str] = None) -> Path:
        """Write a Reflexion-style self-critique."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{date}-{agent}-{_slug(task_id)}"
        fm = {
            "agent": agent, "task_id": task_id, "trace_id": trace_id,
            "tags": ["critique", agent, task_id],
        }
        body_parts = [f"# Self-Critique: {task_id}\n"]
        body_parts.append("## What Worked\n" + "\n".join(f"- {x}" for x in what_worked) + "\n")
        body_parts.append("## What Failed\n" + "\n".join(f"- {x}" for x in what_failed) + "\n")
        body_parts.append("## To Improve\n" + "\n".join(f"- [ ] {x}" for x in to_improve) + "\n")
        body_parts.append("## For Next Agent\n" + "\n".join(f"- {x}" for x in for_next_agent) + "\n")
        return self._write("critique", name, fm, "\n".join(body_parts))

    def write_rca(self, *, incident_id: str, symptom: str, root_cause: str, fix: str,
                  agent: str = "system", severity: str = "HIGH",
                  files_affected: Optional[List[str]] = None,
                  lessons: Optional[List[str]] = None) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{date}-{_slug(incident_id)}"
        fm = {
            "agent": agent, "incident_id": incident_id, "severity": severity,
            "files_affected": files_affected or [],
            "tags": ["rca", agent, severity.lower()],
        }
        body = (
            f"# RCA: {incident_id}\n\n"
            f"## Symptom\n{symptom}\n\n"
            f"## Root Cause\n{root_cause}\n\n"
            f"## Fix\n{fix}\n\n"
            f"## Files Affected\n" + ("\n".join(f"- {f}" for f in (files_affected or [])) or "_none_") + "\n\n"
            f"## Lessons\n" + ("\n".join(f"- {l}" for l in (lessons or [])) or "_none recorded_") + "\n"
        )
        return self._write("rca", name, fm, body)

    def write_bug(self, *, reporter: str, summary: str, severity: str,
                  repro_steps: List[str], expected: str, actual: str,
                  gap_id: Optional[str] = None) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{date}-{reporter}-{_slug(summary)}"
        fm = {
            "agent": reporter, "severity": severity, "gap_id": gap_id,
            "tags": ["bug", reporter, severity.lower()],
        }
        body = (
            f"# Bug: {summary}\n\n"
            f"## Severity\n{severity}\n\n"
            f"## Reproduction Steps\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(repro_steps)) + "\n\n"
            f"## Expected\n{expected}\n\n"
            f"## Actual\n{actual}\n"
        )
        return self._write("bug", name, fm, body)

    def write_fix(self, *, agent: str, file: str, description: str,
                  commit: Optional[str] = None, addresses: Optional[List[str]] = None) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{date}-{agent}-{_slug(file)}-{_slug(description)[:30]}"
        fm = {
            "agent": agent, "file": file, "commit": commit, "addresses": addresses or [],
            "tags": ["fix", agent],
        }
        body = (
            f"# Fix: {file}\n\n"
            f"## Description\n{description}\n\n"
            f"## Commit\n{commit or '_uncommitted_'}\n\n"
            f"## Addresses\n" + ("\n".join(f"- {a}" for a in (addresses or [])) or "_no linked issues_") + "\n"
        )
        return self._write("fix", name, fm, body)

    def write_decision(self, *, decision_id: str, title: str, context: str,
                       decision: str, consequences: str, agent: str = "architect") -> Path:
        name = f"{_slug(decision_id)}-{_slug(title)}"
        fm = {
            "agent": agent, "decision_id": decision_id, "title": title,
            "tags": ["decision", "adr", agent],
        }
        body = (
            f"# {decision_id}: {title}\n\n"
            f"## Context\n{context}\n\n"
            f"## Decision\n{decision}\n\n"
            f"## Consequences\n{consequences}\n"
        )
        return self._write("decision", name, fm, body)

    def write_memory(self, *, agent: str, key: str, value: Any,
                     description: Optional[str] = None) -> Path:
        """Per-agent persistent k/v memory. value is JSON-serializable."""
        name = f"{agent}-{_slug(key)}"
        fm = {
            "agent": agent, "key": key, "description": description,
            "tags": ["memory", agent],
        }
        body = f"# Memory: {agent}.{key}\n\n```json\n{json.dumps(value, indent=2, default=str)}\n```\n"
        return self._write("memory", name, fm, body)

    def write_context_packet(self, packet: Dict[str, Any]) -> Path:
        """Archive a context packet to the vault."""
        pid = packet.get("id", f"pckt_{int(time.time())}")
        from_agent = packet.get("from", "unknown")
        to_agent = packet.get("to", "unknown")
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{date}-{_slug(pid)}-{_slug(from_agent)}-to-{_slug(to_agent)}"
        fm = {
            "agent": from_agent if from_agent in VALID_AGENTS else "system",
            "packet_id": pid, "from": from_agent, "to": to_agent,
            "type_": packet.get("type", "handoff"),
            "tags": ["context-packet", from_agent, to_agent],
        }
        body = "# Context Packet\n\n```json\n" + json.dumps(packet, indent=2, default=str) + "\n```\n"
        return self._write("context_packet", name, fm, body)

    # ── Read APIs ─────────────────────────────────────────────────────────────

    def read_memory(self, *, agent: str, key: str) -> Optional[Any]:
        """Latest write for (agent, key)."""
        target = self.base / KIND_DIRS["memory"]
        candidates = sorted(target.glob(f"{agent}-{_slug(key)}*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        text = candidates[0].read_text()
        # Pull JSON block
        m = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def read_relevant(self, query: str, *, kind: Optional[str] = None,
                      agent: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Keyword search across the vault. Returns list of {path, score, snippet, frontmatter}."""
        roots = [self.base / KIND_DIRS[kind]] if kind else [self.base / d for d in KIND_DIRS.values()]
        terms = [t.lower() for t in re.findall(r"\w{3,}", query)]
        if not terms:
            return []
        results = []
        for root in roots:
            for path in root.rglob("*.md"):
                try:
                    text = path.read_text(errors="replace")
                except Exception:
                    continue
                low = text.lower()
                score = sum(low.count(t) for t in terms)
                if score == 0:
                    continue
                if agent:
                    if f"agent: {agent}" not in low:
                        continue
                # Extract first snippet match
                snippet = ""
                for t in terms:
                    idx = low.find(t)
                    if idx >= 0:
                        snippet = text[max(0, idx-80):idx+200].replace("\n", " ")
                        break
                results.append({
                    "path": str(path), "score": score, "snippet": snippet,
                    "kind": kind or path.parent.name,
                })
        results.sort(key=lambda r: -r["score"])
        return results[:limit]

    def list_recent(self, *, kind: Optional[str] = None, agent: Optional[str] = None,
                    limit: int = 20) -> List[Dict[str, Any]]:
        roots = [self.base / KIND_DIRS[kind]] if kind else [self.base / d for d in KIND_DIRS.values()]
        items = []
        for root in roots:
            for path in root.rglob("*.md"):
                items.append((path.stat().st_mtime, path))
        items.sort(reverse=True)
        out = []
        for mt, path in items[:limit*3]:
            try:
                text = path.read_text(errors="replace")
            except Exception:
                continue
            if agent and f"agent: {agent}" not in text.lower():
                continue
            out.append({
                "path": str(path),
                "mtime": datetime.fromtimestamp(mt, timezone.utc).isoformat(),
                "first_lines": "\n".join(text.splitlines()[:8]),
            })
            if len(out) >= limit:
                break
        return out


# ── Module-level convenience for one-line use from agent code ────────────────
_default = None
def get_bridge() -> ObsidianBridge:
    global _default
    if _default is None:
        _default = ObsidianBridge()
    return _default


# ── CLI ───────────────────────────────────────────────────────────────────────
def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="Karios Obsidian Bridge — vault read/write CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_l = sub.add_parser("learning", help="Write a learning")
    p_l.add_argument("--agent", required=True)
    p_l.add_argument("--title", required=True)
    p_l.add_argument("--body", required=True, help="Markdown body or @path/to/file.md")
    p_l.add_argument("--severity", default="MEDIUM")
    p_l.add_argument("--category", default="general")
    p_l.add_argument("--gap-id", default=None)

    p_c = sub.add_parser("critique", help="Write a self-critique")
    p_c.add_argument("--agent", required=True)
    p_c.add_argument("--task-id", required=True)
    p_c.add_argument("--worked", nargs="*", default=[])
    p_c.add_argument("--failed", nargs="*", default=[])
    p_c.add_argument("--improve", nargs="*", default=[])
    p_c.add_argument("--for-next", nargs="*", default=[])

    p_r = sub.add_parser("rca", help="Write an RCA")
    p_r.add_argument("--incident-id", required=True)
    p_r.add_argument("--symptom", required=True)
    p_r.add_argument("--root-cause", required=True)
    p_r.add_argument("--fix", required=True)
    p_r.add_argument("--agent", default="system")
    p_r.add_argument("--severity", default="HIGH")
    p_r.add_argument("--files", nargs="*", default=[])

    p_m = sub.add_parser("memory", help="Read/write per-agent memory")
    p_m.add_argument("--agent", required=True)
    p_m.add_argument("--key", required=True)
    p_m.add_argument("--value", default=None, help="JSON value to write; omit to read")

    p_s = sub.add_parser("search", help="Search vault by keyword")
    p_s.add_argument("query")
    p_s.add_argument("--kind", default=None)
    p_s.add_argument("--agent", default=None)
    p_s.add_argument("--limit", type=int, default=5)

    p_R = sub.add_parser("recent", help="List recent entries")
    p_R.add_argument("--kind", default=None)
    p_R.add_argument("--agent", default=None)
    p_R.add_argument("--limit", type=int, default=10)

    p_d = sub.add_parser("decision", help="Write a decision (ADR)")
    p_d.add_argument("--decision-id", required=True)
    p_d.add_argument("--title", required=True)
    p_d.add_argument("--context", required=True)
    p_d.add_argument("--decision", required=True)
    p_d.add_argument("--consequences", required=True)
    p_d.add_argument("--agent", default="architect")

    p_b = sub.add_parser("bug", help="Write a bug report")
    p_b.add_argument("--reporter", required=True)
    p_b.add_argument("--summary", required=True)
    p_b.add_argument("--severity", default="MEDIUM")
    p_b.add_argument("--repro-steps", nargs="+", default=[])
    p_b.add_argument("--expected", required=True)
    p_b.add_argument("--actual", required=True)
    p_b.add_argument("--gap-id", default=None)

    p_f = sub.add_parser("fix", help="Write a fix log")
    p_f.add_argument("--agent", required=True)
    p_f.add_argument("--file", required=True)
    p_f.add_argument("--description", required=True)
    p_f.add_argument("--commit", default=None)
    p_f.add_argument("--addresses", nargs="*", default=[])

    args = ap.parse_args()
    b = get_bridge()
    if args.cmd == "learning":
        body = args.body
        if body.startswith("@"):
            body = Path(body[1:]).read_text()
        p = b.write_learning(agent=args.agent, title=args.title, body=body,
                              severity=args.severity, category=args.category, gap_id=args.gap_id)
        print(p)
    elif args.cmd == "critique":
        p = b.write_critique(agent=args.agent, task_id=args.task_id,
                             what_worked=args.worked, what_failed=args.failed,
                             to_improve=args.improve, for_next_agent=args.for_next)
        print(p)
    elif args.cmd == "rca":
        p = b.write_rca(incident_id=args.incident_id, symptom=args.symptom,
                        root_cause=args.root_cause, fix=args.fix,
                        agent=args.agent, severity=args.severity, files_affected=args.files)
        print(p)
    elif args.cmd == "memory":
        if args.value is None:
            print(json.dumps(b.read_memory(agent=args.agent, key=args.key), indent=2, default=str))
        else:
            p = b.write_memory(agent=args.agent, key=args.key, value=json.loads(args.value))
            print(p)
    elif args.cmd == "search":
        for r in b.read_relevant(args.query, kind=args.kind, agent=args.agent, limit=args.limit):
            print(f"[{r['score']:3d}] {r['path']}\n     ...{r['snippet']}...\n")
    elif args.cmd == "recent":
        for r in b.list_recent(kind=args.kind, agent=args.agent, limit=args.limit):
            print(f"{r['mtime']}  {r['path']}")
    elif args.cmd == "decision":
        p = b.write_decision(decision_id=args.decision_id, title=args.title, context=args.context,
                             decision=args.decision, consequences=args.consequences, agent=args.agent)
        print(p)
    elif args.cmd == "bug":
        p = b.write_bug(reporter=args.reporter, summary=args.summary, severity=args.severity,
                        repro_steps=args.repro_steps, expected=args.expected, actual=args.actual,
                        gap_id=args.gap_id)
        print(p)
    elif args.cmd == "fix":
        p = b.write_fix(agent=args.agent, file=args.file, description=args.description,
                        commit=args.commit, addresses=args.addresses)
        print(p)


if __name__ == "__main__":
    _cli()
