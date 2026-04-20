# Architecture — ARCH-IT-ARCH-v10 (iteration 1)

## Gap Requirement

Make KAIROS v7.4 production-ready and battle-tested:
- A. Tool-use enforcement at Hermes level (watchdog + config)
- B. JSON schema validation at all message boundaries (Pydantic)
- C. End-to-end self-test via BG-stub-no-op gap (Phase 1–6)
- D. code-review-graph rubric (get_minimal_context audit per agent)
- E. Gitea push verification before [PROD-DEPLOYED]
- F. No manual Telegram (only pipeline-driven notifications)

## Root Cause Analysis: Why v7.4 Still Has Rough Edges

From META-LOOP ITERATIONS 1–5 (v6–v9), the following systemic failures were observed:

### CF-01: Prose-Only Architect Output (HERMES CONTEXT EXHAUSTION)
**Symptom**: Round 3–4 architect produced 320K tokens of prose without a single `write_file` call. All 5 architecture docs were empty/placeholder.
**Root Cause**: Hermes `tool_use_enforcement` was set to `auto` — Hermes may choose to not call tools when it judges the task "too complex to start with tools". Profile HARD PRE-SUBMIT GATE cannot fire because it IS a tool call — the gate check requires Hermes to have already called `read_file` to check doc sizes.
**Fix**:
1. Change `tool_use_enforcement: auto` → `tool_use_enforcement: strict` in all 9 agent profile configs
2. Add watchdog in `agent-worker` (`run_hermes`) that kills Hermes subprocess if zero tool calls in first 30K streamed tokens
3. Prompt template injection: prepend "FIRST call `karios-vault search ...`, THEN produce JSON, THEN write files. NO PROSE FIRST."

### CF-02: No Schema Validation at Message Boundaries
**Symptom**: `handle_arch_review` received malformed JSON (KeyError on `rating` field). Orchestrator survived via defensive handling, but invalid messages were silently dropped.
**Root Cause**: `MessageEnvelope.from_stream_entry()` deserializes JSON but never validates field presence or types. Agents send arbitrary JSON in the `body` field.
**Fix**: Add Pydantic models for each message subject type. Validate in `parse_message()` before dispatching. Return schema-violation rejection to sender.

### CF-03: No Self-Test of the Pipeline Itself
**Symptom**: Phase 1 (research) and Phase 6 (monitor) are still skipped/forged in meta-loop runs. Pipeline cannot prove its own correctness.
**Root Cause**: No `BG-stub-no-op` gap exists to exercise all 6 phases with measurable criteria.
**Fix**: Design and run BG-stub-no-op as a permanently reserved gap ID that the orchestrator can trigger on demand.

### CF-04: code-review-graph Not Audited
**Symptom**: Agents skip `get_minimal_context()` and go straight to raw file reads, wasting tokens (8–16x more than necessary).
**Root Cause**: No enforcement or scoring mechanism. `get_minimal_context()` call is optional.
**Fix**: Track `get_minimal_context` invocations per Hermes session. Score per agent. Gate Phase 3 advance if code-touching agent has score=0.

### CF-05: No Gitea Push Verification
**Symptom**: Phase 5 deploy succeeded but code was never pushed to `gitea.karios.ai`. `[PROD-DEPLOYED]` fired anyway.
**Root Cause**: No post-deploy push verification step.
**Fix**: After Phase 5 deploy, run `git rev-list --left-right --count origin/<branch>...HEAD`. If both counts > 0, refuse `[PROD-DEPLOYED]`.

### CF-06: Manual Telegram Still Possible
**Symptom**: Sai could manually message the Telegram bot and get responses, bypassing the pipeline event loop.
**Root Cause**: No restriction on bot command handlers. Only `notify_phase_transition()` and `telegram_alert()` should fire.
**Fix**: Add admin-role filter in `karios-hitl-listener` or bot handler. Only pipeline's own calls can send. Manual messages get "Pipeline-controlled bot — please use /status" auto-reply.

