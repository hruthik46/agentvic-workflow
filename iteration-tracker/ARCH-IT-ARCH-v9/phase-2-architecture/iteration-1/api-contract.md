# API Contract — ARCH-IT-ARCH-v9 (iteration 1)

## Overview

This document defines the A2A protocol, Hermes event schemas, Redis stream channels, and Telegram notification formats for the Karios multi-agent pipeline v7.3+.

---

## 1. A2A Protocol (Agent-to-Agent)

### 1.1 Transport
- **Protocol**: HTTP/1.1 POST
- **A2A Server Port**: 8093 (separate from karios_core 8080 and karios_migration 8089)
- **Authentication**: KARIOS_A2A_TOKEN (64-char hex string, sha256 of shared secret)
- **Content-Type**: application/json

### 1.2 Endpoints

#### POST /api/v1/dispatch
Dispatch a task to an agent.

**Request**:
```json
{
  "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1",
  "agent": "architect",
  "intent": "Phase 2 architecture for gap ARCH-IT-ARCH-v9",
  "payload": {
    "gap_id": "ARCH-IT-ARCH-v9",
    "phase": "phase-2-arch-loop",
    "iteration": 1,
    "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
    "requirement_summary": "Self-validating pipeline + eliminate forging"
  },
  "a2a_token": "KARIOS_A2A_TOKEN"
}
```

**Response (200)**:
```json
{
  "status": "dispatched",
  "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1",
  "timestamp": "2026-04-19T17:30:00Z"
}
```

**Response (401)**: Invalid token
**Response (409)**: Task already dispatched

#### POST /api/v1/results
Submit task results from an agent.

**Request**:
```json
{
  "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1",
  "agent": "architect",
  "status": "success",
  "output_files": [
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-2-architecture/iteration-1/architecture.md"
  ],
  "message": "[ARCH-COMPLETE] ARCH-IT-ARCH-v9 iteration 1"
}
```

**Response (200)**:
```json
{
  "status": "received",
  "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1"
}
```

#### GET /api/v1/task/{task_id}
Poll task status.

**Response (200)**:
```json
{
  "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1",
  "status": "in_progress",
  "agent": "architect",
  "started_at": "2026-04-19T17:30:00Z"
}
```

#### POST /api/v1/cancel
Cancel a task.

**Request**:
```json
{
  "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1",
  "reason": "Gap closed by Sai"
}
```

---

## 2. Hermes Event Schemas

### 2.1 Phase Transition Events

All phase transitions publish to Redis stream `gap.phase_change`.

#### Event: phase_research_complete
```json
{
  "event_type": "phase_research_complete",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-1-research",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T17:30:00Z",
  "output_files": [
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-1-research/iteration-1/research.md"
  ],
  "metadata": {
    "doc_size_bytes": 4096,
    "web_search_urls": 3,
    "infra_tests_run": 2
  }
}
```

#### Event: phase_arch_complete
```json
{
  "event_type": "phase_arch_complete",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-2-arch-loop",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T18:00:00Z",
  "output_files": [
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-2-architecture/iteration-1/architecture.md",
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-2-architecture/iteration-1/edge-cases.md",
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-2-architecture/iteration-1/test-cases.md",
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-2-architecture/iteration-1/api-contract.md",
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-2-architecture/iteration-1/deployment-plan.md"
  ],
  "metadata": {
    "all_docs_size_verified": true,
    "blind_review_score": 10,
    "blind_review_json_chars": 8450
  }
}
```

#### Event: phase_arch_reviewed
```json
{
  "event_type": "phase_arch_reviewed",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-2-arch-loop",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T18:30:00Z",
  "reviewer": "architect-blind-tester",
  "score": 10,
  "issues": [],
  "review_json_chars": 8450,
  "review_json_fence": true
}
```

