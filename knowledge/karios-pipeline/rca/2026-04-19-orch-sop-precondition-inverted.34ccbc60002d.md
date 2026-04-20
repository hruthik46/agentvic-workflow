---
type: rca
created: 2026-04-19T06:58:23.111824+00:00
agent: system
incident_id: ORCH-SOP-PRECONDITION-INVERTED
severity: MEDIUM
files_affected: ["/usr/local/bin/sop_engine.py", "/etc/karios/v4/sops/architect-agent.yaml"]
tags: ["rca", "system", "medium"]
---

# RCA: ORCH-SOP-PRECONDITION-INVERTED

## Symptom
Architect SOP requires output files (architecture.md etc) to exist as PRECONDITION; on iteration 1 they cannot exist yet; dispatch was blocked.

## Root Cause
v3 sop_engine.check_pre_conditions reads required_output_files and checks os.path.exists — semantically wrong for first iteration. SHOULD be a postcondition check.

## Fix
Pre-create placeholder files in iteration-tracker dir so SOP precheck unblocks. Long-term fix: move required_output_files to postcondition check.

## Files Affected
- /usr/local/bin/sop_engine.py
- /etc/karios/v4/sops/architect-agent.yaml

## Lessons
- Output-file existence is not a precondition
- SOP engine semantics need review during v6.x
