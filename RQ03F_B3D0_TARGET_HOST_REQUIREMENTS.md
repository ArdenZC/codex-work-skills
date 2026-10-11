# RQ-03F-B3-D0 — Target Host Requirements and Deployment Inventory

**Status: `TARGET_HOST_EVIDENCE_REQUIRED`.** This is an unsigned Owner-fillable template. Every value is intentionally blank and marked `OWNER_INPUT_REQUIRED`; it contains no host ID, address, UID/GID, certificate, secret, trust path, cloud account, or authorization claim.

## Target host identity and platform

| Field | Owner value | Evidence to attach |
|---|---|---|
| Host identity / inventory ID | `OWNER_INPUT_REQUIRED` | Owner-controlled asset inventory record and host identity evidence |
| Host owner and independent deployment administrator | `OWNER_INPUT_REQUIRED` | Named Owner-approved administrators and separation-of-duty record |
| OS distribution, version, support status | `OWNER_INPUT_REQUIRED` | Signed package manifest or immutable image reference |
| Kernel release, architecture, boot mode | `OWNER_INPUT_REQUIRED` | `uname`/boot evidence captured by the independent deployment administrator |
| Secure boot / measured boot / TPM presence and version | `OWNER_INPUT_REQUIRED` | Platform-native evidence; do not infer from a VM product description |
| Base image or OS package set SHA-256 | `OWNER_INPUT_REQUIRED` | Independently calculated image/package-manifest digest and Owner pin |
| Python implementation and exact patch version | `OWNER_INPUT_REQUIRED` | Interpreter path, version output, executable SHA-256 and vendor/package provenance |
| Python standard library tree digest | `OWNER_INPUT_REQUIRED` | Independent complete tree manifest, including symlink target handling |
| Dynamic linker, libc and shared-library inventory | `OWNER_INPUT_REQUIRED` | OS package/dynamic-link manifest and digests |
| Runtime and wheelhouse lock | `OWNER_INPUT_REQUIRED` | Fully pinned package versions, wheel hashes, Python ABI/platform tags, offline-source identity |
| Filesystem type and mount options for every protected root | `OWNER_INPUT_REQUIRED` | `findmnt`/mount output, device and mount IDs, filesystem configuration |
| Snapshot/clone/restore administrators and scope | `OWNER_INPUT_REQUIRED` | Storage control-plane roles, snapshot policy and restore audit trail |
| Trusted time source and maximum accepted skew | `OWNER_INPUT_REQUIRED` | Time-source configuration, monitoring evidence and fail-closed skew threshold |
| DNS/network path and allowed Authority endpoints | `OWNER_INPUT_REQUIRED` | Owner-reviewed outbound policy, endpoint identity and TLS verification evidence |
| Audit log path, access controls and retention | `OWNER_INPUT_REQUIRED` | Independent write/read roles, retention policy and immutable export evidence |

## Independent identities

No numeric IDs or credentials are preselected. Owner must create unique, non-reused OS identities, record them, and prove them with host process credentials and account databases. Each runtime role must have no extra supplementary group, no inherited write-capable descriptor, no sudo/root, no effective capabilities and no path to manage the service or Authority.

| Principal class | OS account / external principal | UID | Primary GID | Supplemental groups | Sudo/capabilities | Owner authorization reference / expiry |
|---|---|---|---|---|---|---|
| Deployment administrator (maintenance only) | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Operator controller runtime | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Candidate | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Author | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Reviewer | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Approver | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| High-Water Authority service / workload identity | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Independent Authority administrator / backup custodian | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |

Identity separation must be tested from actual processes. A Profile role string, Unix account name, Git commit author, cloud service account name, or synthetic hosted UID does not establish a production identity. The formal Profile 1.0 currently has no corpus-custodian grant; a separately authorized Profile 1.1 must provide any future custodian role.

## Protected paths and process boundary

