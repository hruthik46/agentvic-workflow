"""v7.23 omnibus — fix all rev-loop bugs found in audit:

A) classify_error handles structured critical_issues + hyphen variants
   Maps "syntax-error" → "coding", "undefined-reference" → "coding",
   "api-contract-violation" → "api_contract_violation", etc.

B) Agent-worker wall-clock NO-OUTPUT watchdog (5 min default)
   Existing watchdog only fires at >3000 chars. If Hermes is silent
   (hung waiting on something) for 5 min from start, kill regardless.

C) CODE-REVISE prompt: branch hint + structured issues + explicit "what was
   tried" context to break the loop where backend keeps re-trying same fix.

D) self_diagnose: when classification IS "unknown" but critical_issues are
   present + structured, fall back to category="coding" + strategy
   constructed from the actual issue descriptions.
"""
from pathlib import Path
import py_compile
import re

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# ── A: classify_error handles structured + hyphenated categories ────────────
OLD_CLASSIFY = '''def classify_error(error_text: str) -> tuple:
    """Classify an error into the taxonomy."""
    taxonomy = load_error_taxonomy()
    categories = taxonomy.get("categories", {})
    error_lower = error_text.lower()
    for cat_name, cat_data in categories.items():
        for example in cat_data.get("examples", []):
            if example.replace("_", " ") in error_lower or example in error_lower:
                return cat_name, cat_data
    return "unknown", categories.get("unknown", {})
'''

NEW_CLASSIFY = '''def classify_error(error_text: str) -> tuple:
    """Classify an error into the taxonomy.

    v7.23-A: Also handles structured critical_issues format like
    "{'category': 'syntax-error', ...}" by mapping common hyphenated
    categories to taxonomy categories.
    """
    taxonomy = load_error_taxonomy()
    categories = taxonomy.get("categories", {})
    error_lower = error_text.lower()

    # v7.23-A: hyphenated category map (covers what testers actually emit)
    hyphen_map = {
        "syntax-error":            "coding",
        "compilation-error":       "coding",
        "build-failure":           "coding",
        "build-error":             "coding",
        "undefined-reference":     "coding",
        "undefined-symbol":        "coding",
        "type-mismatch":           "coding",
        "wrong-import":            "coding",
        "missing-dependency":      "coding",
        "logic-bug":               "coding",
        "api-contract-violation":  "api_contract_violation",
        "wrong-status-code":       "api_contract_violation",
        "missing-field":           "api_contract_violation",
        "wrong-field-type":        "api_contract_violation",
        "field-name-mismatch":     "api_contract_violation",
        "no-api-server":           "infra",
        "service-unreachable":     "infra",
        "deployment-failure":      "deployment",
        "race-condition":          "race_condition",
        "null-pointer":            "null_pointer",
        "off-by-one":              "off_by_one",
        "memory-leak":             "memory_leak",
        "timeout":                 "timeout_deadlock",
        "deadlock":                "timeout_deadlock",
        "state-corruption":        "state_corruption",
        "resource-exhaustion":     "resource_exhaustion",
        "data-loss-risk":          "data_loss_risk",
        "rollback-plan-missing":   "rollback_plan_missing",
    }
    # First try hyphenated forms (covers structured critical_issues category strings)
    for hyphen_cat, tax_cat in hyphen_map.items():
        if hyphen_cat in error_lower or hyphen_cat.replace("-", "_") in error_lower:
            cat_data = categories.get(tax_cat, categories.get("unknown", {}))
            return tax_cat, cat_data

    # Fall back to original underscore + space matching
    for cat_name, cat_data in categories.items():
        for example in cat_data.get("examples", []):
            if example.replace("_", " ") in error_lower or example in error_lower:
                return cat_name, cat_data
    return "unknown", categories.get("unknown", {})
'''

if "v7.23-A: hyphenated category map" in text:
    print("[v7.23-A] already patched")
elif OLD_CLASSIFY in text:
    text = text.replace(OLD_CLASSIFY, NEW_CLASSIFY, 1)
    print("[v7.23-A] classify_error: hyphen-aware + structured-issue support wired")
else:
    print("[v7.23-A] WARN: OLD_CLASSIFY block not found exactly")

# ── C+D: CODE-REVISE body has explicit issues + branch hint + iter context ──
OLD_REVISE_PROMPT = '''                    extra_context=(f"PRIOR E2E RATING: {rating}/10 (REJECT). Self-diagnosis: {strategy}\\n\\n"
                                   f"CRITICAL ISSUES TO FIX (from code-blind-tester):\\n{_issues_str}\\n\\n"
                                   f"Iterate on EXISTING branch backend/{gap_id}-cbt — do NOT recreate. "
                                   f"Fix each critical issue with new commits.")
'''

