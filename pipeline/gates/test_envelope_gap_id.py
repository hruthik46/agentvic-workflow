#!/usr/bin/env python3
'''R-3 Theme 1 coverage gate: envelope-first gap_id resolution at dispatcher receive boundary.

Asserts two invariants that back every Theme 1 retirement's unreachability proof:

  (1) Behavioral — for each JSON fixture in envelope_gap_id_fixtures/, feed its
      input dict through a replica of parse_message's envelope resolution
      (gap_id = _sanitize_gap_id(data.get("gap_id"))) and check the resolved
      gap_id + _GAP_ID_RE validity match expected values. Uses AST-extracted
      _sanitize_gap_id and _GAP_ID_RE from the live dispatcher — catches
      regressions in either the sanitizer or the id regex.

  (2) Structural — AST-parse parse_message in the live dispatcher, locate the
      FIRST assignment to the name gap_id, assert its RHS contains a
      data.get("gap_id") call. Catches regressions where someone reorders
      parse_message to parse subject/body prose BEFORE reading the envelope
      (which would reintroduce the Theme 1 prose-parsing pathology).

Together: fixture pass + structural pass = envelope wins over subject prose at
the dispatcher receive boundary. Each R-3 Theme 1 retirement cites this gate's
green state as runtime evidence that the subject-prose-parsing code it removes
is unreachable.
'''

import ast
import json
import os
import re
import sys

DISPATCHER = '/var/lib/karios/orchestrator/event_dispatcher.py'
FIXTURES_DIR = '/root/agentic-workflow/pipeline/gates/envelope_gap_id_fixtures'
TARGET_NAMES = {'_sanitize_gap_id', '_GAP_ID_RE'}


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


def find_parse_message(source_path):
    with open(source_path) as f:
        src = f.read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'parse_message':
            return node
    return None


def rhs_reads_envelope_gap_id(rhs_node):
    '''True iff rhs_node contains a data.get("gap_id", ...) call.'''
    for node in ast.walk(rhs_node):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute)
                    and func.attr == 'get'
                    and isinstance(func.value, ast.Name)
                    and func.value.id == 'data'):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == 'gap_id':
                        return True
    return False


def find_first_gap_id_assign(node):
    '''DFS in source order; return first Assign whose target.id == "gap_id".'''
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'gap_id':
                return node
    for child in ast.iter_child_nodes(node):
        result = find_first_gap_id_assign(child)
        if result is not None:
            return result
    return None


def structural_gate(pm_node):
    '''Return (pass, reason). Pass iff first gap_id assignment in parse_message
    sources from data.get("gap_id").'''
    first = find_first_gap_id_assign(pm_node)
    if first is None:
        return False, 'no gap_id assignment found in parse_message'
    if rhs_reads_envelope_gap_id(first.value):
        return True, 'first gap_id assignment reads data.get("gap_id") envelope field'
    try:
        rhs_repr = ast.unparse(first.value)
    except Exception:
        rhs_repr = '<unparse-failed>'
    return False, f'first gap_id assignment does NOT read data.get("gap_id") envelope: rhs={rhs_repr!r}'


def main():
    if not os.path.exists(DISPATCHER):
        print(f'FATAL: dispatcher not found at {DISPATCHER}')
        return 2

    extracted = extract_targets(DISPATCHER)
    if not extracted:
        print('FATAL: could not extract _sanitize_gap_id / _GAP_ID_RE from dispatcher')
        return 2

    ns = {'re': re}
    exec(extracted, ns)
    sanitize = ns.get('_sanitize_gap_id')
    gap_re = ns.get('_GAP_ID_RE')
    if sanitize is None or gap_re is None:
        print('FATAL: extraction did not yield _sanitize_gap_id and _GAP_ID_RE')
        return 2

    def resolve(data):
        gap_id = sanitize(data.get('gap_id'))
        valid = bool(gap_id and gap_re.match(gap_id))
        return gap_id, valid

    passes, fails = 0, 0

    if not os.path.isdir(FIXTURES_DIR):
        print(f'FATAL: fixtures dir not found at {FIXTURES_DIR}')
        return 2

    for fname in sorted(os.listdir(FIXTURES_DIR)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(FIXTURES_DIR, fname)
        with open(fpath) as f:
            fixture = json.load(f)
        data = fixture['input']
        expected = fixture['expected']
        gap_id, valid = resolve(data)

        ok = True
        reasons = []
        if 'resolved_gap_id' in expected:
            if gap_id != expected['resolved_gap_id']:
                ok = False
                reasons.append(f'resolved_gap_id: got {gap_id!r}, expected {expected["resolved_gap_id"]!r}')
        if 'valid' in expected:
            if valid != expected['valid']:
                ok = False
                reasons.append(f'valid: got {valid}, expected {expected["valid"]}')

        if ok:
            print(f'  OK   {fname} ({fixture.get("description", "")[:50]}) -> gap_id={gap_id!r} valid={valid}')
            passes += 1
        else:
            print(f'  FAIL {fname}: {"; ".join(reasons)}')
            fails += 1

    pm_node = find_parse_message(DISPATCHER)
    if pm_node is None:
        print('  FAIL structural__first_gap_id_is_envelope: parse_message not found in dispatcher')
        fails += 1
    else:
        ok, reason = structural_gate(pm_node)
        if ok:
            print(f'  OK   structural__first_gap_id_is_envelope ({reason})')
            passes += 1
        else:
            print(f'  FAIL structural__first_gap_id_is_envelope: {reason}')
            fails += 1

    print(f'\n=== summary: {passes} pass, {fails} fail ===')
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
