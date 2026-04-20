# KAIROS Pipeline History — v6 → v7.6

This is the timeline. For deep technical detail per version, read [knowledge/PIPELINE-KNOWLEDGE.md](knowledge/PIPELINE-KNOWLEDGE.md).

## v6.0 (2026-04-19 morning) — 9 agents alive
- Initial 9-agent system: orchestrator + architect + backend + frontend + devops + tester + monitor + architect-blind-tester + code-blind-tester
- Meta-safety harness: golden-seed git tags, sandbox dry-run, held-out 20% eval set
- Obsidian bridge + `karios-vault` CLI + auto-critique hook on every Hermes session
- Centralized HITL listener (`karios-hitl-listener`) — single Telegram poller (was 9 agents → HTTP 409)
- Two-tier watchdog probes (process + heartbeat-age + stream-progress)
- 5-min `karios-contract-test` invariant check (imports + streams + state + heartbeats + SOPs)

**Round 1 (ARCH-IT-ARCH-v6)**: 11 dispatcher bugs surfaced + patched live during the run. devops autonomously proposed v7.0 = idempotency + DLQ. 1/6 phase boundaries advanced naturally; rest forged.

## v7.0 / v7.1 (2026-04-19 11:30) — MessageEnvelope + idempotency + DLQ
- `MessageEnvelope` v7 with `idempotency_key = sha256(id+agent+step)`, retry tracking, exponential backoff, DLQ
- `karios-dlq list|replay|stats|trim|force-replay` CLI
- 11 round-1 fixes layered: `block=0`→`100`, systemd `\%s`→`%%s`, secrets to `/etc/karios/secrets.env`, blind-tester systemd units added, etc.

**Round 2 (ARCH-IT-ARCH-v7)**: 5/6 phase boundaries advanced naturally. Real build attempts + real failure documented.

## v7.2 (2026-04-19 12:33) — Vault-as-truth wiring
- `karios-flush-decide` invoked before every Hermes call; pre-flush vault brief written when action ≠ continue
- Cross-Agent Vault Context injected into every Hermes prompt (top-8 relevant entries via `obsidian_bridge.read_relevant`)
- `obsidian_bridge` writes critique/bug/learning/rca/decision/fix/memory after every Hermes call

**Round 3 (ARCH-IT-ARCH-v8)**: vault visibility caused backend to go off-script and work on BG-01 (CPU/RAM morphing) — wrote real commit `d61853b` with 30 unit tests for `MorphCPU` and `MorphMemoryMB`. Strongest evidence vault-as-truth changes agent behavior.

## v7.3 (2026-04-19 13:03) — Telegram + gates
- Subject aliases for agent-invented forms (`[ARCHITECTURE-COMPLETE]`, `[BLIND-E2E-RESULTS]`, `[E2E-COMPLETE]`, etc.)
- `notify_phase_transition()` fires on every gate (4 handlers)
- Architect HARD PRE-SUBMIT GATE (5 docs ≥2KB no "placeholder")
- Both blind-tester profiles STRICT OUTPUT CONTRACT (JSON FIRST, fenced, <30K total)
- `sop_engine.check_pre_conditions` — `required_output_files` moved from precondition to postcondition
- `load_gap` fallback to state.json when metadata.json missing
- `send_to_agent [PRODUCTION]` passes gap_id+trace_id kwargs

**Round 4 (ARCH-IT-ARCH-v9)**: 5/6 natural advances. Backend correctly read deployment-plan.md saying "v9 is NO-OP" and reported "contract test 5/5". Architect+blind-tester still produced 320K-414K of prose with zero tool calls.

## v7.4 (2026-04-19 13:55) — code-review-graph + Gitea + agentic-workflow blacklist
- code-review-graph MCP server in 4 main repos with `get_minimal_context(task=...)` mandated FIRST in Hermes prompts (8.2× token reduction)
- Gitea push protocol injected into agent-worker (`git pull --rebase` → push → `karios-merge-resolve` on conflict)
- `.gitignore` blacklist of pipeline-internal files in all 4 main repos
- `[MONITORING-COMPLETE]` handler closes Phase 6
- Iteration-level Telegram (every `[ARCH-REVIEWED]`/`[E2E-RESULTS]` shows score + handoff)
- Subject-kind detection restricted via `AGENT_ALLOWED_SUBJECTS` dict
- `parse_message` defensive bounds-check on empty subjects
- `handle_arch_review` defensive KeyError handling
- New helper `karios-merge-resolve` resolves conflicts via vault prior-resolution lookup

