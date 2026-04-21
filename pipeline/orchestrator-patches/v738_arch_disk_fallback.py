"""v7.38 — disk fallback for [ARCH-REVIEWED] (parallel to v7.20 for E2E)."""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

OLD = '''            except json.JSONDecodeError:
                print(f"[dispatcher] ERROR: Could not parse arch review JSON: {body[:200]}")
            except Exception as _ar_e:'''

NEW = '''            except json.JSONDecodeError:
                # v7.38: disk fallback for arch reviews (parallel to v7.20 for E2E)
                print(f"[dispatcher] WARN: arch review body unparseable, trying disk fallback for {gid}")
                try:
                    from pathlib import Path as _v738_P
                    _v738_root = _v738_P(f"/var/lib/karios/iteration-tracker/{gid}")
                    _v738_files = list(_v738_root.rglob("review.json"))
                    if _v738_files:
                        _v738_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                        _v738_latest = _v738_files[0]
                        _v738_text = _v738_latest.read_text()
                        # Strip markdown fence
                        _m_fb = re.search(r"```(?:json)?\\s*\\n(.+?)\\n```", _v738_text, re.DOTALL)
                        if _m_fb:
                            _v738_text = _m_fb.group(1)
                        if not _v738_text.strip().startswith("{"):
                            _m_fb2 = re.search(r"\\{.*\\}", _v738_text, re.DOTALL)
                            if _m_fb2:
                                _v738_text = _m_fb2.group(0)
                        review = json.loads(_v738_text)
                        print(f"[dispatcher] v7.38 disk fallback: loaded {_v738_latest} for {gid}")
                        handle_arch_review(gid, iteration, review.get("rating", 0),
                                           review.get("critical_issues", []),
                                           review.get("summary", ""),
                                           review.get("dimensions", {}),
                                           review.get("adversarial_test_cases", {}),
                                           review.get("recommendation", "REQUEST_CHANGES"),
                                           trace_id=review.get("trace_id") or trace_id)
                    else:
                        print(f"[dispatcher] v7.38 disk fallback: no review.json under {_v738_root}")
                        try:
                            telegram_alert(f"\u26a0\ufe0f *{gid}*: ARCH-REVIEWED unparseable + no disk fallback")
                        except Exception:
                            pass
                except Exception as _v738_e:
                    print(f"[dispatcher] v7.38 disk fallback failed: {_v738_e}")
            except Exception as _ar_e:'''

if "v7.38 disk fallback" in text:
    print("[v7.38] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.38] arch review disk fallback wired")
else:
    print("[v7.38] WARN: pattern not found")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.38] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.38] SYNTAX ERROR: {e}")