---

## Architecture: Component-by-Component

### A. Tool-Use Enforcement (Hermes Level)

#### A.1 Config Change — `tool_use_enforcement: strict`

Change `tool_use_enforcement: auto` → `tool_use_enforcement: strict` in:
- `/root/.hermes/config.yaml` (global default)
- All 9 agent profile configs at `/root/.hermes/profiles/*/`

The `strict` mode forces Hermes to use a tool on every response turn — no pure prose allowed.

**Verification**: After config change, run a test:
```bash
hermes chat --query "Write hello world to /tmp/test_tool_use.txt" --profile architect --toolsets terminal,file
```
Expected: First response contains a `write_file` or `terminal` tool call, not prose.

#### A.2 Watchdog in `agent-worker` (`run_hermes`)

Location: `/usr/local/bin/agent-worker`, inside `run_hermes()`.

**Problem**: `subprocess.run(..., capture_output=True)` buffers ALL output until the process exits. We cannot monitor streaming tokens incrementally.

**Solution**: Replace `subprocess.run` with `subprocess.Popen` + threaded token counter. Monitor `stdout` as a pipe in a background thread. Count tokens (words × 1.3 as rough token estimate). If >30K tokens stream with zero tool calls detected, send `SIGKILL` to the Hermes process group.

```python
import signal, threading, time

TOOL_CALL_PATTERNS = [
    b'"tool":"', b'"name":"terminal"', b'"name":"read_file"', b'"name":"write_file"',
    b'"name":"search_files"', b'"tool_call":', b'Function call'
]
WATCHDOG_TOKEN_LIMIT = 30000  # tokens
WATCHDOG_TIMEOUT_SEC = 600     # 10 min hard cap

def _watchdog_loop(proc: subprocess.Popen, token_count: list, tool_called: list):
    """Monitor stdout pipe. Kill process if token limit hit with no tool call."""
    import re
    token_buf = b""
    start = time.time()
    while proc.poll() is None and time.time() - start < WATCHDOG_TIMEOUT_SEC:
        chunk = proc.stdout.read(4096)
        if not chunk:
            break
        token_buf += chunk
        # Rough token estimate: mean 4 chars/token
        tokens = len(token_buf) // 4
        token_count[0] = tokens
        # Check for tool call markers
        for pattern in TOOL_CALL_PATTERNS:
            if pattern in token_buf:
                tool_called[0] = True
                return  # normal — tool was called, watchdog stops
        if tokens > WATCHDOG_TOKEN_LIMIT and not tool_called[0]:
            print(f"[watchdog] KILLING Hermes after {tokens} tokens, no tool call detected")
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return

# In run_hermes():
proc = subprocess.Popen(
    [HERMES_CMD, "chat", "--profile", profile, "--query", query,
     "--toolsets", "terminal,file,web", "-v"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    preexec_fn=os.setsid,  # new process group for killpg
    cwd="/root"
)
token_count = [0]
tool_called = [False]
watchdog_thread = threading.Thread(target=_watchdog_loop,
                                   args=(proc, token_count, tool_called),
                                   daemon=True)
watchdog_thread.start()
try:
    output, _ = proc.communicate(timeout=1800)
except subprocess.TimeoutExpired:
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    output = b"TIMEOUT_OR_WATCHDOG_KILL"
```

#### A.3 Prompt Template — "NO PROSE FIRST"

Inject at the top of the query in `run_hermes()`:

```
## MANDATORY TOOL-USE SEQUENCE (v10 HARD RULE)
You MUST follow this exact sequence for every task:
  STEP 1 — Run: karios-vault search "<keywords>"  (or get_minimal_context if code)
  STEP 2 — Plan: decide which files need changes
  STEP 3 — Act: write_file / terminal calls
  STEP 4 — Report: send [ARCH-COMPLETE] or [CODING-COMPLETE] to orchestrator
DO NOT produce any prose before STEP 1. Every response turn MUST contain a tool call.
```

