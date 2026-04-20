# Test Cases — ARCH-IT-ARCH-v10 (iteration 1)

## Overview

52 test cases across 7 categories:
- Tool-Use Enforcement (A): 8 tests
- JSON Schema Validation (B): 9 tests
- Self-Test BG-stub-no-op (C): 8 tests
- code-review-graph Rubric (D): 6 tests
- Gitea Push Verification (E): 6 tests
- Telegram Filter (F): 5 tests
- Integration + Regression: 10 tests

---

## A. Tool-Use Enforcement Tests

### ATC-01: Watchdog Kills Hermes After 30K Tokens With No Tool Call
**Setup**: Mock Hermes subprocess that prints 35,000 tokens of prose and exits without any tool calls.
**Action**: `run_hermes()` with mocked subprocess.
**Expected**: SIGKILL sent to process group. Return includes "WATCHDOG_KILL". Token count = 35,000.
**Pass Criteria**: Hermes process is dead. Output indicates watchdog triggered.

### ATC-02: Watchdog Allows Normal Tool-Using Session
**Setup**: Mock Hermes subprocess that calls `read_file` within first 1,000 tokens, then completes.
**Action**: `run_hermes()` with mocked subprocess.
**Expected**: Subprocess completes normally. Return includes tool call output. No watchdog kill.
**Pass Criteria**: No SIGKILL. Normal completion.

### ATC-03: Watchdog Resets Token Counter After Tool Call
**Setup**: Mock Hermes: token 1–1000 (tool call), token 1001–31000 (prose), token 31001–35000 (tool call).
**Action**: `run_hermes()` with mocked subprocess.
**Expected**: No watchdog kill (counter reset at token 1000, only 30K prose after last tool).
**Pass Criteria**: Normal completion.

### ATC-04: Watchdog Pattern Detection Covers All Known Tool Formats
**Setup**: Mock Hermes outputs various tool-call formats: `{"tool":"terminal"}`, `Function call read_file`, `mcp__code-review-graph__query_graph`.
**Action**: Each format passed individually.
**Expected**: All formats recognized. Watchdog allows.
**Pass Criteria**: All formats detected = tool_called[0] = True.

### ATC-05: Hard 10-Minute Timeout Prevents Infinite Loop
**Setup**: Mock Hermes that runs forever printing "thinking..." without tool calls.
**Action**: `run_hermes()` with mocked subprocess.
**Expected**: Process killed after 600 seconds (WATCHDOG_TIMEOUT_SEC). Returns "TIMEOUT_OR_WATCHDOG_KILL".
**Pass Criteria**: Process dead within 620 seconds of start.

### ATC-06: tool_use_enforcement: strict Forces Tool Call
**Setup**: Hermes config with `tool_use_enforcement: strict`. Task: "Write nothing, just respond."
**Action**: `hermes chat --query "Write nothing" --profile architect --toolsets terminal,file`
**Expected**: Hermes produces error or refuses: "No tool available" or similar. Or uses a tool immediately.
**Pass Criteria**: First non-empty response contains a tool call or explicit refusal.

### ATC-07: Prompt Template Injection Works
**Setup**: `run_hermes()` builds query with the mandatory sequence injected.
**Action**: `run_hermes()` with task that doesn't require tools.
**Expected**: Query string contains "FIRST call `karios-vault search"".
**Pass Criteria**: Query variable contains the injected text.

### ATC-08: Watchdog With Temp File Pipe (Memory Efficiency)
**Setup**: Large output (>50MB) streamed to temp file instead of memory.
**Action**: `run_hermes()` with mocked large output.
**Expected**: Memory usage stable. Output saved to temp file. Watchdog still works.
**Pass Criteria**: No OOM. Output is retrievable.

---

## B. JSON Schema Validation Tests

### BTC-01: Valid ARCH-COMPLETE Body Passes Validation
**Setup**: `ArchCompleteBody` with all 5 docs >= 2048 bytes, files_changed includes all required files.
**Action**: `ArchCompleteBody.model_validate(json_body)`
**Expected**: No exception. Validated model returned.
**Pass Criteria**: Validation succeeds.

### BTC-02: ARCH-COMPLETE With Doc < 2048 Bytes Fails
**Setup**: `ArchCompleteBody` with `architecture.md` = 1024 bytes.
**Action**: `ArchCompleteBody.model_validate(json_body)`
**Expected**: `ValidationError` with message mentioning "architecture.md" and "2048".
**Pass Criteria**: Exception raised. Error message is descriptive.

