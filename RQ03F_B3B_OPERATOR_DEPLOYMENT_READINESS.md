# RQ-03F-B3-B — Independent Operator Trust Deployment Readiness

## 结论

**READY FOR OWNER REVIEW — DEPLOYMENT PACKAGE PREPARED / PRODUCTION TRUST BLOCKED**

本报告提供独立部署所有者可审阅的目标架构、版本迁移顺序、命令模板、验收 Runbook、失败处理和 Owner 决策清单。Codex 未登录或配置目标 Linux 主机，未创建正式账号，未写入正式 Profile/Index，未执行 Intake 或服务启动。这里的命令是未来由 Owner 指定的独立部署者在目标主机上执行的操作步骤，不是本轮执行记录。

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

1. The independent Operator verifies the exact Trust Anchor commit and all old raw Profile/Index/role-authorization hashes above. Copy the legacy Profile 1.0 and Index 1.0 byte-for-byte into an access-controlled read-only archive outside the new candidate/operation root. Rehash the copies. Do not rewrite the old branch or files.
2. The Owner selects the target host, runtime version, fresh role principals and actual UID/GID values. Only after account creation and identity verification can Profile 1.1 bind operator_unix_uid and non_operator_process_unix_uids.
3. Build and verify the immutable controller/runtime first. Owner reviews and adopts its exact Build Inventory 1.1 key and SHA. Then the Owner issues new role authorizations and a new closed-schema Profile 1.1 that pins the approved build, controller tuple, exact UID mapping, dedicated corpus-custodian principal, allowed roles, validity period, revocation state, and new policy epoch.
4. Create a distinct Index 1.1 migration artifact in staging. Preserve each legacy array record and order exactly; add only the required empty qualification_corpus_intakes array. Any new policy_epoch must be an explicit Owner-approved epoch transition greater than the legacy epoch. Do not populate authors, receipts, adjudications, or qualification_runs. The transformed Index is not adopted until its own exact SHA is reviewed.
5. Create a separate Owner-controlled migration lineage record containing source Anchor commit, old raw Profile and Index digests, target Profile/Index/Build digests, old/new schema versions and epochs, record counts, canonical per-array digests, and a field-by-field diff. Verify old/new arrays are structurally identical and in the same order. The old raw bytes remain archived unchanged. The lineage record belongs to Owner-controlled adoption history; it does not claim that an intake custodian authored any historical Content.
6. Owner adopts the exact new Profile, Index, Build Inventory and lineage record through the existing protected trust-anchor append/adoption procedure. Deployment copies only those approved bytes into the new staging generation and verifies their hashes against an independently delivered Owner pin list. Candidate files, Git author metadata, local JSON, synthetic B3 artifacts or a name/role pattern cannot supply the pins.
7. Run schema and TrustContext verification against the exact target bytes. Any unexpected field, array change, epoch mismatch, revoked/expired authorization, principal/UID mismatch, build/path mismatch or duplicate identifier stops the deployment. Preserve the previous Anchor and old generation read-only; do not switch or delete it.

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

This procedure is for the future independent deployment Owner. Commands below deliberately fail if required Owner pins are unset. No placeholder value in this document is an authority value.

### 6.1 Offline source/runtime preparation

Use a new clean package checkout of the exact Owner-accepted merged source commit, never a developer worktree or PR branch. Verify repository cleanliness and the Owner-provided source digest list before building:

~~~bash
set -euo pipefail
: "$OWNER_ACCEPTED_SOURCE_COMMIT"
: "$SOURCE_CHECKOUT"
: "$OWNER_SHA256_MANIFEST"
test "$(git -C "$SOURCE_CHECKOUT" rev-parse HEAD)" = "$OWNER_ACCEPTED_SOURCE_COMMIT"
test -z "$(git -C "$SOURCE_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
(cd "$SOURCE_CHECKOUT" && sha256sum --check "$OWNER_SHA256_MANIFEST")
~~~

The Owner selects the Python patch version and supplies a reviewed, fully pinned requirements lock with hashes plus an offline wheelhouse whose manifest has been independently checked. Existing version ranges are not sufficient. In the copied runtime, install without network access:

~~~bash
set -euo pipefail
: "$PYTHON_EXE"
: "$BUILD_RUNTIME"
: "$LOCK_FILE"
: "$WHEELHOUSE"
"$PYTHON_EXE" -m venv --copies "$BUILD_RUNTIME"
"$BUILD_RUNTIME/bin/python" -m pip install --no-index --find-links "$WHEELHOUSE" --require-hashes --no-compile -r "$LOCK_FILE"
"$BUILD_RUNTIME/bin/python" --version
~~~

