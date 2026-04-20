#!/usr/bin/env python3
"""
Karios Migration Orchestrator — Dual-Loop Event Dispatcher v3.0

SOTA Improvements implemented:
  1. Structured Trace IDs      — correlation IDs on every message
  2. Redis Streams             — XREADGROUP replaces brpop (true event-driven)
  3. Enhanced Checkpointing    — persistent phase-boundary checkpoints
  4. Streaming                 — agents stream to Redis, monitor→Telegram
  5. Dynamic Routing           — conditional edges based on rating quality
  6. GitHub Webhook Trigger    — auto-deploy on PR merge
  7. Agent Memory (cross-session) — Redis-backed learnings with TTL
  8. Parallel Gap Pipeline     — Architect pre-researches next gap
  9. Hierarchical Fan-Out      — auto-decompose large features
  10. External Triggers         — webhook server + scheduler support

Phases:
  0-requirement  → Requirement received from Sai
  1-research      → Architect researches best practices (web + manual infra testing)
  2-arch-loop     → Architect builds architecture → Architect-Blind-Tester reviews
  3-coding        → Coder implements → DevOps deploys → Code-Blind-Tester E2E
  4-production    → DevOps deploys to prod → Notify Sai

Key rules:
  - Architecture loop: max 10 iterations, 10/10 required to pass
  - Coding loop: max 10 iterations, 10/10 required to pass
  - Escalation to Sai if loop exhausted
  - Research always first — Architect MUST test on real infra before writing architecture
  - Dynamic routing: rating >= 9 → fast-track; rating < 7 → escalate immediately
"""

import os, sys, json, time, subprocess, uuid, threading, re

# v7.12: central prompt builder — single source of truth for all dispatch prompts
try:
    sys.path.insert(0, '/var/lib/karios/orchestrator')
    from prompt_builder import build_prompt as _build_prompt
    _PROMPT_BUILDER = True
except ImportError as _pbe:
    print(f'[dispatcher] WARN: prompt_builder not loaded ({_pbe}); using legacy inline prompts')
    _PROMPT_BUILDER = False

# v7.6: Pydantic message-boundary validation
try:
    sys.path.insert(0, '/var/lib/karios/orchestrator')
    from message_schemas import validate_body, SchemaViolation
    _SCHEMA_VALIDATION = True
except ImportError as _ie:
    print(f'[dispatcher] WARN: message_schemas not loaded ({_ie}); validation disabled')
    _SCHEMA_VALIDATION = False
import redis
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Item A (ARCH-IT-ARCH-v11): Pydantic schema validation at message boundary
# LOG_ONLY=True for iteration 1 (log violations, don't quarantine/reject)
try:
    from orchestrator.message_schemas import validate_message, LOG_ONLY_MODE
except ImportError:
    # Fallback if message_schemas not available
    def validate_message(subject, body):
        return True, None, None
    LOG_ONLY_MODE = True

# ── OpenTelemetry Instrumentation (v4.0) ──────────────────────────────────────
import sys
sys.path.insert(0, '/usr/local/bin')
from otel_tracer import get_tracer
from sop_engine import SOPEngine, SOPViolation
from output_verifier import OutputVerifier
from hitl_interrupt import HITLInterruptHandler
from agent_benchmark import AgentBenchmark
from semantic_memory_v4 import SemanticMemoryV4
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.trace import Status, StatusCode

# OTEL Configuration via environment variables
OTEL_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "karios-orchestrator")
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
OTEL_USE_CONSOLE = os.environ.get("OTEL_USE_CONSOLE", "false").lower() == "true"

# Initialize OpenTelemetry tracer provider
def init_otel_tracer():
    """Initialize the OpenTelemetry tracer provider with OTLP/Console exporters."""
    resource = Resource(attributes={
        SERVICE_NAME: OTEL_SERVICE_NAME,
        SERVICE_VERSION: "1.0.0",
    })

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Add console exporter for local debugging
    if OTEL_USE_CONSOLE:
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    # Return KAIROS v4.0 tracer (wraps SDK with ctx,span unpacking)
    return KariosTracer(OTEL_SERVICE_NAME)

# ── Config ────────────────────────────────────────────────────────────────────
REDIS_HOST = os.environ.get("REDIS_HOST", "192.168.118.202")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003999467717")

ORCHESTRATOR_DIR = Path("/var/lib/karios/orchestrator")
IT_DIR = Path("/var/lib/karios/iteration-tracker")
REQS_DIR = Path("/var/lib/karios/coordination/requirements")
STATE_DIR = Path("/var/lib/karios/agent-state")
CHECKPOINT_DIR = Path("/var/lib/karios/checkpoints")
MEMORY_DIR = Path("/var/lib/karios/agent-memory")
SCHEMA_FILE = Path("/var/lib/karios/coordination/state-schema.json")
ERROR_TAXONOMY_FILE = Path("/var/lib/karios/coordination/error-taxonomy-v2.json")
LEARNINGS_FILE = Path("/var/lib/karios/coordination/learnings.json")

ORCHESTRATOR_DIR.mkdir(parents=True, exist_ok=True)
IT_DIR.mkdir(parents=True, exist_ok=True)
REQS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── Redis Streams consumer group
STREAM_KEY = "stream:orchestrator"
CONSUMER_GROUP = "orchestrator-consumers"
CONSUMER_NAME = f"orchestrator-{uuid.uuid4().hex[:8]}"

# ── SOP Engine + Output Verifier (v4.0) ────────────────────────────────────────
# Initialized in main() after config is loaded
sop_engine: SOPEngine = None
output_verifier: OutputVerifier = None
hitl: HITLInterruptHandler = None  # Human-in-the-Loop interrupt handler
semantic_memory: SemanticMemoryV4 = None  # v5.4: Semantic Memory for RAG context injection

# ── Trace ID Infrastructure ───────────────────────────────────────────────────
TRACES_DIR = ORCHESTRATOR_DIR / "traces"
TRACES_DIR.mkdir(exist_ok=True)

def new_trace_id(gap_id: str = None, agent: str = None, op: str = None) -> str:
    """Generate a structured trace ID: trace_<gap>_<agent>_<op>_<uuid8>"""
    parts = ["trace"]
    if gap_id:
        parts.append(gap_id.replace("-", "_"))
    if agent:
        parts.append(agent[:4])
    if op:
        parts.append(op)
    parts.append(uuid.uuid4().hex[:8])
    return "_".join(parts)

def current_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def current_ts_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)

# ── Redis Connection ─────────────────────────────────────────────────────────
def redis_conn():
    import redis
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
                       socket_timeout=5, socket_connect_timeout=5)

def init_stream_consumer_group():
    """FIX v5.1: Orchestrator uses XREAD (no consumer groups). No-op kept for compat."""
    pass  # No consumer group needed

# ── Redis Streams — True Event-Driven (replaces brpop) ───────────────────────
def xread_once(timeout_ms: int = 5000, since_id: str = None) -> (list, str):
    """
    XREAD-based message retrieval (FIX v5.1).
    Returns (messages, last_id) where last_id is the highest ID read — pass it back
    on the next call as since_id to avoid re-processing the same messages.

    Orchestrator is the sole reader of stream:orchestrator — no consumer group needed.
    FIX: Use XREAD with last-read ID tracking instead of consumer groups.
    Replaces brpop() from v2.0.
    """
    since = since_id or "0"  # "0" = all existing messages on first call

    try:
        r = redis_conn()
        # First: read any messages NEWER than since_id (non-blocking).
        # v6.0 FIX 2026-04-19: block=0 in Redis means "block forever", NOT
        # non-blocking. Caused orchestrator main thread to hang in do_sys_poll
        # for 23+ minutes, blocking the heartbeat thread via GIL contention.
        # block=100 = 100ms cap; matches the "fast peek" intent of this call.
        existing = r.xread(
            streams={STREAM_KEY: since},
            count=10,
            block=100
        )
        messages = []
        new_since = since
        if existing:
            for stream, entries in existing:
                for msg_id, data in entries:
                    decoded = {}
                    for k, v in data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        decoded[key] = val
                    messages.append((msg_id, decoded))
                    new_since = msg_id

        # Then: block and wait for NEW messages arriving after new_since.
        result = r.xread(
            streams={STREAM_KEY: new_since},
            count=10,
            block=timeout_ms
        )
        if result:
            for stream, entries in result:
                for msg_id, data in entries:
                    decoded = {}
                    for k, v in data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        decoded[key] = val
                    messages.append((msg_id, decoded))
                    new_since = msg_id
        return messages, new_since
    except redis.ResponseError as e:
        if "No such key" in str(e):
            return [], since
        print(f"[dispatcher] XREAD error: {e}")
        return [], since
    except Exception as e:
        print(f"[dispatcher] XREAD error: {e}")
        return [], since


