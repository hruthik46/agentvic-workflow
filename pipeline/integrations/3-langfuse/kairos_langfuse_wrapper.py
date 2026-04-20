"""kairos_langfuse_wrapper.py — Langfuse self-hosted trace wrapper for KAIROS.

Per v7.16 research: Langfuse (21K stars, OSS) wrapped around event_dispatcher.py +
agent-worker gives per-turn trace tree, cost, latency. Closes the V (Validation/audit)
gap. Self-hosted on .106 to avoid vendor lock-in.

Setup:
    # 1. Run Langfuse server via docker-compose (see langfuse-docker-compose.yml)
    docker-compose -f langfuse-docker-compose.yml up -d
    # 2. Pip install client
    pip install --break-system-packages langfuse
    # 3. Add to /etc/karios/secrets.env:
    LANGFUSE_HOST=http://localhost:3000
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...
    # 4. Import this module from event_dispatcher.py (already added)

Usage in event_dispatcher.py:
    from kairos_langfuse_wrapper import init_langfuse, trace_dispatch, trace_hermes_call
    init_langfuse()
    with trace_dispatch(gap_id, agent, subject) as span:
        send_to_agent(...)
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Optional, Dict, Any

# Soft import — Langfuse may not be installed yet
try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

_client: Optional["Langfuse"] = None


def init_langfuse() -> bool:
    """Initialize Langfuse client. Returns True if successful, False if disabled/missing."""
    global _client
    if not LANGFUSE_AVAILABLE:
        print("[langfuse] not installed — skipping (pip install langfuse to enable)")
        return False
    host = os.environ.get("LANGFUSE_HOST")
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not (host and pk and sk):
        print("[langfuse] env vars missing (LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY) — disabled")
        return False
    try:
        _client = Langfuse(host=host, public_key=pk, secret_key=sk)
        print(f"[langfuse] initialized (host={host})")
        return True
    except Exception as e:
        print(f"[langfuse] init failed: {e}")
        return False


@contextmanager
def trace_dispatch(gap_id: str, agent: str, subject: str, trace_id: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None):
    """Wrap a dispatcher → agent send_to_agent call.

    Records: gap_id, agent, subject, duration, success/failure, output bytes.
    """
    if not _client:
        yield None
        return
    trace = _client.trace(
        name=f"dispatch-{agent}-{subject[:30]}",
        user_id=gap_id,
        session_id=trace_id or gap_id,
        metadata={"gap_id": gap_id, "agent": agent, "subject": subject, **(metadata or {})},
        tags=["kairos", "dispatch", agent],
    )
    try:
        yield trace
        trace.update(output={"status": "success"})
    except Exception as e:
        trace.update(output={"status": "error", "error": str(e)[:500]})
        raise
    finally:
        try:
            _client.flush()
        except Exception:
            pass


@contextmanager
def trace_hermes_call(agent: str, model: str, prompt_chars: int,
                      gap_id: str = "", trace_id: Optional[str] = None):
    """Wrap a Hermes invocation. Records token counts + cost + duration."""
    if not _client:
        yield None
        return
    gen = _client.generation(
        name=f"hermes-{agent}",
        user_id=gap_id,
        session_id=trace_id or gap_id,
        model=model,
        metadata={"agent": agent, "prompt_chars": prompt_chars},
        tags=["kairos", "hermes", agent],
    )
    try:
        yield gen
    except Exception as e:
        gen.update(level="ERROR", status_message=str(e)[:500])
        raise
    finally:
        try:
            _client.flush()
        except Exception:
            pass


def trace_phase_event(gap_id: str, event: str, from_agent: str, to_agent: str,
                      rating: Optional[int] = None, summary: str = ""):
    """Record a phase-transition event (notify_phase_transition wraps this)."""
    if not _client:
        return
    try:
        _client.event(
            name=f"phase-{event}",
            user_id=gap_id,
            metadata={"from_agent": from_agent, "to_agent": to_agent, "rating": rating, "summary": summary[:300]},
            tags=["kairos", "phase-transition", event],
        )
        _client.flush()
    except Exception as e:
        print(f"[langfuse] event log failed: {e}")


# ─── docker-compose for self-host ────────────────────────────────────────────
# Save as langfuse-docker-compose.yml next to this file:
DOCKER_COMPOSE_TEMPLATE = """\
version: "3.5"
services:
  langfuse-db:
    image: postgres:15
    restart: always
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: <set-on-target>
      POSTGRES_DB: langfuse
    volumes:
      - langfuse-db-data:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:54320:5432"  # bind to localhost only

  langfuse:
    image: langfuse/langfuse:latest
    restart: always
    depends_on:
      - langfuse-db
    environment:
      DATABASE_URL: postgresql://langfuse:<set-on-target>@langfuse-db:5432/langfuse
      NEXTAUTH_URL: http://192.168.118.106:3000
      NEXTAUTH_SECRET: <set-on-target — generate via openssl rand -base64 32>
      SALT: <set-on-target — generate via openssl rand -base64 32>
      ENCRYPTION_KEY: <set-on-target — generate via openssl rand -hex 32>
      TELEMETRY_ENABLED: "false"
    ports:
      - "192.168.118.106:3000:3000"

volumes:
  langfuse-db-data:
"""

if __name__ == "__main__":
    # Run a quick connectivity test
    init_langfuse()
    if _client:
        print("Connection OK. Run a test trace:")
        with trace_dispatch("TEST-001", "test-agent", "[TEST]") as t:
            print(f"  trace_id: {t.id if t else 'no client'}")
        print("✓ done")
    else:
        print("Setup steps:")
        print("  1. Save DOCKER_COMPOSE_TEMPLATE to langfuse-docker-compose.yml")
        print("  2. Replace <set-on-target> placeholders")
        print("  3. docker-compose up -d")
        print("  4. Open http://192.168.118.106:3000, sign in, create project, copy keys")
        print("  5. Add LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY to /etc/karios/secrets.env")
        print("  6. Restart karios-orchestrator-sub + all 8 agent services")
