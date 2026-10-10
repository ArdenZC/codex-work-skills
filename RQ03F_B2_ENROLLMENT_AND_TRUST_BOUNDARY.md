# RQ-03F-B2 Enrollment and Protected Operator Boundary

Date: 2026-10-10 (UTC)
Status: Owner Review #5477224955 remediation candidate; code readiness and external trust readiness remain separate. No merge, release, Agent A invocation, live qualification, or Production Trust activation.

## Baseline and scope

- Trusted master: `a4bfa4155e84c55f56567af6b4bf38357e25ab3c`.
- Trust anchor: `eb4a95c618e05c5ad6413137478bc65dbca75ec9`.
- Authority Profile SHA-256: `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4`.
- Initial Protected Operation Index SHA-256: `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4`.
- Frozen golden corpus SHA-256: `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a`.
- Frozen blind holdout SHA-256: `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a`.
- Original NC-02 / N01 Content SHA-256: `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`.

The accepted B1 finding remains unchanged: no protected historical author operation was found for any of the 17 cases. This branch implements a separate qualification-only custody path; it does not repair or infer original authorship.

## Owner Review #5477224955 remediation map

| Finding | Remediation | Evidence / boundary |
| --- | --- | --- |
| Windows Semantic Scope import/discovery failure | `qualification_corpus_intake.py` treats `fcntl` as optional at import and rejects capture before touching TrustContext unless POSIX lock, no-follow, ownership and UID APIs exist. Test fixtures do not call `os.geteuid()` unconditionally. POSIX capture remains a discovered test, skipped only on unsupported OS; Windows still discovers and runs import, fail-closed and deterministic contract tests. | Six-shard exact partition checks are unchanged. Original run `38018128731` completed with only Windows Semantic Scope shard 1/2 failing; macOS and the remaining platform jobs passed. Fresh exact-HEAD matrix is reported in section B after completion. |
| Incomplete trusted controller dependency graph | Build Inventory 1.1 pins the installed controller root, complete scripts/schema trees, required modules (including `lifecycle_digest.py`, `source_truth.py`, `exemplar_contract.py`, `exemplar_split.py`, and `path_safety.py`), schemas, interpreter identity, every installed `site-packages` byte and the validation dependency packages. The stdlib-only bootstrap verifies the externally pinned inventory before controller imports, runs under `-I -S -B`, narrows `sys.path`, and TrustContext checks actual loaded module paths. | Negative tests reject omitted transitive modules, altered dependency pins, malicious `PYTHONPATH`, and non-isolated launch. Tests use an installed-copy fixture; they do not prove real deployment immutability or external Operator ACLs. |
| Auxiliary Gradebook runner failure | The local runner's nested template-validator failure was reproduced on the candidate and exact trusted master. Both report the same template SHA and font charset mismatch. | The executor uses `LibreOfficeDev 26.8.0.0.alpha0`; the prior GitHub Windows/macOS Gradebook jobs passed. This is classified as an executor LibreOffice-version behavior, not a change from this PR. Full command/output details are in section B. |

## A. Contract and code implementation

### Version compatibility

The versions below are proposed closed extensions for Owner review, not pre-approved final schema numbers.

| Record | Existing version(s) | Proposed version | Compatibility rule |
| --- | --- | --- | --- |
| Protected Operation Index | 1.0 | 1.1 | Index 1.1 adds only `qualification_corpus_intakes`; Index 1.0 remains unchanged and keeps its exact closed validation path. |
| Operation Provenance Receipt | 1.0, 1.1 | 1.2 | Receipt 1.2 adds one `qualification_historical_corpus_intake` basis for qualification-purpose Semantic Review. Existing 1.0/1.1 semantics and original-author checks are unchanged. |
| Qualification Corpus Intake | none | 1.0 | New closed, custody-only record bound to the frozen corpus/holdout and all 17 case closures. |
| Operator Authority Profile / Role Authorization | 1.0 | 1.1 | Adds the dedicated custodian grant, external process UID pins and controller-build pin; existing 1.0 remains supported. |
| Operator Controller Build Inventory | 1.0 candidate | 1.1 proposed | Pins the full installed controller trees, loaded module paths, schemas, interpreter, and validation package dependency trees to the externally pinned build. |

Profile 1.1 now fails closed on a Build Inventory 1.0 value because that version cannot express the complete runtime closure. The 1.0 schema remains in the installed compatibility floor, but it is not accepted as the controller trust pin for this qualification-only Profile 1.1 path. The external profile and trust anchor have not been changed; an Owner-approved 1.1 pin is still required before any live use.