#### Event: phase_coding_complete
```json
{
  "event_type": "phase_coding_complete",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-3-coding",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T19:00:00Z",
  "output_files": [
    "/var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v9/phase-3-coding/iteration-1/feature_flag.go"
  ],
  "metadata": {
    "build_exit_code": 0,
    "build_output": "go build ./... succeeded",
    "output_verifier_passed": true,
    "num_files": 1
  }
}
```

#### Event: phase_api_sync_complete
```json
{
  "event_type": "phase_api_sync_complete",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-4-api-sync",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T19:30:00Z",
  "metadata": {
    "api_mismatches": 0,
    "new_apis_found": 0,
    "missing_implementations": 0
  }
}
```

#### Event: phase_staging_deploy_complete
```json
{
  "event_type": "phase_staging_deploy_complete",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-5-staging-deploy",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T20:00:00Z",
  "metadata": {
    "deploy_host": "192.168.118.105",
    "staging_path": "/var/lib/karios-migration/staging",
    "staging_tag": "arch-it-arch-v9-iter-1",
    "deploy_exit_code": 0,
    "health_check_status": 200,
    "health_check_url": "http://192.168.118.105:8089/health"
  }
}
```

#### Event: phase_complete
```json
{
  "event_type": "phase_complete",
  "gap_id": "ARCH-IT-ARCH-v9",
  "phase": "phase-6-complete",
  "iteration": 1,
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T20:30:00Z",
  "metadata": {
    "telegram_sent": true,
    "telegram_chat_id": 6817106382,
    "telegram_message_id": "123",
    "total_duration_seconds": 10800
  }
}
```

### 2.2 Gap State Change Events

#### Event: gap_created
```json
{
  "event_type": "gap_created",
  "gap_id": "ARCH-IT-ARCH-v9",
  "tier": "T1",
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T17:00:00Z",
  "meta": {
    "golden_tag": "karios-v6-iter-5-pre",
    "iter_n": 5
  }
}
```

#### Event: gap_completed
```json
{
  "event_type": "gap_completed",
  "gap_id": "ARCH-IT-ARCH-v9",
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T20:30:00Z",
  "result": "All 6 phases passed naturally"
}
```

#### Event: gap_escalated
```json
{
  "event_type": "gap_escalated",
  "gap_id": "ARCH-IT-ARCH-v9",
  "reason": "Max iterations (10) reached without 10/10 score",
  "trace_id": "trace_ARCH-IT-ARCH-v9_v6_1776618349",
  "timestamp": "2026-04-19T20:30:00Z",
  "last_phase": "phase-2-arch-loop",
  "last_iteration": 10,
  "last_score": 8
}
```

---

## 3. Redis Stream Channels

### 3.1 Stream Channels

| Channel | Producer | Consumer(s) | Purpose |
|---------|----------|-------------|---------|
| `stream:orchestrator` | Orchestrator | All agents | Main dispatch channel |
| `inbox:architect` | Orchestrator | Architect agent | Tasks for architect |
| `inbox:backend` | Orchestrator | Backend agent | Tasks for backend |
| `inbox:frontend` | Orchestrator | Frontend agent | Tasks for frontend |
| `inbox:devops` | Orchestrator | DevOps agent | Tasks for devops |
| `inbox:tester` | Orchestrator | Tester agent | Tasks for tester |
| `gap.phase_change` | All agents | Orchestrator | Phase transition notifications |
| `agent.stream` | All agents | Orchestrator | Real-time progress |

### 3.2 Consumer Groups

| Stream | Consumer Group | Purpose |
|--------|----------------|---------|
| `stream:orchestrator` | `og` | Orchestrator main queue |
| `inbox:{agent}` | `{agent}cg` | Per-agent work queue |

### 3.3 Message Format

All Redis stream messages use the same envelope:

```json
{
  "msg_id": "1234567890-0",
  "stream": "inbox:architect",
  "data": {
    "type": "dispatch",
    "task_id": "ARCH-IT-ARCH-v9-phase-2-iter-1",
    "gap_id": "ARCH-IT-ARCH-v9",
    "payload": { ... }
  }
}
```