Dereference interpreter/package symlinks into the standalone installed tree, preserve no hard links, and verify before provisioning:

~~~bash
set -euo pipefail
find "$BUILD_CONTROLLER_ROOT" "$BUILD_RUNTIME" -type l -print -quit | (! read -r _)
find "$BUILD_CONTROLLER_ROOT" "$BUILD_RUNTIME" -type f -links +1 -print -quit | (! read -r _)
find "$BUILD_CONTROLLER_ROOT" "$BUILD_RUNTIME" -type f -perm /022 -print -quit | (! read -r _)
sha256sum "$BUILD_RUNTIME/bin/python"
~~~

Build Inventory 1.1 must enumerate the complete installed closure, including required modules/schemas, scripts and schema tree hashes, runtime interpreter bytes/version, the complete site-packages tree and each required dependency. Recalculate the canonical Inventory file SHA independently. Owner pins that exact digest before it is placed in Profile 1.1. The current repository does not contain a production inventory generator or approved dependency lock; this step is a production gate, not a claimed completed build.

### 6.2 Prepare isolated versioned roots

First preserve the old raw trust inputs outside the candidate checkout. Run as the deployment root administrator. The destination must be a fresh Owner-controlled archive directory with separate access control. The Anchor checkout is read only:

~~~bash
set -euo pipefail
: "$ANCHOR_CHECKOUT"
: "$OWNER_TRUST_ANCHOR_COMMIT"
: "$ARCHIVE_ROOT"
test "$(git -C "$ANCHOR_CHECKOUT" rev-parse HEAD)" = "$OWNER_TRUST_ANCHOR_COMMIT"
install -d -o root -g root -m 0700 "$ARCHIVE_ROOT"
git -C "$ANCHOR_CHECKOUT" show "$OWNER_TRUST_ANCHOR_COMMIT:.operator-trust/rq03-live/authority-profile.json" > "$ARCHIVE_ROOT/authority-profile-v1.0.json"
git -C "$ANCHOR_CHECKOUT" show "$OWNER_TRUST_ANCHOR_COMMIT:.operator-trust/rq03-live/operation-index.json" > "$ARCHIVE_ROOT/operation-index-v1.0.json"
test "$(sha256sum "$ARCHIVE_ROOT/authority-profile-v1.0.json" | awk '{print $1}')" = "d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4"
test "$(sha256sum "$ARCHIVE_ROOT/operation-index-v1.0.json" | awk '{print $1}')" = "52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4"
chmod 0400 "$ARCHIVE_ROOT/authority-profile-v1.0.json" "$ARCHIVE_ROOT/operation-index-v1.0.json"
~~~

Record the copied bytes and Anchor commit in the Owner migration lineage. Do not push or modify the source Anchor.

Use three distinct fresh roots, all outside the Candidate checkout. Example path layout (the target Owner may approve another canonical layout):

~~~bash
set -euo pipefail
: "$GENERATION_ID"
case "$GENERATION_ID" in (*[!A-Za-z0-9._-]*|'') exit 2;; esac
GEN_ROOT="/var/lib/rq03f/generations/$GENERATION_ID"
TRUST_ROOT="$GEN_ROOT/trust"
CONTROLLER_ROOT="$GEN_ROOT/controller"
RUNTIME_ROOT="$GEN_ROOT/runtime"
sudo install -d -o root -g root -m 0711 "$GEN_ROOT"
sudo install -d -o root -g root -m 0750 "$TRUST_ROOT" "$CONTROLLER_ROOT" "$RUNTIME_ROOT"
sudo cp -RL --preserve=mode,timestamps "$BUILD_CONTROLLER_ROOT/." "$CONTROLLER_ROOT/"
sudo cp -RL --preserve=mode,timestamps "$BUILD_RUNTIME/." "$RUNTIME_ROOT/"
sudo chown -R root:root "$CONTROLLER_ROOT" "$RUNTIME_ROOT"
sudo chmod -R go-w "$CONTROLLER_ROOT" "$RUNTIME_ROOT"
test "$(realpath -e "$TRUST_ROOT")" = "$TRUST_ROOT"
test "$(realpath -e "$CONTROLLER_ROOT")" = "$CONTROLLER_ROOT"
test "$(realpath -e "$RUNTIME_ROOT")" = "$RUNTIME_ROOT"
~~~

