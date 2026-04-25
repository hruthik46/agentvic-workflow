# Edge Cases — ARCH-IT-ARCH-v11 (iteration 1)

## Overview

Edge cases are organized by item (A–F). Each edge case describes the failure mode, trigger condition, and mitigation strategy.

---

## Item A: Pydantic Schema Validation Edge Cases

### Edge-A-01: Empty body string
- **Scenario**: Agent sends message with empty `body: ""`
- **Subject**: `[ARCH-REVIEWED]`
- **Trigger**: `json.loads("")` raises `JSONDecodeError`
- **Mitigation**: `validate_message()` catches `JSONDecodeError`, writes quarantine, returns `(False, "JSON parse error", None)`
- **Expected behavior**: Message quarantined, sender NOT notified (sender unknown in empty body case)

### Edge-A-02: Body is valid JSON but not an object (e.g., array `[]` or string)
- **Scenario**: Agent sends `body = "[]"` or `body = '"just a string"'`
- **Trigger**: `model_cls.model_validate([])` raises `ValidationError` (Pydantic expects dict)
- **Mitigation**: Catch as validation error, quarantine
- **Expected behavior**: Quarantine file written with reason

### Edge-A-03: Subject matches multiple schema prefixes
- **Scenario**: Subject `[ARCH-COMPLETE-FINAL]` matches both `[ARCH-COMPLETE]` and `[ARCH-]` prefix
- **Trigger**: Iteration over `SCHEMA_MAP` — first match wins (insertion order)
- **Mitigation**: `SCHEMA_MAP` ordered with longest-prefix-first. `[ARCH-COMPLETE]` checked before `[ARCH-]`
- **Expected behavior**: `[ARCH-COMPLETE-FINAL]` matches `ArchCompleteBody` (longest prefix)

### Edge-A-04: Schema for subject exists but body is massive (>1MB)
- **Scenario**: Malicious or buggy agent sends 10MB JSON body
- **Trigger**: `json.loads()` loads massive JSON into memory, Pydantic validates
- **Mitigation**: Check `len(body) > 1_000_000` before parsing; if exceeded, quarantine with reason `"body too large"`
- **Expected behavior**: Quarantine with size limit reason

### Edge-A-05: Unicode in body causes decode issues
- **Scenario**: Agent sends body with invalid UTF-8 sequences or excess Unicode
- **Trigger**: `json.loads()` handles this correctly in Python 3, but field extraction may fail
- **Mitigation**: Pydantic v2 handles Unicode natively; use `str` type annotations
- **Expected behavior**: Valid Unicode passes, malformed JSON fails at `json.loads()`

### Edge-A-06: Iteration 1 (log-only) phase — quarantine dir not yet enforced
- **Scenario**: Schema violation occurs during iteration 1 (log-only phase)
- **Trigger**: `validate_message()` logs violation but does NOT quarantine
- **Mitigation**: Quarantine dir IS created for future use, but files not moved during iteration 1
- **Expected behavior**: Log shows `SCHEMA VIOLATION (log-only): <reason>`, no quarantine file

### Edge-A-07: Nested JSON field exceeds Pydantic depth
- **Scenario**: Agent sends deeply nested JSON (e.g., `{"a":{"b":{"c":...}}}` 50 levels deep)
- **Trigger**: Pydantic `model_validate()` accepts it (no depth limit), but downstream handlers may stack overflow
- **Mitigation**: Set reasonable field limits in schema (e.g., `Field(default_factory=list)` for lists)
- **Expected behavior**: Accepted by schema but may cause downstream issues — documented as known limitation

### Edge-A-08: Agent sends subject with trailing whitespace
- **Scenario**: Subject `"[ARCH-COMPLETE] " ` (trailing space)
- **Trigger**: `subject.startswith(prefix)` succeeds but `SCHEMA_MAP.get()` lookup may miss
- **Mitigation**: `subject = subject.strip()` before `startswith()` checks
- **Expected behavior**: Trimmed before schema lookup

---

## Item B: BG-stub-no-op Self-Test Edge Cases

### Edge-B-01: Orchestrator restart during self-test
- **Scenario**: `karios-self-test` running, orchestrator restarted at Phase 3
- **Trigger**: `recover_from_checkpoints()` reloads `state.json`, sees `BG-stub-no-op` in `active_gaps`
- **Mitigation**: `recover_from_checkpoints` skip-if-completed guard (v7.5 item 6) — if gap state = "completed", skip redispatch
- **Expected behavior**: Self-test continues from checkpoint, does not restart from Phase 0

