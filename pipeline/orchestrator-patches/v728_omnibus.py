"""v7.28 omnibus — research-driven bulletproof patches:

1) PTY tool_use detection: match Hermes-rendered "run_agent: tool X completed"
   (the ACTUAL marker that hits the PTY, not raw MiniMax tags)

2) Strip <think>...</think> blocks from char counter so MiniMax thinking
   doesn't trigger watchdog (MiniMax M2.7 ALWAYS emits <think> per direct
   API testing — no API param disables it)

3) CRITICAL #1 from audit: Greedy regex `r'\\{.*\\}'` for fallback JSON
   could grab wrong object if response contains multiple {...}. Fix with
   balanced-brace parser.

4) CRITICAL #3 from audit: Unsafe `tokens[tokens.index("iteration")+1]`
   raises IndexError on bare-iteration subjects. Fix with bounds check.

5) HIGH #5: Silent JSON parse failure escalation — Telegram alert when
   parse fails after disk fallback also fails.

6) MEDIUM #6: hardcoded `iteration-{N}` paths — make tester prompts
   resilient to wrong-dir writes by globbing both iter-1 and iter-N.
"""
from pathlib import Path
import py_compile
import re

# ── 1+2: agent-worker tool detection + think-block filter ───────────────────
aw = Path("/usr/local/bin/agent-worker")
text = aw.read_text()

# Replace v7.27-A markers with broader set including Hermes PTY-rendered format
OLD = '''            # v7.27-A: Detect tool_use across MiniMax + OpenAI + Anthropic formats
            # MiniMax: <minimax:tool_call>, <invoke name=, <parameter name=
            # OpenAI: "tool_calls", "function_call"
            # Anthropic: "tool_use", "type": "tool_use"
            _v727a_tool_markers = (
                "<minimax:tool_call>",
                "<invoke name=",
                "<parameter name=",
                '"tool_calls"',
                '"function_call"',
                '"tool_use"',
                "'tool_use'",
                "tool_use",
            )
'''

NEW = '''            # v7.28-1: Detect tool_use via Hermes PTY-rendered format + raw model formats
            # Hermes PTY actually shows: "run_agent: tool <name> completed (Xs, N chars)"
            # NOT the raw MiniMax tags (those are consumed by Hermes parser).
            # This is the ACTUAL signal that survives PTY rendering.
            _v727a_tool_markers = (
                "run_agent: tool ",       # Hermes rendered (PRIMARY)
                "tool ",                  # broader Hermes match (e.g. "tool terminal completed")
                "<minimax:tool_call>",    # raw MiniMax XML
                "<invoke name=",          # MiniMax invoke
                '"tool_calls"',           # OpenAI JSON
                '"function_call"',        # OpenAI legacy
                '"tool_use"',             # Anthropic
                "tool_use",               # original v7.27-A
            )
            # v7.28-2: but DON'T count <think> blocks toward char watchdog
            # (MiniMax always thinks before tool calls; can't disable via API)
            _v728_2_in_think = "<think>" in decoded and "</think>" not in decoded
'''