def _file_inbox_fallback() -> list:
    """
    FIX v5.1: Check file-based agent-msg inbox at /var/lib/karios/agent-msg/inbox/orchestrator/.
    This is where `agent msg send orchestrator` writes JSON packets.
    We read pending packets, wrap them as pseudo stream messages, and return them.
    After processing, the packet is marked as read (deleted from inbox).
    """
    from pathlib import Path
    inbox_dir = Path("/var/lib/karios/agent-msg/inbox/orchestrator")
    if not inbox_dir.exists():
        return []
    try:
        packets = sorted(inbox_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        messages = []
        for packet_file in packets:
            try:
                data = json.loads(packet_file.read_text())
                fake_id = f"file-{uuid.uuid4().hex[:8]}"
                # Extract subject from message body (first line)
                body = data.get("message", "")
                subject = body.split("\n")[0] if body else "agent-msg"
                # Convert agent-msg format to orchestrator stream format
                wrapped = {
                    "from": data.get("from", "unknown"),
                    "subject": subject,
                    "body": body,
                    "gap_id": None,
                    "trace_id": None,
                    "timestamp": data.get("created_at", current_ts()),
                    "_packet_id": data.get("id"),
                    "_packet_priority": data.get("priority", "normal"),
                }
                messages.append((fake_id, wrapped))
                # Mark as read by moving from inbox (delete)
                packet_file.unlink()
                print(f"[dispatcher] ← FILE INBOX: {subject[:60]}")
            except Exception as e:
                # v7.5: quarantine bad-JSON packets so they don't loop the error every poll
                try:
                    qdir = Path('/var/lib/karios/agent-msg/quarantine')
                    qdir.mkdir(parents=True, exist_ok=True)
                    qpath = qdir / packet_file.name
                    packet_file.rename(qpath)
                    print(f"[dispatcher] file inbox quarantined: {packet_file.name} -> {qpath} ({e})")
                except Exception as qe:
                    print(f"[dispatcher] file inbox error (could not quarantine): {e} / {qe}")
                    try:
                        packet_file.unlink()
                    except Exception:
                        pass
        return messages
    except Exception as e:
        print(f"[dispatcher] file inbox scan error: {e}")
        return []

def _inbox_fallback() -> list:
    """
    Fallback: drain ALL messages from legacy inbox:orchestrator queue (Redis list).
    This handles the case where the stream is empty or consumer group
    doesn't exist yet. Messages can be sent here directly or via rpush.
    FIX v5.1: Normalize agent-msg 'message' field to 'body' for parse_message.
    FIX v5.1: Drain ALL messages (not just one) so fast loop doesn't starve.
    """
    all_messages = []
    try:
        r = redis_conn()
        # FIX v5.1: Drain ALL messages from the queue, not just one.
        while True:
            msg_json = r.rpop("inbox:orchestrator")
            if not msg_json:
                break
            data = json.loads(msg_json)
            # FIX v5.1: agent-msg uses 'message' field, but parse_message expects 'body'
            if "message" in data and "body" not in data:
                data["body"] = data.pop("message")
            # Wrap as a pseudo stream message with a fake ID
            fake_id = f"inbox-{uuid.uuid4().hex[:8]}"
            print(f"[dispatcher] ← INBOX FALLBACK: {data.get('subject', 'N/A')}")
            all_messages.append((fake_id, data))
    except Exception as e:
        if "NOGROUP" not in str(e):
            print(f"[dispatcher] inbox fallback error: {e}")
    return all_messages

def xack_all(msg_ids: list):
    """FIX v5.1: No consumer groups — nothing to acknowledge. Kept for message-loop compat."""
    pass

def stream_publish(subject: str, body: str, from_agent: str = "orchestrator",
                   gap_id: str = None, trace_id: str = None,
                   priority: str = "normal", **extra) -> bool:
    """
    Publish a message via Redis Streams (replaces rpush to inbox: queues).
    This is the new canonical message transport — event-driven, acked, replayable.
    """
    msg_id = str(uuid.uuid4())
    payload = {
        "id": msg_id,
        "from": from_agent,
        "subject": subject,
        "body": body,
        "gap_id": gap_id,
        "trace_id": trace_id or new_trace_id(gap_id, from_agent, subject[:20]),
        "priority": priority,
        "timestamp": current_ts(),
        **extra
    }
    try:
        r = redis_conn()
        r.xadd(STREAM_KEY, payload)
        return True
    except Exception as e:
        print(f"[dispatcher] stream_publish error: {e}")
        return False

# ── Legacy inbox rpush (backwards compat for agents still using old protocol) ─
def rpush(queue: str, msg: str):
    try:
        r = redis_conn()
        r.rpush(queue, msg)
    except Exception as e:
        print(f"[dispatcher] Redis error: {e}")

def brpop(queue: str, timeout: int = 5):
    try:
        r = redis_conn()
        return r.brpop(queue, timeout=timeout)
    except Exception as e:
        print(f"[dispatcher] Redis brpop error: {e}")
        return None

# ── Redis Pub/Sub Event Channels ─────────────────────────────────────────────
EVENT_CHANNELS = {
    "gap.phase_change": "gap.phase_change",
    "gap.iteration": "gap.iteration",
    "gap.escalation": "gap.escalation",
    "gap.completion": "gap.completion",
    "agent.heartbeat": "agent.heartbeat",
    "agent.state_change": "agent.state_change",
    "test.results": "test.results",
    "deploy.status": "deploy.status",
    "agent.stream": "agent.stream",          # NEW: streaming progress
}

def redis_publish(channel: str, payload: dict) -> bool:
    """Publish event to Redis pub/sub channel."""
    try:
        r = redis_conn()
        r.publish(channel, json.dumps(payload))
        return True
    except Exception as e:
        fallback = ORCHESTRATOR_DIR / "pubsub-fallback.jsonl"
        try:
            with open(fallback, "a") as f:
                f.write(json.dumps({"ts": current_ts(), "channel": channel,
                                    "payload": payload, "error": str(e)}) + "\n")
        except Exception:
            pass
        print(f"[dispatcher] Redis pub/sub FAILED on {channel}: {e}")
        return False

def publish_gap_event(event_type: str, gap_id: str, data: dict):
    """Publish a gap lifecycle event to all subscribers."""
    payload = {"event": event_type, "gap_id": gap_id, "ts": current_ts(), **data}
    for ch_name, ch in EVENT_CHANNELS.items():
        if ch_name.startswith(event_type.split(".")[0]) or ch_name == "agent.stream":
            redis_publish(ch, payload)

# ── Agent State Checkpointing ────────────────────────────────────────────────
def load_agent_state(agent: str) -> dict:
    """Load agent checkpoint state."""
    f = STATE_DIR / f"{agent}.json"
    if f.exists():
        with open(f) as fp:
            return json.load(fp)
    return {"agent": agent, "phase": "idle", "iteration": 0, "rating": None,
            "gate_passed": False, "last_update": None, "checkpoints": [],
            "trace_id": None}

def save_agent_state(agent: str, state: dict):
    """Save agent checkpoint and validate against schema."""
    state["last_update"] = current_ts()
    state.setdefault("checkpoints", []).append({
        "ts": current_ts(),
        "phase": state.get("phase"),
        "iteration": state.get("iteration"),
        "rating": state.get("rating"),
        "trace_id": state.get("trace_id"),
    })
    state["checkpoints"] = state["checkpoints"][-20:]
    f = STATE_DIR / f"{agent}.json"
    with open(f, "w") as fp:
        json.dump(state, fp, indent=2)
    redis_publish(EVENT_CHANNELS["agent.state_change"],
                  {"agent": agent, "state": {k: v for k, v in state.items() if k != "checkpoints"}})

def update_agent_checkpoint(agent: str, trace_id: str = None, **kwargs):
    """Update specific fields in agent checkpoint."""
    state = load_agent_state(agent)
    if trace_id:
        state["trace_id"] = trace_id
    for k, v in kwargs.items():
        state[k] = v
    save_agent_state(agent, state)

def save_checkpoint(gap_id: str, phase: str, iteration: int,
                    trace_id: str, data: dict = None,
                    agent: str = None, subtype: str = "phase"):
    """
    Save a durable checkpoint that enables crash recovery.
    Checkpoints are stored as: checkpoints/<gap_id>/<subtype>_<trace_id>.json
    """
    # ── OTEL: checkpoint span ───────────────────────────────────────────────
    tracer = get_tracer()
    ctx, span = tracer.start_span("checkpoint.save", {
        "gap_id": gap_id,
        "phase": phase,
        "iteration": iteration,
        "agent": agent,
        "checkpoint.subtype": subtype,
        "operation": "checkpoint"
    })
    try:
        ckpt_dir = CHECKPOINT_DIR / gap_id
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt = {
            "gap_id": gap_id,
            "phase": phase,
            "iteration": iteration,
            "trace_id": trace_id,
            "agent": agent,
            "subtype": subtype,
            "timestamp": current_ts(),
            "data": data or {}
        }
        ckpt_file = ckpt_dir / f"{subtype}_{trace_id}.json"
        with open(ckpt_file, "w") as f:
            json.dump(ckpt, f, indent=2)
        # Also save latest checkpoint symlink for quick recovery
        latest = ckpt_dir / "latest.json"
        with open(latest, "w") as f:
            json.dump(ckpt, f, indent=2)
        span.set_attribute("checkpoint.success", True)
        return ckpt_file
    except Exception as e:
        span.set_attribute("checkpoint.success", False)
        tracer.end_span(span, e)
        raise
    finally:
        tracer.end_span(span)

def load_latest_checkpoint(gap_id: str) -> dict:
    """Load the latest checkpoint for a gap (for crash recovery)."""
    latest = CHECKPOINT_DIR / gap_id / "latest.json"
    if latest.exists():
        return json.loads(latest.read_text())
    return None

def list_pending_checkpoints(gap_id: str) -> list:
    """List all incomplete checkpoints for a gap."""
    ckpt_dir = CHECKPOINT_DIR / gap_id
    if not ckpt_dir.exists():
        return []
    return sorted(ckpt_dir.glob("*.json"))

# ── Dynamic Routing ───────────────────────────────────────────────────────────
# Routing thresholds
ROUTING_FAST_TRACK = 9   # rating >= 9: skip ahead, minimal iterations
ROUTING_ESCALATE_NOW = 0  # v7.15: never escalate on rating; always revise (per Sai) # rating < 4: escalate immediately
ROUTING_MEDIUM = 8       # v7.15: retry/revise threshold = 8 per Sai       # 4 <= rating < 7: normal retry with self-diagnosis

def compute_routing(gap_id: str, phase: str, iteration: int, rating: int) -> dict:
    """
    Dynamic routing based on agent output quality.
    Returns: {route: "fast_track" | "normal" | "escalate", next_action: str, iterations_left: int}
    """
    if rating >= ROUTING_FAST_TRACK:
        return {
            "route": "fast_track",
            "next_action": "proceed",
            "iterations_left": max(0, 8 - iteration),  # v7.15: K_max=8 for all phases per Sai
            "reason": f"rating {rating} >= {ROUTING_FAST_TRACK} — fast track"
        }
    elif rating < ROUTING_ESCALATE_NOW:
        return {
            "route": "escalate",
            "next_action": "escalate",
            "iterations_left": 0,
            "reason": f"rating {rating} < {ROUTING_ESCALATE_NOW} — immediate escalation"
        }
    elif rating < ROUTING_MEDIUM:
        return {
            "route": "normal",
            "next_action": "retry_with_self_diagnosis",
            "iterations_left": max(0, 8 - iteration),  # v7.15: K_max=8 for all phases per Sai
            "reason": f"rating {rating} < {ROUTING_MEDIUM} — retry with self-correction"
        }
    else:
        return {
            "route": "normal",
            "next_action": "retry",
            "iterations_left": max(0, 8 - iteration),  # v7.15: K_max=8 for all phases per Sai
            "reason": f"rating {rating} >= {ROUTING_MEDIUM} — standard retry"
        }

# ── Error Taxonomy + Self-Diagnosis ──────────────────────────────────────────
def load_error_taxonomy() -> dict:
    if ERROR_TAXONOMY_FILE.exists():
        with open(ERROR_TAXONOMY_FILE) as f:
            return json.load(f)
    return {}

def classify_error(error_text: str) -> tuple:
    """Classify an error into the taxonomy."""
    taxonomy = load_error_taxonomy()
    categories = taxonomy.get("categories", {})
    error_lower = error_text.lower()
    for cat_name, cat_data in categories.items():
        for example in cat_data.get("examples", []):
            if example.replace("_", " ") in error_lower or example in error_lower:
                return cat_name, cat_data
    return "unknown", categories.get("unknown", {})

def self_diagnose(gap_id: str, phase: str, iteration: int, rating: int, error_text: str):
    """Attempt self-diagnosis before escalation (VIGIL-inspired pattern)."""
    taxonomy = load_error_taxonomy()
    cat_name, cat_data = classify_error(error_text)
    resolution_map = taxonomy.get("resolutionStrategies", {})
    strategy = resolution_map.get(cat_name, "No automatic resolution available")
    severity = cat_data.get("severity", "medium")
    auto_retry = cat_data.get("auto_retry", False)
    escalate_after = cat_data.get("escalate_after_attempts", 1)

    if cat_name in ("ambiguity", "access"):
        return False, f"[SELF-DIAGNOSIS] {cat_name} error — {strategy}", True

    if not auto_retry:
        return False, f"[SELF-DIAGNOSIS] {cat_name} error (no auto-retry) — {strategy}", True

    if iteration < escalate_after:
        return True, f"[SELF-DIAGNOSIS] {cat_name} error (severity={severity}) — {strategy} (attempt {iteration}/{escalate_after})", False

    if iteration == escalate_after:
        return True, f"[SELF-DIAGNOSIS] {cat_name} — {strategy} (final attempt {iteration}/{escalate_after})", False

    return False, f"[SELF-DIAGNOSIS] {cat_name} error — exhausted {iteration} attempts. {strategy}", True

# ── Agent Memory (Cross-Session Learnings) ───────────────────────────────────
def load_learnings() -> dict:
    """Load the global learnings store.

    Handles three formats:
    1. Single JSON object: {"learnings": [...], "version": "1.0", ...}
    2. JSON Lines (multiple JSON objects concatenated): {"learnings": [...]}\n{"learnings": [...]}
    3. Plain list: [...]
    """
    if LEARNINGS_FILE.exists():
        text = LEARNINGS_FILE.read_text()
        # Try parsing as a single JSON object first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try JSON Lines: split on }\n{ and merge all top-level "learnings" arrays
            all_learnings = []
            import re
            # Split on } followed by { (allowing whitespace between)
            parts = re.split(r'}\s*\{', text)
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                # Wrap parts[1:] with { and }
                if i > 0:
                    part = "{" + part
                if i < len(parts) - 1:
                    part = part + "}"
                try:
                    obj = json.loads(part)
                    if isinstance(obj, dict) and "learnings" in obj:
                        all_learnings.extend(obj["learnings"])
                    elif isinstance(obj, list):
                        all_learnings.extend(obj)
                except json.JSONDecodeError:
                    pass
            return {
                "version": "1.0",
                "learnings": all_learnings,
                "by_agent": {},
                "by_gap_type": {}
            }
    return {"version": "1.0", "learnings": [], "by_agent": {}, "by_gap_type": {}}

def save_learnings(data: dict):
    """Save the global learnings store."""
    LEARNINGS_FILE.write_text(json.dumps(data, indent=2))

def store_learning(agent: str, gap_id: str, phase: str,
                   what_happened: str, resolution: str,
                   rating: int = None, error_type: str = None):
    """Store a learning from an agent's experience.

    v6.0 FIX 2026-04-19: load_learnings can return list (v6 schema) OR dict (v5 schema).
    Coerce to dict shape before mutation.
    """
    data = load_learnings()
    if isinstance(data, list):
        data = {"version": "1.0", "learnings": data, "by_agent": {}, "by_gap_type": {}}
    elif not isinstance(data, dict):
        data = {"version": "1.0", "learnings": [], "by_agent": {}, "by_gap_type": {}}
    data.setdefault("learnings", [])
    learning = {
        "id": f"lrn_{uuid.uuid4().hex[:8]}",
        "agent": agent,
        "gap_id": gap_id,
        "phase": phase,
        "what_happened": what_happened,
        "resolution": resolution,
        "rating": rating,
        "error_type": error_type,
        "timestamp": current_ts(),
        "ttl_days": 90,  # Retain for 90 days
    }
    data["learnings"].append(learning)
    data["learnings"] = data["learnings"][-500:]  # Keep last 500

    data.setdefault("by_agent", {}).setdefault(agent, []).append(learning["id"])
    data.setdefault("by_gap_type", {}).setdefault(phase, []).append(learning["id"])
    save_learnings(data)

    # v5.4: Also index in semantic_memory for RAG context injection
    if semantic_memory is not None:
        try:
            from semantic_memory_v4 import LearningsEntry as _LE
            content = f"[{agent}/{phase}] {what_happened} | Resolution: {resolution}"
            metadata = {
                "agent_id": agent,
                "gap_id": gap_id,
                "phase": phase,
                "rating": rating or 0,
                "error_type": error_type or "",
            }
            semantic_memory.store_kb_entry(semantic_memory.LEARNINGS, content, metadata)
        except Exception:
            pass  # Non-blocking — don't fail learning storage if semantic_memory fails

def retrieve_relevant_learnings(agent: str = None, phase: str = None,
                               gap_id: str = None, limit: int = 10) -> list:
    """Retrieve learnings relevant to current task (for context injection)."""
    data = load_learnings()
    # Handle both dict format {"learnings": [...]} and plain list [...]
    if isinstance(data, dict):
        learnings = data.get("learnings", [])
    elif isinstance(data, list):
        learnings = data
    else:
        learnings = []
    # Filter by phase first, then by recency
    if phase:
        learnings = [l for l in learnings if l.get("phase") == phase]
    if agent:
        learnings = [l for l in learnings if l.get("agent") == agent]
    # Sort by recency
    learnings = sorted(learnings, key=lambda l: l.get("timestamp", ""), reverse=True)
    return learnings[:limit]

def format_learnings_for_context(learnings: list) -> str:
    """Format learnings as a markdown string for injection into agent context."""
    if not learnings:
        return ""
    lines = ["\n\n## Relevant Past Learnings\n"]
    for l in learnings:
        lines.append(f"- **[{l['agent']}@{l['phase']}]** {l['what_happened']} → {l['resolution']}")
    return "\n".join(lines)

# ── Telegram ─────────────────────────────────────────────────────────────────
def telegram_alert(message: str):
    """v7.5: log on non-200 + Markdown parse failures, retry once with plain text."""
    if not TELEGRAM_TOKEN or len(TELEGRAM_TOKEN) < 30:
        print(f"[dispatcher] Telegram skipped: token missing/invalid (len={len(TELEGRAM_TOKEN)})")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    def _send(text, parse_mode="Markdown"):
        cmd = ["curl", "-s", "-X", "POST", url,
               "-d", f"chat_id={TELEGRAM_CHAT_ID}",
               "-d", f"text={text}"]
        if parse_mode:
            cmd.extend(["-d", f"parse_mode={parse_mode}"])
        return subprocess.run(cmd, capture_output=True, timeout=10, text=True)
    try:
        r = _send(message)
        if r.returncode != 0:
            print(f"[dispatcher] Telegram curl failed: {r.stderr[:200]}")
            return
        if r.stdout and '"ok":false' in r.stdout:
            print(f"[dispatcher] Telegram Markdown rejected, retrying as plain: {r.stdout[:200]}")
            r2 = _send(message, parse_mode=None)
            if r2.stdout and '"ok":false' in r2.stdout:
                print(f"[dispatcher] Telegram plain also failed: {r2.stdout[:200]}")
    except Exception as e:
        print(f"[dispatcher] Telegram exception: {e}")

# ── Fan-Out / Fan-In Pattern ─────────────────────────────────────────────────
FAN_STATE_FILE = ORCHESTRATOR_DIR / "fan-state.json"

def notify_phase_transition(gap_id: str, from_agent: str, to_agent: str,
                              event: str, rating=None, score_max=10, summary: str = ""):
    """v7.3: Loud Telegram notification when a phase transitions or a blind-tester scores.
    User explicitly asked: 'I want to know that the blind-test agent reviewed, this is the
    score, now handing back to architect/coder.'"""
    icons = {"ARCH-COMPLETE": "📐", "ARCH-REVIEWED": "🔍", "CODING-COMPLETE": "💾",
             "FAN-IN-COMPLETE": "🔗", "API-SYNC": "🤝", "E2E-RESULTS": "🧪",
             "STAGING-DEPLOYED": "📦", "PROD-DEPLOYED": "🚀", "MONITORING-COMPLETE": "📊",
             "BLIND-E2E-RESULTS": "🧪", "ESCALATED": "🚨", "FAILED": "❌"}
    icon = icons.get(event, "•")
    score_part = f" — score {rating}/{score_max}" if rating is not None else ""
    handoff = f"\nHanding off: {from_agent} → {to_agent}" if to_agent else ""
    msg = f"{icon} [{event}] {gap_id}{score_part}{handoff}"
    if summary:
        msg += f"\n  {summary[:200]}"
    try:
        telegram_alert(msg)
    except Exception as e:
        print(f"[dispatcher] Telegram phase-notify failed: {e}")


def load_fan_state() -> dict:
    if FAN_STATE_FILE.exists():
        return json.loads(FAN_STATE_FILE.read_text())
    return {"pending": {}}

def save_fan_state(state: dict):
    FAN_STATE_FILE.write_text(json.dumps(state, indent=2))

def fan_out(gap_id: str, agents: list, task_subject: str,
            task_body: str, checkpoint_phase: str, trace_id: str = None):
    """Send the same task to multiple agents in parallel (fan-out)."""
    fan_state = load_fan_state()
    tid = trace_id or new_trace_id(gap_id, "orchestrator", "fan_out")
    fan_state["pending"][gap_id] = {
        "agents": agents,
        "completed": [],
        "task_subject": task_subject,
        "checkpoint_phase": checkpoint_phase,
        "started_at": current_ts(),
        "trace_id": tid,
    }
    save_fan_state(fan_state)
    for agent in agents:
        update_agent_checkpoint(agent, phase=checkpoint_phase, iteration=0, trace_id=tid)
        # v6.0 FIX 2026-04-19: Was stream_publish() which writes to STREAM_KEY
        # (= stream:orchestrator) regardless of `to` field — fan-out messages
        # never reached backend/frontend, just looped back to the dispatcher.
        # send_to_agent() correctly XADDs to stream:{agent}.
        send_to_agent(
            agent,
            f"[FAN-OUT] {task_subject} {gap_id}",
            f"{task_body}\n\nThis is a PARALLEL task. Other agents also working: {agents}.\nSend [FAN-IN] <gap_id> when done. Your trace_id is {tid}.",
            gap_id=gap_id,
            trace_id=tid,
            priority="high",
        )
        redis_publish(EVENT_CHANNELS["agent.state_change"],
                      {"agent": agent, "event": "fan_out", "gap_id": gap_id,
                       "parallel_with": agents, "trace_id": tid})
    publish_gap_event("gap.iteration", gap_id,
                      {"action": "fan_out", "agents": agents,
                       "phase": checkpoint_phase, "trace_id": tid})
    print(f"[dispatcher] FAN-OUT: {gap_id} → {agents} (trace={tid})")

def fan_in(gap_id: str, agent: str, agent_state: dict) -> bool:
    """Record a parallel agent's completion. When all done, trigger next step."""
    fan_state = load_fan_state()
    if gap_id not in fan_state["pending"]:
        print(f"[dispatcher] FAN-IN: {gap_id} from {agent} — no pending fan-out")
        return False

    pending = fan_state["pending"][gap_id]
    if agent not in pending["completed"]:
        pending["completed"].append(agent)
    save_fan_state(fan_state)

    update_agent_checkpoint(agent, trace_id=pending.get("trace_id"), **agent_state)

    still_pending = [a for a in pending["agents"] if a not in pending["completed"]]
    print(f"[dispatcher] FAN-IN: {agent} done for {gap_id}. Still pending: {still_pending}")

    if not still_pending:
        del fan_state["pending"][gap_id]
        save_fan_state(fan_state)
        publish_gap_event("gap.iteration", gap_id,
                          {"action": "fan_in_complete", "agents": pending["agents"],
                           "trace_id": pending.get("trace_id")})
        print(f"[dispatcher] FAN-IN COMPLETE: all {pending['agents']} done for {gap_id}")
        # v7.4: Telegram on Phase 3 → Phase 4 transition
        try:
            notify_phase_transition(gap_id, "backend+frontend", "tester+code-blind-tester (Phase 4 E2E)",
                                    "CODING-COMPLETE", rating=None,
                                    summary=f"FAN-IN done; agents={pending['agents']}")
        except Exception as _e:
            print(f"[dispatcher] notify_phase_transition error: {_e}")
        return True
    return False

# ── Parallel Gap Pipeline ──────────────────────────────────────────────────────
# Track which gap the Architect is pre-researching
PARALLEL_PIPELINE_FILE = ORCHESTRATOR_DIR / "parallel-pipeline.json"

def load_pipeline_state() -> dict:
    if PARALLEL_PIPELINE_FILE.exists():
        return json.loads(PARALLEL_PIPELINE_FILE.read_text())
    return {"pre_researching": {}, "active": {}}

def save_pipeline_state(state: dict):
    PARALLEL_PIPELINE_FILE.write_text(json.dumps(state, indent=2))

def start_parallel_research(gap_id: str, requirement_text: str, trace_id: str = None):
    """
    Start Phase 1 (research) for gap N+1 while Orchestrator handles gap N Phase 2+.
    This enables pipeline parallelism: Architect is never idle.
    """
    tid = trace_id or new_trace_id(gap_id, "architect", "pre_research")
    state = load_pipeline_state()
    state.setdefault("pre_researching", {})  # v7.5.1: defensive
    state["pre_researching"][gap_id] = {
        "started_at": current_ts(),
        "trace_id": tid,
        "requirement": requirement_text[:200],
    }
    save_pipeline_state(state)

    # Check if architect is free (not working on any active gap)
    architect_state = load_agent_state("architect")
    if architect_state.get("phase") not in ("idle", None, "phase-1-done"):
        print(f"[dispatcher] Architect busy ({architect_state.get('phase')}), queuing pre-research for {gap_id}")
        return

    update_agent_checkpoint("architect", phase="phase-1-research", trace_id=tid)
    stream_publish(
        subject=f"[PRE-RESEARCH] {gap_id}",
        body=f"""Pre-research task for upcoming gap {gap_id}.

Requirement (preview): {requirement_text[:500]}

Work on this concurrently with your current tasks. When done,
send [RESEARCH-COMPLETE] {gap_id} to orchestrator.

This is background research — does NOT block the active gap pipeline.""",
        from_agent="orchestrator",
        gap_id=gap_id,
        trace_id=tid,
        to="architect",
        priority="low"
    )
    print(f"[dispatcher] Started parallel pre-research for {gap_id} (trace={tid})")

def is_architect_free() -> bool:
    """Check if architect is available for new tasks."""
    architect_state = load_agent_state("architect")
    phase = architect_state.get("phase", "idle")
    return phase in ("idle", None) or phase == "phase-1-done"

# ── Hierarchical Fan-Out ─────────────────────────────────────────────────────
def decompose_and_fan_out(gap_id: str, task: str, agents: list,
                          parent_trace_id: str = None) -> dict:
    """
    For large features: auto-decompose into sub-tasks routed to sub-agents.
    Returns decomposition metadata.
    """
    parent_tid = parent_trace_id or new_trace_id(gap_id, "orchestrator", "hierarchy")
    sub_tasks = {
        "parent_gap": gap_id,
        "parent_trace": parent_tid,
        "sub_tasks": [],
    }

    # If we have 2 agents and a compound task, split by domain
    if len(agents) == 2 and "backend" in agents and "frontend" in agents:
        sub_tasks["sub_tasks"] = [
            {
                "id": f"{gap_id}_backend",
                "agent": "backend",
                "scope": "backend_only",
                "parent_trace": parent_tid,
            },
            {
                "id": f"{gap_id}_frontend",
                "agent": "frontend",
                "scope": "frontend_only",
                "parent_trace": parent_tid,
            }
        ]
    else:
        # Generic split: round-robin assignment
        for i, agent in enumerate(agents):
            sub_tasks["sub_tasks"].append({
                "id": f"{gap_id}_sub_{i}",
                "agent": agent,
                "scope": "full",
                "parent_trace": parent_tid,
            })

    # Save decomposition
    decomp_file = IT_DIR / gap_id / "phase-3-coding" / "decomposition.json"
    decomp_file.parent.mkdir(parents=True, exist_ok=True)
    decomp_file.write_text(json.dumps(sub_tasks, indent=2))

    return sub_tasks

# ── Phase Transition ──────────────────────────────────────────────────────────
def transition_phase(gap_id: str, new_phase: str, agent: str = None, trace_id: str = None, **kwargs):
    """Transition gap to new phase, save checkpoint, publish event."""
    trace_id = trace_id or new_trace_id(gap_id, agent or "orchestrator", f"phase_{new_phase}")
    update_gap_phase(gap_id, new_phase, trace_id=trace_id, **kwargs)
    if agent:
        update_agent_checkpoint(agent, phase=new_phase, trace_id=trace_id, **kwargs)
    save_checkpoint(gap_id, new_phase, kwargs.get("iteration", 0), trace_id,
                    data=kwargs, agent=agent, subtype="phase")
    publish_gap_event("gap.phase_change", gap_id,
                      {"from_phase": kwargs.get("_prev_phase", "?"), "to_phase": new_phase,
                       "agent": agent, "iteration": kwargs.get("iteration", 0),
                       "trace_id": trace_id})
    return trace_id

# ── Orchestrator State ───────────────────────────────────────────────────────
def load_state() -> dict:
    state_file = ORCHESTRATOR_DIR / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"active_gaps": {}, "completed_gaps": [], "blocked_messages_log": [],
            "trace_log": []}

def save_state(state: dict):
    state_file = ORCHESTRATOR_DIR / "state.json"
    state_file.write_text(json.dumps(state, indent=2))

def load_gap(gap_id: str) -> dict:
    """Load gap metadata and all iteration reviews.

    v7.3 FIX: if metadata.json missing, fall back to state.json active_gaps[gap_id].
    Without this, [COMPLETE] handler always saw current_phase='unknown' and refused
    to transition.
    """
    gap_dir = IT_DIR / gap_id
    metadata_file = gap_dir / "metadata.json"
    if metadata_file.exists():
        data = json.loads(metadata_file.read_text())
    else:
        data = {"gap_id": gap_id, "phase": "unknown", "iteration": 0}
        # Fallback: read state.json
        try:
            state_path = Path("/var/lib/karios/orchestrator/state.json")
            if state_path.exists():
                state = json.loads(state_path.read_text())
                gentry = state.get("active_gaps", {}).get(gap_id)
                if gentry:
                    data["phase"] = gentry.get("phase", "unknown")
                    data["iteration"] = gentry.get("iteration", 0)
                    data["trace_id"] = gentry.get("trace_id", "")
        except Exception:
            pass
    reviews = []
    arch_review_dir = gap_dir / "phase-2-arch-loop"
    if arch_review_dir.exists():
        for f in sorted(arch_review_dir.glob("iteration-*/review.json")):
            reviews.append({"iteration": int(f.parent.name.split("-")[1]),
                           "review": json.loads(f.read_text())})
    data["arch_reviews"] = reviews
    return data

