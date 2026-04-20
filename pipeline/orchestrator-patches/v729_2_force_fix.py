"""Force-fix remaining 2 send_to_agent('sai',...) calls via raw line replacement."""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# Pattern 1 (around line 2095): E2E rating too low
old1 = (
    '        send_to_agent("sai", f"[ESCALATE] {gap_id} — E2E rating too low",\n'
    '                      f"Gap {gap_id}: E2E rating {rating}/10 after {iteration} iteration(s).\\n"\n'
    '                      f"Threshold: {ROUTING_ESCALATE_NOW}/10.\\n"\n'
    '                      f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues))'
)
new1 = (
    '        escalate_to_human(gap_id, "E2E rating too low",\n'
    '                          f"E2E rating {rating}/10 after {iteration} iteration(s).\\n"\n'
    '                          f"Threshold: {ROUTING_ESCALATE_NOW}/10.\\n"\n'
    '                          f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues),\n'
    '                          rating=rating, iteration=iteration)'
)

# Pattern 2 (around line 2196): Coding loop exhausted
old2 = (
    '            send_to_agent("sai", f"[ESCALATE] {gap_id} — Coding loop exhausted",\n'
    '                          f"Gap {gap_id}: {strategy}\\n"\n'
    '                          f"Final rating: {rating}/10.\\n"\n'
    '                          f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues))'
)
new2 = (
    '            escalate_to_human(gap_id, "Coding loop exhausted",\n'
    '                              f"{strategy}\\n"\n'
    '                              f"Final rating: {rating}/10.\\n"\n'
    '                              f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues),\n'
    '                              rating=rating, iteration=iteration)'
)

for old, new, label in [(old1, new1, "E2E rating too low"), (old2, new2, "Coding loop exhausted")]:
    if old in text:
        text = text.replace(old, new, 1)
        print(f"  ✓ replaced: {label}")
    elif new[:50] in text:
        print(f"  - already replaced: {label}")
    else:
        print(f"  ✗ NOT found exactly: {label}")

remaining = text.count('send_to_agent("sai"')
print(f"  remaining send_to_agent(sai) calls: {remaining}")

ed.write_text(text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("  syntax OK")
except Exception as e:
    print(f"  SYNTAX ERROR: {e}")
