# Edge Cases — ARCH-IT-ARCH-v10 (iteration 1)

## A. Tool-Use Enforcement Edge Cases

### AEC-01: Hermes Produces Markdown With Tool-Name in Prose
**Scenario**: Architect writes "To solve this, I'll use write_file to create the doc" — this contains the string `write_file` but is NOT an actual tool call.
**Risk**: Watchdog falsely detects tool call, allows prose-only output.
**Mitigation**: Watchdog only triggers on structured tool-call markers: JSON `{"tool":"...",` or `Function call` prefixed blocks. Prose mentions of tool names won't match. Additionally, require tool call within first 30K *non-whitespace* characters.

### AEC-02: Hermes Produces Very Short Tool Calls (Fast Exit)
**Scenario**: Hermes calls `read_file` on a tiny 100-byte file, then produces 50K of prose in a second turn.
**Risk**: Watchdog sees tool call at token 50, allows prose to continue indefinitely.
**Mitigation**: Reset token counter after each tool call. Watchdog fires if consecutive 30K tokens pass with no tool call. Use per-turn not per-session tracking.

### AEC-03: Agent-worker Process Gets OOM-Killed by systemd
**Scenario**: Hermes output is very large (streaming to memory via PIPE). OOM killer terminates agent-worker.
**Risk**: Watchdog mechanism itself crashes; task hangs.
**Mitigation**: Use `subprocess.PIPE` with `read1()` (non-blocking reads) and bounded buffer. Or use temp file pipe: `stdout=open('/tmp/hermes_out_<pid>.tmp', 'wb')`. Hard cap output size at 50MB.

### AEC-04: `tool_use_enforcement: strict` on Non-Coding Agents
**Scenario**: Monitor agent or tester agent has no tools relevant to their task (e.g., monitoring is mostly read-only API calls).
**Risk**: Hermes with `strict` loops or refuses to respond productively.
**Mitigation**: Only apply `strict` to coding agents (architect, backend, frontend). Keep `auto` for monitor, tester, devops, blind-testers.

### AEC-05: Watchdog Timeout Race Condition
**Scenario**: Hermes produces output at exactly 30,001 tokens — watchdog kills it mid-write. Output file is partially written.
**Risk**: Partial files corrupt the architecture docs.
**Mitigation**: On watchdog kill, move partial output to `/var/lib/karios/partial-outputs/<trace_id>.partial`. Notify orchestrator. Don't process partial files as valid outputs.

### AEC-06: Hermes Uses MCP Tool Not in WATCHDOG_PATTERNS
**Scenario**: New MCP tool (e.g., `mcp__code-review-graph__query_graph`) is used but not in the hardcoded tool-call patterns.
**Risk**: Watchdog misses the tool call, kills Hermes unnecessarily.
**Mitigation**: WATCHDOG_PATTERNS includes broad matches: `b'"tool":"'` (all JSON tool calls), `b'Function call'`. Additional pattern: `b'mcp__'` for all MCP tool invocations. Pattern list is configurable via env var.

---

## B. JSON Schema Validation Edge Cases

### BEC-01: Message Contains No JSON At All
**Scenario**: Agent sends `[ARCH-COMPLETE]` with plain prose body, no JSON fence.
**Risk**: Schema validation fails to find any JSON, crashes on `json.loads(None)`.
**Mitigation**: `parse_message` first tries JSON fence, then raw `{...}`, then treats entire body as invalid. Returns `None` (no dispatch) and sends `[SCHEMA-REJECTED]` with reason `"no JSON found in body"`.

### BEC-02: Extra Fields in JSON (Future-Proofing)
**Scenario**: Agent sends `{"rating": 10, "extra_field": "value"}` — valid except for extra field.
**Risk**: Pydantic rejects extra fields by default (`model_validate` raises ValidationError).
**Mitigation**: Use `model_validate` with `extra='ignore'` by defining BaseModel with `model_config = ConfigDict(extra='ignore')`. Or use `@field_validator` with `strict=False`.

### BEC-03: Schema Version Mismatch (Old Agent, New Schema)
**Scenario**: Backend from v7.4 sends `[CODING-COMPLETE]` with old schema (missing new `unit_tests_added` field).
**Risk**: Pydantic raises ValidationError on missing required field.
**Mitigation**: All new fields in Pydantic models use `Optional` with defaults. Mandatory fields never change. If a required field is truly needed, it gets added in a coordinated migration, not silently.