### Edge-B-02: BG-stub-no-op gap ID conflicts with real gap
- **Scenario**: Real requirement arrives with same gap ID `BG-stub-no-op`
- **Trigger**: Gap ID collision in `state.json` active_gaps
- **Mitigation**: `BG-stub-no-op` is reserved — `handle_requirement()` checks for reserved prefix and uses separate namespace `BG-STUB-NO-OP-SELFTEST` internally
- **Expected behavior**: Self-test runs in isolated namespace

### Edge-B-03: Telegram API is down during self-test
- **Scenario**: Phase transitions fire but Telegram API returns 503
- **Trigger**: `telegram_alert()` fails with non-200
- **Mitigation**: v7.5 item 2 already has retry path with Markdown→plain fallback
- **Expected behavior**: Telegram alerts retry 3 times, then log failure. Self-test continues (Telegram is monitoring-only, not blocking)

### Edge-B-04: Agent-worker crashes during Phase 3 coding
- **Scenario**: `backend-worker` crashes after `[ARCH-REVIEWED]`, before `[CODING-COMPLETE]`
- **Trigger**: Orchestrator STALLED detection fires after 10min of no progress
- **Mitigation**: STALLED handler nudges agent, backoff retry. BG-stub-no-op uses accelerated timeouts so STALLED fires at 5min, not 10min.
- **Expected behavior**: Agent restarted, Phase 3 continues

### Edge-B-05: karios-self-test timeout exceeded
- **Scenario**: Phase takes longer than allowed timeout (e.g., Phase 2→3 > 300s)
- **Trigger**: `karios-self-test` exits with code 1 after 30min total
- **Mitigation**: Timeout is generous (30min total). Telegram alert fires when self-test fails.
- **Expected behavior**: `karios-self-test` returns exit code 1, full logs preserved at `/var/lib/karios/self-test-results/`

### Edge-B-06: Self-test interrupted by new requirement from Sai
- **Scenario**: Sai sends real requirement while BG-stub-no-op self-test is running
- **Trigger**: `handle_requirement()` processes real requirement, state.json updated
- **Mitigation**: Orchestrator handles parallel gaps — self-test and real gap run concurrently
- **Expected behavior**: Both proceed in parallel, self-test results unaffected

---

## Item C: code-review-graph Rubric Gate Edge Cases

### Edge-C-01: Hermes session log is corrupted/unreadable
- **Scenario**: Session log at `/root/.hermes/sessions/{id}/log.txt` is binary/corrupt
- **Trigger**: `session_log_path.read_text()` with errors='replace' produces garbled text
- **Mitigation**: Use `errors='replace'`, `gc_count = log_content.count("get_minimal_context")` still works on garbled text
- **Expected behavior**: `code_review_graph_calls = 0` (misses real calls but no crash)

### Edge-C-02: get_minimal_context appears in a comment or string literal
- **Scenario**: Agent writes `// TODO: call get_minimal_context` in code
- **Trigger**: Naive string count matches the comment too
- **Mitigation**: Accept as-is (false positive is acceptable — better than false negative)
- **Expected behavior**: `code_review_graph_calls >= 1` → critique not written

### Edge-C-03: agent-worker crashes before session log is written
- **Scenario**: Hermes completes but `agent-worker` crashes before extracting metadata
- **Trigger**: No `session_metadata` field in `[CODING-COMPLETE]` message
- **Mitigation**: `session_metadata.get("code_review_graph_calls", 0)` → defaults to 0
- **Expected behavior**: CODING-COMPLETE refused (may be false positive), backend retries

### Edge-C-04: Frontend agent sends CODING-COMPLETE but frontend doesn't touch code
- **Scenario**: `frontend-worker` sends CODING-COMPLETE for a pure UI task (HTML/CSS only)
- **Trigger**: Task doesn't mention `.ts`, `.tsx`, `.py`, `.go` — `touches_code = False`
- **Mitigation**: `touches_code` heuristic — frontend tasks usually involve `.ts`/`.tsx` in real gaps. If false negative, critique written but gate doesn't fire.
- **Expected behavior**: If `touches_code = False`, gate check skipped (no critique for non-code task)

