# REQ-VMWARE-AUDIT-001 — Edge Cases
**trace_id:** trace_vmware_audit_001 | **iteration:** 1 | **agent:** architect

---

## Edge Case 1: Mixed ESXi License in vCenter (vCenter-managed hosts)

**Scenario**: vCenter has Cluster-01 with Node A (licensed ESXi) and Node B (free ESXi). VMs can vMotion between hosts. The migration picks up `runtime.host` for a VM at discovery time, but DRS could have migrated it to the free host by the time ExportLive runs.

**Risk**: Per-host SSH pool is keyed by ESXi IP, which is correct. But `IsFreeLicense()` currently checks the vCenter-level license or the connected host's license — it doesn't check the *current* host's license.

**Mitigation**: The SSH pool is created lazily on first disk operation, using the IP resolved at that moment. If DRS moved the VM between discovery and export, `GetVM()` would re-resolve `runtime.host` and the SSH pool would be created for the correct (current) host.

**Test scenario**: Start migration on VM running on licensed Node A. Manually vMotion to free Node B mid-migration. Expect: per-host SSH pool transparently switches to Node B SSH credentials.

---

## Edge Case 2: VM with 0 Disks

**Scenario**: A VM has no virtual disks (e.g., a boot-only loader, or a template placeholder).

**Risk**: `ExportDisk` / `ExportLive` called with no disks → migration proceeds to register stage with empty disk list → CloudStack template registration fails.

**Current behavior**: `ValidateVM` checks `migratableDisks == 0` → fails with "VM has no migratable disks". This blocks the migration before export.

**Gap**: What if a diskless VM is intentionally being migrated (rare but valid)? The check is a hard block. Consider: warn instead of block.

---

## Edge Case 3: VM with 10+ NICs

**Scenario**: A network-intensive VM has 8 NICs attached to different portgroups.

**Risk**: `engine_deploy.go` builds `NICAssignments` in order of discovery. If source NIC order doesn't match destination network list order, the IP-to-network mapping could be wrong.

**CloudStack limit**: CloudStack has a default limit of 8 NICs per VM (configurable per zone). A 10-NIC VM would exceed the default.

**Current behavior**: No check for NIC count against CloudStack limit. `iptonetworklist` with 10 entries would be sent to `deployVirtualMachine` — CloudStack would return error 435 (too many NICs).

**Fix needed**: Validate NIC count against zone capability before migration starts.

---

## Edge Case 4: VM with Identical MAC Addresses (Duplicate MAC)

**Scenario**: A cloned VM that wasn't properly generalized has the same MAC address as another VM on the same network.

**Risk**: After migration, the destination VM gets a new vNIC in CloudStack (new MAC), but the source VM still has the duplicate MAC. If both are on the same network, there's an ARP conflict.

**Current behavior**: No duplicate MAC detection. The migration silently preserves the duplicate MAC.

**Mitigation**: Before migration, check if the MAC is known to conflict with another VM in the source inventory.

---

## Edge Case 5: VM with Ephemeral Disk (Independent Non-Persistent)

**Scenario**: A VM has an independent non-persistent disk (e.g., a tmpfs disk for swap, or a disposable data disk).

