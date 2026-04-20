# Architecture — ARCH-IT-ARCH-v11 (iteration 1)

## Gap Requirement

Drive KAIROS v7.5 (LIVE on .106) from 8.5/10 to 10/10 production-ready by implementing 6 infrastructure hardening items (A–F). v7.5 shipped items 1–11 are already verified and MUST NOT be re-implemented.

## What v7.5 Shipped (VERIFIED — do not redo)

```
grep -n "tool_use_enforcement\|quarantine\|_update_active_gap_state\|_sanitize_gap_id\|recover_from_checkpoints" \
  /var/lib/karios/orchestrator/event_dispatcher.py | head -30
```

| # | Item | Location | Verification |
|---|------|----------|--------------|
| 1 | `tool_use_enforcement: true` in config.yaml | line 50 | Confirmed |
| 2 | `telegram_alert` retry + Markdown→plain fallback | line 687 | Confirmed |
| 3 | `handle_arch_review` JSON parsing (fence + regex) | line 2149 | Confirmed |
| 4 | File-inbox quarantine for bad JSON | line 249 | Confirmed |
| 5 | `_update_active_gap_state()` wired to phase handlers | line 2067 | Confirmed |
| 6 | `recover_from_checkpoints` skip-if-completed guard | line 2525 | Confirmed |
| 7 | `_sanitize_gap_id()` caps at 80 + em-dash split | line 2083 | Confirmed |
| 8 | Subject aliases for 9 alternative subjects | dispatcher's parse_message | Confirmed |
| 9 | `notify_phase_transition` wired to FAN-IN + ARCH-COMPLETE | line 807 | Confirmed |
| 10 | `3-coding-sync` → Phase 4 transition | COMPLETE handler | Confirmed |
| 11 | Defensive `int(tokens[1])` bounds-check | line 2134 | Confirmed |

---

## Root Cause Analysis: Why 8.5/10 → Not 10/10

### INFRA-01: No Schema Validation at Message Boundary
**Symptom**: `parse_message()` dispatches to handlers based on subject prefix only. Malformed JSON bodies silently pass through if the subject line is correct. `handle_arch_review` KeyError on missing `rating` field survived only because of v7.5 defensive handling.
**Gap**: No Pydantic models exist for any of the 9+ message body types. Validation is string-prefix only.
**Fix**: Item A.

### INFRA-02: No Self-Test of Pipeline Itself
**Symptom**: Phase 1 (research) and Phase 6 (monitor) have never been observed firing naturally in a meta-loop run. All prior meta-loop completions injected synthesized data.
**Gap**: No trivially-implementable gap exists to exercise all 6 phase boundaries with measurable timeouts.
**Fix**: Item B.

### INFRA-03: code-review-graph Not Audited
**Symptom**: Agents skip `get_minimal_context()` and go straight to raw file reads. Token waste estimated 8–16x vs. graph-first approach.
**Gap**: No per-session tracking, no gate enforcement at `[CODING-COMPLETE]`.
**Fix**: Item C.

### INFRA-04: No Gitea Push Verification
**Symptom**: Phase 5 (deploy) succeeded but code was never pushed to origin. `[PROD-DEPLOYED]` fired anyway.
**Gap**: No post-deploy git verification step.
**Fix**: Item D.

### INFRA-05: Watchdog Is Belt-and-Suspenders Only
**Symptom**: `tool_use_enforcement: true` (v7.5 item 1) forces Hermes to use tools, but does not prevent a tool-use flood (hundreds of useless `read_file` calls) followed by prose.
**Gap**: No per-turn token counting with SIGTERM enforcement.
**Fix**: Item E.

### INFRA-06: Anthropic `tool_choice: any` Not Forwarded
**Symptom**: MiniMax-M2.7 uses OpenAI-compatible API. `tool_choice` parameter (which forces tool use) is not forwarded from profile config to API call.
**Gap**: Provider adapter does not map profile field to API parameter.
**Fix**: Item F (deferred if too invasive).

---

## Architecture: Component-by-Component

---

### Item A: Pydantic Schema at Message Boundary

#### A.1 Schema File Location
`/var/lib/karios/orchestrator/message_schemas.py`

This file is loaded by `event_dispatcher.py` at import time. Schemas use Pydantic v2 `BaseModel`.

