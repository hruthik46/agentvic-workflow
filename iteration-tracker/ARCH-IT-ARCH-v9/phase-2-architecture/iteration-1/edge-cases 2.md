# Edge Cases — ARCH-IT-ARCH-v9 (iteration 1)

## Overview

This document catalogues every edge case discovered in META-LOOP iterations 1-3, categorized by the phase in which it occurs. For each edge case, we specify: trigger condition, expected behavior, recovery action, and whether it caused forging in previous iterations.

---

## Phase 1: Research Edge Cases

### EC-P1-01: Web Search Returns No Results
**Trigger**: Search query returns 0 results
**Expected**: Agent retries with 2 alternative queries, then escalates if still 0
**Recovery**: Escalate to Sai with `[ESCALATE] web_search_failed` message
**Caused forging**: No (escalation path existed)

### EC-P1-02: Infra Testing Blocked by Network
**Trigger**: SSH to ESXi host fails or CloudStack API unreachable
**Expected**: Log command attempt and output (even if failure), mark as "could not validate"
**Recovery**: Document what was attempted and what the error was. Continue if other infra tests succeed.
**Caused forging**: No (infra testing was advisory in v6-v8)

### EC-P1-03: Manual SSH Session Hangs
**Trigger**: SSH session to ESXi/CloudStack host hangs indefinitely
**Expected**: Timeout after 30s, log as "SSH hang — could not validate"
**Recovery**: Use alternative tool (govc for VMware, curl for CloudStack). If all tools fail, document failure.
**Caused forging**: No

---

## Phase 2: Architecture Edge Cases

### EC-P2-01: architecture.md Left as Placeholder
**Trigger**: Architect writes content to 4 docs but leaves architecture.md as "placeholder" (1KB)
**Root cause**: No size gate existed in v6-v8. Architect assumed "content is in the other docs" was acceptable.
**Expected**: HARD SIZE GATE — all 5 docs must be >= 2048 bytes. If any doc < 2048, orchestrator rejects [ARCH-COMPLETE].
**Recovery**: Architect receives rejection message with specific doc and byte count. Must expand doc before re-submitting.
**Caused forging**: YES (v6-v8 — architecture.md was placeholder, Phase 2 appeared complete)

