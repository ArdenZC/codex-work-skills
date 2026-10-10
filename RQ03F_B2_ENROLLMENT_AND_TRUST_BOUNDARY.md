# RQ-03F-B2 Enrollment and Protected Operator Boundary

Date: 2026-10-10 (UTC)
Status: contract implementation candidate for Owner review; no merge, release, Agent A invocation, live qualification, or Production Trust activation.

## Baseline and scope

- Trusted master: `a4bfa4155e84c55f56567af6b4bf38357e25ab3c`.
- Trust anchor: `eb4a95c618e05c5ad6413137478bc65dbca75ec9`.
- Authority Profile SHA-256: `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4`.
- Initial Protected Operation Index SHA-256: `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`.
- Frozen golden corpus SHA-256: `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a`.
- Frozen blind holdout SHA-256: `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a`.
- Original NC-02 / N01 Content SHA-256: `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`.

The accepted B1 finding remains unchanged: no protected historical author operation was found for any of the 17 cases. This branch implements a separate qualification-only custody path; it does not repair or infer original authorship.

## A. Contract and code implementation

### Version compatibility

The versions below are proposed closed extensions for Owner review, not pre-approved final schema numbers.

| Record | Existing version(s) | Proposed version | Compatibility rule |
| --- | --- | --- | --- |
| Protected Operation Index | 1.0 | 1.1 | Index 1.1 adds only `qualification_corpus_intakes`; Index 1.0 remains unchanged and keeps its exact closed validation path. |
| Operation Provenance Receipt | 1.0, 1.1 | 1.2 | Receipt 1.2 adds one `qualification_historical_corpus_intake` basis for qualification-purpose Semantic Review. Existing 1.0/1.1 semantics and original-author checks are unchanged. |
| Qualification Corpus Intake | none | 1.0 | New closed, custody-only record bound to the frozen corpus/holdout and all 17 case closures. |
| Operator Authority Profile / Role Authorization | 1.0 | 1.1 | Adds the dedicated custodian grant, external process UID pins and controller-build pin; existing 1.0 remains supported. |
| Operator Controller Build Inventory | none | 1.0 | Pins required loaded controller modules and schemas to protected raw bytes. |

Receipt 1.2 requires `author_principal=null`, `author_operation_id=null`, `historical_author_claim="not_made"`, `intake_is_historical_authoring_operation=false`, and `purpose=qualification_only`. Validation requires a current adopted Intake 1.0 record, exact frozen case/content/source/outline bindings, managed Reviewer Configuration 1.1 and Observation 1.1. The intake must predate the review operation. Production-purpose Semantic Review and Teacher receipts continue to require protected original author operations. Qualification intake evidence cannot authorize PA, Teacher Approval or generation.

### Intake authority and historical identity

The new `qualification_corpus_custodian` role is separate from `author`, `scope_reviewer` and `corpus_adjudicator`; those roles do not imply intake permission. The profile grants only the single custodian role. Capture requires an externally injected Operator principal and dedicated UID, the actual process UID, the pinned non-Operator process UID set (Candidate, Author, Reviewer and Approver), an allowlisted controller, and exact protected controller-module/schema bytes. Capture writes one unique operation and intake artifact under the protected repository, then atomically appends one Index 1.1 row. It never writes `authors[]`.

Intake establishes current controlled custody only. Git commit author is not a protected author principal. The custodian is not the historical Content author. The system makes no claim that a reviewer is independent from an unknown historical author; it checks reviewer/custodian, reviewer/operation, adjudicator/custodian and approver/custodian separation within the explicitly authorized qualification-only path.

### Frozen-byte verification and 17-case matrix

The deterministic intake test verified the exact golden and holdout manifest hashes above and compared all 17 Content bytes with the frozen B1 SHA list. It also verified each existing `authoring_id` is preserved, N01/NC-02 remains the exact original bytes, and the intake artifact omits expected labels and critical-truth values. The original Git introduction commit/path may be recorded as metadata only; it does not establish author identity or operation provenance.

