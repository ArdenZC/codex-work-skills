# RQ-03F-B3-B — Independent Operator Trust Deployment Readiness

## 结论

**READY FOR OWNER REREVIEW — RUNBOOK SAFETY REMEDIATED / PRODUCTION TRUST BLOCKED**

本报告提供独立部署所有者可审阅的目标架构、版本迁移顺序、不可执行的准备伪代码、验收清单、失败处理和 Owner 决策清单。对 Owner Review 5479337622 的裁定 **CHANGES_REQUIRED — DEPLOYMENT RUNBOOK SAFETY** 已逐项整改。Codex 未登录或配置目标 Linux 主机，未创建正式账号，未写入正式 Profile/Index，未执行 Intake 或服务启动。由于独立安全分配器、生产 Launcher、TrustContext provider 和 anti-rollback ledger 均缺失，本报告明确禁止任何正式特权部署操作。

Production Trust 仍为 **BLOCKED**。当前材料没有 Owner 批准的 Profile 1.1、Index 1.1、Build Inventory 1.1、锁定运行时、目标 UID/GID、受控服务入口或真实外部写入边界。仓库有权限 provisioning 工具和 isolated bootstrap，但没有可运行正式 operation 的固定 launcher / TrustContext provider / service unit。不得把 B3-A Hosted PASS 当作这些缺项的替代。

未修改正式 Trust Anchor、冻结语料、Golden Truth、Blind Holdout、原始 NC-02 或生产代码；未启动 Agent A/B、Live Reviewer Qualification、Production Trust、RC-02 或 Lesson Skill 2.4。没有使用 codex review 或 codex-review。

## 1. 正式基线与 CI

| 项目 | 核对结果 |
|---|---|
| Trusted master | 955a52d4891b8bcefc337514aa478de167376e63 |
| B3-A PR #58 | MERGED；merge commit 与 trusted master 完全一致 |
| B3-A PR head | 491ca4538f1cc122ab47e1aeb425b9720d2c88bd |
| B3-A Hosted Operator Isolation CI | 38052430469 — SUCCESS，head 491ca4538f1cc122ab47e1aeb425b9720d2c88bd |
| B3-A Template Package CI | 38052430443 — SUCCESS，head 491ca4538f1cc122ab47e1aeb425b9720d2c88bd |
| Post-merge master CI | 38054956640 — SUCCESS；head 为 trusted master；40 jobs SUCCESS、1 个条件式 Documentation checks SKIPPED、0 failures |
| Formal Trust Anchor | eb4a95c618e05c5ad6413137478bc65dbca75ec9 |
| 本轮基于的 master | 955a52d4891b8bcefc337514aa478de167376e63 |

本轮开始前，远端 refs/heads/master 与可信基线一致，B3-A PR merge commit 与该基线一致，工作分支从该基线建立且无本地改动。若 Owner review 期间 master 前移，应在合并前重新做基线 reconciliation，不得覆盖新提交。

Post-merge run 38054956640 已完成，GitHub 元数据绑定 master head 955a52d4891b8bcefc337514aa478de167376e63；41 个 job 均结束，40 个成功、仅条件式 Documentation checks 被跳过，没有失败 job。这个结果与两个 PR #58 exact-head CI 分开核验。

B3-A 的 Hosted Linux 测试在 GitHub 临时 Runner 上证明了所测配置中的真实 Linux UID/DAC/ACL 行为。工作流、root provisioning 脚本和测试来自待审查分支，Runner 可 sudo；这些证据仅适用于 Hosted OS 隔离，不表示独立 Owner 部署或正式 Trust。

## 2. 当前 Formal Trust Anchor 与冻结材料

Trust Anchor checkout 位于独立候选工作区之外，HEAD 为 eb4a95c618e05c5ad6413137478bc65dbca75ec9，工作树干净。其 .operator-trust/rq03-live 的原始文件摘要为：

| 文件 | SHA-256 |
|---|---|
| authority-profile.json | d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4 |
| operation-index.json | 52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4 |
| role-auth-author.json | e8f375766fce2ecd4f2167729aa9e9b0452036ae83b70329a5a1b86430d1a71b |
| role-auth-reviewer-a.json | 38858d09d18d955795e1553b9ab58dc558bd2e7dbbd7409c129990f07b8ba35e |
| role-auth-approver-b.json | 17349dc6b1432d0e5b839c84a9d22605ec11ab25882ffac33c8bcb9feba1d44f |
| role-auth-corpus-adjudicator.json | 0d3e239212b68b69a5efa73ab9d1b25e6f9e26a2286466b6848d19912b29cd06 |
| evidence-repository.md | c48297c5c9a9012b96493be1b5417da533e6a34bde9c5dd186dd77ba5ced96a0 |
| ingress-procedure.md | b4cb4541f5e73d1e231b9b92277033fadec15f90271fac3bd694e21458ee7314 |
| operator-reference.txt | caeb7bb025fcd352c684463db07eefca965625a07c347ae58993e428a2485452 |

The current external profile is version 1.0, policy epoch 1, controller tuple rq03-live-qualification-controller / lesson-semantic-live-qualification-controller / 1.0. It grants author, scope_reviewer, qualification_approver + teacher_approver, and corpus_adjudicator. None of the current authorization rows is a qualification_corpus_custodian grant. Their current validity ends 2026-10-16T11:00:00Z; a future deployment must not rely on this expiring material without fresh Owner authorization.

The current Index is version 1.0, epoch 1. Its receipts, authors, adjudications and qualification_runs arrays are empty. No historical author operation is inferred from Git authorship, role provisioning, or these empty arrays.

In this Codex Cloud workspace, the materialized trust directory and files are mode 0700 / 0600 and owned by UID/GID 1000:1000, the same execution identity as the current workspace. That establishes no independent protected write boundary. The checkout and bytes were read only and remain unchanged; this local mode must not be represented as Production Trust.

Frozen-byte recheck on the candidate baseline:

| Material | SHA-256 | Result |
|---|---|---|
| Golden qualification corpus | 96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a | MATCH |
| Blind holdout truth | 268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a | MATCH |
| Original NC-02 | 878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352 | MATCH |
| Frozen Content cases | 17 case bytes checked against corpus and fixture SHA entries | ALL MATCH |

The 17 Content entries comprise 14 corpus cases and three separately held-out case inputs. All 17 file bytes were independently hashed against the fixture file manifest; no holdout labels or truth values were read into a reviewer context.