### BEC-04: JSON Fence Inside Code Block Inside JSON
**Scenario**: Agent sends JSON containing a code block with triple backticks inside a string value.
**Risk**: Naive regex ````json\s*(.*?)\s*```` matches the inner ``` prematurely.
**Mitigation**: Use proper JSON parsing: try to find the first `{` and match to the last `}` with balanced brace counting. Or use `json.loads()` on the entire body and catch errors.

### BEC-05: Schema Validation Crashes Dispatcher Itself
**Scenario**: Pydantic library has a bug or import fails (missing dependency in container).
**Risk**: `parse_message` itself crashes, blocking all message processing.
**Mitigation**: Wrap schema validation in `try/except Exception` at top level. On any exception, log and fall back to v7.3 behavior (unvalidated dispatch). Never let schema validation crash the dispatcher.

### BEC-06: `[ARCH-REVIEWED]` Body Is Not JSON But Has Rating Number
**Scenario**: Blind-tester sends `rating: 8/10` in prose but no JSON.
**Risk**: Validation rejects valid review.
**Mitigation**: Schema validation only required for `ARCH-COMPLETE`, `CODING-COMPLETE`, `E2E-RESULTS`. Other subjects use looser validation (subject detection + key presence). Rating fields are required only for review subjects.

---

## C. Self-Test (BG-stub-no-op) Edge Cases

### CEC-01: BG-stub-no-op Runs Concurrently With Real Gaps
**Scenario**: BG-stub-no-op is triggered while another real gap is in Phase 3.
**Risk**: Resource contention (deploy targets overlap, Redis keys collide).
**Mitigation**: Self-test gaps use a dedicated Redis namespace (`gap_id=BG-stub-no-op`). Orchestrator enforces: only ONE self-test gap can run at a time. Second `[SELF-TEST]` trigger while one is active → rejected with "self-test already running".

### CEC-02: Phase 5 Deploy of No-Op Flag Fails Health Check
**Scenario**: The Go code compiles but the service health endpoint (`/health`) returns non-200.
**Risk**: Phase 5 gate fails even though the code is correct.
**Mitigation**: BG-stub-no-op explicitly includes a `/health` endpoint in its minimal Go file. Health check is known to return 200. If it fails, the self-test itself is broken and needs fixing before the pipeline is trusted.

### CEC-03: Telegram Message From Phase 6 Gets Rate Limited
**Scenario**: `notify_phase_transition()` hits Telegram rate limit during self-test.
**Risk**: Phase 6 gate never passes, self-test loops.
**Mitigation**: Add retry with exponential backoff (max 3 retries) in `notify_phase_transition()`. On final failure, log to vault and emit `[MONITORING-COMPLETE]` anyway (Telegram is best-effort notification).

---

## D. code-review-graph Rubric Edge Cases

### DEC-01: Agent Calls `get_minimal_context` Then Ignores It
**Scenario**: Agent calls `get_minimal_context`, gets context, then proceeds to do raw file reads anyway.
**Risk**: Score=1 but graph was not actually used for efficiency.
**Mitigation**: Current score is binary (called vs not-called). For v10, binary is sufficient. Future enhancement: audit actual file reads vs graph-reported files.

### DEC-02: Session Log Doesn't Contain `get_minimal_context` Due to Compression
**Scenario**: Hermes compresses context mid-session. The string `get_minimal_context` doesn't appear in compressed output.
**Risk**: False negative: agent DID use graph but it's not in the captured stdout.
**Mitigation**: Also check session log files at `~/.hermes/profiles/<agent>/sessions/`. Additionally, have the MCP server itself log invocations to a Redis stream (`stream:graph-audit-mcp`) — this is authoritative.

### DEC-03: Phase 1 Research Agent Has No Code to Review
**Scenario**: Architect Phase 1 does no code touching at all — pure research.
**Risk**: `check_graph_rubric` returns False for architect in Phase 1, fails the gate incorrectly.
**Mitigation**: Only apply graph rubric check to agents in Phase 3 (backend, frontend). Phase 1 is exempt. Or: check if `AGENT in ("backend", "frontend")` before applying rubric.

---

## E. Gitea Push Verification Edge Cases

### EEC-01: Multiple Repos — karios-migration AND karios-web Changed
**Scenario**: Gap touches both backend and frontend, both repos need push verification.
**Risk**: Checking only karios-migration misses karios-web.
**Mitigation**: Track `repos_modified` in gap metadata. After deploy, verify EACH modified repo:
```python
for repo in gap_metadata.get("repos_modified", ["karios-migration"]):
    if not verify_gitea_push(repo):
        send_to_agent("devops", "[PUSH-REQUIRED]", f"repo={repo} not pushed")
        return
