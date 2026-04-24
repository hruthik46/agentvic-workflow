#!/usr/bin/env python3
'''R-4 follow-on: lint inline Python snippets inside agent SOUL.md prompts.

Scans /root/.hermes/profiles/*/SOUL.md for python3 invocations embedded in
bash (python3 -c "..." and python3 << EOF ... EOF forms), extracts the
Python body, and runs ast.parse() on it.

Two modes per snippet:
  EXECUTABLE — no <placeholder> patterns. Must parse cleanly. Syntax errors are FAIL.
  TEMPLATE  — contains <placeholder> patterns. Substituted with None, then parsed.
              If substituted version parses, report OK-template. Otherwise FAIL
              (template is broken beyond just placeholders).

Motivation: ARCH-IT-091 devops smoke gate had unquoted string literals
(d.get(error) instead of d.get("error")) — silent NameError at runtime,
making the gate always fail. Static parse-before-ship catches this class.
'''

import ast
import os
import re
import sys

PROFILES_DIR = '/root/.hermes/profiles'

# Match <placeholder_name> — used as template substitution markers in agent prompts.
# Conservative: require the first char to be a letter/underscore so we don't match
# comparison operators like a<b.
PLACEHOLDER_RE = re.compile(r'<([A-Za-z_][A-Za-z0-9_ .,]*)>')


def extract_python_snippets(soul_md_path):
    with open(soul_md_path) as f:
        text = f.read()
    snippets = []

    # Form 1: python3 -c 'BODY' or python3 -c "BODY"
    for m in re.finditer(r'python3\s+-c\s+(?P<q>["\'])(?P<body>(?:(?!(?P=q)).)*?)(?P=q)',
                         text, re.DOTALL):
        body = m.group('body')
        line_no = text[:m.start()].count('\n') + 1
        snippets.append((line_no, body, 'python3 -c'))

    # Form 2: python3 << 'EOF' ... EOF (and variants)
    for m in re.finditer(r'python3\s*<<-?\s*["\'‘]?(?P<delim>\w+)["\'’]?'
                         r'\s*\n(?P<body>.*?)\n(?P=delim)', text, re.DOTALL):
        body = m.group('body')
        line_no = text[:m.start()].count('\n') + 1
        snippets.append((line_no, body, f'heredoc <<{m.group("delim")}'))

    return snippets


def classify_and_parse(body):
    '''Return (status, info) where status is OK / OK-template / FAIL.'''
    placeholders = PLACEHOLDER_RE.findall(body)
    if placeholders:
        # Template mode: substitute every <placeholder> with None and parse.
        substituted = PLACEHOLDER_RE.sub('None', body)
        try:
            ast.parse(substituted)
            return 'OK-template', f'{len(placeholders)} placeholder(s): {placeholders[:3]}...' if len(placeholders) > 3 else f'placeholders: {placeholders}'
        except SyntaxError as e:
            return 'FAIL', f'template broken beyond placeholders: line {e.lineno}: {e.msg}'
    else:
        # Executable mode: must parse as-is.
        try:
            ast.parse(body)
            return 'OK', f'{len(body)} chars'
        except SyntaxError as e:
            return 'FAIL', f'SyntaxError line {e.lineno}: {e.msg}'


def main():
    if not os.path.isdir(PROFILES_DIR):
        print(f'FATAL: profiles dir not found at {PROFILES_DIR}')
        return 2

    total_snippets = 0
    total_fail = 0
    total_template = 0

    for d in sorted(os.listdir(PROFILES_DIR)):
        soul = os.path.join(PROFILES_DIR, d, 'SOUL.md')
        if not os.path.isfile(soul):
            continue
        snippets = extract_python_snippets(soul)
        total_snippets += len(snippets)
        for line_no, body, form in snippets:
            status, info = classify_and_parse(body)
            marker = {'OK': ' OK  ', 'OK-template': ' TMPL', 'FAIL': ' FAIL'}[status]
            print(f' {marker} {d}/SOUL.md:{line_no} ({form}): {info}')
            if status == 'FAIL':
                total_fail += 1
            if status == 'OK-template':
                total_template += 1

    print()
    print(f'=== summary: {total_snippets} scanned, {total_template} template-OK, {total_fail} failed ===')
    return 0 if total_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