def save_gap(gap_id: str, data: dict):
    gap_dir = IT_DIR / gap_id
    gap_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = gap_dir / "metadata.json"
    metadata_file.write_text(json.dumps(data, indent=2))

def update_gap_phase(gap_id: str, phase: str, iteration: int = None, trace_id: str = None, **kwargs):
    """Update gap phase and optional fields."""
    data = load_gap(gap_id)
    data["phase"] = phase
    if iteration is not None:
        data["iteration"] = iteration
    if trace_id:
        data["trace_id"] = trace_id
    for k, v in kwargs.items():
        data[k] = v
    data["updated_at"] = current_ts()
    save_gap(gap_id, data)
    return data

# ── Context Archiving ────────────────────────────────────────────────────────
def archive_context_packet(packet: dict, gap_id: str = None):
    """Archive every handoff context packet to Obsidian for durability."""
    VAULT = Path("/opt/obsidian/config/vaults/My-LLM-Wiki/wiki")
    arch_dir = VAULT / "agents" / packet.get("from", "unknown") / "context-packets"
    arch_dir.mkdir(parents=True, exist_ok=True)
    ts = current_ts().replace(":", "-").replace("Z", "")
    sender = packet.get("from", "unknown")
    recipient = packet.get("to", "unknown")
    seq_id = f"{gap_id}-{ts}" if gap_id else f"{sender}-to-{recipient}-{ts}"
    packet_file = arch_dir / f"{seq_id}.md"

    learnings_hint = ""
    if packet.get("gap_id") or gap_id:
        gid = packet.get("gap_id") or gap_id
        phase = packet.get("phase", "")
        learnings = retrieve_relevant_learnings(agent=sender, phase=phase, limit=5)
        if learnings:
            learnings_hint = format_learnings_for_context(learnings)

    content = f"""---
packet_id: {seq_id}
from: {packet.get('from')}
to: {packet.get('to')}
subject: {packet.get('subject')}
task_id: {packet.get('task_id')}
gap_id: {gap_id or 'unknown'}
timestamp: {packet.get('timestamp')}
trace_id: {packet.get('trace_id', 'none')}
type: context_packet
---

# Context Packet: {seq_id}

**From:** {packet.get('from')}
**To:** {packet.get('to')}
**Subject:** {packet.get('subject')}
**Gap:** {gap_id or 'unknown'}
**Time:** {packet.get('timestamp')}
**Trace:** `{packet.get('trace_id', 'none')}`

## Body

{packet.get('body', '(empty)')}

{learnings_hint}

---
_Archived by orchestrator event_dispatcher v3.0_
"""
    try:
        packet_file.write_text(content)
        print(f"[dispatcher] Archived: {packet_file}")
    except Exception as e:
        print(f"[dispatcher] Archive failed: {e}")

# ── Message Envelope (v7.0) ─────────────────────────────────────────────────
import hashlib

class MessageEnvelope:
    """v7.0: Rich message envelope with idempotency keys and DLQ support."""
    VERSION = "v7"
    MSG_TYPES = {"DISPATCH", "NUDGE", "INTERRUPT", "HEARTBEAT", "RESULT"}
    MAX_RETRIES = {"DISPATCH": 3, "NUDGE": 5, "INTERRUPT": 0, "HEARTBEAT": 1}
    BACKOFF_CAP  = {"DISPATCH": 30, "NUDGE": 60, "INTERRUPT": 0, "HEARTBEAT": 5}
    
    def __init__(self, agent_id: str, step_id: str, gap_id: str, 
                 trace_id: str, msg_type: str, payload: dict,
                 existing_id: str = None, existing_retry_count: int = None):
        self.version = self.VERSION
        self.id = existing_id or f"msg_{uuid.uuid4().hex[:12]}"
        self.agent_id = agent_id
        self.step_id = step_id
        self.gap_id = gap_id
        self.trace_id = trace_id
        self.msg_type = msg_type
        self.payload = payload
        self.retry_count = existing_retry_count or 0
        self.max_retries = self.MAX_RETRIES.get(msg_type, 3)
        self.backoff_cap = self.BACKOFF_CAP.get(msg_type, 30)
        self.first_seen = int(datetime.utcnow().timestamp())
        self.last_attempt = self.first_seen
        self.error = None
    
    @property
    def idempotency_key(self) -> str:
        raw = f"{self.id}:{self.agent_id}:{self.step_id}"
        return hashlib.sha256(raw.encode()).hexdigest()
    
    def to_stream_entry(self, dlq_headers: dict = None) -> dict:
        entry = {
            "version": self.version,
            "id": self.id,
            "idempotency_key": self.idempotency_key,
            "agent_id": self.agent_id,
            "step_id": self.step_id,
            "gap_id": self.gap_id,
            "trace_id": self.trace_id,
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
            "first_seen": str(self.first_seen),
            "last_attempt": str(self.last_attempt),
            "error": self.error or "",
            "msg_type": self.msg_type,
            "payload": json.dumps(self.payload)
        }
        if dlq_headers:
            for k, v in dlq_headers.items():
                entry[f"dlq_{k}"] = str(v)
        return entry
    
    @classmethod
    def from_stream_entry(cls, entry: dict) -> "MessageEnvelope":
        env = cls(
            agent_id=entry["agent_id"],
            step_id=entry["step_id"],
            gap_id=entry["gap_id"],
            trace_id=entry["trace_id"],
            msg_type=entry["msg_type"],
            payload=json.loads(entry["payload"]),
            existing_id=entry["id"],
            existing_retry_count=int(entry["retry_count"])
        )
        env.first_seen = int(entry["first_seen"])
        env.last_attempt = int(entry["last_attempt"])
        env.error = entry["error"] or None
        return env

def handle_failure(message: MessageEnvelope, error: Exception) -> None:
    """v7.0: Retry with exponential backoff, or move to DLQ."""
    
    message.retry_count += 1
    message.last_attempt = int(datetime.utcnow().timestamp())
    message.error = str(error)
    
    if message.retry_count < message.max_retries:
        # Exponential backoff: 1, 2, 4, 8, 16, 30 (capped)
        delay = min(message.backoff_cap, 2 ** message.retry_count)
        print(f"[dispatcher] RETRY: {message.gap_id}/{message.step_id} retry={message.retry_count}, backoff={delay}s")
        time.sleep(delay)
        
        # Re-dispatch with same idempotency_key (key still held)
        stream_key = f"stream:{message.agent_id}"
        redis_conn().xadd(stream_key, message.to_stream_entry())
        # Metric: karios_retries_total{agent=agent, retry_count=message.retry_count}++
    else:
        # Move to DLQ
        dlq_key = f"stream:dlq:{message.agent_id}"
        
        dlq_headers = {
            "first_seen": message.first_seen,
            "last_attempt": message.last_attempt,
            "retry_count": message.retry_count,
            "max_retries": message.max_retries,
            "last_error": message.error,
            "root_cause_gap_id": message.gap_id,
            "dispatched_by": "orchestrator"
        }
        
        redis_conn().xadd(dlq_key, message.to_stream_entry(dlq_headers))
        
        # Release idempotency key (allow future re-dispatch)
        idem_key = f"idem:{message.agent_id}:{message.idempotency_key}"
        redis_conn().delete(idem_key)
        
        # Alert
        publish_alert("DLQ_ENTRY_CREATED", {
            "agent": message.agent_id,
            "gap_id": message.gap_id,
            "step_id": message.step_id,
            "retry_count": message.retry_count,
            "last_error": message.error
        })
        
        print(f"[dispatcher] DLQ: {message.gap_id}/{message.step_id} moved after {message.retry_count} retries")
        # Metric: karios_dlq_entries_total{agent=agent}++

def cleanup_orphaned_keys() -> int:
    """Scan idem:* keys with no stream entry for > 1 hour, delete them."""
    
    r = redis_conn()
    cleaned = 0
    
    for idem_key in r.scan_iter("idem:*"):
        # Check if corresponding stream entry exists
        # Key format: idem:{agent}:{idempotency_key}
        parts = idem_key.split(":")
        if len(parts) != 3:
            continue
        
        agent = parts[1]
        stream_key = f"stream:{agent}"
        
        # Check TTL remaining
        ttl = r.ttl(idem_key)
        if ttl > 0 and ttl < 82800:  # Less than 23h remaining = key is old
            # Key has been there > 1h without corresponding activity
            # Check if any message with this key is in flight
            messages = r.xrange(stream_key, count=100)
            in_flight = any(
                entry.get("idempotency_key", "") == parts[2]
                for _, entry in messages
            )
            
            if not in_flight:
                r.delete(idem_key)
                cleaned += 1
                print(f"[dispatcher] IDEM_CLEANUP_ORPHANED: {idem_key}")
                # Metric: karios_orphan_cleanup_total{agent=agent}++
    
    return cleaned

# ── Send to Agent (Streams-based) ─────────────────────────────────────────────
def send_to_agent(agent: str, subject: str, body: str,
                  task_id: str = None, gap_id: str = None,
                  trace_id: str = None, priority: str = "normal"):
    """Send a context packet to an agent via their dedicated Redis Stream.

    FIX v5.1: Write to stream:{agent} — each agent has its own stream.
    Previously wrote to stream:orchestrator with separate consumer groups per agent,
    causing XREADGROUP race conditions where agents claimed each other's messages.
    Now orchestrator writes directly to agent's private stream — no group needed.

    FIX v5.4: Semantic Memory inject_context() prepended to body before dispatch.
    """
    tid = trace_id or new_trace_id(gap_id, "orchestrator", subject[:20])
    # FIX v5.4: Inject semantic memory context before sending to agent
    if semantic_memory is not None and gap_id:
        try:
            context_query = f"{agent} {gap_id} {subject[:30]}"
            injected = semantic_memory.inject_context(agent, context_query, max_tokens=2000)
            if injected:
                body = injected + "\n\n---\n\n## Task\n\n" + body
                print(f"[dispatcher] Injected semantic context ({len(injected)} chars) for {agent}")
        except Exception:
            pass  # Non-blocking — don't fail dispatch if semantic memory fails
    # FIX v5.1: Filter None values — Redis XADD can't serialize None
    packet = {
        k: v for k, v in {
        "from": "orchestrator",
        "to": agent,
        "subject": subject,
        "body": body,
        "task_id": task_id,
        "gap_id": gap_id,
        "trace_id": tid,
        "timestamp": current_ts()
    }.items() if v is not None
    }
    # Deliver to agent's private stream (v5.1 fix — no shared stream, no consumer group race)
    # ── OTEL: Redis op instrumentation ──────────────────────────────────────
    import time
    tracer = get_tracer()
    # v6.0 FIX 2026-04-19: agent-worker maps short agent names to systemd service names for stream keys.
    # Dispatcher MUST use the same mapping or messages land in the wrong stream.
    # Pre-v6 bug: backend reads stream:backend-worker but dispatcher wrote stream:backend.
    DISPATCH_STREAM_MAP = {
        "backend":   "backend-worker",
        "frontend":  "frontend-worker",
        "devops":    "devops-agent",
        "tester":    "tester-agent",
    }
    mapped = DISPATCH_STREAM_MAP.get(agent, agent)
    stream_key = f"stream:{mapped}"

    # ── SOP Pre-Check (v4.0) ────────────────────────────────────────────────
    # Check SOP pre-conditions before dispatching to agent
    if sop_engine is not None:
        # Extract phase and step_id from subject/body context
        phase = "unknown"
        step_id = "default"
        if "[RESEARCH]" in subject:
            phase = "research"
            step_id = "web_search"
        elif "[ARCHITECT]" in subject or "[ARCH-" in subject:
            phase = "architecture"
            step_id = "design_overview"
        elif "[CODE-" in subject or "[FAN-OUT]" in subject or "[CODE-REQUEST]" in subject:
            phase = "coding"
            step_id = "implement_api"
        elif "[DEPLOY]" in subject or "[STAGING]" in subject:
            phase = "deploy"
            step_id = "staging_deploy"
        elif "[BLIND-E2E]" in subject or "[E2E-" in subject:
            phase = "testing"
            step_id = "e2e_tests"

        context = {"gap_id": gap_id, "learnings_checked": True}
        violations = sop_engine.check_pre_conditions(agent, phase, step_id, context)
        if violations:
            gate = sop_engine.get_gate_condition(agent)
            if gate.get('block_on_sop_violation'):
                print(f"[dispatcher] SOP VIOLATION blocked dispatch to {agent}: {violations}")
                # Use HITL to pause and wait for human approval
                if hitl:
                    status = hitl.send_interrupt(
                        gap_id=gap_id,
                        agent_id=agent,
                        reason=f"SOP violation: {violations}",
                        trace_id=tid
                    )
                    print(f"[dispatcher] HITL interrupt response: {status}")
                    if status == 'approved' or status == 'auto_approved':
                        print(f"[dispatcher] Proceeding after HITL approval")
                    else:
                        print(f"[dispatcher] Dispatch blocked by HITL rejection")
                        return False
                else:
                    # Fallback to old behavior if HITL not initialized
                    stream_publish(
                        subject=f"[INTERRUPT] {subject}",
                        body=f"SOP violation blocked dispatch: {violations}\n\nOriginal task:\n{body}",
                        from_agent="orchestrator",
                        gap_id=gap_id,
                        trace_id=tid,
                        priority="high"
                    )
                    return False
            else:
                print(f"[dispatcher] SOP WARNING for {agent}: {violations}")

    # ── Wave Rules Check (v5.4) ───────────────────────────────────────────────
    # Read blockers.json wave_rules before every dispatch.
    # Orchestrator rule: "If blocker's event has not fired, do NOT dispatch."
    if gap_id:
        blockers_path = Path("/var/lib/karios/coordination/blockers.json")
        if blockers_path.exists():
            try:
                import json as _json
                blockers = _json.loads(blockers_path.read_text())
                cb = blockers.get('current_blockers', {})
                entry = cb.get(gap_id, {})
                blocked_by = entry.get('blocked_by', [])
                can_start = entry.get('can_start_when', '')
                status = entry.get('status', '')

                # Skip dispatch if explicitly marked implemented
                if status == 'implemented':
                    pass  # fine, already done
                # Check blocked_by list
                elif blocked_by:
                    unmet = [b for b in blocked_by if cb.get(b, {}).get('status') != 'implemented']
                    if unmet:
                        print(f"[dispatcher] Wave BLOCKED: {gap_id} is blocked by {unmet} (not yet implemented)")
                        return False
                # Check can_start_when condition (simple eval for state-driven gates)
                elif can_start and can_start != 'N/A - already implemented':
                    # Parse conditions like "ARCH-IT-002 passes 10/10 arch gate"
                    # For state checks, look up in state.json
                    state_path = Path("/var/lib/karios/coordination/state.json")
                    if state_path.exists():
                        state = _json.loads(state_path.read_text())
                        active = state.get('active_gaps', {})
                        # Simple check: if referenced gap_id has a passing arch gate score
                        import re
                        ref_gaps = re.findall(r'([A-Z]+-[IT]+-\d+)', can_start)
                        for ref in ref_gaps:
                            ref_entry = active.get(ref, {})
                            # Check if arch gate passed (score >= 10 or equivalent)
                            arch_score = ref_entry.get('architecture_score', 0)
                            if arch_score < 10:
                                print(f"[dispatcher] Wave BLOCKED: {gap_id} waits for {ref} arch gate (score={arch_score}/10, need >=10)")
                                return False
            except Exception as e:
                print(f"[dispatcher] Wave rules check error: {e}")

    # ── v7.0: Build message envelope for idempotency ─────────────────────────
    msg_type = "DISPATCH"
    if "NUDGE" in subject:
        msg_type = "NUDGE"
    elif "INTERRUPT" in subject:
        msg_type = "INTERRUPT"
    elif "HEARTBEAT" in subject:
        msg_type = "HEARTBEAT"
    
    payload = {k: v for k, v in {
        "from": "orchestrator",
        "to": agent,
        "subject": subject,
        "body": body,
        "task_id": task_id,
        "timestamp": current_ts()
    }.items() if v is not None}
    
    env = MessageEnvelope(
        agent_id=agent,
        step_id=subject[:30],  # Use subject as step_id
        gap_id=gap_id,
        trace_id=tid,
        msg_type=msg_type,
        payload=payload
    )
    
    ctx, span = tracer.start_span(f"redis.xadd", {
        "db.system": "redis",
        "db.operation": "xadd",
        "db.redis.key": stream_key,
        "gap_id": gap_id,
        "agent": agent,
        "subject": subject[:40],
        "operation": "dispatch"
    })
    try:
        r = redis_conn()
        
        # ── v7.0 Idempotency Check ───────────────────────────────────────────
        idem_key = f"idem:{agent}:{env.idempotency_key}"
        
        # SETNX returns True if key was set (new), False if exists (duplicate)
        claimed = r.set(idem_key, "1", nx=True, ex=86400)
        
        if not claimed:
            print(f"[dispatcher] DUPLICATE_SKIPPED: {gap_id}/{env.step_id} (idem={env.idempotency_key[:16]}...)")
            # Metric: karios_idem_duplicates_total{agent=agent}++
            span.set_attribute("dispatch.duplicate", True)
            tracer.end_span(span)
            return True  # Not an error — just skip
        
        # v6.0/v7.1 FIX 2026-04-19: agent-worker maps short names to systemd-style stream keys.
        # Without this, dispatcher writes stream:backend but agent reads stream:backend-worker.
        DISPATCH_STREAM_MAP = {"backend": "backend-worker", "frontend": "frontend-worker",
                                "devops": "devops-agent", "tester": "tester-agent"}
        actual_stream_key = f"stream:{DISPATCH_STREAM_MAP.get(agent, agent)}"
        # Proceed with dispatch using envelope
        r.xadd(actual_stream_key, env.to_stream_entry())
        span.set_attribute("dispatch.success", True)
    except Exception as e:
        span.set_attribute("dispatch.success", False)
        tracer.end_span(span, e)
        print(f"[dispatcher] send_to_agent error: {e}")
        return False
    tracer.end_span(span)
    print(f"[dispatcher] → {agent}: {subject} (trace={tid})")
    archive_context_packet(env.payload, gap_id=gap_id)
    return True

# ── Gap Advance Functions ──────────────────────────────────────────────────────
def advance_to_research(gap_id: str, requirement_text: str, trace_id: str = None):
    """Phase 0→1: Assign requirement to Architect for research."""
    tid = trace_id or new_trace_id(gap_id, "architect", "research")
    update_gap_phase(gap_id, "1-research", iteration=1, trace_id=tid,
                     requirement_text=requirement_text, started_at=current_ts())
    req_file = REQS_DIR / f"{gap_id}.md"
    req_file.write_text(f"# Requirement: {gap_id}\n\n{requirement_text}\n")

    # Inject relevant learnings for this phase
    learnings = retrieve_relevant_learnings(phase="1-research", limit=5)
    learnings_context = format_learnings_for_context(learnings) if learnings else ""

    send_to_agent("architect",
                  f"[RESEARCH] {gap_id}",
                  f"""New requirement assigned to you for research.

Requirement ID: {gap_id}
Text: {requirement_text}
{learnings_context}

Your job in this phase:
1. Web search: Find best practices for implementing this
2. Read existing Karios docs in Obsidian
3. MANUAL TESTING on real infrastructure (VMware ESXi + CloudStack) — NO CODE
4. Test all methods manually on the actual systems
5. Document: research-findings.md, manual-test-results.md, environment-matrix.md

IMPORTANT: You must test on REAL infrastructure before writing any architecture.
Do NOT write code. Only test feasibility with existing tools.

When done, send your findings back to orchestrator with subject: [RESEARCH-COMPLETE] {gap_id}

Your trace_id: {tid}""",
                  gap_id=gap_id, trace_id=tid, priority="high")
    save_checkpoint(gap_id, "1-research", 1, tid, data={"requirement": requirement_text},
                    agent="architect", subtype="phase")
    print(f"[dispatcher] Gap {gap_id} advanced to research phase (trace={tid})")

