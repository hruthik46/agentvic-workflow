"""Inject v7.18 imports after existing v7.6 import block in event_dispatcher.py."""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

PATCH = '''
# v7.18: Stream backlog prune + Langfuse trace integration
sys.path.insert(0, "/var/lib/karios/orchestrator/patches")
sys.path.insert(0, "/root/agentic-workflow/pipeline/integrations/3-langfuse")
try:
    from stream_prune import prune_stale_streams as _v718_prune_streams
except Exception as _e:
    _v718_prune_streams = None
    print(f"[dispatcher] v7.18 stream-prune unavailable: {_e}")
try:
    import langfuse_dispatcher_patch  # noqa: F401  initializes Langfuse if env vars set
except Exception as _e:
    print(f"[dispatcher] v7.18 langfuse-patch unavailable: {_e}")
'''

marker = "    _SCHEMA_VALIDATION = False\n"
if "_v718_prune_streams = None" in text:
    print("[v7.18] already patched")
elif marker in text:
    text = text.replace(marker, marker + PATCH, 1)
    ed.write_text(text)
    print("[v7.18] imports inserted after v7.6 schema block")
else:
    print("[v7.18] ERROR: marker not found")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.18] syntax OK")
except Exception as e:
    print(f"[v7.18] SYNTAX ERROR: {e}")
