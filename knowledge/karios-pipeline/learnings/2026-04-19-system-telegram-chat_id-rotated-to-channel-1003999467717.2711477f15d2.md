---
type: learning
created: 2026-04-19T07:32:20.525695+00:00
agent: system
severity: MEDIUM
category: orchestration
title: Telegram chat_id rotated to channel -1003999467717
tags: ["learning", "system", "orchestration"]
---

Old: 6817106382 (private DM with Sai). New: -1003999467717 (channel name=Hermes, type=channel). Rotation required because every agent worker initializes HITLInterruptHandler which long-polls Telegram independently — 9 concurrent pollers caused 409 Conflict on getUpdates. Workaround: stop all 9 agents, race-poll, capture chat_id from channel_post update. Long-term: centralize HITL polling in orchestrator so only ONE process holds the long-poll.