### BTC-03: ARCH-COMPLETE Missing a Required Doc Fails
**Setup**: `ArchCompleteBody` missing `edge-cases.md`.
**Action**: `ArchCompleteBody.model_validate(json_body)`
**Expected**: `ValidationError` mentioning "edge-cases.md".
**Pass Criteria**: Exception raised.

### BTC-04: ARCH-REVIEWED Rating Out of Range Fails
**Setup**: `ArchReviewedBody` with `rating: 11`.
**Action**: `ArchReviewedBody.model_validate(json_body)`
**Expected**: `ValidationError` with "rating" constraint.
**Pass Criteria**: Exception raised.

### BTC-05: Malformed JSON Triggers SCHEMA-REJECTED
**Setup**: `parse_message` receives body with `{invalid json}`.
**Action**: `parse_message(msg_id, data)`
**Expected**: `None` returned. `[SCHEMA-REJECTED]` sent to sender.
**Pass Criteria**: No crash. Rejection message sent with reason.

### BTC-06: Extra Fields Accepted (Extra='ignore')
**Setup**: `ArchCompleteBody` with extra field `experimental_flag: true`.
**Action**: `ArchCompleteBody.model_validate(json_body)`
**Expected**: No exception (extra fields ignored).
**Pass Criteria**: Validation succeeds despite extra fields.

### BTC-07: parse_message Falls Back to Unvalidated on Exception
**Setup**: Pydantic throws unexpected exception (not ValidationError).
**Action**: `parse_message(msg_id, data)` with corrupt schema class.
**Expected**: Exception caught, fallback to v7.3 unvalidated dispatch.
**Pass Criteria**: Dispatcher continues. Exception logged. No crash.

### BTC-08: E2E-RESULTS With Invalid Criteria Scores Fails
**Setup**: `E2EResultsBody` with `criteria_scores` containing non-int values.
**Action**: `E2EResultsBody.model_validate(json_body)`
**Expected**: `ValidationError`.
**Pass Criteria**: Exception raised with descriptive message.

### BTC-09: CodingComplete Without build_passed Fails
**Setup**: `CodingCompleteBody` missing required `build_passed` field.
**Action**: `CodingCompleteBody.model_validate(json_body)`
**Expected**: `ValidationError` mentioning "build_passed".
**Pass Criteria**: Exception raised.

---

## C. Self-Test BG-stub-no-op Tests

### CTC-01: BG-stub-no-op Triggers From SELF-TEST Message
**Setup**: Orchestrator idle. Send `[SELF-TEST]` to orchestrator.
**Action**: `parse_message` + handler dispatch.
**Expected**: `dispatch_research("BG-stub-no-op", ...)` called. Phase 1 begins.
**Pass Criteria**: Research dispatched. Gap state updated.

### CTC-02: BG-stub-no-op Phase 1 Research Produces 512+ Byte Doc
**Setup**: Architect Phase 1 for BG-stub-no-op completes.
**Action**: Manual check of `phase-1-research/iteration-1/research.md` size.
**Expected**: File exists, >= 512 bytes, contains >= 3 web search URLs.
**Pass Criteria**: Size and URL count verified.

### CTC-03: BG-stub-no-op Phase 2 All 5 Docs >= 2048 Bytes
**Setup**: Architect Phase 2 for BG-stub-no-op completes.
**Action**: `stat` on each of the 5 docs.
**Expected**: All 5 docs >= 2048 bytes.
**Pass Criteria**: All sizes >= 2048.

### CTC-04: BG-stub-no-op Phase 2 Blind-Tester Scores 10/10
**Setup**: Architect-blind-tester reviews BG-stub-no-op Phase 2.
**Action**: Parse JSON output of blind-tester.
**Expected**: `rating >= 10`, `recommendation == "APPROVE"`.
**Pass Criteria**: Score 10/10.

### CTC-05: BG-stub-no-op Phase 3 Code Compiles
**Setup**: Backend implements BG-stub-no-op minimal Go file.
**Action**: `cd /root/karios-source-code/karios-migration && go build ./...`
**Expected**: Exit code 0.
**Pass Criteria**: Build succeeds.

### CTC-06: BG-stub-no-op Phase 4 API Contract + Smoke Test
**Setup**: BG-stub-no-op Go file includes `/health` endpoint.
**Action**: `curl -s http://localhost:8089/health`
**Expected**: HTTP 200, body contains expected health response.
**Pass Criteria**: 200 OK.

