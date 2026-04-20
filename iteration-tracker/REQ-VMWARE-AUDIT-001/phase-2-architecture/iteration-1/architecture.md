# REQ-VMWARE-AUDIT-001 — Phase 2 Architecture: VMware Provider Audit
**trace_id:** trace_vmware_audit_001 | **iteration:** 1 | **agent:** architect

---

## Category Ratings Summary

| # | Category | Score | Status |
|---|----------|-------|--------|
| 1 | OS detection + mutation (govmomi) | 8/10 | Good — minor gaps |
| 2 | Disk transfer paths (Tier 1-4) | 7/10 | Partial — missing Tier 1/4 |
| 3 | CBT (Changed Block Tracking) | 5/10 | Informational only |
| 4 | UEFI / Secure Boot | 9/10 | Excellent |
| 5 | VMDK paths | 9/10 | Excellent |
| 6 | Multi-NIC / IP+MAC preservation | 8/10 | Good |
| 7 | Snapshot lifecycle | 9/10 | Good |
| 8 | License detection | 7/10 | Partial — preflight not wired |
| 9 | Firmware columns | 8/10 | Good |
| 10 | Health check + verify stage | 5/10 | Weak — guest not probed |
| 11 | Frontend (karios-web) | 6/10 | Partial — no VMware-specific UI |
| 12 | Test coverage | 4/10 | Minimal |

---

## Category 1: OS Detection + Mutation (govmomi) — Score: 8/10

### Current Implementation
- **OS Detection**: `MapVMwareGuestID` in `internal/osmap/osmap.go` (lines 51-203) maps VMware `GuestId` strings to CloudStack OS descriptions. Covers Ubuntu, Debian, CentOS, RHEL, SUSE, Fedora, Oracle Linux, Rocky, AlmaLinux, Windows (desktop + server), FreeBSD, Solaris, Darwin.
- **Windows Detection**: `isWindowsVM(osType string)` in `internal/migration/morph.go` (lines 14-30) detects Windows via `win*` / `windows*` prefix matching.
- **NIC Model Detection**: `parseVMNICs` in `discovery.go` (lines 390-442) detects `VirtualVmxnet3`, `VirtualE1000`, `VirtualE1000e`.
- **Controller Detection**: `detectControllerType` in `discovery.go` (lines 662-689) detects `ParaVirtualSCSIController` (pvscsi), `VirtualLsiLogicSASController` (lsi_sas), `VirtualLsiLogicController` (lsi_logic), `VirtualAHCIController` (ahci), `VirtualIDEController` (ide).
- **Mutation**: `runMorph` + `injectVirtIODrivers` in `morph.go` uses guestfish to inject VirtIO .sys drivers + registry Start=0 for vioscsi/viostor.

### Bugs / Gaps
- **BUG-1**: `MapVMwareGuestID` returns "Other (64-bit)" for unknown VMware guest IDs silently. No warning logged. VMs with uncommon OS types (e.g., `crx76k`, `vmkernel65Guest`, `bottlerocket`) silently get wrong OS description → template may not boot correctly.
- **BUG-2**: FreeBSD UEFI detection: `freebsd14_64Guest` maps to "FreeBSD (64-bit)" but FreeBSD 14 UEFI requires `OVMF_CODE.fd` with proper GOP/UEFI console setup. No distinction between BIOS-boot and UEFI-boot FreeBSD. Bootstrapper cannot know which OVMF variant to inject.
- **BUG-3**: Windows Server 2025 (if VMware exposes it as `windows2025srv_64Guest`) is not in the map — falls through to "Windows Server 2019" via substring. Acceptable but should be explicit.
- **GAP-1**: No detection of NVMe controller (`VirtualNVMEController`) in `detectControllerType`. NVMe on KVM requires ` virtio-blk` or `nvme` emulation — neither maps cleanly from VMware's `vmnvme` adapter type.

