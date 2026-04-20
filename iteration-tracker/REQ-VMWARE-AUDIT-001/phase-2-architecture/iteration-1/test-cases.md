# REQ-VMWARE-AUDIT-001 — Test Cases
**trace_id:** trace_vmware_audit_001 | **iteration:** 1 | **agent:** architect

---

## Category 1: OS Detection + Mutation

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-1-1 | MapVMwareGuestID: exact match Ubuntu | `ubuntu64Guest` | "Ubuntu 22.04 LTS (64-bit)" | P1 |
| TC-1-2 | MapVMwareGuestID: exact match Debian 12 | `debian12_64Guest` | "Debian GNU/Linux 12 (64-bit)" | P1 |
| TC-1-3 | MapVMwareGuestID: exact match Windows 2022 | `windows2019srvNext_64Guest` | "Windows Server 2022 (64-bit)" | P1 |
| TC-1-4 | MapVMwareGuestID: unknown guest ID | `crx76kGuest` | "Other (64-bit)" + WARN log | P1 |
| TC-1-5 | MapVMwareGuestID: windows2025 (future) | `windows2025srv_64Guest` | "Windows Server 2022 (64-bit)" | P2 |
| TC-1-6 | isWindowsVM: Windows 10 | `windows9_64Guest` | true | P1 |
| TC-1-7 | isWindowsVM: Debian | `debian12_64Guest` | false | P1 |
| TC-1-8 | detectControllerType: PVSCSI | VM with pvscsi controller | "pvscsi" | P1 |
| TC-1-9 | detectControllerType: NVMe | VM with VirtualNVMEController | "nvme" (new) | P2 |
| TC-1-10 | Morph: Linux VM skips injection | debian12_64Guest | runMorph returns nil immediately | P1 |

---

## Category 2: Disk Transfer Paths

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-2-1 | ExportDisk: stopped VM flat VMDK | powered-off VM with flat disk | Protocol="vmware_nfc_direct", ExportPath starts with "https://esxi/folder/" | P0 |
| TC-2-2 | ExportDisk: delta VMDK triggers consolidation | VM with snapshot delta chain | consolidateSnapshots called, then fresh disk path resolved | P0 |
| TC-2-3 | ExportDisk: 0-byte flat VMDK | VM with snapshot whose base is 0 bytes | Error: "flat VMDK is 0 bytes" | P0 |
| TC-2-4 | ExportDisk: RDM disk | VM with Physical RDM | Error: "disk is an RDM" | P0 |
| TC-2-5 | ExportDisk: SeSparse disk | VM with sesparse backing | Error: "disk has snapshot chain (SeSparse)" | P0 |
| TC-2-6 | ExportDisk: unknown backing type | VM with unhandled backing | Warning logged, disk skipped | P2 |
| TC-2-7 | discoverFlatVMDK: monolithic VMDK | IDE VM with monolithic VMDK | Returns actual data file path | P1 |
| TC-2-8 | discoverFlatVMDK: descriptor parse | Thin VM with descriptor | Parses descriptor extent line → data file | P1 |
| TC-2-9 | ExportLive: running VM via NFC | powered-on VM | NFC lease obtained, raw streamed, qcow2 created | P0 |
| TC-2-10 | ExportLive: free license + running VM | VM on free ESXi | Error: "MIG_EXPORT_LICENSE: ESXi free license prohibits snapshot creation" | P0 |

---

## Category 3: CBT (Changed Block Tracking)

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-3-1 | ValidateVM: CBT enabled on licensed ESXi | VM with ctkEnabled=true | ValidationCheck: cbt_enabled=pass, message about full copy | P1 |
| TC-3-2 | ValidateVM: CBT disabled | VM with CBT off | No CBT validation check emitted | P1 |
| TC-3-3 | IncrementalExporter: called on licensed host | Licensed ESXi VM with CBT | Returns nil, false (not yet implemented) | P1 |

---

## Category 4: UEFI / Secure Boot

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-4-1 | GetVM: UEFI + SecureBoot=true | VM with firmware="efi", EfiSecureBootEnabled=true | BIOSType=UEFI, SecureBoot=true, Firmware="efi", Bios="Secure", MachineType="q35" | P0 |
| TC-4-2 | GetVM: UEFI + SecureBoot=false | VM with firmware="efi", no secure boot | BIOSType=UEFI, SecureBoot=false, Bios="EFI", MachineType="q35" | P0 |
| TC-4-3 | GetVM: Legacy BIOS | VM with firmware="bios" | BIOSType=Legacy, Bios="BIOS", MachineType="pc-i440fx" | P0 |
| TC-4-4 | ValidateVM: Secure Boot warning | VM with EfiSecureBootEnabled=true | ValidationCheck: secure_boot=warn | P0 |
| TC-4-5 | deriveBiosLabel: efi+secure | "efi", true | "Secure" (not "OVMF-Secure") | P1 |
| TC-4-6 | deriveMachineType: efi | "efi" | "q35" | P1 |

