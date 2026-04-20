# 1-dspy-gepa — STATUS

## Code completeness: FULL (no TODOs, no commented-out compile call)

`kairos-evolve.py` implements end-to-end:
- `load_session_trajectories(agent)` — reads `~/.hermes/sessions/*.jsonl`, filters by profile
- `build_trainset(agent, trajs)` — converts trajectories to `dspy.Example` per agent's signature
- `configure_dspy_lm()` — reads `/etc/karios/secrets.env` (`MINIMAX_API_KEY`/`HERMES_API_KEY`), configures `dspy.LM("openai/MiniMax-M2.7", api_base=...)`
- `evolve_agent(agent, iterations)` — full GEPA optimizer.compile() + re-score + write to `/var/lib/karios/orchestrator/profiles_evolved/<agent>.txt`
- 4 per-agent scorers (`score_arch_session`, `score_blind_review`, `score_code_request`, `score_e2e_session`)
- 4 per-agent signatures (`KairosArchSignature`, `KairosBlindReviewSignature`, `KairosCodeRequestSignature`, `KairosE2ESignature`)

## To activate

```bash
pip install --break-system-packages dspy-ai gepa
ln -s /root/agentic-workflow/pipeline/integrations/1-dspy-gepa/kairos-evolve.py /usr/local/bin/karios-evolve
chmod +x /usr/local/bin/karios-evolve
karios-evolve --agent backend --iterations 5 --dry-run     # verify
karios-evolve --all --iterations 5                          # evolve all 5 supported agents
```

## To schedule (weekly)

```bash
hermes cron add --name "kairos-evolve-weekly" \
  --schedule "0 4 * * 0" \
  --command "/usr/local/bin/karios-evolve --all --iterations 5" \
  --notify-channel telegram-hermes \
  --notify-on-failure-only
```

## Honest caveats

- **Cost**: GEPA's "auto=medium" runs ~50-100 LM calls per agent per iteration. At MiniMax pricing this is ~$2-10 per agent per evolution run. Budget accordingly before enabling weekly cron.
- **Scoring is heuristic**: scorers grep for `tool_use`, commit SHAs, JSON fences, etc. They reward correlates of good behavior, not direct quality measurement. Consider adding human-rated golden trajectories as the eval signal matures.
- **Profile load contract**: `prompt_builder.py` must read `EVOLVED_DIR / "<agent>.txt"` and prepend it. Verify the loader respects mtime; current `prompt_builder.py` is mtime-checked but the `EVOLVED_DIR` path may need wiring (next deploy cycle).
- **Trainset minimum**: 5 sessions required; agents with low traffic (orchestrator, monitor) are skipped today.

## Where the evolved prompt lands

```
/var/lib/karios/orchestrator/profiles_evolved/
├── architect.txt
├── backend.txt
├── frontend.txt
├── architect-blind-tester.txt
└── code-blind-tester.txt
```

`prompt_builder.py` checks this dir before falling through to baseline templates.

## Last evolution run summary

```
/var/lib/karios/orchestrator/last_evolution_run.json
```