### Fixes Proposed
1. Add logging when `MapVMwareGuestID` falls through to "Other (64-bit)": `logger.Warn("unmapped VMware guest ID", "guest_id", guestID)`.
2. Add `freebsd14_64Guest` + UEFI detection via `Config.Firmware == "efi"` → CloudStack OS should be "BSD Unix (64-bit)" with UEFI boot mode forced.
3. Add explicit `windows2025srv_64Guest` → "Windows Server 2022 (64-bit)".
4. Add `VirtualNVMEController` detection → `Format: "raw:nvme"` flag so deploy can warn about NVMe emulation gaps on KVM.

### Files to Change
- `internal/osmap/osmap.go`: Add warning log for unmapped guest IDs; add `windows2025srv_64Guest`.
- `internal/providers/vmware/discovery.go`: Add `VirtualNVMEController` to `detectControllerType`.

---

## Category 2: Disk Transfer Paths (Tier 1-4) — Score: 7/10

### Current Implementation
The provider has THREE transfer mechanisms:
1. **Tier 2-equivalent (SSH streaming)**: `ExportDisk` returns `Protocol: "vmware_ssh"` + `vmfsPath`. The actual SSH dd is in the transfer layer (not in the provider).
2. **Tier 3-equivalent (NFC HTTPS)**: `ExportDisk` returns `Protocol: "vmware_nfc_direct"` + ESXi `/folder/` HTTPS URL. `transferViaVMwareNFC()` in `vmware_nfc.go` streams at ~115 MB/s.
3. **Tier 3-live (NFC via ExportSnapshot)**: `liveExporter.ExportLive()` uses `govmomi.ExportSnapshot` NFC lease to stream running VM disk at ~115 MB/s. Includes fsfreeze quiesce.
4. **SSH dd fallback**: Old path, ~17 MB/s.

### Bugs / Gaps
- **BUG-4**: Tier 1 (VDDK) not implemented. Requires: (a) VDDK library download from VMware (requires login, non-redistributable), (b) `nbdkit` plugin. Not feasible for automated pipeline. **Acceptable gap** — VDDK is only needed for environments where SSH is blocked AND NFS is unavailable.
- **BUG-5**: Tier 4 (NBD via `rbd-nbd`) not implemented. Requires Ceph `rbd-nbd` on the KVM host + CloudStack primary storage configured. The transfer layer would need to: (a) attach the VMDK as an NBD device, (b) `qemu-img convert` from NBD to qcow2. Not wired at all. **Acceptable gap for now** — current pipeline uses NFC HTTPS which is ~115 MB/s, sufficient.
- **GAP-2**: The `IncrementalExporter()` always returns `nil, false` (line 516 in provider.go). If CBT is available on a licensed ESXi, the system cannot do warm migration incrementally. This is documented as "Phase 2" but no ETA.

### Fixes Proposed
- Tier 1/4 gaps are **environment-specific** and acceptable given the NFC HTTPS path already achieves 115 MB/s.
- Tier 3 (warm migration via CBT) should be tracked as a separate backlog item for licensed ESXi customers.

---

## Category 3: CBT (Changed Block Tracking) — Score: 5/10

### Current Implementation
- `ValidateVM()` detects CBT via `config.ChangeTrackingEnabled` flag and `disk.ChangeId` on backing (export.go lines 527-547, 612-622). This is **informational only** — a validation check that says "CBT is on but we use full copy."
- `IncrementalExporter()` returns `nil, false` — no warm migration implemented.

### Bugs / Gaps
- **GAP-3**: No actual incremental (CBT-based) transfer. Running VMs require full disk copy even when CBT is enabled. For large disks (500GB+), this adds significant transfer time.
- **GAP-4**: The `isESXiLicenseError()` function correctly detects free license blocks but the preflight stage does NOT call `IsFreeLicense()` before deciding to use the running-VM path. A running VM on free ESXi will hit the license error at ExportSnapshot time, causing saga rollback.

### Fixes Proposed
1. Wire `IsFreeLicense()` call into preflight for running VMs on VMware sources. If running VM + free license → fail preflight with clear message.
2. Add `IncrementalExporter` implementation stub that returns a meaningful error: "CBT-based warm migration requires vSphere license. Use cold (stopped VM) migration on free ESXi."