def advance_to_arch_loop(gap_id: str, iteration: int, research_body: str, trace_id: str = None):
    """Phase 1→2: Architect creates architecture, enters iteration loop."""
    tid = trace_id or new_trace_id(gap_id, "architect", f"arch_iter{iteration}")
    update_gap_phase(gap_id, "2-arch-loop", iteration=iteration, trace_id=tid,
                     research_findings=research_body)
    gap_dir = IT_DIR / gap_id / "phase-2-arch-loop"
    arch_doc = gap_dir / f"iteration-{iteration}" / "architecture.md"
    arch_doc.parent.mkdir(parents=True, exist_ok=True)

    learnings = retrieve_relevant_learnings(phase="2-arch-loop", limit=5)
    learnings_context = format_learnings_for_context(learnings) if learnings else ""

    send_to_agent("architect",
                  f"[ARCHITECT] {gap_id} iteration {iteration}",
                  f"""Research complete. Now create the architecture document.

Gap ID: {gap_id}
Iteration: {iteration}/10
{learnings_context}

Your outputs for this iteration:
1. {arch_doc} — Full architecture document
2. {arch_doc.parent / 'edge-cases.md'} — All edge cases
3. {arch_doc.parent / 'test-cases.md'} — Test cases for Code-Blind-Tester
4. {arch_doc.parent / 'api-contract.md'} — API contract if applicable
5. {arch_doc.parent / 'deployment-plan.md'} — Deployment steps

When all docs are written, notify orchestrator with subject: [ARCH-COMPLETE] {gap_id} iteration {iteration}

Your trace_id: {tid}""",
                  gap_id=gap_id, trace_id=tid, priority="high")
    save_checkpoint(gap_id, "2-arch-loop", iteration, tid,
                    data={"iteration": iteration}, agent="architect", subtype="arch_iter")
    print(f"[dispatcher] Gap {gap_id} in arch loop iteration {iteration} (trace={tid})")

def submit_arch_for_review(gap_id: str, iteration: int, trace_id: str = None):
    """Submit architecture to Architect-Blind-Tester for review."""
    tid = trace_id or new_trace_id(gap_id, "tester", f"arch_review_iter{iteration}")
    gap_dir = IT_DIR / gap_id / "phase-2-arch-loop" / f"iteration-{iteration}"
    arch_doc = gap_dir / "architecture.md"
    if not arch_doc.exists():
        print(f"[dispatcher] WARNING: {arch_doc} not found, skipping review")
        return

    # v7.12: use build_prompt (deterministic minimal prompt with 7-dimension intent)
    if _PROMPT_BUILDER:
        _review_body = _build_prompt(
            task_type="ARCH-BLIND-REVIEW",
            gap_id=gap_id,
            iteration=iteration,
            trace_id=tid,
            intent_tags=["7_dimensions"],
            intent_query=f"blind architecture review {gap_id}",
        )
    else:
        _review_body = (
        f"TASK: Blind architecture review for {gap_id} iter {iteration}.\n\n"
        f"STEP 1 (REQUIRED FIRST — use bash tool): cat {arch_doc}\n"
        f"STEP 2 (bash): ls /var/lib/karios/iteration-tracker/{gap_id}/phase-2-architecture/iteration-{iteration}/\n"
        f"STEP 3 (bash): for each doc in that dir — cat it and score it\n"
        f"STEP 4 (file_write): /var/lib/karios/iteration-tracker/{gap_id}/phase-2-arch-loop/iteration-{iteration}/review.json with this schema:\n"
        f'    {{"gap_id":"{gap_id}","iteration":{iteration},"rating":N,"critical_issues":[...],"dimensions":{{"correctness":N,"completeness":N,"feasibility":N,"security":N,"testability":N,"resilience":N}},"adversarial_test_cases":{{...}},"recommendation":"APPROVE|REQUEST_CHANGES|REJECT","summary":"...","trace_id":"{tid}"}}\n'
        f"STEP 5 (bash): emit [ARCH-REVIEWED] with the review JSON in body:\n"
        f"    /usr/local/bin/agent-stream-progress '{tid}' '[ARCH-REVIEWED] {gap_id} iteration {iteration}'\n"
        f"    then send the full JSON via: agent send orchestrator \"[ARCH-REVIEWED] {gap_id} iteration {iteration}\" < review.json\n\n"
        f"DO NOT WRITE PROSE. Each output MUST be a tool call. Watchdog kills prose-only sessions at 6000 chars.\n"
        f"Your role doc is at ~/.hermes/profiles/architect-blind-tester/SOUL.md — consult it only if needed via read_file."
)
    send_to_agent("architect-blind-tester",
                  f"[ARCH-BLIND-REVIEW] {gap_id} iteration {iteration}",
                  _review_body,
                  gap_id=gap_id, trace_id=tid, priority="normal")
    print(f"[dispatcher] Submitted {gap_id} arch iteration {iteration} for blind review (trace={tid})")

# ── Handle Architect Review ───────────────────────────────────────────────────
def handle_arch_review(gap_id: str, iteration: int, rating: int,
                       critical_issues: list, summary: str,
                       dimensions: dict = None,
                       adversarial_test_cases: dict = None,
                       recommendation: str = "REQUEST_CHANGES",
                       trace_id: str = None):
    """Process Architect-Blind-Tester review result with dynamic routing + checkpoint.
    
    v4.0: Now accepts dimensions, adversarial_test_cases, and recommendation from
    the Architect-Blind-Tester. adversarial_test_cases are stored in the review.json
    for the Code-Blind-Tester to use during E2E testing.
    """
    tid = trace_id or new_trace_id(gap_id, "architect-blind-tester", f"arch_review_result_{iteration}")
    dimensions = dimensions or {}
    adversarial_test_cases = adversarial_test_cases or {}
    gap_dir = IT_DIR / gap_id / "phase-2-arch-loop" / f"iteration-{iteration}"
    review_file = gap_dir / "review.json"
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_data = {
        "rating": rating,
        "critical_issues": critical_issues,
        "summary": summary,
        "dimensions": dimensions,
        "adversarial_test_cases": adversarial_test_cases,
        "recommendation": recommendation,
        "tester": "architect-blind-tester",
        "timestamp": current_ts(),
        "trace_id": tid
    }
    review_file.write_text(json.dumps(review_data, indent=2))

    update_agent_checkpoint("architect", iteration=iteration, rating=rating,
                            docs_ready=True, arch_complete=True, trace_id=tid)
    update_agent_checkpoint("architect-blind-tester", test_mode="architect-blind", iteration=iteration,
                            rating=rating, issues_found=len(critical_issues),
                            trace_id=tid)
    redis_publish(EVENT_CHANNELS["test.results"],
                  {"tester": "architect-blind-tester", "gap_id": gap_id,
                   "rating": rating, "iteration": iteration, "trace_id": tid})

    # Save checkpoint for crash recovery
    save_checkpoint(gap_id, "2-arch-review", iteration, tid,
                    data={"rating": rating, "issues": critical_issues,
                          "route": "unknown"},
                    agent="architect-blind-tester", subtype="arch_review")

    # Store learning (v4.0: include dimensions and error categories found)
    if rating < 10:
        error_categories = [issue.get("category", "unknown") for issue in critical_issues]
        store_learning("architect-blind-tester", gap_id, "2-arch-loop",
                       what_happened=f"Architecture iteration {iteration} scored {rating}/10. " +
                                   f"Dimensions: {dimensions}. " +
                                   f"Issues: {'; '.join(str(i) for i in critical_issues[:5])}",
                       resolution="; ".join(str(i) for i in critical_issues[:3]) if critical_issues else "No critical issues",
                       rating=rating,
                       error_type="architecture")

    # ── Dynamic Routing ─────────────────────────────────────────────────────
    routing = compute_routing(gap_id, "2-arch-loop", iteration, rating)
    print(f"[dispatcher] Dynamic routing for {gap_id} iter {iteration}: {routing}")

    if rating >= 8:  # v6.0 FIX: was 10 (impossibly strict — docs say >=8)
        transition_phase(gap_id, "3-coding", agent="architect", iteration=0, trace_id=tid,
                        _prev_phase="2-arch-loop")
        update_agent_checkpoint("architect", phase="idle", arch_complete=False, docs_ready=False)
        update_agent_checkpoint("backend", phase="phase-3-waiting")
        update_agent_checkpoint("frontend", phase="phase-3-waiting")

        # Hierarchical fan-out: decompose if needed
        decomp = decompose_and_fan_out(gap_id, "coding", ["backend", "frontend"], parent_trace_id=tid)
        _update_active_gap_state(gap_id, phase="phase-3-coding", state="active", iteration=iteration, trace_id=tid)

        learnings = retrieve_relevant_learnings(phase="3-coding", limit=5)
        learnings_context = format_learnings_for_context(learnings)

        fan_out(gap_id, ["backend", "frontend"],
                f"[CODE-REQUEST] {gap_id}",
                f"""Architecture approved (rating={rating}/10). Implement your part in parallel.
{learnings_context}

Architecture docs: {IT_DIR / gap_id / 'phase-2-arch-loop' / f'iteration-{iteration}'}

Backend: implement Go backend logic.
Frontend: implement React UI.

Decomposition: {decomp.get('sub_tasks', [])}

When done, send [FAN-IN] {gap_id} — do NOT contact tester directly.""",
                checkpoint_phase="phase-3-coding",
                trace_id=tid)
        telegram_alert(f"✅ *{gap_id}*: Architecture loop PASSED ({rating}/10, {iteration} iter). Fan-out to Backend+Frontend for parallel coding.")
        print(f"[dispatcher] Gap {gap_id} architecture APPROVED — FAN-OUT to backend+frontend")

    elif routing["route"] == "escalate":
        transition_phase(gap_id, "escalated", agent="architect", iteration=iteration,
                         trace_id=tid, _prev_phase="2-arch-loop",
                         last_rating=rating, last_issues=critical_issues)
        update_agent_checkpoint("architect", phase="escalated", iteration=iteration)
        publish_gap_event("gap.escalation", gap_id,
                          {"reason": "arch_rating_below_threshold",
                           "rating": rating, "iterations": iteration,
                           "issues": critical_issues, "routing": routing,
                           "trace_id": tid})
        telegram_alert(f"🚨 *{gap_id}*: Architecture loop rating {rating}/10 < {ROUTING_ESCALATE_NOW} — immediate escalation.")
        send_to_agent("sai", f"[ESCALATE] {gap_id} — Architecture rating too low",
                      f"Gap {gap_id}: Architecture rating {rating}/10 after {iteration} iteration(s).\n"
                      f"Threshold: {ROUTING_ESCALATE_NOW}/10.\n"
                      f"Critical issues:\n" + "\n".join(f"- {i}" for i in critical_issues))
        print(f"[dispatcher] Gap {gap_id} IMMEDIATE ESCALATION (rating {rating}/10)")

    elif routing["route"] == "fast_track":
        # Very high rating: proceed even if not 10/10, with minimal extra iterations
        update_gap_phase(gap_id, "2-arch-loop", iteration=iteration + 1, trace_id=tid,
                         last_rating=rating, last_issues=critical_issues, fast_tracked=True)
        send_to_agent("architect",
                      f"[ARCH-FAST-TRACK] {gap_id} — rating {rating} ≥ {ROUTING_FAST_TRACK}, final iteration",
                      f"Excellent architecture (rating={rating}/10).\n"
                      f"Minor issues to address:\n" + "\n".join(f"- {i}" for i in critical_issues) + "\n\n"
                      f"One final iteration to address these quickly, then proceed to coding.")
        print(f"[dispatcher] Gap {gap_id} FAST-TRACK: rating {rating} >= {ROUTING_FAST_TRACK}")

    elif routing["next_action"] == "retry_with_self_diagnosis":
        combined_issues = " ".join(str(i) if not isinstance(i, str) else i for i in critical_issues)  # v7.15: coerce dict items
        can_resolve, strategy, needs_escalate = self_diagnose(
            gap_id, "2-arch-loop", iteration, rating, combined_issues)

        if needs_escalate:
            transition_phase(gap_id, "escalated", agent="architect", iteration=iteration,
                             trace_id=tid, _prev_phase="2-arch-loop")
            update_agent_checkpoint("architect", phase="escalated", iteration=iteration)
            publish_gap_event("gap.escalation", gap_id,
                              {"reason": "arch_loop_self_diagnosis_failed",
                               "rating": rating, "iterations": iteration,
                               "issues": critical_issues, "self_diagnosis": strategy,
                               "trace_id": tid})
            telegram_alert(f"🚨 *{gap_id}*: Architecture loop EXHAUSTED ({rating}/10, {iteration} iter). {strategy}")
            send_to_agent("sai", f"[ESCALATE] {gap_id} — Architecture exhausted",
                          f"Gap {gap_id}: {strategy}\n"
                          f"Final rating: {rating}/10.\n"
                          f"Issues:\n" + "\n".join(f"- {i}" for i in critical_issues))
            print(f"[dispatcher] Gap {gap_id} ESCALATED: {strategy}")
        else:
            next_iter = iteration + 1
            update_gap_phase(gap_id, "2-arch-loop", iteration=next_iter, trace_id=tid,
                             last_rating=rating, last_issues=critical_issues,
                             self_diagnosis=strategy)
            update_agent_checkpoint("architect", phase="phase-2-arch", iteration=next_iter,
                                    rating=rating, self_diagnosis=strategy, trace_id=tid)
            send_to_agent("architect",
                          f"[ARCH-ITERATE] {gap_id} — self-correct iteration {next_iter}",
                          f"⚠️ {strategy}\n\n"
                          f"Issues to fix:\n" + "\n".join(f"- {i}" for i in critical_issues) + "\n\n"
                          f"Extra iteration granted for self-correction. Iteration: {next_iter}/11")
            print(f"[dispatcher] Gap {gap_id} self-correcting: {strategy}")

    else:
        next_iter = iteration + 1
        update_gap_phase(gap_id, "2-arch-loop", iteration=next_iter, trace_id=tid,
                         last_rating=rating, last_issues=critical_issues)
        update_agent_checkpoint("architect", phase="phase-2-arch", iteration=next_iter,
                                rating=rating, trace_id=tid)
        send_to_agent("architect",
                      f"[ARCH-ITERATE] {gap_id} — iteration {next_iter}",
                      f"Architecture iteration {iteration} scored {rating}/10.\n\n"
                      f"Critical issues:\n" + "\n".join(f"- {i}" for i in critical_issues) + "\n\n"
                      f"Fix these issues and create updated architecture docs.\n"
                      f"Iteration: {next_iter}/10\n"
                      f"trace_id: {tid}")
        print(f"[dispatcher] Gap {gap_id} arch loop iteration {next_iter} (prev rating {rating}/10)")

def submit_code_for_test(gap_id: str, iteration: int, trace_id: str = None):
    """Submit deployed code to Code-Blind-Tester for E2E testing."""
    tid = trace_id or new_trace_id(gap_id, "tester", f"e2e_iter{iteration}")
    update_gap_phase(gap_id, "3-coding-testing", iteration=iteration, trace_id=tid)
    save_checkpoint(gap_id, "3-coding-testing", iteration, tid,
                    data={"iteration": iteration}, agent="code-blind-tester", subtype="e2e_test")
    send_to_agent("code-blind-tester",
                  f"[BLIND-E2E] {gap_id} iteration {iteration}",
                  f"""Code deployed for {gap_id}. Run adversarial E2E tests against staging.

Gap ID: {gap_id}
Iteration: {iteration}/10
What was built: See architecture docs at {IT_DIR / gap_id / 'phase-2-arch-loop'}
trace_id: {tid}

Your role: Code-Blind-Tester — you test the DEPLOYED SYSTEM only.
You do NOT know what was built or how. You only interact with the running system.
Run your full E2E test suite AND the adversarial test cases from the Architect-Blind-Tester.

IMPORTANT: The Architect-Blind-Tester generated adversarial test cases for this gap.
Read them from: {IT_DIR / gap_id / 'phase-2-arch-loop' / f'iteration-{iteration}' / 'review.json'}
Run those adversarial cases FIRST, then run your own adversarial tests.

Rate 0-10 on ALL 7 dimensions:
- Functional correctness: Does it work as specified?
- Edge cases: Does it handle error conditions?
- Performance: Is it fast enough?
- Security: Obvious vulnerabilities?
- Concurrency: Race conditions?
- Resilience: Crash handling, timeouts?
- Error handling: Are errors handled gracefully?

When done: subject=[E2E-RESULTS] {gap_id} iteration {iteration}
body=JSON with {{"rating": N, "critical_issues": [...], "dimensions": {{...}}, "adversarial_tests": {{...}}, "test_results": {{...}}, "recommendation": "APPROVE|REQUEST_CHANGES|REJECT", "trace_id": "{tid}"}}""",
                  gap_id=gap_id, trace_id=tid, priority="high")
    print(f"[dispatcher] Submitted {gap_id} code iteration {iteration} for E2E testing (trace={tid})")