### CTC-07: BG-stub-no-op Phase 5 Staging Deploy
**Setup**: DevOps deploys BG-stub-no-op to staging.
**Action**: Health check on staging endpoint.
**Expected**: HTTP 200.
**Pass Criteria**: Staging healthy.

### CTC-08: BG-stub-no-op Phase 6 Telegram Sent
**Setup**: Monitor Phase 6 completes for BG-stub-no-op.
**Action**: Check Telegram `getUpdates` for pipeline message.
**Expected**: Message sent to chat_id with `notify_phase_transition` content.
**Pass Criteria**: Message found in Telegram.

---

## D. code-review-graph Rubric Tests

### DTC-01: get_minimal_context Tracked in Audit Stream
**Setup**: Hermes session with `get_minimal_context` call.
**Action**: After `run_hermes()` completes, check `stream:graph-audit`.
**Expected**: Entry exists with `code_review_graph_used: true`.
**Pass Criteria**: Audit entry found.

### DTC-02: No get_minimal_context Tracked as False
**Setup**: Hermes session without `get_minimal_context`.
**Action**: After `run_hermes()` completes, check `stream:graph-audit`.
**Expected**: Entry with `code_review_graph_used: false`.
**Pass Criteria**: Audit entry found with false.

### DTC-03: Phase 3 Gate Fails Without Graph Usage
**Setup**: Backend dispatched to Phase 3 without any prior graph usage.
**Action**: `check_graph_rubric("BG-01", "backend")` called.
**Expected**: Returns `False`. Phase 3 gate logs warning.
**Pass Criteria**: Warning logged, gap state marked.

### DTC-04: Phase 3 Gate Passes With Graph Usage
**Setup**: Backend dispatched to Phase 3 with prior `get_minimal_context` call.
**Action**: `check_graph_rubric("BG-01", "backend")` called.
**Expected**: Returns `True`.
**Pass Criteria**: True returned.

### DTC-05: Phase 1 Architect Exempt From Graph Rubric
**Setup**: Architect dispatched to Phase 1 (research).
**Action**: `check_graph_rubric("BG-01", "architect")` during Phase 1.
**Expected**: Returns `True` (exempt) or skipped.
**Pass Criteria**: No false failure for Phase 1.

### DTC-06: MCP Server Logs Graph Invocations
**Setup**: Direct test of `code-review-graph get_minimal_context`.
**Action**: `uvx code-review-graph get_minimal_context task="bg01 cpu morphing"`
**Expected**: Tool returns context and logs to audit stream.
**Pass Criteria**: Audit entry written.

---

## E. Gitea Push Verification Tests

### ETC-01: Push Verification Passes When Fully Synced
**Setup**: Local HEAD = origin/main. No divergence.
**Action**: `verify_gitea_push("karios-migration")`
**Expected**: Returns `True`.
**Pass Criteria**: True.

### ETC-02: Push Verification Fails When Ahead
**Setup**: Local has unpushed commit.
**Action**: `verify_gitea_push("karios-migration")` with unpushed commits.
**Expected**: Returns `False`. `[PUSH-REQUIRED]` sent to devops.
**Pass Criteria**: False returned. Message sent.

### ETC-03: Push Verification Fails When Behind
**Setup**: origin/main has been force-updated.
**Action**: `verify_gitea_push("karios-migration")` with divergence.
**Expected**: Returns `False`.
**Pass Criteria**: False.

### ETC-04: PROD-DEPLOYED Blocked Until Push
**Setup**: Unpushed commits. DevOps sends `[PROD-DEPLOYED]`.
**Action**: `handle_prod_deployed` calls `verify_gitea_push`.
**Expected**: `[PUSH-REQUIRED]` sent. `[MONITORING-COMPLETE]` NOT sent.
**Pass Criteria**: Phase 6 blocked.

### ETC-05: Timeout on Gitea Network Failure
**Setup**: Gitea unreachable. `git rev-list` times out.
**Action**: `verify_gitea_push` with network timeout.
**Expected**: Returns `False` after 30s. Warning logged. PROD-DEPLOYED allowed with note.
**Pass Criteria**: Timeout handled gracefully.

### ETC-06: Multiple Repos Verified
**Setup**: Gap modified both `karios-migration` and `karios-web`.
**Action**: Verify both after deploy.
**Expected**: Both verified. If one fails, `[PUSH-REQUIRED]` lists the failed repo.
**Pass Criteria**: Both checked. Failure identifies specific repo.

---

## F. Telegram Filter Tests

### FTC-01: Pipeline Message Passes Filter
**Setup**: Message with `callback_data: "karios_auto:phase_complete"` from pipeline.
**Action**: `is_pipeline_origin(update)`
**Expected**: Returns `True`.
**Pass Criteria**: True.