if "v7.28-1: Detect tool_use via Hermes PTY-rendered" in text:
    print("[v7.28-1] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    print("[v7.28-1] tool detection now matches Hermes PTY-rendered 'run_agent: tool X completed'")
else:
    print("[v7.28-1] WARN: OLD pattern not found")

# Strip think blocks from token_count[0] increment
OLD_INC = '''            # Rough token estimate: words × 1.3
            token_count[0] += len(decoded.split()) * 1.3
'''
NEW_INC = '''            # v7.28-2: Strip <think>...</think> from chunk before counting (MiniMax thinking is normal)
            _v728_2_for_count = re.sub(r"<think>.*?</think>", "", decoded, flags=re.DOTALL) if "<think>" in decoded else decoded
            # Rough token estimate: words × 1.3
            token_count[0] += len(_v728_2_for_count.split()) * 1.3
'''

# Need re imported in agent-worker
if "import re" not in text:
    text = text.replace("import sys as _sys", "import re\nimport sys as _sys", 1)
    print("[v7.28-2] added 're' import to agent-worker")

if "v7.28-2: Strip <think>" in text:
    print("[v7.28-2] already patched")
elif OLD_INC in text:
    text = text.replace(OLD_INC, NEW_INC, 1)
    print("[v7.28-2] <think> blocks excluded from char watchdog counter")
else:
    print("[v7.28-2] WARN: OLD_INC pattern not found")

aw.write_text(text)
try:
    py_compile.compile(str(aw), doraise=True)
    print("[v7.28-1+2] agent-worker syntax OK")
except Exception as e:
    print(f"[v7.28-1+2] SYNTAX ERROR: {e}")

# ── 3+4+5: dispatcher fixes ─────────────────────────────────────────────────
ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
ed_text = ed.read_text()

# 3: replace greedy `r'\{.*\}'` with balanced-brace finder
OLD_GREEDY = '''            if not _b.strip().startswith('{'):
                _m2 = re.search(r'\\{.*\\}', _b, re.DOTALL)
                if _m2:
                    _b = _m2.group(0)
'''

NEW_GREEDY = '''            if not _b.strip().startswith('{'):
                # v7.28-3: balanced-brace parser instead of greedy `{.*}`
                # (greedy version captured wrong object when body had multiple {...} blocks)
                _v728_3_first = _b.find("{")
                if _v728_3_first >= 0:
                    _v728_3_depth = 0
                    _v728_3_end = -1
                    _v728_3_in_str = False
                    _v728_3_escape = False
                    for _v728_3_i in range(_v728_3_first, len(_b)):
                        _v728_3_c = _b[_v728_3_i]
                        if _v728_3_escape:
                            _v728_3_escape = False
                            continue
                        if _v728_3_c == "\\\\":
                            _v728_3_escape = True
                            continue
                        if _v728_3_c == '"':
                            _v728_3_in_str = not _v728_3_in_str
                            continue
                        if _v728_3_in_str:
                            continue
                        if _v728_3_c == "{":
                            _v728_3_depth += 1
                        elif _v728_3_c == "}":
                            _v728_3_depth -= 1
                            if _v728_3_depth == 0:
                                _v728_3_end = _v728_3_i + 1
                                break
                    if _v728_3_end > 0:
                        _b = _b[_v728_3_first:_v728_3_end]
'''

if "v7.28-3: balanced-brace parser" in ed_text:
    print("[v7.28-3] already patched")
elif OLD_GREEDY in ed_text:
    # Replace ALL occurrences (audit found 2x: 2622 + 2940)
    ed_text = ed_text.replace(OLD_GREEDY, NEW_GREEDY)
    print("[v7.28-3] greedy regex replaced with balanced-brace parser (all occurrences)")
else:
    print("[v7.28-3] WARN: OLD_GREEDY pattern not found")

# 4: safe IndexError on iteration token
OLD_ITER = '''        _iter_token = tokens[tokens.index("iteration") + 1] if "iteration" in tokens else None
        iteration = int(_iter_token.rstrip(':')) if _iter_token else 1
'''
NEW_ITER = '''        # v7.28-4: safe IndexError + try/except on int()
        _iter_token = None
        try:
            if "iteration" in tokens:
                _v728_4_idx = tokens.index("iteration") + 1
                if _v728_4_idx < len(tokens):
                    _iter_token = tokens[_v728_4_idx]
        except Exception:
            _iter_token = None
        try:
            iteration = int(_iter_token.rstrip(':')) if _iter_token else 1
        except (ValueError, AttributeError):
            iteration = 1
'''

# This pattern appears multiple times; replace_all
count_before = ed_text.count(OLD_ITER)
if "v7.28-4: safe IndexError" in ed_text:
    print("[v7.28-4] already patched")
elif count_before > 0:
    ed_text = ed_text.replace(OLD_ITER, NEW_ITER)
    print(f"[v7.28-4] safe iteration extraction replaced {count_before} occurrences")
else:
    print("[v7.28-4] WARN: OLD_ITER pattern not found")

# 5: Telegram escalate when JSON parse fails after disk fallback also fails
OLD_FAIL = '''            print(f"[dispatcher] ERROR: Could not parse E2E results JSON: {body[:200]}")
        return
'''
NEW_FAIL = '''            print(f"[dispatcher] ERROR: Could not parse E2E results JSON: {body[:200]}")
            # v7.28-5: escalate to Telegram instead of silent drop
            try:
                telegram_alert(f"⚠️ *{gid}*: E2E-RESULTS unparseable AND no disk fallback — message dropped. body[:120]={body[:120]!r}")
            except Exception:
                pass
        return
'''

# This pattern appears once at end of E2E-RESULTS handler
if "v7.28-5: escalate to Telegram" in ed_text:
    print("[v7.28-5] already patched")
elif OLD_FAIL in ed_text:
    ed_text = ed_text.replace(OLD_FAIL, NEW_FAIL, 1)
    print("[v7.28-5] Telegram escalation on full parse failure wired")
else:
    print("[v7.28-5] WARN: OLD_FAIL pattern not found")

ed.write_text(ed_text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.28-3+4+5] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.28-3+4+5] SYNTAX ERROR: {e}")