```

### EEC-02: Rebase In Progress on Machine
**Scenario**: Developer has local commits not yet rebased. `git rev-list` shows `ahead > 0`.
**Risk**: Push verification fails even though the machine is in a normal working state.
**Mitigation**: On `ahead > 0`, check if the local branch is clean (no uncommitted changes). If clean and ahead, push is needed → fail with `[PUSH-REQUIRED]`. If dirty, reject with `[DIRTY-WORKTREE]` and instruction to stash/clean first.

### EEC-03: Gitea Unreachable (Network Partition)
**Scenario**: Network partition to gitea.karios.ai during push verification.
**Risk**: `git rev-list` hangs or times out, blocking Phase 6.
**Mitigation**: Add 30-second timeout to `subprocess.run` for `git rev-list`. On timeout: log warning, allow PROD-DEPLOYED with note "push verification skipped (timeout)", notify Sai via Telegram.

### EEC-04: Force-Pushed Branch
**Scenario**: Branch was force-pushed. `origin/main` is now different from what was deployed.
**Risk**: Verification passes (0,0) but deployed code is not what Gitea shows.
**Mitigation**: After push, record the pushed commit SHA in gap metadata. Verify the SHA matches what was deployed. If not, fail `[PROD-DEPLOYED]` with explanation.

---

## F. Telegram Filter Edge Cases

### FEC-01: Sai Needs Emergency Manual Intervention
**Scenario**: Pipeline is stuck, Sai needs to manually send a command to unblock.
**Risk**: Filter blocks all manual Telegram, including emergency interventions.
**Mitigation**: Keep `/status` and `/emergency` commands available to humans. Emergency bypass: `/emergency-unblock <gap_id>` sends a direct Redis command to unstick the gap. All manual commands are logged to vault with `[MANUAL-OVERRIDE]` tag.

### FEC-02: Pipeline Sends Telegram But Bot Token Is Revoked
**Scenario**: Telegram API returns 401 during `notify_phase_transition()`.
**Risk**: Phase transitions silently fail to notify.
**Mitigation**: Catch Telegram API errors in `notify_phase_transition()`. On 401/403, alert via Redis pub/sub (`channel:alerts`). On 429 (rate limit), retry with backoff. Log all failures to vault.

### FEC-03: Telegram Chat ID Changed Again
**Scenario**: Telegram chat_id rotates (happened once already per learnings).
**Risk**: Pipeline sends to old chat_id, notifications are lost.
**Mitigation**: `notify_phase_transition` always fetches current chat_id from `/etc/karios/secrets.env` at runtime (not cached). On send failure with "chat not found", automatically update chat_id from Telegram `getUpdates` response.

---

## G. Cross-Cutting Edge Cases

### GEC-01: All 6 Changes Deployed Simultaneously
**Scenario**: All v10 components deployed in one shot. Something breaks. Hard to isolate.
**Risk**: Debugging becomes difficult.
**Mitigation**: Deploy in the 5-phase sequence defined in architecture.md. Each phase is independently reversible. Test BG-stub-no-op after each phase, not just at the end.

### GEC-02: Agent-Worker Restart During Watchdog Monitoring
**Scenario**: systemd restarts agent-worker mid-Hermes-call.
**Risk**: Watchdog thread dies with the process. Orphaned Hermes subprocess continues running.
**Mitigation**: Hermes subprocess is in its own process group (`preexec_fn=os.setsid`). When agent-worker dies, systemd's cgroup cleanup sends SIGKILL to the entire process group. Orphan Hermes is killed.

### GEC-03: Redis Connection Lost During Schema Validation
**Scenario**: `parse_message` tries to send `[SCHEMA-REJECTED]` but Redis is unavailable.
**Risk**: Rejection message never sent. Sender hangs waiting for response.
**Mitigation**: Redis connection uses 5-second timeout. On Redis failure during schema rejection, log to vault file as fallback (`/var/lib/karios/coordination/schema-violations/<msg_id>.json`). Don't block on Redis.

### GEC-04: BG-stub-no-op Completes Successfully But Previous Gaps Are Now Broken
**Scenario**: BG-stub-no-op passes all 6 phases. But a concurrent real gap that was running during deployment now fails.
**Risk**: False confidence — self-test passes but production is degraded.
**Mitigation**: Monitor p95 latency of real gaps during self-test window. If any real gap degrades during self-test, abort self-test and escalate.