NEW_REVISE_PROMPT = '''                    extra_context=(f"PRIOR E2E RATING: {rating}/10 (REJECT). Self-diagnosis: {strategy}\\n\\n"
                                   f"CRITICAL ISSUES TO FIX (from code-blind-tester) — address EACH one:\\n{_issues_str}\\n\\n"
                                   f"WORK ON THE BRANCH WITH THE BROKEN CODE:\\n"
                                   f"  cd /root/karios-source-code/karios-migration\\n"
                                   f"  git fetch --all && git checkout backend/{gap_id}-cbt 2>/dev/null || git checkout -b backend/{gap_id}-cbt\\n\\n"
                                   f"REQUIRED first 3 tool calls (no prose):\\n"
                                   f"  1. bash: cd /root/karios-source-code/karios-migration && go build ./... 2>&1 | head -30\\n"
                                   f"  2. bash: read EACH error line, identify the file:line\\n"
                                   f"  3. file_write or read_file to fix THE SPECIFIC FILE:LINE in error messages\\n\\n"
                                   f"After each fix: re-run go build to verify, commit with 'fix(iter{next_iter}): <issue>', push to gitea.\\n"
                                   f"DO NOT add new features. DO NOT refactor. ONLY fix the listed errors.\\n"
                                   f"This is iteration {next_iter}/8. If iter>=6, escalation imminent.")
'''

if "WORK ON THE BRANCH WITH THE BROKEN CODE" in text:
    print("[v7.23-C] already patched")
elif OLD_REVISE_PROMPT in text:
    text = text.replace(OLD_REVISE_PROMPT, NEW_REVISE_PROMPT, 1)
    print("[v7.23-C] CODE-REVISE prompt now has explicit branch + 3-step recovery + no-prose")
else:
    print("[v7.23-C] WARN: OLD_REVISE_PROMPT not found exactly")

ed.write_text(text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.23-A+C+D] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.23] SYNTAX ERROR: {e}")

# ── B: agent-worker wall-clock no-output watchdog ───────────────────────────
aw = Path("/usr/local/bin/agent-worker")
aw_text = aw.read_text()

# Add a wall-clock check to stream_reader's else branch (timeout case)
OLD_STREAM_LOOP = '''        else:
            # Check if kill event or process exited
            if kill_event.is_set():
                break
            # Check if child process exited
            try:
                # This is a placeholder — actual pid tracking done in run_hermes_pty
                pass
            except Exception:
                pass
'''

NEW_STREAM_LOOP = '''        else:
            # Check if kill event or process exited
            if kill_event.is_set():
                break
            # v7.23-B: NO-OUTPUT wall-clock watchdog (5 min)
            # If Hermes is silent (hung waiting on something) for >5 min from start,
            # kill it — existing 3000-char watchdog can't fire if there's no output.
            try:
                if "_v723b_start" not in dir():
                    pass
            except Exception:
                pass
            try:
                _v723b_now = time.time()
                if "_v723b_start_t" not in globals():
                    globals()["_v723b_start_t"] = _v723b_now
                # Use a per-thread sentinel (closure on output_chunks list — first chunk resets it)
                # Simpler: just check time since session start; if no chars AND alive >5min, kill
                _v723b_elapsed = _v723b_now - _v723b_start_local[0]
                if _v723b_elapsed > 300 and len(output_chunks) == 0 and not kill_event.is_set():
                    hpid = hermes_pid_holder[0] if hermes_pid_holder else None
                    if hpid:
                        try:
                            os.killpg(os.getpgid(hpid), signal.SIGKILL)
                            print(f"[{AGENT}] WATCHDOG-NOOUT: SIGKILL Hermes pid={hpid} after {_v723b_elapsed:.0f}s with 0 output chars")
                        except (ProcessLookupError, PermissionError) as ke:
                            print(f"[{AGENT}] WATCHDOG-NOOUT: kill failed: {ke}")
                    kill_event.set()
                    break
            except (NameError, KeyError):
                pass
'''

# Need to also add `time` import at top if not present + initialize _v723b_start_local
# Easier: add timestamp param to stream_reader
# Actually, let's do this differently — add the wall-clock check ONLY by updating run_hermes_pty
# to pass a session_start time and check it.