Before any copy, capture target filesystem/mount and ACL state, confirm all ancestors are root-owned and not group/world writable, and verify the three roots do not overlap each other or the Candidate run root. Load only the Owner-adopted bytes into Trust Root. The file mapping for the pinned Build Inventory must match Profile 1.1's controller_build_inventory_key after the script's colon-to-underscore mapping and .bin suffix. Preserve the owner-delivered pin list outside Candidate-writable roots.

Copy only Owner-adopted Profile/Index/Inventory bytes from the separately delivered package. Confirm each raw SHA before staging. The inventory filename is derived from the Owner-pinned Profile key, and the script rechecks the Profile-to-Inventory digest binding:

~~~bash
set -euo pipefail
: "$OWNER_PROFILE_FILE"
: "$OWNER_INDEX_FILE"
: "$OWNER_BUILD_FILE"
: "$OWNER_BUILD_INVENTORY_KEY"
: "$PROFILE_SHA256"
: "$INDEX_SHA256"
: "$BUILD_SHA256"
case "$OWNER_BUILD_INVENTORY_KEY" in (*[!A-Za-z0-9._:-]*|'') exit 2;; esac
test -f "$OWNER_PROFILE_FILE" && test ! -L "$OWNER_PROFILE_FILE"
test -f "$OWNER_INDEX_FILE" && test ! -L "$OWNER_INDEX_FILE"
test -f "$OWNER_BUILD_FILE" && test ! -L "$OWNER_BUILD_FILE"
test "$(sha256sum "$OWNER_PROFILE_FILE" | awk '{print $1}')" = "$PROFILE_SHA256"
test "$(sha256sum "$OWNER_INDEX_FILE" | awk '{print $1}')" = "$INDEX_SHA256"
test "$(sha256sum "$OWNER_BUILD_FILE" | awk '{print $1}')" = "$BUILD_SHA256"
BUILD_INVENTORY_FILENAME="$(printf '%s' "$OWNER_BUILD_INVENTORY_KEY" | tr ':' '_').bin"
sudo install -o root -g root -m 0400 "$OWNER_PROFILE_FILE" "$TRUST_ROOT/authority-profile.json"
sudo install -o root -g root -m 0400 "$OWNER_INDEX_FILE" "$TRUST_ROOT/operation-index.json"
sudo install -o root -g root -m 0400 "$OWNER_BUILD_FILE" "$TRUST_ROOT/$BUILD_INVENTORY_FILENAME"
~~~

The source files and pin list must come from the independent Owner delivery channel. A Candidate-controlled JSON file cannot set these variables or replace the pin list.

### 6.3 Provision separate role accounts and protected directories

The checked-in script source SHA at trusted master is 59f45da183aac30926a7ca6badb414b7e2c29652cdaa9be68869d025c8bf34b0. After Owner accepts the final source commit, independently compare this tool's bytes with the Owner-approved source/build manifest. Run only during a maintenance window as root:

~~~bash
set -euo pipefail
: "$APPROVED_SOURCE_CHECKOUT"
TOOL="$APPROVED_SOURCE_CHECKOUT/tools/rq03f_operator_boundary.sh"
test "$(sha256sum "$TOOL" | awk '{print $1}')" = "59f45da183aac30926a7ca6badb414b7e2c29652cdaa9be68869d025c8bf34b0"
sudo -- bash "$TOOL" create-accounts
~~~

This exact digest applies to the trusted-master baseline. If an Owner-accepted commit changes the script, the Owner must approve the new digest and update the command rather than reuse this value. The script refuses pre-existing role names and emits actual UIDs/GIDs. Stop on any existing name, UID/GID collision, extra group, unlocked account, unexpected home/shell, or sudo grant. Do not choose Profile 1.1 UID fields from a design estimate.

Once the Owner has approved new Profile 1.1, Index 1.1 and Build Inventory 1.1 bytes, stage those exact files and run:

~~~bash
set -euo pipefail
: "$PROFILE_SHA256"
: "$INDEX_SHA256"
: "$BUILD_SHA256"
sudo -- bash "$TOOL" provision "$TRUST_ROOT" "$CONTROLLER_ROOT" "$RUNTIME_ROOT" "$PROFILE_SHA256" "$INDEX_SHA256" "$BUILD_SHA256"
~~~

