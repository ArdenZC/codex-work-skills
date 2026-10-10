# RQ-03F-B3 — Hosted Operator Isolation Qualification

## 结论与适用范围

**Hosted Linux OS boundary：PASS。Production Operator Trust：未建立。**

本报告记录在 GitHub-hosted `ubuntu-24.04` 临时 Runner 上，以真实 Linux UID、DAC、ACL 和进程权限完成的 B3 测试。它仅证明本 PR 的临时合成部署在该 Runner 上表现符合所测边界。Workflow、provisioning 脚本和测试脚本均来自待审查 PR，且临时 Runner 提供 sudo；因此这些测试不是独立 Owner 部署，也不构成正式 Trust Evidence。

未启动 Agent A/B、未执行 Live Reviewer Qualification、未写入正式 Trust Anchor、未激活 Production Trust、未 merge/release、未启动 RC-02，也未发布 Lesson Skill 2.4。所有临时账号、安装目录、TrustContext、launcher 和合成证据均在 job 结束前清理。

## 基线与交付

| 项目 | 精确值 |
|---|---|
| Trusted `origin/master` | `91389936551b5a6b1b2ac24db09ee2c215146fb6` |
| B2 PR | [#57（MERGED）](https://github.com/ArdenZC/codex-work-skills/pull/57) |
| B2 PR HEAD | `9000157ab11b2115a27d5ae2afd74f2375588e62` |
| B2 CI | `38031076347`, `38033020969` — SUCCESS |
| B2 post-merge master CI | `38044562972` — SUCCESS |
| Formal Trust Anchor | `eb4a95c618e05c5ad6413137478bc65dbca75ec9` |
| B3 Draft PR | [#58](https://github.com/ArdenZC/codex-work-skills/pull/58) |
| B3 code-under-test HEAD | `64fbe60c5f4f89a4044d8ce7b79c01ef387c6e55` |

`origin/master` was fetched before testing and still matched the supplied trusted master. The external Trust Anchor checkout remained at the supplied commit and clean. Its Authority Profile SHA-256 is `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4`; Initial Operation Index SHA-256 is `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`. Neither was modified.

The exact final PR HEAD is the SHA shown by the post-report exact-HEAD CI linked in §8 and by PR #58. The hosted run before the report-only commit tested code HEAD `64fbe60c5f4f89a4044d8ce7b79c01ef387c6e55`.

Files in this single PR:

- `.github/workflows/rq03f-b3-hosted-operator-isolation.yml` — isolated hosted Linux workflow.
- `tools/rq03f_operator_boundary.sh` — Option B account creation and protected-path provisioning.
- `tools/rq03f_b3_hosted_isolation.py` — disposable hosted test orchestration and assertions.
- `tools/rq03f_b3_hosted_operator_probe.py` — synthetic-only protected intake probe.
- `RQ03F_B3_HOSTED_OPERATOR_ISOLATION.md` — this report.

No frozen corpus, holdout, NC-02, golden labels, trust files, Lesson Skill version, or existing CI matrix was changed.

## Frozen material verification

The exact protected inputs still match their required SHA-256 values:

| Material | SHA-256 | Result |
|---|---|---|
| Golden Corpus | `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a` | PASS |
| Blind Holdout | `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a` | PASS |
| Original NC-02 | `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` | PASS |

Every one of the 17 frozen Content files was rehashed from its raw bytes against the existing fixture manifest; all 17 matched. Their identities and hashes are listed below. N01 is the original NC-02 source.

| Case | Raw Content file | SHA-256 |
|---|---|---|
| N01 | `tests/fixtures/lesson-original-nc02.json` | `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` |
| N02 | `tests/fixtures/semantic-scope/N02/content.json` | `1151b44b2be3e43530f7ca47178aa92d30366e96673c10fc68deb2c7375916a7` |
| N03 | `tests/fixtures/semantic-scope/N03/content.json` | `e02c519ebb837790760bd76b62667605a7c2916c7f561ba4ec120c195e0331e2` |
| N04 | `tests/fixtures/semantic-scope/N04/content.json` | `47094b26a926afc0ae2761109f1814a00f7ceb0bb222684a8ba6e93b266f597c` |
| N05 | `tests/fixtures/semantic-scope/N05/content.json` | `57a6efee6021248ded80d831564f5287c1315231cc08759e9f9d6ab223a3e2a1` |
| N06 | `tests/fixtures/semantic-scope/N06/content.json` | `f491c68aeda4bdfa5430ab5c024327da181726fcfd1e835eeafa8ca813dc218b` |
| P07 | `tests/fixtures/semantic-scope/P07/content.json` | `6b21514f15c4e0b287f3a999dd475604b7d0f1f94f7d3b669433adf952be7fa3` |
| P08 | `tests/fixtures/semantic-scope/P08/content.json` | `be75ec999322fc7985dcbd6cb7692d2bbe3bac0499e27fd5bc8cf879a260e867` |
| P09 | `tests/fixtures/semantic-scope/P09/content.json` | `9da74d20e240e77ec207ca6a5fadc539c409dbaac16bf6d99f6cdd9ee02583a5` |
| P10 | `tests/fixtures/semantic-scope/P10/content.json` | `dd6e94df2a37c3fbfe0f29c873496e272498ab4c67ec557ae62c1591e26eb5ae` |
| P11 | `tests/fixtures/semantic-scope/P11/content.json` | `769d72f7adbae5e617ac2c9a2a504b658a142d40304d535ef04d34766e8f6512` |
| P12 | `tests/fixtures/semantic-scope/P12/content.json` | `06ca333e97f9ad40e44d9e7b13a5dfa9b31d44986da43209d503fe1145738a2c` |
| A13 | `tests/fixtures/semantic-scope/A13/content.json` | `6438cdd391f5a2482e62b3be5e821daa860b09664aa0fb1b0f149d5e4786ab92` |
| P14 | `tests/fixtures/semantic-scope/P14/content.json` | `c2163bbbd0d0d3f7cf65275185cda051a488c872fb2e3a8b798e05e135008000` |
| H01 | `tests/fixtures/semantic-scope/H01/content.json` | `4cc354b058a6a0dc79eeff0907863594030eddbb2c50e294e3a8db6a444b8924` |
| H02 | `tests/fixtures/semantic-scope/H02/content.json` | `f31c794c2f624f5e8cc7154f30fb3dcb69ec25378e94bd92c55b3fba5c159d41` |
| H03 | `tests/fixtures/semantic-scope/H03/content.json` | `85f75c14e687737fc95e5cec89f5ad67c5e977d49e6d4112dc0f2d3bead7b113` |

The fresh intake test bound all 17 Content records to the unchanged Golden Corpus and Blind Holdout hashes. The synthetic probe emitted no holdout truth or golden labels.

## Hosted environment, phases, and process identities

The dedicated workflow used a fresh GitHub-hosted `ubuntu-24.04` runner and Python `3.11.17`. It checked out the exact PR head with `persist-credentials: false`; workflow permissions were `contents: read`. No secrets or persistent credentials were provided. The existing Template Package CI remains enabled and retains its Windows/macOS matrices.

The workflow separates three phases:

1. **Privileged provisioning:** the normal GitHub runner user invokes short `sudo` commands to create five new system accounts, install a root-owned controller/runtime copy, and stage synthetic trust data. This is temporary runner root, not an external Owner identity.
2. **Operator-only operation:** controller capture runs under the real `rq03f-operator` UID with the pinned synthetic Profile 1.1, Index 1.1, Controller Build Inventory 1.1, fixed launcher, and isolated Python bootstrap.
3. **Non-privileged adversarial probes:** Candidate, Author, Reviewer, and Approver run in separate real UIDs with cleared supplementary groups, clean environments, `no_new_privs`, zero capability bounding/effective sets, and closed inherited file descriptors.

Role UID/GID values are those recorded by the successful job (UIDs are runner-assigned and intentionally not hard-coded):

| Role | UID:GID | Home | Shell | Sudo probe |
|---|---:|---|---|---|
| Operator | `999:987` | `/var/lib/rq03f-operator`, mode `0700` | `/usr/sbin/nologin` | exit `1`, denied |
| Candidate | `997:986` | `/var/lib/rq03f-candidate`, mode `0700` | `/usr/sbin/nologin` | exit `1`, denied |
| Author | `995:985` | `/var/lib/rq03f-author`, mode `0700` | `/usr/sbin/nologin` | exit `1`, denied |
| Reviewer | `994:984` | `/var/lib/rq03f-reviewer-a`, mode `0700` | `/usr/sbin/nologin` | exit `1`, denied |
| Approver | `993:983` | `/var/lib/rq03f-approver-b`, mode `0700` | `/usr/sbin/nologin` | exit `1`, denied |

The provisioning log confirms distinct UID/GID pairs, locked accounts, no supplementary groups, and the absence of direct sudo grants. Each test process printed and asserted real/effective UID equality, non-root identity, empty groups, `NoNewPrivs=1`, `CapEff=0`, `CapBnd=0`, and absence of inherited descriptors targeting the protected TrustContext. `subprocess` calls close inherited descriptors. The root provisioning phase is explicitly recorded as UID 0.

## Effective filesystem boundary

Temporary layout:

```text
/var/lib/rq03f-operator/                    Operator home, 0700
└── rq03f-b3-data/                          root:root 0755, under private Operator home
    └── operator/                           operator:operator 0700
        └── trust/                           operator:operator 0700
            ├── authority-profile.json       operator:operator 0600
            ├── operation-index.json         operator:operator 0600
            └── b3-context.json              operator:operator 0600
/var/lib/rq03f-b3-install/                   root:root 0755
├── controller/                              root:root 0555; directories 0555, files 0444
└── runtime/                                 root:root 0555; executable files 0555, others 0444
/usr/local/sbin/rq03f-b3-operator-launch     root:root 0555, fixed arguments, accepts no caller args
```

The runner log includes `stat` and recursive `getfacl` captures before and after provisioning. Effective Trust ACLs contain only owner entries (`group::---`, `other::---` for protected data); named/default ACLs are rejected. Candidate cannot traverse the Operator home. The controller and Python runtime are root-owned and read/execute-only, outside the checkout. The trust root and Index are Operator-owned and private; non-Operator roles cannot read the Profile, Index, Build Inventory, or launch TrustContext.

## Hosted result by required scenario

The exact run is [GitHub Actions run 38048852787](https://github.com/ArdenZC/codex-work-skills/actions/runs/38048852787), job `114203744227`. It ran 78 deterministic intake/semantic contract tests and emitted 146 structured `B3_TEST` records. All 146 records were `PASS`, with no harness failures. Each structured log record contains the command argv, actual UID/role, exit code, expected result, stdout/stderr excerpt, and assertion result. The job log is the per-invocation evidence for the rows below.

| ID | Test and actual process | Observed exit/result | Evidence |
|---|---|---|---|
| A | Operator UID/EUID `999`; reads synthetic Profile, Index, Build Inventory using `/usr/bin/python3` | `0`, PASS; printed matching synthetic file SHA-256 values | [run log](https://github.com/ArdenZC/codex-work-skills/actions/runs/38048852787) |
| B | Operator UID `999`; fixed root-owned launcher starts pinned bootstrap and performs protected custody intake | `0`, PASS; actual Index 1.1 append and protected intake artifact | same run log |
| C–E | Candidate `997`, Author `995`, Reviewer `994`, Approver `993`; direct read, append, create, controller write and runtime replacement attempts | Denied operations exit `1`, PASS for all four principals; no direct sudo | same run log |
| D/F | Candidate `997`; symlink read, hardlink creation, Index replace/unlink, path traversal, trust-directory rename, protected subdirectory creation | exit `1`, PASS; kernel permission denial | same run log |
| F | Root provisioner UID `0`; preflight hardlink, controller symlink, and symlinked trust-root fixtures | each refused with exit `1`, PASS; pre/post Profile and Index bytes unchanged | same run log |
| G | Candidate `997`; self-created Profile/Index/Build files; caller-selected launcher args and direct bootstrap with Candidate Build file | launcher exit `64`, bootstrap exit `2`, PASS; pinned Inventory SHA mismatch | same run log |
| H | Candidate `997` creates hostile `semantic_scope_records.py` and `jsonschema.py`; Operator `999` runs with hostile `PYTHONPATH` under `-I -S -B` | capture exit `0`; poison marker absent, PASS; loaded modules resolve inside root-owned installed scripts | same run log |
| I | Candidate `997`; invokes fixed launcher without Operator UID or readable private TrustContext | exit `2`, PASS; failed closed on `EACCES` at protected Operator data path | same run log |
| J | Operator `999`; old TrustContext after synthetic policy epoch rotation, then after synthetic role revocation | each rejected with exit `2`, PASS; reasons were stale policy epoch and revoked role; original Index bytes restored/preserved | same run log |
| K | Operator `999`; two normal synthetic qualification-only Intakes and one winning concurrent Intake | each committed operation exited `0`; `authors[]` remained empty; Intake says `historical_author_claim=not_made` | same run log |
| L | 78 deterministic contract tests, including production/Teacher rejection, candidate evidence rejection, authority revocation, and fail-closed cases | `Ran 78 tests … OK`; PASS | same run log |

For every protected read/write denial, the command ran as the named real role UID, not a mocked UID. A separate direct sudo probe ran without `no_new_privs` masking the result and returned exit `1` for all five role accounts. The Candidate cannot substitute arguments into the launcher; its only interface is a fixed executable with no caller-provided Profile, Index, Build Inventory, or TrustContext path.

### Operator positive write and append-only evidence

The synthetic Operator used the B2 `capture_qualification_corpus_intake` route through the fixed launcher. One structured successful capture recorded real/effective UID `999`, principal `owner-controller:qualification-corpus-custodian` from the **synthetic-only** Profile, 17 frozen cases, the required Golden/Holdout/NC-02 hashes, no historical-author claim, and zero author rows before/after. A second fresh-context capture succeeded. Two concurrent Operator processes were released from a barrier with stale Index snapshots: one exited `0` and appended exactly one row; the other exited `2` with `changed raw-byte binding: operation_index`. The final synthetic Index SHA-256 was `7301b9b92e7b0dfc76f1fcb9e3c8fc3466c9d92702aac2c1cae596baab8a1f2f` and contained 3 qualification intake rows, 0 authors, 0 receipts, 0 adjudications, and 0 qualification runs.

This demonstrates the tested append path and stale-snapshot refusal on the temporary Linux filesystem. It does not make any synthetic intake, Operation ID, principal, profile, index, or receipt an adopted or protected Owner record. No Reviewer Qualification, independent approval, three-repetition result, or production authorization was created.

## Controller Build, import path, and hash pins

The harness copied scripts and schemas out of the checkout into `/var/lib/rq03f-b3-install/controller`, copied a Python 3.11 runtime into `/var/lib/rq03f-b3-install/runtime`, and constructed synthetic Build Inventory 1.1 after that copy. In this run:

- synthetic Profile SHA-256: `8a75692b870bd995b4638de3ce6f8f503363b526ae0ba92ac9f9c84a0fd06d11`;
- initial synthetic Index SHA-256: `9fba9b7b62e21c67e43ff29518c3adcff0f89d6f443cd4348b742c57efaaf92a`;
- synthetic Build Inventory SHA-256: `38d3209a81e03089868d84dad228f172551b32b33fd95752d1532b4654474e8e`.

These are ephemeral test pins, not formal Owner pins. Build Inventory 1.1 verifies the isolated interpreter and version, executable hash, pinned site-packages tree, required controller modules and schemas, dependency packages/modules, and controller/schema trees before importing non-stdlib code. The checked controller closure includes `lifecycle_digest`, `source_truth`, `semantic_scope_records`, `semantic_scope_review`, `operation_provenance`, `reviewer_qualification`, `qualification_corpus_intake`, `operator_controller_bootstrap`, `exemplar_contract`, `exemplar_split`, and `path_safety`; dependencies are pinned from the copied site-packages tree. The bootstrap narrows `sys.path`, starts with `-I -S -B`, and verifies each component against the externally pinned Inventory digest.

Evidence includes: a wrong Build Pin rejected for Operator UID `999` with exit `2`; a Candidate-selected Build Inventory rejected with exit `2`; hostile `PYTHONPATH` module shadows did not run; and the probe reported `semantic_scope_records`, `qualification_corpus_intake`, `operator_controller_bootstrap`, and `lifecycle_digest` loaded from the protected installed scripts path. Synthetic Build/Profile/Index pin material was removed at cleanup.

## Provisioning script audit: race, rollback, and remaining limits

The reviewed shell script `tools/rq03f_operator_boundary.sh` was exercised in the disposable environment. It refuses pre-existing role names rather than reusing them; requires unique non-root UID/GID pairs, locked accounts, nologin shell, private account homes and no supplementary groups; probes direct sudo rights as each actual UID; requires absolute canonical disjoint roots outside the candidate checkout; checks path ancestors, ownership, mode, device boundaries, symlinks, hardlinks, special files, named/default ACLs, Profile/Index/Build hashes, policy epoch, role pin, and controller/runtime pin; then applies Operator-only trust ownership and root-owned immutable controller/runtime permissions and verifies the permissions and raw Profile/Index bytes again. Tests proved pre-existing-name refusal and non-mutating refusal for symlink/hardlink/path aliases.

The intake writer uses a private `O_NOFOLLOW` lock file with `flock(LOCK_EX)`, reloads TrustContext under the lock, writes the artifact with `O_EXCL|O_NOFOLLOW`, fsyncs it, writes a same-directory temporary Index, atomically replaces the Index and fsyncs the directory, then verifies the resulting hashes. Concurrent stale-snapshot testing accepted one writer and failed the stale one closed.

Two deployment limits remain for Owner review:

1. The provisioning `provision` operation is **not transactional**. It performs restrictive ACL/owner/mode changes after read-only preflight; a mid-operation error can leave a partially normalized but restrictive deployment tree. The script does not silently broaden access, but the external deployment owner must use a fresh deployment tree or prepare an offline rollback/restore procedure before provisioning.
2. Hosted tests did not race an untrusted process against root provisioning or a malicious concurrent trusted Operator against path normalization. The tested filesystem roots were not candidate-writable before provisioning, but deployment must run before enabling the Operator service and while no Operator writer is active. Intake concurrency was tested separately under the actual Operator UID.

The harness has a `finally` cleanup path and the workflow has an `if: always()` residue check. This successful job logged cleanup for all five accounts and every protected path. A crash outside the workflow cleanup window can only be mitigated by GitHub-hosted runner disposal; no reusable authorization capability is intentionally retained.

## CI evidence and iteration history

Exact code-under-test HEAD `64fbe60c5f4f89a4044d8ce7b79c01ef387c6e55`:

- [B3 Hosted Operator Isolation run 38048852787](https://github.com/ArdenZC/codex-work-skills/actions/runs/38048852787) — SUCCESS, `ubuntu-24.04`, job `114203744227`, 78 contract tests `OK`, 146 structured hosted checks PASS, cleanup step PASS.
- The post-report commit must receive fresh exact-HEAD B3 and Template Package CI before this report is accepted as complete. Their run IDs and exact HEADs are listed here once completed; the existing Windows/macOS matrix is not disabled or filtered out by this PR.

Provisioning/harness failures during development were not counted as passes. The observed defects and changes were:

| Run | Failure observed | Correction |
|---|---|---|
| `38046976294` | `sudo -l -U` exit status gave a false positive for grants | Replaced with a real-UID `/usr/bin/sudo -n true` probe using `setpriv` |
| `38047421720` | Python 3.11 `Path.chown` unavailable | Use portable `os.chown` |
| `38047621219` | Strict preflight correctly rejected writable `/opt` ancestor | Stage installation under fresh root-owned `/var/lib/rq03f-b3-install` |
| `38047830150` | A copied wheel file had group/world write bits | Root provisioning uses restrictive umask and removes write bits from the temporary runtime before pinning; validation was not relaxed |
| `38048208060` | Operator could not traverse root-created trust parent | Make the synthetic `operator/` directory Operator-owned/private |
| `38048378977` | Synthetic data root inherited mode `0700`, blocking Operator traversal | Explicitly create root-owned `0755` data root below Operator's `0700` home; strict preflight retained |

For each failed run, the harness/provisioner failed closed and cleanup ran; the next code revision re-ran exact-head CI. The final successful run is separate and linked above.

## Hosted trust boundary and outstanding Production Trust prerequisites

GitHub-hosted evidence is controlled by the PR branch: the workflow, test script, and root-invoked provisioning script all come from the branch under review. The runner has temporary sudo. `contents: read`, `persist-credentials: false`, and absence of secrets limit exposure, but they do not make the execution independent. A malicious PR could change its own checks or use its temporary runner privilege; therefore the Owner must review the workflow and scripts and treat the run only as hosted behavior evidence.

This hosted run demonstrates actual Linux kernel enforcement between distinct ephemeral UIDs, private trust storage, read-only installed code/runtime, UID-level sudo denial, import-path isolation, refusal of build-pin substitution, and cleanup on the successful path. It does not prove a durable external host, separate human/operator custody, independent authorization, or production operation.

Before Production Trust can be established, an independent deployment owner still needs to:

- provision and verify real, independently managed OS identities on the target host;
- materialize Owner-approved Profile 1.1, Index 1.1, TrustContext, Build Inventory pin, and authority/revocation process from the formal Trust Anchor without using this hosted synthetic material;
- install reviewed controller/schema/runtime bytes outside the Candidate checkout and recalculate/approve their hashes independently;
- establish and document the protected repository owner, mode/ACL boundary, backup and offline rollback plan, maintenance window, and service activation controls;
- inspect exact commands and logs from the deployment host and independently accept the OS separation, operator custody, revocation, and lifecycle procedures.

### Entry decision for the next Owner step

**Ready for Owner review as a hosted OS-isolation qualification and as input to an independent deployment-owner acceptance.** This is not completion of that independent deployment acceptance. `PRODUCTION_OPERATOR_TRUST_ESTABLISHED` remains false, and B3 creates no production-authorized evidence.

## Exact final report HEAD and post-report CI

The implementation code tested above is pinned to `64fbe60c5f4f89a4044d8ce7b79c01ef387c6e55`. This report is added as a documentation-only commit on the same Draft PR. The handoff records the exact final PR HEAD and the fresh post-report B3 and Template Package CI run IDs. Acceptance requires both workflows to report that same final PR HEAD; the B3 job must pass and the retained Template Package CI gates must complete successfully. GitHub run metadata is the source of exact report-commit SHA/run binding. No statement here upgrades hosted test data to formal Trust Evidence.
