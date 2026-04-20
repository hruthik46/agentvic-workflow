# Test Cases — ARCH-IT-ARCH-v11 (iteration 1)

## Overview

Test cases cover all 6 items (A–F) from the v11 requirement. Items are grouped by component.
F (tool_choice passthrough) is deferred — only documentation tests are provided.

**Environment**: v7.5 LIVE at 192.168.118.106. Orchestrator at `/var/lib/karios/orchestrator/event_dispatcher.py`.

---

## Item A: Pydantic Schema Validation

### Schema TC-A-01: Valid ARCH-REVIEWED JSON passes validation
- **Input**: `{"gap_id":"ARCH-IT-ARCH-v11","iteration":1,"rating":8,"critical_issues":[],"summary":"ok","dimensions":{},"adversarial_test_cases":{},"recommendation":"APPROVE"}`
- **Expected**: `validate_message()` returns `(True, None, ArchReviewedBody instance)`
- **Phase**: Unit test in `message_schemas_test.py`

### Schema TC-A-02: ARCH-REVIEWED missing `rating` field triggers violation
- **Input**: `{"gap_id":"ARCH-IT-ARCH-v11","iteration":1,"summary":"missing rating"}`
- **Expected**: `validate_message()` returns `(False, "Pydantic validation error: ValueError", None)`. File quarantined to `/var/lib/karios/agent-msg/schema-violations/`.
- **Phase**: Unit test. Iteration 1: log-only (no quarantine). Iteration 2: enforce.

### Schema TC-A-03: ARCH-REVIEWED `rating` out of range (11) triggers violation
- **Input**: `{"gap_id":"ARCH-IT-ARCH-v11","iteration":1,"rating":11,"critical_issues":[],"summary":"","dimensions":{},"adversarial_test_cases":{},"recommendation":"APPROVE"}`
- **Expected**: `validate_message()` returns `(False, "Pydantic validation error: ValidationError", None)`
- **Phase**: Unit test

### Schema TC-A-04: StagingDeployedBody accepts valid deploy payload
- **Input**: `{"gap_id":"BG-stub-no-op","iteration":1,"deploy_url":"https://staging.karios.ai/bg-stub","artifacts":["/tmp/test"],"phase":"phase-5-staging"}`
- **Expected**: `validate_message()` returns `(True, None, StagingDeployedBody instance)`
- **Phase**: Unit test

### Schema TC-A-05: ProdDeployedBody rejects missing `gap_id`
- **Input**: `{"iteration":1,"deploy_url":"https://karios.ai","artifacts":[]}`
- **Expected**: Validation error returned, quarantine file written
- **Phase**: Unit test

### Schema TC-A-06: RequirementBody with all optional fields empty passes
- **Input**: `{}`
- **Expected**: `validate_message()` returns `(True, None, RequirementBody instance)` (all fields optional except `gap_id`)
- **Phase**: Unit test

### Schema TC-A-07: Unrecognized subject prefix passes through (legacy compat)
- **Input**: Subject `[CUSTOM-UNKNOWN]` with body `{"foo":"bar"}`
- **Expected**: `validate_message()` returns `(True, None, None)` — no schema match, pass through
- **Phase**: Unit test

### Schema TC-A-08: Invalid JSON body triggers JSON parse error
- **Input**: `{"gap_id": "ARCH-IT-ARCH-v11", invalid json}`
- **Expected**: Quarantine written, reason = "JSON parse error"
- **Phase**: Integration test with actual dispatcher

---

## Item B: BG-stub-no-op Self-Test

### Self-Test TC-B-01: `karios-self-test` CLI exists and is executable
- **Command**: `test -x /usr/local/bin/karios-self-test && echo OK || echo FAIL`
- **Expected**: `OK`
- **Phase**: Pre-flight

### Self-test TC-B-02: Requirement dispatched → `[REQUIREMENT]` received within 30s
- **Setup**: Run `agent send orchestrator "[REQUIREMENT] BG-stub-no-op: pipeline self-test"`
- **Expected**: Within 30s, orchestrator log shows `[REQUIREMENT]` processed
- **Phase**: E2E self-test, Phase 0→1

### Self-test TC-B-03: Phase 1 → 2: `[RESEARCH-COMPLETE]` fires within 120s
- **Trigger**: `[REQUIREMENT]` for BG-stub-no-op received
- **Expected**: `[RESEARCH-COMPLETE]` received by orchestrator within 120s
- **Phase**: E2E self-test, Phase 1→2

### Self-test TC-B-04: Phase 2 → 3: `[ARCH-COMPLETE]` + `[ARCH-REVIEWED]` (rating≥8) within 300s
- **Trigger**: `[RESEARCH-COMPLETE]` for BG-stub-no-op received
- **Expected**: `[ARCH-COMPLETE]` AND `[ARCH-REVIEWED]` (rating ≥ 8) received within 300s
- **Phase**: E2E self-test, Phase 2→3

