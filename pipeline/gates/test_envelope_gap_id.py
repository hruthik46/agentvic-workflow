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
      FIRST assignment to the name gap_id (traversal is depth-first via
      ast.iter_child_nodes: sibling statements are visited in source order,
      but the walk descends into nested blocks — if/try/for — before
      continuing past their parent. In the current dispatcher the first
      gap_id assignment is at top-level of parse_message so DFS and source
      order agree; if a future change inserts "if cond: gap_id = ..." BEFORE
      the envelope read, DFS would report the nested assignment as first.
      Upgrade to a source-order walk if that class of regression matters.)
      Assert its RHS contains a data.get("gap_id") call. Catches regressions
      where someone reorders parse_message to parse subject/body prose
      BEFORE reading the envelope (which would reintroduce the Theme 1
      prose-parsing pathology).

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


HANDLER_BEGIN_MARKER = 'R-3-GATE: handler-gid-resolve-begin'
HANDLER_END_MARKER = 'R-3-GATE: handler-gid-resolve-end'


def extract_handler_resolver(source_path):
    """Extract the [CODING-COMPLETE]/[FAN-IN] handler's gid-resolution block from
    the live dispatcher (delimited by R-3-GATE markers) and return Python source
    for a callable `_handler_resolve(subject, body, gap_id, _GAP_ID_RE) -> gid`.
    The block is at 8-space indent inside parse_message's handler; we dedent to
    4 spaces so it sits inside our wrapper function."""
    with open(source_path) as f:
        lines = f.read().splitlines()
    begin_idx = end_idx = None
    for i, line in enumerate(lines):
        if HANDLER_BEGIN_MARKER in line:
            begin_idx = i + 1
        elif HANDLER_END_MARKER in line:
            end_idx = i
            break
    if begin_idx is None or end_idx is None:
        raise RuntimeError('R-3-GATE markers not found in dispatcher (refactor without updating gate?)')
    body_lines = lines[begin_idx:end_idx]
    dedented = []
    for ln in body_lines:
        if ln.startswith('        '):
            dedented.append('    ' + ln[8:])
        elif ln.strip() == '':
            dedented.append(ln)
        else:
            raise RuntimeError(f'unexpected indent in handler block: {ln!r}')
    return (
        'def _handler_resolve(subject, body, gap_id, _GAP_ID_RE):\n'
        + '\n'.join(dedented)
        + '\n    return gid\n'
    )


FILEINBOX_BEGIN_MARKER = 'R-3-GATE: file-inbox-envelope-promote-begin'
FILEINBOX_END_MARKER = 'R-3-GATE: file-inbox-envelope-promote-end'

REDISINBOX_BEGIN_MARKER = 'R-3-GATE: redis-inbox-envelope-promote-begin'
REDISINBOX_END_MARKER = 'R-3-GATE: redis-inbox-envelope-promote-end'


def extract_fileinbox_promoter(source_path):
    """Extract the _file_inbox_fallback envelope-promotion block delimited by
    R-3-GATE markers and return Python source for a callable
    _fileinbox_promote(subject, data, _GAP_ID_RE) -> envelope_gap_id.
    The block is at 16-space indent inside _file_inbox_fallback (nested in
    try/for/try); dedent 16 to 4 so it runs inside our wrapper function."""
    with open(source_path) as f:
        lines = f.read().splitlines()
    begin_idx = end_idx = None
    for i, line in enumerate(lines):
        if FILEINBOX_BEGIN_MARKER in line:
            begin_idx = i + 1
        elif FILEINBOX_END_MARKER in line:
            end_idx = i
            break
    if begin_idx is None or end_idx is None:
        raise RuntimeError('R-3-GATE file-inbox markers not found in dispatcher')
    body_lines = lines[begin_idx:end_idx]
    dedented = []
    for ln in body_lines:
        if ln.startswith('                '):  # 16 spaces
            dedented.append('    ' + ln[16:])
        elif ln.strip() == '':
            dedented.append(ln)
        else:
            raise RuntimeError(f'unexpected indent in file-inbox block: {ln!r}')
    return (
        'def _fileinbox_promote(subject, data, _GAP_ID_RE):\n'
        + '\n'.join(dedented)
        + '\n    return envelope_gap_id\n'
    )


