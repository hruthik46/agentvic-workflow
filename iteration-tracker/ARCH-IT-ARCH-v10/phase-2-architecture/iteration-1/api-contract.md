# API Contract — ARCH-IT-ARCH-v10 (iteration 1)

## Overview

Changes to the API contract for v10 fall into 3 categories:
1. **New message schemas** (Pydantic models) for all inter-agent messages
2. **New subjects** for v10-specific communication
3. **Modified handling rules** for existing subjects

---

## 1. New Message Schemas (Pydantic Models)

### File: `/var/lib/karios/orchestrator/message_schemas.py`

```python
# Architect → Orchestrator
ARCH_COMPLETE = "ARCH-COMPLETE"
# body: ArchCompleteBody (JSON)

# Architect-Blind-Tester → Orchestrator  
ARCH_REVIEWED = "ARCH-REVIEWED"
# body: ArchReviewedBody (JSON)

# Backend/Frontend → Orchestrator
CODING_COMPLETE = "CODING-COMPLETE"
# body: CodingCompleteBody (JSON)

# Code-Blind-Tester → Orchestrator
E2E_RESULTS = "E2E-RESULTS"
# body: E2EResultsBody (JSON)

# Orchestrator → All
NUDGE = "NUDGE"
# body: NudgeBody (JSON)

# Orchestrator → Sai
MONITORING_COMPLETE = "MONITORING-COMPLETE"
# body: PhaseTransitionBody (JSON)

# Orchestrator → DevOps
PUSH_REQUIRED = "PUSH-REQUIRED"
# body: PushRequiredBody (JSON)

# Orchestrator → Any Agent
SCHEMA_REJECTED = "SCHEMA-REJECTED"
# body: SchemaRejectedBody (JSON)

# Any Agent → Orchestrator
SELF_TEST = "[SELF-TEST]"
# Triggers BG-stub-no-op self-test gap
```

### Schema Definitions

```json
{
  "ArchCompleteBody": {
    "type": "object",
    "required": ["phase", "iteration", "gap_id", "trace_id", "files_changed", "doc_sizes"],
    "properties": {
      "phase": {"const": "phase-2-arch"},
      "iteration": {"type": "integer", "minimum": 1, "maximum": 10},
      "gap_id": {"type": "string"},
      "trace_id": {"type": "string"},
      "files_changed": {
        "type": "array",
        "items": {"type": "string"},
        "contains_all": ["architecture.md", "edge-cases.md", "test-cases.md", "api-contract.md", "deployment-plan.md"]
      },
      "doc_sizes": {
        "type": "object",
        "additionalProperties": {"type": "integer", "minimum": 2048}
      }
    }
  },
  "ArchReviewedBody": {
    "type": "object",
    "required": ["rating", "gap_id", "iteration", "recommendation"],
    "properties": {
      "rating": {"type": "integer", "minimum": 0, "maximum": 10},
      "gap_id": {"type": "string"},
      "iteration": {"type": "integer", "minimum": 1, "maximum": 10},
      "recommendation": {"enum": ["APPROVE", "REJECT", "REVISE"]},
      "issues": {"type": "array", "items": {"type": "string"}},
      "resilience_pass": {"type": "boolean"}
    }
  },
  "CodingCompleteBody": {
    "type": "object",
    "required": ["phase", "iteration", "gap_id", "trace_id", "files_changed", "build_passed", "lint_passed", "unit_tests_added"],
    "properties": {
      "phase": {"const": "phase-3-coding"},
      "iteration": {"type": "integer", "minimum": 1, "maximum": 10},
      "gap_id": {"type": "string"},
      "trace_id": {"type": "string"},
      "files_changed": {"type": "array", "items": {"type": "string"}},
      "build_passed": {"type": "boolean"},
      "lint_passed": {"type": "boolean"},
      "unit_tests_added": {"type": "integer", "minimum": 0}
    }
  },
  "E2EResultsBody": {
    "type": "object",
    "required": ["rating", "gap_id", "iteration", "recommendation", "criteria_scores", "tests_passed", "tests_failed", "issues_found"],
    "properties": {
      "rating": {"type": "integer", "minimum": 0, "maximum": 10},
      "gap_id": {"type": "string"},
      "iteration": {"type": "integer", "minimum": 1, "maximum": 10},
      "recommendation": {"enum": ["APPROVE", "REJECT"]},
      "criteria_scores": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0, "maximum": 2}},
      "tests_passed": {"type": "integer", "minimum": 0},
      "tests_failed": {"type": "integer", "minimum": 0},
      "issues_found": {"type": "integer", "minimum": 0}
    }
  },
  "SchemaRejectedBody": {
    "type": "object",
    "required": ["reason", "subject", "gap_id"],
    "properties": {
      "reason": {"type": "string"},
      "subject": {"type": "string"},
      "gap_id": {"type": "string"},
      "trace_id": {"type": "string"}
    }
  },
  "PushRequiredBody": {
    "type": "object",
    "required": ["gap_id", "repo"],
    "properties": {
      "gap_id": {"type": "string"},
      "repo": {"type": "string"},
      "message": {"type": "string"}
    }
  }
}
```

