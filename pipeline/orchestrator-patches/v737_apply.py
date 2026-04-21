"""v7.37 — bump WATCHDOG-FREQ + fix retry prompt."""
from pathlib import Path
import py_compile

aw = Path("/usr/local/bin/agent-worker")
text = aw.read_text()

# Fix 1: bump threshold 10K → 30K
old1 = "if (token_count[1] > 10000 and tool_use_detected.is_set()"
new1 = "if (token_count[1] > 30000 and tool_use_detected.is_set()"
if old1 in text:
    text = text.replace(old1, new1)
    print("  ✓ WATCHDOG-FREQ 10K → 30K")
else:
    print("  - threshold pattern not found (already fixed?)")

# Fix 2: rewrite retry prepend
old2 = """            'BEGIN by calling karios-vault.search. Do not output prose first.\\n\\n' +
            query"""
new2 = """            (\"FOLLOW SUGGESTED FIX STEP 1 EXACTLY from CRITICAL ISSUES section above.\\n\"
             \"DO NOT call karios-vault.search. DO NOT call search_files.\\n\"
             \"Your FIRST tool call MUST be: read_file at the path:line listed in LOCATION field.\\n\\n\"
             + query)"""

if old2 in text:
    text = text.replace(old2, new2)
    print("  ✓ retry prompt rewritten to reinforce v7.32 STEP 1")
elif "FOLLOW SUGGESTED FIX STEP 1 EXACTLY" in text:
    print("  - retry prompt already fixed")
else:
    print("  ✗ retry prompt pattern not found")

aw.write_text(text)
try:
    py_compile.compile(str(aw), doraise=True)
    print("  syntax OK")
except Exception as e:
    print(f"  err: {e}")
