#!/usr/bin/env python3
'''R-4 fixture runner for v7.50 live-probe / real-env-probe gates.

Extracts the gate functions from /var/lib/karios/orchestrator/event_dispatcher.py
via AST (no full-module import — the dispatcher has heavy init side effects),
runs them against JSON fixtures. Positive fixtures expect pass=True; negative
fixtures expect pass=False AND a reason containing reason_substring.
'''

import ast
import json
import os
import sys

DISPATCHER = '/var/lib/karios/orchestrator/event_dispatcher.py'
FIXTURES_DIR = '/root/agentic-workflow/pipeline/gates/v7_50_fixtures'
TARGET_NAMES = {'_v750_gate_arch', '_v750_gate_e2e',
                'REAL_ENV_PROBE_MIN_ARCH', 'REAL_ENV_PROBE_MIN_E2E'}


def extract_targets(source_path):
    with open(source_path) as f:
        src = f.read()
    tree = ast.parse(src)
    chunks = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_NAMES:
            chunks.append(ast.get_source_segment(src, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in TARGET_NAMES:
                    chunks.append(ast.get_source_segment(src, node))
    return '\n\n'.join(chunks)


def main():
    if not os.path.exists(DISPATCHER):
        print(f'FATAL: dispatcher not found at {DISPATCHER}')
        return 2

    extracted = extract_targets(DISPATCHER)
    if not extracted:
        print('FATAL: could not extract v7.50 targets from dispatcher')
        return 2

    ns = {}
    exec(extracted, ns)

    passes, fails = 0, 0
    for fname in sorted(os.listdir(FIXTURES_DIR)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(FIXTURES_DIR, fname)
        with open(fpath) as f:
            fixture = json.load(f)

        gate_name = fixture.get('gate')
        fn = ns.get(gate_name)
        if fn is None:
            print(f'  SKIP {fname}: gate {gate_name!r} not found')
            continue

        review = fixture['input']
        expected = fixture['expected']
        actual_pass, actual_reason = fn(review)

        ok = (actual_pass == expected['pass'])
        if not expected['pass'] and 'reason_substring' in expected:
            ok = ok and (expected['reason_substring'] in actual_reason)

        if ok:
            print(f'  OK   {fname} ({gate_name} -> pass={actual_pass})')
            passes += 1
        else:
            print(f'  FAIL {fname} ({gate_name}): expected pass={expected["pass"]} '
                  f'reason~={expected.get("reason_substring", "<any>")!r}, '
                  f'got pass={actual_pass} reason={actual_reason!r}')
            fails += 1

    print(f'\n=== summary: {passes} pass, {fails} fail ===')
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
