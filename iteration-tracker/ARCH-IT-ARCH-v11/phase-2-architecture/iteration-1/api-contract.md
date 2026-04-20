# API Contract — ARCH-IT-ARCH-v11 (iteration 1)

## Overview

This document defines API contracts for all new components introduced by items A–F of ARCH-IT-ARCH-v11.
v7.5 existing APIs are listed for reference and MUST NOT be modified.

---

## Existing APIs (v7.5 — Do Not Modify)

### Orchestrator → Agent: Stream Publish
```
Redis Streams: XADD stream:{agent} payload
```
Existing — no changes.

### Agent → Orchestrator: File Inbox
```
Path: /var/lib/karios/agent-msg/inbox/orchestrator/{uuid}.json
Format: {"from": "...", "subject": "...", "body": "...", "gap_id": "...", "trace_id": "...", "created_at": "..."}
```
Existing — no changes.

### Orchestrator → Telegram
```
POST https://api.telegram.org/bot{TOKEN}/sendMessage
Body: {"chat_id": "...", "text": "...", "parse_mode": "Markdown"}
```
Existing — no changes.

### Orchestrator → Agent: Redis Pub/Sub
```
Channel: agent.stream
Payload: {"event_type": "...", "agent": "...", "gap_id": "...", "trace_id": "...", "message": "...", "detail": "...", "timestamp": "...", "phase": "..."}
```
Existing — no changes.

---

## New APIs: Item A (Pydantic Schema Validation)

### Schema File Module
```
File: /var/lib/karios/orchestrator/message_schemas.py
```

#### Public Functions

**`validate_message(subject: str, body: str) -> tuple[bool, Optional[str], Optional[BaseModel]]`**
- **Description**: Validates a message body against the Pydantic schema that matches the subject prefix.
- **Args**:
  - `subject: str` — message subject line (e.g., `"[ARCH-REVIEWED] ARCH-IT-ARCH-v11 iteration 1"`)
  - `body: str` — JSON-encoded message body
- **Returns**: `(valid: bool, reason: Optional[str], instance: Optional[BaseModel])`
  - `valid=True, reason=None, instance=<Model>` = passed validation
  - `valid=False, reason=<str>, instance=None` = failed validation
  - `valid=True, reason=None, instance=None` = no schema defined for subject (legacy compat)
- **Errors**: Never raises — all exceptions caught internally
- **Side Effects**: Writes quarantine file to `/var/lib/karios/agent-msg/schema-violations/` on validation failure

**`get_schema_for_subject(subject: str) -> Optional[type[BaseModel]]`**
- **Description**: Returns the Pydantic model class for a given subject prefix
- **Args**: `subject: str`
- **Returns**: Model class or `None` if no schema defined
- **Errors**: None

#### Schema Models

All models in `message_schemas.py`:

| Model | Subject Prefixes | Key Fields |
|-------|-----------------|------------|
| `ArchCompleteBody` | `[ARCH-COMPLETE]`, `[ARCHITECTURE-COMPLETE]` | `gap_id: str`, `iteration: int`, `files_changed: List[str]` |
| `ArchReviewedBody` | `[ARCH-REVIEWED]`, `[BLIND-REVIEWED]` | `gap_id: str`, `iteration: int`, `rating: int (1-10)`, `recommendation: str` |
| `CodingCompleteBody` | `[CODING-COMPLETE]` | `gap_id: str`, `iteration: int`, `files_changed: List[str]` |
| `E2EResultsBody` | `[E2E-RESULTS]`, `[E2E-COMPLETE]`, `[TEST-RESULTS]`, `[BLIND-E2E-RESULTS]` | `gap_id: str`, `iteration: int`, `rating: int (1-10)` |
| `StagingDeployedBody` | `[DEPLOYED-STAGING]`, `[STAGING-COMPLETE]` | `gap_id: str`, `iteration: int`, `deploy_url: str` |
| `ProdDeployedBody` | `[DEPLOYED-PROD]`, `[DEPLOY-DONE]`, `[PRODUCTION-COMPLETE]`, `[PROD-DEPLOYED]` | `gap_id: str`, `iteration: int`, `deploy_url: str` |
| `MonitoringCompleteBody` | `[MONITORING-COMPLETE]` | `gap_id: str`, `iteration: int`, `uptime_seconds: int` |
| `RequirementBody` | `[REQUIREMENT]` | `gap_id: str`, `message: str`, `priority: str` |
| `ResearchCompleteBody` | `[RESEARCH-COMPLETE]` | `gap_id: str`, `iteration: int`, `files_changed: List[str]` |

---

## New APIs: Item B (Self-Test CLI)

