# RQ-03F-B3-D0 — Production Pin and Migration Checklist

**Status: `OWNER_ADOPTION_REQUIRED`.** Only the existing Anchor and frozen-material pins below are observed values. All future production fields intentionally remain `OWNER_INPUT_REQUIRED`. This is not a Trust Anchor update, Profile/Index issuance, signature or deployment authorization.

## Existing formal values to preserve byte-for-byte

| Item | Observed value | Treatment |
|---|---|---|
| Formal Trust Anchor path | `trust/rq03-live-qualification` | Keep its exact checkout and history read-only; this D0 branch does not write to it. |
| Formal Trust Anchor commit | `eb4a95c618e05c5ad6413137478bc65dbca75ec9` | Verified detached checkout; no branch write. |
| Profile 1.0 raw SHA-256 | `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4` | Preserve original bytes; never edit/upgrade in place. |
| Index 1.0 raw SHA-256 | `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4` | Preserve original bytes and commit history. Existing arrays `receipts`, `authors`, `adjudications`, `qualification_runs` are empty. |
| Legacy Profile version / epoch | Profile 1.0 / epoch 1 | Existing role grants expire at `2026-10-16T11:00:00Z`. No automatic extension. |
| Existing roles | author; scope_reviewer; qualification_approver + teacher_approver; corpus_adjudicator | No qualification corpus custodian grant is present. Do not infer or synthesize one. |
| Golden corpus SHA-256 | `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a` | Frozen; 17 original Content bytes rechecked against the fixture manifest. |
| Blind holdout SHA-256 | `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a` | Frozen; no labels imported into any Candidate/Reviewer context. |
| Original NC-02 SHA-256 | `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` | Frozen exact bytes; also N01 Content. |
| 17 case Content digests | All 17 entries in `tests/fixtures/semantic-scope/fixture-files.json` matched. | Per-case SHA values are listed in the existing C1 and B3-B reports; all remain frozen. |

## Future exact-pin template

The Owner or independent deployment authority must fill each blank from independently delivered evidence. Do not use Candidate-generated JSON, a local file, Git metadata, hosted artifact or report-generated value as the production pin source.

| Pin | Exact value | Source / owner / independent check | State |
|---|---|---|---|
| Formal Anchor commit and directory | `OWNER_INPUT_REQUIRED` | Existing Anchor owner; exact commit plus clean checkout and raw hashes | `OWNER_INPUT_REQUIRED` |
| Legacy Profile 1.0 SHA-256 | `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4` | Recompute before archive and after archive | `KNOWN — PRESERVE` |
| Legacy Index 1.0 SHA-256 | `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4` | Recompute before archive and after archive | `KNOWN — PRESERVE` |
| New exclusive archive path and allocation record | `OWNER_INPUT_REQUIRED` | Owner canonical parent and future approved allocator | `OWNER_INPUT_REQUIRED` |
| New Generation ID and absolute Generation path | `OWNER_INPUT_REQUIRED` | Owner-controlled ID and canonical root; created once exclusively | `OWNER_INPUT_REQUIRED` |
| Trusted source commit and checkout SHA | `OWNER_INPUT_REQUIRED` | Exact master/source commit and independent clean-tree check | `OWNER_INPUT_REQUIRED` |
| Controller Root and all Controller/module/schema paths | `OWNER_INPUT_REQUIRED` | Final installed absolute paths; no later relocation | `OWNER_INPUT_REQUIRED` |
| Runtime Root, Python executable, exact patch version | `OWNER_INPUT_REQUIRED` | Final immutable absolute paths; interpreter and runtime digests | `OWNER_INPUT_REQUIRED` |
| Python standard-library/runtime closure SHA | `OWNER_INPUT_REQUIRED` | Complete module/symlink/shared-library closure and host/package identity | `OWNER_INPUT_REQUIRED` |
| Requirements lock, wheelhouse manifest and wheel hashes | `OWNER_INPUT_REQUIRED` | Owner-controlled offline input source; every dependency exact and hashed | `OWNER_INPUT_REQUIRED` |
| OS/base-image/package manifest and shared-library evidence | `OWNER_INPUT_REQUIRED` | Independent host package/image attestation, not a caller claim | `OWNER_INPUT_REQUIRED` |
| Build Inventory 1.1 key, absolute path and raw SHA-256 | `OWNER_INPUT_REQUIRED` | Generate after final installation; independently recalculate, then Owner approve | `OWNER_INPUT_REQUIRED` |
| New Profile 1.1 exact raw SHA-256 | `OWNER_INPUT_REQUIRED` | Created only after adopted Build Inventory and role/identity values | `OWNER_INPUT_REQUIRED` |
| New Index 1.1 exact raw SHA-256 | `OWNER_INPUT_REQUIRED` | Versioned migration with exact old arrays/order preserved; initially no business records | `OWNER_INPUT_REQUIRED` |
| Generation and Controller identity tuple | `OWNER_INPUT_REQUIRED` | Exact profile/index/build/controller binding | `OWNER_INPUT_REQUIRED` |
| Operator, Candidate, Author, Reviewer, Approver identities and UID/GID map | `OWNER_INPUT_REQUIRED` | Host-sourced identity evidence, no inferred defaults | `OWNER_INPUT_REQUIRED` |
| Qualification custodian authorization reference and validity | `OWNER_INPUT_REQUIRED` | Separately granted, least-privilege, bounded authorization; not an old role alias | `OWNER_INPUT_REQUIRED` |
| Launch Policy 1.0 raw SHA-256 and canonical absolute path | `OWNER_INPUT_REQUIRED` | Owner-created from adopted pins and final host paths | `OWNER_INPUT_REQUIRED` |
| Independent Policy Pin 1.0 raw SHA-256 and canonical path | `OWNER_INPUT_REQUIRED` | Separate Owner-controlled trust channel; not stored in Candidate-controlled path | `OWNER_INPUT_REQUIRED` |
| High-Water Authority identity, endpoint and authentication source | `OWNER_INPUT_REQUIRED` | Owner-chosen option; independently authenticated service identity | `OWNER_INPUT_REQUIRED` |
| Genesis Ledger SHA, authority sequence and head-state digest | `OWNER_INPUT_REQUIRED` | Owner-adopted Genesis tied to exact Profile/Build/Generation/Index SHA and revision | `OWNER_INPUT_REQUIRED` |
| Policy Epoch | `OWNER_INPUT_REQUIRED` | C3 only permits the explicit next epoch for migration; the value is not pre-approved here | `OWNER_INPUT_REQUIRED` |
| Role Registry source and revocation-state SHA | `OWNER_INPUT_REQUIRED` | Owner-controlled current source; includes expiry and revoked references | `OWNER_INPUT_REQUIRED` |
| Owner migration lineage SHA and append-only adoption reference | `OWNER_INPUT_REQUIRED` | Exact old/new raw SHA, schema versions, arrays/order diff, record counts and epoch | `OWNER_INPUT_REQUIRED` |
| Independent Owner adoption record | `OWNER_INPUT_REQUIRED` | Existing Trust Anchor append/adoption process only | `OWNER_INPUT_REQUIRED` |