---

## 2. New Subjects

### `[SELF-TEST]`
**Direction**: Any → Orchestrator
**Trigger**: Sai sends `agent send orchestrator "[SELF-TEST]"` or orchestrator auto-triggered on schedule.
**Body**: None required (empty body OK).
**Response**: Orchestrator dispatches Phase 1 research for `BG-stub-no-op`.
**Validation**: No schema (empty body OK). Rate-limited: only one concurrent self-test allowed.
**Error Response**: If self-test already running, sends `[STATUS-REPLY]` "self-test already in progress".

### `[PUSH-REQUIRED]`
**Direction**: Orchestrator → DevOps
**Trigger**: `verify_gitea_push()` fails for one or more repos.
**Body**: `PushRequiredBody` JSON.
**Response**: DevOps pushes the specified repo and re-triggers `[PROD-DEPLOYED]`.
**Error**: DevOps ignores → gap stuck at Phase 5, escalates after 3 retries.

### `[SCHEMA-REJECTED]`
**Direction**: Orchestrator → Original Sender
**Trigger**: `parse_message` fails schema validation.
**Body**: `SchemaRejectedBody` JSON with reason.
**Response**: Original agent must fix and resend with valid JSON.
**Logging**: Full violation logged to `/var/lib/karios/coordination/schema-violations/<msg_id>.json`.

---

## 3. Modified Handling Rules

### `[ARCH-COMPLETE]` — Enhanced Validation
**Previous**: Orchestrator checked doc sizes via `sop_engine`.
**v10 Change**: Full Pydantic validation via `ArchCompleteBody`. All 5 docs must be >= 2048 bytes (enforced in schema). Missing doc → `[SCHEMA-REJECTED]`.

### `[ARCH-REVIEWED]` — Defensive KeyError Fix
**Previous**: `handle_arch_review` had defensive KeyError handling.
**v10 Change**: Full Pydantic validation via `ArchReviewedBody`. Missing `rating` field → `[SCHEMA-REJECTED]` sent back to blind-tester.

### `[CODING-COMPLETE]` — New Required Fields
**Previous**: Only `files_changed` required.
**v10 Change**: `CodingCompleteBody` requires `build_passed`, `lint_passed`, `unit_tests_added`. Schema enforced before dispatch.

### `[E2E-RESULTS]` — Schema Strictness
**Previous**: Loosely parsed (any JSON accepted).
**v10 Change**: `E2EResultsBody` with required `rating`, `recommendation`, `criteria_scores`. Optional fields for backwards compat.

---

## 4. Redis Stream Changes

### New Stream: `stream:graph-audit`
**Written by**: `agent-worker` after each Hermes session.
**Read by**: Orchestrator Phase 3 gate check.
**Entry format**:
```json
{
  "gap_id": "BG-01",
  "agent": "backend",
  "trace_id": "trace_BACK_codin_abc123",
  "timestamp": "2026-04-20T00:00:00Z",
  "code_review_graph_used": "true",
  "phase": "phase-3-coding"
}
```

