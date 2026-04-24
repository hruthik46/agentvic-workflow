# Gate Fixtures (R-4)

Structural discipline: every pipeline gate ships with positive and negative
fixtures and a test that runs them. Prevents silent always-fail gates (the
`d.get(error)` NameError class found during ARCH-IT-091).

Reference: [[kairos-pipeline-structural-audit-2026-04-24]] R-4.

## Run everything

```
bash /root/agentic-workflow/pipeline/gates/run-all-gate-tests.sh
```

Exit 0 = all fixtures matched expected outcome. Non-zero = at least one gate's
logic diverged from its fixtures — either the gate is broken or the fixture is
stale; whoever changed the gate must fix one or the other.

## Gates covered today

| Gate | Fixtures | Test runner |
|------|---------:|-------------|
| R-6 pre-commit (conflict-marker rejection) | 7 (4 positive, 3 negative) | `git-hooks/test.sh` |
| v7.50 arch-review evidence gate (`_v750_gate_arch`) | 3 (1 positive, 2 negative) | `gates/test_v7_50.py` |
| v7.50 e2e evidence gate (`_v750_gate_e2e`) | 5 (2 positive, 3 negative) | `gates/test_v7_50.py` |

## Adding a fixture for a new gate

1. Identify a pure function in the gate: takes input, returns pass/fail (+ reason).
   If the gate is not pure, refactor until the decision logic is. Avoid testing
   gates that require a full Redis/Hermes runtime.
2. Create `gates/<gate_name>_fixtures/` directory.
3. For each fixture, write a JSON file with:
   ```
   {
     "gate": "<function_name>",
     "description": "one-sentence intent",
     "input": { ... the object passed to the gate ... },
     "expected": {"pass": true}
   }
   ```
   Or for negative fixtures:
   ```
   {
     "gate": "<function_name>",
     "description": "why this must fail",
     "input": { ... },
     "expected": {"pass": false, "reason_substring": "missing"}
   }
   ```
4. Write a test runner at `gates/test_<gate_name>.py` modeled on `test_v7_50.py`.
   The runner should extract the gate from the live source file via AST
   (not re-implement it — that defeats the purpose).
5. Add a line to `run-all-gate-tests.sh` that invokes the new runner.
6. Run `run-all-gate-tests.sh` to confirm everything still passes.

## Why fixtures run against the LIVE source, not a copy

The v7.50 test harness AST-extracts the gate functions directly from
`/var/lib/karios/orchestrator/event_dispatcher.py` (the running dispatcher).
This is deliberate: if the dispatcher diverges from source (as we discovered
during R-1.2 — 24 versions of drift), fixtures run against a copy would lie
about the real behavior. Extract from what's actually running.

## Known gaps (future work)

- Devops analytics smoke gate (lives inline in `/root/.hermes/profiles/devops/SOUL.md`
  as bash + Python-inside-heredoc; extracting it requires decomposing the SOUL.md
  prompt, out of scope for this pilot).
- v8.0-A escalation gate + v8.0-B convergence detector (need to locate equivalent
  logic in the running dispatcher after the 24-version reconciliation and fixture
  them).
- Other ~15 sanitizer / drop-if stages in `parse_message()`.
