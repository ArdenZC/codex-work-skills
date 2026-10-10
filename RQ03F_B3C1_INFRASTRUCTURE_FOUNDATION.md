# RQ-03F-B3-C1 — Production Operator Infrastructure Foundation

## Owner Review 5480118486 remediation status

This addendum records the required changes on the existing Draft PR #60. Code commit `0fa07c65b930fbee16144a4f24dceac3298858b2` is the implementation/test head before this report update. The exact report commit SHA is the current PR head; it is also returned in the completion response and GitHub PR checks.

### Allocation terminal-state fix

`operator_allocator.allocate` now treats `.rq03f-allocation-record.json` with `allocation_status="complete"` as prepared data. It first fsyncs the target and parent directories, reopens and checks the pinned parent identity, and rechecks the target identity through the reopened parent. Only then does it exclusively create `.rq03f-allocation-finalized.json`, binding the exact allocation-record SHA, allocation-plan SHA, target ID, and target device/inode/UID/GID/mode. Any exception keeps the already-created target and record, adds an exclusive `.rq03f-incomplete.json` failure tombstone when possible, and never reuses the target ID.

The builder, all locked-install entry points, and the independent stdlib verifier now require the canonical finalization receipt and reject any incomplete marker. The builder and verifier also recheck terminal allocation state before returning candidate output. A matching SHA for a complete record is insufficient when an incomplete marker exists; a complete record without a finalization receipt is unfinalized and rejected. Neither failure markers nor target directories are removed or overwritten.

### Added deterministic coverage

- `test_parent_fsync_failure_after_complete_record_is_rejected_by_every_consumer`: injects a parent-directory fsync error after the complete record exists, verifies the record remains complete with its exact SHA, confirms the incomplete marker exists and finalization is absent, and confirms Builder, Installer, and Verifier all refuse it. Reallocation of the target ID is refused.
- `test_final_parent_identity_failure_after_complete_record_is_rejected_by_every_consumer`: injects failure at the reopened-parent identity check after the complete record write and asserts the same downstream refusal and no-reuse behavior.
- `test_complete_record_without_failure_marker_or_finalizer_is_rejected`: removes only the success finalization receipt in an isolated synthetic fixture and confirms all consumers reject the otherwise correctly SHA-pinned complete record as unfinalized.
- Positive allocation asserts the finalized receipt binds the exact complete-record SHA.

### Required Template CI investigation

The previous Template Package run [38070998888](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070998888) did eventually schedule jobs after the initial zero-job queued period. Its Windows and macOS `semantic-scope-1` jobs failed at the existing full-manifest coverage assertion before running their semantic partition: both reported `manifest=982`, `discovered=1004`. The 22-test difference was the C1 test module added in this PR but absent from `run_test_shards.py`'s full manifest. This is a C1 CI coverage regression, not an infrastructure-only failure.

The fix adds the C1 module as an explicit Linux-only suite in the full manifest and gives it an explicit non-Linux refusal path. The existing six semantic partitions and their Windows/macOS matrix are unchanged. On the implementation head, local manifest verification reports 1,006 full-suite tests plus the two release-scale tests, matching 1,008 discovered root tests. `test_c1_operator_tests_are_explicitly_covered_by_linux_full_manifest`, `test_full_manifest_matches_root_discovery`, and `test_semantic_scope_top_level_partitions_are_exact` all pass.

The earlier zero-job observations were investigated against workflow/run APIs. `38070998888` was a `pull_request` run in `queued` state with no jobs at the review snapshot, then acquired a queued `Classify changes` job and later 40 jobs. The later zero-job cancellation `38070879497` has conclusion `cancelled`, but GitHub returned no cancellation reason. The workflow defines a PR-head concurrency group with `cancel-in-progress: true`; that policy is a possible interaction, not proven as the cause of either observation. The API approval endpoint for the remediation run returned an empty list. No evidence identifies whether queue delay, event processing, or concurrency caused the earlier no-job interval, so the report does not assign a root cause.

