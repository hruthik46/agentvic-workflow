"""v7.21.1 — extract gap_id from trace_id when [E2E-RESULTS] subject has no gap.

Witnessed: agent emits bare '[E2E-RESULTS]' subject, dispatcher rejects.
Fallback: parse trace_id (e.g. 'trace_ARCH_IT_018_unkn_...') for ARCH-IT-NNN
or other GAP-NNN patterns; if not found, look up active in-progress gaps
in state.json and use the one in phase=3-coding/4-testing.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

OLD = '''        if not tokens:
            print(f"[dispatcher] ERROR: [E2E-RESULTS] message has no gap_id in subject: {subject!r}")
            return
        gid = tokens[0]
'''

NEW = '''        if not tokens:
            # v7.21.1: try trace_id pattern then active-gap fallback
            _v721_1_gid = None
            try:
                _v721_1_pat = re.search(r"(ARCH[\\-_]IT[\\-_]\\w+|REQ[\\-_]\\w+|GAP[\\-_]\\w+)", trace_id or "")
                if _v721_1_pat:
                    _v721_1_gid = _v721_1_pat.group(1).replace("_", "-")
            except Exception:
                pass
            if not _v721_1_gid:
                try:
                    _v721_1_state = json.loads(Path("/var/lib/karios/orchestrator/state.json").read_text())
                    _v721_1_active = [k for k, v in _v721_1_state.get("active_gaps", {}).items()
                                      if v.get("state") not in ("completed", "closed", "cancelled", "escalated")
                                      and v.get("phase") in ("3-coding", "phase-3-coding",
                                                              "4-testing", "phase-4-testing",
                                                              "3-coding-sync", "3-coding-testing")]
                    if len(_v721_1_active) == 1:
                        _v721_1_gid = _v721_1_active[0]
                except Exception:
                    pass
            if _v721_1_gid:
                print(f"[dispatcher] v7.21.1 [E2E-RESULTS] no gap in subject — recovered gap_id={_v721_1_gid} (from trace_id or active-gap fallback)")
                gid = _v721_1_gid
                tokens = [gid]
            else:
                print(f"[dispatcher] ERROR: [E2E-RESULTS] message has no gap_id in subject: {subject!r} and trace/state fallback failed")
                return
        else:
            gid = tokens[0]
'''

if "v7.21.1 [E2E-RESULTS] no gap in subject" in text:
    print("[v7.21.1] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.21.1] gap_id extraction fallback wired")
else:
    print("[v7.21.1] WARN: OLD block not found exactly")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.21.1] syntax OK")
except Exception as e:
    print(f"[v7.21.1] SYNTAX ERROR: {e}")
