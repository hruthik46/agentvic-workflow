# REQ-VMWARE-AUDIT-001 — API Contract Changes
**trace_id:** trace_vmware_audit_001 | **iteration:** 1 | **agent:** architect

---

## Current API Endpoints (Relevant to VMware)

### Source Management

#### POST /api/v1/migration/sources
Register a new migration source (ESXi or vCenter).

**Request body**:
```json
{
  "name": "vmware-esxi-232",
  "platform": "vmware",
  "host": "192.168.115.232",
  "port": 443,
  "username": "root",
  "password": "karios@12345",
  "esxi_ssh_password": "karios@12345",
  "verify_tls": false
}
```

**Response** (201 Created):
```json
{
  "data": {
    "id": "src-xxxx",
    "name": "vmware-esxi-232",
    "platform": "vmware",
    "status": "connected",
    "metadata": {
      "platform_version": "8.0.3 build-24677879",
      "is_vcenter": false,
      "esxi_host_ip": "192.168.115.232"
    }
  }
}
```

**Changes needed**: None. Already includes `esxi_ssh_password`.

---

#### GET /api/v1/migration/sources/{sourceId}
Get source connection status and basic info.

**Response**:
```json
{
  "data": {
    "id": "src-xxxx",
    "platform": "vmware",
    "status": "connected",
    "metadata": {
      "platform_version": "8.0.3 build-24677879",
      "is_vcenter": false,
      "is_free_license": true,
      "esxi_host_ip": "192.168.115.232"
    }
  }
}
```

**Changes needed**: Add `is_free_license` to metadata (new — surfaced from `IsFreeLicense()`).

---

#### GET /api/v1/migration/sources/{sourceId}/nodes
List ESXi hosts in a vCenter or standalone ESXi.

**Response**:
```json
{
  "data": [
    {
      "id": "host-40",
      "name": "192.168.115.232",
      "status": "online",
      "cpu_cores": 16,
      "memory_mb": 99893,
      "metadata": {
        "vendor": "Intel Corporation",
        "model": "NUC12WSHi7",
        "version": "8.0.3",
        "build": "24677879",
        "management_ip": "192.168.115.232"
      }
    }
  ]
}
```

**Changes needed**: None. Already uses `HostSystem.name` correctly.

---

#### GET /api/v1/migration/sources/{sourceId}/vms
List all VMs on a source.

**Response** (abbreviated):
```json
{
  "data": [
    {
      "id": "vm-47",
      "name": "karios-test",
      "state": "running",
      "node_id": "host-40",
      "cpu_cores": 4,
      "memory_mb": 8192,
      "disks": [
        {"id": "disk-2000", "index": 0, "size_bytes": 68719476736}
      ],
      "pci_devices": ["vTPM"]
    }
  ]
}
```

**Changes needed**: None.

---

#### GET /api/v1/migration/sources/{sourceId}/vms/{vmId}
Get detailed VM information including firmware, NICs, snapshots.

**Response**:
```json
{
  "data": {
    "id": "vm-47",
    "name": "karios-test",
    "state": "running",
    "node_id": "host-40",
    "cpu_cores": 4,
    "memory_mb": 8192,
    "bios_type": "uefi",
    "secure_boot": false,
    "os_type": "debian12_64Guest",
    "firmware": "efi",
    "machine_type": "q35",
    "bios": "EFI",
    "boot_mode": "UEFI",
    "root_disk_controller": "pvscsi",
    "disks": [
      {
        "id": "disk-2000",
        "index": 0,
        "size_bytes": 68719476736,
        "device_path": "[datastore1] karios-test/karios-test.vmdk",
        "storage_name": "datastore1",
        "storage_type": "vmfs",
        "format": "raw:pvscsi",
        "is_boot": true
      }
    ],
    "nics": [
      {
        "id": "nic-4000",
        "model": "vmxnet3",
        "mac": "00:0c:29:ab:cd:ef",
        "bridge": "VM Network",
        "assigned_ip": "192.168.1.100"
      }
    ],
    "snapshots": ["snap-1", "snap-2"],
    "has_agent": true,
    "metadata": {
      "esxi_host_ip": "192.168.115.232"
    }
  }
}
```

**Changes needed**:
1. Add `assigned_ip` to NICs (new — from `vmMo.Guest.Net` via VMware Tools).
2. Add `root_disk_controller` to response (new — from boot disk controller detection).
3. Add `boot_mode` (new — was missing from projection).
4. Change `bios` from "OVMF-Secure" to "Secure" for secure boot VMs.

---

#### GET /api/v1/migration/sources/{sourceId}/vms/{vmId}/networks
Get network interfaces for a VM.

**Response**:
```json
{
  "data": [
    {
      "id": "nic-4000",
      "model": "vmxnet3",
      "mac": "00:0c:29:ab:cd:ef",
      "bridge": "VM Network",
      "network_type": "standard"
    },
    {
      "id": "nic-4001",
      "model": "vmxnet3",
      "mac": "00:0c:29:ab:cd:f0",
      "bridge": "dvs-dvportgroup-12345",
      "network_type": "distributed"
    }
  ]
}
```

**Changes needed**: Add `network_type` ("standard" vs "distributed") — already derivable from backing type.

---

#### POST /api/v1/migration/sources/{sourceId}/vms/{vmId}/validate
Run pre-migration validation.

