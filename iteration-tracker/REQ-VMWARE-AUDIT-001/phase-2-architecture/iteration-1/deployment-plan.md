# REQ-VMWARE-AUDIT-001 — Deployment Plan
**trace_id:** trace_vmware_audit_001 | **iteration:** 1 | **agent:** architect

---

## Overview

This deployment plan covers the fixes required to bring the VMware provider to production-ready status based on the Phase 2 architecture audit.

**Priority**: P0 fixes must be deployed before any production VMware migration. P1 fixes should be deployed in the same release if possible. P2 fixes can follow in the next release.

---

## Phase 0: Pre-Deployment Verification (Do First)

Before any code changes:

```bash
# 1. Verify ESXi connectivity
ssh root@192.168.115.232 "vim-cmd vmsvc/getallvms" 2>/dev/null | head -5
# Expected: list of VMs

# 2. Verify vCenter connectivity
govc about -host 192.168.115.233 -u administrator@vsphere.local -p '***' 2>/dev/null | head -5
# Expected: vCenter version info

# 3. Verify CloudStack API
curl -s http://192.168.118.106:8080/client/api?command=listZones 2>/dev/null | head -3
# Expected: XML/JSON zone response

# 4. Check karios-migration builds
cd /root/karios-source-code/karios-migration && go build ./...
# Expected: no errors
```

---

## Phase 1: P0 Fixes (Must-Do)

### P0-1: Wire IsFreeLicense() into Preflight

**File**: `internal/migration/orchestrator.go` (or wherever preflight is called)

**Change**: Before starting a migration for a running VM on VMware, call `provider.IsFreeLicense(ctx)`. If `true` and the VM is running, fail preflight with clear message.

**Risk**: Low. Only adds a new preflight check, doesn't change existing behavior.

**Test**:
```bash
# Start migration on running VM on free ESXi .232
# Expected: preflight fails with "Running VM migration requires licensed ESXi"
```

**Rollback**: Remove the preflight check call. No data migration needed.

---

### P0-2: Add AssignedIP to NICs (Guest IP Detection)

**File**: `internal/providers/vmware/discovery.go`

**Change**: In `GetVM()`, add a `vmMo.Guest.Net` lookup to populate the `AssignedIP` field for each NIC. This requires an additional property collector call to fetch the `guest` property from the VM.

```go
// Add to GetVM properties list:
"guest",

// In parseVMNICs or as a separate step:
if vmMo.Guest != nil {
    for _, net := range vmMo.Guest.Net {
        // net.IPAddress, net.MACAddress
        // Match to NIC by MAC address
    }
}
```

**Risk**: Low. Adds information only. VMware Tools must be running for this to populate.

**Test**: Run against `karios-test` (running VM with VMware Tools) → `assigned_ip` field populated.

---

### P0-3: Persist root_disk_controller to MigrationProfile

**File**: `internal/migration/engine_deploy.go`

**Change**: Extract the controller from `VMDetail.Disks[0].Format` (which contains e.g., `raw:pvscsi`) and write to `root_disk_controller` field.

```go
// After detecting boot disk controller from disk.Format
if len(rc.VMDetail.Disks) > 0 && strings.Contains(rc.VMDetail.Disks[0].Format, ":") {
    parts := strings.Split(rc.VMDetail.Disks[0].Format, ":")
    if len(parts) == 2 {
        rootDiskController = parts[1]
    }
}
```

**Risk**: Low. Only changes what's written to DB.

---

### P0-4: Standardize boot_mode Values

**Files**:
- `internal/providers/vmware/discovery.go` — `deriveBiosLabel`
- `internal/migration/engine_deploy.go` — `UpdateFirmwareProjection` call

**Change**: `deriveBiosLabel` should return "Secure" instead of "OVMF-Secure". The CloudStack `bootMode` API uses "BIOS", "UEFI", "Secure" — not "OVMF-Secure".

