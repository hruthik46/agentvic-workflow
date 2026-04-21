"""Send the SAME prompt body backend received, directly to MiniMax. Compare output."""
import json, subprocess, time
from pathlib import Path

# 1. Get the EXACT prompt backend received
import redis as _r
R = _r.Redis(host="192.168.118.202", username="karios_admin", password="Adminadmin@123")
entries = R.xrevrange("stream:backend-worker", count=10)
target_body = None
for entry_id, fields in entries:
    payload = json.loads(fields.get(b"payload", b"{}").decode())
    if "iteration 7" in payload.get("subject", "") and "ARCH-IT-018" in payload.get("subject", ""):
        target_body = payload.get("body", "")
        print(f"Found backend's iter 7 prompt: {len(target_body)} chars")
        print(f"  subject: {payload['subject']}")
        break

if not target_body:
    print("No iter 7 prompt found in backend stream")
    raise SystemExit(1)

# 2. Send EXACTLY this body to MiniMax directly with backend's same model + tool config
PK = subprocess.run(
    ["bash", "-c", "grep 'api_key:' /root/.hermes/profiles/backend/config.yaml | head -1 | sed 's/.*api_key:[[:space:]]*//'"],
    capture_output=True, text=True, timeout=5
).stdout.strip()

# Tools backend has (terminal, read_file, file_write — same as Hermes provides)
tools = [
    {"type": "function", "function": {"name": "terminal", "description": "run bash command",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "read file lines",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
        "required": ["path"]}}},
    {"type": "function", "function": {"name": "file_write", "description": "write file content",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}}},
]

# Add the SOUL-style system message Hermes prepends
system_msg = """You are the backend agent. Your role is defined in your profile at ~/.hermes/profiles/backend/SOUL.md.

You write Go code following the architecture spec. You commit + push real code. You do NOT write prose."""

print(f"\n=== SENDING TO MINIMAX DIRECTLY ===")
print(f"  prompt: {len(target_body)} chars")
print(f"  tools: {len(tools)}")
print(f"  tool_choice: required")

payload = {
    "model": "MiniMax-M2.7",
    "messages": [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": target_body},
    ],
    "tools": tools,
    "tool_choice": "required",
    "max_tokens": 4000,
}

r = subprocess.run(
    ["curl", "-sS", "-X", "POST", "https://api.minimax.io/v1/chat/completions",
     "-H", f"Authorization: Bearer {PK}",
     "-H", "Content-Type: application/json",
     "-d", json.dumps(payload)],
    capture_output=True, text=True, timeout=180
)

try:
    d = json.loads(r.stdout)
    if "error" in d or d.get("base_resp", {}).get("status_code", 0) not in (0, None):
        print(f"\nAPI ERROR: {r.stdout[:600]}")
    else:
        ch = d.get("choices", [{}])[0]
        msg = ch.get("message", {})
        content = msg.get("content", "")
        tcs = msg.get("tool_calls", [])
        usage = d.get("usage", {})
        finish = ch.get("finish_reason")

        print(f"\n=== MINIMAX RESPONSE ===")
        print(f"  finish_reason: {finish}")
        print(f"  content_chars: {len(content)}")
        print(f"  tool_calls: {len(tcs)}")
        print(f"  prompt_tokens: {usage.get('prompt_tokens')}, completion_tokens: {usage.get('completion_tokens')}")

        if content:
            think_idx = content.find("</think>")
            if think_idx > 0:
                think = content[:think_idx+8]
                print(f"\n  <think> block ({len(think)} chars) — first 600 chars:")
                print(f"  {think[:600]}")
                content_after = content[think_idx+8:]
                if content_after.strip():
                    print(f"\n  POST-THINK CONTENT ({len(content_after)} chars):")
                    print(f"  {content_after[:600]}")

        if tcs:
            print(f"\n=== TOOL CALLS MINIMAX PRODUCED ===")
            for i, tc in enumerate(tcs[:10]):
                fn = tc.get("function", {})
                args = fn.get("arguments", "")
                print(f"  [{i+1}] {fn.get('name')}({args[:200]})")
        else:
            print(f"\n  ✗ NO tool_calls in response despite tool_choice=required!")
except Exception as e:
    print(f"parse err: {e}")
    print(r.stdout[:800])
