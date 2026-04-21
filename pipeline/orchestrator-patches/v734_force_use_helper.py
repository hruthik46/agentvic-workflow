"""v7.34.1 — directly replace _issues_str = "\\n".join(...) with format helper call."""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# Match the exact 5-line block
old = '''            _issues_str = "\\n".join(
                (f"- [{i.get('severity','?')}] {i.get('description', str(i)[:200])}"
                 if isinstance(i, dict) else f"- {i}")
                for i in critical_issues[:10]
            )'''

new = '''            # v7.34.1: ALWAYS use format_critical_issues_for_revise (v7.32 SWE-Bench-style)
            _issues_str = format_critical_issues_for_revise(critical_issues, kind="code")'''

if "v7.34.1: ALWAYS use" in text:
    print("[v7.34.1] already patched")
elif old in text:
    text = text.replace(old, new)  # all occurrences
    ed.write_text(text)
    n = text.count("v7.34.1: ALWAYS use")
    print(f"[v7.34.1] replaced {n} occurrences of OLD _issues_str with v7.32 helper")
else:
    print("[v7.34.1] WARN: OLD pattern not found")

# Same for v7.23.2 INFRA-FIX path
old2 = '''                    _v7232_issues_short = "\\n".join(
                        (f"- [{i.get('severity','?')}] {i.get('description', str(i)[:200])}"
                         if isinstance(i, dict) else f"- {i}")
                        for i in critical_issues[:10]
                    )'''
new2 = '''                    # v7.34.1: detailed format for INFRA-FIX too
                    _v7232_issues_short = format_critical_issues_for_revise(critical_issues, kind="code")'''
if old2 in text:
    text = text.replace(old2, new2)
    ed.write_text(text)
    print("[v7.34.1 infra] also fixed INFRA-FIX path")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.34.1] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.34.1] SYNTAX ERROR: {e}")
