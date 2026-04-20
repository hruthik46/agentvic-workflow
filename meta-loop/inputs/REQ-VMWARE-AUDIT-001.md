# REQ-VMWARE-AUDIT-001 — Audit + Fix VMware Provider end-to-end

You are the KAIROS pipeline. Audit the VMware provider implementation in `karios-migration` and fix every bug, gap, or rough edge you find. Use the obsidian vault as the source of truth for prior knowledge.

## Source code locations on .106 (already pulled to latest)

- **karios-migration** (Go): `/root/karios-source-code/karios-migration/`
  - VMware provider: `internal/vmware/`, `internal/migration/provider_vmware.go`, `pkg/providers/vmware/`
  - Use `get_minimal_context(task="audit vmware provider")` FIRST — pre-built graph at `.code-review-graph/graph.db`
- **karios-web** (React): `/root/karios-source-code/karios-web/`
  - VMware-related UI: `src/lib/migration/components/`, `src/lib/control-center/`
  - On branch `feature-arch-it-arch-v9` with bf6775f6 latest

## Knowledge base sources (read FIRST via `karios-vault search`)

In Obsidian at `/opt/obsidian/config/vaults/My-LLM-Wiki/raw/workspace/karios-knowledge/`:
- `vmware-to-cloudstack-migration-knowledge-2026-04-07.md` — practical ESXi 8.0.3 findings, 4-tier transfer, govmomi API, all VM cases
- `vmware-blind-test-report-2026-04-08.md` — doc-only blind test 6.25/10, 7 blocking gaps
- `vmware-blind-test-v2-real-2026-04-08.md` — 5/5 real migrations PASSED, score 8.3/10, Tier 4=101MB/s, rbd-nbd required
- `vmware-blind-test-v3-validation-2026-04-09.md` — internet-validated, 8/10, all 3 critical fixes applied
- `vmware-all-setups-and-methods-2026-04-09.md` — 12 storage types × 6 licenses × 8 architectures, competitor analysis, VDDK commands, CBT warm migration
- `vmware-final-validation-2026-04-09.md` — parallel blind agents, methods 8/10, code 8.5/10
- `vmware-genius-agent-solutions-2026-04-09.md` — 7.5/10, 12 problems found + solved
- `vmware-implementation-complete-2026-04-09.md` — implementation complete report
- `vmware-vcenter-multi-host-migration-2026-04-13.md` — multi-host migration scenarios
- `vmware-blind-test-gui-2026-04-16.md` — blind test of GUI side
- `proxmox-vmware-parity-fixes-2026-04-09.md` — Proxmox vs VMware parity gaps

Architecture/implementation guide:
- `karios-migration/docs/VMWARE-IMPLEMENTATION-GUIDE.md` — 16 interface methods, govmomi patterns
- `karios-migration/docs/VMWARE-LICENSING.md` (if present)
- `karios-migration/internal/vmware/README.md` (if present)

Real test infrastructure:
- VMware ESXi 8.0.3 free at `192.168.115.232` (root/karios@12345, ha-datacenter, 9 test VMs)
- VMware ESXi licensed at `192.168.115.23` (CBT/vMotion/advanced features)
- 12 storage types previously documented: VMFS, vSAN, NFS, vVol, RDM physical, RDM virtual, etc.

## What I want fixed

**Audit categories** (rate each 0-10 in your `[ARCH-COMPLETE]`):

1. **OS detection + mutation (govmomi)** — does provider correctly identify Linux/Windows/BSD/Solaris guest? Does it mutate to CloudStack-compatible drivers (virtio, VMBus removal, etc.)?

2. **Disk transfer paths**:
   - Tier 1 (VDDK) — only with paid license
   - Tier 2 (SSH + ovftool) — fallback for free license, currently primary
   - Tier 3 (govc pipe) — 114 MB/s validated
   - Tier 4 (NBD) — 101 MB/s, rbd-nbd required
   Are all 4 implemented? Do we degrade gracefully when license is free?