| Case | Content SHA-256 |
|---|---|
| N01 | 878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352 |
| N02 | 1151b44b2be3e43530f7ca47178aa92d30366e96673c10fc68deb2c7375916a7 |
| N03 | e02c519ebb837790760bd76b62667605a7c2916c7f561ba4ec120c195e0331e2 |
| N04 | 47094b26a926afc0ae2761109f1814a00f7ceb0bb222684a8ba6e93b266f597c |
| N05 | 57a6efee6021248ded80d831564f5287c1315231cc08759e9f9d6ab223a3e2a1 |
| N06 | f491c68aeda4bdfa5430ab5c024327da181726fcfd1e835eeafa8ca813dc218b |
| P07 | 6b21514f15c4e0b287f3a999dd475604b7d0f1f94f7d3b669433adf952be7fa3 |
| P08 | be75ec999322fc7985dcbd6cb7692d2bbe3bac0499e27fd5bc8cf879a260e867 |
| P09 | 9da74d20e240e77ec207ca6a5fadc539c409dbaac16bf6d99f6cdd9ee02583a5 |
| P10 | dd6e94df2a37c3fbfe0f29c873496e272498ab4c67ec557ae62c1591e26eb5ae |
| P11 | 769d72f7adbae5e617ac2c9a2a504b658a142d40304d535ef04d34766e8f6512 |
| P12 | 06ca333e97f9ad40e44d9e7b13a5dfa9b31d44986da43209d503fe1145738a2c |
| A13 | 6438cdd391f5a2482e62b3be5e821daa860b09664aa0fb1b0f149d5e4786ab92 |
| P14 | c2163bbbd0d0d3f7cf65275185cda051a488c872fb2e3a8b798e05e135008000 |
| H01 | 4cc354b058a6a0dc79eeff0907863594030eddbb2c50e294e3a8db6a444b8924 |
| H02 | f31c794c2f624f5e8cc7154f30fb3dcb69ec25378e94bd92c55b3fba5c159d41 |
| H03 | 85f75c14e687737fc95e5cec89f5ad67c5e977d49e6d4112dc0f2d3bead7b113 |

No frozen bytes or truth were edited. The B3-A report records the same 17 case hashes and the corpus/holdout linkage.

## 3. 目标信任架构和执行身份

| Role | Real host identity / authority | Allowed operations | Explicitly denied |
|---|---|---|---|
| Owner | Independent authority holder using the existing Owner-controlled Trust Anchor adoption path | Approves source/build/profile/index hashes, role grants, epoch, revocations, activation and final acceptance | Does not rely on Candidate-generated metadata as authority |
| Deployment Operator | Named human administrator with separately audited root access for the maintenance window; root is not the runtime principal | Creates fresh system accounts and directories, verifies artifacts, provisions ACL/ownership, keeps service disabled on any mismatch | Must not act as Author, Reviewer, or Approver for the qualification evidence whose independence is being accepted |
| Controller runtime | Dedicated OS account rq03f-operator with unique UID/GID and no supplementary groups; Profile 1.1 principal must have only qualification_corpus_custodian | Runs the Owner-pinned fixed controller path for protected intake and evidence capture with a fresh TrustContext; the Reviewer remains an independently authorized actor | No root, no Candidate-provided authority paths/arguments, no production-authoring or Teacher/PA role; custodian authority does not make it the Reviewer |
| Candidate | Dedicated nonprivileged UID/GID | Submits untrusted candidate operation input through a separately controlled ingress | Cannot read/write Profile, Index, Build Inventory, installed code/runtime, service configuration, or active-generation pointer |
| Author | Separate UID/GID and protected author principal | Uses the real protected authoring path for future production Content | Cannot write review receipts or protected Index; unknown historical corpus author remains unknown |
| Reviewer | Separate UID/GID and managed reviewer principal | Reviews only the authorized operation inputs, under Observation 1.1 and qualification rules | Cannot self-authorize, change Profile/Index, see blind truth, or act as the operation custodian/approver |
| Approver | Separate UID/GID and authorization principal | Independently approves qualification result after required repetitions and evidence review | Cannot write source review evidence or approve own/reviewer/custodian action |

The runtime corpus custodian permission is a new least-privilege qualification role. It is not inherited from author, scope_reviewer, corpus_adjudicator, qualification_approver, or teacher_approver. Deployment Operator is an OS/deployment identity; it is not automatically a semantic role or a historical Content author.

Target ownership and modes required by the reviewed Option B provisioning tool:

| Object | Required target state |
|---|---|
| Trust root | Operator UID/GID, directory 0700; regular protected files 0600; no named/default ACL |
| Profile, Index, Build Inventory, TrustContext inputs | Readable only to the Operator process and root-controlled provisioning path |
| Controller and schemas | root:root, directories 0555, ordinary files 0444, no symlink/hardlink/special file or writable bytecode cache |
| Python runtime | root:root, directories 0555, executable files 0555, other files 0444; exact interpreter and site-packages bytes pinned |
| Candidate/Author/Reviewer/Approver | No traversal/read/write to protected roots; no sudo, shared group, inherited writable descriptor or service control |
| Launcher, service unit and active-generation state | Must be root-owned and immutable to all five runtime roles; the production launcher/service is not present in this repository |

## 4. Controller and operational-code audit

The following exact code digests describe the trusted-master source bytes at this baseline. They are source checks, not Owner-approved runtime pins:

| Component | Baseline SHA-256 |
|---|---|
| tools/rq03f_operator_boundary.sh | 59f45da183aac30926a7ca6badb414b7e2c29652cdaa9be68869d025c8bf34b0 |
| operator_controller_bootstrap.py | 203411ec9ac5a1dcd795412a43942d86c1105d5603b4a3ead3606ddeaa7576dc |
| qualification_corpus_intake.py | 59ad2574e978096ff28cc85ed33eb27674aecaad5979d026e32d358dedd6dbd6 |
| Profile 1.0 schema | 1b8c26a219e97ac7f44d0317c64e4bc62ff062e970badfa1eb6c6650a25136b1 |
| Profile 1.1 schema | d49e2fd973dc411e775e4173b1690c41612d64437354780a1b49c62edabb0876 |
| Index 1.0 schema | 70c2bf66c049237df4749f5214d3cd0c3cec57de435475ae36e9b491a81de505 |
| Index 1.1 schema | cc73f37b727eeec7e6277fe1d0e48ff6b86c0699906a81d5abf8cf09b82828bb |
| Build Inventory 1.1 schema | f0d5a5b3177981f20be3273e30055ce6ffb55dcaabbf1a7974b5b0282055e030 |
| lesson-plan requirements.txt | 6beebd41ac9427ac3344518e097123feb3fa287ed823685f79f7096775f4da96 |

The independent tree calculation on the checked-out source yielded scripts tree SHA-256 7b89a590fe7a00c052da11beeb372de9a129c01c25d7c77b8998bdb341f4ae9a and schemas tree SHA-256 2bad046552996c3fd229712d1480a13c669b8b4da152fe2359be9812d21d7f0e. These values are not deployment Build Inventory pins because a target Python executable, version, site-packages tree, root path and Owner-approved build digest have not been selected.

Build Inventory 1.1 and the stdlib-only bootstrap cover required controller modules including semantic_scope_records, semantic_scope_review, operation_provenance, reviewer_qualification, qualification_corpus_intake, lifecycle_digest, source_truth, exemplar_contract, exemplar_split and path_safety; schema files; Python executable/version; full site-packages tree; and validator dependencies. The bootstrap requires isolated launch with -I -S -B and verifies the externally pinned Inventory before importing controller or third-party modules. TrustContext checks the pinned Profile 1.1, epoch, process UID mapping, controller allowlist, protected Index, Build Inventory and loaded module/schema bindings.

Three deployment gaps remain material:

