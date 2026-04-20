# Test Cases — ARCH-IT-ARCH-v9 (iteration 1)

## Overview

This document contains test cases for the self-validating pipeline designed in architecture.md. Test cases are organized into 5 categories:
1. **Self-Validating Pipeline Tests** — BG-stub-feature-no-op through all 6 phases
2. **Regression Tests** — Each fix applied in v7.3
3. **Edge Case Tests** — Phase failure scenarios from edge-cases.md
4. **Cross-Phase Integration Tests** — Multi-phase scenarios
5. **Output Contract Tests** — Blind-tester format validation

---

## Category 1: Self-Validating Pipeline Tests

### TC-SVP-01: BG-stub-feature-no-op Phase 1 (Research)
**Gap**: BG-stub-feature-no-op
**Phase**: 1
**Prerequisites**: None
**Steps**:
1. Dispatch BG-stub-feature-no-op to architect agent
2. Architect performs web search for "feature flag golang" (minimum 3 results)
3. Architect tests against existing CloudStack API (curl, no code)
4. Architect writes research.md >= 512 bytes
**Expected Result**: [RESEARCH-COMPLETE] sent, research.md has web search evidence + infra test evidence
**Pass Criteria**: research.md >= 512 bytes, >= 3 URLs cited, >= 2 infra test commands with output
**Auto-Pass**: NO (requires Orchestrator size validation)

### TC-SVP-02: BG-stub-feature-no-op Phase 2 (Architecture)
**Gap**: BG-stub-feature-no-op
**Phase**: 2
**Prerequisites**: TC-SVP-01 passed
**Steps**:
1. Architect writes all 5 docs (architecture.md, edge-cases.md, test-cases.md, api-contract.md, deployment-plan.md)
2. Each doc must be >= 2048 bytes
3. Orchestrator validates all 5 doc sizes before accepting [ARCH-COMPLETE]
4. Dispatch to architect-blind-tester
5. Blind-tester produces JSON score under 30K chars
**Expected Result**: [ARCH-COMPLETE] sent, blind-review score >= 10/10
**Pass Criteria**: All 5 docs >= 2048 bytes, blind-review JSON produced, score >= 10/10
**Auto-Pass**: NO (requires blind-review score)

### TC-SVP-03: BG-stub-feature-no-op Phase 3 (Coding)
**Gap**: BG-stub-feature-no-op
**Phase**: 3
**Prerequisites**: TC-SVP-02 passed with 10/10
**Steps**:
1. Backend generates feature_flag.go with no-op implementation
2. go build ./... succeeds
3. output_verifier validates no corruption markers
4. No output_type field corruption
5. No KARIOS_A2A_TOKEN corruption
**Expected Result**: [CODING-COMPLETE] sent
**Pass Criteria**: go build exit code 0, no corruption markers, output_verifier passes
**Auto-Pass**: YES (orchestrator build gate)

### TC-SVP-04: BG-stub-feature-no-op Phase 4 (API-SYNC)
**Gap**: BG-stub-feature-no-op
**Phase**: 4
**Prerequisites**: TC-SVP-03 passed
**Steps**:
1. API contract updated with new feature flag endpoint (if any)
2. Orchestrator validates all APIs in code are in contract
3. All APIs in contract that are relevant have implementation
**Expected Result**: [API-SYNC] sent
**Pass Criteria**: No mismatches between api-contract.md and implementation
**Auto-Pass**: YES (orchestrator API-SYNC gate)

### TC-SVP-05: BG-stub-feature-no-op Phase 5 (Staging Deploy)
**Gap**: BG-stub-feature-no-op
**Phase**: 5
**Prerequisites**: TC-SVP-04 passed
**Steps**:
1. DevOps runs deploy-all.sh to 192.168.118.105:/var/lib/karios-migration/staging
2. deploy.sh executes successfully
3. Service /health returns 200 OK
**Expected Result**: [STAGING-DEPLOYED] sent with Telegram notification
**Pass Criteria**: deploy exit code 0, health check 200
**Auto-Pass**: YES (orchestrator deploy gate + health check)

### TC-SVP-06: BG-stub-feature-no-op Phase 6 (Completion)
**Gap**: BG-stub-feature-no-op
**Phase**: 6
**Prerequisites**: TC-SVP-05 passed
**Steps**:
1. Orchestrator formats complete pipeline summary message
2. notify_phase_transition sends Telegram to @Migrator_hermes_bot chat_id 6817106382
3. Message contains all 6 phase statuses
**Expected Result**: Telegram message sent successfully
**Pass Criteria**: Telegram API returns 200
**Auto-Pass**: NO (Telegram is best-effort; pipeline continues even if Telegram fails)

---

## Category 2: Regression Tests