#### A.2 Schema Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ArchCompleteBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    files_changed: List[str] = Field(default_factory=list)
    summary: str = ""
    phase: str = ""

class ArchReviewedBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    rating: int = Field(ge=1, le=10)
    critical_issues: List[str] = Field(default_factory=list)
    summary: str = ""
    dimensions: Dict[str, float] = Field(default_factory=dict)
    adversarial_test_cases: Dict[str, Any] = Field(default_factory=dict)
    recommendation: str = "REQUEST_CHANGES"
    trace_id: Optional[str] = None

class CodingCompleteBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    files_changed: List[str] = Field(default_factory=list)
    test_results: Optional[Dict[str, Any]] = None
    phase: str = ""

class E2EResultsBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    rating: int = Field(ge=1, le=10)
    passed_tests: int = 0
    failed_tests: int = 0
    summary: str = ""

class StagingDeployedBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    deploy_url: str = ""
    artifacts: List[str] = Field(default_factory=list)
    phase: str = ""

class ProdDeployedBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    deploy_url: str = ""
    artifacts: List[str] = Field(default_factory=list)
    phase: str = ""

class MonitoringCompleteBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    uptime_seconds: int = 0
    error_count: int = 0
    summary: str = ""

class RequirementBody(BaseModel):
    gap_id: str
    message: str = ""
    priority: str = "normal"
    tier: str = "T2"

class ResearchCompleteBody(BaseModel):
    gap_id: str
    iteration: int = Field(ge=1)
    files_changed: List[str] = Field(default_factory=list)
    summary: str = ""
    phase: str = ""
```

#### A.3 Validation in `parse_message()`

Before dispatching to any handler, `parse_message()` calls `validate_message(subject, body)`:

```python
SCHEMA_MAP = {
    "[ARCH-COMPLETE]": ArchCompleteBody,
    "[ARCHITECTURE-COMPLETE]": ArchCompleteBody,
    "[ARCH-REVIEWED]": ArchReviewedBody,
    "[BLIND-REVIEWED]": ArchReviewedBody,
    "[CODING-COMPLETE]": CodingCompleteBody,
    "[E2E-RESULTS]": E2EResultsBody,
    "[E2E-COMPLETE]": E2EResultsBody,
    "[TEST-RESULTS]": E2EResultsBody,
    "[BLIND-E2E-RESULTS]": E2EResultsBody,
    "[DEPLOYED-STAGING]": StagingDeployedBody,
    "[STAGING-COMPLETE]": StagingDeployedBody,
    "[DEPLOYED-PROD]": ProdDeployedBody,
    "[DEPLOY-DONE]": ProdDeployedBody,
    "[PRODUCTION-COMPLETE]": ProdDeployedBody,
    "[PROD-DEPLOYED]": ProdDeployedBody,
    "[MONITORING-COMPLETE]": MonitoringCompleteBody,
    "[REQUIREMENT]": RequirementBody,
    "[RESEARCH-COMPLETE]": ResearchCompleteBody,
}

def validate_message(subject: str, body: str) -> tuple[bool, Optional[str], Optional[BaseModel]]:
    """Returns (valid, reason, model_instance). Logs and quarantines on violation."""
    for prefix, model_cls in SCHEMA_MAP.items():
        if subject.startswith(prefix):
            try:
                data = json.loads(body)
                instance = model_cls.model_validate(data)
                return True, None, instance
            except json.JSONDecodeError as e:
                reason = f"JSON parse error: {e}"
            except Exception as e:
                reason = f"Pydantic validation error: {type(e).__name__}: {e}"
            
            # Quarantine + notify sender
            qdir = Path('/var/lib/karios/agent-msg/schema-violations')
            qdir.mkdir(parents=True, exist_ok=True)
            qpath = qdir / f"{uuid.uuid4().hex[:8]}_{sanitize_filename(subject)}.json"
            qpath.write_text(json.dumps({"subject": subject, "body": body, "reason": reason}))
            print(f"[dispatcher] SCHEMA VIOLATION quarantined: {qpath}")
            
            # Notify sender (if we can determine who sent it)
            return False, reason, None
    # No schema defined for this subject — pass through (legacy compat)
    return True, None, None