### FTC-02: Human /start Command Gets Auto-Reply
**Setup**: Human sends `/start` to bot.
**Action**: `is_pipeline_origin(update)` for `/start` message.
**Expected**: Returns `False`. Auto-reply sent: "Pipeline-controlled bot".
**Pass Criteria**: Auto-reply sent.

### FTC-03: /emergency Command Available
**Setup**: Human sends `/emergency-unblock BG-01`.
**Action**: Bot handles `/emergency-unblock`.
**Expected**: Direct Redis command executed. Sai notified.
**Pass Criteria**: Gap unblocked. Action logged to vault.

### FTC-04: Telegram 401 Token Revoked Triggers Alert
**Setup**: `notify_phase_transition` calls Telegram API with revoked token.
**Action**: API returns 401.
**Expected**: Redis alert on `channel:alerts`. Failure logged to vault.
**Pass Criteria**: Alert fired. Logging complete.

### FTC-05: Telegram Rate Limit 429 Triggers Retry
**Setup**: `notify_phase_transition` hits rate limit.
**Action**: API returns 429.
**Expected**: Exponential backoff retry (max 3). If all fail, log and continue.
**Pass Criteria**: Retry happens. No hang.

---

## G. Integration and Regression Tests

### GTC-01: Full BG-stub-no-op Pipeline Run
**Setup**: Trigger `[SELF-TEST]`. Run pipeline without intervention.
**Action**: Wait for all 6 phases to complete.
**Expected**: Phase 6 `[MONITORING-COMPLETE]` received. All 6 phase gates passed.
**Pass Criteria**: Complete end-to-end run.

### GTC-02: v7.4 Real Gap Still Works After v10 Deploy
**Setup**: Real gap (e.g., BG-01) in Phase 3 during v10 deployment.
**Action**: Deploy v10 components. Monitor BG-01 progress.
**Expected**: BG-01 completes without degradation.
**Pass Criteria**: BG-01 rating >= 8.

### GTC-03: Orchestrator Does Not Crash on Malformed Message
**Setup**: Send malformed message (missing `subject`, missing `body`) to orchestrator.
**Action**: `parse_message` handles it.
**Expected**: No crash. Defensive KeyError handling. Message dropped.
**Pass Criteria**: Orchestrator alive. Error logged.

### GTC-04: MessageEnvelope Retains Backwards Compatibility
**Setup**: Old v7.3 message without `version` field.
**Action**: `MessageEnvelope.from_stream_entry(old_format)`
**Expected**: No crash. Payload extracted correctly.
**Pass Criteria**: Old messages processed correctly.

### GTC-05: DLQ Still Works After Schema Validation Added
**Setup**: Message that fails validation 3 times.
**Action**: DLQ entry created.
**Expected**: DLQ entry has full envelope info + schema violation reason.
**Pass Criteria**: DLQ entry complete.

### GTC-06: Agent-Worker Restart Kills Hermes Subprocess
**Setup**: Hermes running. Systemd kills agent-worker.
**Action**: `systemctl stop karios-backend-worker`.
**Expected**: Hermes subprocess also dead (SIGKILL via process group).
**Pass Criteria**: No orphaned Hermes processes.

### GTC-07: Concurrent SELF-TEST Rejected
**Setup**: BG-stub-no-op already running. Second `[SELF-TEST]` sent.
**Action**: Orchestrator handles second SELF-TEST.
**Expected**: Rejected with "self-test already running".
**Pass Criteria**: No concurrent self-test. First continues.

### GTC-08: Hermes Config tool_use_enforcement=strcit Spelled Correctly
**Setup**: Check all 9 profile configs.
**Action**: `grep "tool_use_enforcement" /root/.hermes/profiles/*/config.yaml`
**Expected**: All 9 profiles show `strict` (not `strcit` typo).
**Pass Criteria**: All profiles correct.

### GTC-09: Vault Write Still Works After Schema Validation Added
**Setup**: Architect writes learning via `karios-vault learning`.
**Action**: Vault entry written.
**Expected**: Entry visible in vault search.
**Pass Criteria**: Vault functional.

### GTC-10: Rollback Restores v7.4 State
**Setup**: v10 deployed. Run `karios-meta-runner rollback`.
**Action**: Check orchestrator version. Check all 9 agent configs.
**Expected**: Back to v7.4 state. `tool_use_enforcement: auto`.
**Pass Criteria**: Rollback complete.