### TC-REG-01: architecture.md Size Gate
**Gap**: Any T1 gap
**Phase**: 2
**Prerequisites**: Architect has 5 docs ready
**Steps**:
1. Architect submits with architecture.md = 1024 bytes (placeholder)
2. Orchestrator checks all 5 doc sizes
**Expected Result**: Orchestrator REJECTS [ARCH-COMPLETE], sends rejection message specifying architecture.md is only 1024 bytes
**Regression For**: v6-v8 where architecture.md could be placeholder

### TC-REG-02: Blind-Tester JSON Output < 30K
**Gap**: Any T1 gap
**Phase**: 2
**Prerequisites**: architect-blind-tester dispatched
**Steps**:
1. Blind-tester produces output that is NOT in JSON fenced block
2. OR output is JSON but > 30K chars
**Expected Result**: Orchestrator output parser rejects, score auto-set to 0/10
**Regression For**: v6-v8 where blind-tester produced 414K unstructured output

### TC-REG-03: go build Gate in Phase 3
**Gap**: Any T1 gap with Go code
**Phase**: 3
**Prerequisites**: Backend generated Go files
**Steps**:
1. Backend sends [CODING-COMPLETE]
2. Orchestrator runs `go build ./...`
3. Build fails (exit code != 0)
**Expected Result**: Orchestrator rejects [CODING-COMPLETE], does not dispatch to Phase 4
**Regression For**: v6-v8 where build failures were not checked before Phase 4

### TC-REG-04: output_verifier Checks All Files
**Gap**: Any T1 gap
**Phase**: 3
**Prerequisites**: Backend generated files
**Steps**:
1. One of the generated files has `output_type = "ARCH-01"` (corruption)
2. Backend sends [CODING-COMPLETE]
**Expected Result**: output_verifier detects corruption, orchestrator rejects [CODING-COMPLETE]
**Regression For**: v6-v8 where output_type corruption was not caught

### TC-REG-05: API Contract Precondition
**Gap**: Any T1 gap
**Phase**: 3
**Prerequisites**: Backend generated files with API endpoints
**Steps**:
1. Backend implements `/api/v2/new-feature` but does NOT add to api-contract.md
2. Backend sends [CODING-COMPLETE]
**Expected Result**: Phase 4 API-SYNC gate catches mismatch, backend must add to contract first
**Regression For**: v6-v8 where API contract was not enforced as precondition

---

## Category 3: Edge Case Tests

### TC-EC-01: Phase 2 Architecture Fails Size Gate
**Trigger**: EC-P2-01 (architecture.md placeholder)
**Gap**: Any T1 gap
**Phase**: 2
**Steps**:
1. Architect submits with architecture.md < 2048 bytes
2. Orchestrator sends rejection: "architecture.md is {X} bytes, need >= 2048"
3. Architect expands doc to >= 2048 bytes
4. Architect re-submits
**Expected Result**: Second submission passes size gate
**Pass Criteria**: Re-submission passes without manual intervention from Sai