### Self-test TC-B-05: Phase 3 → 4: `[CODING-COMPLETE]` fires within 300s
- **Trigger**: `[ARCH-REVIEWED]` rating ≥ 8 received
- **Expected**: `[CODING-COMPLETE]` received within 300s
- **Phase**: E2E self-test, Phase 3→4

### Self-test TC-B-06: Phase 4 → 5: `[DEPLOYED-STAGING]` fires within 300s
- **Trigger**: `[CODING-COMPLETE]` received
- **Expected**: `[DEPLOYED-STAGING]` received within 300s
- **Phase**: E2E self-test, Phase 4→5

### Self-test TC-B-07: Phase 5 → 6: `[DEPLOYED-PROD]` fires within 300s
- **Trigger**: `[DEPLOYED-STAGING]` received
- **Expected**: `[DEPLOYED-PROD]` received within 300s
- **Phase**: E2E self-test, Phase 5→6

### Self-test TC-B-08: `karios-self-test` exits 0 after all phases fire
- **Command**: `/usr/local/bin/karios-self-test`
- **Expected**: Exit code 0
- **Timeout**: 30 minutes
- **Phase**: E2E self-test final

### Self-test TC-B-09: Telegram alert received for each phase transition
- **Setup**: During `karios-self-test` run, monitor Telegram bot messages
- **Expected**: At least 6 Telegram notifications (one per phase transition) received
- **Phase**: E2E self-test Telegram verification

---

## Item C: code-review-graph Rubric Gate

### CRG TC-C-01: Agent-worker writes critique when get_minimal_context missing on code task
- **Setup**: Mock Hermes session log with zero `get_minimal_context` calls
- **Agent**: `backend-worker`
- **Task**: "Fix the IndexError in event_dispatcher.py line 42"
- **Expected**: `karios-vault critique --agent backend-worker --failed "skipped get_minimal_context"` called
- **Phase**: Unit test of `_check_code_review_graph_usage()`

### CRG TC-C-02: Agent-worker does NOT write critique for non-code task
- **Setup**: Mock Hermes session log with zero `get_minimal_context` calls
- **Agent**: `backend-worker`
- **Task**: "Write a research summary on VMware snapshot formats"
- **Expected**: No critique written (task does not touch code files)
- **Phase**: Unit test

### CRG TC-C-03: Agent-worker does NOT write critique for research agent
- **Setup**: Mock Hermes session log with zero `get_minimal_context` calls
- **Agent**: `architect` (not in code_profiles set)
- **Task**: "Research CloudStack API pagination"
- **Expected**: No critique written
- **Phase**: Unit test

### CRG TC-C-04: Dispatcher refuses CODING-COMPLETE when code_review_graph_calls=0
- **Setup**: Send `[CODING-COMPLETE]` from `backend` with `session_metadata.code_review_graph_calls = 0`
- **Expected**: Orchestrator does NOT call `handle_coding_complete()`. Instead sends `[CODING-RETRY]` back to backend
- **Phase**: Integration test

### CRG TC-C-05: Dispatcher accepts CODING-COMPLETE when code_review_graph_calls>0
- **Setup**: Send `[CODING-COMPLETE]` from `backend` with `session_metadata.code_review_graph_calls = 3`
- **Expected**: Orchestrator calls `handle_coding_complete()` normally
- **Phase**: Integration test

### CRG TC-C-06: Session metadata extraction counts get_minimal_context calls correctly
- **Setup**: Mock session log containing 5 `get_minimal_context` occurrences
- **Expected**: Extracted `code_review_graph_calls = 5`
- **Phase**: Unit test

---

## Item D: Gitea Push Verification Gate

### GitPush TC-D-01: verify_gitea_push returns True when all repos are pushed
- **Setup**: All gap repos are clean (no unpushed commits)
- **Command**: `git -C /root/karios-source-code/karios-migration rev-list --left-right --count origin/main...HEAD`
- **Expected**: `0\t0`
- **Result**: `verify_gitea_push()` returns `(True, "all repos up-to-date")`
- **Phase**: Unit test

### GitPush TC-D-02: verify_gitea_push returns False when ahead commits exist
- **Setup**: `karios-migration` has 3 commits unpushed
- **Command**: Returns `3\t0`
- **Expected**: `verify_gitea_push()` returns `(False, "karios-migration: 3 ahead, 0 behind origin")`
- **Phase**: Unit test