### New Stream: `stream:schema-violations`
**Written by**: Orchestrator `parse_message` on schema violation.
**Read by**: Monitor agent for alerting.
**Entry format**:
```json
{
  "msg_id": "msg_abc123",
  "from_agent": "architect-blind-tester",
  "subject": "ARCH-REVIEWED",
  "reason": "rating field missing",
  "gap_id": "BG-01",
  "timestamp": "2026-04-20T00:00:00Z"
}
```

---

## 5. Orchestrator API Changes

### `parse_message(msg_id, data)` — Enhanced
**Before**: Deserialized envelope, detected subject, dispatched.
**After**: Deserializes envelope → finds JSON body → looks up schema → validates → dispatches OR rejects.

### `verify_gitea_push(repo, branch)` — New Function
**Returns**: `bool`
**Behavior**: Runs `git rev-list --left-right --count origin/<branch>...HEAD` in repo. Returns `True` if both counts are 0.

### `check_graph_rubric(gap_id, agent)` — New Function
**Returns**: `bool` (True = graph used, False = not used)
**Behavior**: Reads `stream:graph-audit` for most recent entry for this agent+gap. Returns `code_review_graph_used` value.

### `handle_self_test()` — New Handler
**Triggered by**: `[SELF-TEST]` subject.
**Behavior**: Dispatches `BG-stub-no-op` to Phase 1 research. Sets concurrency lock in Redis.

---

## 6. Agent-Worker API Changes

### `run_hermes(task, agent_name, gap_id, trace_id, phase)` — Enhanced
**Before**: `subprocess.run([HERMES_CMD, "chat", ...], capture_output=True)`
**After**: `subprocess.Popen` with watchdog thread monitoring token count. SIGKILL on 30K tokens no-tool. Also writes to `stream:graph-audit` on completion.

### Environment Variable Changes
| Variable | Default | Description |
|----------|---------|-------------|
| `WATCHDOG_ENABLED` | `0` | Set to `1` to enable watchdog |
| `WATCHDOG_TOKEN_LIMIT` | `30000` | Token count before kill |
| `WATCHDOG_TIMEOUT_SEC` | `600` | Hard cap (10 min) |
| `TOOL_USE_ENFORCEMENT` | `strict` | Applied to hermes config |
| `PUSH_VERIFY_TIMEOUT` | `30` | Seconds before git push verify times out |

---

## 7. Telegram API Changes

### `notify_phase_transition(gap_id, from_phase, to_phase, score, recommendation)` — Enhanced
**Before**: Simple Telegram send.
**After**: Fetches chat_id from secrets.env at call time (not cached). Retries on 429 (max 3). Logs to vault on failure.

### Allowed Send Sources
Only these may call Telegram bot API:
- `notify_phase_transition()`
- `telegram_alert()` (internal dispatcher)
- `publish_alert()` (internal)

### Human Command Handlers (Reduced)
| Command | Access | Behavior |
|---------|--------|----------|
| `/status` | Public | Returns current pipeline status |
| `/emergency-unblock <gap_id>` | Admin | Unblocks stuck gap, logs to vault |
| `/help` | Public | "Pipeline-controlled bot — use /status" |

---

## 8. State Schema Changes

### New Fields in `state-schema.json`

```json
{
  "orchestrator": {
    "fields": {
      "self_test_running": {"type": "bool"},
      "self_test_gap_id": {"type": "string", "nullable": true}
    }
  },
  "architect": {
    "fields": {
      "graph_usage_score": {"type": "float", "nullable": true}
    }
  },
  "backend": {
    "fields": {
      "graph_usage_score": {"type": "float", "nullable": true},
      "last_push_verify": {"type": "string", "format": "iso8601", "nullable": true}
    }
  }
}
```

---

## 9. Backwards Compatibility

- All schema validations wrapped in `try/except`. On exception, fall back to v7.3 behavior (no validation, just dispatch).
- `MessageEnvelope` v7 format unchanged. Old messages without `version` field are handled by envelope's `__init__` defaults.
- New optional fields in schemas don't break old agents (Optional[T] with defaults).
- Redis stream `stream:graph-audit` is append-only. Old consumers that don't read it are unaffected.
- `WATCHDOG_ENABLED=0` preserves exact v7.4 behavior when not explicitly enabled.
