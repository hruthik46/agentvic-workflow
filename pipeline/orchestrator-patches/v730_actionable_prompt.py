"""v7.30 — make CODE-REVISE prompts ACTIONABLE.

Bug: backend agent gets generic "fix critical issues" prompt with categories
listed but no HOW-TO. Direct API tests prove MiniMax M2.7 CAN fix code when
told specifically "WaitEx → WaitForResult, Backing.FileName needs type
assertion, add StorageTypeIndependent constant" etc.

Fix: CODE-REVISE prompt now mandates a "build-fix-build" loop:
1. Run go build, capture errors
2. For each error, read the file at the specific line
3. Use file_write to apply fix
4. Re-run go build to verify
5. Loop until clean OR escalate
6. git commit + push

Plus: include common govmomi/library API drift hints in the prompt so the
agent doesn't have to guess.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# Find the v7.23-C CODE-REVISE extra_context and replace with v7.30 actionable version
OLD = '''                    extra_context=(f"PRIOR E2E RATING: {rating}/10 (REJECT). Self-diagnosis: {strategy}\\n\\n"
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

NEW = '''                    extra_context=(f"PRIOR E2E RATING: {rating}/10 (REJECT). Self-diagnosis: {strategy}\\n\\n"
                                   f"CRITICAL ISSUES (verbatim from code-blind-tester):\\n{_issues_str}\\n\\n"
                                   f"=== MANDATORY BUILD-FIX-BUILD LOOP (no prose, all tool calls) ===\\n\\n"
                                   f"STEP 1 — go to repo and the broken branch:\\n"
                                   f"  cd /root/karios-source-code/karios-migration\\n"
                                   f"  git fetch --all && git checkout backend/{gap_id}-cbt 2>/dev/null || git checkout -b backend/{gap_id}-cbt\\n\\n"
                                   f"STEP 2 — capture EVERY build error with file:line:\\n"
                                   f"  go build ./... 2>&1 | tee /tmp/build-iter{next_iter}.log | head -40\\n\\n"
                                   f"STEP 3 — fix each error using read_file + file_write. KNOWN GOVMOMI API DRIFT FIXES:\\n"
                                   f"  - `task.WaitEx(ctx)` returns ONLY error → replace with `task.WaitForResult(ctx, nil)` which returns `(*types.TaskInfo, error)`\\n"
                                   f"  - `taskInfo.Snapshot.Value` → `taskInfo.Result.(types.ManagedObjectReference).Value`\\n"
                                   f"  - `device.Backing.FileName` → `device.Backing.(*types.VirtualDiskFlatVer2BackingInfo).FileName`\\n"
                                   f"  - `provider.StorageTypeIndependent` undefined → add `StorageTypeIndependent StorageType = \\\"independent\\\"` to pkg/provider/types.go\\n"
                                   f"  - `vmObj.ExportSnapshot(ctx, ref)` returns `(*nfc.Lease, error)` not 3 values\\n"
                                   f"  - `QueryChangedDiskAreas(ctx, *Mo, *Mo, *Disk, int64)` — needs pointers + VirtualDisk + int64 offset\\n"
                                   f"  - DiskChangeInfo fields: `Length` (not ChangedAreaSize), `ChangedArea` (not ChangedAreas)\\n"
                                   f"  - syntax errors `unexpected name X expected (` usually mean missing `}}` brace before line X — count braces in surrounding function\\n\\n"
                                   f"STEP 4 — verify build is GREEN:\\n"
                                   f"  go build ./... && echo BUILD_OK || echo BUILD_FAIL\\n\\n"
                                   f"STEP 5 — IF BUILD_OK: commit and push:\\n"
                                   f"  git add -A internal/ pkg/ cmd/  # explicit dirs only, never agentic-workflow files\\n"
                                   f"  git commit -m 'fix(iter{next_iter}): {gap_id} — address build errors'\\n"
                                   f"  git push origin backend/{gap_id}-cbt\\n"
                                   f"  agent send orchestrator '[CODING-COMPLETE] {gap_id} commit_sha=<40-hex>'\\n\\n"
                                   f"STEP 6 — IF BUILD_FAIL after 3 fix attempts: write iteration-tracker note + emit [CODING-ERROR]\\n\\n"
                                   f"HARD RULES:\\n"
                                   f"- DO NOT WRITE PROSE. Every action MUST be a tool call.\\n"
                                   f"- DO NOT skip the go build step. The error list above MUST be ground truth.\\n"
                                   f"- DO NOT add new features. ONLY fix listed errors.\\n"
                                   f"- iteration {next_iter}/8. Coding category escalates after 2 fails — be precise.")
'''

if "v7.30" in text or "MANDATORY BUILD-FIX-BUILD LOOP" in text:
    print("[v7.30] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.30] CODE-REVISE prompt now actionable with specific govmomi API guidance")
else:
    print("[v7.30] WARN: OLD pattern not found — check whitespace")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.30] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.30] SYNTAX ERROR: {e}")