---

## 4. Telegram Notification Format

### 4.1 Bot Configuration
- **Bot**: @Migrator_hermes_bot
- **Token**: <REDACTED-TELEGRAM-BOT-TOKEN>
- **Chat ID**: 6817106382 (Sai Hruthik)

### 4.2 Phase Transition Message Template

```
[PIPELINE] {gap_id} — Phase {N} {phase_name}

Status: {status_emoji} {status_text}
Trace: {trace_id}
Time: {timestamp}

Details:
  - Doc size: {doc_size}B ✓
  - Blind review: {score}/10 ✓
  - Build: {build_status} ✓
  - Deploy: {deploy_status} ✓

Next: {next_phase} → {next_agent}
Duration: {duration_seconds}s
```

### 4.3 Completion Message Template

```
[PIPELINE COMPLETE] {gap_id}

Phase 1: Research ✓ ({research_size}B)
Phase 2: Architecture ✓ ({arch_score}/10)
Phase 3: Coding ✓ ({num_files} files, build {build_status})
Phase 4: API-SYNC ✓ ({api_sync_status})
Phase 5: Staging Deploy ✓ ({deploy_status})
Phase 6: Telegram ✓

Trace: {trace_id}
Total Duration: {total_duration_seconds}s
Status: {final_status}
```

### 4.4 Error Message Template

```
[PIPELINE ERROR] {gap_id} — Phase {N}

Error: {error_summary}
Trace: {trace_id}
Time: {timestamp}

Details:
  - Failed at: {failed_at}
  - Error message: {error_message}
  - Retry count: {retry_count}

Action: {suggested_action}
```

---

## 5. Orchestrator Command Handlers

### 5.1 Subject Format Handlers (v7.3+)

| Subject Pattern | Handler | Notes |
|----------------|---------|-------|
| `[RESEARCH-COMPLETE]` | handle_research_complete | Canonical |
| `[ARCH-COMPLETE]` | handle_arch_complete | Canonical |
| `[ARCHITECTURE-COMPLETE]` | handle_arch_complete | Alias for v6-v8 drift |
| `[ARCH-REVIEWED]` | handle_arch_reviewed | Canonical |
| `[CODING-COMPLETE]` | handle_coding_complete | Canonical |
| `[API-SYNC]` | handle_api_sync | Canonical |
| `[API-SYNC-COMPLETE]` | handle_api_sync | Alias |
| `[STAGING-DEPLOYED]` | handle_staging_deploy | Canonical |
| `[DEPLOYED]` | handle_staging_deploy | Alias |
| `[E2E-RESULTS]` | handle_e2e_results | Canonical |
| `[BLIND-E2E-RESULTS]` | handle_e2e_results | Alias for v6-v8 drift |
| `[PROD-DEPLOYED]` | handle_prod_deploy | Canonical |
| `[COMPLETE]` | handle_gap_complete | Canonical |
| `[ESCALATE]` | handle_escalate | Canonical |
| `[STALLED]` | handle_stalled | Auto-detect |

### 5.2 Precondition Gates (enforced BEFORE accepting message)

| Phase | Gate | Check |
|-------|------|-------|
| Phase 1 | SIZE | research.md >= 512 bytes |
| Phase 2 | SIZE | All 5 docs >= 2048 bytes |
| Phase 2 | REVIEW | blind-review JSON valid, score >= 10 |
| Phase 3 | BUILD | go build ./... exit code = 0 |
| Phase 3 | VERIFY | output_verifier passes all checks |
| Phase 4 | API_SYNC | No API mismatches |
| Phase 5 | DEPLOY | deploy.sh exit code = 0 |
| Phase 5 | HEALTH | /health returns 200 |

---

## Trace ID

trace_ARCH-IT-ARCH-v9_v6_1776618349