**Response**:
```json
{
  "data": {
    "valid": false,
    "checks": [
      {"name": "has_disks", "status": "pass", "message": "VM has 1 migratable disk(s)", "severity": "info"},
      {"name": "uefi_firmware", "status": "warn", "message": "VM uses UEFI — CloudStack template will need UEFI boot type configured", "severity": "warn"},
      {"name": "vmxnet3_mutation", "status": "warn", "message": "VM has VMXNET3 NIC — VirtIO network driver injection will be needed", "severity": "warn"},
      {"name": "pvscsi_mutation", "status": "warn", "message": "VM has PVSCSI controller — VirtIO SCSI driver injection will be needed", "severity": "warn"},
      {"name": "cbt_enabled", "status": "pass", "message": "VM has Changed Block Tracking (CBT) enabled — karios uses full copy; CBT history is not preserved", "severity": "info"}
    ]
  }
}
```

**Changes needed**: 
1. Add `is_free_license_running_vm` check: if free license + running VM → hard fail with message "Running VM migration requires licensed ESXi. Stop the VM or upgrade the license."
2. Add `zone_uefi_capability` check: if VM is UEFI but zone doesn't support UEFI → hard fail.

---

## Migration API

### POST /api/v1/migrations
Create and start a migration.

**Request body** (VMware source):
```json
{
  "source_id": "src-xxxx",
  "vm_id": "vm-47",
  "dest_zone_id": "zone-xxxx",
  "dest_network_id": "network-xxxx",
  "dest_offering_id": "offering-xxxx",
  "firmware": "efi",
  "machine_type": "q35",
  "bios": "EFI",
  "boot_mode": "UEFI",
  "root_disk_controller": "pvscsi",
  "stop_source_vm": true
}
```

**Changes needed**:
1. Add `stop_source_vm` field (new — operator choice for cold vs warm migration).
2. Add `nic_assignments` for multi-NIC preservation:
```json
{
  "nic_assignments": [
    {"index": 0, "network_id": "network-yyyy", "ip": "192.168.1.100", "mac": "00:0c:29:ab:cd:ef"},
    {"index": 1, "network_id": "network-zzzz", "ip": "10.0.0.50", "mac": "00:0c:29:ab:cd:f0"}
  ]
}
```

---

### GET /api/v1/migrations/{migrationId}
Get migration status.

**Response** (abbreviated):
```json
{
  "data": {
    "id": "mig-xxxx",
    "source_id": "src-xxxx",
    "vm_id": "vm-47",
    "state": "transferring",
    "stage": "disk_transfer",
    "firmware": "efi",
    "machine_type": "q35",
    "bios": "EFI",
    "boot_mode": "UEFI",
    "root_disk_controller": "pvscsi",
    "progress": {
      "disk_transfers": [
        {"disk_id": "disk-2000", "transferred_bytes": 34359738368, "total_bytes": 68719476736, "rate_bps": 131072000, "pct": 50.0}
      ]
    },
    "error": null
  }
}
```

**Changes needed**:
1. Add `root_disk_controller` to response (new — persisted firmware column).
2. Add `stop_source_vm` to response.

---

### POST /api/v1/migrations/{migrationId}/health-check
**NEW endpoint** — verify deployed VM health.

**Request**:
```json
{
  "checks": ["firmware_assertion", "ping_workload", "disk_access"]
}
```

**Response**:
```json
{
  "data": {
    "migration_id": "mig-xxxx",
    "results": [
      {"check": "firmware_assertion", "status": "pass", "message": "VM booted in UEFI mode (libvirt os/type machine=q35)"},
      {"check": "ping_workload", "status": "pass", "message": "ICMP reached 192.168.1.100"},
      {"check": "disk_access", "status": "fail", "message": "Disk I/O test failed — VirtIO driver may not be loaded"}
    ],
    "overall": "degraded"
  }
}
```

**Implementation note**: `firmware_assertion` runs `virsh dumpxml` on the KVM host and parses `<os type="hvm" machine="q35">`. `ping_workload` pings the workload IP from the KVM host. `disk_access` runs `dd if=/dev/urandom of=test bs=1M count=10` on the VM via SSH.

---

## Schema Changes Required

### New field: SourceCredentials.IsFreeLicense (read-only, from IsFreeLicense())
```go
// SourceCredentials — add after ESXiSSHPassword
IsFreeLicense bool `json:"is_free_license,omitempty"`
```

### New field: VMDetail.NICs[].AssignedIP
```go
type NIC struct {
    ID           string `json:"id"`
    Model        string `json:"model"`
    MAC          string `json:"mac"`
    Bridge       string `json:"bridge"`
    NetworkType  string `json:"network_type,omitempty"`  // "standard" or "distributed"
    AssignedIP   string `json:"assigned_ip,omitempty"`     // from vmMo.Guest.Net
}
```

### New field: MigrationProfile.RootDiskController
```go
type MigrationProfile struct {
    // ... existing fields ...
    RootDiskController string `json:"root_disk_controller,omitempty"` // pvscsi, lsi_sas, nvme, ide
}
```

### New field: ValidationCheck for free license
```json
{
  "name": "free_license_running_vm",
  "status": "fail",
  "message": "Running VM migration requires licensed ESXi. Stop the VM or upgrade the license.",
  "severity": "block",
  "auto_fix": false
}
```

---

## Breaking Changes

1. **`bios` field value change**: For secure boot VMs, `bios` changes from `"OVMF-Secure"` to `"Secure"`. API consumers that do string matching on "OVMF-Secure" will break. **Announce as API change in release notes**.

---

## Non-Breaking Additions

- `is_free_license` in source metadata (new field, absent for old records)
- `assigned_ip` in NICs (new field, absent for old records)
- `root_disk_controller` in VM detail and migration profile (new field, absent for old records)
- `POST /api/v1/migrations/{id}/health-check` (new endpoint)

---

*Generated: 2026-04-19 | architect: architect-agent | trace: trace_vmware_audit_001*