### GitPush TC-D-03: PROD-DEPLOYED refused when git not pushed
- **Setup**: BG-stub-no-op gap has unpushed commits in `karios-web`
- **Action**: DevOps emits `[PROD-DEPLOYED]`
- **Expected**: Orchestrator sends `[GITEA-PUSH-PENDING]` to devops. Phase 6 NOT entered. Telegram alert sent.
- **Phase**: Integration test

### GitPush TC-D-04: PROD-DEPLOYED accepted when git is pushed
- **Setup**: All gap repos are clean
- **Action**: DevOps emits `[PROD-DEPLOYED]`
- **Expected**: Orchestrator enters Phase 6 normally, `notify_phase_transition()` fires
- **Phase**: Integration test

### GitPush TC-D-05: Manifest.json read correctly for repo list
- **Setup**: `/var/lib/karios/iteration-tracker/BG-stub-no-op/manifest.json` contains `{"repos_touched":["karios-web","karios-migration"]}`
- **Expected**: `verify_gitea_push()` checks both repos
- **Phase**: Unit test

---

## Item E: Watchdog Kill-on-No-Tool-Call

### Watchdog TC-E-01: run_hermes_pty streams output incrementally
- **Setup**: Call `run_hermes_pty()` with a simple task
- **Expected**: `output_chunks` populated during execution (not all at end)
- **Phase**: Unit test

### Watchdog TC-E-02: Watchdog sends SIGTERM after >4000 tokens with zero tool_use
- **Setup**: Mock PTY that emits 5000 tokens of prose with no `tool_use` event
- **Expected**: `os.killpg()` called with SIGTERM
- **Phase**: Unit test (mock PTY)

### Watchdog TC-E-03: Watchdog does NOT fire when tool_use events detected
- **Setup**: Mock PTY emits 5000 tokens but includes `"tool_use"` in stream at token 2000
- **Expected**: No SIGTERM sent
- **Phase**: Unit test

### Watchdog TC-E-04: SIGTERM triggers retry with explicit prompt prepend
- **Setup**: Watchdog kills Hermes process
- **Expected**: Retry call made with query prefixed by `"BEGIN by calling karios-vault.search. Do not output prose first."`
- **Phase**: Integration test

### Watchdog TC-E-05: PTY fallback to subprocess.run on watchdog retry
- **Setup**: First PTY run killed by watchdog, retry also fails
- **Expected**: Second retry uses normal `subprocess.run` path (not PTY)
- **Phase**: Integration test

### Watchdog TC-E-06: Token count estimated correctly (words × 1.3)
- **Setup**: Mock PTY emits "hello world hello world" (4 words → ~5.2 tokens)
- **Expected**: `token_count` updated incrementally
- **Phase**: Unit test

---

## Item F: tool_choice Passthrough (Deferred — Documentation Tests Only)

### tool_choice TC-F-01: Profile config field documented
- **Expected**: `agent.anthropic.tool_choice: any` field documented in profile schema
- **Phase**: Documentation

### tool_choice TC-F-02: Provider adapter traced for OpenAI-compatible endpoints
- **Expected**: Call chain documented: `hermes chat --profile X` → provider adapter → `openai.ChatCompletion.create()`
- **Phase**: Documentation

---

## Regression Tests (Must Continue to Pass)

### Reg-01: v7.5 quarantine for bad JSON still works
- **Setup**: Send malformed JSON to orchestrator file inbox
- **Expected**: Moved to `/var/lib/karios/agent-msg/quarantine/`, not re-processed
- **Phase**: Regression

### Reg-02: `telegram_alert` retry + Markdown fallback still works
- **Setup**: Telegram API returns non-200 once, then 200
- **Expected**: Message delivered in plain text on retry
- **Phase**: Regression

### Reg-03: `_update_active_gap_state` wired correctly
- **Setup**: `[ARCH-REVIEWED]` received with rating ≥ 8
- **Expected**: `state.json` active_gaps[gap_id].phase updated to "phase-3-coding"
- **Phase**: Regression

### Reg-04: `_sanitize_gap_id` still handles 100-char gap IDs
- **Setup**: Send message with `gap_id` = 100-char string with em-dash at position 50
- **Expected**: Gap ID truncated/split to ≤80 chars
- **Phase**: Regression

### Reg-05: Subject aliases still work (9 aliases)
- **Setup**: Send `[DEPLOYED-PROD]`, `[DEPLOY-DONE]`, `[PRODUCTION-COMPLETE]` equivalent messages
- **Expected**: All map to `ProdDeployedBody` validation
- **Phase**: Regression

---

## Test Execution Plan

**Unit tests**: Run in orchestrator venv with `pytest message_schemas_test.py -v`
**Integration tests**: Run against LIVE v7.5 orchestrator with mock agents
**E2E self-test**: `karios-self-test` — full pipeline from requirement to monitoring
**Regression**: Run after each item implementation to confirm v7.5 features still work