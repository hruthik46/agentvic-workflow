"""v7.29 — fix escalation handoff: 'sai' isn't a real agent stream.
Replace `send_to_agent("sai", ...)` with proper telegram + state-freeze pattern.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# Pattern: send_to_agent("sai", subject, body) — wrap in proper telegram + state.json freeze
# Found 3+ occurrences in event_dispatcher.py

# A consistent fix: define a helper escalate_to_human() that does telegram + state freeze
HELPER = '''

def escalate_to_human(gap_id: str, subject: str, body: str, rating=None, iteration=None):
    """v7.29: proper escalation — Telegram alert + state.json freeze.
    Replaces broken send_to_agent('sai', ...) which fails because 'sai' has no stream.
    """
    import json as _v729_j
    from pathlib import Path as _v729_P
    # Telegram alert with full body (truncated to 4096 chars Telegram limit)
    try:
        msg = f"\\U0001F6A8 ESCALATE — {gap_id}\\n{subject}\\n\\n{body[:3500]}"
        telegram_alert(msg)
        print(f"[dispatcher] v7.29 escalate_to_human: Telegram sent for {gap_id}")
    except Exception as _v729_e:
        print(f"[dispatcher] v7.29 telegram failed: {_v729_e}")
    # Freeze state.json so future dispatcher restarts skip this gap
    try:
        sp = _v729_P("/var/lib/karios/orchestrator/state.json")
        st = _v729_j.loads(sp.read_text())
        ag = st.setdefault("active_gaps", {}).setdefault(gap_id, {})
        ag["state"] = "escalated"
        ag["phase"] = "escalated"
        if iteration is not None:
            ag["iteration"] = iteration
        if rating is not None:
            ag["last_rating"] = rating
        ag["escalated_at"] = current_ts()
        ag["escalation_reason"] = subject
        sp.write_text(_v729_j.dumps(st, indent=2))
        print(f"[dispatcher] v7.29 escalate_to_human: state.json frozen for {gap_id}")
    except Exception as _v729_e:
        print(f"[dispatcher] v7.29 state freeze failed: {_v729_e}")

'''

# Insert helper before send_to_agent definition
marker = "# ── Send to Agent (Streams-based) ─────────────────────────────────────────────"
if "def escalate_to_human" in text:
    print("[v7.29] helper already exists")
elif marker in text:
    text = text.replace(marker, HELPER + "\n" + marker, 1)
    print("[v7.29] escalate_to_human helper added")
else:
    print("[v7.29] WARN: marker not found")

# Replace 3 escalation calls with the helper
patterns = [
    # Pattern 1: Architecture rating too low
    ('''        send_to_agent("sai", f"[ESCALATE] {gap_id} — Architecture rating too low",
                      f"Gap {gap_id}: Architecture rating {rating}/10 after {iteration} iteration(s).\\n"
                      f"Threshold: {ROUTING_ESCALATE_NOW}/10.\\n"
                      f"Critical issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues))''',
     '''        escalate_to_human(gap_id, "Architecture rating too low",
                          f"Architecture rating {rating}/10 after {iteration} iteration(s).\\n"
                          f"Threshold: {ROUTING_ESCALATE_NOW}/10.\\n"
                          f"Critical issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues),
                          rating=rating, iteration=iteration)'''),
    # Pattern 2: Architecture exhausted
    ('''            send_to_agent("sai", f"[ESCALATE] {gap_id} — Architecture exhausted",
                          f"Gap {gap_id}: {strategy}\\n"
                          f"Final rating: {rating}/10.\\n"
                          f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues))''',
     '''            escalate_to_human(gap_id, "Architecture exhausted",
                              f"{strategy}\\n"
                              f"Final rating: {rating}/10.\\n"
                              f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues),
                              rating=rating, iteration=iteration)'''),
    # Pattern 3: E2E rating too low
    ('''        send_to_agent("sai", f"[ESCALATE] {gap_id} — E2E rating too low",
                      f"Gap {gap_id}: E2E rating {rating}/10 after {iteration} iteration(s).\\n"
                      f"Threshold: {ROUTING_ESCALATE_NOW}/10.\\n"
                      f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues))''',
     '''        escalate_to_human(gap_id, "E2E rating too low",
                          f"E2E rating {rating}/10 after {iteration} iteration(s).\\n"
                          f"Threshold: {ROUTING_ESCALATE_NOW}/10.\\n"
                          f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues),
                          rating=rating, iteration=iteration)'''),
    # Pattern 4: Coding loop exhausted
    ('''            send_to_agent("sai", f"[ESCALATE] {gap_id} — Coding loop exhausted",
                          f"Gap {gap_id}: {strategy}\\n"
                          f"Final rating: {rating}/10.\\n"
                          f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues))''',
     '''            escalate_to_human(gap_id, "Coding loop exhausted",
                              f"{strategy}\\n"
                              f"Final rating: {rating}/10.\\n"
                              f"Issues:\\n" + "\\n".join(f"- {i}" for i in critical_issues),
                              rating=rating, iteration=iteration)'''),
]

replacements = 0
for old, new in patterns:
    if new[:30] in text:
        continue  # already replaced
    if old in text:
        text = text.replace(old, new, 1)
        replacements += 1

print(f"[v7.29] replaced {replacements}/{len(patterns)} escalation calls")

ed.write_text(text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.29] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.29] SYNTAX ERROR: {e}")