Receipt 1.2 requires `author_principal=null`, `author_operation_id=null`, `historical_author_claim="not_made"`, `intake_is_historical_authoring_operation=false`, and `purpose=qualification_only`. Validation requires a current adopted Intake 1.0 record, exact frozen case/content/source/outline bindings, managed Reviewer Configuration 1.1 and Observation 1.1. The intake must predate the review operation. Production-purpose Semantic Review and Teacher receipts continue to require protected original author operations. Qualification intake evidence cannot authorize PA, Teacher Approval or generation.

### Intake authority and historical identity

The new `qualification_corpus_custodian` role is separate from `author`, `scope_reviewer` and `corpus_adjudicator`; those roles do not imply intake permission. The profile grants only the single custodian role. Capture requires an externally injected Operator principal and dedicated UID, the actual process UID, the pinned non-Operator process UID set (Candidate, Author, Reviewer and Approver), an allowlisted controller, and exact protected controller-module/schema bytes. Capture writes one unique operation and intake artifact under the protected repository, then atomically appends one Index 1.1 row. It never writes `authors[]`.

Owner Review #5477224955 identified that the initial controller build pin checked loaded module bytes after import, omitted transitive validator code, and did not bind runtime paths. Build Inventory 1.1 pins the installed controller root, exact module and schema runtime paths, full `scripts/` and `schemas/` tree hashes, Python executable/version, a full `site-packages` tree digest, and package-tree hashes for `attr`, `attrs`, `jsonschema`, `jsonschema_specifications`, `referencing`, `rpds`, plus `typing_extensions`. Required controller modules include `lifecycle_digest.py`, `source_truth.py`, `exemplar_contract.py`, `exemplar_split.py`, and `path_safety.py`. The stdlib-only `operator_controller_bootstrap.py` independently hashes the Owner-pinned inventory before controller or third-party imports, requires Python `-I -S -B`, and narrows `sys.path` to the installed controller, standard library, and pinned site-packages. `TrustContext.load()` requires that bootstrap attestation, refuses to import missing modules, and checks loaded module origins against the exact protected build paths. The installed-copy adversarial test injects a malicious `PYTHONPATH` module and confirms that only the installed copy loads. Inventory, controller file, schema, tree, and dependency hashes are recalculated directly from bytes. Candidate source SHA-256 values are `4e79117ca30284126e1c850fcf746309acabc0990817f0479a75bbf00187e887` for `operator_controller_bootstrap.py` and `f0d5a5b3177981f20be3273e30055ce6ffb55dcaabbf1a7974b5b0282055e030` for Build Inventory 1.1 schema. Test fixtures independently hash canonical Build Inventory bytes. The actual trust-anchor profile remains Profile 1.0 and has no controller-build pin; it was not changed, and no synthetic inventory is claimed as protected production evidence.

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
- `教案生成器/lesson-plan-docx-generator/scripts/operator_controller_bootstrap.py`
- `教案生成器/lesson-plan-docx-generator/scripts/operation_provenance.py`
- `教案生成器/lesson-plan-docx-generator/scripts/qualification_corpus_intake.py`
- `教案生成器/lesson-plan-docx-generator/scripts/reviewer_qualification.py`
- `教案生成器/lesson-plan-docx-generator/scripts/semantic_scope_records.py`
- `教案生成器/lesson-plan-docx-generator/schemas/operation-provenance-receipt-v1.2.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-authority-profile-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-controller-build-inventory-v1.0.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-controller-build-inventory-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/operator-role-authorization-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/protected-operation-index-v1.1.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/qualification-corpus-intake-v1.0.schema.json`

## B. Deterministic CI and test evidence

### Local candidate results

- `python -B -m compileall -q 教案生成器/lesson-plan-docx-generator tests/test_qualification_corpus_intake.py .github/scripts/run_test_shards.py`, `bash -n tools/rq03f_operator_boundary.sh`, and `git diff --check`: passed.
- `python -B .github/scripts/run_test_shards.py --suite semantic-scope -v`: six shards passed, **78/78** (634.10 seconds). Exact six-shard manifest/partition checks ran; the new intake and import-boundary tests remained in discovery. All 17 frozen Content bytes and the golden/holdout manifest hashes passed.
- `python -B .github/scripts/run_test_shards.py --suite hardening -v`: **52/52** passed (14.03 seconds), including the installed source-floor assertions for the controller bootstrap and Build Inventory 1.1 schema.
- `python -B .github/scripts/run_test_shards.py --suite lesson-semantic-lifecycle-evidence -v`: **21/21** passed (462.44 seconds), including O2 entry points, transitive stale-build checks, production authorization, Teacher/PA separation and exact NC-02 bytes.
- Semantic scope adversarial tests passed within the six shards: missing `source_truth` pin, altered dependency hash, malicious `PYTHONPATH`, wrong import origin, non-isolated bootstrap and candidate-side protected-index tampering all fail closed.