### Current verification and CI state

- Deterministic C1 suite on the implementation head: 25 tests run, 24 passed, one real-ACL test skipped locally because it runs in the disposable hosted Linux job.
- Local manifest/semantic coverage checks: 3/3 passed; `run_test_shards.py --list` passed; `py_compile` and `git diff --check` passed.
- Running the full local `tests.test_run_test_shards` module produced 28 passes and one Gradebook validator failure. The validator reported `Named-range template changed protected workbook structure or formatting` while the workbook SHA matched. No Gradebook code or template is changed in this remediation, and no root cause is assigned from this local observation. The fresh GitHub run is the authoritative matrix evidence.
- Exact implementation-head hosted real-UID run [38072762678](https://github.com/ArdenZC/codex-work-skills/actions/runs/38072762678) completed SUCCESS on commit `0fa07c65b930fbee16144a4f24dceac3298858b2`: all 25 C1 tests passed under Operator UID 4601, including the real ACL case, late-failure injections, consumer rejection, exclusive creation, runtime drift, and cleanup. Candidate/Author/Reviewer/Approver UIDs 4602–4605 were separately exercised; the artifact is [11676754907](https://github.com/ArdenZC/codex-work-skills/actions/runs/38072762678/artifacts/11676754907), SHA-256 `9f3f69c2c7f4395217729980ba961a69569b4cb5cceb47619ba6f6187eb02fff`.
- Exact implementation-head Template Package run [38072762647](https://github.com/ArdenZC/codex-work-skills/actions/runs/38072762647) remained `PENDING` with zero jobs at `2026-10-10T17:48:24Z`. The GitHub Actions workflow is `active`; the run and its Check Suite are `pending`; the Check Suite reports `latest_check_runs_count=0`; the jobs endpoint returns `total_count=0`; and the run approval endpoint returns `[]`. Thus GitHub accepted the pull-request event and created a Check Suite but had not created any job at that observation. The prior-head run [38070998888](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070998888) remained overall `queued` while its jobs endpoint listed 40 jobs; its Windows and macOS `semantic-scope-1` jobs failed on the already-described `manifest=982`, `discovered=1004` guard. The checked-in workflow uses a PR-head concurrency group with `cancel-in-progress: true`, but the available API evidence does not establish whether concurrency, queue capacity, event processing, or another scheduler condition caused the current exact-head run to remain jobless. No root cause is assigned.
- The full 12-job Windows/macOS semantic-scope matrix and CI Gate have not passed on the remediation head. The report commit will trigger another exact-head Template Package run; the final response will identify that run and its result. A pending or zero-job run is not a pass.
- Recomputed all 85 SHA rows in `tests/fixtures/semantic-scope/fixture-files.json`; all match. The 17 `.content` entries cover N01–N06, P07–P12, A13, P14, and H01–H03. Golden corpus `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a`, Blind Holdout `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a`, and Original NC-02 `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` match their frozen byte hashes. These source paths are unchanged from trusted master.
- The external Trust Anchor checkout remains at `eb4a95c618e05c5ad6413137478bc65dbca75ec9`, clean; Profile SHA-256 `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4`, Index SHA-256 `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`.
- No formal Trust Anchor, frozen case, Golden Truth, Blind Holdout, Original NC-02, or production authorization was modified. Production Trust remains unestablished; this work does not authorize deployment or qualification.

### Remediation files

- `tools/rq03f_c1/operator_allocator.py`
- `tools/rq03f_c1/build_inventory.py`
- `tools/rq03f_c1/locked_install.py`
- `tools/rq03f_c1/verify_inventory.py`
- `tests/test_rq03f_c1_operator_infrastructure.py`
- `.github/scripts/run_test_shards.py`
- `tests/test_run_test_shards.py`
- `RQ03F_B3C1_INFRASTRUCTURE_FOUNDATION.md`

## Original C1 review status and scope (historical baseline)

This section records the evidence before Owner Review 5480118486. The remediation addendum above is authoritative for the current code, tests, and CI state.

This PR implements the C1-A exclusive candidate Archive/Generation allocator and the C1-B candidate Runtime/Controller Build Inventory toolchain. All locally generated records and fixtures are synthetic. Nothing in this change grants production authority or changes the RQ-03F qualification state.

PR: [#60](https://github.com/ArdenZC/codex-work-skills/pull/60), Draft, open. The implementation and test head is `ae88376e3921534be1ba97316b9024e758c0d94e`. The report is committed after that tested implementation; the final report commit SHA and its fresh exact-head CI are available from the PR head and Checks view. No code changes are planned after the final exact-head CI.

## 1. Trusted baseline and immutable evidence

- Starting `origin/master`: `908959367e1361d9194d1ac412eb9a7fd0d53c02`. A fresh fetch during this work returned the same SHA; no reconciliation was needed.
- B3-B PR #59 is merged. Its final head was `1c646df68dc2d15371707dbc9da1b23672d7d6b0`.
- PR #59 exact-head CI run [38062867801](https://github.com/ArdenZC/codex-work-skills/actions/runs/38062867801) succeeded.
- Post-merge CI run [38066462029](https://github.com/ArdenZC/codex-work-skills/actions/runs/38066462029) completed with 30/30 jobs successful, including existing Windows/macOS semantic scope and lesson/gradebook lanes.
- Formal Trust Anchor checkout remains at `eb4a95c618e05c5ad6413137478bc65dbca75ec9`, clean. `authority-profile.json` SHA-256 is `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4`; `operation-index.json` SHA-256 is `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`.
- Golden corpus SHA-256 is `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a`; blind holdout SHA-256 is `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a`; Original NC-02 SHA-256 is `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`.
- Recomputed raw Content bytes for all 17 entries in `fixture-files.json` match the frozen manifest. No trust material, fixture, label, frozen corpus, or production authorization/schema file changed from the starting master.

| Case | Content SHA-256 | Case | Content SHA-256 |
|---|---|---|---|
| N01 / Original NC-02 | `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` | N02 | `1151b44b2be3e43530f7ca47178aa92d30366e96673c10fc68deb2c7375916a7` |
| N03 | `e02c519ebb837790760bd76b62667605a7c2916c7f561ba4ec120c195e0331e2` | N04 | `47094b26a926afc0ae2761109f1814a00f7ceb0bb222684a8ba6e93b266f597c` |
| N05 | `57a6efee6021248ded80d831564f5287c1315231cc08759e9f9d6ab223a3e2a1` | N06 | `f491c68aeda4bdfa5430ab5c024327da181726fcfd1e835eeafa8ca813dc218b` |
| P07 | `6b21514f15c4e0b287f3a999dd475604b7d0f1f94f7d3b669433adf952be7fa3` | P08 | `be75ec999322fc7985dcbd6cb7692d2bbe3bac0499e27fd5bc8cf879a260e867` |
| P09 | `9da74d20e240e77ec207ca6a5fadc539c409dbaac16bf6d99f6cdd9ee02583a5` | P10 | `dd6e94df2a37c3fbfe0f29c873496e272498ab4c67ec557ae62c1591e26eb5ae` |
| P11 | `769d72f7adbae5e617ac2c9a2a504b658a142d40304d535ef04d34766e8f6512` | P12 | `06ca333e97f9ad40e44d9e7b13a5dfa9b31d44986da43209d503fe1145738a2c` |
| A13 | `6438cdd391f5a2482e62b3be5e821daa860b09664aa0fb1b0f149d5e4786ab92` | P14 | `c2163bbbd0d0d3f7cf65275185cda051a488c872fb2e3a8b798e05e135008000` |
| H01 | `4cc354b058a6a0dc79eeff0907863594030eddbb2c50e294e3a8db6a444b8924` | H02 | `f31c794c2f624f5e8cc7154f30fb3dcb69ec25378e94bd92c55b3fba5c159d41` |
| H03 | `85f75c14e687737fc95e5cec89f5ad67c5e977d49e6d4112dc0f2d3bead7b113` |  |  |

## 2. C1-A — exclusive candidate allocation

`tools/rq03f_c1/operator_allocator.py` implements Linux-only `allocate` for a new `generation` or `legacy_archive`. Its closed versioned input is `rq03f-exclusive-allocation-plan-1.0`; the caller must provide the plan path and an independently delivered expected plan SHA-256. The plan names an exact non-root Operator UID/GID, canonical protected Trust root, canonical trusted parent and its device/inode/mount ID, operation scope, target ID, source checkout/commit, and (for an archive) the two exact source SHA values.

The allocator checks the current real/effective UID and GID, rejects supplementary groups, walks each directory with dirfd + `O_NOFOLLOW`, checks owner/mode/ACLs and canonical `/proc/self/fd` identity, pins the destination parent's device/inode/mount ID, and rejects any destination path that overlaps the protected Trust root. It uses `mkdirat` semantics and `O_EXCL` for a one-time target and every output file, then fsyncs file and directory data and rechecks the parent path identity. A preexisting directory, file, or dangling symlink is never opened or reused.

For `legacy_archive`, the source checkout must be clean and at its exact pinned Git commit. Both source files are opened without following links, rejected if hard-linked, hashed before any destination is created, copied into a new target with exclusive creation, and verified from the copied bytes. A partial failure leaves an explicit `.rq03f-incomplete.json`; the target ID cannot be reused. A successful record is explicitly `candidate_allocation_only` and binds the parent, target inode, plan SHA, source commit, protected Trust root, and copied file hashes.

The plan digest is a comparison pin only. This component does not provide an Owner-authenticated configuration channel; a future fixed launcher must source the digest and plan from an independently protected location. Running the tool with Candidate-controlled plan and digest can at most create a candidate-only allocation in a path the process already controls.

## 3. C1-B — locked install and Inventory 1.1

`rq03f-build-inputs-1.0` binds an exact source commit/checkout, target platform, non-root Operator identity, an exclusive Generation record and its digest, final absolute Controller/Runtime paths, exact Python patch version, complete `==`/SHA-256 requirements lock, offline wheelhouse manifest, protected Trust root, Inventory key, and a new candidate Inventory output. The build loader rejects missing/unknown fields, paths outside the Generation layout, a changed allocation record, path overlap with Trust material, wrong host platform, mismatched identity, changed lock/wheelhouse bytes, and incomplete wheel coverage.

The locked installer creates `controller/` and `runtime/` once beneath the allocator's Generation. It copies tracked Controller script/schema Git blobs to the final absolute Controller path and freezes installed bytes read-only. Runtime creation copies the selected exact-version Python executable to the fixed final venv layout and installs only hash-locked wheels from the local wheelhouse (`--no-index`, `--only-binary`, `--require-hashes`, no cache/build isolation). It does not resolve or fetch dependencies.

The builder emits the existing Build Controller Inventory 1.1 shape without changing its production schema. It includes exact Controller scripts/schema trees, all discovered security-sensitive Controller modules, required schemas, Python executable/version/hash, site-packages root/tree hash, and installed dependency components. Its receipt is `candidate_only_not_owner_approved`. `verify_inventory.py` is stdlib-only and independently re-reads the plan, source commit, allocation record, lock/wheelhouse, final paths, Inventory bytes, Controller tree, module/schema set, Python executable/version, and every installed package byte. It does not import the builder, controller, third-party dependencies, or `PYTHONPATH` modules.

`runtime_closure.py` provides a separate versioned candidate sidecar for os-release, Python stdlib tree, final Runtime tree, package/shared-library manifests, and a caller-supplied base-image digest claim. It explicitly marks those external host claims unverified; it is not an OS image attestation and does not enlarge Build Inventory 1.1's authority.

**Production build input gate:** no independently Owner-approved production requirements lock or wheelhouse is currently available. The implementation was exercised only with a deterministic generated synthetic wheel. A production build request must stop until the actual Python patch release, locked requirements, wheelhouse manifest, all wheel SHA values, and the external plan digests are independently approved and supplied. The synthetic values in tests are not candidates for production adoption.

## 4. Original deterministic validation evidence (pre-remediation)

Command: `python3 -m unittest tests.test_rq03f_c1_operator_infrastructure -v`.

Local result: 22 tests discovered; 21 passed; one ACL test was skipped locally because it is reserved for the disposable hosted runner where a real POSIX ACL is provisioned. The test suite checks actual files/bytes, permission bits, race outcomes, hashes, and subprocess exit codes. `py_compile`, `bash -n tools/rq03f_c1/hosted_linux_isolation.sh`, and `git diff --check` also passed.

| Area | Checked behavior | Result |
|---|---|---|
| Allocation IDs / external pin | Empty/dot/path IDs, wrong plan digest, and malformed IDs fail closed | PASS |
| Exclusive Generation | New candidate is created once; record and target bytes hash correctly; second use is refused | PASS |
| Archive source | Exact synthetic Profile/Index bytes copied and rehashed; bad source SHA fails before destination creation | PASS |
| Source/path safety | Hardlink and dirty checkout rejected; group/world-writable, symlink, and dangling symlink parents rejected | PASS |
| Existing targets | Existing regular file and dangling symlink are preserved and not followed/reused | PASS |
| Protected Trust boundary | New target overlapping the protected Trust root is rejected without changing its marker bytes | PASS |
| Failure/concurrency | Partial copy leaves an incomplete marker and cannot reuse the ID; two simultaneous allocators produce exactly one winner | PASS |
| TOCTOU | Parent rename/replacement between secure open and creation is detected before a target is left at either path | PASS |
| Build / independent verify | Clean synthetic install builds a candidate Inventory, independently verifies it, and passes the legacy Bootstrap 1.1 verifier | PASS |
| Drift rejection | Controller byte, final path, Python version/executable, site-packages byte, dependency set, lock SHA, and Inventory SHA changes fail | PASS |
| Candidate input rejection | Adoption request is rejected; malicious `PYTHONPATH`/`sitecustomize` is ignored by isolated verifier | PASS |
| Runtime closure | Candidate sidecar is independently rechecked, candidate-only status retained, and existing output is never overwritten | PASS |
| Runtime symlinks | Safe file symlink digest binds raw link text and resolved target bytes; changed target bytes, dangling links, and symlink directories are rejected/detected | PASS |

## 5. Original hosted Linux real-identity evidence (pre-remediation)

The dedicated `RQ-03F-B3-C1 Operator Infrastructure` workflow uses `ubuntu-24.04`, the runner's root-owned `/usr/bin/python3.12` (mode `0755`, `pip 24.0`), the real kernel UID/GID and POSIX ACL implementation, and creates temporary unrelated accounts for Operator, Candidate, Author, Reviewer, and Approver. The job log records UIDs/GIDs `4601/4601` through `4605/4605`; each has one private primary group, no supplementary groups, zero effective capabilities, and receives only standard input/output/error descriptors through `setpriv`. The job has `contents: read`, does not persist the checkout token, uses no repository secrets, and removes all temporary accounts/directories in an unconditional cleanup step.

The workflow and root provisioning shell are part of the reviewed PR head. The hosted result therefore proves only that this exact branch-controlled harness and tested code behaved as logged on one disposable GitHub runner. It is not an independent workflow owner, a production deployment, or evidence of Owner Trust.

The latest exact implementation-head hosted run is [38070879482](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070879482), testing `ae88376e3921534be1ba97316b9024e758c0d94e`. The deterministic suite and cleanup steps completed successfully. The job logs show:

- Operator UID 4601 read the synthetic protected Profile and Index; the Operator-run deterministic suite completed successfully, including exclusive allocation and archive behavior.
- Candidate/Author/Reviewer/Approver UIDs 4602–4605 each received `EACCES` (`errno=13`) for Profile read, Index read/write/unlink/rename, and forged-file creation. The explicit Candidate allocator plan substitution exited 2 with `BLOCKED — allocator must run with the exact non-root Owner-approved Operator UID`.
- A named Reviewer ACL (`r-x`) was installed on the ACL test parent; `test_named_posix_acl_is_rejected_when_hosted_acl_path_is_supplied` passed.
- The suite ran 22 tests and all 22 passed, including the real ACL test. All temporary identities and the protected synthetic test root were removed by cleanup.
- The job uploaded evidence artifact [11676458668](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070879482/artifacts/11676458668), SHA-256 `353038ea69a102976bc7da9993a973d7a2a2f105e01a7eab7852770953a3d999`; this remains disposable test evidence, not formal Trust evidence.

Failed hosted attempts are retained as failures and each correction is recorded; none is represented as a pass:

| Run | Observed failure | Correction |
|---|---|---|
| [38070003416](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070003416) | Probe polarity treated exit 0 (“all denied”) as bypass; an Operator-side glob was expanded by the runner before it could read the protected directory. | Correct probe result handling and perform the read inside the Operator process (`ab1c788`). |
| [38070117215](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070117215) | Real UID denials and ACL setup were observed, but the harness could not execute the allocator from the checkout path as the unprivileged identity. | Follow-up run isolated the exact checkout-parent traversal failure. |
| [38070252914](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070252914) | Candidate Python reported `Permission denied` opening `tools/rq03f_c1/operator_allocator.py` from the runner checkout. | Copy the tracked allocator to a root-owned read-only location and compare source/copy SHA before execution (`fbd2500`). |
| [38070322944](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070322944) | Allocator substitution was correctly denied, then unittest import failed with `ModuleNotFoundError: No module named 'tests'` because Operator could not traverse/read the checkout. | Copy the complete tracked test source closure to root-owned read-only storage with byte-for-byte SHA checks (`a736a57`). |
| [38070495748](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070495748) | Allocator denials and ACL setup ran; build test `setUpClass` could not create `TemporaryDirectory` under the root-owned read-only code directory. | Direct build fixtures to an Operator-owned temporary root (`d487848`). |
| [38070575358](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070575358) | Allocator tests passed; build fixture correctly rejected setup-python's group/world-writable Python executable at `/opt/hostedtoolcache/Python/3.11.17/x64/bin/python3.11`. | Keep the secure permission check; use root-owned non-writable `/usr/bin/python3` and system pip (`7ea16a7`). |
| [38070683715](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070683715) | Real UID denials, ACL test, and allocator tests passed; runtime closure failed closed on Ubuntu Python 3.12's standard-library file symlink `_sysconfigdata__linux_x86_64-linux-gnu.py`. | Hash the exact symlink text plus resolved regular target bytes; continue to reject dangling/special targets and symlink directories; add deterministic regression coverage (`ae88376`). |

## 6. Original CI and changed files (pre-remediation)

On implementation/test head `ae88376e3921534be1ba97316b9024e758c0d94e`:

- Hosted C1 run [38070879482](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070879482): SUCCESS, 22/22 tests passed, cleanup and evidence upload succeeded.
- Main Template package CI [38070879497](https://github.com/ArdenZC/codex-work-skills/actions/runs/38070879497): fresh exact-head run; final matrix result is checked after the report commit.
- Final report commit also receives fresh exact-head CI. Its run links and final PR SHA are included in the PR Checks page and completion message because a report cannot contain its own Git object SHA without changing that SHA again.

No existing workflow, shard count, CI gate, production schema, or test expectation has been disabled or weakened. The PR retains the existing required repository gates and Windows/macOS matrix.

Changed files:

- `.github/workflows/rq03f-b3c1-operator-infrastructure.yml`
- `tools/rq03f_c1/__init__.py`
- `tools/rq03f_c1/operator_allocator.py`
- `tools/rq03f_c1/build_inventory.py`
- `tools/rq03f_c1/locked_install.py`
- `tools/rq03f_c1/verify_inventory.py`
- `tools/rq03f_c1/runtime_closure.py`
- `tools/rq03f_c1/hosted_linux_isolation.sh`
- `tools/rq03f_c1/schemas/exclusive-allocation-plan-v1.0.schema.json`
- `tools/rq03f_c1/schemas/build-inputs-plan-v1.0.schema.json`
- `tools/rq03f_c1/schemas/wheelhouse-manifest-v1.0.schema.json`
- `tools/rq03f_c1/schemas/operator-runtime-closure-candidate-v1.0.schema.json`
- `tests/test_rq03f_c1_operator_infrastructure.py`
- `RQ03F_B3C1_INFRASTRUCTURE_FOUNDATION.md`

Auditable commits:

1. `36f24940260d112954ab3ae9b1a62b0fc7311d24` — exclusive candidate allocator.
2. `888c5a6a3d92abab7afc58c159dcd7bd9bd8fa2c` — candidate Runtime/Inventory and deterministic suite.
3. `882bb9215b5fc91206bc007ce55b3636427b4a52` — hosted real-UID workflow.
4. `ab1c788022648ff7113b7a34e1c236aa024e65ea` — hosted probe assertion/readback correction.
5. `2cdbce589947e8878cef0449683216df9953d206` — add hosted plan-stage evidence logging.
6. `fbd25004128010a2d669016cb9e172975acaaf0d` — stage the allocator read-only for Candidate identity testing.
7. `45bfca4d155852c5d796d457f1d8ad6c93e58a55` — stage the read-only source closure for Operator tests.
8. `a736a5767599a949508124d604d38c3b4b13c2b0` — include the hosted harness in the copied test closure.
9. `d4878487b8c8bd2acc621d0890fb4ba39d1b8077` — run build fixtures in an Operator-owned temp root.
10. `7ea16a717b477629945be6a1164d5b32f9a7ce6e` — use root-owned system Python for locked runtime tests.
11. `ae88376e3921534be1ba97316b9024e758c0d94e` — hash standard-library file symlink targets and test rejection cases.

## 7. Residual risk and C2/C3 handoff

The new tools are not wired into a production launcher. They do not create an authenticated Owner configuration channel, a fixed launcher, a protected TrustContext provider, an anti-rollback/epoch ledger, systemd service identity, production service account, formal plan/Inventory approval, or production archive destination. They do not prove full OS image, libc/shared-library, kernel, or machine identity. They do not qualify a reviewer or activate a Generation. A Candidate-controlled plan and matching caller-provided digest is not authority.

The future C2/C3 integration must:

1. Deliver the allocation and build plan digests from independently protected Owner-controlled configuration, not from Candidate arguments/files.
2. Run allocator/install/build/verify only as a separately provisioned non-root Operator with one primary GID and no Candidate/Author/Reviewer/Approver group membership.
3. Pin the final absolute Generation, Controller, Runtime, Python executable, and site-packages paths before Build Inventory creation; any path or byte change requires a new candidate Inventory and fresh Owner approval.
4. Supply actual Owner-approved exact Python, hash-locked requirements, offline wheelhouse, OS package and shared-library manifests, and independently authenticated base-image digest.
5. Keep the Trust Anchor and append-only index in an independently protected repository; never interpret `candidate_allocation_only` or `candidate_only_not_owner_approved` as a production receipt or authorization.
6. Add and separately validate the fixed production launcher, TrustContext provider, service isolation, expiry/revocation, and anti-rollback controls before any live qualification.

**Not established:** Production Operator Trust, Production Trust activation, an approved production build, formal Archive/Generation adoption, Agent A/B execution, Live Reviewer Qualification, RC-02, or Lesson Skill 2.4.