| Path / object | Canonical absolute path | Owner:UID:GID | Mode / ACL | Filesystem / mount identity | Candidate-access result |
|---|---|---|---|---|---|
| Formal Anchor checkout (read-only preservation) | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Read-only; no mutation |
| New protected Trust root | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` |
| Legacy Profile/Index archive target | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | New exclusive target only |
| Generation root / selected Generation | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Candidate cannot choose ID, parent, pointer, or rename target |
| Controller root and schemas | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Read-only to runtime roles |
| Python executable / runtime root / site-packages | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Read-only to runtime roles |
| Profile 1.1 / Index 1.1 / Build Inventory 1.1 | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Candidate/Author/Reviewer/Approver denied |
| Launch Policy / Policy Pin | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Owner/root-controlled; not selected from env/argv |
| Evidence and staged transaction root | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Exact staging/publication ACL recorded |
| Active-generation pointer (if introduced) | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Root/Owner only; generation switch requires adoption |
| systemd unit, fixed Launcher and environment | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Runtime roles cannot edit, enable, start or stop |
| High-Water Authority endpoint or Unix socket | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Authenticated Operator identity only |
| Authority database/state, WAL, backups and restore staging | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Separate Authority admin domain |
| Security audit logs and immutable export | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | `OWNER_INPUT_REQUIRED` | Candidate/Operator cannot erase or rewrite |

For every path, the independent verifier must record `lstat`/canonical identity for each ancestor, owner/mode/ACL, symlink/hardlink status, device/inode/mount ID and whether the parent is writable by Candidate. Same UID in a different directory is not isolation. A candidate or Operator path that can alter the Authority's code, state, backups, credentials, policy, or endpoint fails the boundary.

## Service and Authority deployment fields

| Field | Owner value | Required evidence |
|---|---|---|
| Chosen Authority option (A/B/C) and decision reference | `OWNER_INPUT_REQUIRED` | Signed Owner decision; current proposal is not approval |
| Provider/product and region or Witness host set | `OWNER_INPUT_REQUIRED` | Exact resource identity and management boundary |
| Authority adapter source commit / source digest | `OWNER_INPUT_REQUIRED` | Owner-reviewed source, CI evidence and independently recalculated digest |
| Authority service binary/runtime digest | `OWNER_INPUT_REQUIRED` | Locked build, exact runtime and measured installed bytes |
| Authority identity and authentication mechanism | `OWNER_INPUT_REQUIRED` | Owner-controlled certificate/identity enrollment; private material kept outside this repository |
| Operator workload identity and permitted calls | `OWNER_INPUT_REQUIRED` | Least-privilege auth policy with distinct admin/backup roles |
| Genesis sequence, head digest, initial Index SHA/revision | `OWNER_INPUT_REQUIRED` | Owner-adopted Genesis binding; no synthetic value accepted |
| Fencing token semantics and reservation lifetime | `OWNER_INPUT_REQUIRED` | Versioned protocol contract and expiry/revocation tests |
| Backup schedule / independent backup domain | `OWNER_INPUT_REQUIRED` | Separate control plane and verified retention |
| Restore and re-adoption procedure | `OWNER_INPUT_REQUIRED` | Restore-to-quarantine evidence and Owner-only activation rule |
| Service state | `DISABLED — OWNER_INPUT_REQUIRED` | Remains disabled until the Owner's separate A–L acceptance |

## Acceptance evidence packet

Before any deployment decision, attach raw, redacted-for-secrets host evidence with stable artifact hashes for: machine and kernel identity; all OS account mappings and actual process UIDs/GIDs; groups/capabilities/open descriptors; ACL and ancestor/path audit; code/schema/Inventory/runtime SHA manifests; launch policy and unit byte hashes; endpoint peer identity; Authority transaction and recovery test logs; backup/restore trial; audit log location/retention; and cleanup/disabled-service proof. Do not place secrets or private keys in this template or in the repository.

**No target-host fields are completed in this D0 package.**