---

## Category 4: UEFI / Secure Boot — Score: 9/10

### Current Implementation
- `Config.Firmware` ("efi" vs "bios") → `mapFirmware()` → `BIOSTypeUEFI` or `BIOSTypeLegacy`.
- `BootOptions.EfiSecureBootEnabled` → `SecureBoot: true/false`.
- `deriveMachineType("efi")` → "q35"; `deriveMachineType("bios")` → "pc-i440fx".
- `deriveBiosLabel("efi", secureBoot=true)` → "OVMF-Secure"; `deriveBiosLabel("efi", false)` → "EFI".
- `UpdateFirmwareProjection` persists 5 columns: `firmware`, `machine_type`, `bios`, `boot_mode`, `root_disk_controller`.

### Bugs / Gaps
- **BUG-6**: `deriveBiosLabel` uses "OVMF-Secure" for Secure Boot, but CloudStack `bootMode` does not have a "Secure" variant — only "BIOS", "UEFI", "UEFI+SecureBoot". The UI needs to pass `bootMode=Secure` to CloudStack deploy, but the current `bios` column stores "OVMF-Secure" which doesn't map directly.
- **BUG-7**: No validation that the target CloudStack zone has UEFI boot capability. If a UEFI VM is migrated to a BIOS-only zone, deployment silently falls back to BIOS boot → VM may not boot.

### Fixes Proposed
1. Change `deriveBiosLabel` to return "Secure" instead of "OVMF-Secure" (maps directly to CloudStack `bootMode`).
2. Add zone capability check in preflight: if `BIOSType == UEFI` and zone doesn't support UEFI → preflight error.

---

## Category 5: VMDK Paths — Score: 9/10

### Current Implementation
- `resolveVMFSPath()` converts `[datastore] vm/vm.vmdk` → `/vmfs/volumes/datastore/vm/vm.vmdk`.
- Handles delta snapshots: `vm-000003.vmdk` detected via suffix pattern (6-digit and 3-digit variants).
- Auto-consolidation via `RemoveAllSnapshot` before export.
- 0-byte flat VMDK detection prevents silent data loss.
- Descriptor parsing for monolithic VMDKs (Strategy 0 in `discoverFlatVMDK`).
- Glob-safe SSH for delta chain size resolution.

### Bugs / Gaps
- **BUG-8**: RDM (Raw Device Mapping) disks are detected and blocked (`StorageTypeRDM`), but `VirtualDiskRawDiskMappingVer1BackingInfo` is only partially handled — the physical vs. virtual RDM distinction is not exposed. Virtual RDM (vRDM) can theoretically be migrated; physical RDM (pRDM) cannot.
- **BUG-9**: The `isSnapshotDeltaPath` check uses a simple suffix pattern (`-%06d.vmdk` or `-%03d.vmdk`). A disk named `something-000001.vmdk` that is NOT a snapshot delta (e.g., a manually named disk) would be misidentified as a delta.

### Fixes Proposed
1. Add distinction between vRDM and pRDM: check `Backing.GetVirtualDevice().Backing.Info` for `RawDiskMappingBackingInfoKind`.
2. Improve delta detection: check BOTH the suffix pattern AND `Backing.Parent != nil` — a file with a delta-like name but no parent is not a snapshot delta.

---

## Category 6: Multi-NIC / IP+MAC Preservation — Score: 8/10

### Current Implementation
- VMware discovery collects all NICs (vmxnet3, e1000, e1000e) with MAC and bridge info.
- CloudStack `DeployVM` uses `iptonetworklist[N]` precedence rule (lines 431-445 in cloudstack provider.go):
  - If `len(NICAssignments) > 0` → use ONLY `iptonetworklist[N]` with `networkid`, `ip`, `mac` per index.
  - Else → use `networkids` + optional single `ipaddress`.
- `engine_deploy.go` builds `NICAssignments` by matching source NIC count to destination network count.

