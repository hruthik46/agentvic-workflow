"""v7.20 patch — E2E-RESULTS parser disk fallback.

When [E2E-RESULTS] arrives with empty/unparseable body, look up the latest
e2e-results.json on disk under iteration-tracker/<gap>/ and use that instead
of giving up. Closes the gap where agents emit a bare subject line via
`agent send orchestrator '[E2E-RESULTS]'` without piping the file content.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

OLD = '''        except json.JSONDecodeError:
            print(f"[dispatcher] ERROR: Could not parse E2E results JSON: {body[:200]}")
        return
'''

NEW = '''        except json.JSONDecodeError:
            # v7.20: disk fallback — agent may have emitted bare subject without piping JSON
            print(f"[dispatcher] WARN: E2E-RESULTS body unparseable, trying disk fallback for {gid}")
            try:
                from pathlib import Path as _v720_P
                _v720_root = _v720_P(f"/var/lib/karios/iteration-tracker/{gid}")
                _v720_files = list(_v720_root.rglob("e2e-results.json"))
                if _v720_files:
                    _v720_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    _v720_latest = _v720_files[0]
                    _v720_text = _v720_latest.read_text()
                    # Strip markdown fence if present
                    _m_fb = re.search(r'```(?:json)?\\s*\\n(.+?)\\n```', _v720_text, re.DOTALL)
                    if _m_fb:
                        _v720_text = _m_fb.group(1)
                    if not _v720_text.strip().startswith("{"):
                        _m_fb2 = re.search(r'\\{.*\\}', _v720_text, re.DOTALL)
                        if _m_fb2:
                            _v720_text = _m_fb2.group(0)
                    results = json.loads(_v720_text)
                    print(f"[dispatcher] v7.20 disk fallback: loaded {_v720_latest} for {gid}")
                    _r = results.get("rating", 0)
                    _rec = results.get("recommendation", "?")
                    _next = "devops (Phase 5 deploy)" if _r >= 8 else f"backend+frontend (revise iter {iteration+1})"
                    try:
                        notify_phase_transition(gid, "code-blind-tester+tester", _next,
                                                "E2E-RESULTS", rating=_r,
                                                summary=f"[disk-fallback] recommendation={_rec}; {results.get('summary', '')[:120]}")
                    except Exception:
                        pass
                    _crit_issues = results.get("critical_issues", [])
                    if not isinstance(_crit_issues, list):
                        _crit_issues = []
                    handle_e2e_results(gid, iteration, results.get("rating", results.get("score", 0)),
                                       _crit_issues,
                                       results.get("test_results", {}),
                                       results.get("dimensions", {}),
                                       results.get("adversarial_tests", {}),
                                       results.get("recommendation", "REQUEST_CHANGES"),
                                       trace_id=results.get("trace_id") or trace_id)
                    return
                else:
                    print(f"[dispatcher] v7.20 disk fallback: no e2e-results.json under {_v720_root}")
            except Exception as _v720_e:
                print(f"[dispatcher] v7.20 disk fallback failed: {_v720_e}")
            print(f"[dispatcher] ERROR: Could not parse E2E results JSON: {body[:200]}")
        return
'''

if "v7.20 disk fallback" in text:
    print("[v7.20] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.20] E2E-RESULTS parser disk fallback wired")
else:
    print("[v7.20] WARN: OLD block not found exactly")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.20] syntax OK")
except Exception as e:
    print(f"[v7.20] SYNTAX ERROR: {e}")