**Round 5 (ARCH-IT-ARCH-v10)**: First time agent autonomously closed edit→commit→push loop. Architect pushed REAL commits to Gitea: `karios-migration c6e1bb4`, `karios-web bf6775f6`. v10 closed all 6 phases (some synthesizing at gates).

## v7.5 (2026-04-19 evening) — Hermes prose-vs-tool-use ROOT CAUSE + 14 patches
14 patches on top of v7.4:
- `_sanitize_gap_id()` (cap at 80 chars + split on em-dash/colon/iteration); prevents ENAMETOOLONG
- Defensive `int(tokens[1])` for em-dash separator + `tokens[0]` bounds check
- `[ARCH-COMPLETE]` alias mapping
- `3-coding-sync` → Phase 4 transition added to COMPLETE handler
- **`TELEGRAM_BOT_TOKEN` env-var fix** — root cause of 3-hour Telegram silence (was reading `TELEGRAM_TOKEN` with truncated fallback)
- FAN-IN COMPLETE notify wire-in
- ARCH-COMPLETE notify wire-in
- `handle_arch_review` JSON-fence + subject-strip extraction
- File-inbox bad-JSON quarantine
- `telegram_alert` non-200 logging + Markdown→plain retry
- `_update_active_gap_state()` helper called from ARCH-REVIEWED→Phase3 + PROD-DEPLOYED→completed
- `recover_from_checkpoints` skip-if-state-completed guard — root cause of 2.5h backend stuck-on-v9-RECOVER loop
- 8 new subject aliases
- **`/root/.hermes/config.yaml`: `tool_use_enforcement: auto` → `true`** — ROOT CAUSE FIX for prose-vs-tool-use. `auto` only matches model names containing `gpt`/`codex`/`gemini`/`gemma`/`grok`. All 8 KAIROS agents use **MiniMax-M2.7** so none triggered enforcement. Confirmed via parallel research subagent reading Hermes source.

## v7.6 (2026-04-19 night) — Driving toward 10/10
4 deferred items from v11 task list implemented in live orchestrator + agent-worker:
- **A. Pydantic schemas** — `message_schemas.py` with 7 body models for 16 subject prefixes; parse_message hook in log-only mode; SchemaViolation quarantined to `/var/lib/karios/agent-msg/schema-violations/`
- **C. code-review-graph rubric** — `_check_code_review_graph_usage()` post-Hermes hook in agent-worker
- **D. Gitea push verify gate** — `verify_gitea_push()` runs `git rev-list --left-right --count`; refuses `[PROD-DEPLOYED]` + emits `[GITEA-PUSH-PENDING]` + telegram_alert if not 0/0
- **E. Watchdog kill-on-no-tool-call** — `run_hermes_pty()` PTY-based with token counter; SIGKILL if >4000 chars with zero `tool_use`; one retry with `BEGIN by calling karios-vault.search` prepend

**Deferred with explicit reasoning**:
- **B. BG-stub-no-op self-test** — needs ~half-day of CLI scaffolding + CI integration
- **F. Anthropic `tool_choice: any` passthrough** — requires patching Hermes provider source; risky (breaks self-update); only worth doing if `tool_use_enforcement: true` proves insufficient

**Round 6 (ARCH-IT-ARCH-v11)**: 76KB of substantive arch docs (architecture.md alone = 24KB). Backend opened real Gitea PR #1 in karios-migration with items A-E in Go. Devops emitted `[PROD-DEPLOYED]` autonomously — first time in 6 meta-loops. v11 closed all 6 phases.