**Risk**: This disk type is NOT migrated (correct — it's non-persistent). But the operator may not realize their data disk won't be copied.

**Current behavior**: `ValidateVM` treats independent disks like regular disks unless specifically checked. Independent non-persistent disks have `Backing.Sharing=""` but `Backing.Lazy` or independent flag not checked.

---

## Edge Case 6: VM with vGPU or Shared GPU

**Scenario**: A VM has an NVIDIA vGPU or AMD GPU passed through.

**Risk**: vGPU / GPU passthrough cannot be migrated. The VM would come up without the GPU on KVM, causing workload failure.

**Current behavior**: `ValidateVM` checks for `VirtualPCIPassthrough` and flags it as a warning ("non-migratable passthrough device"). Not a hard block.

**Gap**: The migration still proceeds even with GPU passthrough. No hard block.

---

## Edge Case 7: VM with Memory Hot-Add / CPU Hot-Add Enabled

**Scenario**: A production VM has memory hot-add enabled (`memory.hotadd = true` in VMX).

**Risk**: The hot-add configuration is in VMX / ExtraConfig. After migration to KVM, hot-add may or may not work depending on the libvirt configuration. CloudStack doesn't carry over this setting.

**Current behavior**: No detection. The hot-add setting is silently dropped.

---

## Edge Case 8: Storage DRS (SDRS) Datastore

**Scenario**: VM is on a Storage DRS cluster. The VMDK could be on any datastore in the cluster, and SDRS can migrate it dynamically.

**Risk**: The VMDK path discovered at the start of migration could change mid-transfer if SDRS migrates the disk to a different datastore.

**Current behavior**: Datastore is determined at `GetVM()` time. If SDRS moves the disk during export, the file would disappear and NFC download would fail.

**Mitigation**: Use the VMDK path from the NFC lease itself (which reflects the actual location at snapshot time), not the pre-computed `DevicePath`. The NFC path in `diskItem.Path` is already resolved to the actual location.

---

## Edge Case 9: Thick-Provisioned Lazy-Zeroed vs. Eager-Zeroed

**Scenario**: A thick-provisioned eager-zeroed disk (`provisioningType = "eagerZeroedThick"`) vs lazy-zeroed (`"lazy"`).

**Risk**: Both are migrated as raw VMDK → qcow2. Eager-zeroed is fully written at creation time (all zeros written), so qcow2 compression on the staging host would produce a highly compressible file (90%+ compression). This is fine but may be misleading — operators see a 500GB disk compressed to 10MB and think something is wrong.

**Current behavior**: No distinction. The compression is shown in the SSE logs but no explanation is given.

---

## Edge Case 10: VM with Snapshots and CBT Enabled

**Scenario**: A VM has 3 snapshots in a chain AND CBT is enabled. The CBT change tracking file (`vm-ctk.vmdk`) is in the snapshot chain.

**Risk**: When `RemoveAllSnapshot` is called, the CBT file is deleted as part of the consolidation. After migration, CBT is no longer enabled on the destination. The operator's backup software relying on CBT would be broken.

**Current behavior**: No warning about CBT state change after migration. The validation check mentions CBT is informational.

---

## Edge Case 11: VM with Windows in Safe Mode

**Scenario**: A Windows VM that was booted into Safe Mode (or was improperly shut down).

**Risk**: The NTFS dirty bit is set. When `guestfish` tries to mount the disk RW for VirtIO injection, `ntfs-3g` refuses RW mount because of the dirty bit. The `ntfsfix` command is included in the guestfish script but `ntfsfix` doesn't always clear the dirty bit reliably for journals in inconsistent states.

**Current behavior**: `buildGuestfishScript` includes `-ntfsfix` before each mount attempt. If `ntfsfix` doesn't clear the bit, the mount fails and VirtIO injection silently does nothing (the `-` prefix makes guestfish ignore errors on individual commands).

**Gap**: If VirtIO injection silently fails (no .sys files copied), the Windows VM will BSOD on first KVM boot. The migration proceeds without error.

---

## Edge Case 12: ESXi Host with Management IP as FQDN (Not Resolvable)

**Scenario**: ESXi host was added to vCenter with FQDN `esxi-a.karios.ai` instead of IP `192.168.115.232`. The management network DNS is not reachable from the Karios bridgehead.

**Risk**: `HostSystem.name` returns `esxi-a.karios.ai`. SSH connection to that hostname would fail. The code falls back to `p.creds.Host` (the connection IP), but only if `isIPAddress()` returns false for the resolved name.

**Current behavior**: `ExportDisk` checks `isIPAddress(esxiHostIP)` and falls back to `p.creds.Host` if the resolved name is not an IP. This is correct.

---

## Edge Case 13: Concurrent Migration of Same VM (Duplicate Migration)

**Scenario**: Operator accidentally triggers the same migration twice (e.g., double-clicked the migrate button).

**Risk**: Two concurrent migration sagas for the same VM → two concurrent disk exports → two concurrent CloudStack template registrations → race condition on destination.

**Current behavior**: No idempotency guard. `ExportDisk` doesn't check if a migration for this VM is already in progress.

**Fix needed**: Add a `migration_lock` table row with `vm_id` as a unique key. `AcquireMigrationLock(vmID)` before starting. `ReleaseMigrationLock(vmID)` on completion or failure.

---

## Edge Case 14: Migration Timeout Mid-Transfer

**Scenario**: 500GB disk transfer takes 2 hours and exceeds the saga timeout.

**Risk**: The saga times out and triggers rollback. The partial qcow2 file on the staging host is left behind. The source snapshot is left on the ESXi host.

**Current behavior**: `CleanupExport` is called during rollback, which should delete the snapshot and local files. But if the timeout happens during NFC download, the cleanup path may not have been registered yet (depends on where the timeout fires).

**Fix needed**: Ensure `cloneByDisk` entry is registered before NFC download starts. Timeout during NFC should still trigger cleanup.

---

## Edge Case 15: VM with vSphere Encryption (VM Encryption)

**Scenario**: An encrypted VM (`config.KeyId != nil`) is being migrated.

**Risk**: Encrypted VMs require the encryption key to be accessible during export. The NFC export of an encrypted VM without the key would fail.

**Current behavior**: `ValidateVM` flags encryption as a warning: "VM is encrypted — must decrypt before disk export". Not a hard block.

**Gap**: The migration could be started on an encrypted VM, reach export, and fail there.

---

## Edge Case 16: BSD EFI Boot with UEFI Shell

**Scenario**: `bsd-efi-bootonly-loader` (freebsd14_64Guest, UEFI firmware) — a FreeBSD VM booting via EFI.

**Risk**: FreeBSD UEFI boot requires OVMF with proper GOP (Graphics Output Protocol) support. Not all OVMF builds include GOP, and FreeBSD is sensitive to this.

**Current behavior**: FreeBSD UEFI is mapped to "FreeBSD (64-bit)" OS type. The deploy uses UEFI boot mode. But no validation that the OVMF build on the KVM host supports FreeBSD GOP.

---

## Edge Case 17: VM with Memory Reservation (Resource Pool)

**Scenario**: A VM has a memory reservation set (e.g., guaranteed minimum RAM).

**Risk**: Memory reservations are VMware-specific and don't map to KVM / CloudStack service offerings. The VM would deploy without the reservation.

**Current behavior**: No detection of memory reservations.

---

## Edge Case 18: VM Running on vSAN Datastore

**Scenario**: ESXi host is licensed but the VM's disks are on vSAN storage.

**Risk**: vSAN is accessed differently than VMFS/NFS. `vmkfstools` commands don't work the same way. The NFC path should still work since NFC doesn't care about storage type.

**Current behavior**: No special handling for vSAN. NFC is the primary path so vSAN should work. But `resolveDiskSizeViaSSH` would fail because vSAN has a different filesystem structure (`/vmfs/volumes/vsan:...`).

---

## Edge Case 19: VM with Paravirtual SCSI (PVSCSI) and > 16 Scsi Disks

**Scenario**: A database VM has 18 virtual disks all attached to a single PVSCSI controller.

**Risk**: PVSCSI supports up to 16 disks per controller. More than 16 requires multiple controllers. CloudStack's VirtIO SCSI doesn't have this limit but the PVSCSI → VirtIO SCSI mapping needs care.

**Current behavior**: Each disk is flagged with its controller type. No check for per-controller disk count.

---

## Edge Case 20: CloudStack Zone with No Suitable Network

**Scenario**: A 3-NIC VM is being migrated to a CloudStack zone that only has 1 network defined.

**Risk**: `DeployVM` would fail with "more NICs than available networks" error.

**Current behavior**: No pre-check that the destination zone has enough networks for the VM's NIC count.

---

*Generated: 2026-04-19 | architect: architect-agent | trace: trace_vmware_audit_001*