### Edge-C-05: Multiple get_minimal_context calls in single tool_call block
- **Scenario**: Agent calls `karios-vault.search` twice in rapid succession
- **Trigger**: Output stream contains `get_minimal_context` twice
- **Mitigation**: Count occurrences, not unique calls
- **Expected behavior**: `code_review_graph_calls = 2` → passes gate

---

## Item D: Gitea Push Verification Edge Cases

### Edge-D-01: Repo is not a git repository
- **Scenario**: `karios-migration` path is not a git repo
- **Trigger**: `git rev-list` returns non-zero exit code
- **Mitigation**: Catch exception, report as `"<repo>: git error <stderr>"`
- **Expected behavior**: PROD-DEPLOYED refused with git error detail

### Edge-D-02: origin/<branch> does not exist
- **Scenario**: Repo has no `origin/main` or `origin/master`
- **Trigger**: `git rev-list` fails with `fatal: ambiguous argument`
- **Mitigation**: Catch, report as branch not found
- **Expected behavior**: PROD-DEPLOYED refused, devops notified

### Edge-D-03: git authentication failure (Gitea token expired)
- **Scenario**: `git push` fails due to expired Gitea token
- **Trigger**: `git rev-list` still works (read-only), but push verification gate only checks read state
- **Mitigation**: This gate only checks commits exist locally vs origin. Push auth failure is a separate failure mode (outside this gate's scope — handled by Gitea push protocol in devops phase)
- **Expected behavior**: Gate passes (reads succeed), push still fails later — devops handles

### Edge-D-04: Manifest.json missing for gap
- **Scenario**: `/var/lib/karios/iteration-tracker/{gap_id}/manifest.json` does not exist
- **Trigger**: `verify_gitea_push()` called but `repos = []`
- **Mitigation**: If no manifest, check all 4 known repos (`karios-migration`, `karios-web`, `karios-core`, `karios-bootstrap`)
- **Expected behavior**: All known repos checked

### Edge-D-05: Gap repos span multiple git hosts
- **Scenario**: `karios-web` is on Gitea but `karios-migration` is on GitHub
- **Trigger**: Different origin remote names
- **Mitigation**: Read remote URL from `git remote get-url origin` per repo
- **Expected behavior**: Check `origin/main...HEAD` for each repo regardless of host

---

## Item E: Watchdog Kill-on-No-Tool-Call Edge Cases

### Edge-E-01: Hermes writes partial UTF-8 character at token boundary
- **Scenario**: 4001st token cuts mid-UTF-8 sequence
- **Trigger**: `os.read()` returns bytes with incomplete Unicode codepoint
- **Mitigation**: Decode with `errors='replace'` — replacement character added, no crash
- **Expected behavior**: Token count slightly inaccurate but watchdog still fires correctly

### Edge-E-02: tool_use event spans multiple read chunks
- **Scenario**: `"tool_use"` appears at chunk boundary, split across two reads
- **Trigger**: Chunk 1 ends with `"tool"`, Chunk 2 starts with `_use"`
- **Mitigation**: Accumulate buffer, search on concatenated string
- **Expected behavior**: `tool_use` detected across chunk boundary

### Edge-E-03: Hermes process is already dead when watchdog checks
- **Scenario**: Hermes exits naturally before watchdog fires
- **Trigger**: `pid.poll() is not None` after read returns empty
- **Mitigation**: Exit loop cleanly, no SIGTERM sent
- **Expected behavior**: Normal completion

### Edge-E-04: SIGTERM fails to kill process (zombie)
- **Scenario**: Hermes is in uninterruptible sleep (I/O wait)
- **Trigger**: `os.killpg()` with SIGTERM returns but process still alive after 5s
- **Mitigation**: Escalate to SIGKILL after 5s
- **Expected behavior**: Process killed

### Edge-E-05: PTY fd leak if reader_thread crashes
- **Scenario**: Exception in `stream_reader()` thread before `os.close(master_fd)`
- **Trigger**: `master_fd` left open
- **Mitigation**: `try/finally` ensures `os.close(master_fd)` always called
- **Expected behavior**: File descriptor closed even on thread crash

### Edge-E-06: Token count overflow (very long session)
- **Scenario**: Session runs for hours, token_count grows beyond `int` range
- **Trigger**: Python int is unbounded, but `> 4000` comparison still works
- **Mitigation**: None needed — Python ints are arbitrary precision
- **Expected behavior**: Watchdog fires at correct threshold

### Edge-E-07: Retry also triggers watchdog
- **Scenario**: Retry with explicit prompt also produces >4000 tokens with no tool_use
- **Trigger**: Two consecutive watchdog kills
- **Mitigation**: After second SIGTERM, do NOT retry again — return error to orchestrator
- **Expected behavior**: `"[WATCHDOG-RETRY-SKIPPED]"` appended to output, orchestrator handles failure

### Edge-E-08: PTY not available on platform
- **Scenario**: Running in container without PTY support (`os.openpty()` raises `OSError: out of pty pairs`)
- **Trigger**: `run_hermes_pty()` raises exception
- **Mitigation**: Catch exception, fall back to `subprocess.run` (no watchdog, but functional)
- **Expected behavior**: Degraded mode (no watchdog) until PTY issue resolved

---

## Item F: tool_choice Passthrough Edge Cases (Deferred)

### Edge-F-01: Profile has `extended_thinking: true` AND `tool_choice: any`
- **Scenario**: Both fields set simultaneously in profile
- **Trigger**: Incompatible — extended thinking requires model to reason before tools
- **Mitigation**: Gate: if `extended_thinking: true` in profile, do NOT forward `tool_choice: any`
- **Expected behavior**: `tool_choice` silently ignored for extended thinking profiles

### Edge-F-02: Provider does not support tool_choice parameter
- **Scenario**: OpenAI-compatible endpoint that doesn't recognize `tool_choice`
- **Trigger**: API returns 400 error
- **Mitigation**: Wrap in try/except, log warning, continue without `tool_choice`
- **Expected behavior**: Non-fatal warning, request succeeds without tool_choice

---

## Cross-Item Edge Cases

### Cross-01: Schema violation AND Gitea push failure AND watchdog kill simultaneously
- **Scenario**: Multiple failures in same gap
- **Trigger**: Complex interaction between items
- **Mitigation**: Each item is independently gated — failures accumulate in gap state
- **Expected behavior**: First failure gates advance; subsequent failures logged but don't re-trigger

### Cross-02: Iteration 1 log-only schema validation misses real violation
- **Scenario**: Malformed `[CODING-COMPLETE]` passes through during iteration 1
- **Trigger**: Log-only mode doesn't enforce
- **Mitigation**: Iteration 2 enforces. If real violation occurs, it will be caught then.
- **Expected behavior**: Violation logged but not quarantined in iteration 1

### Cross-03: Self-test uses new code paths that break production gaps
- **Scenario**: BG-stub-no-op implementation accidentally changes `event_dispatcher.py` in a way that breaks real gap processing
- **Trigger**: Shared code modification
- **Mitigation**: BG-stub-no-op only adds NEW code paths (separate functions); existing handlers unchanged
- **Expected behavior**: No regression in production gap handling

### Cross-04: Concurrent self-test and real gap in same phase
- **Scenario**: BG-stub-no-op in Phase 3 while real gap is also in Phase 3
- **Trigger**: Both gap IDs different, both in `active_gaps`
- **Mitigation**: Orchestrator handles concurrent gaps via independent state entries
- **Expected behavior**: Both progress independently

### Cross-05: StateRetrying FSM is a manual-retry state (not automatic)
- **Scenario**: Migration enters `StateRetrying` after `StateFailed + EventRetry`
- **Clarification**: StateRetrying is NOT a dead state. It has defined transitions:
  - Enter: `StateFailed + EventRetry → StateRetrying`
  - Exit via EventStart: `StateRetrying → StatePreflight` (manual operator retry)
  - Exit via EventCancel: `StateRetrying → StateCancelled`
- **Important**: There is NO automatic timeout transition from StateRetrying. The operator must explicitly send `EventStart` to resume from the checkpoint, or `EventCancel` to abort. This is intentional — operator decision is required before retry to avoid infinite retry loops.
- **Implementation**: See `internal/migration/fsm.go` lines 129-131, 143
- **Disk-level retry**: `DiskStateRetrying` in `DiskTransferState` FSM (ARCHITECTURE.md §38) is separate and DOES automatically re-enter `TRANSFERRING` via `runFromTransfer()` checkpoint logic.