---

### B. JSON Schema Validation at Message Boundaries

#### B.1 Pydantic Models

Add to `/var/lib/karios/orchestrator/message_schemas.py` (new file):

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from enum import Enum

class SubjectKind(str, Enum):
    ARCH_COMPLETE = "ARCH-COMPLETE"
    ARCH_REVIEWED = "ARCH-REVIEWED"
    CODING_COMPLETE = "CODING-COMPLETE"
    E2E_RESULTS = "E2E-RESULTS"
    STAGING_DEPLOYED = "STAGING-DEPLOYED"
    PROD_DEPLOYED = "PROD-DEPLOYED"
    MONITORING_COMPLETE = "MONITORING-COMPLETE"
    API_SYNC = "API-SYNC"
    RECOVER = "RECOVER"
    ESCALATE = "ESCALATE"
    STATUS_REPLY = "STATUS-REPLY"
    NUDGE = "NUDGE"

class PhaseEnum(str, Enum):
    IDLE = "idle"
    PHASE_1 = "phase-1-research"
    PHASE_2 = "phase-2-arch"
    PHASE_3 = "phase-3-coding"
    PHASE_4 = "phase-4-testing"
    PHASE_5 = "phase-5-staging"
    PHASE_6 = "phase-6-monitor"

class ArchCompleteBody(BaseModel):
    phase: Literal["phase-2-arch"]
    iteration: int = Field(ge=1, le=10)
    gap_id: str
    trace_id: str
    files_changed: list[str]
    doc_sizes: dict[str, int]  # filename → byte count

    @field_validator("files_changed")
    @classmethod
    def all_docs_present(cls, v, info):
        required = {"architecture.md", "edge-cases.md", "test-cases.md",
                    "api-contract.md", "deployment-plan.md"}
        if not required.issubset(set(v)):
            raise ValueError(f"Missing docs: {required - set(v)}")
        return v

    @field_validator("doc_sizes")
    @classmethod
    def min_sizes(cls, v):
        for doc, size in v.items():
            if size < 2048:
                raise ValueError(f"{doc} is only {size} bytes — must be >= 2048")
        return v

class ArchReviewedBody(BaseModel):
    rating: int = Field(ge=0, le=10)
    gap_id: str
    iteration: int = Field(ge=1, le=10)
    score_breakdown: Optional[dict[str, int]] = None
    recommendation: Literal["APPROVE", "REJECT", "REVISE"]
    issues: Optional[list[str]] = None
    resilience_pass: Optional[bool] = None

class CodingCompleteBody(BaseModel):
    phase: Literal["phase-3-coding"]
    iteration: int = Field(ge=1, le=10)
    gap_id: str
    trace_id: str
    files_changed: list[str]
    build_passed: bool
    lint_passed: bool
    unit_tests_added: int

class E2EResultsBody(BaseModel):
    rating: int = Field(ge=0, le=10)
    gap_id: str
    iteration: int = Field(ge=1, le=10)
    recommendation: Literal["APPROVE", "REJECT"]
    criteria_scores: dict[str, int]  # dimension → score 0-2
    tests_passed: int
    tests_failed: int
    issues_found: int

class PhaseTransitionBody(BaseModel):
    gap_id: str
    from_phase: PhaseEnum
    to_phase: PhaseEnum
    score: Optional[int] = None
    recommendation: Optional[str] = None
