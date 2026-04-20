# API Contract v9.0
## Subjects (orchestrator handlers)
- [REQUIREMENT] gap_id — new gap input
- [RESEARCH-COMPLETE] gap_id — phase 1 done
- [ARCH-COMPLETE] gap_id iteration N (alias [ARCHITECTURE-COMPLETE]) — phase 2 done
- [ARCH-REVIEWED] gap_id iteration N — blind-tester review (JSON body required)
- [CODING-COMPLETE] gap_id iteration N — backend/frontend done
- [FAN-IN] gap_id — alias for CODING-COMPLETE
- [API-SYNC] gap_id — both coders confirmed alignment
- [STAGING-DEPLOYED] gap_id (alias [DEPLOYED-STAGING], [DEPLOY-COMPLETE]) — staging deploy done
- [E2E-RESULTS] gap_id iteration N (alias [BLIND-E2E-RESULTS], [E2E-COMPLETE]) — phase 4 done (JSON body required)
- [PROD-DEPLOYED] gap_id (alias [DEPLOYED-PROD], [PRODUCTION-DEPLOYED]) — prod deploy done
- [MONITORING-COMPLETE] gap_id — phase 6 done

## CLI
- karios-vault learning|critique|rca|bug|fix|decision|memory|search|recent
- karios-flush-decide agent task_id — exit 0/1/2
- karios-meta-runner dispatch|status|stop|rollback
- karios-dlq list|replay|stats|trim|force-replay
- karios-contract-test (auto every 5 min via systemd timer)

## Telegram alerts (Hermes channel -1003999467717)
- 🔍 [ARCH-REVIEWED] — score N/10 + handoff
- 🧪 [E2E-RESULTS] — score N/10 + handoff
- 📦 [STAGING-DEPLOYED] — handoff to tester+code-blind-tester
- 🚀 [PROD-DEPLOYED] — handoff to monitor
- ❌ DOWN/RECOVERED via watchdog