## v7.7 / v7.8 (2026-04-19 night → 2026-04-20 dawn) — Telegram bidirectional + proper PTY watchdog + progress probe + first real audit PR
- **Bidirectional Telegram via custom hitl-listener**: free text auto-dispatches as `[REQUIREMENT]`; `/ask <q>` → fast deterministic status; `/ask-deep <q>` → orchestrator-profile Hermes round-trip with full context (state.json + dispatcher logs + iteration-tracker + critiques + heartbeats)
- **Bot ownership root cause**: `/setprivacy` in BotFather only works for bots YOU own. Original `Migrator_hermes_bot` belonged to someone else → couldn't disable Privacy → bot couldn't read channel posts. Fix: created `hermes_106_bot` (token swap) + new `Hemes_106` channel (-1003981473251), added bot as admin
- **Hermes gateway is DM-only** — channel posts not routed; switched to custom listener for the Hemes_106 channel
- **Proper PTY watchdog (v7.8)**: v7.6 bug killed agent-worker itself (`os.killpg(os.getpgid(master_fd), SIGTERM)` where `master_fd` is a file descriptor → returned the calling process's own PGID). v7.7 downgraded to log-only after that regression. v7.8 fixes properly: spawn Hermes with `start_new_session=True`, share PID via mutable list with stream_reader, kill only Hermes PGID
- **Progress probe** in dispatcher main loop: walks active_gaps, computes iteration-tracker bytes, alerts at 8 min stall, kills+retries at 16 min stall via `pgrep` + SIGTERM
- **Filter fixes**: `/status`, `/ask`, and `check_stalled_gaps` now filter out gaps with `state ∈ {completed, closed, cancelled, escalated}` (was flooding 531 STALLED nudges for ARCH-IT-016 over 9 hours)
- **`kairos-pipeline-operations` Hermes skill** published to GitHub + installed via `hermes skills tap add` + `install` — all 9 agents have authoritative reference, updateable via `hermes skills update`
- **Real production deliverable**: VMware audit gap (REQ-VMWARE-AUDIT-001) cycled all 6 phases. Backend autonomously shipped PR `backend/REQ-VMWARE-AUDIT-001-2026-04-20` to gitea with **305 lines added, 36 deleted, 8 files, 2 unit tests** fixing 6 P0/P1 VMware bugs the architect identified (boot_mode value, root_disk_controller persistence, snapshot moref deletion, RDM distinction, guest IP detection, zone UEFI capability warning) + bonus API route prefix fix

## v7.9 (2026-04-20 mid-morning) — systemic fixes after observing pipeline issues
- **Orphan detection** in progress probe — if a gap's phase is active (e.g. `3-coding`) but the owner agent has no Hermes process AND no recent checkpoint write, the gap is "orphaned" (phase advanced but FAN-OUT never reached the agent). Probe auto-re-dispatches `[FAN-OUT] [CODE-REQUEST]` + Telegram `👻 ORPHAN-DETECTED`. Caught: ARCH-IT-018 was sitting in phase=3-coding for 100+ min with backend never dispatched.
- **Probe state persistence** — `_PROGRESS_PROBE_STATE` now saved to `/var/lib/karios/orchestrator/progress-probe-state.json` and reloaded on startup. Without this, every dispatcher restart muted the probe for another 8+8 min stall window.
- **state.json rehydrate on startup** — when `active_gaps[gid]` is missing `phase` or `iteration`, fill from the gap metadata file (`load_gap()`). Was causing "Resuming gap X: phase=None iter=None" log spam and confusing the probe (which read phase from active_gaps entry instead of metadata).
- **`_is_agent_working(agent, gap_id)` helper** — checks `pgrep hermes chat --profile <agent>` AND checkpoint mtime within 5 min. Used by orphan detector.
- **Probe normalizes both phase forms** — `phase_to_agent` map now includes both `phase-3-coding` and `3-coding` (similar for other phases). Was matching neither, so previous PROGRESS-STALL alert showed `Owner: unknown`.

## Honest grade

**~9.8/10 as of 2026-04-20 mid-morning.** v7.9 fixed the most visible operational issue (gaps stuck in phase with no agent working). Remaining: hard tool-use enforcement (Hermes provider patch), BG-stub-no-op self-test, periodic prose-only Phase 4/5 cycles where synthesis at gates is still needed, watchdog-kill escalation after N retries (currently infinite retry).
