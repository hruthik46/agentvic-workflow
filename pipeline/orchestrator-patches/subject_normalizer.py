"""v7.18 subject normalizer — converts wrong-subject [COMPLETE] from testers
into proper [E2E-RESULTS] / [TEST-RESULTS] envelopes for the dispatcher to
process.

Wired into event_dispatcher.py [COMPLETE] handler. Triggered when:
  - sender ∈ {code-blind-tester, tester}
  - active gap phase ∈ {3-coding, 3-e2e-review, 4-testing, 4-production-test}

Behaviour:
  1. Look for latest results JSON on disk for this gap:
     - code-blind-tester → e2e-results.json
     - tester           → test-results.json
  2. If found and JSON has 'rating' field → emit as proper subject
  3. If absent or no rating → synthesize honest REJECT rating=1 with reason
     "agent emitted [COMPLETE] without producing results JSON"
     (NOT a fake pass — surfaces the failure to the rev-loop)

Result: the orchestrator's existing handle_e2e_results / handle_test_results
runs the rev-loop normally instead of stalling.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any


SUBJECT_BY_AGENT: Dict[str, str] = {
    "code-blind-tester": "[E2E-RESULTS]",
    "tester":            "[TEST-RESULTS]",
}

RESULTS_FILE_BY_AGENT: Dict[str, str] = {
    "code-blind-tester": "e2e-results.json",
    "tester":            "test-results.json",
}

# Phase contexts where [COMPLETE] from a tester should be rewritten
TESTING_PHASES = {"3-coding", "3-e2e-review", "4-testing", "4-production-test", "phase-4-testing"}

ITERATION_TRACKER_ROOT = Path("/var/lib/karios/iteration-tracker")


def _find_latest_results_file(gap_id: str, results_filename: str) -> Optional[Path]:
    """Return the most recent e2e-results.json or test-results.json under
    iteration-tracker/<gap>/ regardless of which phase-N-* / iteration-M dir
    it landed in. None if not found.
    """
    gap_root = ITERATION_TRACKER_ROOT / gap_id
    if not gap_root.exists():
        return None
    candidates = list(gap_root.rglob(results_filename))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _parse_results(path: Path) -> Optional[Dict[str, Any]]:
    """Try strict JSON parse; fall back to extracting first {...} block."""
    try:
        return json.loads(path.read_text())
    except Exception:
        pass
    try:
        text = path.read_text()
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start:end + 1])
    except Exception:
        pass
    return None


def maybe_normalize_complete(sender: str, gap_id: str, active_phase: str,
                              iteration: int, trace_id: str = "") -> Optional[Dict[str, Any]]:
    """Decide whether this [COMPLETE] from a tester should be rewritten to
    a results envelope. Returns dict {subject, body, source} or None to
    leave the [COMPLETE] alone.
    """
    if sender not in SUBJECT_BY_AGENT:
        return None
    # Phase context check (tolerant — also fires if active_phase is empty/idle
    # but the previous phase was a testing phase; the orchestrator passes the
    # phase BEFORE the [COMPLETE] transition)
    if active_phase and active_phase not in TESTING_PHASES and "test" not in active_phase.lower():
        return None

    target_subject = SUBJECT_BY_AGENT[sender]
    results_filename = RESULTS_FILE_BY_AGENT[sender]
    results_path = _find_latest_results_file(gap_id, results_filename)

    if results_path:
        parsed = _parse_results(results_path)
        if parsed and "rating" in parsed:
            # Found honest results on disk — use them
            body = json.dumps(parsed)
            return {
                "subject": f"{target_subject} {gap_id} iteration {iteration}",
                "body": body,
                "source": f"normalized from [COMPLETE] using {results_path}",
            }

    # No results on disk OR no rating field → honest REJECT rating=1 stub
    stub = {
        "gap_id": gap_id,
        "iteration": iteration,
        "rating": 1,
        "recommendation": "REJECT",
        "summary": (f"Agent {sender} emitted [COMPLETE] without producing "
                    f"{results_filename}. Treated as honest fail (not a fake pass) "
                    f"— routes back to backend for code-revise."),
        "critical_issues": [
            f"NO_RESULTS_FILE: {sender} did not write {results_filename} "
            f"to iteration-tracker/{gap_id}/. Subject normalizer auto-rejected.",
        ],
        "dimensions": {
            "functional_correctness": 0, "edge_cases": 0, "security": 0,
            "performance": 0, "concurrency": 0, "resilience": 0, "error_handling": 0,
        },
        "evidence": {},
        "trace_id": trace_id,
        "synthesized_by": "v7.18-subject-normalizer",
        "synthesized_at": int(time.time()),
    }
    return {
        "subject": f"{target_subject} {gap_id} iteration {iteration}",
        "body": json.dumps(stub),
        "source": "synthesized REJECT (no results JSON on disk)",
    }