### Auxiliary Gradebook runner failure classification

The repository helper was run as `python -B .github/scripts/run_test_shards.py --suite runner -v`: **27/28 pass, 1 fail**. The failing test is `test_gradebook_discovery_worker_does_not_reuse_lesson_package_common`; its nested Gradebook `test_template_validator` subprocess exits 1 with empty stderr. Direct reproduction:

```text
$ python 平时成绩记分册生成器/course-gradebook-generator/scripts/validate_template.py --json
exit status: 1
errors: ["Named-range template changed protected workbook structure or formatting."]
template SHA expected=actual=FEA186D65DCE742FC7DD0370FF24C60D8D5A1004BC357D99FC75F22F06B9C28E
protected_signature_differences: 20
first difference: non_target_sheets.Sheet1.cells[1][1].format.font
  expected font charset=1; actual font charset=null
```

The exact same validator command on candidate `25983a30b61985f429e148bfbc5222c4a67a88c9` and trusted master `a4bfa4155e84c55f56567af6b4bf38357e25ab3c` produced byte-for-byte equal `checks` JSON and the same 20 differences. The Gradebook subtree has no diff from trusted master. This executor runs Python 3.12.14, openpyxl 3.1.5 and `LibreOfficeDev 26.8.0.0.alpha0` (`2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`). In original GitHub run `38018128731`, Windows and macOS Gradebook jobs both passed. Classification: **executor environment behavior from the LibreOffice development build**, not this PR's code and not evidence of an existing cross-platform Gradebook regression. The auxiliary runner result is not counted as passing.

### GitHub CI evidence

Original run [38018128731](https://github.com/ArdenZC/codex-work-skills/actions/runs/38018128731) completed with `CI Gate` failure because Windows Semantic Scope shards 1 and 2 failed. The macOS Semantic Scope shards, Windows shards 3–6, macOS shards 1–6, O2 lifecycle evidence, final acceptance, and Windows/macOS Gradebook jobs succeeded. Shard 1 failed at `Verify exact semantic partition coverage` because test discovery could not import `qualification_corpus_intake`; shard 2 failed at `Run requested semantic scope partition`. Owner Review #5477224955 identifies the import traceback as the unconditional `fcntl` dependency. This run is **not** a passing remediation CI result.

Fresh exact-HEAD GitHub CI for the remediation commit: **pending push and completion**. Windows/macOS O1/O2 results will be recorded here from that run before Owner rereview.

## C. Independent Codex review

**No independent review pass is claimed.** The previously attempted review endpoint failed before producing findings (`401 Unauthorized` while refreshing the token and `451 no_biscuit_no_service`). This remediation did not invoke `codex-review`, which remains prohibited. Owner review is still required.

## D. Actual Operator isolation

**NOT ESTABLISHED.** The external trust snapshot remains materialized at the Owner's exact anchor path `eb4a95c618e05c5ad6413137478bc65dbca75ec9`; its authority-profile and operation-index hashes still match the Owner pins. The snapshot path is not a Git worktree. Its trust directory is mode `0700` and files are mode `0600`, owned by the current executor UID 1000, so that same UID has write access to the protected directory and index. No write was attempted; no trust file or branch was changed.

`tools/rq03f_operator_boundary.sh` is an Owner-run Linux Option B provisioning plan. It creates distinct Operator/Candidate/Author/Reviewer/Approver UIDs, makes the trust root Operator-owned/private, pins the immutable controller copy, and probes actual denied index writes under the non-Operator accounts. It was not run here. Its synthetic tests are not deployment proof.

## E. Remaining Production Trust prerequisites

Before any Agent A operation or RQ-03F live qualification, an independent deployment owner must provision and verify the separate Operator process, protected ingress/profile/index, immutable installed controller and schema bytes, distinct author/reviewer/approver identities, current revocation/epoch policy and actual OS-level Candidate write denial. Owner must then review and adopt the versioned intake contract and resulting protected intake operation. The existing golden/holdout, hard-miss, three-repetition, observation, O2/Teacher/PA and production-author gates remain unchanged.

This report deliberately separates code/test readiness from external trust readiness. No Agent A, Agent B, live qualification, merge, release, RC-02 or Lesson 2.4 action was started.