```

#### A.4 Incremental Rollout (Two-Iteration Plan)

**Iteration 1 (this one, log-only)**:
- Load schemas, call `validate_message()` in `parse_message()`, but only LOG violations — do not quarantine, do not reject.
- Collect violation stats for one full meta-loop cycle.
- Quarantine dir created but not actively used yet.

**Iteration 2 (enforce)**:
- Enable full quarantine + sender notification.
- Refine schemas based on real violations observed in iteration 1.

---

### Item B: BG-stub-no-op Self-Test

#### B.1 Requirement File

Create `/var/lib/karios/coordination/requirements/BG-stub-no-op.md`:

```markdown
# BG-stub-no-op — Pipeline Self-Test Gap

## Summary
A trivially-implementable backend gap that exercises all 6 phase boundaries
of the KAIROS pipeline. Each phase must fire within a defined timeout.
Exit 0 from `karios-self-test` = pipeline healthy.

## Implementation
- Backend: Add `GET /api/v1/stub/ok` returning `{"ok": true, "timestamp": "<iso>"}`
- Frontend: Add "Pipeline Self-Test" button in Control Center, calls the above endpoint
- All other phases: naturally exercised by the orchestrator dispatching this gap

## Phase Boundaries (must all fire within timeout)
| Phase | Boundary | Timeout |
|-------|----------|---------|
| 0 → 1 | `[REQUIREMENT]` received | 30s |
| 1 → 2 | `[RESEARCH-COMPLETE]` received | 120s |
| 2 → 3 | `[ARCH-COMPLETE]` + `[ARCH-REVIEWED]` (rating ≥ 8) | 300s |
| 3 → 4 | `[CODING-COMPLETE]` received | 300s |
| 4 → 5 | `[DEPLOYED-STAGING]` received | 300s |
| 5 → 6 | `[DEPLOYED-PROD]` received | 300s |
| 6 → done | `[MONITORING-COMPLETE]` received (or 24h watchdog) | 86400s |

## Success Criteria
- All 7 phase transitions observed in orchestrator logs
- Telegram notification for each phase transition received
- `karios-self-test` exits 0 within 30 minutes
```

#### B.2 `karios-self-test` CLI

Location: `/usr/local/bin/karios-self-test`

```bash
#!/bin/bash
# Runs BG-stub-no-op gap through all 6 phases and asserts boundaries fire.
# Exit 0 = pipeline healthy. Exit 1 = failure.

set -e
GAP_ID="BG-stub-no-op"
TIMEOUT=1800  # 30 minutes
PHASES_FIRED=0

log() { echo "[self-test] $(date -Iseconds) $*"; }