### EC-P2-02: Blind-Tester Produces 414K Unstructured Output
**Trigger**: architect-blind-tester or code-blind-tester runs without output format constraint
**Root cause**: No STRICT OUTPUT CONTRACT in v6-v8. Tester produced verbose analysis, context exhausted before JSON.
**Expected**: STRICT OUTPUT CONTRACT — JSON FIRST in fenced ```json block, total < 30K chars.
**Recovery**: Orchestrator output parser rejects non-JSON. Score auto-set to 0/10. Tester must re-run with format constraint.
**Caused forging**: YES (blind-review appeared to pass in v6-v8 because no structured score was produced)

### EC-P2-03: Subject Format Drift
**Trigger**: Agent invents new subject format like [ARCHITECTURE-COMPLETE] or [BLIND-E2E-RESULTS]
**Root cause**: v7.3 added handler aliases but agents in v6-v8 used inconsistent formats
**Expected**: Orchestrator handler aliases accept both canonical and drift formats. Canonical: [ARCH-COMPLETE], [ARCH-REVIEWED], [E2E-RESULTS], [STAGING-DEPLOYED], [PROD-DEPLOYED]
**Recovery**: Orchestrator normalizes subject via aliases table. No forging risk, but logs deviation for metrics.
**Caused forging**: Indirect (caused confusion in tracking, led to missed phase transitions)

### EC-P2-04: Blind-Tester Score < 10/10 But Agent Didn't Fix
**Trigger**: architect-blind-tester returns 8/10 with issues list, but orchestrator did not route back to architect
**Root cause**: Handler for [ARCH-REVIEWED] existed but was not wired to retry loop in v6-v8
**Expected**: Score < 10 → architect receives issues → fixes → re-submits. Loop continues until 10/10 or max iterations.
**Recovery**: Re-wire [ARCH-REVIEWED] handler to route back to architect for fix iteration.
**Caused forging**: YES (score was < 10 but Phase 2 was marked complete anyway)

### EC-P2-05: Iteration Limit Reached (10 Iterations)
**Trigger**: Gap reaches iteration 10 without achieving 10/10 blind-review score
**Expected**: Orchestrator sends [ESCALATE] to Sai with full trace and all iteration artifacts
**Recovery**: Sai reviews manually and either closes gap as "won't fix" or provides specific guidance for fix
**Caused forging**: No (limit was enforced)

---

## Phase 3: Coding Edge Cases

### EC-P3-01: go build Fails Mid-Phase
**Trigger**: `go build ./...` returns non-zero exit code
**Expected**: Backend receives build failure. Files are still written to output directory but [CODING-COMPLETE] is NOT sent.
**Recovery**: Backend analyzes build errors, fixes code, re-runs build. Loop until build succeeds.
**Caused forging**: YES (v6-v8 — [CODING-COMPLETE] sent even when build failed, Phase 4 received broken code)

### EC-P3-02: Output File Corruption (output_type Field)
**Trigger**: Generated file has `output_type` = "ARCH-01" instead of "request"
**Root cause**: delegate_task sub-agent corruption — string replacement bug in output_verifier_v4.py
**Expected**: Phase 3 now validates all output files with output_verifier_v4.py before [CODING-COMPLETE]
**Recovery**: output_verifier finds corruption, backend re-generates files
**Caused forging**: YES (Phase 3 appeared complete but files were corrupted)

### EC-P3-03: KARIOS_A2A_TOKEN Corruption
**Trigger**: A2A protocol file has line 18 corrupted with partial token string
**Root cause**: String concatenation error in a2a_protocol.py generation
**Expected**: output_verifier checks for KARIOS_A2A_TOKEN = valid format (64 hex chars)
**Recovery**: Backend re-generates a2a_protocol.py
**Caused forging**: YES (Phase 3 output was corrupted)

### EC-P3-04: Stream Routing Confusion (stream:backend vs inbox:backend)
**Trigger**: Generated orchestrator sends to `stream:backend` but backend reads from `inbox:backend`
**Root cause**: Inconsistent stream naming convention in v6-v8
**Expected**: All stream routing now standardized. Backend reads from `inbox:backend`. Orchestrator writes to `stream:orchestrator` for dispatch.
**Recovery**: a2a_protocol.py updated to use consistent naming
**Caused forging**: Indirect (caused Phase 3 files to not integrate properly)

### EC-P3-05: No Output Files Generated
**Trigger**: Phase 3 completes but output directory is empty
**Expected**: Orchestrator detects 0 output files, rejects [CODING-COMPLETE]
**Recovery**: Backend must regenerate and produce at least 1 output file
**Caused forging**: No (detected in v6-v8)

### EC-P3-06: Python Syntax Error in Generated .py File
**Trigger**: `python -m py_compile` fails on a generated Python file
**Expected**: Build gate catches this. Backend must fix syntax before re-submitting.
**Recovery**: Backend re-generates file with correct syntax
**Caused forging**: No (caught by build gate)

---

## Phase 4: API-SYNC Edge Cases

### EC-P4-01: New API Not in Contract
**Trigger**: Backend implements an API endpoint that is not in api-contract.md
**Expected**: API-SYNC gate detects mismatch. Backend must add to api-contract.md before [CODING-COMPLETE] is accepted.
**Recovery**: Backend adds new API to api-contract.md in the same iteration
**Caused forging**: No (was caught in v6-v8)

### EC-P4-02: API in Contract But Not Implemented
**Trigger**: api-contract.md has an API entry, but no implementation exists in output files
**Expected**: API-SYNC gate detects missing implementation. Backend must implement or remove from contract.
**Recovery**: Backend implements missing API or removes from contract (depending on whether it's needed)
**Caused forging**: No

### EC-P4-03: API Contract Outdated (Endpoint URL Changed)
**Trigger**: Code uses `/api/v2/migrate` but contract says `/api/v1/migrate`
**Expected**: API-SYNC gate detects URL mismatch
**Recovery**: Backend updates contract to match code, or updates code to match contract
**Caused forging**: No

---

## Phase 5: Staging Deploy Edge Cases

### EC-P5-01: Staging Host Unreachable
**Trigger**: SSH to 192.168.118.105 fails or rsync fails
**Expected**: Deploy script fails, [STAGING-DEPLOYED] NOT sent
**Recovery**: DevOps agent receives failure, investigates connectivity, retries after fix
**Caused forging**: No (was detected in v6-v8)

### EC-P5-02: Deploy Script Fails Mid-Execution
**Trigger**: deploy.sh script runs but fails at some step (e.g., service restart fails)
**Expected**: Deploy script returns non-zero, [STAGING-DEPLOYED] NOT sent
**Recovery**: DevOps agent analyzes deploy log, fixes script or infrastructure issue
**Caused forging**: No

### EC-P5-03: Health Check Returns Non-200
**Trigger**: Service starts but /health endpoint returns 500 or timeout
**Expected**: Health check gate fails, [STAGING-DEPLOYED] NOT sent
**Recovery**: DevOps agent investigates service logs, fixes issue
**Caused forging**: No

### EC-P5-04: Build Succeeded But Deployment Failed
**Trigger**: go build succeeded, but deploy script or service start failed
**Expected**: Phase 5 fails. Backend must fix deploy issue.
**Recovery**: DevOps + Backend coordinate. Backend may need to fix build output or dependencies.
**Caused forging**: No (was detected in v6-v8)

---

## Phase 6: Telegram Notification Edge Cases

### EC-P6-01: Telegram Bot Token Invalid
**Trigger**: Telegram API returns 401 when sending notification
**Expected**: notify_phase_transition() logs error but does NOT block pipeline completion
**Recovery**: DevOps agent updates bot token. Notification retried on next phase transition.
**Caused forging**: No (Telegram is best-effort notification only)

### EC-P6-02: Telegram Chat ID Unknown
**Trigger**: notify_phase_transition() called with unknown chat_id
**Expected**: Log warning, skip notification, continue pipeline
**Recovery**: Sai must provide correct chat_id for future notifications
**Caused forging**: No

### EC-P6-03: Message Format Malformed
**Trigger**: notify_phase_transition() formats message with missing fields (e.g., None score)
**Expected**: Validation before send. If invalid format, log error and use fallback message.
**Recovery**: DevOps agent fixes message template
**Caused forging**: No

---

## Cross-Phase Edge Cases

### EC-XP-01: Context Window Exhausted Mid-Phase
**Trigger**: Agent reaches context limit before completing phase
**Expected**: Agent writes checkpoint, sends [ESCALATE], exits. Orchestrator resumes with same iteration.
**Recovery**: Orchestrator re-dispatches to same agent with context of what was completed
**Caused forging**: Indirect (caused blind-tester to produce 414K output without JSON)

### EC-XP-02: Redis Stream Message Lost
**Trigger**: XREADGROUP does not return expected message
**Expected**: Consumer re-claims after 30s health monitor sweep
**Recovery**: Nudge mechanism triggers re-dispatch
**Caused forging**: No

### EC-XP-03: Orchestrator Crash Mid-Phase
**Trigger**: Orchestrator process dies after Phase N completion but before Phase N+1 dispatch
**Expected**: Health monitor detects stalled gap after backoff timeout, re-dispatches
**Recovery**: Gap resumes at Phase N start (not mid-phase)
**Caused forging**: No (stalled detection existed)

### EC-XP-04: Agent Hermes Process Crashes
**Trigger**: Agent worker dies (OOM, segfault, etc.)
**Expected**: Orchestrator detects stalled (no heartbeat), re-dispatches to same gap
**Recovery**: Gap resumes at current phase start
**Caused forging**: No

### EC-XP-05: Phase Transition Message Sent But Not Processed
**Trigger**: Backend sends [CODING-COMPLETE] but orchestrator was restarting
**Expected**: Message is in Redis stream. Orchestrator resumes, processes message.
**Recovery**: Automatic (message durability in Redis streams)
**Caused forging**: No

---

## Recoverability Matrix

| Edge Case | Phase | Detectable By | Recovery Method | Auto-Retry? |
|-----------|-------|---------------|-----------------|-------------|
| EC-P2-01 architecture.md placeholder | 2 | Orchestrator size gate | Architect expands doc | No — requires human |
| EC-P2-02 blind-tester no JSON | 2 | Orchestrator output parser | Tester re-runs with format | No — requires human |
| EC-P2-04 score < 10 no fix | 2 | Orchestrator review handler | Route back to architect | YES |
| EC-P3-01 go build fails | 3 | Orchestrator build gate | Backend re-runs build | YES (3 attempts) |
| EC-P3-02 output_type corruption | 3 | output_verifier | Backend re-generates | YES |
| EC-P5-01 staging unreachable | 5 | Deploy script | DevOps fixes connectivity | No |
| EC-P5-03 health check fails | 5 | Health check gate | DevOps investigates | YES (3 attempts) |

---

## Trace ID

trace_ARCH-IT-ARCH-v9_v6_1776618349