### Bugs / Gaps
- **GAP-5**: DVS (Distributed Virtual Switch) port backing: `nic.Bridge = fmt.Sprintf("dvs-%s", backing.Port.PortgroupKey)`. The CloudStack side receives a `dvs-xxxxx` bridge name that cannot map to a CloudStack network. No warning issued, and the DVS info is silently dropped.
- **GAP-6**: IP address discovery: `parseVMNICs` does NOT read the guest's assigned IP from VMware Tools. It only reads the MAC + bridge from VMX config. The actual IP address assigned to the NIC (from DHCP or static config inside the guest) is not captured. Without this, static IP migrations cannot preserve the IP.

### Fixes Proposed
1. Add guest IP detection via `vmMo.Guest.Net` — govmomi populates this when VMware Tools reports guest network info. Add to `NIC` struct: `AssignedIP string`.
2. When DVS backing detected → add validation warning: "DVS NIC detected — network topology cannot be preserved across hypervisors. Manual switchport configuration required post-migration."

---

## Category 7: Snapshot Lifecycle — Score: 9/10

### Current Implementation
- Audit landmine L2 fix: `cloneByDisk` tracker is populated BEFORE `ExportSnapshot` is called (line 1047-1057 in export.go). Any failure between tracker registration and NFC completion will still trigger cleanup.
- `mig-export-snap` named snapshot created before NFC lease.
- Pre-existing snapshots are detected and reused (BUG-11 fix).
- Quiesce fallback: if fsfreeze fails → crash-consistent retry.
- Cleanup: deletes migration snapshot (unless pre-existing) + local staging qcow2.

### Bugs / Gaps
- **BUG-10**: `snapshotReused` flag: when a pre-existing `mig-export-snap` is found and reused, the cleanup path correctly skips deletion. However, if the pre-existing snapshot was created by a previous migration run that failed mid-way, the snapshot might be in an inconsistent state. The code doesn't detect this.
- **BUG-11**: The `snapshotID` field in `cloneRecord` is always set to `1` (line 1053) regardless of the actual snapshot moref. This works because `RemoveSnapshot` by name works, but if there are multiple snapshots with the same name (unlikely but possible), the wrong one might be deleted.

### Fixes Proposed
1. Store the actual `snapRef.Value` (the moref string) in `cloneRecord.snapshotID` instead of always `1`. Use that for targeted deletion.
2. Before reusing a pre-existing snapshot, verify it has exactly one child (the current delta) by checking `RootSnapshotList` — if the snapshot tree is complex, warn the operator.

---

## Category 8: License Detection — Score: 7/10

### Current Implementation
- `IsFreeLicense()` uses `license.NewManager(c.Client).List()` to enumerate licenses. Checks edition key and name for "free", "evaluation", "hypervisor".
- `isESXiLicenseError()` pattern-matches error messages for "prohibits execution", "not supported on the object".
- Both functions exist but the preflight stage (where migrations are validated before running) does NOT call `IsFreeLicense()` for VMware sources.