def run_fileinbox_fixtures(fixtures_dir, gap_re, dispatcher_path):
    """Run fileinbox_*.json fixtures through the extracted promoter.
    Each fixture's input has subject + data (packet dict); expected has
    envelope_gap_id."""
    import tempfile, runpy
    wrapper_src = extract_fileinbox_promoter(dispatcher_path)
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as tf:
        tf.write(wrapper_src)
        tf_path = tf.name
    try:
        ns = runpy.run_path(tf_path)
    finally:
        os.unlink(tf_path)
    promoter = ns['_fileinbox_promote']

    passes, fails = 0, 0
    for fname in sorted(os.listdir(fixtures_dir)):
        if not (fname.startswith('fileinbox_') and fname.endswith('.json')):
            continue
        fpath = os.path.join(fixtures_dir, fname)
        with open(fpath) as f:
            fixture = json.load(f)
        inp = fixture['input']
        expected = fixture['expected']
        got = promoter(inp.get('subject', ''), inp.get('data', {}), gap_re)
        if got == expected.get('envelope_gap_id'):
            print(f'  OK   {fname} ({fixture.get("description", "")[:50]}) -> envelope_gap_id={got!r}')
            passes += 1
        else:
            print(f'  FAIL {fname}: envelope_gap_id: got {got!r}, expected {expected.get("envelope_gap_id")!r}')
            fails += 1
    return passes, fails


def extract_redisinbox_promoter(source_path):
    """Extract the _inbox_fallback envelope-promotion block delimited by
    R-3-GATE markers and return Python source for a callable
    _redisinbox_promote(subject, data, _GAP_ID_RE) -> envelope_gap_id.
    The block is at 12-space indent inside _inbox_fallback (nested in
    try/while); dedent 12 to 4 so it runs inside our wrapper function."""
    with open(source_path) as f:
        lines = f.read().splitlines()
    begin_idx = end_idx = None
    for i, line in enumerate(lines):
        if REDISINBOX_BEGIN_MARKER in line:
            begin_idx = i + 1
        elif REDISINBOX_END_MARKER in line:
            end_idx = i
            break
    if begin_idx is None or end_idx is None:
        raise RuntimeError('R-3-GATE redis-inbox markers not found in dispatcher')
    body_lines = lines[begin_idx:end_idx]
    dedented = []
    for ln in body_lines:
        if ln.startswith('            '):  # 12 spaces
            dedented.append('    ' + ln[12:])
        elif ln.strip() == '':
            dedented.append(ln)
        else:
            raise RuntimeError(f'unexpected indent in redis-inbox block: {ln!r}')
    return (
        'def _redisinbox_promote(subject, data, _GAP_ID_RE):\n'
        + '\n'.join(dedented)
        + '\n    return envelope_gap_id\n'
    )


def run_redisinbox_fixtures(fixtures_dir, gap_re, dispatcher_path):
    """Run redisinbox_*.json fixtures through the extracted promoter.
    Each fixture's input has subject + data (raw redis packet dict);
    expected has envelope_gap_id. Mirrors run_fileinbox_fixtures."""
    import tempfile, runpy
    wrapper_src = extract_redisinbox_promoter(dispatcher_path)
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as tf:
        tf.write(wrapper_src)
        tf_path = tf.name
    try:
        ns = runpy.run_path(tf_path)
    finally:
        os.unlink(tf_path)
    promoter = ns['_redisinbox_promote']

    passes, fails = 0, 0
    for fname in sorted(os.listdir(fixtures_dir)):
        if not (fname.startswith('redisinbox_') and fname.endswith('.json')):
            continue
        fpath = os.path.join(fixtures_dir, fname)
        with open(fpath) as f:
            fixture = json.load(f)
        inp = fixture['input']
        expected = fixture['expected']
        got = promoter(inp.get('subject', ''), inp.get('data', {}), gap_re)
        if got == expected.get('envelope_gap_id'):
            print(f'  OK   {fname} ({fixture.get("description", "")[:50]}) -> envelope_gap_id={got!r}')
            passes += 1
        else:
            print(f'  FAIL {fname}: envelope_gap_id: got {got!r}, expected {expected.get("envelope_gap_id")!r}')
            fails += 1
    return passes, fails


