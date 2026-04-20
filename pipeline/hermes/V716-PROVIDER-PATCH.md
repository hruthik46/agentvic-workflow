Hermes v0.9.0 KAIROS patch line 6242 area: add tool_choice forwarding when tool_use_enforcement=true

## What it does

Patches /root/.hermes/hermes-agent/run_agent.py around the api_kwargs["tools"] = self.tools line.
After tools is set, also sets api_kwargs["tool_choice"] from:

1. environment variable HERMES_FORCE_TOOL_CHOICE (values: required, auto, any), OR
2. when self._tool_use_enforcement is True (which is the case for all 8 KAIROS agent profiles
   via /root/.hermes/config.yaml agent.tool_use_enforcement: true)

This is the OpenAI-compat equivalent of Anthropic-style {"type": "any"} — forces the model
to emit a tool_use block in every response. Verified working with MiniMax-M2.7 via direct
API test earlier in v7.10 retrospective.

## Why

Hermes\'s built-in tool_use_enforcement only injects a prompt instruction (TOOL_USE_ENFORCEMENT_GUIDANCE).
MiniMax-M2.7 ignores this for long prompts (>4K chars) — drifts to prose-only output.
Per direct API test: tool_choice="required" makes MiniMax comply 100% with tool emission.

## Apply on disaster-recovery node

Same sed equivalent of the patch in v7.16 commit. Activated by setting
agent.tool_use_enforcement: true in /root/.hermes/config.yaml (already done in v7.5).

## Risk

Will break Hermes on schema upgrade (run_agent.py:6242 area might shift). Re-apply manually
after any 'hermes update' command.