## Migration sequence and stop points

1. **Preserve and verify legacy inputs.** Verify the exact Anchor commit, Profile/Index file bytes, schemas and existing authorization validity. Keep the source checkout read-only. Recompute both old raw hashes before any archive action.
2. **Owner chooses Authority and host.** Complete the applicable fields in the [Target Host Inventory](RQ03F_B3D0_TARGET_HOST_REQUIREMENTS.md) and [Owner Decision Register](RQ03F_B3D0_OWNER_DECISION_REGISTER.md). Without independent Host and Authority owners, stop.
3. **Provision identities through the independent deployment owner.** Verify actual unique UIDs/GIDs, root/sudo boundary, groups, capabilities, ACLs, parent path identities and service manager controls. Values must come from the host, not a candidate plan.
4. **Archive legacy bytes into a new exclusive target.** Only after independently checking source SHAs: allocate a fresh archive target under a pre-existing Owner-controlled canonical parent; copy exact bytes without replacement; recalculate destination SHAs. On collision or mismatch, stop and preserve both original sources and any failed target for forensic review.
5. **Allocate a fresh Generation.** Use the reviewed exclusive allocator and Owner-pinned plan on the canonical parent. Reject existing IDs/targets. Candidate cannot set the Generation ID, parent directory, active pointer or destination path.
6. **Build and install at final absolute paths.** Use exact source commit, fixed runtime and complete hash-locked wheelhouse. Install Controller, schemas and Runtime once; set read-only final paths. Any copy/reinstall/path or byte change restarts from candidate Inventory generation and independent verification.
7. **Build candidate Inventory only after paths are final.** Recompute Controller tree, module/schema set, Python executable/version, site-packages/dependency bytes, runtime closure and absolute-path bindings independently. Owner approves the exact Inventory key/path/SHA. Never edit an adopted Inventory to match a relocated tree.
8. **Create Profile 1.1 and Index 1.1 as new migration artifacts.** Preserve legacy arrays exactly and in order; do not rewrite Profile 1.0 or Index 1.0. The new Index starts with empty business arrays and an empty `qualification_corpus_intakes`. Epoch selection and all role grants remain Owner inputs.
9. **Create migration lineage and Genesis.** Bind source Anchor, old raw hashes, new Profile/Index/Build/Generation hashes, versions/epochs, per-array digests, counts and field-level diff. Separately bind the initial Authority head and revision. An Owner-controlled checkpoint must remain outside both Operator and Authority restore control.
10. **Owner adopts exact bytes.** Use the existing protected Anchor append/adoption route. Candidate JSON, PR commits, Git author identity or synthetic test receipts cannot supply the pins. Keep the old Anchor checkout and historical evidence intact.
11. **Adopt Launch Policy/Pin and disabled service bytes.** Pin exact absolute paths and raw hashes; install nothing until a separate Owner-authorized deployment window. The existing C2 unit is candidate-only, with a candidate Generation path and no `[Install]` section.
12. **Perform A–G acceptance and stop.** Owner reviews target host and production Authority evidence. H (formal Intake) requires its own explicit authorization. L remains an independent Owner action.

## Invalidating events

Any path change, filesystem alias, relocation, reinstall, code/schema byte change, interpreter/runtime change, package or standard-library change, host/base-image change, policy file change, Authority identity change, Owner role/revocation change, or Profile/Index byte change invalidates dependent pins. Rebuild the candidate Inventory or affected adoption record and obtain fresh independent Owner approval. Never patch a historical/Owner-adopted record in place.

## Prohibited recovery shortcuts

Do not clear or recreate the Ledger, restore an old Index as current, lower/reuse an epoch, reuse a Generation ID, reactivate a stale backup, extend old role authorization without new Owner action, infer missing author history, or use a synthetic hosted hash as a production pin. Unknown/high-water mismatch remains `RECOVERY_REQUIRED` and `PRODUCTION_TRUST_BLOCKED`.