def run_handler_fixtures(fixtures_dir, gap_re, dispatcher_path):
    """Run handler_*.json fixtures through the extracted handler resolver.
    Each fixture's input has subject/body/gap_id; expected has gid. Loads the
    resolver via runpy.run_path so the helper lives in a real module namespace."""
    import tempfile, runpy
    wrapper_src = extract_handler_resolver(dispatcher_path)
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as tf:
        tf.write(wrapper_src)
        tf_path = tf.name
    try:
        ns = runpy.run_path(tf_path)
    finally:
        os.unlink(tf_path)
    resolver = ns['_handler_resolve']

    passes, fails = 0, 0
    for fname in sorted(os.listdir(fixtures_dir)):
        if not (fname.startswith('handler_') and fname.endswith('.json')):
            continue
        fpath = os.path.join(fixtures_dir, fname)
        with open(fpath) as f:
            fixture = json.load(f)
        inp = fixture['input']
        expected = fixture['expected']
        got = resolver(inp.get('subject', ''), inp.get('body', ''), inp.get('gap_id'), gap_re)
        if got == expected.get('gid'):
            print(f'  OK   {fname} ({fixture.get("description", "")[:50]}) -> gid={got!r}')
            passes += 1
        else:
            print(f'  FAIL {fname}: gid: got {got!r}, expected {expected.get("gid")!r}')
            fails += 1
    return passes, fails


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
        if fname.startswith(('handler_', 'fileinbox_', 'redisinbox_')):
            continue  # handler-path + file-inbox fixtures run via their own extractors below
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

    # ── R-3 handler-path coverage: [CODING-COMPLETE]/[FAN-IN] ─────────────
    # Extracts the gid-resolution block delimited by R-3-GATE markers from the
    # live dispatcher, wraps it as a callable, and runs handler_*.json fixtures
    # through it. This backs per-handler retirements that the receive-head gate
    # cannot back on its own (handlers each rebind gid from subject prose).
    h_pass, h_fail = run_handler_fixtures(FIXTURES_DIR, gap_re, DISPATCHER)
    passes += h_pass
    fails += h_fail

    # R-3 Theme 1 session #4 coverage: file-inbox envelope promotion.
    # Exercises the envelope-promote block (inside _file_inbox_fallback, gated
    # by R-3-GATE markers) against fileinbox_*.json fixtures. Backs every
    # retirement whose handler is reachable via the agent-msg file-inbox path,
    # now that file-inbox supplies canonical envelope gap_id.
    fi_pass, fi_fail = run_fileinbox_fixtures(FIXTURES_DIR, gap_re, DISPATCHER)
    passes += fi_pass
    fails += fi_fail

    # R-3 Theme 1 session #5 coverage: redis-inbox envelope promotion.
    # Exercises the envelope-promote block (inside _inbox_fallback, gated
    # by R-3-GATE markers) against redisinbox_*.json fixtures. Backs every
    # retirement whose handler is reachable via the agent-msg Redis path,
    # now that redis-inbox supplies canonical envelope gap_id.
    ri_pass, ri_fail = run_redisinbox_fixtures(FIXTURES_DIR, gap_re, DISPATCHER)
    passes += ri_pass
    fails += ri_fail

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