```

#### B.2 Schema Registry

```python
MESSAGE_SCHEMAS: dict[str, type[BaseModel]] = {
    "ARCH-COMPLETE": ArchCompleteBody,
    "ARCH-REVIEWED": ArchReviewedBody,
    "CODING-COMPLETE": CodingCompleteBody,
    "E2E-RESULTS": E2EResultsBody,
    # other subjects...
}
```

#### B.3 Validation in `parse_message`

In `event_dispatcher.py`, modify `parse_message()`:

```python
def parse_message(msg_id: str, data: dict):
    subject = data.get("subject", "")
    # Extract JSON body from subject line pattern: [SUBJECT] ...
    body_text = data.get("body", "")
    # Try to find JSON block
    import re
    json_match = re.search(r"```json\s*(.*?)\s*```", body_text, re.DOTALL)
    if not json_match:
        # Try raw JSON
        json_match = re.search(r"\{.*\}", body_text, re.DOTALL)
    
    if json_match:
        try:
            json_body = json.loads(json_match.group(0))
            schema_cls = MESSAGE_SCHEMAS.get(subject)
            if schema_cls:
                validated = schema_cls.model_validate(json_body)
                data["_validated_body"] = validated.model_dump()
                data["_schema_valid"] = True
        except Exception as e:
            # Schema violation — reject + notify sender
            print(f"[dispatcher] SCHEMA VIOLATION from {data.get('from')}: {e}")
            # Send rejection back to sender
            send_to_agent(
                data.get("from", "unknown"),
                "[SCHEMA-REJECTED]",
                json.dumps({
                    "reason": str(e),
                    "subject": subject,
                    "gap_id": data.get("gap_id"),
                    "trace_id": data.get("trace_id")
                }),
                gap_id=data.get("gap_id"),
                trace_id=data.get("trace_id")
            )
            return None  # Don't dispatch invalid message
```

---

### C. End-to-End Self-Test: BG-stub-no-op Gap

#### C.1 Gap Definition

```json
{
  "gap_id": "BG-stub-no-op",
  "tier": "T0",
  "requirement": "Add a no-op feature flag to karios-migration that does absolutely nothing.",
  "feature_flag_key": "BG_STUB_NOOP_ENABLED",
  "feature_flag_default": false,
  "expected_phases": 6,
  "self_test": true,
  "success_criteria_per_phase": {
    "phase_1": "Research doc >= 512 bytes with web search evidence + infra test commands",
    "phase_2": "All 5 arch docs >= 2048 bytes, blind-review score 10/10",
    "phase_3": "1 Go file added, compiles (`go build ./...`), no corruption",
    "phase_4": "API contract updated, mock-server smoke test passes",
    "phase_5": "Staging deploy succeeds, service health check 200 OK",
    "phase_6": "Telegram message sent via notify_phase_transition() with complete summary"
  }
}
```

#### C.2 Orchestrator Trigger

Add to `event_dispatcher.py` a handler for `[SELF-TEST]` subject:

```python
elif subject == "[SELF-TEST]":
    # Run BG-stub-no-op through all 6 phases
    gap_id = "BG-stub-no-op"
    dispatch_research(gap_id, trace_id=new_trace_id(gap_id=gap_id, op="self-test"))
```

Sai can trigger via:
```
agent send orchestrator "[SELF-TEST]"
```

#### C.3 Measurable Per-Phase Gates

| Phase | Gate | Measurement |
|-------|------|-------------|
| 1 | MIN_SIZE=512, >=3 web sources, >=2 infra test commands | Size check + URL count + command output |
| 2 | ALL_DOCS >= 2048 bytes, blind-review score >= 10/10 | `stat` + blind-tester JSON score |
| 3 | Go file added, `go build ./...` exits 0 | `git diff --name-only` + `go build` |
| 4 | API contract updated, smoke test 200 OK | Contract diff + curl smoke test |
| 5 | Deploy success, health check 200 | Deploy log + curl |
| 6 | Telegram message sent | Telegram API `getUpdates` check |

---

### D. code-review-graph Rubric

#### D.1 Audit Log

In `agent-worker`, after each Hermes invocation, scan session log for `get_minimal_context` string:

```python
def check_code_review_graph_usage(output: str) -> bool:
    """Return True if get_minimal_context was called in this session."""
    return "get_minimal_context" in output