| Case | Frozen Content SHA-256 | Existing `authoring_id` | Historical author principal | Protected author operation ID | Protected evidence / verification |
| --- | --- | --- | --- | --- | --- |
| N01 | `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` | `synthetic-fixture-contract-test` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| N02 | `1151b44b2be3e43530f7ca47178aa92d30366e96673c10fc68deb2c7375916a7` | `semantic-case-N02` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| N03 | `e02c519ebb837790760bd76b62667605a7c2916c7f561ba4ec120c195e0331e2` | `semantic-case-N03` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| N04 | `47094b26a926afc0ae2761109f1814a00f7ceb0bb222684a8ba6e93b266f597c` | `semantic-case-N04` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| N05 | `57a6efee6021248ded80d831564f5287c1315231cc08759e9f9d6ab223a3e2a1` | `semantic-case-N05` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| N06 | `f491c68aeda4bdfa5430ab5c024327da181726fcfd1e835eeafa8ca813dc218b` | `semantic-case-N06` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P07 | `6b21514f15c4e0b287f3a999dd475604b7d0f1f94f7d3b669433adf952be7fa3` | `semantic-case-P07` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P08 | `be75ec999322fc7985dcbd6cb7692d2bbe3bac0499e27fd5bc8cf879a260e867` | `semantic-case-P08` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P09 | `9da74d20e240e77ec207ca6a5fadc539c409dbaac16bf6d99f6cdd9ee02583a5` | `semantic-case-P09` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P10 | `dd6e94df2a37c3fbfe0f29c873496e272498ab4c67ec557ae62c1591e26eb5ae` | `semantic-case-P10` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P11 | `769d72f7adbae5e617ac2c9a2a504b658a142d40304d535ef04d34766e8f6512` | `semantic-case-P11` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P12 | `06ca333e97f9ad40e44d9e7b13a5dfa9b31d44986da43209d503fe1145738a2c` | `semantic-case-P12` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| A13 | `6438cdd391f5a2482e62b3be5e821daa860b09664aa0fb1b0f149d5e4786ab92` | `semantic-case-A13` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| P14 | `c2163bbbd0d0d3f7cf65275185cda051a488c872fb2e3a8b798e05e135008000` | `semantic-case-P14` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| H01 | `4cc354b058a6a0dc79eeff0907863594030eddbb2c50e294e3a8db6a444b8924` | `semantic-case-H01` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| H02 | `f31c794c2f624f5e8cc7154f30fb3dcb69ec25378e94bd92c55b3fba5c159d41` | `semantic-case-H02` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |
| H03 | `85f75c14e687737fc95e5cec89f5ad67c5e977d49e6d4112dc0f2d3bead7b113` | `semantic-case-H03` | unknown | none found | B1 evidence search found no protected author operation; exact Content bytes match |

### Security invariants

- Candidate index-byte alteration is rejected by the protected inventory SHA pin; candidate-local profile/index/receipt/intake records are not accepted as protected evidence.
- Duplicate intake and operation IDs are rejected. The append helper preserves all existing receipts, authors, adjudications, qualification runs and intake rows.
- Epoch rotation and authority revocation invalidate an older intake.
- Content SHA, case ID, existing authoring ID, manifest identity and every source/outline closure are rechecked against the exact frozen bytes.
- No frozen corpus, holdout truth, NC-02 bytes, production trust anchor, or original author mapping was changed. No synthetic evidence is promoted to live evidence.
- Existing three fresh repetitions, blind holdout truth isolation, hard-miss fail-closed behavior, separate reviewer/adjudicator/approver authority, independent qualification approval, Observation 1.1 trace binding, 24-hour managed observation validity, profile epoch rotation and revocation remain required.

### Changed files