### Self-Test CLI
```
File: /usr/local/bin/karios-self-test
```

**`karios-self-test [--gap-id BG-stub-no-op] [--timeout 1800]`**
- **Description**: Runs the pipeline self-test gap through all 6 phases. Asserts each phase boundary fires within timeout.
- **Args**:
  - `--gap-id` (optional): Gap ID to use for self-test. Default: `BG-stub-no-op`
  - `--timeout` (optional): Total timeout in seconds. Default: `1800` (30 min)
- **Returns**: Exit code 0 = all phases fired. Exit code 1 = failure.
- **Output**: Logs to stdout + `/var/lib/karios/self-test-results/{gap_id}.jsonl`
- **Errors**: Non-zero exit on any phase boundary timeout

### Self-Test Results Log
```
File: /var/lib/karios/self-test-results/{gap_id}.jsonl
Format: One JSON object per line:
{"phase": "0→1", "event": "[REQUIREMENT]", "timestamp": "2026-04-19T...", "elapsed_ms": 1234}
{"phase": "1→2", "event": "[RESEARCH-COMPLETE]", "timestamp": "...", "elapsed_ms": 45678}
...
```

### BG-stub-no-op Requirement
```
File: /var/lib/karios/coordination/requirements/BG-stub-no-op.md
Format: Markdown requirement document (see architecture.md Section B.1)
```

---

## New APIs: Item C (code-review-graph Rubric Gate)

### Agent-Worker Post-Hermes Hook
```
File: /var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker (production: /usr/local/bin/agent-worker)
```

**`_check_code_review_graph_usage(task: str, hermes_output: str, agent: str) -> None`**
- **Description**: Called after Hermes completes. Checks if task touches code and if Hermes called `get_minimal_context`. Writes vault critique if missing.
- **Args**:
  - `task: str` — the original task description
  - `hermes_output: str` — full Hermes stdout+stderr
  - `agent: str` — agent name (e.g., `"backend-worker"`)
- **Returns**: None
- **Side Effects**: Calls `karios-vault critique --agent X --failed "skipped get_minimal_context"` if conditions met
- **Errors**: Swallowed — never propagates

**`_extract_session_metadata(session_id: str) -> dict`**
- **Description**: Extracts metadata from Hermes session log
- **Args**: `session_id: str`
- **Returns**: `{"code_review_graph_calls": int}`
- **Errors**: Returns `{"code_review_graph_calls": 0}` on any error

### Orchestrator Gate
```
File: /var/lib/karios/orchestrator/event_dispatcher.py
```

**`handle_coding_complete(gap_id: str, iteration: int, body: str, trace_id: str, session_metadata: dict)`**
- **Modified signature**: Adds `session_metadata: dict` parameter
- **Gate logic**: If `sender in ("backend", "frontend")` AND `session_metadata.get("code_review_graph_calls", 0) == 0` → refuse advance, send `[CODING-RETRY]`

### New Message Type: `[CODING-RETRY]`
```
Subject: [CODING-RETRY] {gap_id}
Body: {"reason": "code_review_graph_calls=0 — retry with get_minimal_context", "gap_id": "...", "iteration": ...}
From: orchestrator
To: backend or frontend
Priority: high
```

---

## New APIs: Item D (Gitea Push Verification Gate)

### Verification Function
```
File: /var/lib/karios/orchestrator/event_dispatcher.py
```

**`verify_gitea_push(gap_id: str, repos: list[str]) -> tuple[bool, str]`**
- **Description**: Checks git push status for each repo in the gap's manifest
- **Args**:
  - `gap_id: str`
  - `repos: list[str]` — e.g., `["karios-migration", "karios-web"]`
- **Returns**: `(ok: bool, message: str)`
  - `(True, "all repos up-to-date with origin")` = all clean
  - `(False, "karios-migration: 3 ahead, 0 behind origin; karios-web: 0 ahead, 0 behind")` = failures
- **Errors**: Caught per-repo; errors included in message string
- **Side Effects**: Reads git state only — no modifications

**`read_gap_manifest(gap_id: str) -> dict`**
- **Description**: Reads iteration-tracker manifest for a gap
- **Args**: `gap_id: str`
- **Returns**: `{"repos_touched": [...], "files_changed": [...], "iteration": int, ...}`
- **Errors**: Returns `{"repos_touched": []}` if manifest missing

### New Message Type: `[GITEA-PUSH-PENDING]`
```
Subject: [GITEA-PUSH-PENDING] {gap_id}
Body: {"repos": ["karios-migration", "karios-web"], "diff_detail": "karios-migration: 3 ahead...", "gap_id": "..."}
From: orchestrator
To: devops
Priority: high
```