Expected output includes Operator UID/GID, denied direct Index append for Candidate/Author/Reviewer/Approver, allowed Operator append open, and exact Profile/Index hashes. This script is not an Owner trust source and does not create a production launcher. Do not run it against the existing Trust Anchor directory. Since it mutates modes/ACLs in place, a nonzero exit means service remains disabled, logs are retained, and the entire new generation is quarantined; create a fresh generation to retry.

After provisioning, independently capture:

~~~bash
sudo stat -Lc '%n %F %u:%g %a %h %d' "$TRUST_ROOT" "$TRUST_ROOT/authority-profile.json" "$TRUST_ROOT/operation-index.json" "$CONTROLLER_ROOT" "$RUNTIME_ROOT"
sudo getfacl -pe -R "$TRUST_ROOT" "$CONTROLLER_ROOT" "$RUNTIME_ROOT"
sudo find "$TRUST_ROOT" "$CONTROLLER_ROOT" "$RUNTIME_ROOT" -xdev -printf '%y %u:%g %m %n %p\n'
~~~

Compare Profile/Index raw hashes before and after provisioning. Confirm no candidate-writable parent, ACL, mount alias, symlink, hardlink, file descriptor, or writable bytecode path remains.

### 6.4 Bootstrap verification command

Only after a fixed root-owned service launcher exists, the Operator can run the bootstrap with clean environment and Owner-pinned values. For a read-only build probe, the direct command is:

~~~bash
sudo -u rq03f-operator -- env -i PATH=/usr/bin:/bin "$RUNTIME_ROOT/bin/python" -I -S -B "$CONTROLLER_ROOT/scripts/operator_controller_bootstrap.py" --build-inventory "$TRUST_ROOT/$BUILD_INVENTORY_FILENAME" --build-sha256 "$BUILD_SHA256" --controller-root "$CONTROLLER_ROOT"
~~~

Expected stdout: controller_build=verified and exit 0. A wrong build SHA, altered dependency/module/schema, unpinned root, normal Python launch, Candidate-selected Inventory or hostile import origin must exit nonzero. This probe validates a build, not a TrustContext provider, a semantic operation, or Production Trust. The direct bootstrap command must not be exposed to Candidate as a launcher.

## 7. Independent Owner acceptance Runbook

The following A–L steps are for the real target host and a later Owner-authorized acceptance window. No GitHub-hosted result substitutes for them. Each step must save UTC timestamps, command lines, actual UID/EUID/GID/groups, exit status, stdout/stderr, raw hashes and target host identity into the Owner-controlled acceptance record. Any unexpected result stops the procedure and leaves the service disabled.

At the start, the independent Operator supplies the following verified values from the Owner-controlled deployment manifest. Empty or Candidate-sourced values fail closed:

~~~bash
set -euo pipefail
: "$OWNER_ACCEPTED_SOURCE_COMMIT"
: "$OWNER_TRUST_ANCHOR_COMMIT"
: "$PROFILE_SHA256"
: "$INDEX_SHA256"
: "$BUILD_SHA256"
: "$GENERATION_ID"
: "$TRUST_ROOT"
: "$CONTROLLER_ROOT"
: "$RUNTIME_ROOT"
: "$BUILD_INVENTORY_FILENAME"
~~~

### A. Real Operator identity and UID/GID

- **Precondition / actor:** Root-controlled maintenance session, service disabled. The deployment admin must authenticate independently; the controller runs as rq03f-operator.
- **Command:** Run the create-accounts/provision commands in §6.3; then run **id rq03f-operator**, **id rq03f-candidate**, **id rq03f-author**, **id rq03f-reviewer-a**, **id rq03f-approver-b**, **getent passwd** for each, and **sudo -n -u ROLE -- /usr/bin/sudo -n true** for each role.
- **Expected / evidence:** Five distinct nonzero UID/GID pairs, locked accounts, nologin shell, no supplementary group, private home and direct sudo denial. Store raw command output and host /etc/passwd + /etc/group snapshot hash.
- **Stop / Owner:** Any reused name, shared UID/GID, unexpected group, unlocked account or sudo success is FAIL. Owner records and adopts the principal-to-UID mapping before Profile 1.1 is accepted.

### B. Candidate / Author / Reviewer / Approver protected-file denial