# After run_hermes completes:
graph_used = check_code_review_graph_usage(output)
audit_entry = {
    "gap_id": gap_id,
    "agent": AGENT,
    "trace_id": tid,
    "timestamp": current_ts(),
    "code_review_graph_used": graph_used,
    "phase": phase
}
r = get_redis()
r.xadd("stream:graph-audit", audit_entry)
```

#### D.2 Gate in Phase 3 Dispatch

Before dispatching to backend/frontend for Phase 3 coding, check graph-audit:

```python
def check_graph_rubric(gap_id: str, agent: str) -> bool:
    r = get_redis()
    # Get last 10 audit entries for this agent+gap
    entries = r.xrevrange("stream:graph-audit", "+", "-", count=10)
    for _, data in entries:
        if data.get("gap_id") == gap_id and data.get("agent") == agent:
            return data.get("code_review_graph_used", False) in ("true", "True", True)
    return False  # No record = fail open (lenient for Phase 1)
```

Phase 3 gate: If agent is `backend` or `frontend` and `check_graph_rubric` returns `False`, set `graph_violation=True` in metadata and either reject or log severe warning.

#### D.3 Scoring

Per-agent score: `1` if `get_minimal_context` called, `0` otherwise.
Overall rubric score = mean of all code-touching agents' scores.
Must be >= 1.0 (all agents must use it) to pass Phase 3 gate.

---

### E. Gitea Push Verification

#### E.1 Post-Deploy Push Check

Add to Phase 5 → Phase 6 transition in `event_dispatcher.py`:

```python
def verify_gitea_push(repo: str, branch: str = "main") -> bool:
    """Return True if HEAD commit is pushed to origin/<branch>."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count",
             f"origin/{branch}...HEAD"],
            capture_output=True, text=True, cwd=f"/root/karios-source-code/{repo}"
        )
        behind, ahead = map(int, result.stdout.strip().split())
        return behind == 0 and ahead == 0
    except Exception as e:
        print(f"[dispatcher] push verify failed: {e}")
        return False

# In PROD_DEPLOYED handler:
if not verify_gitea_push("karios-migration"):
    print("[dispatcher] REFUSING PROD-DEPLOYED: karios-migration not pushed to Gitea")
    send_to_agent("devops", "[PUSH-REQUIRED]",
                  f"gap_id={gap_id}: code must be pushed to gitea before PROD-DEPLOYED")
    return  # Don't fire MONITORING-COMPLETE
```

#### E.2 Refused `[PROD-DEPLOYED]` Path

If push verification fails:
1. Send `[PUSH-REQUIRED]` to devops with gap_id
2. Log incident to vault
3. Do NOT send `[MONITORING-COMPLETE]`
4. DevOps must push and re-trigger

---

### F. No Telegram From Human Admin

#### F.1 Bot Handler Filter

In `karios-hitl-listener` or the Telegram bot handler:

```python
ALLOWED_TELEGRAM_SENDERS = {
    "notify_phase_transition",
    "telegram_alert",
    "publish_alert",  # internal dispatcher function
}

def is_pipeline_origin(update: dict) -> bool:
    """Check if the update originated from the pipeline itself (not a human)."""
    # Pipeline messages have a marker in their callback_data or text
    return update.get("callback_data", "").startswith("karios_auto:")
    # Human messages won't have this prefix

# In message handler:
if not is_pipeline_origin(update) and update.get("message", {}).get("text", "").startswith("/"):
    # Auto-reply to / commands
    bot.send_message(
        chat_id=update["message"]["chat"]["id"],
        text="🤖 This bot is pipeline-controlled. Use /status for automated info."
    )
    return
```

#### F.2 Remove Direct Command Handlers

Strip any `/start`, `/help`, `/debug` handlers that accept human input and produce responses.
Keep only the webhook endpoint that `notify_phase_transition()` calls directly via HTTP.

---

## Data Flows

### Tool-Use Watchdog Flow
```
agent-worker.run_hermes()
  → subprocess.Popen(hermes chat ...)
  → watchdog_thread starts (daemon)
  → thread reads stdout pipe, counts tokens
  → if tokens > 30K and no tool_call detected:
      → os.killpg(SIGKILL)
      → return "WATCHDOG_KILL: no tool call in 30K tokens"
  → stream_progress("task_completed" or "task_watchdog_kill")
```

### Message Validation Flow
```
parse_message(msg_id, data)
  → extract subject from data["subject"]
  → find JSON body in data["body"]
  → look up MESSAGE_SCHEMAS[subject]
  → Pydantic.model_validate(json_body)
  → if valid: data["_validated_body"] = validated; dispatch
  → if invalid: send_to_agent("[SCHEMA-REJECTED]", reason); return None
```

### Gitea Push Verification Flow
```
handle_prod_deployed(gap_id, ...)
  → verify_gitea_push("karios-migration")
  → git rev-list --left-right --count origin/main...HEAD
  → if (0, 0): allow PROD-DEPLOYED
  → else: send_to_agent("devops", "[PUSH-REQUIRED]"); do NOT advance to Phase 6
```

---

## File Changes Summary

| File | Change |
|------|--------|
| `/root/.hermes/config.yaml` | `tool_use_enforcement: auto` → `strict` |
| All 9 `/root/.hermes/profiles/*/config.yaml` | Add `tool_use_enforcement: strict` |
| `/usr/local/bin/agent-worker` | Add watchdog in `run_hermes()` (SIGKILL on 30K tokens, no tool) |
| `/var/lib/karios/orchestrator/message_schemas.py` | NEW: Pydantic models for all message subjects |
| `/var/lib/karios/orchestrator/event_dispatcher.py` | Add schema validation in `parse_message`, push verification, self-test trigger |
| `/var/lib/karios/coordination/state-schema.json` | Add new schemas for v10 message types |
| `/var/lib/karios/coordination/requirements/BG-stub-no-op.md` | NEW: Self-test gap definition |
| `karios-hitl-listener` | Add pipeline-origin filter, remove human command handlers |

---

## Deployment Sequence

1. **Pre-deploy**: Archive current v7.4 state (`karios-meta-runner archive`)
2. **Phase 1**: Deploy message_schemas.py + dispatcher patch (schema validation only — no behavior change yet)
3. **Phase 2**: Deploy agent-worker watchdog (opt-in via env var `WATCHDOG_ENABLED=1`)
4. **Phase 3**: Flip `tool_use_enforcement: strict` in config (requires restart of all 9 agents)
5. **Phase 4**: Deploy push verification + self-test trigger
6. **Phase 5**: Deploy Telegram filter
7. **Verify**: Trigger BG-stub-no-op self-test, confirm all 6 phases pass

Rollback: `karios-meta-runner rollback` restores previous v7.4 state.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|--------|
| `tool_use_enforcement: strict` causes Hermes to refuse tasks (loop on "I need to use a tool but none is available") | Medium | High | Keep `auto` as fallback for non-coding agents; strict only for architect/backend/frontend |
| Watchdog SIGKILL during Phase 2 long write operations (legitimate >30K prose before first tool) | Low | Medium | 30K token threshold is generous (Hermes typically calls tool within 500-2000 tokens); tune if needed |
| Pydantic validation breaks on backwards-incompatible agent output | Medium | Medium | Defensive `try/except` in `parse_message` — on any exception, fall back to unvalidated dispatch (v7.3 behavior) |
| BG-stub-no-op gap pollutes production namespace | Low | Low | It is a no-op feature flag — zero functional impact; just exercises the pipeline |
| Gitea push verification fails due to network/credential issues (false positive) | Medium | Low | Add `PUSH_VERIFY_TIMEOUT=30` env; on timeout, log warning but allow PROD-DEPLOYED with notification |