1. There is no approved target build generator or complete hash-locked runtime/wheelhouse. The current requirements file contains ranges, not a reproducible dependency lock. Build Inventory generation and its SHA must be performed for an Owner-selected runtime and independently recalculated before Owner adoption.
2. operator_controller_bootstrap.py is a verifier/bootstrap, not a production service. Its CLI accepts inventory/root/entrypoint parameters. Security depends on a fixed root-owned caller that supplies only the Owner-pinned values.
3. semantic_lifecycle.operator_context requires an externally installed TrustContext provider. The repository does not provide the production factory, fixed launcher, systemd unit or root-controlled active-generation/high-water mechanism. No candidate-controlled args/environment may select these values.
4. Build Inventory 1.1 pins the Python executable/version and site-packages but has no explicit standard-library tree or system shared-library/image digest field. The launcher/bootstrap itself imports Python standard-library modules before third-party validation. A target host therefore also needs an Owner-approved immutable OS/Python base-image or package-manifest digest and update freeze, independently verified at launch; executable hash plus site-packages hash alone is not the full runtime byte closure.

TrustContext checks that its profile epoch equals its supplied epoch and checks current role revocation. It does not itself maintain an independent monotonic high-water ledger that prevents an operator from restoring an older Profile/Index snapshot. The target service integration must pin the current Owner-adopted generation and epoch outside Candidate-writable data and fail closed if it is absent, lower, revoked or mismatched. This control requires independent design review before activation.

The provisioning script validates path shape, owners, ACLs, links, mode bits, Profile/Index/Build pins and process-role append access. Its provision path changes ACLs, deletes bytecode cache and changes ownership/modes in place; it is not transactional. Run only against fresh, versioned staging directories, with no running writer and service disabled. On any command failure, retain logs, quarantine the entire stage and start again from a fresh directory. Never “roll back” by broadening an old trust directory or restoring an older Index over a newer Index.

## 5. Profile/Index version migration and lineage

The legacy bytes remain immutable at the current Anchor commit. They are an input snapshot, not the new production root.

1. The independent Operator verifies the exact Trust Anchor commit and all old raw Profile/Index/role-authorization hashes above. Preserve the original Anchor checkout and history read-only. Archive the legacy Profile 1.0 and Index 1.0 byte-for-byte only through a separately reviewed exclusive archive allocator, into a new directory under a pre-existing Owner-controlled canonical parent. Verify each source SHA before copying and each destination SHA after copying. A collision, mismatch, path alias, or failed copy is STOP; never repair or reuse an archive.
2. The Owner selects the target host, runtime version, fresh role principals and actual UID/GID values. Only after account creation and identity verification can Profile 1.1 bind operator_unix_uid and non_operator_process_unix_uids.
3. Build controller/runtime from the exact trusted source and locked runtime in private staging. Allocate a fresh final Generation under a separately reviewed fail-closed allocator; install final bytes at their final absolute paths and freeze those paths. Only then build the candidate Build Inventory 1.1 for the installed paths, independently recalculate component/tree and raw Inventory hashes, and obtain Owner approval of that exact key, path, and SHA. Do not rewrite an adopted Inventory if a path or byte changes.
4. After Build Inventory adoption, the Owner issues new role authorizations and a new closed-schema Profile 1.1 that pins the approved build, controller tuple, exact UID mapping, dedicated corpus-custodian principal, allowed roles, validity period, revocation state, and new policy epoch.
5. Create a distinct Index 1.1 migration artifact in staging. Preserve each legacy array record and order exactly; add only the required empty qualification_corpus_intakes array. Any new policy_epoch must be an explicit Owner-approved epoch transition greater than the legacy epoch. Do not populate authors, receipts, adjudications, or qualification_runs. The transformed Index is not adopted until its exact SHA and Profile/Build/Generation binding are reviewed.
6. Create a separate Owner-controlled migration lineage record containing source Anchor commit, old raw Profile and Index digests, target Profile/Index/Build digests, old/new schema versions and epochs, record counts, canonical per-array digests, and a field-by-field diff. Verify old/new arrays are structurally identical and in the same order. The old raw bytes remain archived unchanged. The lineage record belongs to Owner-controlled adoption history; it does not claim that an intake custodian authored any historical Content.
7. Owner adopts the exact new Profile, Index, Build Inventory and lineage record through the existing protected trust-anchor append/adoption procedure. Deployment transfers only those approved bytes through the independent Owner channel and verifies their hashes against the same independently delivered pin list. Candidate files, Git author metadata, local JSON, synthetic B3 artifacts or a name/role pattern cannot supply the pins.
8. Run schema and TrustContext verification against the exact target bytes. Any unexpected field, array change, epoch mismatch, revoked/expired authorization, principal/UID mismatch, build/path mismatch or duplicate identifier stops the deployment. Preserve the previous Anchor and old generation read-only; do not switch or delete it. Any copied/reinstalled path or byte change invalidates the Inventory candidate and requires a new Inventory SHA and fresh Owner adoption; never edit an adopted Inventory to fit a new path.

Index 1.0 and Index 1.1 have closed schemas. Index 1.1 adds qualification_corpus_intakes; it does not reinterpret old fields. Profile 1.1 adds UID and Build Inventory binding requirements; Profile 1.0 is not promoted by editing its version string. New Profile values and the target epoch remain Owner decisions. A value of 2 is a possible next epoch after legacy epoch 1, but this report does not approve or assign it.

### Owner migration decisions to sign

- Target Linux host identity, distribution/kernel/filesystem and supported ACL behavior.
- Exact code source commit after this report is reviewed/merged; target Controller/Build Inventory paths; interpreter version/build; offline package lock and wheelhouse digest.
- Runtime Operator principal and OS UID/GID; Candidate, Author, Reviewer and Approver UIDs/GIDs; proof that accounts have unique IDs, no extra groups, no sudo, no shared write paths.
- New dedicated qualification_corpus_custodian principal and authority record; validity start/end and revocation owner; explicit confirmation that this role grants no production authoring, Teacher approval, PA or Generation authority.
- Owner-approved controller tuple, Inventory key/SHA, Profile 1.1 SHA, Index 1.1 SHA, epoch, revocation list and exact old-to-new lineage digest.
- Root-owned fixed launch integration and active-generation/epoch anti-rollback policy; service account and disabled-by-default unit name.
- Backup location, encryption/physical custody, retention, restore operator and acceptance owner.
- Approval to record a qualification-only corpus intake in the newly adopted protected Index. Without this separate authority, no Intake operation is run.

## 6. Repeatable build and staged deployment procedure

**SAFETY STATUS: DESIGN ONLY / NOT AN EXECUTABLE PRODUCTION RUNBOOK.** This report authorizes no root-level provisioning, archival, trust-file installation, Generation allocation, service launch, or protected operation. Do not copy/paste the former privileged snippets. The repository currently has no separately reviewed exclusive Generation/archive allocator, fixed production Launcher, TrustContext provider, or monotonic anti-rollback ledger. Until these exist and are independently accepted, every production write or protected operation below is **STOP**. The read-only guard is for input-shape checks and synthetic validation only; it does not establish Owner authority or host trust.

### 6.1 Source, parameter, and locked-runtime gates

All values must come from an independently delivered Owner deployment manifest, not CLI arguments, Candidate files, inherited Candidate environment, local Git metadata, or generated JSON. Compare every value under examination with the separately delivered Owner-pinned value for exact equality. Missing and empty fields both fail before any root write.

This Bash guard is read-only. It validates input shapes and exact source checkout identity; it is not a production launcher or trust decision:

~~~bash
set -euo pipefail
fail() { printf 'STOP: %s\n' "$*" >&2; exit 2; }
require_nonempty() {
  local name value
  for name in "$@"; do
    declare -p "$name" >/dev/null 2>&1 || fail "unset: $name"
    value="${!name}"
    [[ -n "$value" ]] || fail "empty: $name"
  done
}
require_sha256() { [[ "$1" =~ ^[a-f0-9]{64}$ ]] || fail "invalid SHA-256"; }
require_commit() { [[ "$1" =~ ^[a-f0-9]{40}$ ]] || fail "invalid commit SHA"; }
verify_pinned_file_sha() {
  local file="$1" expected="$2" actual
  require_sha256 "$expected"
  [[ -f "$file" && ! -L "$file" ]] || fail "missing, non-regular, or symlinked pinned file"
  actual="$(sha256sum -- "$file" | awk '{print $1}')" || fail "cannot hash pinned file"
  [[ "$actual" == "$expected" ]] || fail "file SHA differs from Owner pin"
}
require_canonical_existing_path() {
  local path="$1" expected="$2"
  [[ "$path" == /* && "$expected" == /* ]] || fail "path is not absolute"
  [[ -e "$path" && ! -L "$path" ]] || fail "path missing or symlink"
  [[ "$(realpath -e -- "$path")" == "$expected" && "$path" == "$expected" ]] || fail "non-canonical path"
}
require_generation_id() {
  [[ "$1" =~ ^rq03f-[a-z0-9][a-z0-9-]{0,54}$ && "$1" != *- ]] || fail "invalid Generation ID"
  [[ "$1" != . && "$1" != .. ]] || fail "dot Generation ID"
}
require_inventory_key() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_:-]{0,159}$ ]] || fail "invalid Inventory key"
  [[ "$1" != . && "$1" != .. ]] || fail "dot Inventory key"
}
require_positive_id() { [[ "$1" =~ ^[1-9][0-9]{0,9}$ ]] || fail "invalid UID/GID"; }
require_admin_uid() { [[ "$1" =~ ^(0|[1-9][0-9]{0,9})$ ]] || fail "invalid deployment-admin UID"; }
require_distinct() {
  local expected="$#" actual
  actual="$(printf '%s\n' "$@" | sort -u | wc -l | tr -d ' ')"
  [[ "$actual" == "$expected" ]] || fail "role identities are not distinct"
}

require_nonempty OWNER_ACCEPTED_SOURCE_COMMIT SOURCE_CHECKOUT \
  OWNER_CANONICAL_SOURCE_CHECKOUT OWNER_SHA256_MANIFEST OWNER_CANONICAL_SHA256_MANIFEST
require_commit "$OWNER_ACCEPTED_SOURCE_COMMIT"
require_canonical_existing_path "$SOURCE_CHECKOUT" "$OWNER_CANONICAL_SOURCE_CHECKOUT"
require_canonical_existing_path "$OWNER_SHA256_MANIFEST" "$OWNER_CANONICAL_SHA256_MANIFEST"
[[ "$(git -C "$SOURCE_CHECKOUT" rev-parse HEAD)" == "$OWNER_ACCEPTED_SOURCE_COMMIT" ]] || fail "source commit mismatch"
[[ -z "$(git -C "$SOURCE_CHECKOUT" status --porcelain=v1 --untracked-files=all)" ]] || fail "source tree dirty"
(cd "$SOURCE_CHECKOUT" && sha256sum --check "$OWNER_SHA256_MANIFEST") || fail "source manifest mismatch"
~~~

The code block above runs only the source phase. Later phases must call these same guards with their complete phase-specific parameters, before any privileged operation:

- **Archive:** require nonempty Owner Anchor commit, both exact source file paths and expected hashes, archive parent and target ID; validate commit/SHA formats, exact approved commit, canonical already-existing parent and ownership/ACL/mount chain; hash both source files before asking the exclusive helper to write.
- **Generation:** require nonempty `OWNER_APPROVED_GENERATION_ID`, `GENERATION_ID`, `GENERATION_PARENT`, and Owner-pinned canonical parent; validate Generation ID syntax and exact equality; check parent identity/ownership/permissions for every ancestor before invoking the exclusive allocator. Reject `.`/`..`, empty values, separator characters and target existence.
- **Pre-Inventory:** require nonempty Owner-expected Controller Root, runtime root, module paths, Python executable, site-packages, schemas, Generation ID and source commit. Compare every installed path to its Owner-pinned absolute canonical path and every byte to the locked staging manifest. There is not yet an approved Build SHA at this phase.
- **Post-Inventory adoption:** only after Owner adoption, require nonempty Profile/Index/Build file paths, exact raw SHA pins, Inventory key and filename mapping, Owner-approved Generation, identities, host and maintenance window. Validate the Owner-pinned Profile/Index/Build files with `verify_pinned_file_sha`, every file's exact canonical path, and the Profile-to-Inventory key/SHA/path binding before staging.
- **Role/permission acceptance:** require nonempty Owner, deployment-admin, Operator, Candidate, Author, Reviewer and Approver principals plus actual UID/GID map; validate numeric formats and uniqueness, then compare `getent` and real process IDs. The deployment-admin UID may be 0 only if explicitly Owner-approved; runtime role IDs must be positive and distinct.

For each phase, extend `require_nonempty` with every parameter used in that phase; Bash `: "$VAR"` alone is forbidden because it fails when unset but accepts an empty value. Every expected SHA must be lowercase 64-character SHA-256 and match the independently Owner-delivered pin. Every commit must be a lowercase 40-character object ID and resolve to the exact commit in the pinned checkout. The absolute path value must exactly equal the Owner-pinned canonical string and `realpath -e` result. Apply `require_canonical_existing_path` separately to the final Controller Root, each module/runtime path, Python executable, site-packages, schema tree, Profile/Index/Build source files, and Inventory path. A wrong absolute Build Inventory path is STOP even if its file contents hash correctly. For a not-yet-created target, validate only its already-existing canonical parent; creation belongs to the future exclusive allocator, never shell `mkdir -p`.

Require explicit nonempty host ID, maintenance window, source/archive/Generation paths, Inventory file path, Profile/Index/Build source paths, Owner and deployment-admin principals, runtime principals and all UIDs/GIDs before the relevant operation. UIDs/GIDs must be canonical positive decimal values matching the Owner manifest and live `getent`/process results. Owner, deployment admin, Operator, Candidate, Author, Reviewer and Approver must have the approved independent identities; all runtime role UIDs/GIDs must be distinct, with no shared group, supplementary group, sudo grant, inherited writable descriptor, or cross-role identity. No Candidate-supplied identity, path, pin, launcher argument, or environment variable is accepted. Any exact-equality, format, ownership, permission, or separation failure means STOP before privileged execution.

The Owner must select a fully pinned Python patch release, complete hash-locked requirements file, and offline wheelhouse with independently checked manifests. Existing version ranges do not meet this condition. Build staging is private and non-root. Runtime trust is not established until the complete byte closure has been installed at final paths and inventoried. The current repository has neither an approved dependency lock nor a production Inventory producer.

### 6.2 Legacy archive and fresh Generation allocation

#### Legacy Profile 1.0 / Index 1.0 archive

Preserve the original Anchor checkout, commit, and history read-only. The required source hashes are Profile `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4` and Index `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`. The source commit must equal Owner-pinned `eb4a95c618e05c5ad6413137478bc65dbca75ec9`, unless the independent Owner explicitly supplies a separately verified anchor.

**NON-EXECUTABLE provisioning pseudocode — do not run as shell commands.** The future reviewed archive helper must: (1) require exact nonempty Owner commit, source paths, source SHA values, archive parent, and target identifier; (2) verify the source Anchor commit and both source-byte hashes before any destination write; (3) pin the exact source bytes through immutable Git objects or no-follow file descriptors and copy the same bytes that were prehashed; (4) require an already-existing canonical archive parent whose full ancestor chain is Owner/root controlled, with no symlink, path alias, Candidate-writable component, unexpected ACL, or unexpected mount; (5) atomically create a new archive directory with exclusive semantics and fail if any target entry exists; (6) create destination files with no-overwrite/exclusive semantics, copy exact raw bytes, and rehash both copies; and (7) only after both destination hashes match, apply read-only controls and record the hashes. No implicit parent creation is allowed. A collision, failure, or mismatch stops; a partial newly allocated archive is marked incomplete and never reused. No existing archive or source checkout is modified.

The repository does not contain this reviewed helper. Formal archiving is therefore **STOP / NOT EXECUTABLE**. Do not use `install -d`, output redirection, `cp`, or `mv` against a formal archive path in this runbook.

#### Fresh Generation and trusted root paths

Generation ID is an Owner-manifest value, not a Candidate parameter. Accepted syntax is `rq03f-` followed by a lowercase letter or digit and up to 55 lowercase letters, digits, or hyphens, without a trailing hyphen. Empty values, `.`, `..`, slash, backslash, whitespace, path aliases, and any value differing from the Owner-approved ID are rejected. The trusted parent is fixed in the Owner manifest; Candidate cannot choose the ID, parent, or derived roots.

**NON-EXECUTABLE allocation pseudocode — do not run as shell commands.** Before any root write, a future independently reviewed Linux allocator must pin/open the trusted parent by directory file descriptor; walk and verify every ancestor's canonical identity, owner, mode, ACL, mount, and non-Candidate writability; reject symlinks, hardlinks, bind/path aliases, directory replacement, and unexpected devices; then create the Generation atomically and exclusively relative to that verified descriptor (`openat2`/`mkdirat` with no-follow/beneath constraints or an independently reviewed equivalent). Existing target, dangling symlink, renamed/replaced parent, noncanonical path, or failed post-create identity check is an immediate STOP. Never chmod/chown, repair, reuse, overwrite, or continue inside an existing Generation. All root writes occur only after the path and authority checks pass. The new Generation and derived `trust`, `controller`, and `runtime` paths remain fixed; no rename or symlink/path normalization may retarget them while a process is using them.

Archive and Generation parents must already exist with independently verified ownership and permissions. No implicit parent creation. Before each operation, collect `stat`, ACL, mount, and full-ancestor evidence; require the checked path to equal the Owner-pinned canonical path; and prove Candidate has no write/traverse route, inherited descriptor, shared group, or equivalent privilege. A read-only `realpath` check is necessary but cannot replace descriptor-anchored allocation or prove safety against TOCTOU.

No reviewed exclusive allocator exists in this repository. Formal archive and Generation creation are **STOP / NOT EXECUTABLE**. The existing `tools/rq03f_operator_boundary.sh` is not a safe allocator and must not create or reuse a Generation. Do not perform any root write before the allocator and trust-path checks are implemented, independently reviewed, and Owner accepted.

### 6.3 Final installation path, Build Inventory, and Owner binding order

The required order is strict:

**trusted source → locked runtime → final installation paths → Build Inventory build → independent SHA/path recheck → Owner approval → Profile/Index binding → deployment acceptance.**

1. Verify the Owner-pinned trusted source commit and raw source hashes from the independent Owner channel.
2. Build controller and runtime artifacts in locked, non-root staging; verify the complete runtime and offline package manifest.
3. Securely allocate a fresh Generation under the fixed trusted parent using the reviewed exclusive allocator. Install controller and runtime bytes at their **final immutable absolute paths**. Reject source or destination links, special files, writable files, path aliases, and unexpected filesystem changes. Recalculate installed bytes against the staging manifest. Freeze `controller_root`, every module `runtime_path`, Python executable, site-packages root, schema paths, and Python/dependency tree paths.
4. Only after installation at those final paths, generate candidate Build Inventory 1.1 naming those exact absolute paths and hashes. Cover controller root, every security-sensitive module and schema, module runtime paths, Python executable/version, site-packages root/tree, every dependency, and the separately pinned Python/system runtime closure. The current schema does not capture the complete standard-library/system-library closure; an Owner-approved immutable base-image/package manifest and update freeze are also required.
5. A second independent verifier recalculates component hashes, exact path equality/canonicality, and canonical Inventory bytes, then independently computes raw Inventory SHA-256. Record verifier identity, tools/version, source commit, all absolute paths, component hashes, Inventory key, and raw Inventory digest. Any mismatch is STOP.
6. The Owner reviews and adopts that exact Inventory key, file path, absolute path set, and raw SHA through the existing protected trust-anchor process. Only after this adoption may the Owner create Profile/Index bytes bound to the accepted Inventory SHA/key/paths, epoch, roles, and Generation. Deployment acceptance then rechecks these exact bytes and paths on the target host.

The Inventory key comes only from the Owner-adopted Profile, never Candidate input. Before deriving the existing filename mapping (`:` becomes `_`, then `.bin`), enforce a deployment-safe key form, reject empty/dot/path components and separators, compare the resulting filename exactly with the independently Owner-pinned filename, and prove it resolves directly beneath the canonical Trust Root with no symlink or alias. Any mapping collision or mismatch is STOP. The Profile schema's broader non-whitespace key acceptance does not waive this path-safety gate.

Any copy, reinstall, relocation, symlink resolution, Python/runtime replacement, schema/module byte change, site-packages change, or final-path change invalidates the candidate Inventory. Generate a new candidate Inventory from the new final tree, independently recalculate its hashes, and obtain fresh Owner approval and corresponding Profile/Index binding. Never edit, relabel, or adapt an Inventory already adopted by the Owner.

### 6.4 Existing provisioning tool and absent production runtime

The trusted-master baseline SHA for `tools/rq03f_operator_boundary.sh` is `59f45da183aac30926a7ca6badb414b0e2c29652cdaa9be68869d025c8bf34b0`. It refuses pre-existing account names and performs reviewed permission checks, but it mutates ACLs/ownership/modes in place and is non-transactional. It is not an exclusive archive/Generation allocator, Owner trust source, production launcher, TrustContext provider, or anti-rollback mechanism.

Use that tool only in a later Owner-authorized host window, from the exact independently approved source/build closure, after a reviewed allocator has created the fresh Generation and every final path and Owner-adopted Profile/Index/Inventory hash has been rechecked. Do not run it on the old Anchor or any existing/partially provisioned Generation. Any nonzero status means service remains disabled; preserve logs and the partial tree as incomplete and use a new Generation after the allocator exists. This document intentionally does not provide a root command template because the required trusted inputs and allocator do not yet exist.

A read-only bootstrap probe can verify Build Inventory bytes, but it cannot establish the missing fixed Launcher, TrustContext provider, service unit, or monotonic anti-rollback state. Those operations are **NOT EXECUTABLE / STOP** until separately implemented, independently reviewed, Owner-pinned, and tested on the target host. No command in this report may be interpreted as permission to create Production Trust.

## 7. Independent Owner acceptance Runbook

The following A–L items are an **acceptance checklist only**, not executable commands or production deployment approval. No GitHub-hosted result substitutes for an independent target-host acceptance. Every operational item is **STOP / NOT EXECUTABLE** until the Owner supplies and accepts the independent host, exact source/runtime/Inventory/Profile/Index pins, safe exclusive archive/Generation allocator, fixed Launcher, TrustContext provider, and monotonic anti-rollback mechanism. Any future authorized run must save UTC timestamps, exact command lines, actual UID/EUID/GID/groups, exit status, stdout/stderr, raw hashes, and target host identity in the Owner-controlled record.

Before any future root operation, the independent Operator must run the read-only input-shape checks from §6.1 with an operation-specific complete required-variable list. That list must reject **both unset and empty** values. At minimum the source phase requires the Owner-approved source commit, source checkout and digest manifest; archive phase requires anchor commit, both source paths/SHA pins, canonical existing parent and new target identifier; Generation phase requires Owner-approved Generation ID, canonical existing parent, actual parent ownership/ACL/mount evidence, and all derived final paths; Inventory phase requires key, exact absolute paths, all component hashes, and independent verifier identity; provisioning/acceptance requires Profile/Index/Build SHA, exact Owner-adopted files, host/window, service unit, role principals, and actual UID/GID map. SHA-256 must be 64 lowercase hex; commits must be 40 lowercase hex and resolve in the exact checkout; IDs/keys must pass §6.1 syntax plus exact Owner-manifest equality; all filesystem paths must be absolute and exactly canonical. A wrong path, unapproved SHA, missing Owner approval, failed identity/permission prerequisite, or any empty parameter is STOP before root writes.

The current system has no Owner-adopted Profile 1.1, Index 1.1 or Build Inventory 1.1 for a production host; no final absolute install paths; and no production Launcher, TrustContext provider, service unit or anti-rollback ledger. Therefore these acceptance steps describe future evidence only; they cannot pass in this package and no formal command should be run.

### A. Real Operator identity and UID/GID

- **Precondition / actor:** Root-controlled maintenance session, service disabled. The deployment admin must authenticate independently; the controller runs as rq03f-operator.
- **Command:** In a later Owner-authorized host window, use only the exact independently approved existing account/provisioning tool after the safe allocator and all §6.1 checks pass; this package supplies no root command and does not authorize account creation; then run **id rq03f-operator**, **id rq03f-candidate**, **id rq03f-author**, **id rq03f-reviewer-a**, **id rq03f-approver-b**, **getent passwd** for each, and **sudo -n -u ROLE -- /usr/bin/sudo -n true** for each role.
- **Expected / evidence:** Five distinct nonzero UID/GID pairs, locked accounts, nologin shell, no supplementary group, private home and direct sudo denial. Store raw command output and host /etc/passwd + /etc/group snapshot hash.
- **Stop / Owner:** Any reused name, shared UID/GID, unexpected group, unlocked account or sudo success is FAIL. Owner records and adopts the principal-to-UID mapping before Profile 1.1 is accepted.

### B. Candidate / Author / Reviewer / Approver protected-file denial

- **Precondition / actor:** Fresh real nonprivileged account processes, not mocked UID checks. Root runs each probe under the named UID with groups cleared.
- **Command:** For each role, use **sudo -u ROLE -- /usr/bin/stat "$TRUST_ROOT/operation-index.json"** and a Python **os.open(path, O_WRONLY|O_APPEND)** probe. Record errno; do not count unrelated command errors as denial.
- **Expected / evidence:** Candidate, Author, Reviewer and Approver receive EACCES for both Index read and append, and cannot traverse the protected root. Record actual real/effective IDs and syscall result.
- **Stop / Owner:** Any readable/writable result, unexpected group/descriptor or failure reason other than permission denial is FAIL. Owner accepts the permission matrix and target logs through the existing adoption procedure.

### C. Protected Repository, ACL and path verification

- **Precondition / actor:** Root read-only audit before activating the fixed launcher.
- **Command:** In a later target-host acceptance, the independent verifier captures read-only stat/ACL/tree/ancestor/mount evidence for the exact Owner-pinned paths. This package does not define a privileged path mutation.
- **Expected / evidence:** Trust files are Operator-owned/private; installed code/runtime root-owned/read-only; no named/default ACL, nested mount, symlink, hardlink, special file, group/world writable ancestor, path alias or candidate-owned component.
- **Stop / Owner:** Any mismatch, mutable parent, unexpected mount or ACL is FAIL. Preserve complete output and filesystem/mount identity for Owner.

### D. Controller, schema and dependency SHA verification

- **Precondition / actor:** Independent build verifier and Operator; exact Owner-pinned Build Inventory already in Trust Root.
- **Command:** Only after the final paths and independently Owner-adopted Inventory exist, an independent verifier recalculates the Inventory file SHA, controller/scripts and schemas trees, interpreter, site-packages tree, all components and absolute-path bindings. The existing bootstrap probe is not the missing production Launcher/provider and cannot establish Production Trust; no production probe is authorized in this package.
- **Expected / evidence:** Bootstrap exits 0; independent SHA manifest has zero mismatches; all loaded modules originate at the installed root and package paths equal the Inventory.
- **Stop / Owner:** Any omitted transitive module, schema, dependency, mutable byte, path drift, unknown Python patch or mismatch is FAIL. Owner signs exact Build Inventory SHA and runtime lock/wheelhouse digests. No probe result is captured or claimed in this documentation-only remediation.

### E. Candidate-controlled launcher, environment and module substitution

- **Precondition / actor:** Root-owned fixed launcher and disabled-by-default unit must exist and have been independently reviewed. This is currently missing, so this item cannot pass in this package.
- **Command:** Attempt launch as Candidate with attacker-controlled arguments, PROFILE/INDEX/BUILD variables, PYTHONPATH, PYTHONHOME, user site, hostile shadow modules and a Candidate-local bootstrap; also attempt to replace/rename the installed launcher and service configuration.
- **Expected / evidence:** Fixed launcher rejects all caller arguments and obtains Profile, Index, Build pin and TrustContext only from Owner-controlled generation state; hostile PYTHONPATH marker is not executed under -I -S -B; replacement and service-control attempts are denied.
- **Stop / Owner:** No fixed production launcher/provider/unit means STOP and Production Trust remains blocked. Do not count B3-A synthetic launcher as installed service.

### F. Profile 1.1 / Index 1.1 / Build Inventory 1.1 exact binding

- **Precondition / actor:** Owner-adopted generation and independently delivered raw SHA pins.
- **Command:** Rehash raw files; run the provisioning script with all three expected hashes; run the bootstrap; have the installed external TrustContext provider load the same Profile/Index/Build under the real Operator UID. Compare Profile controller-build key/SHA, Index controller/epoch, UID mapping and protected repository paths.
- **Expected / evidence:** All raw SHA and schema validation succeeds; controller allowlist and epoch match; profile custodian UID equals actual effective UID; other role UID set matches; Build Inventory runtime/controller roots are the installed immutable paths.
- **Stop / Owner:** Any mismatch or Candidate-supplied pin is FAIL. Owner signs the exact adopted tuple and migration-lineage digest.

### G. Epoch rotation and revocation

- **Precondition / actor:** Owner-controlled new generation and a separate disposable test generation for negative tests.
- **Command:** In the disposable generation, load an authorized context, rotate test Profile/epoch and revoke the test role, then prove the old context fails. For production, update the Owner-controlled high-water generation and Profile pin, restart only through the fixed launcher, and test that the previous generation cannot start.
- **Expected / evidence:** Old Profile pin, revoked role, stale epoch, old active-generation pointer and mismatched Build pin all fail closed. Preserve test raw hashes and process logs; never alter formal authority for a test.
- **Stop / Owner:** Since current TrustContext has no monotonic high-water state by itself, the external fixed launcher/high-water control must be independently implemented and accepted before this step can PASS.

### H. Real permission Intake path

- **Precondition / actor:** Exact Owner-approved Profile 1.1 and Index 1.1; separate written Owner authorization to create the qualification-only intake. No reviewer qualification is included.
- **Command:** First execute a nonformal canary Intake in an isolated disposable generation with synthetic test materials. After Owner has adopted the production pins and separately authorized an actual protected intake, invoke the fixed Controller route as rq03f-operator only.
- **Expected / evidence:** Actual UID/EUID matches the dedicated custodian; operation capture and Index append use the approved protected path; old authors[] records remain byte/record-identical; no history is created for an author; corpus/holdout bytes match exact frozen SHA. Save raw operation capture, Index before/after, SHA manifest, timestamp and Operator log.
- **Stop / Owner:** No formal Owner authorization or no fixed provider means no operation. A synthetic Intake is never promoted to protected authority. Any author row, changed truth, hard miss or unauthorized reviewer context is FAIL.

### I. Historical author identity is not fabricated

- **Precondition / actor:** Independent verifier compares old archived Index, new migrated Index and lineage record.
- **Command:** Compare old raw Profile/Index checksums; compare ordered old/new receipts, authors, adjudications and qualification_runs arrays; inspect new qualification_corpus_intakes only for explicit custody evidence.
- **Expected / evidence:** All old raw bytes are retained unchanged; migration arrays preserve source values/order; current source authors remains empty; Intake says historical author claim not made and authoring operation false.
- **Stop / Owner:** Any inferred/inserted author principal, operation ID or historical timestamp is FAIL. Owner accepts the lineage without claims about unknown historical authors.

### J. Qualification-only evidence cannot authorize production

- **Precondition / actor:** Disposable test generation with a qualification-only Intake; production trust files remain read-only.
- **Command:** Run existing deterministic negative contract tests for semantic-scope receipt validation, Production Authoring, Teacher Approval, PA and Generation using the qualification-only receipt/intake fixture. Repeat with a production-purpose request and require rejection.
- **Expected / evidence:** Qualification-only receipt cannot satisfy production authoring provenance, Teacher Approval, PA or Generation; production path still requires true protected author operation. Include exact test command/commit/output and test fixture digests.
- **Stop / Owner:** Any acceptance of qualification-only custody in production path is FAIL. This does not replace the Reviewer three-repetition/hard-miss/holdout/Observation 1.1 review.

### K. Backup, restore and disabled-service failure path

- **Precondition / actor:** Deployment Operator; no operation writer active; service is disabled; backup destination is independent of the protected data filesystem and access-controlled.
- **Command:** Verify backup manifest and raw Profile/Index/Build/operation artifact hashes. Restore only into a disposable clone; keep service disabled and active generation unchanged. Simulate partial provisioning failure and mismatched hashes against a fresh staging tree.
- **Expected / evidence:** Failed provisioning leaves the service disabled, logs complete, stage quarantined, prior active data unchanged; restored clone validates without starting service; operation IDs are reconciled against the append-only Owner ledger. No stale Profile/Index is activated.
- **Stop / Owner:** Never restore an older Index over a newer one, reuse operation IDs, lower the monotonic epoch or reactivate revoked authority. A recovery requires a new Owner-approved epoch/Profile pin, recovery record and acceptance.

### L. Independent Owner final sign-off

- **Precondition / actor:** Owner reviews original target-host evidence, migration lineage, exact code/runtime/profile/index hashes, role mapping, denial results, revocation/anti-rollback behavior, recovery test and all failed attempts.
- **Command:** Owner fills the final acceptance record with host ID, UTC window, source commit, trust anchor commit, Profile/Index/Build SHA, epoch, generation, actor UID/GID mapping and evidence artifact hashes; then explicitly records GO or NO-GO using the existing trust-anchor adoption path.
- **Expected / evidence:** GO only if every A–K required gate is evidenced and recorded/adopted by the independent Owner through the existing trust-anchor process; otherwise NO-GO and service stays disabled. No new PKI is introduced.
- **Stop / Owner:** No Codex-authored signature or synthetic evidence can satisfy this step. No Owner record means Production Trust is not established.

## 8. Backup, recovery, activation and rollback policy

This section is policy only, not executable steps. The production service unit and fixed Launcher are absent, so activation, restore and rollback are **STOP / NOT EXECUTABLE** until an independently reviewed implementation and Owner-controlled parameters exist.

### Before any activation

- Use a maintenance window; stop/disable the independently audited service; verify no Operator writer is active and no lock is held.
- Verify an external backup by hash and restore it into a disposable directory before touching the new generation.
- Provision only fresh versioned trust/controller/runtime paths. Keep the old trust generation and exact Anchor checkout read-only.
- Do not switch service state until every pre-activation check and Owner decision is complete. Activation must use a root-owned fixed launcher and root-controlled generation pointer, not user environment or command arguments.

### Failure before activation

- Keep the service disabled and retain exact stdout/stderr, host identity, and partial tree stat/ACL snapshots.
- Do not repair, reuse, overwrite, rename, or move a Generation through ad hoc shell commands. A future independently reviewed quarantine helper must accept only nonempty Owner-pinned service-unit, canonical Generation path, Generation ID and quarantine-parent values; reject unset/empty inputs; verify the unit is stopped; verify every ancestor's canonical identity/ownership/permissions and same-filesystem requirement; and allocate a new quarantine target exclusively without overwriting any existing entry.
- No such service unit or quarantine helper exists in this repository. Quarantine/rollback is therefore **STOP / NOT EXECUTABLE**. Do not run `install -d`, `mv`, or `systemctl` templates from this report. Restart planning requires a different fresh Generation ID after the safe allocator is implemented; prior trust bytes remain untouched.

### Failure after any protected operation

- Stop the fixed service and deny new operations; preserve the current Index and operation artifacts as the live forensic record.
- Do not restore a prior Index over the current one, truncate an append, reuse any operation ID, or lower epoch. A backup is for forensic copy/recovery planning, not for erasing new operations.
- Reconcile every current operation ID and artifact digest with the external Owner-controlled append ledger. If authority or data integrity is uncertain, remain disabled.
- Restore content only into a separate recovery generation. Owner must issue a fresh nondecreasing epoch, Profile pin, revocation state, Build pin and recovery lineage/adoption record before any service resume.
- The current code lacks a monotonic anti-rollback ledger and a production activation service. Until those controls are supplied and accepted, post-operation rollback cannot produce a Production Trust PASS.

## 9. Go / No-Go decision table

| Gate | Current status | Required evidence for GO |
|---|---|---|
| Independent Operator real host identity | NOT ESTABLISHED | Target-host UID/GID and human root-administration evidence |
| Candidate/Author/Reviewer/Approver OS denial | Hosted test only | A–C target-host process/syscall/ACL logs |
| Owner-adopted Profile 1.1 / Index 1.1 / Build 1.1 | NOT ESTABLISHED | Owner adoption commit and exact raw SHA lineage |
| Reproducible locked runtime | NOT ESTABLISHED | Owner-approved lock/wheelhouse, target Python and full Inventory |
| Standard-library / system runtime integrity | NOT ESTABLISHED | Owner-approved immutable base-image or package-manifest digest and update freeze |
| Fixed production launcher and TrustContext provider | MISSING | Owner-reviewed root-owned service integration and no-argument boundary |
| Monotonic epoch/revocation anti-rollback | MISSING | Independent high-water/current-generation control and stale-generation denial |
| Permission/ACL and import closure | Hosted test only | Target-host A–F evidence against exact production bytes |
| Backup and nonregressing recovery | DESIGN PREPARED | Target-host K restore/failure tests and Owner recovery record |
| Real protected Intake authority | NOT APPROVED | Separate Owner approval and A/H evidence; no review/qualification implied |
| Independent Owner final sign-off | NOT STARTED | Signed/adopted final record after every gate passes |

Any NOT ESTABLISHED or MISSING item means **NO-GO; service disabled; Production Trust blocked**.

## 10. 后续 RQ-03F Live Qualification 的准入条件

本次部署包不授权开始 live qualification。之后必须另有 Owner 明确授权，并先满足以下所有条件：

1. 独立部署所有者在正式 Linux 主机完成 A–L；目标主机真实 UID/GID、权限矩阵、ACL、受信任代码/运行时、服务入口、epoch/revocation、高水位防回滚和恢复流程均有原始 evidence。
2. Owner 通过现有 Trust Anchor adoption 路径批准新的 Profile 1.1、Index 1.1、Build Inventory 1.1、独立迁移 lineage 和精确 SHA；原 Profile/Index 1.0 字节保留。
3. Owner 独立接受实际 Operator 边界，并单独授权 qualification-only corpus intake；只在真正 protected Operator 控制下追加 Intake，确认 authors[] 未因此新增历史 author。
4. 按既有要求确认 corpus/holdout/NC-02 精确冻结、holdout truth 不进入 Reviewer context、每 case fresh operation、three fresh repetitions、hard-miss fail-closed、Reviewer/custodian/approver 独立、Observation 1.1 trace binding、24 小时 expiry、O2/Teacher/PA 隔离均原样有效。
5. Owner 在新的工作包中明确批准启动 Agent A，逐项审查结果后再决定是否允许 Agent B；Agent A/B 仍须有双 logical principals 和独立 qualification approval。任何 hard miss 立即阻断，不允许 retry-until-pass。

缺少任一前置条件时，RQ-03F live qualification、Agent A/B、Production Trust、RC-02 和 Lesson Skill 2.4 都保持未启动/阻断。

## 11. Codex capability boundary and remaining blockers

Codex can verify repository state, public CI metadata, source/schema bytes, frozen fixture hashes and prepare this reviewable runbook. Codex cannot create a distinct human Owner, provision independent target-host UIDs, establish real root-vs-Operator custody on an external machine, issue Owner-authorized profile/role pins, or sign/adopt the new protected generation.

Production remains blocked until all of the following are supplied and reviewed:

1. Owner-selected target host, service owner, real role UID/GID mapping, and separately controlled human deployment root account.
2. Exact Owner-adopted Profile 1.1 / Index 1.1 / Build Inventory 1.1 and migration-lineage record based on the unchanged Anchor bytes.
3. Complete offline runtime lock/wheelhouse and exact target Python patch release.
4. Deterministic Build Inventory producer or independently audited operator build procedure, plus an Owner-pinned base-image/package manifest covering the Python standard library and linked system libraries.
5. Fixed root-owned service launcher, TrustContext provider, disabled-by-default service unit, root-owned generation/high-water state and revocation/anti-rollback tests.
6. Target-host backup/restore evidence and a separately authorized decision to append any formal qualification corpus intake.
7. Target-host A–K evidence followed by independent Owner L sign-off.

Existing requirements remain in force after deployment: three fresh repetitions, blind holdout truth isolation, hard-miss fail-closed, Reviewer/custodian/approver independence, independent qualification approval, Observation 1.1 trace binding, 24-hour managed observation expiry, Profile epoch rotation/revocation, O2/Teacher/PA security boundaries, and production author provenance. This package grants no permission to begin Agent A/B or Live Reviewer Qualification.

## 12. 本轮交付

- This remediation changes this deployment-readiness report only; no production code, schema, script, workflow, fixture, trust anchor, frozen corpus, holdout or golden truth is modified.
- Owner Review finding 1 (Generation escape/reuse): rejects empty/dot/path-alias IDs, pins the canonical Owner parent, requires ancestor ownership/permission/ACL/mount checks, and marks exclusive descriptor-anchored allocation non-executable until a reviewed helper exists. Existing Generations are never repaired or reused.
- Owner Review finding 2 (archive overwrite): requires a fresh exclusive archive under a pre-existing Owner-controlled parent, source SHA checks before copy, destination SHA checks after copy, no-overwrite writes, fail-stop behavior, and preservation of the original Anchor checkout/history.
- Owner Review finding 3 (Inventory binding): records the exact trusted source → locked runtime → final install path → Inventory build → independent SHA/path review → Owner approval → Profile/Index binding → deployment acceptance order. Any path/byte change requires a new candidate Inventory and Owner approval; adopted Inventory is immutable.
- Owner Review finding 4 (parameters/executability): read-only guard rejects unset and empty inputs, validates digest/commit/ID/key formats, canonical paths, exact Owner pins and role/UID/GID inputs; absent production Launcher, TrustContext provider, service unit and anti-rollback ledger are explicit STOP / NOT EXECUTABLE blockers.
- Synthetic command-flow validation: **18 PASS** on disposable temporary paths and synthetic bytes, using real file operations under the current nonprivileged UID. Rejected `.`, `..`, empty/separator Generation IDs, unset and empty variables, invalid SHA, wrong absolute Build Inventory path, unapproved SHA before state advancement, existing Generation reuse, existing Archive overwrite, source SHA mismatch before Archive allocation, and a symlink parent alias. Existing Generation/Archive sentinel hashes remained unchanged; unapproved SHA created no advancement marker; a valid new synthetic Archive had matching source and copied-byte SHA. This does not exercise independent UIDs, root/DAC/ACL isolation, a production allocator, or a target host and is not deployment acceptance.
- Frozen-byte recheck: trust anchor remains `eb4a95c618e05c5ad6413137478bc65dbca75ec9`; Profile SHA `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4`; Index SHA `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`. Golden corpus `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a`, Blind Holdout `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a`, Original NC-02 `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`; all **17 case Content bytes** match `fixture-files.json`.
- No formal Anchor archive, Generation, Profile/Index migration, trust-anchor append, service installation/activation, Intake, Agent A/B, or qualification operation was performed.
- Fresh exact-HEAD PR CI URL and final commit SHA are reported from GitHub after push; Production Trust remains BLOCKED.