# Phase 0 → 1: Dispatch requirement
log "Phase 0: Dispatching requirement..."
agent send orchestrator "[REQUIREMENT] ${GAP_ID}: Pipeline self-test gap"
# Wait for RESEARCH-COMPLETE (polling agent-msg inbox for 120s)
for i in $(seq 1 120); do
  if grep -q "RESEARCH-COMPLETE.*${GAP_ID}" /var/lib/karios/agent-msg/inbox/orchestrator/*.json 2>/dev/null; then
    PHASES_FIRED=$((PHASES_FIRED+1)); break
  fi
  sleep 1
done

# Phase 1 → 2: Wait for ARCH-COMPLETE (300s)
for i in $(seq 1 300); do
  if grep -q "ARCH-COMPLETE.*${GAP_ID}" /var/lib/karios/agent-msg/inbox/orchestrator/*.json 2>/dev/null; then
    PHASES_FIRED=$((PHASES_FIRED+1)); break
  fi
  sleep 1
done

# ... (similar for phases 2→3, 3→4, 4→5, 5→6) ...

if [ $PHASES_FIRED -ge 6 ]; then
  log "SUCCESS: All 6 phase boundaries fired"
  exit 0
else
  log "FAILURE: Only $PHASES_FIRED/6 phases fired"
  exit 1
fi
```

#### B.3 Integration with Orchestrator

The orchestrator's `handle_requirement()` recognizes `BG-stub-no-op` as a self-test gap and:
1. Sets accelerated timeouts (no 24h monitor wait for Phase 6)
2. Logs each phase transition to `/var/lib/karios/self-test-results/${GAP_ID}.jsonl`
3. Emits Telegram alerts for each phase transition

---

### Item C: code-review-graph Rubric Gate

#### C.1 Agent-Worker Post-Hermes Hook

Location: `/var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker` (production: `/usr/local/bin/agent-worker`)

After `run_hermes()` completes (line ~600), add:

```python
def _check_code_review_graph_usage(task: str, hermes_output: str, agent: str) -> None:
    """Post-Hermes hook: audit get_minimal_context calls, write critique if missing."""
    code_profiles = {"backend-worker", "frontend-worker", "devops-agent"}
    if agent not in code_profiles:
        return
    
    # Check if task touches code (rough heuristic: mentions .go, .ts, .py files)
    touches_code = any(ext in task for ext in [".go", ".ts", ".tsx", ".py", ".sh"])
    if not touches_code:
        return
    
    # Count get_minimal_context calls in Hermes output
    gc_count = hermes_output.count("get_minimal_context")
    
    if gc_count == 0:
        try:
            subprocess.run(
                ["/usr/local/bin/karios-vault", "critique",
                 "--agent", agent,
                 "--failed", "skipped get_minimal_context",
                 "--task", task[:200],
                 "--trace", trace_id],
                capture_output=True, timeout=10
            )
            print(f"[{AGENT}] CRITIQUE written: skipped get_minimal_context for code task")
        except Exception as e:
            print(f"[{AGENT}] critique write failed: {e}")
```

#### C.2 Dispatcher Gate at `[CODING-COMPLETE]`

In `parse_message()`, when handling `[CODING-COMPLETE]` for backend/frontend:

```python
if subject.startswith("[CODING-COMPLETE]"):
    # Gate: require code_review_graph_calls > 0 for code-touching agents
    sender = data.get("from", "")
    if sender in ("backend", "frontend"):
        session_meta = data.get("session_metadata", {})
        crg_calls = session_meta.get("code_review_graph_calls", 0)
        if crg_calls == 0:
            # Refuse advance — send back for retry
            stream_publish(
                subject=f"[CODING-RETRY] {gap_id}",
                body=json.dumps({
                    "reason": "code_review_graph_calls=0 — retry with get_minimal_context",
                    "gap_id": gap_id, "iteration": iteration
                }),
                from_agent="orchestrator",
                gap_id=gap_id, priority="high"
            )
            print(f"[dispatcher] CODING-COMPLETE refused: {sender} had 0 code_review_graph calls")
            return
    handle_coding_complete(gap_id, iteration, body, trace_id=trace_id)
    return
```

**Note**: The `session_metadata` field is populated by `agent-worker` post-Hermes hook by parsing the Hermes session log for `get_minimal_context` invocations.

#### C.3 Session Metadata Extraction

In `agent-worker`, after Hermes completes, parse the session log:

```python
# Extract code_review_graph_calls from session log
session_log_path = Path(f"/root/.hermes/sessions/{session_id}/log.txt")
if session_log_path.exists():
    log_content = session_log_path.read_text(errors="ignore")
    crg_calls = log_content.count("get_minimal_context")
    session_metadata = {"code_review_graph_calls": crg_calls}
else:
    session_metadata = {"code_review_graph_calls": 0}
```

---

### Item D: Gitea Push Verification Gate

#### D.1 Implementation

After devops emits `[PROD-DEPLOYED]`, before transitioning to Phase 6, run:

```python
def verify_gitea_push(gap_id: str, repos: list[str]) -> tuple[bool, str]:
    """Verify all gap repos are pushed to origin. Returns (ok, message)."""
    results = []
    for repo in repos:
        repo_path = f"/root/karios-source-code/{repo}"
        try:
            # Get count of commits ahead of origin
            result = subprocess.run(
                ["git", "-C", repo_path, "rev-list", "--left-right", "--count",
                 "origin/main...HEAD"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                results.append(f"{repo}: git error {result.stderr}")
                continue
            ahead, behind = result.stdout.strip().split("\t")
            if int(ahead) > 0 or int(behind) > 0:
                results.append(f"{repo}: {ahead} ahead, {behind} behind origin")
        except Exception as e:
            results.append(f"{repo}: exception {e}")
    
    if results:
        return False, "; ".join(results)
    return True, "all repos up-to-date with origin"

def handle_prod_deployed(gap_id: str, iteration: int, body: str, trace_id: str):
    # Load iteration manifest to get repos touched
    manifest_path = Path(f"/var/lib/karios/iteration-tracker/{gap_id}/manifest.json")
    repos = []
    if manifest_path.exists():
        repos = json.loads(manifest_path.read_text()).get("repos_touched", [])
    
    ok, msg = verify_gitea_push(gap_id, repos)
    if not ok:
        # Refuse PROD-DEPLOYED — send GITEA-PUSH-PENDING to devops
        stream_publish(
            subject=f"[GITEA-PUSH-PENDING] {gap_id}",
            body=json.dumps({"repos": repos, "diff_detail": msg, "gap_id": gap_id}),
            from_agent="orchestrator", gap_id=gap_id, priority="high"
        )
        telegram_alert(f"🚨 {gap_id}: Git not pushed to origin. DevOps must push before PROD-DEPLOYED completes. Detail: {msg}")
        return
    
    # Proceed with normal Phase 6 transition
    _update_active_gap_state(gap_id, phase="phase-6-monitoring", state="active", iteration=iteration)
    notify_phase_transition(gap_id, "devops", "monitor (Phase 6 24h watch)", "PROD-DEPLOYED")
    # ... rest of existing handler
```

#### D.2 Iteration Manifest

Each gap iteration tracker directory contains a `manifest.json`:

```json
{
  "gap_id": "ARCH-IT-ARCH-v11",
  "iteration": 1,
  "repos_touched": ["karios-migration", "karios-web"],
  "files_changed": ["/var/lib/karios/orchestrator/message_schemas.py"],
  "created_at": "2026-04-19T19:00:00Z"
}
```

DevOps updates this manifest at Phase 3 start (from `git diff --name-only`).

---

### Item E: Watchdog Kill-on-No-Tool-Call

#### E.1 Problem Statement

`tool_use_enforcement: true` forces Hermes to use at least one tool per response turn, but does NOT prevent:
1. A flood of useless `read_file` calls (token waste)
2. Prose after tool calls (the prose is the "final" response after all tool results)
3. A very long reasoning trace followed by one trivial tool call

The watchdog counts tokens streamed to stdout. If >4000 tokens with zero `tool_use` events observed, it sends SIGTERM.

#### E.2 Implementation: PTY-Based Streaming

Replace `subprocess.run` with `subprocess.Popen` + PTY in `agent-worker`'s `run_hermes()`:

```python
import os, pty, select, signal, threading, time

def run_hermes_pty(task: str, agent_name: str, gap_id: str = None,
                   trace_id: str = None, phase: str = None) -> str:
    """Run Hermes with PTY streaming for token-counting watchdog."""
    master_fd, slave_fd = pty.openpty()
    
    pid = subprocess.Popen(
        [HERMES_CMD, "chat",
         "--profile", get_profile_name(),
         "--query", build_query(task, agent_name, gap_id, trace_id, phase),
         "--toolsets", "terminal,file,web", "-v"],
        stdout=slave_fd, stderr=slave_fd,
        cwd="/root"
    )
    os.close(slave_fd)
    
    output_chunks = []
    tool_use_events = 0
    token_count = 0
    start_time = time.time()
    tool_use_detected = threading.Event()
    
    def stream_reader():
        nonlocal token_count, tool_use_events, output_chunks
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.5)
            if master_fd in r:
                chunk = os.read(master_fd, 4096)
                if not chunk:
                    break
                decoded = chunk.decode('utf-8', errors='replace')
                output_chunks.append(decoded)
                token_count += len(decoded.split()) * 1.3  # rough token estimate
                
                # Detect tool_use event in output
                if '"tool_use"' in decoded or 'tool_use' in decoded:
                    tool_use_events += 1
                    tool_use_detected.set()
                
                # Watchdog: >4000 tokens, no tool_use event
                if token_count > 4000 and not tool_use_detected.is_set():
                    # SIGTERM the process group
                    os.killpg(os.getpgid(pid.pid), signal.SIGTERM)
                    print(f"[{AGENT}] WATCHDOG: SIGTERM after {token_count:.0f} tokens, 0 tool_use events")
                    break
            else:
                # Check if process exited
                if pid.poll() is not None:
                    break
    
    reader_thread = threading.Thread(target=stream_reader)
    reader_thread.start()
    
    # Wait with timeout
    try:
        pid.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(pid.pid), signal.SIGKILL)
    
    reader_thread.join(timeout=5)
    os.close(master_fd)
    
    full_output = "".join(output_chunks)
    
    # If killed by watchdog, retry once with explicit prompt prepend
    if pid.returncode == -signal.SIGTERM.value:
        print(f"[{AGENT}] WATCHDOG retry with forced tool-use prompt")
        retry_query = (
            'BEGIN by calling karios-vault.search. Do not output prose first.\n\n' + 
            build_query(task, agent_name, gap_id, trace_id, phase)
        )
        # Fall through to normal subprocess.run for retry (one level of escalation)
        full_output = subprocess.run(
            [HERMES_CMD, "chat", "--profile", get_profile_name(),
             "--query", retry_query, "--toolsets", "terminal,file,web", "-v"],
            capture_output=True, text=True, timeout=1800, cwd="/root"
        ).stdout + "\n[WATCHDOG-RETRY]"
    
    return full_output
```

#### E.3 Integration Point

In `agent-worker`, replace the `subprocess.run` call in `run_hermes()` with a call to `run_hermes_pty()`. The existing `subprocess.run` path is retained as the fallback retry mechanism.

---

### Item F: Anthropic `tool_choice: any` Passthrough

#### F.1 Investigation Notes

The Hermes codebase at `/root/.hermes/hermes-agent/` uses OpenAI-compatible API format for MiniMax-M2.7 (and other non-Anthropic providers). The provider adapter is in `agent/model_metadata.py` or `hermes_cli/models.py`.

The `tool_choice` parameter is part of the OpenAI Chat Completions API. For Anthropic, the equivalent is `tools[].input.schema` but for OpenAI-compatible endpoints (MiniMax), `tool_choice` is a valid parameter.

#### F.2 Implementation (Deferred)

**Reason for deferral**: Requires tracing the full provider adapter chain from `hermes chat --profile X` through to `openai.ChatCompletion.create()` call site. Risk of breaking all 9 agents if done incorrectly.

**Deferred implementation plan** (document for future iteration):
1. Locate the provider adapter in `hermes-agent/agent/model_metadata.py` or similar
2. Add profile config field: `agent.anthropic.tool_choice: any`
3. Map to OpenAI `tool_choice` parameter in the API call
4. Gate on `extended_thinking: false` in profile (incompatible combination)
5. Test with MiniMax-M2.7 on a non-production gap before rolling out

**Citation**: Deferring F per task instruction: "F. Anthropic `tool_choice: any` passthrough (deepest fix; defer if too invasive)".

---

## Dependencies Between Items

```
Item A (Pydantic schemas)      → no deps, independent
Item B (BG-stub-no-op)         → depends on A (quarantine dir exists)
Item C (code-review-graph gate) → no deps, independent
Item D (Gitea push gate)        → no deps, independent
Item E (Watchdog PTY)           → no deps, independent
Item F (tool_choice passthrough) → deferred

Execution order: A, C, D, E can run in parallel.
B (self-test) should run last as the final validation.
F is documented only, no code changes.
```

---

## Files to be Created or Modified

| File | Action | Items |
|------|--------|-------|
| `/var/lib/karios/orchestrator/message_schemas.py` | Create | A |
| `/var/lib/karios/orchestrator/event_dispatcher.py` | Modify | A, C, D |
| `/var/lib/karios/coordination/requirements/BG-stub-no-op.md` | Create | B |
| `/usr/local/bin/karios-self-test` | Create | B |
| `/var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker` | Copy to `/usr/local/bin/agent-worker` with E modifications | C, E |
| `/root/.hermes/hermes-agent/agent/model_metadata.py` | Document only | F |

---

## Rollout Plan

**Phase 1 (this iteration)**: Architecture documents + log-only schema validation + BG-stub-no-op requirement + self-test CLI skeleton
**Phase 2 (next iteration)**: Full schema enforcement + code-review-graph gate + Gitea push gate + watchdog PTY + self-test full run