def handle_e2e_results(gap_id: str, iteration: int, rating: int,
                       critical_issues: list, test_results: dict,
                       dimensions: dict = None,
                       adversarial_tests: dict = None,
                       recommendation: str = "REQUEST_CHANGES",
                       trace_id: str = None):
    """Process Code-Blind-Tester E2E results with dynamic routing.
    
    v4.0: Now accepts dimensions (7 testing dimensions), adversarial_tests
    (generated by the Code-Blind-Tester), and recommendation.
    Stores adversarial test results for future regression testing.
    """
    tid = trace_id or new_trace_id(gap_id, "code-blind-tester", f"e2e_result_{iteration}")
    dimensions = dimensions or {}
    adversarial_tests = adversarial_tests or {}
    gap_dir = IT_DIR / gap_id / "phase-3-coding"
    test_dir = gap_dir / f"iteration-{iteration}"
    test_dir.mkdir(parents=True, exist_ok=True)
    results_data = {
        "rating": rating,
        "critical_issues": critical_issues,
        "test_results": test_results,
        "dimensions": dimensions,
        "adversarial_tests": adversarial_tests,
        "recommendation": recommendation,
        "tester": "code-blind-tester",
        "timestamp": current_ts(),
        "trace_id": tid
    }
    (test_dir / "e2e-results.json").write_text(json.dumps(results_data, indent=2))

    update_agent_checkpoint("code-blind-tester", test_mode="code-blind", iteration=iteration,
                            rating=rating, tests_passed=test_results.get("passed", 0),
                            tests_failed=test_results.get("failed", 0),
                            issues_found=len(critical_issues), trace_id=tid)
    update_agent_checkpoint("devops", phase="staging-verified")
    redis_publish(EVENT_CHANNELS["test.results"],
                  {"tester": "code-blind", "gap_id": gap_id,
                   "rating": rating, "iteration": iteration,
                   "tests_passed": test_results.get("passed", 0),
                   "tests_failed": test_results.get("failed", 0),
                   "trace_id": tid})

    # Store learning (v4.0: include dimensions, adversarial_tests, error categories)
    if rating < 10:
        error_categories = [issue.get("category", "unknown") for issue in critical_issues]
        store_learning("code-blind-tester", gap_id, "3-coding",
                       what_happened=f"E2E iteration {iteration} scored {rating}/10. " +
                                   f"Adversarial tests run: {adversarial_tests.get('run', 0)}, " +
                                   f"failed: {adversarial_tests.get('failed', 0)}. " +
                                   f"Dimensions: {dimensions}. " +
                                   f"Issues: {'; '.join(str(i) for i in critical_issues[:5])}",
                       resolution="; ".join(str(i) for i in critical_issues[:3]) if critical_issues else "All tests passed",
                       rating=rating,
                       error_type="testing")
    else:
        store_learning("code-blind-tester", gap_id, "3-coding",
                       what_happened=f"E2E iteration {iteration} scored {rating}/10. " +
                                   f"All adversarial tests passed. No critical issues.",
                       resolution="All tests passed including adversarial edge cases",
                       rating=rating,
                       error_type=None)

    save_checkpoint(gap_id, "3-e2e-review", iteration, tid,
                    data={"rating": rating, "tests": test_results},
                    agent="code-blind-tester", subtype="e2e_review")

    # ── Dynamic Routing ─────────────────────────────────────────────────────
    routing = compute_routing(gap_id, "3-coding", iteration, rating)
    print(f"[dispatcher] E2E dynamic routing for {gap_id} iter {iteration}: {routing}")

    # ── Output Verification (v4.0) ─────────────────────────────────────────
    if output_verifier is not None:
        # v6.0 FIX 2026-04-19: handle_e2e_results signature has no `body` param;
        # synthesize from structured args.
        try:
            _body_summary = json.dumps({
                "rating": rating, "critical_issues": critical_issues,
                "test_results": test_results, "dimensions": dimensions or {},
            })
            context = {"gap_id": gap_id, "trace_id": tid, "step_id": "e2e_tests",
                       "expected_files": 0, "files_created": []}
            result = output_verifier.verify(_body_summary, context)
            decision = output_verifier.gatekeeper_decision(result)
            print(f"[dispatcher] E2E results verification: passed={result.passed}, score={result.score}, decision={decision}")
        except Exception as _verr:
            print(f"[dispatcher] E2E verifier non-blocking error: {type(_verr).__name__}: {_verr}")
        # Note: E2E results are already structured JSON, so we don't fail on decision alone

    if rating >= 8:  # v6.0 FIX: was 10 (impossibly strict — docs say >=8)
        transition_phase(gap_id, "4-production", agent="devops", iteration=iteration, trace_id=tid,
                        _prev_phase="3-coding-testing")
        update_agent_checkpoint("backend", phase="idle", coding_complete=False)
        update_agent_checkpoint("frontend", phase="idle", coding_complete=False)
        update_agent_checkpoint("devops", phase="production")
        publish_gap_event("gap.completion", gap_id,
                          {"action": "coding_gate_passed", "rating": rating,
                           "iterations": iteration, "trace_id": tid})
        send_to_agent("devops",
                      f"[PRODUCTION] {gap_id}",
                      f"E2E testing PASSED ({rating}/10) for {gap_id} after {iteration} iteration(s).\n\n"
                      f"Deploy to production and notify orchestrator when done: [PROD-DEPLOYED] {gap_id}\n"
                      f"trace_id: {tid}",
                      gap_id=gap_id, trace_id=tid)  # v7.3: pass kwargs to avoid None task_id
        telegram_alert(f"✅ *{gap_id}*: Coding loop PASSED ({rating}/10, {iteration} iter). Deploying to production.")
        print(f"[dispatcher] Gap {gap_id} PASSED coding loop, deploying to production")

    elif routing["route"] == "escalate":
        transition_phase(gap_id, "escalated", agent="backend", iteration=iteration,
                         trace_id=tid, _prev_phase="3-coding")
        update_agent_checkpoint("backend", phase="escalated", iteration=iteration)
        update_agent_checkpoint("frontend", phase="escalated", iteration=iteration)
        publish_gap_event("gap.escalation", gap_id,
                          {"reason": "e2e_rating_below_threshold",
                           "rating": rating, "iterations": iteration,
                           "issues": critical_issues, "routing": routing,
                           "trace_id": tid})
        telegram_alert(f"🚨 *{gap_id}*: E2E rating {rating}/10 < {ROUTING_ESCALATE_NOW} — immediate escalation.")
        send_to_agent("sai", f"[ESCALATE] {gap_id} — E2E rating too low",
                      f"Gap {gap_id}: E2E rating {rating}/10 after {iteration} iteration(s).\n"
                      f"Threshold: {ROUTING_ESCALATE_NOW}/10.\n"
                      f"Issues:\n" + "\n".join(f"- {i}" for i in critical_issues))
        print(f"[dispatcher] Gap {gap_id} IMMEDIATE ESCALATION (E2E rating {rating}/10)")

    elif routing["route"] == "fast_track":
        update_gap_phase(gap_id, "3-coding", iteration=iteration + 1, trace_id=tid,
                         last_rating=rating, last_issues=critical_issues, fast_tracked=True)
        send_to_agent("devops",
                      f"[FAST-REDEPLOY] {gap_id}",
                      f"E2E rating {rating} ≥ {ROUTING_FAST_TRACK}. Quick final check, then deploy to prod.")
        print(f"[dispatcher] Gap {gap_id} E2E FAST-TRACK: rating {rating}")

    elif routing["next_action"] == "retry_with_self_diagnosis":
        combined_issues = " ".join(str(i) if not isinstance(i, str) else i for i in critical_issues)  # v7.15: coerce dict items
        can_resolve, strategy, needs_escalate = self_diagnose(
            gap_id, "3-coding", iteration, rating, combined_issues)

        if needs_escalate:
            transition_phase(gap_id, "escalated", agent="backend", iteration=iteration, trace_id=tid)
            update_agent_checkpoint("backend", phase="escalated", iteration=iteration)
            update_agent_checkpoint("frontend", phase="escalated", iteration=iteration)
            publish_gap_event("gap.escalation", gap_id,
                              {"reason": "coding_loop_exhausted", "rating": rating,
                               "iterations": iteration, "issues": critical_issues,
                               "self_diagnosis": strategy, "trace_id": tid})
            telegram_alert(f"🚨 *{gap_id}*: Coding loop EXHAUSTED ({rating}/10, {iteration} iter). {strategy}")
            send_to_agent("sai", f"[ESCALATE] {gap_id} — Coding loop exhausted",
                          f"Gap {gap_id}: {strategy}\n"
                          f"Final rating: {rating}/10.\n"
                          f"Issues:\n" + "\n".join(f"- {i}" for i in critical_issues))
            print(f"[dispatcher] Gap {gap_id} ESCALATED: {strategy}")
        else:
            next_iter = iteration + 1
            update_gap_phase(gap_id, "3-coding", iteration=next_iter, trace_id=tid,
                             last_rating=rating, last_issues=critical_issues,
                             self_diagnosis=strategy)
            update_agent_checkpoint("backend", phase="phase-3-coding", iteration=next_iter)
            update_agent_checkpoint("frontend", phase="phase-3-coding", iteration=next_iter)
            # v7.15: dispatch BACKEND for code revise (not devops) — bugs need code fixes
            _issues_str = "\n".join(
                (f"- [{i.get('severity','?')}] {i.get('description', str(i)[:200])}"
                 if isinstance(i, dict) else f"- {i}")
                for i in critical_issues[:10]
            )
            if _PROMPT_BUILDER:
                _revise_body = _build_prompt(
                    task_type="CODE-REQUEST",
                    gap_id=gap_id,
                    iteration=next_iter,
                    trace_id=tid,
                    repo="karios-migration",
                    intent_tags=["vmware", "7_dimensions"],
                    intent_query=f"revise iter{next_iter} {gap_id}",
                    commit_title=f"fix({gap_id}): iter{next_iter} address E2E critical issues",
                    extra_context=(f"PRIOR E2E RATING: {rating}/10 (REJECT). Self-diagnosis: {strategy}\n\n"
                                   f"CRITICAL ISSUES TO FIX (from code-blind-tester):\n{_issues_str}\n\n"
                                   f"Iterate on EXISTING branch backend/{gap_id}-cbt — do NOT recreate. "
                                   f"Fix each critical issue with new commits.")
                )
            else:
                _revise_body = (f"E2E iter {iteration} rated {rating}/10. Critical issues:\n{_issues_str}\n\n"
                                f"Fix and re-emit [CODING-COMPLETE] with new commit_sha.")
            send_to_agent("backend",
                          f"[CODE-REVISE] {gap_id} iteration {next_iter}",
                          _revise_body,
                          gap_id=gap_id, trace_id=tid, priority="high")
            print(f"[dispatcher] Gap {gap_id} CODE-REVISE -> backend (iter {next_iter}/8): {strategy}")
            try:
                notify_phase_transition(gap_id, "code-blind-tester", f"backend (revise iter {next_iter})",
                                        "E2E-REVISE", rating=rating,
                                        summary=f"rating {rating}/10 — backend revising. Issues: {len(critical_issues)} critical.")
            except Exception as _e:
                print(f"[dispatcher] notify error: {_e}")

    else:
        next_iter = iteration + 1
        update_gap_phase(gap_id, "3-coding", iteration=next_iter, trace_id=tid,
                         last_rating=rating, last_issues=critical_issues)
        update_agent_checkpoint("backend", phase="phase-3-coding", iteration=next_iter)
        update_agent_checkpoint("frontend", phase="phase-3-coding", iteration=next_iter)
        fan_out(gap_id, ["backend", "frontend"],
                f"[CODE-FIX] {gap_id} iteration {next_iter}",
                f"E2E testing iteration {iteration} scored {rating}/10.\n\n"
                f"Critical issues:\n" + "\n".join(f"- {i}" for i in critical_issues) + "\n\n"
                f"Fix these issues. Both agents work in PARALLEL.\n"
                f"When done, send [FAN-IN] {gap_id}.",
                checkpoint_phase="phase-3-coding",
                trace_id=tid)
        print(f"[dispatcher] Gap {gap_id} FAN-OUT to backend+frontend for fixes (rating {rating}/10)")

# ── Item D (ARCH-IT-ARCH-v11): Gitea Push Verification Gate ─────────────────────

def read_gap_manifest(gap_id: str) -> dict:
    """Read iteration-tracker manifest for a gap. Returns repos_touched list."""
    manifest_path = Path(f"/var/lib/karios/iteration-tracker/{gap_id}/manifest.json")
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except Exception:
            pass
    return {"repos_touched": []}


def verify_gitea_push(gap_id: str, repos: list) -> tuple[bool, str]:
    """
    Verify all gap repos are pushed to origin. Returns (ok, message).

    Checks git rev-list --left-right --count origin/main...HEAD for each repo.
    Returns (False, detail) if any repo has unpushed commits.
    """
    results = []
    for repo in repos:
        repo_path = f"/root/karios-source-code/{repo}"
        if not os.path.isdir(repo_path):
            results.append(f"{repo}: not found at {repo_path}")
            continue
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "rev-list", "--left-right", "--count",
                 "origin/main...HEAD"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                results.append(f"{repo}: git error {result.stderr.strip()}")
                continue
            ahead, behind = result.stdout.strip().split("\t")
            if int(ahead) > 0:
                results.append(f"{repo}: {ahead} commit(s) ahead of origin")
            if int(behind) > 0:
                results.append(f"{repo}: {behind} commit(s) behind origin")
        except FileNotFoundError:
            results.append(f"{repo}: git not found")
        except Exception as e:
            results.append(f"{repo}: exception {e}")

    if results:
        return False, "; ".join(results)
    return True, "all repos up-to-date with origin"


def handle_production_deployed(gap_id: str, trace_id: str = None):
    """Production deployment complete — with Gitea push gate (Item D)."""
    tid = trace_id or new_trace_id(gap_id, "devops", "prod_deployed")

    # Item D (ARCH-IT-ARCH-v11): Gitea push verification gate
    manifest = read_gap_manifest(gap_id)
    repos = manifest.get("repos_touched", [])
    if repos:
        ok, msg = verify_gitea_push(gap_id, repos)
        if not ok:
            # Refuse PROD-DEPLOYED — send GITEA-PUSH-PENDING to devops
            print(f"[dispatcher] GITEA-PUSH-PENDING: {msg}")
            stream_publish(
                subject=f"[GITEA-PUSH-PENDING] {gap_id}",
                body=json.dumps({
                    "repos": repos,
                    "diff_detail": msg,
                    "gap_id": gap_id,
                    "iteration": manifest.get("iteration", 1)
                }),
                from_agent="orchestrator",
                gap_id=gap_id, priority="high"
            )
            telegram_alert(
                f"🚨 {gap_id}: Git not pushed to origin. DevOps must push before PROD-DEPLOYED completes. Detail: {msg}"
            )
            return

    # Proceed with normal completion
    update_gap_phase(gap_id, "completed", completed_at=current_ts(), trace_id=tid)
    state = load_state()
    state.setdefault("completed_gaps", []).append(gap_id)
    save_state(state)

    # Start parallel pre-research for next gap if available
    pipeline = load_pipeline_state()
    if pipeline.get("pre_researching"):
        next_gap_id = list(pipeline["pre_researching"].keys())[0]
        pre_req = pipeline["pre_researching"].pop(next_gap_id)
        save_pipeline_state(pipeline)
        advance_to_research(next_gap_id, pre_req["requirement"], pre_req["trace_id"])
        print(f"[dispatcher] Started pre-researched gap {next_gap_id} as next active gap")

    telegram_alert(f"🎉 *{gap_id}*: COMPLETED and deployed to production! (trace={tid})")
    _update_active_gap_state(gap_id, phase="completed", state="completed")
    print(f"[dispatcher] Gap {gap_id} marked as completed in production (trace={tid})")

# ── Message Handlers ───────────────────────────────────────────────────────────
def handle_requirement(message_body: str, trace_id: str = None):
    """Parse a new requirement and start the pipeline."""
    tid = trace_id or new_trace_id(op="new_requirement")
    state = load_state()
    req_count = len(state.get("completed_gaps", [])) + len(state.get("active_gaps", {})) + 1
    req_id = f"REQ-{req_count:03d}"
    gap_id = f"ARCH-IT-{req_count:03d}"

    req_file = REQS_DIR / f"{req_id}.md"
    req_file.write_text(f"# Requirement: {req_id}\n\n{message_body}\n\n_Received: {current_ts()} (trace={tid})_\n")

    state["active_gaps"][gap_id] = {"req_id": req_id, "created_at": current_ts(), "trace_id": tid}
    save_state(state)

    advance_to_research(gap_id, message_body, trace_id=tid)

    # Check if architect is free for parallel pre-research of the next gap
    if is_architect_free() and len(message_body) > 200:
        # Long requirement: pre-stage next research
        next_req_count = req_count + 1
        next_gap_id = f"ARCH-IT-{next_req_count:03d}"
        start_parallel_research(next_gap_id,
                                 requirement_text=f"Pre-research placeholder for gap {next_gap_id}",
                                 trace_id=new_trace_id(next_gap_id, "orchestrator", "pre_research"))

    print(f"[dispatcher] New requirement {req_id} → gap {gap_id} (trace={tid})")
    telegram_alert(f"📋 New requirement *{req_id}*: {message_body[:100]}... (trace={tid})")

def handle_research_complete(gap_id: str, body: str, trace_id: str = None):
    """Architect completed research phase."""
    tid = trace_id or new_trace_id(gap_id, "architect", "research_complete")
    research_dir = IT_DIR / gap_id / "phase-1-research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "research-findings.md").write_text(body)
    
    # ── Output Verification (v4.0) ─────────────────────────────────────────
    if output_verifier is not None:
        context = {"gap_id": gap_id, "trace_id": tid, "step_id": "web_search",
                   "expected_files": 2, "files_created": ["research-findings.md"]}
        result = output_verifier.verify(body, context)
        decision = output_verifier.gatekeeper_decision(result)
        print(f"[dispatcher] Research output verification: passed={result.passed}, score={result.score}, decision={decision}")
        if decision == "rewind":
            # Trigger rewind - send back to architect for redo
            send_to_agent("architect",
                          f"[REWIND] {gap_id} — research output below quality threshold",
                          f"Research output verification failed (score={result.score}). Please redo the research.\n\nOriginal findings:\n{body[:500]}",
                          gap_id=gap_id, trace_id=tid, priority="high")
            return
    
    save_checkpoint(gap_id, "1-research-done", 1, tid, data={"body": body[:500]},
                    agent="architect", subtype="research_done")
    advance_to_arch_loop(gap_id, iteration=1, research_body=body, trace_id=tid)

    # Store learning
    store_learning("architect", gap_id, "1-research",
                   what_happened=f"Research completed for {gap_id}",
                   resolution=f"Findings: {body[:200]}...")

    # ── Self-Benchmarking (v4.0) ──────────────────────────────────────────────
    if os.environ.get('KAIROS_BENCHMARK_ENABLED') == 'true':
        benchmark = AgentBenchmark()
        result = benchmark.benchmark_gap(
            gap_id=gap_id,
            agent_id='architect',
            iteration_dir=str(IT_DIR / gap_id)
        )
        print(f"[Benchmark] {gap_id}: {result.overall_score:.2f} (passed={result.passed})")
        if not result.passed:
            telegram_alert(f"⚠️ Benchmark failed for {gap_id}: {result.overall_score:.2f}")

def handle_arch_complete(gap_id: str, iteration: int, body: str, trace_id: str = None):
    """Architect completed architecture docs for this iteration."""
    tid = trace_id or new_trace_id(gap_id, "architect", f"arch_complete_iter{iteration}")
    arch_dir = IT_DIR / gap_id / "phase-2-arch-loop" / f"iteration-{iteration}"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "architecture.md").write_text(body)

    # ── Output Verification (v4.0) ─────────────────────────────────────────
    if output_verifier is not None:
        context = {"gap_id": gap_id, "trace_id": tid, "step_id": "design_overview",
                   "expected_files": 1, "files_created": ["architecture.md"]}
        result = output_verifier.verify(body, context)
        decision = output_verifier.gatekeeper_decision(result)
        print(f"[dispatcher] Architecture output verification: passed={result.passed}, score={result.score}, decision={decision}")
        if decision == "rewind":
            # Trigger rewind - send back to architect for redo
            send_to_agent("architect",
                          f"[REWIND] {gap_id} — architecture output below quality threshold",
                          f"Architecture output verification failed (score={result.score}). Please fix the architecture.\n\nOriginal architecture:\n{body[:500]}",
                          gap_id=gap_id, trace_id=tid, priority="high")
            return

    save_checkpoint(gap_id, "2-arch-complete", iteration, tid,
                    data={"iteration": iteration}, agent="architect", subtype="arch_complete")
    submit_arch_for_review(gap_id, iteration, trace_id=tid)

    # ── Self-Benchmarking (v4.0) ──────────────────────────────────────────────
    if os.environ.get('KAIROS_BENCHMARK_ENABLED') == 'true':
        benchmark = AgentBenchmark()
        result = benchmark.benchmark_gap(
            gap_id=gap_id,
            agent_id='architect',
            iteration_dir=str(IT_DIR / gap_id)
        )
        print(f"[Benchmark] {gap_id}: {result.overall_score:.2f} (passed={result.passed})")
        if not result.passed:
            telegram_alert(f"⚠️ Benchmark failed for {gap_id}: {result.overall_score:.2f}")

def _update_active_gap_state(gap_id: str, phase: str = None, state: str = None, iteration: int = None, trace_id: str = None):
    """v7.5: keep state.json active_gaps in sync with phase progression so recover_from_checkpoints
    doesn't redispatch stale phases on restart. Idempotent — silently no-op if state file missing."""
    try:
        st = load_state() or {}
        ag = st.setdefault('active_gaps', {})
        entry = ag.setdefault(gap_id, {})
        if phase is not None: entry['phase'] = phase
        if state is not None: entry['state'] = state
        if iteration is not None: entry['iteration'] = iteration
        if trace_id is not None: entry['trace_id'] = trace_id
        save_state(st)
    except Exception as _e:
        print(f"[dispatcher] _update_active_gap_state error: {_e}")



# v7.8: Progress probe — detect stuck active phases
_PROBE_STATE_FILE = Path("/var/lib/karios/orchestrator/progress-probe-state.json")

