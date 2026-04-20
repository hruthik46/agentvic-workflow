[RESEARCH-COMPLETE] ARCH-IT-018

gap_id: ARCH-IT-018
trace_id: trace_tg_REQ-TG-1776689817
requirement: CBT warm migration implementation

## Research Summary

CBT (Changed Block Tracking) warm migration is FEASIBLE and well-understood.

### What Was Done
1. Read VMWARE-IMPLEMENTATION-GUIDE.md (CBT section documented at lines 382-392)
2. Read provider.go:515 — IncrementalExporter() is a stub returning (nil, false)
3. Read IncrementalProvider interface (pkg/provider/source.go:49-53) — clean and sufficient
4. Read liveExporter and snapshotProvider (export.go L864 and L1391) — already implemented
5. Verified no cbtAvailable field exists yet on Provider struct
6. Checked govmomi source — QueryChangedDiskAreas API exists and is accessible
7. Reviewed architecture.md (L2781-2784) for CBT design notes

### Key Findings
- Architecture already designed in docs/VMWARE-IMPLEMENTATION-GUIDE.md and ARCHITECTURE.md
- IncrementalProvider interface already defined — just needs implementation
- CBT uses govmomi QueryChangedDiskAreas API — all needed APIs are available
- Free ESXi: CBT blocked → IncrementalExporter returns (nil, false) → full copy fallback
- Licensed ESXi: CBT available → create cbtExporter implementing CreateSnapshot + ExportIncremental

### Blocking Issues for Manual Testing
- ESXi SSH credentials unavailable (192.168.115.232 SSH blocked)
- Go version mismatch (1.19.8 vs 1.25 needed)
- Could NOT test on real infrastructure — credentials needed

### Architecture Design (in /tmp/arch-it-018/architecture.md)
- New file: internal/providers/vmware/cbt.go (~450 lines)
- cbtExporter struct implementing provider.IncrementalProvider
- detectCBTForVM(ctx, vmID) — probe CBT availability per VM
- CreateSnapshot → snapshot for CBT tracking
- ExportIncremental → QueryChangedDiskAreas → NFC transfer of changed blocks
- Add CapabilityIncremental to provider.Capability constants
- 10 edge cases documented, 10 test cases defined

### Files Produced
- /tmp/arch-it-018/research-findings.md — detailed findings
- /tmp/arch-it-018/architecture.md — implementation architecture
- /tmp/arch-it-018/manual-test-results.md — manual test log
- /tmp/arch-it-018/environment-matrix.md — infra availability matrix

## Status: PHASE 1 RESEARCH COMPLETE
## Recommendation: Proceed to Architecture Review (Phase 2)
## Blocking: Need ESXi/vCenter credentials for real-infra validation before coding