---

## Category 5: VMDK Paths

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-5-1 | resolveVMFSPath: standard format | `[datastore1] vm/disk.vmdk` | "/vmfs/volumes/datastore1/vm/disk.vmdk" | P0 |
| TC-5-2 | resolveVMFSPath: flat file | `[datastore1] vm/disk-flat.vmdk` | "/vmfs/volumes/datastore1/vm/disk-flat.vmdk" | P0 |
| TC-5-3 | resolveVMFSPath: delta 6-digit | `[datastore1] vm/vm-000003.vmdk` | detected as snapshot delta | P0 |
| TC-5-4 | resolveVMFSPath: delta 3-digit | `[datastore1] vm/vm-001.vmdk` | detected as snapshot delta | P1 |
| TC-5-5 | resolveDiskSizeViaSSH: delta glob | delta path ending in `/*-flat.vmdk` | size resolved via glob-safe ls | P0 |
| TC-5-6 | verifyFileExists: file present | valid VMFS path | nil error | P1 |
| TC-5-7 | verifyFileExists: file missing | invalid VMFS path | error returned | P1 |
| TC-5-8 | discoverFlatVMDK: all strategies | monolithic VMDK | Strategy 0 (descriptor) finds data file | P1 |

---

## Category 6: Multi-NIC / IP+MAC Preservation

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-6-1 | parseVMNICs: single vmxnet3 | VM with 1 vmxnet3 | 1 NIC, model="vmxnet3", MAC populated | P0 |
| TC-6-2 | parseVMNICs: multi-NIC mixed types | VM with 3 NICs (vmxnet3, e1000, e1000e) | 3 NICs with correct models and MACs | P0 |
| TC-6-3 | parseVMNICs: DVS backing | VM on distributed switch | nic.Bridge="dvs-{portgroupKey}" | P1 |
| TC-6-4 | CloudStack Deploy: NICAssignments present | 2 NICs with assignments | Params use iptonetworklist[0].networkid + iptonetworklist[0].ip + iptonetworklist[0].mac | P0 |
| TC-6-5 | CloudStack Deploy: no NICAssignments | single NIC, no assignments | Params use networkids + ipaddress | P0 |
| TC-6-6 | CloudStack Deploy: multi-NIC deduplication | 3 NICs mapping to 2 networks | networkids deduped, extra nic via AddNIC | P1 |
| TC-6-7 | NICAssignment: guest IP preservation | NIC with guest-assigned IP | AssignedIP field populated from vmMo.Guest.Net | P2 |

---

## Category 7: Snapshot Lifecycle

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-7-1 | ExportLive: creates mig-export-snap | running VM | snapshot named "mig-export-snap" created | P0 |
| TC-7-2 | ExportLive: pre-existing snap reused | VM with existing mig-export-snap | snapshotReused=true, no CreateSnapshot call | P0 |
| TC-7-3 | ExportLive: quiesce fallback | VM without VMware Tools | crash-consistent snapshot created after quiesce fail | P0 |
| TC-7-4 | ExportLive: tracker registered before NFC | running VM | cloneByDisk populated before ExportSnapshot call | P0 |
| TC-7-5 | CleanupExport: created snapshot deleted | non-reused snapshot | vim-cmd snapshot.remove called | P0 |
| TC-7-6 | CleanupExport: reused snapshot NOT deleted | pre-existing snapshot | snapshot.remove NOT called | P0 |
| TC-7-7 | CleanupExport: nfcStagingPath cleaned | NFC export path | local qcow2 file deleted | P1 |
| TC-7-8 | consolidateSnapshots: no snapshots | VM with 0 snapshots | RemoveAllSnapshot is no-op | P1 |
| TC-7-9 | consolidateSnapshots: with delta chain | VM with snapshot chain | RemoveAllSnapshot called, waits 30min timeout | P0 |
| TC-7-10 | consolidateSnapshots: free license fails | free ESXi VM | isESXiLicenseError returns true, warning logged | P0 |

---

## Category 8: License Detection

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-8-1 | IsFreeLicense: free edition | ESXi with "VMware vSphere Hypervisor" | (true, nil) | P0 |
| TC-8-2 | IsFreeLicense: evaluation | ESXi with "evaluation" | (true, nil) | P0 |
| TC-8-3 | IsFreeLicense: licensed | ESXi with vSphere Standard license | (false, nil) | P0 |
| TC-8-4 | IsFreeLicense: license API denied | network error on licenseManager.List | (false, nil) — conservative | P1 |
| TC-8-5 | isESXiLicenseError: prohibits operation | error containing "prohibits execution" | true | P0 |
| TC-8-6 | isESXiLicenseError: not supported object | error containing "not supported on the object" | true | P0 |
| TC-8-7 | Preflight: free license + running VM | free ESXi + powered-on VM | Preflight fails: "Running VM migration requires licensed ESXi" | P0 |
| TC-8-8 | Preflight: free license + stopped VM | free ESXi + powered-off VM | Preflight passes (cold migration allowed) | P0 |