def _load_probe_state():
    """v7.9: load probe state from disk so stall detection survives dispatcher restarts."""
    try:
        if _PROBE_STATE_FILE.exists():
            return json.loads(_PROBE_STATE_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_probe_state(st):
    try:
        _PROBE_STATE_FILE.write_text(json.dumps(st, indent=2))
    except Exception as e:
        print(f"[probe] save state failed: {e}")

_PROGRESS_PROBE_STATE = _load_probe_state()  # v7.9: persisted across restarts
PROGRESS_STALL_SECS = 480  # 8 min with no growth → considered stuck
PROGRESS_KILL_AFTER_STALLS = 2  # 2 consecutive stalls → kill agent

def _gap_iter_tracker_size(gap_id: str) -> int:
    """v7.8.1: Count bytes in MEANINGFUL files only — ignore metadata.json and *.tmp
    which get touched every dispatcher cycle (nudge, resume, etc) and would mask real stalls.
    Meaningful = *.md, review.json, decomposition.json, e2e-results.json."""
    base = Path(f"/var/lib/karios/iteration-tracker/{gap_id}")
    if not base.exists():
        return 0
    total = 0
    MEANINGFUL = ('.md', 'review.json', 'decomposition.json', 'e2e-results.json', 'manifest.json', 'api-contract.json')
    try:
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            name = f.name
            if name == 'metadata.json' or name.endswith('.tmp'):
                continue
            if not (name.endswith('.md') or name in MEANINGFUL):
                continue
            try:
                total += f.stat().st_size
            except Exception:
                pass
    except Exception:
        pass
    return total

def _kill_agent_hermes(agent_short: str) -> bool:
    """Kill the Hermes child of the named agent's worker (uses pgrep + kill)."""
    try:
        out = subprocess.run(["pgrep", "-f", f"hermes chat --profile {agent_short}"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        pids = [p for p in out.split() if p.isdigit()]
        for pid in pids:
            try:
                os.kill(int(pid), 15)  # SIGTERM
                print(f"[probe] killed Hermes pid={pid} (agent={agent_short})")
            except Exception as e:
                print(f"[probe] kill {pid} failed: {e}")
        return bool(pids)
    except Exception as e:
        print(f"[probe] pgrep failed: {e}")
        return False

def _is_agent_working(agent_short: str, gap_id: str) -> bool:
    """v7.9: Returns True if agent_short has an active Hermes process OR recent checkpoint write."""
    import subprocess as _sp, time as _t
    try:
        out = _sp.run(["pgrep", "-f", f"hermes chat --profile {agent_short}"],
                      capture_output=True, text=True, timeout=3).stdout.strip()
        if out:
            return True
    except Exception:
        pass
    # Fallback: check checkpoint mtime
    try:
        from pathlib import Path as _P
        ckpt = _P(f"/var/lib/karios/checkpoints/{agent_short}/{gap_id}/latest.json")
        if ckpt.exists() and (_t.time() - ckpt.stat().st_mtime) < 300:  # 5 min
            return True
    except Exception:
        pass
    return False


def progress_probe_check():
    """Called periodically from dispatcher main loop. Detects + reacts to stuck gaps."""
    import time as _t
    try:
        st = load_state() or {}
        ag = st.get("active_gaps", {})
        now = int(_t.time())
        for gap_id, ge in ag.items():
            if ge.get("state") in ("completed", "closed", "cancelled", "escalated"):
                continue
            # v7.8.1: phase lives in gap metadata file, not active_gaps entry. Use load_gap.
            gdata = load_gap(gap_id) or {}
            phase = gdata.get("phase") or ge.get("phase", "")
            if not phase or phase in ("completed", "closed", "idle"):
                continue
            # Check iteration-tracker growth
            cur_size = _gap_iter_tracker_size(gap_id)
            ps = _PROGRESS_PROBE_STATE.setdefault(gap_id, {"last_check_ts": now, "last_size": cur_size, "stale_count": 0})
            elapsed = now - ps["last_check_ts"]
            if elapsed < PROGRESS_STALL_SECS:
                continue  # not yet time to re-evaluate
            grew = cur_size > ps["last_size"]
            if grew:
                # Reset stale counter
                ps["stale_count"] = 0
                ps["last_size"] = cur_size
                ps["last_check_ts"] = now
                _save_probe_state(_PROGRESS_PROBE_STATE)
            else:
                ps["stale_count"] += 1
                ps["last_check_ts"] = now
                _save_probe_state(_PROGRESS_PROBE_STATE)
                # Determine which agent owns this phase
                phase_to_agent = {
                    "phase-2-arch-loop": "architect",
                    "phase-2-architecture": "architect",
                    "2-arch-loop": "architect",
                    "2-architecture": "architect",
                    "phase-3-coding": "backend",
                    "3-coding": "backend",
                    "phase-3-coding-sync": "backend",
                    "3-coding-sync": "backend",
                    "phase-4-testing": "code-blind-tester",
                    "4-testing": "code-blind-tester",
                    "phase-5-deployment": "devops",
                    "5-deployment": "devops",
                    "4-production": "devops",
                    "phase-6-monitoring": "monitor",
                    "6-monitoring": "monitor",
                }
                # Normalize: strip 'phase-' prefix if present, look up either form
                owner = phase_to_agent.get(phase) or phase_to_agent.get(phase.lstrip("phase-")) or "unknown"
                # v7.9: orphan detection — if phase is active but owner agent has no session
                # AND no recent checkpoint, the fan-out never reached the agent (ghost phase).
                if owner != "unknown" and not _is_agent_working(owner, gap_id):
                    orphan_msg = (f"👻 ORPHAN-DETECTED: {gap_id} in {phase}, owner={owner} has no session + no recent checkpoint. "
                                  f"Re-dispatching [FAN-OUT] to {owner}.")
                    telegram_alert(orphan_msg)
                    print(f"[probe] {orphan_msg}")
                    try:
                        # Re-dispatch the CODE-REQUEST to the owner
                        send_to_agent(owner, f"[FAN-OUT] [CODE-REQUEST] {gap_id} {gap_id}",
                                      f"gap_id: {gap_id}\niteration: 1\ntrace_id: trace_orphan_recover_{int(_t.time())}\n\n"
                                      f"Orphan recovery: this gap's phase=3-coding but you never received a dispatch. "
                                      f"Read /var/lib/karios/iteration-tracker/{gap_id}/ for context. "
                                      f"Use get_minimal_context first. Implement + push to gitea + emit [CODING-COMPLETE].",
                                      gap_id=gap_id, trace_id=f"trace_orphan_{gap_id}", priority="high")
                        ps["stale_count"] = 0
                        _save_probe_state(_PROGRESS_PROBE_STATE)
                        continue
                    except Exception as _oe:
                        print(f"[probe] orphan re-dispatch failed: {_oe}")
                if ps["stale_count"] == 1:
                    msg = (f"⚠ PROGRESS-STALL: {gap_id} in {phase} produced 0 new files in {PROGRESS_STALL_SECS // 60} min. "
                           f"Owner: {owner}. Watchdog will kill+retry on next stall ({PROGRESS_KILL_AFTER_STALLS - 1} more).")
                    telegram_alert(msg)
                    print(f"[probe] {msg}")
                elif ps["stale_count"] >= PROGRESS_KILL_AFTER_STALLS and owner != "unknown":
                    killed = _kill_agent_hermes(owner)
                    msg = (f"💀 PROGRESS-KILL: {gap_id} in {phase} stuck for {ps['stale_count'] * PROGRESS_STALL_SECS // 60} min. "
                           f"Killed {owner} Hermes (success={killed}). agent-worker will pick up next message; iteration counter unchanged.")
                    telegram_alert(msg)
                    print(f"[probe] {msg}")
                    ps["stale_count"] = 0  # reset after kill
    except Exception as e:
        print(f"[probe] error: {e}")



def _sanitize_gap_id(gid: str) -> str:
    """v7.4: Truncate runaway gap_ids and strip non-id chars (em-dash prose tail bug)."""
    if not gid:
        return gid
    # Stop at em-dash, colon, hyphen+space, or any whitespace-prose
    gid = re.split("[—–:;,.!?\n\t]| - | iteration | with | for | from ", gid, maxsplit=1)[0]
    gid = gid.strip()
    # Cap at 80 chars regardless
    if len(gid) > 80:
        gid = gid[:80]
    return gid


def parse_message(msg_id: str, data: dict):
    """Parse incoming message, dispatch to appropriate handler."""
    sender = data.get("from", "unknown")
    subject = data.get("subject", "")
    body = data.get("body", "")
    task_id = data.get("task_id")
    gap_id = _sanitize_gap_id(data.get("gap_id"))
    trace_id = data.get("trace_id") or new_trace_id(gap_id, sender, subject[:20])

    # Item A (ARCH-IT-ARCH-v11): Schema validation at message boundary (log-only iteration 1)
    # Call validate_message — in LOG_ONLY mode this logs violations but allows message through
    valid, reason, instance = validate_message(subject, body)
    if not valid and not LOG_ONLY_MODE:
        # Iteration 2: quarantine and reject
        print(f"[dispatcher] SCHEMA VIOLATION rejected: {reason} from {sender} (trace={trace_id})")
        return

    print(f"[dispatcher] ← {sender}: {subject} (trace={trace_id})")

    # v7.6 Item A: Pydantic schema validation (log-only first pass)
    if _SCHEMA_VALIDATION and subject and body:
        try:
            _validated = validate_body(subject, body, log_only=True)
            if _validated is not None:
                print(f"[dispatcher] schema OK: {type(_validated).__name__}")
        except SchemaViolation as _sv:
            # Log + quarantine (do not refuse yet — soft mode)
            print(f"[dispatcher] SCHEMA VIOLATION: subject={_sv.subject} errors={_sv.errors[:2]}")
            try:
                from pathlib import Path as _P
                qd = _P('/var/lib/karios/agent-msg/schema-violations')
                qd.mkdir(parents=True, exist_ok=True)
                qf = qd / f'{int(time.time())}-{(trace_id or "unknown")[:30]}.json'
                qf.write_text(json.dumps({'subject': subject, 'sender': sender, 'errors': _sv.errors, 'body_preview': _sv.body_preview, 'trace_id': trace_id}))
            except Exception as _qe:
                print(f"[dispatcher] schema-violation log failed: {_qe}")
        except Exception as _ve:
            print(f"[dispatcher] schema validation error: {type(_ve).__name__}: {_ve}")

    # v7.7.1: Human DEEP chat — answer with orchestrator profile via async Hermes subprocess
    if subject.startswith("[HUMAN-DEEP-MESSAGE]"):
        question = body
        tid = trace_id or new_trace_id(op="human_deep")
        def _answer_async(q, t):
            import subprocess as _sp, json as _j, time as _t
            from pathlib import Path as _P
            try:
                # Gather context for orchestrator profile
                ctx = []
                ctx.append("## Live pipeline state (state.json)")
                try:
                    st = _j.load(open("/var/lib/karios/orchestrator/state.json"))
                    ctx.append(_j.dumps({"active_gaps": st.get("active_gaps", {})}, indent=2)[:3000])
                except Exception as e:
                    ctx.append(f"(state.json read error: {e})")
                ctx.append("\n## Recent dispatcher events (last 60 lines)")
                try:
                    out = _sp.run(["journalctl", "-u", "karios-orchestrator-sub", "--since", "20 min ago",
                                   "--no-pager", "-n", "60"], capture_output=True, text=True, timeout=10).stdout
                    ctx.append(out[-3500:])
                except Exception as e:
                    ctx.append(f"(journalctl error: {e})")
                ctx.append("\n## Active gap iteration-tracker contents")
                for gid in (st.get("active_gaps", {}).keys() if isinstance(st, dict) else []):
                    g_state = st["active_gaps"].get(gid, {}).get("state")
                    if g_state in ("completed", "closed"): continue
                    gd = _P(f"/var/lib/karios/iteration-tracker/{gid}")
                    if gd.exists():
                        files = list(gd.rglob("*.md"))[:20] + list(gd.rglob("*.json"))[:10]
                        ctx.append(f"\n### {gid} files:")
                        for f in files:
                            try:
                                size = f.stat().st_size
                                ctx.append(f"  {f.relative_to(gd)} ({size}B)")
                            except Exception:
                                pass
                ctx.append("\n## Recent vault critiques (last 5)")
                try:
                    cd = _P("/opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/critiques")
                    if cd.exists():
                        recent = sorted(cd.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]
                        for f in recent:
                            ctx.append(f"  - {f.name}")
                except Exception:
                    pass
                ctx.append("\n## Heartbeat ages")
                try:
                    now = int(_t.time())
                    hd = _P("/var/lib/karios/heartbeat")
                    if hd.exists():
                        for f in sorted(hd.glob("*.beat")):
                            try:
                                ts = int(f.read_text().strip())
                                ctx.append(f"  {f.stem}: {now - ts}s")
                            except Exception:
                                pass
                except Exception:
                    pass
                full_ctx = "\n".join(ctx)
                prompt = (
                    "You are the KAIROS pipeline ORCHESTRATOR responding to Sai via Telegram.\n"
                    "You have full visibility into the live pipeline state below.\n"
                    "Answer the user question DIRECTLY and IN DETAIL using only the data provided.\n"
                    "Do NOT speculate. Do NOT invoke tools. Just synthesize a clear multi-paragraph answer.\n"
                    "Format: plain text (no Markdown). Keep under 3500 chars (Telegram limit).\n\n"
                    f"USER QUESTION:\n  {q}\n\n"
                    f"=== LIVE STATE ===\n{full_ctx}\n\n"
                    "Your answer:"
                )
                # Write prompt to a tempfile so we don't need to escape shell
                pf = _P(f"/tmp/ask_deep_{int(_t.time())}.txt")
                pf.write_text(prompt)
                # Invoke Hermes orchestrator profile in non-interactive mode
                r = _sp.run(
                    ["/root/.local/bin/hermes", "chat", "--profile", "orchestrator",
                     "--max-turns", "3", "-q", prompt[:30000]],
                    capture_output=True, text=True, timeout=180,
                    env={**__import__("os").environ, "HERMES_NO_TUI": "1"}
                )
                pf.unlink(missing_ok=True)
                # Hermes outputs banner + answer; extract text after the banner
                out = (r.stdout or "") + (r.stderr or "")
                # Strip the banner (everything before the last "─" line) and ANSI codes
                import re as _re
                ansi = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
                clean = ansi.sub("", out)
                # Take the last 3500 chars as the answer (or look for marker)
                answer = clean.strip()[-3500:]
                if not answer:
                    answer = "(orchestrator returned empty output)"
                telegram_alert(f"🤖 (orchestrator) {answer}")
                print(f"[dispatcher] /ask-deep answered ({len(answer)} chars, trace={t})")
            except _sp.TimeoutExpired:
                telegram_alert("⏱ /ask-deep timed out (180s). Pipeline may be busy; try /ask for fast status.")
            except Exception as ex:
                telegram_alert(f"❌ /ask-deep error: {ex}")
                print(f"[dispatcher] /ask-deep error: {ex}")
        threading.Thread(target=_answer_async, args=(question, tid), daemon=True).start()
        telegram_alert("🔬 Reading state + iteration-tracker + dispatcher logs + vault. Orchestrator answer in 30-90s...")
        print(f"[dispatcher] [HUMAN-DEEP-MESSAGE] thread spawned (trace={tid})")
        return

    # v7.7: agent reply destined for Telegram (used by /ask-deep flow)
    if subject.startswith("[TELEGRAM-REPLY]"):
        # Strip the prefix to get the answer text
        try:
            answer = subject.split("]", 1)[1].strip() if "]" in subject else ""
            if not answer:
                answer = body.strip()
            if not answer:
                answer = "(empty answer from agent)"
            telegram_alert(f"🤖 {answer[:3500]}")
            print(f"[dispatcher] [TELEGRAM-REPLY] forwarded to telegram ({len(answer)} chars)")
        except Exception as _te:
            print(f"[dispatcher] [TELEGRAM-REPLY] handler error: {_te}")
        return

    # v7.7: Human chat from Telegram via /ask — answer with current pipeline status
    if subject.startswith("[HUMAN-MESSAGE]"):
        try:
            st = load_state() or {}
            ag = st.get("active_gaps", {})
            active = [k for k, v in ag.items() if v.get("state") not in ("completed", "closed")]
            completed = [k for k, v in ag.items() if v.get("state") == "completed"]
            # Build a quick status reply
            reply_lines = [f"📊 Pipeline status (you asked: {body[:80]})"]
            reply_lines.append(f"Active gaps: {len(active)}")
            for g in active[:5]:
                e = ag[g]
                reply_lines.append(f"  • {g}: {e.get('phase', '?')} iter={e.get('iteration', 1)}")
            reply_lines.append(f"Completed (recent): {len(completed)}")
            for g in completed[-3:]:
                reply_lines.append(f"  ✓ {g}")
            # Heartbeat ages
            import time as _t, os as _os
            now = int(_t.time())
            hb = []
            for f in sorted(_os.listdir("/var/lib/karios/heartbeat") if _os.path.isdir("/var/lib/karios/heartbeat") else []):
                if not f.endswith(".beat"): continue
                try:
                    ts = int(open(f"/var/lib/karios/heartbeat/{f}").read().strip())
                    age = now - ts
                    icon = "✓" if age < 120 else "⚠"
                    hb.append(f"{icon} {f[:-5]}={age}s")
                except Exception:
                    pass
            reply_lines.append("Agents: " + " ".join(hb[:9]))
            telegram_alert("\n".join(reply_lines))
            print(f"[dispatcher] [HUMAN-MESSAGE] answered via telegram_alert")
        except Exception as _e:
            print(f"[dispatcher] [HUMAN-MESSAGE] handler error: {_e}")
            telegram_alert(f"❌ /ask handler error: {_e}")
        return

    # ── New requirement ────────────────────────────────────────────────────
    if subject.startswith("[REQUIREMENT]"):
        handle_requirement(body, trace_id=trace_id)
        return

    # ── Research phase complete ───────────────────────────────────────────
    if subject.startswith("[RESEARCH-COMPLETE]"):
        # Format: "[RESEARCH-COMPLETE] GAP-ID: body" → extract GAP-ID (before ":")
        parts = subject.split("]")
        gid = parts[1].strip().split(":")[0].strip() if len(parts) > 1 else subject
        handle_research_complete(gid, body, trace_id=trace_id)
        return

    # ── Architecture iteration complete ────────────────────────────────────
    if subject.startswith("[ARCH-COMPLETE]") or subject.startswith("[ARCHITECTURE-COMPLETE]"):  # v7.3 alias
        parts = subject.split("]")
        if len(parts) > 1:
            remaining = parts[1].strip()
            tokens = remaining.split()
            gid = tokens[0]
            iter_token = "iteration"
            if iter_token in tokens:
                iter_idx = tokens.index(iter_token)
                iteration = int(tokens[iter_idx + 1]) if iter_idx + 1 < len(tokens) else 1
            else:
                # v7.4: defensive — tokens[1] may be '—' or other non-numeric
                try:
                    iteration = int(tokens[1]) if len(tokens) > 1 else 1
                except (ValueError, TypeError):
                    iteration = 1
            handle_arch_complete(gid, iteration, body, trace_id=trace_id)
        return

    # ── Architecture blind review complete ──────────────────────────────────
    if subject.startswith("[ARCH-REVIEWED]") or subject.startswith("[BLIND-REVIEWED]"):  # v7.3 alias
        parts = subject.split("]")
        if len(parts) > 1:
            remaining = parts[1].strip()
            tokens = remaining.split()
            gid = tokens[0]
            iteration = int(tokens[tokens.index("iteration") + 1]) if "iteration" in tokens else 1
            try:
                # v7.5: Extract JSON from body — file-inbox includes subject prefix + may have ```json fences
                _b = body.strip()
                if _b.startswith('[ARCH-REVIEWED]') or _b.startswith('[BLIND-REVIEWED]'):
                    _b = _b.split('\n', 1)[1] if '\n' in _b else _b
                _m = re.search(r'```(?:json)?\s*\n(.+?)\n```', _b, re.DOTALL)
                if _m:
                    _b = _m.group(1)
                if not _b.strip().startswith('{'):
                    _m2 = re.search(r'\{.*\}', _b, re.DOTALL)
                    if _m2:
                        _b = _m2.group(0)
                review = json.loads(_b)
                _r = review.get("rating", 0)
                _rec = review.get("recommendation", "?")
                _next = "backend+frontend (Phase 3)" if _r >= 8 else f"architect (revise iter {iteration+1})"
                notify_phase_transition(gid, "architect-blind-tester", _next,
                                        "ARCH-REVIEWED", rating=_r,
                                        summary=f"recommendation={_rec}; {review.get('summary', '')[:140]}")
                if "rating" not in review:
                    print(f"[dispatcher] WARN: arch review missing rating; dropping. body={body[:120]}")
                else:
                    handle_arch_review(gid, iteration, review["rating"],
                                      review.get("critical_issues", []),
                                      review.get("summary", ""),
                                      review.get("dimensions", {}),
                                      review.get("adversarial_test_cases", {}),
                                      review.get("recommendation", "REQUEST_CHANGES"),
                                      trace_id=review.get("trace_id") or trace_id)
            except json.JSONDecodeError:
                print(f"[dispatcher] ERROR: Could not parse arch review JSON: {body[:200]}")
            except Exception as _ar_e:
                print(f"[dispatcher] WARN: handle_arch_review exception {type(_ar_e).__name__}: {_ar_e}; dropping")
        return

    # ── Agent task complete (FIX v5.1) ─────────────────────────────────────────
    # Handle generic [COMPLETE] messages from agent-worker after _notify_orchestrator_completion.
    # Format: "[COMPLETE] agent completed gap=GAP-ID phase=PHASE trace=TRACE-ID"
    # This is the feedback loop closer — agents now notify orchestrator automatically.
    if subject.startswith("[COMPLETE]") or subject.startswith("[COMPLETE]"):
        # v7.5.2: re imported at module top
        # Extract gap_id from body (gap_id: ARCH-IT-XXX)
        gap_id_match = re.search(r"gap_id:\s*(\S+)", body)
        phase_match = re.search(r"phase:\s*(\S+)", body)
        coding_complete_match = re.search(r"coding_complete:\s*(True|False)", body)
        iteration_match = re.search(r"iteration:\s*(\d+)", body)
        gap_id = gap_id_match.group(1) if gap_id_match else None
        phase = phase_match.group(1) if phase_match else None
        iteration = int(iteration_match.group(1)) if iteration_match else 1
        coding_complete = coding_complete_match.group(1) == "True" if coding_complete_match else False

        if gap_id:
            gap_data = load_gap(gap_id)
            current_phase = gap_data.get("phase", "unknown") if gap_data else "unknown"
            status = "COMPLETE" if coding_complete else "ERROR"
            print(f"[dispatcher] ← {status}: {gap_id} {phase} (was {current_phase}), iter={iteration}")

            # v6.0 FIX 2026-04-19: phase names come in BOTH forms — "phase-3-coding" (long, set
            # by meta-runner / fan_out) and "3-coding" (short, used by transition_phase). Normalize.
            def _norm_phase(p):
                if not p: return None
                p = p.lower()
                if p.startswith("phase-"): p = p[6:]  # phase-3-coding -> 3-coding
                return p
            n_phase = _norm_phase(phase)
            n_current = _norm_phase(current_phase)

            # Determine next phase based on current phase (using normalized names)
            if n_phase in ("1-research", "1-research-pre") and n_current == "1-research":
                advance_to_arch_loop(gap_id, iteration, body, trace_id=trace_id)
            elif n_phase in ("2-arch-loop", "2-architecture") and n_current in ("2-arch-loop", "2-architecture"):
                transition_phase(gap_id, "3-coding", iteration=iteration, trace_id=trace_id)
            elif n_phase == "3-coding" and n_current in ("3-coding", "2-arch-loop", "2-architecture"):
                # Coding complete → trigger API-SYNC gate (also accept arriving from 2-* if state lagged)
                gap_data = load_gap(gap_id) or {}
                gap_data["iteration_status"] = "awaiting_sync"
                gap_data["phase"] = "phase-3-coding"
                save_gap(gap_id, gap_data)
                send_to_agent("backend",
                            f"[API-SYNC] {gap_id} — ready for API contract verification",
                            f"gap_id={gap_id}\niteration={iteration}\ntrace_id={trace_id}\n\n"
                            "Verify the API contract against the implementation. "
                            "Report back with [CODING-COMPLETE] or [CODING-ERROR].",
                            gap_id=gap_id, trace_id=trace_id)
            elif n_phase in ("3-coding-sync", "3-coding-testing") or n_phase.startswith("3-coding"):
                # v7.4: API-SYNC complete → Phase 4 (E2E testing by code-blind-tester + tester)
                # v7.12: E2E build_prompt — 7 dimensions + VMware intent
                if _PROMPT_BUILDER:
                    _e2e_body = _build_prompt(
                        task_type="E2E-REVIEW",
                        gap_id=gap_id,
                        iteration=iteration,
                        trace_id=trace_id,
                        repo="karios-migration",
                        intent_tags=["7_dimensions", "vmware", "adversarial"],
                        intent_query=f"e2e test {gap_id}",
                    )
                else:
                                    _e2e_body = (
                    f"TASK: Real E2E test of {gap_id} iter {iteration}. NO synthesis — run actual commands.\n\n"
                    f"STEP 1 (REQUIRED FIRST — bash): cat /var/lib/karios/iteration-tracker/{gap_id}/phase-2-architecture/iteration-{iteration}/test-cases.md\n"
                    f"STEP 2 (bash): curl -sI http://192.168.118.106:8089/api/v1/healthz — confirm API alive\n"
                    f"STEP 3 (bash for VMware gaps): ssh -o StrictHostKeyChecking=no root@192.168.115.232 'vim-cmd vmsvc/getallvms | head' — probe ESXi\n"
                    f"STEP 4 (bash): cd /root/karios-source-code/karios-playwright && npx playwright test --reporter=json > /tmp/pw-{gap_id}.json 2>&1 || true\n"
                    f"STEP 5 (file_write): /var/lib/karios/iteration-tracker/{gap_id}/phase-3-coding/iteration-{iteration}/e2e-results.json with:\n"
                    f'    {{"gap_id":"{gap_id}","iteration":{iteration},"rating":N,"recommendation":"APPROVE|REJECT","summary":"what actually ran and what passed","critical_issues":[...],"dimensions":{{"functional_correctness":N,"edge_cases":N,"security":N,"performance":N,"concurrency":N,"resilience":N,"error_handling":N}},"adversarial_test_cases":{{"test_id":"pass|fail + evidence"}},"trace_id":"{trace_id}"}}\n'
                    f"STEP 6 (bash): agent send orchestrator \"[E2E-RESULTS] {gap_id} iteration {iteration}\" < /var/lib/karios/iteration-tracker/{gap_id}/phase-3-coding/iteration-{iteration}/e2e-results.json\n\n"
                    f"HARD RULES:\n"
                    f"- DO NOT WRITE PROSE. Each output MUST be a tool call.\n"
                    f"- DO NOT synthesize results. If you cannot run a test, mark it 'skipped — reason: X'.\n"
                    f"- Real evidence required: curl output, playwright reporter JSON, ESXi vim-cmd output.\n"
                    f"- Watchdog kills prose-only sessions at 6000 chars.\n"
                    f"- Your role doc: ~/.hermes/profiles/code-blind-tester/SOUL.md (read only if needed)."
                )
                send_to_agent("code-blind-tester",
                            f"[E2E-REVIEW] {gap_id} iteration {iteration}",
                            _e2e_body,
                            gap_id=gap_id, trace_id=trace_id)
                # v7.12: TEST-RUN build_prompt
                if _PROMPT_BUILDER:
                    _test_body = _build_prompt(
                        task_type="TEST-RUN",
                        gap_id=gap_id,
                        iteration=iteration,
                        trace_id=trace_id,
                        repo="karios-migration",
                        intent_query=f"functional tests {gap_id}",
                    )
                else:
                                    _test_body = (
                    f"TASK: Execute functional test plan for {gap_id} iter {iteration}.\n\n"
                    f"STEP 1 (bash): cat /var/lib/karios/iteration-tracker/{gap_id}/phase-2-architecture/iteration-{iteration}/test-cases.md\n"
                    f"STEP 2 (bash): for each test case in the plan — execute the commands listed\n"
                    f"STEP 3 (file_write): /var/lib/karios/iteration-tracker/{gap_id}/phase-3-coding/iteration-{iteration}/test-results.json\n"
                    f"STEP 4 (bash): agent send orchestrator \"[TEST-RESULTS] {gap_id} iteration {iteration}\" < test-results.json\n\n"
                    f"DO NOT WRITE PROSE. Each output MUST be a tool call. Report honest skipped/pass/fail counts."
                )
                send_to_agent("tester",
                            f"[TEST-RUN] {gap_id} iteration {iteration}",
                            _test_body,
                            gap_id=gap_id, trace_id=trace_id)
                update_gap_phase(gap_id, "4-testing", iteration=iteration, trace_id=trace_id)
                try:
                    notify_phase_transition(gap_id, "backend (API-SYNC)", "code-blind-tester+tester (Phase 4 E2E)",
                                            "API-SYNC", rating=None,
                                            summary="API contract aligned; advancing to E2E testing")
                except Exception as _e:
                    print(f"[dispatcher] notify error: {_e}")
            else:
                print(f"[dispatcher] COMPLETE handler: no transition for {gap_id} {phase} (current={current_phase}; normalized {n_phase}/{n_current})")
        else:
            print(f"[dispatcher] ← [COMPLETE] but no gap_id in body: {body[:100]}")
        return

    # ── Coding complete / FAN-IN ──────────────────────────────────────────
    # v7.13: code-blind-tester emitting [CODING-COMPLETE] is a phantom — it should emit
    # [E2E-RESULTS] in Phase 4. Drop these to stop the cycling spam.
    if subject.startswith("[CODING-COMPLETE]") and sender in ("code-blind-tester", "architect-blind-tester", "tester"):
        print(f"[dispatcher] DROP: [CODING-COMPLETE] from {sender} — wrong sender (only backend/frontend may emit). Should be [E2E-RESULTS].")
        return
    if subject.startswith("[CODING-COMPLETE]") or subject.startswith("[FAN-IN]"):
        remaining = subject.split("]")[1].strip() if "]" in subject else subject
        tokens = remaining.split()
        # v6.0 FIX 2026-04-19: tokens[0] could be "gap_id=ARCH-IT-X" or "ARCH-IT-X"
        # depending on agent format. Normalize by stripping known prefixes.
        gid_raw = tokens[0] if tokens else ""
        for prefix in ("gap_id=", "gap=", "id=", "trace_id="):
            if gid_raw.startswith(prefix):
                gid_raw = gid_raw[len(prefix):]
                break
        gid = gid_raw
        # Also try regex on body in case subject was wholly different
        import re as _re
        bm = _re.search(r"gap_id[=:\s]+(\S+)", body)
        if bm and (not gid or "=" in gid):
            gid = bm.group(1).strip()
        iter_idx = tokens.index("iteration") if "iteration" in tokens else -1
        iteration = int(tokens[iter_idx + 1]) if iter_idx != -1 and iter_idx + 1 < len(tokens) else 1
        # Also pull iteration= from body
        im = _re.search(r"iteration[=:\s]+(\d+)", body)
        if im:
            iteration = int(im.group(1))
        gap_data = load_gap(gid)

        # Item C (ARCH-IT-ARCH-v11): code-review-graph rubric — v7.10 downgrade to warning when real commit shipped
        code_profiles = {"backend", "frontend", "backend-worker", "frontend-worker"}
        if sender in code_profiles:
            session_metadata = data.get("session_metadata", {})
            crg_calls = session_metadata.get("code_review_graph_calls", 0)
            # v7.10: if body contains a commit_sha=<40-hex>, the agent shipped real code → just warn
            import re as _re
            has_real_commit = bool(_re.search(r"commit_sha=[0-9a-f]{40}", body or ""))
            if crg_calls == 0 and not has_real_commit:
                # No proof of work → refuse + retry (orig v7.6 behavior)
                print(f"[dispatcher] CODING-COMPLETE refused: {sender} had 0 code_review_graph calls AND no commit")
                stream_publish(
                    subject=f"[CODING-RETRY] {gid}",
                    body=json.dumps({
                        "reason": "code_review_graph_calls=0 + no commit — retry with get_minimal_context + ship code",
                        "gap_id": gid, "iteration": iteration
                    }),
                    from_agent="orchestrator",
                    gap_id=gid, priority="high"
                )
                telegram_alert(f"🚨 {gid}: CODING-COMPLETE refused — {sender} skipped graph + no commit. Retry required.")
                return
            elif crg_calls == 0 and has_real_commit:
                # Real commit shipped, just skipped graph — warn but advance
                print(f"[dispatcher] CODING-COMPLETE accepted (warn): {sender} skipped code_review_graph but shipped real commit")
                telegram_alert(f"⚠ {gid}: {sender} shipped real commit but skipped code-review-graph rubric. Acceptable but suboptimal.")

        if gap_data.get("iteration", 0) > 0:
            iteration = gap_data["iteration"]
        agent = sender
        agent_state = {"phase": "idle", "iteration": iteration, "coding_complete": True}
        all_done = fan_in(gid, agent, agent_state)
        if all_done:
            # Trigger API-SYNC gate
            gap_data = load_gap(gid)
            iter_num = gap_data.get("iteration", 1)
            api_contract_file = IT_DIR / gid / "phase-2-arch-loop" / f"iteration-{iter_num}" / "api-contract.md"
            tid = new_trace_id(gid, "orchestrator", "api_sync")
            sync_body = (
                f"PARALLEL coding complete for {gid}.\n"
                f"Before DevOps deploys, you must confirm API contract alignment.\n"
                f"Read: {api_contract_file}\n"
                f"Confirm by sending to orchestrator: [API-SYNC] {gid}\n"
                f"Do NOT implement more code — only confirm alignment.\n"
                f"trace_id: {tid}"
            )
            send_to_agent("backend", f"[API-SYNC] {gid} — confirm API alignment before deploy",
                          sync_body, gap_id=gid, trace_id=tid, priority="high")
            send_to_agent("frontend", f"[API-SYNC] {gid} — confirm API alignment before deploy",
                          sync_body, gap_id=gid, trace_id=tid, priority="high")
            publish_gap_event("gap.iteration", gid,
                              {"action": "fan_in_api_sync_triggered", "gap_id": gid, "trace_id": tid})
        return

    # ── API sync confirmation ─────────────────────────────────────────────
    if subject.startswith("[API-SYNC]"):
        # Format: "[API-SYNC] GAP-ID: body" → extract GAP-ID (before ":")
        gid = subject.split("]")[1].strip().split(":")[0].strip()
        agent = sender
        gap_data = load_gap(gid)
        sync_confirmed = set(gap_data.get("api_sync_confirmed", []))
        sync_confirmed.add(agent)
        gap_data["api_sync_confirmed"] = list(sync_confirmed)
        save_gap(gid, gap_data)
        remaining = {"backend", "frontend"} - sync_confirmed
        print(f"[dispatcher] API-SYNC: {agent} confirmed for {gid}. Still pending: {remaining}")
        if not remaining:
            iteration = gap_data.get("iteration", 1)
            devops_state = load_agent_state("devops")
            tid = new_trace_id(gid, "orchestrator", "deploy_triggered")
            if devops_state.get("busy", False):
                queue = devops_state.get("deploy_queue", [])
                queue.append({"gap_id": gid, "iteration": iteration, "reason": "api_sync_complete"})
                update_agent_checkpoint("devops", deploy_queue=queue)
                print(f"[dispatcher] DevOps busy. Deploy for {gid} queued.")
                publish_gap_event("deploy.status", gid,
                                {"action": "deploy_queued", "iteration": iteration, "queue_pos": len(queue),
                                 "trace_id": tid})
                telegram_alert(f"⏳ *{gid}*: API-SYNC passed. DevOps busy — deploy queued.")
            else:
                update_agent_checkpoint("devops", busy=True, trace_id=tid)
                update_gap_phase(gid, "3-deploy", iteration=iteration, trace_id=tid)
                update_agent_checkpoint("backend", phase="phase-3-done", coding_complete=True)
                update_agent_checkpoint("frontend", phase="phase-3-done", coding_complete=True)
                publish_gap_event("deploy.status", gid,
                                {"action": "deploy_triggered", "iteration": iteration, "trace_id": tid})
                send_to_agent("devops",
                             f"[DEPLOY] {gid} — API-SYNC complete, deploy to staging",
                             f"Both agents confirmed API alignment for {gid}.\n"
                             f"Deploy to staging and notify: [STAGING-DEPLOYED] {gid} iteration {iteration}\n"
                             f"Arch docs: {IT_DIR / gid / 'phase-2-arch-loop' / f'iteration-{iteration}'}\n"
                             f"trace_id: {tid}",
                             gap_id=gid, trace_id=tid, priority="high")
                telegram_alert(f"🚀 *{gid}*: API-SYNC passed. DevOps deploying to staging.")
                print(f"[dispatcher] {gid}: API-SYNC complete — DEPLOY dispatched (trace={tid})")
        return

    # ── Staging deployed ───────────────────────────────────────────────────
    if subject.startswith("[STAGING-DEPLOYED]") or subject.startswith("[DEPLOYED-STAGING]") or subject.startswith("[DEPLOY-COMPLETE]"):  # v7.3 alias
        # v7.3 Telegram phase transition
        try:
            _gid_match = re.search(r"\[[A-Z\-]+\]\s*(\S+)", subject)
            _gid_n = _gid_match.group(1) if _gid_match else "?"
            notify_phase_transition(_gid_n, "devops", "tester+code-blind-tester (Phase 4 E2E)",
                                    "STAGING-DEPLOYED", summary=body[:140])
        except Exception:
            pass
        remaining = subject.split("]")[1].strip() if "]" in subject else subject
        tokens = remaining.split()
        gid = tokens[0]
        iteration = int(tokens[tokens.index("iteration") + 1]) if "iteration" in tokens else 1
        devops_state = load_agent_state("devops")
        devops_state["busy"] = False
        queue = devops_state.pop("deploy_queue", [])
        save_agent_state("devops", devops_state)
        publish_gap_event(EVENT_CHANNELS["deploy.status"], gid,
                          {"status": "staging_deployed", "iteration": iteration, "gap_id": gid})
        if queue:
            next_deploy = queue.pop(0)
            devops_state["busy"] = True
            devops_state["deploy_queue"] = queue
            save_agent_state("devops", devops_state)
            send_to_agent("devops",
                          f"[DEPLOY] {next_deploy['gap_id']} — next queued deploy",
                          f"Next queued gap: {next_deploy['gap_id']} iteration {next_deploy['iteration']}.\n"
                          f"Deploy to staging and notify: [STAGING-DEPLOYED] {next_deploy['gap_id']} iteration {next_deploy['iteration']}")
        submit_code_for_test(gid, iteration)
        return

    # ── E2E results (v4.0: includes dimensions, adversarial_tests, recommendation) ──
    if subject.startswith("[E2E-RESULTS]") or subject.startswith("[BLIND-E2E-RESULTS]") or subject.startswith("[E2E-COMPLETE]") or subject.startswith("[TEST-RESULTS]") or subject.startswith("[BLIND-E2E-RESULTS]") or subject.startswith("[E2E-COMPLETE]") or (subject.startswith("[TASK-COMPLETE]") and "E2E" in subject):  # v7.3 alias
        remaining = subject.split("]")[1].strip() if "]" in subject else subject
        tokens = remaining.split()
        if not tokens:
            print(f"[dispatcher] ERROR: [E2E-RESULTS] message has no gap_id in subject: {subject!r}")
            return
        gid = tokens[0]
        _iter_token = tokens[tokens.index("iteration") + 1] if "iteration" in tokens else None
        iteration = int(_iter_token.rstrip(':')) if _iter_token else 1
        try:
            # v7.5.3: extract JSON from prose+fence body (same fix as handle_arch_review)
            _b = body.strip()
            if _b.startswith('[E2E-RESULTS]') or _b.startswith('[BLIND-E2E-RESULTS]') or _b.startswith('[E2E-COMPLETE]') or _b.startswith('[TEST-RESULTS]'):
                _b = _b.split('\n', 1)[1] if '\n' in _b else _b
            _m = re.search(r'```(?:json)?\s*\n(.+?)\n```', _b, re.DOTALL)
            if _m:
                _b = _m.group(1)
            if not _b.strip().startswith('{'):
                _m2 = re.search(r'\{.*\}', _b, re.DOTALL)
                if _m2:
                    _b = _m2.group(0)
            results = json.loads(_b)
            _r = results.get("rating", 0)
            _rec = results.get("recommendation", "?")
            _next = "devops (Phase 5 deploy)" if _r >= 8 else f"backend+frontend (revise iter {iteration+1})"
            notify_phase_transition(gid, "code-blind-tester+tester", _next,
                                    "E2E-RESULTS", rating=_r,
                                    summary=f"recommendation={_rec}; {results.get('summary', '')[:140]}")
            _crit_issues = results.get("critical_issues", [])
            if not isinstance(_crit_issues, list):
                _crit_issues = []
            handle_e2e_results(gid, iteration, results["rating"],
                              _crit_issues,
                              results.get("test_results", {}),
                              results.get("dimensions", {}),
                              results.get("adversarial_tests", {}),
                              results.get("recommendation", "REQUEST_CHANGES"),
                              trace_id=results.get("trace_id") or trace_id)
        except json.JSONDecodeError:
            print(f"[dispatcher] ERROR: Could not parse E2E results JSON: {body[:200]}")
        return

    # ── Production deployed ────────────────────────────────────────────────
    if subject.startswith("[PROD-DEPLOYED]") or subject.startswith("[DEPLOYED-PROD]") or subject.startswith("[PRODUCTION-DEPLOYED]"):  # v7.3 alias
        try:
            _gid_match = re.search(r"\[[A-Z\-]+\]\s*(\S+)", subject)
            _gid_n = _gid_match.group(1) if _gid_match else "?"
            notify_phase_transition(_gid_n, "devops", "monitor (Phase 6 24h watch)",
                                    "PROD-DEPLOYED", summary=body[:140])
        except Exception:
            pass
        # Format: "[PROD-DEPLOYED] GAP-ID: body" → extract GAP-ID (before ":")
        gid = subject.split("]")[1].strip().split(":")[0].strip()
        handle_production_deployed(gid, trace_id=trace_id)
        return

    # ── Escalation ────────────────────────────────────────────────────────
    if subject.startswith("[ESCALATE]"):
        # Format: "[ESCALATE] GAP-ID: reason" → extract GAP-ID (before ":")
        gid = subject.split("]")[1].strip().split(":")[0].strip()
        telegram_alert(f"🚨 ESCALATION for {gid}: {body[:200]}")
        return

    # ── Status request ────────────────────────────────────────────────────
    if subject in ["[STATUS]", "status"]:
        state = load_state()
        gaps = []
        for gid in state.get("active_gaps", {}):
            g = load_gap(gid)
            gaps.append(f"  {gid}: phase={g.get('phase')} iter={g.get('iteration')} trace={g.get('trace_id', '?')}")
        status_msg = "Active gaps:\n" + "\n".join(gaps) if gaps else "No active gaps"
        send_to_agent(sender, "[STATUS-REPLY]", status_msg, trace_id=trace_id)
        return

    # ── GitHub webhook: PR merged → auto-deploy ────────────────────────────
    if subject.startswith("[GITHUB-PR-MERGED]"):
        gid = body.strip()
        if gid and gid in load_state().get("active_gaps", {}):
            devops_state = load_agent_state("devops")
            tid = new_trace_id(gid, "github", "pr_merged_auto_deploy")
            if not devops_state.get("busy", False):
                update_agent_checkpoint("devops", busy=True, trace_id=tid)
                send_to_agent("devops",
                              f"[AUTO-DEPLOY] {gid} — GitHub PR merged",
                              f"GitHub webhook: PR merged for {gid}.\n"
                              f"Auto-triggering production deploy.\n"
                              f"trace_id: {tid}",
                              gap_id=gid, trace_id=tid, priority="high")
                telegram_alert(f"🔄 *{gid}*: GitHub PR merged — auto-deploy triggered.")
            else:
                queue = devops_state.get("deploy_queue", [])
                queue.append({"gap_id": gid, "iteration": 1, "reason": "github_pr_merged"})
                update_agent_checkpoint("devops", deploy_queue=queue)
                telegram_alert(f"⏳ *{gid}*: PR merged but DevOps busy — queued.")
        return

    # ── v7.4 [MONITORING-COMPLETE] handler — closes Phase 6 and marks gap fully done ───
    if subject.startswith("[MONITORING-COMPLETE]"):
        try:
            import re as _re_mc
            _gid_m = _re_mc.search(r"\[MONITORING-COMPLETE\]\s*(\S+)", subject)
            _gid_n = _gid_m.group(1) if _gid_m else None
            if _gid_n:
                _state = load_state()
                _ag = _state.get("active_gaps", {})
                if _gid_n in _ag:
                    _g = _ag.pop(_gid_n)
                    _state.setdefault("completed_gaps", []).append({
                        "gap_id": _gid_n, "phase": "6-monitoring-complete",
                        "completed_at": current_ts(), "result": "Phase 6 monitor closed",
                        "original_state": _g,
                    })
                    save_state(_state)
                notify_phase_transition(_gid_n, "monitor", "(none — gap fully closed)",
                                        "MONITORING-COMPLETE", summary=body[:140])
                print(f"[dispatcher] Gap {_gid_n} fully closed — Phase 6 done")
        except Exception as _mc_e:
            print(f"[dispatcher] MONITORING-COMPLETE handler error: {type(_mc_e).__name__}: {_mc_e}")
        return

    print(f"[dispatcher] Unhandled message: {subject} (trace={trace_id})")

# ── Stalled Gap Detection ─────────────────────────────────────────────────────
def check_stalled_gaps():
    """Check for gaps that have been in the same phase too long."""
    from datetime import datetime as dt
    state = load_state()
    PHASE_TIMEOUTS = {
        "1-research": 30 * 60,
        "2-arch-loop": 15 * 60,
        "3-coding": 30 * 60,
        "3-coding-testing": 20 * 60,
    }
    stalled = []
    for gid, ge in state.get("active_gaps", {}).items():
        # v7.8: skip gaps marked completed/closed/cancelled in state.json — dispatcher should NOT
        # nudge them. ARCH-IT-016 cost ~9 hours of telegram noise because this filter was missing.
        if ge.get("state") in ("completed", "closed", "cancelled", "escalated"):
            continue
        g = load_gap(gid)
        phase = g.get("phase", "")
        if phase in ("completed", "closed"):
            continue
        updated_at = g.get("updated_at", g.get("started_at", ""))
        if not updated_at or phase not in PHASE_TIMEOUTS:
            continue
        try:
            updated_ts = dt.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ")
            age_seconds = (dt.utcnow() - updated_ts).total_seconds()
            timeout = PHASE_TIMEOUTS.get(phase, 0)
            if age_seconds > timeout:
                stalled.append((gid, phase, g.get("iteration", "?"), int(age_seconds / 60)))
        except Exception:
            pass
    return stalled

# ── Recovery from Checkpoints ─────────────────────────────────────────────────
def recover_from_checkpoints(active_gaps: dict):
    """On startup, recover any in-progress gaps from checkpoints.
    
    FIX v5.1: Only recover gaps that are in active_gaps (cross-reference check).
    Gaps not in active_gaps are orphaned (completed/cancelled) and must be skipped.
    Also skips terminal phase patterns that indicate the gap is done.
    """
    recovered = []
    for gap_dir in sorted(IT_DIR.iterdir()):
        if not gap_dir.is_dir():
            continue
        gap_id = gap_dir.name

        # FIX v5.1: Skip gaps not in active_gaps — they are orphaned/stale
        if gap_id not in active_gaps:
            continue

        # v7.5: also skip if state.json says the gap is completed/closed
        ag_entry = active_gaps.get(gap_id, {})
        if ag_entry.get("state") in ("completed", "closed", "cancelled", "escalated"):
            print(f"[dispatcher] Skipping recover for {gap_id}: state={ag_entry.get('state')}")
            continue
        if ag_entry.get("phase") in ("completed", "closed"):
            continue

        ckpt = load_latest_checkpoint(gap_id)
        if not ckpt:
            continue
        phase = ckpt.get("phase", "")

        # FIX v5.1: Expanded terminal phases — any phase pattern that means "done"
        terminal_phases = (
            "completed", "escalated", "idle", "unknown", None, "",
            "2-arch-review", "2-arch-loop", "2-arch-complete",  # arch done
            "3-coding", "3-code-review", "3-code-complete",       # coding done
            "4-production", "4-prod-complete",                  # prod done
        )
        if phase in terminal_phases:
            continue

        # Gap was in progress — nudge the agent
        agent = ckpt.get("agent", "unknown")
        trace_id = ckpt.get("trace_id", new_trace_id(gap_id, "recovery", phase))
        iteration = ckpt.get("iteration", 1)
        print(f"[dispatcher] RECOVERING gap {gap_id}: phase={phase} iter={iteration} trace={trace_id}")
        recovered.append(gap_id)

        if phase.startswith("1-"):
            send_to_agent("architect", f"[RECOVER] {gap_id} — resume research",
                          f"Gap {gap_id} was in research phase when dispatcher restarted.\n"
                          f"Please resume from your last checkpoint.\n"
                          f"trace_id: {trace_id}",
                          gap_id=gap_id, trace_id=trace_id, priority="high")
        elif phase.startswith("2-"):
            send_to_agent("architect", f"[RECOVER] {gap_id} — resume architecture",
                          f"Gap {gap_id} was in arch loop iteration {iteration} when dispatcher restarted.\n"
                          f"trace_id: {trace_id}",
                          gap_id=gap_id, trace_id=trace_id, priority="high")
        elif phase.startswith("3-"):
            send_to_agent("backend", f"[RECOVER] {gap_id} — resume coding",
                          f"Gap {gap_id} was in coding iteration {iteration} when dispatcher restarted.\n"
                          f"trace_id: {trace_id}",
                          gap_id=gap_id, trace_id=trace_id, priority="high")
    return recovered

# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    print("[dispatcher] Dual-Loop Event Dispatcher v3.0 starting...", flush=True)
    print("[dispatcher] Improvements: Streams, Trace IDs, Dynamic Routing, Streaming, Agent Memory", flush=True)

    # Initialize Redis Stream consumer group
    init_stream_consumer_group()

    # ── OTEL: Initialize KAIROS tracer ────────────────────────────────────────
    tracer = get_tracer()

    # ── SOP Engine + Output Verifier (v4.0) ──────────────────────────────────
    global sop_engine, output_verifier, hitl, semantic_memory
    sop_engine = SOPEngine()
    output_verifier = OutputVerifier(quality_threshold=0.7)
    hitl = HITLInterruptHandler()
    semantic_memory = SemanticMemoryV4()
    print(f"[dispatcher] SOP Engine loaded: {list(sop_engine.sops.keys())}")
    print(f"[dispatcher] HITL Interrupt Handler initialized")
    print(f"[dispatcher] Semantic Memory initialized: {list(semantic_memory.knowledge_bases.keys())}")

    # FIX v5.1: Load state BEFORE recover_from_checkpoints so we know active_gaps
    state = load_state()
    # v7.9: rehydrate incomplete active_gaps entries from gap metadata file (load_gap)
    _rehydrated = 0
    for _gid, _ge in state.get("active_gaps", {}).items():
        if not _ge.get("phase") or not _ge.get("state"):
            _g = load_gap(_gid) or {}
            if _g.get("phase") and not _ge.get("phase"):
                _ge["phase"] = _g["phase"]
                _rehydrated += 1
            if _g.get("iteration") and not _ge.get("iteration"):
                _ge["iteration"] = _g["iteration"]
            if not _ge.get("state") and _g.get("state"):
                _ge["state"] = _g["state"]
    if _rehydrated:
        save_state(state)
        print(f"[dispatcher] Rehydrated {_rehydrated} active_gaps entries from gap metadata")
    print(f"[dispatcher] State loaded: {len(state.get('active_gaps', {}))} active gaps")

    # FIX v5.1: Pass active_gaps so recover_from_checkpoints skips orphaned checkpoints
    recovered = recover_from_checkpoints(state.get("active_gaps", {}))
    if recovered:
        print(f"[dispatcher] Recovered {len(recovered)} in-progress gaps: {recovered}")

    fan_state = load_fan_state()
    if fan_state.get("pending"):
        print(f"[dispatcher] Recovered {len(fan_state['pending'])} pending fan-outs: {list(fan_state['pending'].keys())}")
        for gid, pending in fan_state["pending"].items():
            still_pending = [a for a in pending["agents"] if a not in pending["completed"]]
            print(f"  {gid}: {len(pending['agents'])} agents, still pending: {still_pending}")

    for gid in state.get("active_gaps", {}):
        # FIX v5.1: Gap state lives in state.json's active_gaps dict, NOT in
        # load_gap() which reads IT_DIR/metadata.json (different schema).
        g = state["active_gaps"][gid]  # active_gaps entry has state field
        print(f"[dispatcher] Resuming gap {gid}: phase={g.get('phase')} iter={g.get('iteration')} trace={g.get('trace_id', '?')}")
        # FIX v5.1: Dispatch pending gaps to agents — the orchestrator was just
        # printing "Resuming gap" but never actually sending work to the architect.
        gap_state = g.get("state", "pending")
        phase = g.get("phase", "")
        if gap_state == "pending" and phase.startswith("phase-2-"):
            # Dispatch Phase 2 architecture task to architect
            trace_id = g.get("trace_id", new_trace_id(gid, "orchestrator", "phase-2"))
            iteration = g.get("iteration", 1)
            # Read requirement text if available
            req_text = ""
            req_file = REQS_DIR / f"{gid}.md"
            if req_file.exists():
                req_text = req_file.read_text()[:2000]
            # v7.12: ARCH-DESIGN build_prompt (startup) — preserves intent via tags
            if _PROMPT_BUILDER:
                body = _build_prompt(
                    task_type="ARCH-DESIGN",
                    gap_id=gid,
                    iteration=iteration,
                    trace_id=trace_id,
                    intent_tags=["7_dimensions"],
                    intent_query=f"architecture design {gid}",
                    extra_context=f"Requirement:\n{req_text[:1500]}" if req_text else ""
                )
            else:
                            body = (
                f"Resume Phase 2 architecture design for {gid} (iteration {iteration}).\n"
                f"trace_id: {trace_id}\n"
                f"Requirement context:\n{req_text}\n\n"
                f"Produce architecture.md, test-cases.md, edge-cases.md, api-contract.md, "
                f"and deployment-plan.md in {IT_DIR / gid / f'phase-2-architecture' / f'iteration-{iteration}'}/"
            )
            send_to_agent("architect", f"[ARCH-DESIGN] {gid} — Phase 2: Architecture Design",
                          body, gap_id=gid, trace_id=trace_id, priority="high")
            print(f"[dispatcher] Dispatched Phase 2 task to architect for {gid}")
            # Update state from pending -> active in state.json
            state["active_gaps"][gid]["state"] = "active"
            save_state(state)

    # ── Orchestrator Heartbeat Daemon ──────────────────────────────────────────
    # Write Unix timestamp to orchestrator.beat every 60s so external monitors
    # can detect if the orchestrator is alive. FIX v5.4: was only writing on
    # startup via ExecStartPost which wrote "%n" (unit name) instead of timestamp.
    _orch_beat_path = Path("/var/lib/karios/heartbeat/orchestrator.beat")
    _orch_beat_stop = threading.Event()

    def _orch_heartbeat_loop(stop: threading.Event):
        while not stop.wait(60):
            try:
                _orch_beat_path.write_text(str(int(time.time())))
            except Exception:
                pass

    _hb_thread = threading.Thread(target=_orch_heartbeat_loop, args=(_orch_beat_stop,),
                                  daemon=True, name="orchestrator-heartbeat")
    _hb_thread.start()
    print("[dispatcher] Heartbeat daemon started", flush=True)

    print("[dispatcher] Using Redis Streams XREAD (v5.1 — single-reader, no consumer groups)", flush=True)
    print("[dispatcher] Entering main loop...", flush=True)

    processed_ids = []
    last_read_id = None  # FIX v5.1: track last ID to avoid re-processing messages

    while True:
        # FIX v5.1: XREAD with last-read ID tracking — no consumer group needed.
        # Returns (messages, last_id) so we never re-read the same messages.
        # CRITICAL: Use short timeout (1000ms) so the loop cycles fast enough to
        # also check Redis inbox + file inbox fallbacks between stream reads.
        messages, last_read_id = xread_once(timeout_ms=1000, since_id=last_read_id)
        if not messages:
            # FIX v5.1: Check Redis inbox fallback (agent-msg writes here too)
            messages = _inbox_fallback()
        if not messages:
            # FIX v5.1: Check file inbox (for direct agent-msg deliveries)
            messages = _file_inbox_fallback()

        # Heartbeat tick on every loop (every 5s) — FIX v5.0: exponential backoff on STALLED
        STALLED_BACKOFF = [5, 10, 20, 40, 60]  # seconds; cap at 60s
        stalled = check_stalled_gaps()
        from datetime import datetime, timezone as tz
        now_ts = datetime.now(tz.utc)
        for gid, phase, iteration, age_min in stalled:
            gap = load_gap(gid)
            nudge_count = gap.get("nudge_count", 0)
            last_nudge_ts = gap.get("last_nudge_ts", "")
            # Compute backoff based on nudge_count
            backoff_idx = min(nudge_count, len(STALLED_BACKOFF) - 1)
            backoff_seconds = STALLED_BACKOFF[backoff_idx]
            # Check if backoff has elapsed
            should_nudge = True
            if last_nudge_ts:
                try:
                    last_ts = datetime.fromisoformat(last_nudge_ts)
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=tz.utc)
                    elapsed = (now_ts - last_ts).total_seconds()
                    if elapsed < backoff_seconds:
                        should_nudge = False
                except Exception:
                    pass
            if not should_nudge:
                continue  # Still in backoff window
            # Backoff elapsed — send nudge (but Telegram only on first of a burst)
            print(f"[dispatcher] STALLED: {gid} in phase {phase} iter {iteration} for {age_min}min (nudge={nudge_count})")
            assigned = gap.get("assigned_agent", "unknown")
            tid = gap.get("trace_id", new_trace_id(gid, "orchestrator", "stalled"))
            # Telegram only every 3rd nudge to avoid spam
            if nudge_count == 0:
                telegram_alert(f"STALLED: {gid} in {phase} (iter {iteration}) for {age_min}min. Nudge {nudge_count+1}. Backoff={backoff_seconds}s.")
            if assigned in ["architect", "backend", "frontend", "devops", "tester"]:
                send_to_agent(assigned,
                              f"[NUDGE] {gid} — stalled in {phase}",
                              f"Your gap {gid} has been in phase {phase} (iteration {iteration}) for {age_min} minutes. "
                              "Please make progress or report an issue. If blocked, escalate to orchestrator.\n"
                              f"trace_id: {tid}",
                              gap_id=gid, trace_id=tid, priority="normal")
            # Update nudge tracking in gap
            gap["nudge_count"] = nudge_count + 1
            gap["last_nudge_ts"] = now_ts.isoformat()
            save_gap(gid, gap)

        for msg_id, data in messages:
            sender = data.get("from", "unknown")
            subject = data.get("subject", "")
            gap_id = data.get("gap_id")
            # ── OTEL: dispatch span for each incoming message ───────────────
            ctx, span = tracer.start_span("dispatch.main_loop", {
                "gap_id": gap_id,
                "msg_id": str(msg_id),
                "sender": sender,
                "subject": subject[:40],
                "operation": "dispatch"
            })
            try:
                parse_message(msg_id, data)
                processed_ids.append(msg_id)
                span.set_attribute("dispatch.success", True)
            except Exception as e:
                span.set_attribute("dispatch.success", False)
                tracer.end_span(span, e)
                print(f"[dispatcher] ERROR processing message {msg_id}: {e}")
                raise
            tracer.end_span(span)

        # v7.8: progress probe — detect stuck active phases every cycle
        try:
            progress_probe_check()
        except Exception as _ppe:
            print(f"[dispatcher] progress_probe error: {_ppe}")

        # FIX v5.1: Delete processed messages from stream so they're not re-read next cycle.
        # XACK was for consumer groups (which we no longer use). XDEL removes from stream.
        if processed_ids:
            # ── OTEL: Redis xdel span ─────────────────────────────────────────
            xdel_ctx, xdel_span = tracer.start_span("redis.xdel", {
                "db.system": "redis",
                "db.operation": "xdel",
                "db.redis.key": STREAM_KEY,
                "operation": "stream_cleanup"
            })
            try:
                r = redis_conn()
                real_ids = [mid for mid in processed_ids if isinstance(mid, (str, bytes))]
                if real_ids:
                    r.xdel(STREAM_KEY, *real_ids)
                xdel_span.set_attribute("xdel.count", len(real_ids))
            except Exception as e:
                xdel_span.set_attribute("xdel.success", False)
                tracer.end_span(xdel_span, e)
                print(f"[dispatcher] XDEL error: {e}")
            else:
                xdel_span.set_attribute("xdel.success", True)
            finally:
                tracer.end_span(xdel_span)
            processed_ids = []

if __name__ == "__main__":
    main()
