# Semantic lifecycle integration (RQ-03O2)

This opt-in integration implements the merged normative repository contract
`docs/semantic-scope-review-contract-v1.md`, using the O1 APIs. Skill **2.3.1**,
Content **2.3** / historical **2.2**, Template **1.1.2**, and Acceptance **3.0**
retain their identities. No release, provider invocation, actual reviewer
qualification, human authentication or production deployment is performed here.

## Versions and immutable runs

Create a new run with `orchestrator_version="2.0"` through the controller API
(`--orchestrator-version 2.0` selects the same version in the CLI). Pipeline,
Teacher Packet, Teacher Review and PA must all use **2.0** for that run. Historical
1.0 envelopes and artifacts retain their original validation policy. They are
never implicitly upgraded to O2; a new run needs fresh independent review and
approval. Standalone generator calls remain legacy and do not grant O2 authority.
Content changes, teacher revisions or source/outline changes require successor
runs. Installation changes invalidate existing QA and PA Skill inventories.
The Draft RQ03F-B2 qualification-only corpus-intake extension does not change
O2 dispatch or grant a production authoring, Teacher approval, PA or generation
capability. Index 1.1/Receipt 1.2 intake evidence is limited to
qualification-purpose case reviews; all production paths retain the actual
protected author-operation requirement.

After deterministic QA, both Benchmark branches require the same readiness gate.
Disposition-only binding in O2 stays at PREPRODUCTION_QA_PASSED; a completed
Benchmark Review stays at BENCHMARK_REVIEW_COMPLETE. The controller calls
`bind-semantic-scope-review` to atomically bind the real evidence and immutable
dependency inventory without adding a same-state transition. Then
`ready-for-teacher-review` requires valid PASS or HUMAN_REVIEW_REQUIRED evidence.
PREVIEW can inspect missing evidence at QA; it cannot become READY without it or
authorize/generate/finalize production. CLI diagnostics explicitly report the
authorization flag and missing semantic report.

Packet 2.0 preserves the existing quota/selection and appends every recorded
semantic issue, including unselected Lessons. Review 2.0 retains usability and
whole-course assessments and explicitly resolves every ambiguity exactly once
using bounded rationale and verified source references. Definite revisions cannot
be waived. A separate protected teacher approval receipt binds its exact bytes;
role, actor, operation, decision and current authority are validated by O1.
PA 2.0 records all semantic/configuration/qualification/approval/profile hashes
and independently recomputes effective PASS. Its validators require the actual O2
run as `semantic_run`; bare sidecars cannot establish production authority.

## External operator integration

The supported integration is a strict **external TrustContext** API. The operator
must provision protected controller code, ingress, immutable evidence and an
append-only operation index outside author/reviewer access. Controller launch
policy supplies the profile path/raw pin, epoch, protected repositories and exact
controller allowlist. None comes from candidate JSON or the installed Skill.

An operator-controlled embedding process registers a callable using
`semantic_lifecycle.operator_context(provider)`. On each check, `provider()`
re-reads current protected launch policy/index and returns the O1 `TrustContext`
with its explicit `Inventory`. The integration validates current UTC time itself,
re-reads actual ordinary bytes and verifies current profile and protected capture.
The provider must fail on unavailable policy/index, configuration not pinned by
the operator, uncontrolled ingress or author-writable authority. An ordinary
author process must not register this provider; Python cannot establish ACLs,
authenticate humans or protect an operator from itself (Option B's trust limit).
The CLI alone deliberately does not provision this authority and fails closed at
semantic binding. Do not serialize a candidate-supplied factory/root or copy a
test controller into production.

Within that scope, call the existing `run_lesson_pipeline.execute` commands.
The controller records Semantic Review/receipt and qualification approvals through
external ingress before binding. Later it captures exact Teacher Review bytes and
a separate teacher receipt before `bind-teacher-review`. The live index can append
captures; immutable reviewed dependencies are frozen in the run and cannot change.
The provider's inventory may grow as ingress captures new artifacts. Qualification
and blind holdout bytes remain in protected external storage and are never copied
into the Teacher Packet. The run inventory contains only their file bindings.

Canonical O2 generation invokes the existing generator in that embedding process
so it retains the same external authority. It revalidates before candidate
directory creation, before transaction publication, and in the existing
post-commit validator; that transaction restores old output on failure and removes
staging. The orchestrator removes newly generated output if final validation/state
commit fails. Old authorized output remains immutable in canonical runs. Retained
render, Artifact QA, Visual Review and Acceptance remain independent gates.

## Qualification limits

`tests/test_semantic_lifecycle.py` exercises synthetic independent records at
actual lifecycle/generator/installer entry points. Existing O1 corpus/authority
tests remain required in all 12 matrix legs. These results prove deterministic
wiring and fail-closed transactions only. They establish neither realistic P12
approval nor blind holdout independence, actual model execution, human
participation, or a live qualified reviewer. Owner-controlled provisioning and
live reviewer qualification remain separate post-code acceptance gates.
