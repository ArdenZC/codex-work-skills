# RQ-03F-B2 Enrollment and Protected Operator Boundary

Date: 2026-10-10 (UTC)
Status: Owner Review #5477224955 remediation candidate; code readiness and external trust readiness remain separate. No merge, release, Agent A invocation, live qualification, or Production Trust activation.

## Baseline and scope

- Trusted master: `a4bfa4155e84c55f56567af6b4bf38357e25ab3c`.
- Code under test: `e4bbf247747e13e5fcf7c5d9f2b3be84e399314e` (branch `rq03f-b2-qualification-intake`, PR #57 remains OPEN / Draft).
- This report-only update follows the completed CI run above; no controller, schema, test, workflow, trust, corpus, or golden-label bytes changed after the tested code HEAD.
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
| Windows Semantic Scope import/discovery failure and timeout | `qualification_corpus_intake.py` treats `fcntl` as optional at import and rejects capture before touching TrustContext unless POSIX lock, no-follow, ownership and UID APIs exist. UID-sensitive fixtures use platform-safe identity helpers; Windows still discovers and executes applicable contract tests. The semantic job creates a runner-temp venv with unchanged requirements and exports its exact interpreter path. `_resolve_python_command()` now preserves that lexical path so a macOS venv symlink is not resolved back to the base interpreter. Inventory construction checks file type without hashing every evidence file; `Inventory.raw()` still checks bytes when consumed. Path aliases are expanded once per path instead of repeatedly for every pair. | Original run `38018128731` shard 1 failed import discovery on unconditional `fcntl`; the test fixture also called `os.geteuid()` directly. Run `38025448941` passed six-shard coverage (6/6) but Windows shard 1 reached the existing 35-minute limit while the worker waited in `_winapi.WaitForSingleObject`. Run `38029711490` then exposed two specific remaining issues: macOS shards failed with `ModuleNotFoundError: No module named 'docx'` because `.resolve()` collapsed the venv interpreter symlink, and Windows shard 2 failed because Python 3.11 `-S` reported base `sysconfig` site-packages. Both are corrected without deleting tests or changing timeouts/shard coverage. Fresh exact-code-HEAD run `38031076347` on `e4bbf247747e13e5fcf7c5d9f2b3be84e399314e` passed all 12 semantic shards across Windows/macOS (13 tests per shard; Windows shard 4 has one platform-specific skip). The exact six-partition coverage check passed in macOS shard 1. The Windows installed-copy hostile-import test passed in shard 2. Windows shard 1 completed in 306.47s, below the unchanged 35-minute timeout. All 41 workflow jobs completed: 40 succeeded, one expected Documentation checks skip, and CI Gate succeeded. |
| Incomplete trusted controller dependency graph | Build Inventory 1.1 pins the installed controller root, complete scripts/schema trees, required modules (including `lifecycle_digest.py`, `source_truth.py`, `exemplar_contract.py`, `exemplar_split.py`, and `path_safety.py`), schemas, interpreter identity, every installed `site-packages` byte and validation dependency packages. The stdlib-only bootstrap verifies the externally pinned inventory and exact module/schema/package hashes before importing controller code, runs under `-I -S -B`, and narrows `sys.path`. When Python 3.11 `-S` hides the venv prefix, bootstrap now binds the pinned site-packages directory to the active lexical venv executable path; it does not trust mutable `pyvenv.cfg` metadata. Profile 1.1 requires the process-local bootstrap attestation; TrustContext verifies the attestation, pinned manifest and inventory bindings, checks required loaded module/package origins, and rehashes schemas used for validation. Installed source and runtime trees still require external Operator immutability, which is not established here. | Negative tests reject an omitted transitive module, altered component/dependency pins, malicious `PYTHONPATH`, wrong loaded-module origin, a site-packages root from a different venv, and non-isolated launch. The installed-copy test copies scripts and schemas to an independent root and confirms the hostile `PYTHONPATH` module does not execute. A separate independent hash implementation recalculated all 35 synthetic build components with no mismatch. These tests do not prove real deployment immutability or external Operator ACLs. |
| Auxiliary Gradebook runner failure | The local runner's nested template-validator failure was reproduced after installing / using the repository's Gradebook dependency (`xlrd 2.0.1`), so the earlier missing-`xlrd` result from the minimal semantic venv is not the Gradebook finding. Direct validation reports an unchanged template byte SHA but 20 protected formatting differences after LibreOffice conversion; the first is `non_target_sheets.Sheet1.cells[1][1].format.font`, expected `charset=1`, actual `null`. | Candidate and trusted master Gradebook subtrees are byte-identical. The executor runs `LibreOfficeDev 26.8.0.0.alpha0`; exact trusted-master reproduction reported identical checks JSON and all 20 font charset differences. Fresh exact-code-HEAD run `38031076347` passed both Windows and macOS Gradebook jobs. Evidence supports an executor LibreOffice conversion behavior, not a PR regression; section B retains the raw reproduction and failed local runner disposition. |
| Protected Operator write isolation | No production identity or filesystem boundary was provisioned during this remediation. The report continues to classify external Operator isolation as NOT ESTABLISHED; same-UID directories and synthetic ACL tests are not accepted as deployment evidence. | The external trust snapshot/profile/index remain unchanged. Candidate-side writes to trust state were not attempted. Owner/deployment acceptance of distinct OS identities, protected ingress and denied Candidate writes remains a prerequisite; no Agent A/B or live qualification was started. |
| Independent review endpoint | The previous independent review request did not produce a review result (`401 Unauthorized` during token refresh and `451 no_biscuit_no_service`). `codex-review` remains prohibited by instruction. | No independent review pass is claimed. This is reported as unavailable/failed, and Owner rereview remains required. |

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

Owner Review #5477224955 identified that the initial controller build pin checked loaded module bytes after import, omitted transitive validator code, and did not bind runtime paths. Build Inventory 1.1 pins the installed controller root, exact module and schema runtime paths, full `scripts/` and `schemas/` tree hashes, Python executable/version, the complete `site-packages` tree, and package-tree hashes for `attr`, `attrs`, `jsonschema`, `jsonschema_specifications`, `referencing`, `rpds`, plus `typing_extensions`. Required controller modules include `lifecycle_digest.py`, `source_truth.py`, `exemplar_contract.py`, `exemplar_split.py`, and `path_safety.py`. The stdlib-only `operator_controller_bootstrap.py` independently hashes the Owner-pinned inventory before controller or third-party imports, requires Python `-I -S -B`, and narrows `sys.path` to the installed controller, standard library, and pinned site-packages. Under Python 3.11 `-S`, the bootstrap binds the inventory's venv site-packages path to the active lexical `sys.executable` location; it does not trust mutable `pyvenv.cfg` metadata. `TrustContext.load()` requires that exact process-local bootstrap attestation, validates inventory component paths, refuses missing or shadowed controller modules, and recomputes hashes for loaded controller modules and schemas. Third-party dependency tree bytes are checked by the bootstrap before imports; TrustContext verifies loaded package origins against those pinned paths without repeating the full dependency-tree hash for every review case. The installed-copy adversarial test injects a malicious `PYTHONPATH` module and confirms that only the installed copy loads. On the code commit, the independently calculated bootstrap SHA-256 is `203411ec9ac5a1dcd795412a43942d86c1105d5603b4a3ead3606ddeaa7576dc`; `lifecycle_digest.py` is `e10afbf7044e3f840e830aa46d0ffd472758c302d2cebd826e00dcd70c7f9919`; `source_truth.py` is `5415e6543c69a9c454e5a0d2ac825055599edbd720cc3998f3acb2bb83e74997`; and the Build Inventory 1.1 schema is `f0d5a5b3177981f20be3273e30055ce6ffb55dcaabbf1a7974b5b0282055e030`. An independent implementation recalculated all 35 components in a synthetic fixture without mismatch; its ephemeral canonical inventory SHA-256 was `448a2b13a3ec7a36167a363826dd343b2f3f029999836c7a53d79113fce02232`, scripts tree `7b89a590fe7a00c052da11beeb372de9a129c01c25d7c77b8998bdb341f4ae9a`, and schemas tree `2bad046552996c3fd229712d1480a13c669b8b4da152fe2359be9812d21d7f0e`. Those fixture values demonstrate reproducible calculation only; they are not adopted production pins or protected authority. The actual trust-anchor profile remains Profile 1.0 and has no controller-build pin; it was not changed.

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
- `.github/workflows/template-package-ci.yml`
- `docs/semantic-scope-review-contract-v1.md`
- `RQ03F_B2_ENROLLMENT_AND_TRUST_BOUNDARY.md`
- `tests/test_lesson_skill_hardening.py`
- `tests/test_qualification_corpus_intake.py`
- `tests/test_semantic_scope_foundation.py`
- `tests/test_run_test_shards.py`
- `tools/rq03f_operator_boundary.sh`
- `教案生成器/lesson-plan-docx-generator/docs/semantic-scope-lifecycle-v2.md`
- `教案生成器/lesson-plan-docx-generator/docs/semantic-scope-runtime-foundation-v1.md`
- `教案生成器/lesson-plan-docx-generator/scripts/install_adapters.py`
- `教案生成器/lesson-plan-docx-generator/scripts/operator_controller_bootstrap.py`
- `教案生成器/lesson-plan-docx-generator/scripts/operation_provenance.py`
- `教案生成器/lesson-plan-docx-generator/scripts/exemplar_contract.py`
- `教案生成器/lesson-plan-docx-generator/scripts/path_safety.py`
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

- With `RUN_TEST_SHARDS_PYTHON=/tmp/rq03f-b2-semantic-venv/bin/python`, `/tmp/rq03f-b2-semantic-venv/bin/python -B .github/scripts/run_test_shards.py --suite semantic-scope --parallel -v`: all six shards passed, **78/78** (78.30 seconds wall time). This exercises the explicit worker-interpreter setting used by CI. Exact six-shard manifest/partition checks ran; intake and import-boundary tests remained in discovery. All 17 frozen Content bytes and golden/holdout manifest hashes passed.
- The six explicit shard-manifest coverage tests passed, including exact top-level partition coverage, hard-miss discovery, the new-test partition rule and full-manifest discovery. The per-path alias expansion assertion is inside an existing semantic test, so coverage and hard-miss counts did not change.
- `python -B -m compileall`, `bash -n tools/rq03f_operator_boundary.sh` and `git diff --check`: passed before the report-only update; they will be rerun on the final report HEAD.
- Hardening: **52/52** passed (14.62 seconds), including installed source-floor assertions for the controller bootstrap and Build Inventory 1.1 schema.
- O2 lifecycle evidence: **21/21** passed (448.14 seconds), including production authorization, Teacher/PA separation, transitive stale-build checks and exact NC-02 bytes.
- Independent raw-byte digest recalculation in a synthetic controller-build fixture matched its manifest pin: ephemeral canonical inventory SHA-256 `448a2b13a3ec7a36167a363826dd343b2f3f029999836c7a53d79113fce02232`; scripts tree `7b89a590fe7a00c052da11beeb372de9a129c01c25d7c77b8998bdb341f4ae9a`; schemas tree `2bad046552996c3fd229712d1480a13c669b8b4da152fe2359be9812d21d7f0e`; bootstrap source `203411ec9ac5a1dcd795412a43942d86c1105d5603b4a3ead3606ddeaa7576dc`; Build Inventory 1.1 schema `f0d5a5b3177981f20be3273e30055ce6ffb55dcaabbf1a7974b5b0282055e030`. Independent calculation covered all 35 manifest components with zero mismatches. Fixture values are calculation evidence, not adopted production pins or protected authority.
- Six exact shard-manifest coverage checks plus isolated workflow configuration and explicit interpreter selection: **8/8** passed on the final code commit. The complete local `runner` suite on the semantic-only venv is not a valid Gradebook environment because that venv intentionally lacks `xlrd`; its nested Gradebook tests report `ModuleNotFoundError: xlrd`. Re-run using the executor's normal Python (which has `xlrd 2.0.1`) gave **27/28**, with only the Gradebook template-validator test failing. Direct `validate_template.py --json` reproduction reports the unchanged workbook SHA `FEA186D65DCE742FC7DD0370FF24C60D8D5A1004BC357D99FC75F22F06B9C28E` and 20 LibreOffice conversion formatting differences; first mismatch is the font charset `1` versus `null`. Candidate and trusted master Gradebook subtrees are identical.
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

The same direct validator command on candidate `25983a30b61985f429e148bfbc5222c4a67a88c9` and trusted master `a4bfa4155e84c55f56567af6b4bf38357e25ab3c` produced byte-for-byte equal `checks` JSON and the same 20 differences. The Gradebook subtree has no diff from trusted master. This executor runs Python 3.12.14, openpyxl 3.1.5 and `LibreOfficeDev 26.8.0.0.alpha0` (`2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`). GitHub Gradebook jobs passed on Windows and macOS in both original run `38018128731` and fresh exact-code-HEAD run `38031076347`. Classification: **executor environment behavior from the LibreOffice development build**, not a PR regression. The auxiliary runner result is not counted as passing.

### GitHub CI evidence

Original run [38018128731](https://github.com/ArdenZC/codex-work-skills/actions/runs/38018128731) completed with `CI Gate` failure because Windows Semantic Scope shards 1 and 2 failed. The macOS Semantic Scope shards, Windows shards 3–6, macOS shards 1–6, O2 lifecycle evidence, final acceptance, and Windows/macOS Gradebook jobs succeeded. Shard 1 failed at `Verify exact semantic partition coverage` because discovery could not import `qualification_corpus_intake`; Owner Review #5477224955 records the traceback as the unconditional `fcntl` dependency, and the test fixture also called `os.geteuid()` directly. Shard 2 failed at `Run requested semantic scope partition`. This run is **not** a passing remediation CI result.

Run [38021661330](https://github.com/ArdenZC/codex-work-skills/actions/runs/38021661330) tested PR head `b8d96c94f60b7e4ca1a418350cfc81c6efd215b2`; it concluded **failure**. All six macOS Semantic Scope shards passed. Windows shards 3–6 passed; shard 2 failed only at the installed-copy path assertion described above after 13 tests ran in 1,509.916 seconds, and shard 1 was cancelled at 35 minutes while the child test process was still running (`KeyboardInterrupt` in `run_test_shards.py` while waiting for the worker). Windows/macOS O2 lifecycle evidence, final acceptance and Gradebook jobs passed. This is not a passing remediation CI result.

Run [38025448941](https://github.com/ArdenZC/codex-work-skills/actions/runs/38025448941) tested `680836b8ad4fd4d67844d075b67f191ec94a8813` and concluded **cancelled**. The exact coverage check passed; Windows Semantic Scope shard 1 was cancelled at 35 minutes while its worker was still running. Its job log ended in the parent waiting for the worker (`subprocess.run` / `_winapi.WaitForSingleObject`), not a test assertion. All macOS shards and Windows shards 2–6 passed, as did Windows/macOS O2 lifecycle evidence, Gradebook, final acceptance and other CI jobs; CI Gate failed only because shard 1 was cancelled. This establishes that the `fcntl` and short-path findings were corrected but the performance issue remained. The current patch adds the isolated venv and avoids repeated byte hashing and alias normalization while preserving exact checks and six-shard coverage. Fresh CI below must confirm the timeout is resolved.

Run [38029295706](https://github.com/ArdenZC/codex-work-skills/actions/runs/38029295706) tested `e388ce789f24a147dbb38bce2e75fc568dc13272`. The macOS shard 1 log confirms the venv install and isolation probe succeeded and the exact six-test coverage check passed; the worker then exited in 0.34 seconds with `ModuleNotFoundError: No module named 'docx'` while using the base framework interpreter. Windows shard 3 passed, but the run is an unsuccessful intermediate attempt and is superseded by the explicit worker-interpreter correction. This failure was reproduced from the trace and fixed in code; it is not classified as an unrelated environment failure.

Fresh exact-code-HEAD run [38031076347](https://github.com/ArdenZC/codex-work-skills/actions/runs/38031076347) tested `e4bbf247747e13e5fcf7c5d9f2b3be84e399314e` and completed **success**. All 12 Windows/macOS Semantic Scope shards passed (13 tests per shard; one Windows-only applicability skip); shard 1's six-partition coverage check passed; both O2 semantic-lifecycle evidence jobs passed 21/21; both Gradebook jobs passed; installed-copy, canonical-generation, rollback, final-acceptance, core regression, tooling, release-scale, WorkOrder and courseware jobs completed successfully. All **41** jobs completed: **40 success, one expected Documentation checks skip**, with **CI Gate success** and no failures.

## C. Independent Codex review

**No independent review pass is claimed.** The previously attempted review endpoint failed before producing findings (`401 Unauthorized` while refreshing the token and `451 no_biscuit_no_service`). This remediation did not invoke `codex-review`, which remains prohibited. Owner review is still required.

## D. Actual Operator isolation

**NOT ESTABLISHED.** The external trust snapshot remains materialized at the Owner's exact anchor path `eb4a95c618e05c5ad6413137478bc65dbca75ec9`; its authority-profile and operation-index hashes still match the Owner pins. The snapshot path is not a Git worktree. Its trust directory is mode `0700` and files are mode `0600`, owned by the current executor UID 1000, so that same UID has write access to the protected directory and index. No write was attempted; no trust file or branch was changed.

`tools/rq03f_operator_boundary.sh` is an Owner-run Linux Option B provisioning plan. It creates distinct Operator/Candidate/Author/Reviewer/Approver UIDs, makes the trust root Operator-owned/private, pins the immutable controller copy, and probes actual denied index writes under the non-Operator accounts. It was not run here. Its synthetic tests are not deployment proof.

## E. Remaining Production Trust prerequisites

Before any Agent A operation or RQ-03F live qualification, an independent deployment owner must provision and verify the separate Operator process, protected ingress/profile/index, immutable installed controller and schema bytes, distinct author/reviewer/approver identities, current revocation/epoch policy and actual OS-level Candidate write denial. Owner must then review and adopt the versioned intake contract and resulting protected intake operation. The existing golden/holdout, hard-miss, three-repetition, observation, O2/Teacher/PA and production-author gates remain unchanged.

This report deliberately separates code/test readiness from external trust readiness. No Agent A, Agent B, live qualification, merge, release, RC-02 or Lesson 2.4 action was started.