**Risk**: Medium. Changes the value stored in DB for secure boot VMs. Must be coordinated with frontend display logic.

**Migration**: Existing DB rows with "OVMF-Secure" should be treated as equivalent to "Secure" in the UI.

---

## Phase 2: P1 Fixes

### P1-1: Fix snapshotID to Store Actual MOREF

**File**: `internal/providers/vmware/export.go`

**Change**: In `liveExporter.ExportLive()`, after `vmObj.FindSnapshot(ctx, "mig-export-snap")` returns `snapRef`, store `snapRef.Value` in `cloneRecord.snapshotID` instead of hardcoding `1`.

**Risk**: Low. Only changes which snapshot is deleted during cleanup.

---

### P1-2: Add RDM vRDM vs pRDM Distinction

**File**: `internal/providers/vmware/discovery.go`

**Change**: In `parseVMDisks()`, when `VirtualDiskRawDiskMappingVer1BackingInfo` is detected, check `Backing.Kind` to distinguish virtual RDM (`com.vmware.vmdk.VirtualRDMPersistent`) from physical RDM (`com.vmware.vmdk.RawPhysical`).

```go
case *types.VirtualDiskRawDiskMappingVer1BackingInfo:
    d.StorageType = provider.StorageTypeRDM
    if backing.Kind == "com.vmware.vmdk.RawPhysical" {
        d.RDMType = "physical"
        // block migration
    } else {
        d.RDMType = "virtual"
        // warn but allow
    }
```

**Risk**: Low. Adds more granular detection.

---

### P1-3: Improve Delta Detection

**File**: `internal/providers/vmware/discovery.go`

**Change**: In `isSnapshotDeltaPath()`, add `Backing.Parent != nil` check alongside the suffix pattern check.

```go
func isSnapshotDeltaPath(vmfsPath string, backing *types.VirtualDiskBackingInfo) bool {
    // Must have the delta suffix pattern AND a parent reference
    hasDeltaSuffix := false
    for i := 1; i <= 999; i++ {
        if strings.HasSuffix(vmfsPath, fmt.Sprintf("-%06d.vmdk", i)) ||
           strings.HasSuffix(vmfsPath, fmt.Sprintf("-%03d.vmdk", i)) {
            hasDeltaSuffix = true
            break
        }
    }
    if !hasDeltaSuffix {
        return false
    }
    // Also require parent reference
    if flat, ok := backing.(*types.VirtualDiskFlatVer2BackingInfo); ok {
        return flat.Parent != nil
    }
    return hasDeltaSuffix
}
```

**Risk**: Low. Only changes classification logic.

---

### P1-4: Add Zone UEFI Capability Check

**File**: `internal/providers/cloudstack/provider.go` (or a preflight checker)

**Change**: In the preflight sequence, after getting the zone capabilities, check if the destination zone supports UEFI boot. If the VM is UEFI but zone doesn't support it → preflight fail.

**Risk**: Low. Adds a new validation check.

---

### P1-5: VMware Playwright Test (`vmware-migration.spec.ts`)

**File**: `karios-playwright/tests/vmware-migration.spec.ts` (new)

**Change**: Add Playwright test covering: add VMware source → discover VMs → view VM detail (UEFI, NICs, controller) → start migration → watch SSE progress.

**Risk**: N/A (test only).

---

## Phase 3: P2 Fixes (Next Release)

See architecture.md Section "P2 (nice-to-have)".

---

## Deployment Sequence

### Step 1: Backend Code Changes (karios-migration)

```bash
cd /root/karios-source-code/karios-migration

# Make the changes (coders will implement these)

# Build and verify
go build ./...

# Run unit tests
go test ./internal/osmap/... -v
go test ./internal/providers/vmware/... -v -short

# Commit
git add -A
git commit -m "REQ-VMWARE-AUDIT-001 P0+P1: VMware provider fixes"
git push origin backend/REQ-VMWARE-AUDIT-001-iter1
```

### Step 2: Database Migration (if needed)