- **Precondition / actor:** Fresh real nonprivileged account processes, not mocked UID checks. Root runs each probe under the named UID with groups cleared.
- **Command:** For each role, use **sudo -u ROLE -- /usr/bin/stat "$TRUST_ROOT/operation-index.json"** and a Python **os.open(path, O_WRONLY|O_APPEND)** probe. Record errno; do not count unrelated command errors as denial.
- **Expected / evidence:** Candidate, Author, Reviewer and Approver receive EACCES for both Index read and append, and cannot traverse the protected root. Record actual real/effective IDs and syscall result.
- **Stop / Owner:** Any readable/writable result, unexpected group/descriptor or failure reason other than permission denial is FAIL. Owner accepts the permission matrix and target logs through the existing adoption procedure.

### C. Protected Repository, ACL and path verification

- **Precondition / actor:** Root read-only audit before activating the fixed launcher.
- **Command:** Run the stat/getfacl/find commands in §6.3, plus **namei -l "$TRUST_ROOT/operation-index.json"** and **findmnt -T "$TRUST_ROOT"**.
- **Expected / evidence:** Trust files are Operator-owned/private; installed code/runtime root-owned/read-only; no named/default ACL, nested mount, symlink, hardlink, special file, group/world writable ancestor, path alias or candidate-owned component.
- **Stop / Owner:** Any mismatch, mutable parent, unexpected mount or ACL is FAIL. Preserve complete output and filesystem/mount identity for Owner.

### D. Controller, schema and dependency SHA verification

- **Precondition / actor:** Independent build verifier and Operator; exact Owner-pinned Build Inventory already in Trust Root.
- **Command:** Run the §6.4 bootstrap probe with the Build Inventory hash delivered outside Candidate data. Recalculate the Build Inventory file SHA, controller/scripts tree, schemas tree, interpreter, site-packages tree and all components independently.
- **Expected / evidence:** Bootstrap exits 0; independent SHA manifest has zero mismatches; all loaded modules originate at the installed root and package paths equal the Inventory.
- **Stop / Owner:** Any omitted transitive module, schema, dependency, mutable byte, path drift, unknown Python patch or mismatch is FAIL. Owner signs exact Build Inventory SHA and runtime lock/wheelhouse digests.

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

### Before any activation

- Use a maintenance window; stop/disable the independently audited service; verify no Operator writer is active and no lock is held.
- Verify an external backup by hash and restore it into a disposable directory before touching the new generation.
- Provision only fresh versioned trust/controller/runtime paths. Keep the old trust generation and exact Anchor checkout read-only.
- Do not switch service state until every pre-activation check and Owner decision is complete. Activation must use a root-owned fixed launcher and root-controlled generation pointer, not user environment or command arguments.

### Failure before activation

- Keep service disabled.
- Retain exact stdout/stderr, host identity and partial tree stat/ACL snapshots.
- With no process using the generation, move the whole fresh generation directory to a root-only quarantine directory on the same filesystem. Example commands, executed as root after verifying the unit is stopped:

~~~bash
set -euo pipefail
: "$OWNER_APPROVED_SERVICE_UNIT"
: "$GEN_ROOT"
: "$GENERATION_ID"
sudo systemctl disable --now "$OWNER_APPROVED_SERVICE_UNIT"
if sudo systemctl is-active --quiet "$OWNER_APPROVED_SERVICE_UNIT"; then exit 1; fi
QUARANTINE_ROOT=/var/lib/rq03f/quarantine
sudo install -d -o root -g root -m 0700 "$QUARANTINE_ROOT"
test "$(stat -c %d "$GEN_ROOT")" = "$(stat -c %d "$QUARANTINE_ROOT")"
test ! -e "$QUARANTINE_ROOT/$GENERATION_ID"
sudo mv -T -- "$GEN_ROOT" "$QUARANTINE_ROOT/$GENERATION_ID"
~~~

The service-unit variable must come from the Owner-controlled deployment manifest, never Candidate input. The repository currently supplies no such unit, so this command is a required interface for the future integration and will fail closed until that unit exists. Do not attempt to repair a half-provisioned tree in place; the shell tool is not transactional.
- Restart from a new generation ID and fresh paths after root-cause correction. Prior trust bytes are not changed by this method.

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

- Added this deployment-readiness report only; no production code, schemas, scripts, workflow or fixture changed.
- Independent byte checks confirmed all 17 frozen Content SHA entries and the supplied Golden Corpus, Blind Holdout and Original NC-02 digests.
- No production tests were run because no production code changed; report formatting and patch whitespace are checked on the final commit.
- No independent target-host deployment command was run.
- No profile/index migration, trust anchor append, service installation/activation, Intake or qualification operation was performed.
- The exact final Git HEAD and fresh exact-head PR CI are reported in the Owner handoff and verified from GitHub metadata after the documentation commit is pushed.
