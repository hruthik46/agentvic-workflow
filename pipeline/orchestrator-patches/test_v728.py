"""Immediate verification test for v7.28 patches."""
import re

# Test 1: tool detection markers — mirror what's in agent-worker after v7.28
markers = (
    "run_agent: tool ",
    "tool ",
    "<minimax:tool_call>",
    "<invoke name=",
    '"tool_calls"',
    '"function_call"',
    '"tool_use"',
    "tool_use",
)

samples = [
    ("<think>Let me reason through this complex problem step by step. " * 30 + "</think>",
     "thinking-only", False),
    ("2026-04-20 INFO run_agent: tool terminal completed (0.24s, 102 chars)",
     "hermes-tool-completed", True),
    ("Now I will analyze the output from the previous command. " * 50,
     "prose-only", False),
    ("<minimax:tool_call><invoke name=\"file_write\"><parameter name=\"path\">a</parameter></invoke></minimax:tool_call>",
     "raw-minimax-format", True),
]

print("=== TEST 1: tool_use detection ===")
for chunk, label, expect_detect in samples:
    detected = any(m in chunk for m in markers)
    status = "PASS" if detected == expect_detect else "FAIL"
    print(f"  [{status}] {label}: detected={detected} (expected={expect_detect})")

print()
print("=== TEST 2: <think> filter for char counter ===")
for chunk, label, _ in samples:
    raw_chars = len(chunk)
    counted = re.sub(r"<think>.*?</think>", "", chunk, flags=re.DOTALL) if "<think>" in chunk else chunk
    counted_chars = len(counted)
    saved = raw_chars - counted_chars
    print(f"  [{label}] raw={raw_chars} after_think_strip={counted_chars} (saved={saved})")

print()
print("=== TEST 3: balanced-brace JSON parser (CRITICAL #1 fix) ===")

def extract_balanced_json(b: str):
    first = b.find("{")
    if first < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(first, len(b)):
        c = b[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return b[first:i+1]
    return None

cases = [
    ('Estimated cost: {"type": "money", "amount": 5000} {"rating": 4, "recommendation": "REJECT"}',
     '{"type": "money", "amount": 5000}'),
    ('{"rating": 8, "summary": "all good"}',
     '{"rating": 8, "summary": "all good"}'),
    ('Some prose then {"nested": {"x": 1, "y": [1,2,3]}, "rating": 9}',
     '{"nested": {"x": 1, "y": [1,2,3]}, "rating": 9}'),
    ('No braces here', None),
]
for body, expected in cases:
    got = extract_balanced_json(body)
    status = "PASS" if got == expected else "FAIL"
    print(f"  [{status}] body[:60]={body[:60]!r}")
    print(f"           got=     {got!r}")
    print(f"           expect=  {expected!r}")

print()
print("=== TEST 4: safe iteration extraction (CRITICAL #3 fix) ===")
def safe_iter(tokens):
    _iter_token = None
    try:
        if "iteration" in tokens:
            idx = tokens.index("iteration") + 1
            if idx < len(tokens):
                _iter_token = tokens[idx]
    except Exception:
        _iter_token = None
    try:
        return int(_iter_token.rstrip(":")) if _iter_token else 1
    except (ValueError, AttributeError):
        return 1

iter_cases = [
    (["GAP-1", "iteration", "5"], 5),
    (["GAP-1", "iteration"], 1),                     # truncated — used to crash
    (["GAP-1", "iteration", "abc"], 1),              # non-numeric — used to crash
    (["GAP-1"], 1),                                  # no iteration token
    (["GAP-1", "iteration", "5:"], 5),               # trailing colon
    ([], 1),                                          # empty
]
for toks, expected in iter_cases:
    got = safe_iter(toks)
    status = "PASS" if got == expected else "FAIL"
    print(f"  [{status}] tokens={toks} → iter={got} (expected={expected})")
