# Harness Frameworks + Hermes Self-Evolving Research (2026-04-20)

**Context**: User asked to research best harness frameworks + leverage Hermes native self-evolving features. Goal: integrate top findings into KAIROS pipeline. Skip cost/latency tracking (L) per user preference.

## TL;DR

| Rank | Integration | Effort | What it adds | ETCSLV |
|---|---|---|---|---|
| 1 | DSPy+GEPA via hermes-agent-self-evolution | 10-14h | Auto-optimize ALL 9 agent prompts from session traces | C+T+V |
| 2 | Inspect AI (UK AISI) | 8-12h | One eval framework with Proxmox sandbox + 200 pre-built evals | E+T+V |
| 3 | Langfuse self-hosted | 6-8h | Per-turn trace tree across 9 agents | V |
| 4 | Hermes plugin replacing obsidian_bridge.py | 4-6h | Native on_session_end hook | V+T |
| 5 | Holographic memory + per-agent profiles | 4-6h | Local SQLite long-term memory per role | C |

Total: ~34-46h.

## Stream 1: Harness frameworks (13 evaluated)

### Top picks for KAIROS

**SWE-bench Pro** (2,294 multi-language issues; Verified is now considered contaminated): wire as **V** for code-blind-tester. Run nightly Docker harness against backend's PRs.

**EvalPlus (HumanEval+ / MBPP+)**: cheap (~5min) regression for meta-loop critic. 80x more tests than vanilla HumanEval.

**AgentBench (THUDM)**: 8-environment stress test for the dispatcher itself.

**Inspect AI** (UK AISI): **best general-purpose harness in 2026.** Native Proxmox sandbox. Drives Claude Code/Codex/Gemini CLI as external agents. Replaces our ad-hoc evals.

**DSPy + GEPA**: GEPA = Reflective Pareto Evolution, **ICLR 2026 oral**, 13% over MIPROv2, 35x fewer rollouts than GRPO. Wraps each agent's prompt as a mutable artifact.

**Langfuse**: open-source observability (21K stars). Self-hostable, OTEL-compatible. Closes our trace gap.

**ToolBench / GAIA / CRAG / PromptFoo / OpenAI Evals / HELM / Phoenix**: secondary, evaluate later as needed.

## Stream 2: Hermes Agent v0.9.0 native features (10 confirmed)

**hermes-agent-self-evolution repo** (https://github.com/NousResearch/hermes-agent-self-evolution) — separate Phase-1 project that uses DSPy+GEPA to evolve SKILL.md files via PR. Cost $2-10/run.

**8 memory providers**: Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, Supermemory. Recommended: **Holographic** (local SQLite + FTS5 + HRR algebraic queries + trust scoring + contradiction detection).

**Plugin system**: hooks for pre_tool_call, post_tool_call, pre_llm_call, post_llm_call, on_session_start, on_session_end. APIs: register_tool, register_hook, register_command, register_cli_command, inject_message, register_skill. Default-disabled, opt-in.

**hermes cron**: native cron with delivery to 16 messaging platforms in natural language. Replace our bash cron + meta-loop scheduler.

**hermes insights**: token/cost/activity analytics. /insights slash command.

**hermes skills tap/install/audit/snapshot**: full skill lifecycle. 649 skills in hub.

**hermes acp**: Agent Communication Protocol server for editor integration.

**hermes profile**: per-agent isolated instances with own MEMORY.md, USER.md, config, plugins, memory provider.

**MEMORY.md / USER.md / sessions/**: native paths Hermes writes to. FTS5 search built-in.

**NO native hermes eval / hermes learn / hermes regression**: must wire DSPy+GEPA externally (or write a plugin).

## Specific files to add/modify

`pipeline/orchestrator/event_dispatcher.py` — wrap dispatch with langfuse trace, replace inline prompts with dspy.Signature classes.

`pipeline/orchestrator/prompt_builder.py` — replace string concat with dspy.ChainOfThought; persist GEPA-evolved instructions.

`pipeline/agent-worker` — wrap with @langfuse.observe(); spawn each agent as hermes --profile <role> for isolated MEMORY.md.

`pipeline/hermes/config.yaml` — add memory.provider: holographic; plugins.enabled list.

NEW: `pipeline/hermes/plugins/kairos-obsidian-bridge/{plugin.yaml,__init__.py}` — replace standalone obsidian_bridge.py.

NEW: `pipeline/evals/kairos_dispatch.py` — Inspect AI Task per agent role.

## Risks per integration

- **GEPA**: mutations can drift skill semantics. Mitigate: PR-review safety guardrail + karios-acceptance-test as hard gate.
- **Inspect AI**: heavy initial setup; Proxmox sandbox adapter may need patches for PVE9.
- **Langfuse**: Postgres dependency on .106; trace overhead — use sampling.
- **Hermes plugin**: opt-in/disabled-by-default — easy to forget on fresh node; document in karios-bootstrap-ops.
- **Holographic**: 9 SQLite DBs to back up; FTS5 grows unbounded — schedule weekly VACUUM via hermes cron.

## Sources

See full agent transcript. Key URLs:
- https://github.com/NousResearch/hermes-agent-self-evolution
- https://hermes-agent.nousresearch.com/docs/
- https://dspy.ai/api/optimizers/GEPA/overview/
- https://inspect.aisi.org.uk/
- https://langfuse.com/
- https://github.com/SWE-bench/SWE-bench