### Bugs / Gaps
- **GAP-7**: `IsFreeLicense()` is never called from the preflight or audit stage. Running VMs on free ESXi will reach `ExportSnapshot` and fail there, triggering saga rollback. Preflight should call `IsFreeLicense()` and fail fast with a clear message.
- **GAP-8**: For vCenter, the license is per-ESXi-host, not per-vCenter. A vCenter might have a mix of licensed and free ESXi hosts. `IsFreeLicense()` returns the vCenter license (or the connected host's license), which could be misleading for multi-host vCenters.

### Fixes Proposed
1. Call `IsFreeLicense()` in preflight for running VMs on VMware sources. If free license + running VM → preflight fail: "Running VM migration requires licensed ESXi. Stop the VM or upgrade the license."
2. For vCenter, iterate all ESXi hosts that own VMs being migrated and check each host's license individually.

---

## Category 9: Firmware Columns — Score: 8/10

### Current Implementation
- 5 NULLABLE columns added: `firmware`, `machine_type`, `bios`, `boot_mode`, `root_disk_controller`.
- `UpdateFirmwareProjection` called from `engine_deploy.go` (line 345) with the 5 values derived from VMware config.
- `deriveMachineType` → "q35" for UEFI, "pc-i440fx" for BIOS.
- `deriveBiosLabel` → "OVMF-Secure", "EFI", or "BIOS".
- `root_disk_controller` currently always NULL — controller info is parsed but not persisted into the profile.

### Bugs / Gaps
- **BUG-12**: `root_disk_controller` is always NULL because `engine_deploy.go` does not populate it. The `detectControllerType` function exists but its result is only stored in `Disk.Format` as a suffix (e.g., `raw:pvscsi`), not extracted for the profile's `root_disk_controller` field.
- **BUG-13**: `boot_mode` column: The code derives `boot_mode` from `BIOSType` but it's not clear what values are stored ("UEFI", "BIOS", "Secure"?). The CloudStack `bootMode` API uses "BIOS", "UEFI", "UEFI+SecureBoot" — there may be a mismatch.

### Fixes Proposed
1. Extract primary boot disk controller from `VMDetail.Disks[0].Format` (which contains the controller suffix) and write to `root_disk_controller`.
2. Standardize `boot_mode` values to match CloudStack API: "BIOS", "UEFI", "Secure" (not "OVMF-Secure").

---

## Category 10: Health Check + Verify Stage — Score: 5/10

### Current Implementation
- `Healthy()` method: checks `SessionIsActive()` or falls back to `About.Version != ""`. This only proves the vSphere API is reachable — not that the VM is accessible.
- `ValidateVM()`: comprehensive validation checks (RDMs, snapshots, UEFI, secure boot, NIC types, PVSCSI, fault tolerance, encryption, USB passthrough, shared disks, NVMe, CBT, NUMA, vTPM, linked clones). But this is a **static validation** — it reads VM config from vSphere API, it does NOT probe the guest.

### Bugs / Gaps
- **GAP-9**: No guest probe. After migration, the verify stage should SSH into the destination VM (if agent is installed) or ping the workload IP to confirm it's running. The current verify only checks the CloudStack VM state via API.
- **GAP-10**: No firmware assertion. `ValidateVM` reads `Config.Firmware` but doesn't verify the deployed VM actually booted in the expected mode. A UEFI VM that deploys with BIOS boot would go undetected.
- **GAP-11**: `HealthCheckResult` is mentioned in the requirement but there's no `HealthCheckResult` struct or persistence in the codebase. The health check result after migration is not stored.

### Fixes Proposed
1. Add `VerifyDeployment(ctx, vmID)` method that: (a) calls `virsh dumpxml` on the KVM host and parses `os/type[@machine='q35']` and `osboot` elements to assert firmware mode matches the profile; (b) attempts `ping` or `nc` to the workload IP; (c) returns a `HealthCheckResult` struct persisted to DB.
2. Add `POST /api/v1/migrations/{id}/health-check` endpoint.

---

## Category 11: Frontend (karios-web) — Score: 6/10

### Current Implementation
- `karios-web` has `MigrationPanel`, `MigrationDetailDrawer`, `BatchMigrateModal`, `AddSourceModal` components.
- The `AddSourceModal` conditionally shows `esxi_ssh_password` field for VMware platform.
- No VMware-specific migration wizard or detail view that surfaces UEFI/BIOS, NIC count, snapshot state, controller type from the VMware discovery data.

### Bugs / Gaps
- **GAP-12**: No VMware-specific migration UI. The migration wizard uses a generic form that doesn't expose VMware-specific fields like: "Stop VM before migration?", "Quiesce snapshot?", "Boot mode: UEFI/BIOS".
- **GAP-13**: The `SlideInPanel` and `DeleteConfirmModal` patterns exist in `ui-patterns.json` but are not used in the migration flow. The migration wizard uses inline modals instead of the prescribed slide-in pattern.
- **GAP-14**: No VMware pre-migration checklist UI. The `ValidateVM` results are not surfaced in the frontend — operators don't see the RDM warnings, secure boot warnings, or snapshot chain warnings before starting migration.

### Fixes Proposed
1. Add `VMwareMigrationPanel` component that shows: BIOS type, Secure Boot status, NIC count+models, disk count+controllers, snapshot count, CBT status.
2. Surface `ValidateVM` results as a pre-flight checklist in the migration wizard.
3. Use `SlideInPanel` from `ui-patterns.json` for the migration detail drawer instead of the current inline drawer.

---

## Category 12: Test Coverage — Score: 4/10

### Current Implementation
- 56 backend test files in `karios-migration/`.
- 11 Playwright test files for auth and control-center.
- No VMware-specific Playwright tests.

### Bugs / Gaps
- **GAP-15**: No Playwright tests for VMware source addition, VM discovery, or migration wizard.
- **GAP-16**: No unit tests for `MapVMwareGuestID` with edge cases (unknown guest IDs, substring heuristic mismatches).
- **GAP-17**: No unit tests for `detectControllerType` with all controller variants.
- **GAP-18**: No integration tests for multi-NIC preservation (build `NICAssignments` with 3+ NICs and verify `iptonetworklist` construction).
- **GAP-19**: No tests for delta VMDK consolidation path.
- **GAP-20**: No tests for the free license + running VM preflight failure path.

### Fixes Proposed
1. Add `internal/providers/vmware/discovery_test.go` with mocks for govmomi VM objects covering all controller types, NIC types, disk backing types.
2. Add `internal/osmap/osmap_test.go` with all VMware guest ID variants.
3. Add Playwright test: `vmware-migration.spec.ts` covering source-add → VM-select → validate → start-migration flow.

---

## Summary of Fixes to Implement

### P0 (must-fix before production)
1. Wire `IsFreeLicense()` into preflight for running VMs (GAP-7).
2. Add guest IP detection via `vmMo.Guest.Net` (GAP-6 in Category 6).
3. Add `HealthCheckResult` struct + `VerifyDeployment` stub (Category 10).
4. Persist `root_disk_controller` from boot disk controller (BUG-12).
5. Standardize `boot_mode` values to CloudStack API (BUG-13).

### P1 (should-fix)
6. Fix `snapshotID` to store actual moref (BUG-11).
7. Add RDM distinction vRDM vs pRDM (BUG-8).
8. Fix delta detection to require `Backing.Parent != nil` (BUG-9).
9. Add `VMwareMigrationPanel` + preflight checklist UI (GAP-12, GAP-14).
10. Add VMware Playwright test (GAP-15).

### P2 (nice-to-have)
11. Add warning for unmapped guest IDs (BUG-1).
12. Add FreeBSD UEFI detection (BUG-2).
13. Add NVMe controller detection (GAP-1).
14. DVS backing → validation warning (GAP-5).
15. Add zone UEFI capability check (BUG-7).

---

## Files Changed in Prior Fixes (for reference)

From `vmware-vcenter-multi-host-migration-2026-04-13.md`:
- `internal/providers/vmware/provider.go` — per-host SSH pool map
- `internal/providers/vmware/discovery.go` — resolveHostIP(), GetVM metadata, glob fix
- `internal/providers/vmware/export.go` — all SSH calls use getSSHPoolForHost()
- `internal/migration/orchestrator.go` — buildRunContext uses esxi_host_ip and ESXiSSHPassword
- `pkg/provider/types.go` — VMDetail.Metadata field, SourceCredentials.ESXiSSHPassword
- `internal/source/service.go` — ESXiSSHPassword in CreateRequest and toCredentials()
- `internal/server/server.go` — esxi_ssh_password in VMware provider schema
- `karios-web/src/lib/migration/migration-types.ts` — esxi_ssh_password in CreateMigrationSourceRequest
- `karios-web/src/lib/migration/MigrationPage.tsx` — conditional ESXi SSH password UI field

---

*Generated: 2026-04-19 | architect: architect-agent | trace: trace_vmware_audit_001*