3. **CBT (Changed Block Tracking)** — for warm migration. Detect license capability, fall back to cold migration if not. Currently blocked on free license.

4. **UEFI / Secure Boot** — boot mode detection from VMX firmware="efi" + secureBoot=TRUE. Map to CloudStack `bootMode=Secure`. Test against all 9 VMs.

5. **VMDK paths** — handle `[datastore] path/disk.vmdk` syntax across vSphere versions. Datastore-relative vs absolute paths.

6. **Multi-NIC / IP+MAC preservation** — see `iptonetworklist[N]` precedence rules learned during 2026-04-17 multi-NIC P0. Current fix: if NICAssignments present → ONLY iptonetworklist[N], else → networkids + ipaddress.

7. **Snapshot lifecycle** — create snapshot BEFORE clone, register in store IMMEDIATELY (per L2 landmine fix in iter22). CleanupExport must find + delete even on failure.

8. **License detection** — `IsFreeLicense()` probing licenseManager.List. Preflight fail on `esxi_license_vs_vm_state` when running VM + free edition.

9. **Firmware columns** — 5 NULLABLE columns (firmware, machine_type, bios, boot_mode, root_disk_controller) added in iter22 audit-wave. UpdateFirmwareProjection called from engine_deploy.go.

10. **Health check + verify stage** — does verify probe the guest (not just ping)? Does it virsh dumpxml the firmware assertion? Does HealthCheckResult get persisted?

11. **Frontend (karios-web)** — VMware-specific UI patterns: SlideInPanel for source picker, DeleteConfirmModal, Tabs, StatsCard. Validate against `karios_web_ui_patterns` rule. Reject custom widgets.

12. **Test coverage** — does `playwright-tests/` cover VMware-specific paths? Multi-NIC, UEFI, multi-disk, BSD-EFI cases?

## Constraints

- **Read prior knowledge FIRST** via `karios-vault search "<keywords>"` — every bug already has an RCA somewhere
- **Use `get_minimal_context(task=...)` FIRST** for any code-touching audit (8.2× token reduction)
- **HARD PRE-SUBMIT GATE**: Phase 2 architect must produce 5 docs ≥ 2KB each
- **Iteration loop**: rating < 8 → revise back to architect/coder; K_max = 5/3/3 per phase
- **Gitea push protocol**: backend/frontend push to `gitea.karios.ai/KariosD/<repo>` after fix; never push agentic-workflow files (blacklist enforced)
- **Telegram**: every phase boundary fires `notify_phase_transition()`; Sai will see scores + handoffs in real-time
- **Do NOT retest karios-test thick disk on Ceph until cluster restored** (per memory `vmware_migration_iter22_final`)

## Success criteria

- All 12 audit categories rated 0-10 in architecture.md
- Per category: list of bugs found + concrete fixes proposed
- Backend implements fixes in karios-migration; opens PR to gitea
- Frontend updates UI if needed (probably minimal for backend-heavy audit)
- E2E test against ESXi 192.168.115.232 (9 test VMs) — at least 3 successful migrations across different OS types
- DevOps deploys to staging; monitor confirms 24h healthy
- v11 quality bar: zero synthesized JSON injections at gates

## Telegram interaction model (NEW v7.7)

Sai will follow this in the Hermes Telegram channel. Phase events arrive automatically. Sai can ask questions via:
- `/status` — agent heartbeats + active gaps
- `/pending` — pending HITL approvals
- `/ask <question>` — routes to architect for free-form answer (~60s response)
- `/approve <id>` / `/reject <id>` — approve/reject pending decisions
- Free text — auto-routed as `[REQUIREMENT]` (creates a new gap)

The orchestrator will fire phase notifications to the channel for THIS gap. Stay in the channel.

trace_id: trace_vmware_audit_001