### Orchestrator Gate
```
Modified: handle_prod_deployed() — calls verify_gitea_push() before Phase 6 transition
On failure: sends [GITEA-PUSH-PENDING] to devops, does NOT call notify_phase_transition()
On success: proceeds with Phase 6 transition
```

---

## New APIs: Item E (Watchdog Kill-on-No-Tool-Call)

### PTY-Based Hermes Runner
```
File: /var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker (production: /usr/local/bin/agent-worker)
```

**`run_hermes_pty(task: str, agent_name: str, gap_id: str = None, trace_id: str = None, phase: str = None) -> str`**
- **Description**: Runs Hermes with PTY streaming for token-counting watchdog
- **Args**:
  - `task: str` — task description
  - `agent_name: str` — agent name
  - `gap_id: str` (optional)
  - `trace_id: str` (optional)
  - `phase: str` (optional)
- **Returns**: Full Hermes output string (includes `[WATCHDOG-RETRY]` suffix if retry happened)
- **Watchdog behavior**:
  - Token count > 4000 with 0 `tool_use` events → SIGTERM
  - Retry: query prefixed by `"BEGIN by calling karios-vault.search. Do not output prose first."`
  - If retry also killed → do NOT retry again, return with `[WATCHDOG-RETRY-SKIPPED]`
- **PTY errors**: Falls back to `subprocess.run` if PTY unavailable
- **Side Effects**: May send SIGTERM to Hermes process group

**`stream_reader(master_fd: int, output_chunks: list, token_count: float, tool_use_events: int, tool_use_detected: Event) -> None`**
- **Description**: Background thread that reads PTY, counts tokens, detects tool_use events
- **Args**:
  - `master_fd: int` — PTY master file descriptor
  - `output_chunks: list` — append decoded chunks here
  - `token_count: float` — running token estimate (modified in place)
  - `tool_use_events: int` — count of tool_use occurrences (modified in place)
  - `tool_use_detected: threading.Event` — set when tool_use found
- **Returns**: None
- **Side Effects**: May call `os.killpg()` with SIGTERM

### Token Counting Formula
```
token_count += len(decoded.split()) * 1.3  # rough token estimate: words × 1.3
```

### Tool Use Detection
```
if '"tool_use"' in decoded or 'tool_use' in decoded:
    tool_use_events += 1
    tool_use_detected.set()
```
Matches both JSON-formatted and plain-text occurrences of `tool_use`.

---

## New APIs: Item F (tool_choice Passthrough — Deferred)

### No new APIs for Item F (deferred)
```
Documentation only — no implementation in this iteration
```

---

## Iteration Manifest Schema

```
File: /var/lib/karios/iteration-tracker/{gap_id}/manifest.json
```

```json
{
  "gap_id": "string",
  "iteration": "integer",
  "repos_touched": ["string"],
  "files_changed": ["string"],
  "created_at": "ISO8601 timestamp",
  "completed_at": "ISO8601 timestamp or null"
}
```

**`repos_touched`**: Git repo names in `/root/karios-source-code/` that this gap modified.
**`files_changed`**: Absolute paths of files modified by this gap.

---

## Schema Violation Quarantine

```
Directory: /var/lib/karios/agent-msg/schema-violations/
File format: {uuid8}_{sanitized_subject}.json
Content: {"subject": "...", "body": "...", "reason": "...", "timestamp": "..."}
```

Example: `a1b2c3d4_ARCH_REVIEWED.json`

---

## Vault Critique Format

```
Command: /usr/local/bin/karios-vault critique --agent {agent} --failed "{reason}" --task "{task_excerpt}" --trace {trace_id}
Output: Entry written to vault at /opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/critiques/
Kind: critique
```

---

## Integration Points

### Dispatcher parse_message() Integration
```
Location: event_dispatcher.py:parse_message()
Change: Call validate_message(subject, body) BEFORE any handler dispatch
On valid: continue to handler
On invalid (iteration 2+): quarantine + send [SCHEMA-VIOLATION] to sender
On invalid (iteration 1): log only, continue to handler
```

### Dispatcher handle_coding_complete() Integration
```
Location: event_dispatcher.py
Change: Extract session_metadata from data.get("session_metadata", {})
Gate: If code_profiles[sender] and code_review_graph_calls == 0 → refuse with [CODING-RETRY]
```

### Dispatcher handle_prod_deployed() Integration
```
Location: event_dispatcher.py
Change: Call verify_gitea_push(gap_id, repos) before Phase 6 transition
On failure: send [GITEA-PUSH-PENDING], do NOT enter Phase 6
On success: continue to Phase 6 transition
```