---

## Category 9: Firmware Columns

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-9-1 | UpdateFirmwareProjection: UEFI VM | VM with firmware="efi" | firmware='efi', machine_type='q35', bios='EFI', boot_mode='UEFI' | P0 |
| TC-9-2 | UpdateFirmwareProjection: Secure Boot | VM with EfiSecureBootEnabled=true | bios='Secure', boot_mode='Secure' | P1 |
| TC-9-3 | UpdateFirmwareProjection: root_disk_controller | VM with pvscsi boot disk | root_disk_controller='pvscsi' | P1 |
| TC-9-4 | UpdateFirmwareProjection: failure non-fatal | DB write fails | Warning logged, migration continues | P1 |

---

## Category 10: Health Check + Verify Stage

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-10-1 | Healthy: connected | vSphere reachable | (true, nil) | P0 |
| TC-10-2 | Healthy: session expired | session evicted | Reconnect triggered, (true, nil) | P0 |
| TC-10-3 | Healthy: not implemented (free ESXi) | SessionIsActive returns "not implemented" | (true, nil) if Version != "" | P0 |
| TC-10-4 | ValidateVM: all passing checks | Valid VM | Valid=true, no fail checks | P0 |
| TC-10-5 | ValidateVM: RDM present | VM with pRDM | Valid=false, rdM_disk=fail | P0 |
| TC-10-6 | ValidateVM: USB passthrough | VM with USB passthrough | Valid=false, usb_passthrough=fail | P0 |
| TC-10-7 | ValidateVM: shared disk | VM with multi-writer disk | Valid=false, shared_disk=fail | P0 |
| TC-10-8 | ValidateVM: FT secondary | Fault Tolerance secondary | Valid=false, fault_tolerance=fail | P0 |
| TC-10-9 | VerifyDeployment: virsh dumpxml check | deployed KVM VM | Firmware mode matches profile | P2 |
| TC-10-10 | VerifyDeployment: ping workload | migrated VM | ICMP reaches workload IP | P2 |

---

## Category 11: Frontend (karios-web)

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-11-1 | AddSourceModal: VMware platform | platform=vmware | ESXi SSH password field shown | P0 |
| TC-11-2 | AddSourceModal: non-VMware | platform=cloudstack | No ESXi SSH password field | P0 |
| TC-11-3 | MigrationWizard: VMware VM selected | VM with UEFI, 2 NICs, pvscsi | Panel shows: BIOS=UEFI, NICs=2 (vmxnet3), Controller=pvscsi | P1 |
| TC-11-4 | MigrationWizard: preflight checklist | VMware VM with RDM | Checklist shows RDM as blocking item | P1 |
| TC-11-5 | SlideInPanel: used for migration detail | open migration detail | Slide-in drawer pattern used (not inline) | P2 |

---

## Category 12: Test Coverage

| ID | Test Case | Input | Expected Output | Priority |
|----|-----------|-------|-----------------|----------|
| TC-12-1 | discovery_test: all controller types | mock VM with pvscsi, lsi_sas, ahci, ide | detectControllerType returns correct type per disk | P1 |
| TC-12-2 | discovery_test: all NIC types | mock VM with vmxnet3, e1000, e1000e | parseVMNICs returns 3 NICs with correct models | P1 |
| TC-12-3 | osmap_test: all guest IDs | all 50+ VMware guest IDs | MapVMwareGuestID returns non-empty string for all | P1 |
| TC-12-4 | export_test: delta consolidation | mock delta VMDK path | consolidateSnapshots called with correct timeout | P1 |
| TC-12-5 | export_test: NFC lease abort | NFC lease times out | nfcLease.Abort called, cleanup registered | P1 |
| TC-12-6 | vmware_ssh_test: glob-safe ls | delta path with glob | ls command has unquoted glob | P1 |
| TC-12-7 | playwright: add VMware source | fill VMware source form | Source added, status=connected | P2 |
| TC-12-8 | playwright: VM discovery | select VMware source | VM list populated with correct BIOS/OS | P2 |
| TC-12-9 | playwright: start migration | click start migration on VMware VM | Migration starts, SSE events received | P2 |
| TC-12-10 | morph_test: guestfish injection | Windows VM, guestfish available | guestfish script contains virtio driver copy | P1 |

---

## Test Execution Order

### Phase A: Unit Tests (run locally)
```
go test ./internal/osmap/... -v
go test ./internal/providers/vmware/... -v  
go test ./internal/migration/... -run Morph -v
```

### Phase B: Integration Tests (requires real ESXi .232)
```
go test ./internal/providers/vmware/... -tags=integration -v
```

### Phase C: E2E Playwright (requires full stack on .106)
```
cd /root/karios-source-code/karios-playwright
npx playwright test --project=vmware
```

---

*Generated: 2026-04-19 | architect: architect-agent | trace: trace_vmware_audit_001*
