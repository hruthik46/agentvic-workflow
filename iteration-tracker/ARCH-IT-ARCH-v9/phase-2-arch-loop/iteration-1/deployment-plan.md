# Deployment Plan v9.0
v9 IS NO-OP for production code (v7.3 already live). Deploy = verify-and-confirm protocol:

1. md5sum /var/lib/karios/orchestrator/event_dispatcher.py — confirm matches /tmp/karios-v6/src/event_dispatcher.v7.3.py
2. systemctl is-active karios-orchestrator-sub — must be active
3. /usr/local/bin/karios-contract-test — must pass 5/5
4. /usr/local/bin/agent-watchdog.py — 9/9 must be alive
5. Telegram test: curl --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" — must return ok:true
6. Backup /var/lib/karios/backups/{ts}-pre-v7.3/ exists for rollback
7. If all 6 pass: send [STAGING-DEPLOYED] then [PROD-DEPLOYED]
8. If any fail: send [ESCALATE] to Sai via Telegram

Rollback: cp /var/lib/karios/backups/{latest-pre-v7.3}/event_dispatcher.py.v7.1 /var/lib/karios/orchestrator/event_dispatcher.py && systemctl restart karios-orchestrator-sub