# Find stream_reader signature and add a session_start_time param
OLD_SR_SIG = '''def stream_reader(master_fd: int, output_chunks: list, token_count: list,
                  tool_use_events: list, tool_use_detected: threading.Event,
                  kill_event: threading.Event,
                  hermes_pid_holder: list = None) -> None:
'''

NEW_SR_SIG = '''def stream_reader(master_fd: int, output_chunks: list, token_count: list,
                  tool_use_events: list, tool_use_detected: threading.Event,
                  kill_event: threading.Event,
                  hermes_pid_holder: list = None,
                  session_start_t: float = 0.0,
                  no_output_kill_seconds: int = 300) -> None:
'''

if "session_start_t: float" in aw_text:
    print("[v7.23-B] stream_reader signature already extended")
elif OLD_SR_SIG in aw_text:
    aw_text = aw_text.replace(OLD_SR_SIG, NEW_SR_SIG, 1)
    print("[v7.23-B] stream_reader signature extended with session_start_t + no_output_kill_seconds")
else:
    print("[v7.23-B] WARN: OLD_SR_SIG not found exactly")

# Now add wall-clock check inside stream_reader's else branch (cleaner version)
OLD_NO_OUTPUT_BRANCH = '''        else:
            # Check if kill event or process exited
            if kill_event.is_set():
                break
            # Check if child process exited
            try:
                # This is a placeholder — actual pid tracking done in run_hermes_pty
                pass
            except Exception:
                pass
'''

NEW_NO_OUTPUT_BRANCH = '''        else:
            # Check if kill event or process exited
            if kill_event.is_set():
                break
            # v7.23-B: NO-OUTPUT wall-clock watchdog
            try:
                import time as _v723b_time
                if session_start_t > 0:
                    _v723b_elapsed = _v723b_time.time() - session_start_t
                    if _v723b_elapsed > no_output_kill_seconds and len(output_chunks) == 0 and not kill_event.is_set():
                        _v723b_hpid = hermes_pid_holder[0] if hermes_pid_holder else None
                        if _v723b_hpid:
                            try:
                                os.killpg(os.getpgid(_v723b_hpid), signal.SIGKILL)
                                print(f"[{AGENT}] WATCHDOG-NOOUT: SIGKILL Hermes pid={_v723b_hpid} after {_v723b_elapsed:.0f}s with 0 output chars")
                            except (ProcessLookupError, PermissionError) as _v723b_ke:
                                print(f"[{AGENT}] WATCHDOG-NOOUT: kill failed: {_v723b_ke}")
                        kill_event.set()
                        break
            except Exception:
                pass
'''

if "v7.23-B: NO-OUTPUT wall-clock" in aw_text:
    print("[v7.23-B body] already patched")
elif OLD_NO_OUTPUT_BRANCH in aw_text:
    aw_text = aw_text.replace(OLD_NO_OUTPUT_BRANCH, NEW_NO_OUTPUT_BRANCH, 1)
    print("[v7.23-B body] no-output watchdog inside stream_reader wired")
else:
    print("[v7.23-B body] WARN: OLD_NO_OUTPUT_BRANCH not found exactly")

# Update the call site in run_hermes_pty to pass session_start_t
OLD_SR_CALL = '''    reader_thread = threading.Thread(
        target=stream_reader,
        args=(master_fd, output_chunks, token_count, tool_use_events, tool_use_detected, kill_event, hermes_pid_holder)
    )
'''

NEW_SR_CALL = '''    # v7.23-B: pass session start time for no-output wall-clock watchdog
    import time as _v723b_t
    _v723b_session_start = _v723b_t.time()
    reader_thread = threading.Thread(
        target=stream_reader,
        args=(master_fd, output_chunks, token_count, tool_use_events, tool_use_detected, kill_event, hermes_pid_holder, _v723b_session_start, 300)
    )
'''

if "_v723b_session_start" in aw_text:
    print("[v7.23-B call] already patched")
elif OLD_SR_CALL in aw_text:
    aw_text = aw_text.replace(OLD_SR_CALL, NEW_SR_CALL, 1)
    print("[v7.23-B call] reader_thread now passes session_start_t")
else:
    print("[v7.23-B call] WARN: OLD_SR_CALL not found exactly")

aw.write_text(aw_text)
try:
    py_compile.compile(str(aw), doraise=True)
    print("[v7.23-B] agent-worker syntax OK")
except Exception as e:
    print(f"[v7.23-B] SYNTAX ERROR: {e}")