- `.github/scripts/run_test_shards.py`
- `docs/semantic-scope-review-contract-v1.md`
- `RQ03F_B2_ENROLLMENT_AND_TRUST_BOUNDARY.md`
- `tests/test_lesson_skill_hardening.py`
- `tests/test_qualification_corpus_intake.py`
- `tests/test_run_test_shards.py`
- `tools/rq03f_operator_boundary.sh`
- `教案生成器/lesson-plan-docx-generator/docs/semantic-scope-lifecycle-v2.md`
- `教案生成器/lesson-plan-docx-generator/docs/semantic-scope-runtime-foundation-v1.md`
- `教案生成器/lesson-plan-docx-generator/scripts/install_adapters.py`
- `教案生成器/lesson-plan-docx-generator/scripts/operation_provenance.py`
- `教案生成器/lesson-plan-docx-generator/scripts/qualification_corpus_intake.py`
- `教案生成器/lesson-plan-docx-generator/scripts/reviewer_qualification.py`
- `教案生成器/lesson-plan-docx-generator/scripts/semantic_scope_records.py`
- `教案生成器/lesson-plan-docx-generator/schemas/operation-provenance-receipt-v1.2.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-authority-profile-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-controller-build-inventory-v1.0.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-role-authorization-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/protected-operation-index-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/qualification-corpus-intake-v1.0.schema.json`

## B. Deterministic CI and test evidence

Passed:

- `python -m compileall -q 教案生成器/lesson-plan-docx-generator tests/test_qualification_corpus_intake.py .github/scripts/run_test_shards.py`, `bash -n tools/rq03f_operator_boundary.sh`, and `git diff --check` passed.
- `python .github/scripts/run_test_shards.py --suite semantic-scope -v`: six shards passed, 73/73 (557.24 seconds). The final standalone Intake module passed 12/12; the 17-case exact-byte and frozen manifest test passed within the matrix.
- Semantic shard-manifest checks: 6/6 passed, including exact partition coverage, automatic Intake-test inclusion, and full-root discovery.
- `python .github/scripts/run_test_shards.py --suite hardening -v`: 52/52 passed against this candidate, including installed source-floor checks.
- `python .github/scripts/run_test_shards.py --suite lesson-semantic-lifecycle-evidence -v`: 21/21 passed (492.89 seconds), including current production trust, teacher and PA separation gates.
- `PYTHONPATH='教案生成器/lesson-plan-docx-generator/scripts:.' python -m unittest tests.test_semantic_lifecycle.SemanticLifecycleTests.test_installed_copy_external_controller_resume -v`: 1/1 passed (95.25 seconds).

The repository-wide auxiliary `runner` shard was also attempted. Its gradebook template subprocess failed in this executor environment; this is outside the Lesson semantic CI gate and does not modify or weaken that gate. It is not counted as a passing CI result.

## C. Independent Codex review

**BLOCKED — review did not run.** The built-in `codex review` CLI was invoked against the uncommitted diff with the required security scope, but the installed CLI could not refresh its access token (`401 Unauthorized`: token could not be parsed/refreshed) and its review transport returned `451 no_biscuit_no_service`. It exited before producing findings. The separate `codex-review` tool was not used. This is not recorded as a clean independent review; Owner review remains required.

## D. Actual Operator isolation

**NOT ESTABLISHED.** The protected trust checkout is still at exact anchor commit `eb4a95c618e05c5ad6413137478bc65dbca75ec9`; its profile and index hashes still match the Owner pins; the trust worktree is clean. However, its directory is mode `0700` and files are mode `0600`, owned by the current executor UID 1000. That same UID has write access to the protected directory and index. No write was attempted, and no trust file or branch was changed.

`tools/rq03f_operator_boundary.sh` is an Owner-run Linux Option B provisioning plan. It creates distinct Operator/Candidate/Author/Reviewer/Approver UIDs, makes the trust root Operator-owned/private, pins the immutable controller copy, and probes actual denied index writes under the non-Operator accounts. It was not run here. Its synthetic tests are not deployment proof.

## E. Remaining Production Trust prerequisites

Before any Agent A operation or RQ-03F live qualification, an independent deployment owner must provision and verify the separate Operator process, protected ingress/profile/index, immutable installed controller and schema bytes, distinct author/reviewer/approver identities, current revocation/epoch policy and actual OS-level Candidate write denial. Owner must then review and adopt the versioned intake contract and resulting protected intake operation. The existing golden/holdout, hard-miss, three-repetition, observation, O2/Teacher/PA and production-author gates remain unchanged.

This report deliberately separates code/test readiness from external trust readiness. No Agent A, Agent B, live qualification, merge, release, RC-02 or Lesson 2.4 action was started.