If `root_disk_controller` column doesn't exist:
```sql
ALTER TABLE migration_profile ADD COLUMN IF NOT EXISTS root_disk_controller TEXT;
```

### Step 3: Backend Deployment

```bash
# On .106
cd /root/karios-source-code/karios-migration
git pull
go build ./...
systemctl restart karios-backend-worker
# Verify
curl -s http://localhost:8089/api/v1/migration/sources | jq '.[0].data.status'
```

### Step 4: Frontend Changes (karios-web) — Only if P0-4 (boot_mode) changes UI

```bash
cd /root/karios-source-code/karios-web
# Any display logic that matches "OVMF-Secure" needs to also accept "Secure"
git add -A
git commit -m "REQ-VMWARE-AUDIT-001: standardize boot_mode display"
git push origin frontend/REQ-VMWARE-AUDIT-001-iter1
# Deploy
cd /root/karios-source-code/karios-web && npm run build
systemctl restart karios-frontend-worker
```

### Step 5: Verification Against Real ESXi

```bash
# Test P0-1: Free license detection on running VM
curl -X POST http://localhost:8089/api/v1/migrations \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "'$(curl -s http://localhost:8089/api/v1/migration/sources | jq -r '.data[0].id')'",
    "vm_id": "vm-47",
    "dest_zone_id": "...",
    "dest_network_id": "...",
    "dest_offering_id": "..."
  }'
# Expected: 400 Bad Request with "Running VM migration requires licensed ESXi"

# Test P0-2: Assigned IP in VM detail
curl -s http://localhost:8089/api/v1/migration/sources/.../vms/vm-47 | jq '.data.nics[0].assigned_ip'
# Expected: actual IP if VMware Tools running

# Test P0-3: root_disk_controller in migration profile
curl -s http://localhost:8089/api/v1/migrations/... | jq '.data.root_disk_controller'
# Expected: pvscsi or lsi_sas etc.
```

---

## Rollback Plan

If a change causes issues in production:

1. **Revert the commit**:
   ```bash
   cd /root/karios-source-code/karios-migration
   git revert HEAD
   go build ./...
   systemctl restart karios-backend-worker
   ```

2. **Database**: All new columns are NULLABLE — existing records remain valid.

3. **API contract**: New fields are additive — no breaking changes in P0/P1 except `bios` value standardization. If "Secure" causes display issues, revert `deriveBiosLabel` to return "OVMF-Secure" and update the frontend to handle both.

---

## Testing Matrix

| Fix | Dev Test | Integration Test | E2E Test |
|-----|----------|-----------------|----------|
| P0-1: IsFreeLicense wired | `go test -run IsFreeLicense` | Against .232 free ESXi | Playwright: running VM migration blocked |
| P0-2: AssignedIP | Mock VM with Guest.Net | Against `karios-test` (has tools) | — |
| P0-3: root_disk_controller | `go test -run RootDisk` | Against .232 VMs | Check DB: migration_profile.root_disk_controller |
| P0-4: boot_mode values | Unit test | Against all UEFI VMs | UI shows "Secure" not "OVMF-Secure" |
| P1-1: snapshotID moref | Mock test | Against .232 | Monitor: snapshot cleanup on failed migration |
| P1-2: RDM distinction | Mock test | Against RDM VM if available | Migration blocked for pRDM, warned for vRDM |
| P1-3: Delta detection | Mock test | Against snapshot VMs | 3-snapshot chain correctly identified |
| P1-4: Zone UEFI check | Mock zone | Against BIOS-only zone + UEFI VM | Migration blocked |

---

## Dependencies

- **P0-2** requires `vmMo.Guest` property — ensure `GetVM()` property collector request includes `"guest"`.
- **P1-4** requires CloudStack zone capability API — ensure `listCapabilities` is working in the cloudstack provider.

---

*Generated: 2026-04-19 | architect: architect-agent | trace: trace_vmware_audit_001*