### TC-EC-02: Blind-Tester No JSON — Auto Reject
**Trigger**: EC-P2-02 (no JSON fence)
**Gap**: Any T1 gap
**Phase**: 2
**Steps**:
1. architect-blind-tester dispatched
2. Produces output without ```json fence
3. Orchestrator output parser rejects
**Expected Result**: Score auto 0/10, [ARCH-REVIEWED] sent with issues
**Pass Criteria**: Orchestrator rejects without manual intervention

### TC-EC-03: Build Fails — Backend Must Retry
**Trigger**: EC-P3-01 (go build fails)
**Gap**: BG-stub-feature-no-op
**Phase**: 3
**Steps**:
1. Backend sends [CODING-COMPLETE]
2. Orchestrator runs `go build ./...`
3. Build fails with compilation error
4. Orchestrator sends rejection with build error
5. Backend fixes error
6. Backend re-sends [CODING-COMPLETE]
**Expected Result**: Second attempt succeeds
**Pass Criteria**: Re-submission succeeds within 3 attempts

### TC-EC-04: Staging Deploy Fails Health Check
**Trigger**: EC-P5-03 (health check non-200)
**Gap**: BG-stub-feature-no-op
**Phase**: 5
**Steps**:
1. Deploy script succeeds
2. Service starts but /health returns 500
3. Orchestrator sends [DEPLOY-FAILED] to DevOps
4. DevOps fixes service issue
5. DevOps re-runs health check
**Expected Result**: Health check passes within 3 attempts
**Pass Criteria**: Service returns 200 within 3 retry attempts

### TC-EC-05: Telegram Fails But Pipeline Continues
**Trigger**: EC-P6-01 (Telegram bot token invalid)
**Gap**: BG-stub-feature-no-op
**Phase**: 6
**Steps**:
1. All 5 previous phases pass
2. notify_phase_transition called with invalid bot token
3. Telegram API returns 401
4. Orchestrator logs error but marks gap as complete
**Expected Result**: Gap marked COMPLETED in state.json, Telegram error logged
**Pass Criteria**: Gap is complete, Telegram error does not block state update

---

## Category 4: Cross-Phase Integration Tests

### TC-XP-01: Complete Happy Path (BG-stub-feature-no-op)
**Gap**: BG-stub-feature-no-op
**Phases**: 1-6
**Steps**: All 6 phase test cases in sequence
**Expected Result**: All phases pass naturally without any forging or manual intervention
**Pass Criteria**: Gap marked COMPLETED in state.json, Telegram message sent, all gates passed

### TC-XP-02: Phase 2 Iteration Loop (Score < 10 → Fix → 10)
**Gap**: Any T1 gap
**Phases**: 2 → 2 → 2 (iteration loop)
**Steps**:
1. First blind-review: score = 8/10 with 3 issues
2. Orchestrator routes issues to architect
3. Architect fixes all 3 issues
4. Second blind-review: score = 10/10
**Expected Result**: Phase 2 completes after 2 iterations
**Pass Criteria**: Second review achieves 10/10

### TC-XP-03: Phase 3 Iteration Loop (Build Fail → Fix → Pass)
**Gap**: Any T1 gap with Go code
**Phases**: 3 → 3 → 3 (iteration loop)
**Steps**:
1. First [CODING-COMPLETE]: go build fails
2. Orchestrator rejects, routes to backend
3. Backend fixes compilation error
4. Second [CODING-COMPLETE]: go build succeeds
**Expected Result**: Phase 3 completes after 2 iterations
**Pass Criteria**: Second build succeeds

### TC-XP-04: Phase 5 Iteration Loop (Deploy Fail → Fix → Pass)
**Gap**: Any T1 gap
**Phases**: 5 → 5 → 5 (iteration loop)
**Steps**:
1. First deploy: staging host unreachable
2. DevOps fixes connectivity
3. Second deploy: deploy.sh succeeds but health check 500
4. DevOps fixes service
5. Third deploy: health check 200
**Expected Result**: Phase 5 completes after 3 iterations
**Pass Criteria**: Third deploy succeeds

---

## Category 5: Output Contract Tests

### TC-OC-01: JSON Fence Required
**Agent**: architect-blind-tester
**Output**: Plain text without JSON fence
**Expected**: Orchestrator output parser rejects, score = 0/10
**Pass Criteria**: Rejection within 5 seconds of output receipt

### TC-OC-02: JSON > 30K Rejected
**Agent**: architect-blind-tester
**Output**: Valid JSON in fence but total chars > 30000
**Expected**: Orchestrator output parser rejects, score = 0/10
**Pass Criteria**: Rejection within 5 seconds of output receipt

### TC-OC-03: Valid JSON < 30K Accepted
**Agent**: architect-blind-tester
**Output**: Valid JSON in fence, total chars = 15000
**Expected**: Orchestrator accepts JSON, score = extracted from JSON
**Pass Criteria**: Score extracted and sent in [ARCH-REVIEWED] within 5 seconds

### TC-OC-04: JSON Missing Required Fields
**Agent**: architect-blind-tester
**Output**: Valid JSON but missing "score" field
**Expected**: Orchestrator treats as invalid, score = 0/10
**Pass Criteria**: Rejection with "missing required field: score"

---

## Test Execution Order

For BG-stub-feature-no-op self-validation:

```
Week 1:
  TC-SVP-01 (Research)
  TC-SVP-02 (Architecture)
  TC-REG-01 (architecture.md size gate)
  TC-REG-02 (blind-tester JSON output)
  
Week 2:
  TC-SVP-03 (Coding)
  TC-REG-03 (go build gate)
  TC-REG-04 (output_verifier)
  TC-EC-03 (build fail → retry)
  
Week 3:
  TC-SVP-04 (API-SYNC)
  TC-REG-05 (API contract precondition)
  
Week 4:
  TC-SVP-05 (Staging Deploy)
  TC-EC-04 (health check fail → retry)
  TC-SVP-06 (Telegram completion)
  TC-EC-05 (Telegram fail but continue)
  
Week 5:
  TC-XP-01 (complete happy path)
  TC-XP-02 (phase 2 iteration loop)
  TC-XP-03 (phase 3 iteration loop)
  TC-XP-04 (phase 5 iteration loop)
  
Week 6:
  TC-OC-01 (JSON fence required)
  TC-OC-02 (JSON > 30K rejected)
  TC-OC-03 (valid JSON accepted)
  TC-OC-04 (JSON missing fields)
```

---

## Trace ID

trace_ARCH-IT-ARCH-v9_v6_1776618349
