"""SYNTHETIC O2 controller records: no actual human/model qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import subprocess
import sys
from unittest.mock import patch

from tests.semantic_scope_test_support import Evidence, AT, END
from tests.test_lesson_lifecycle_contracts import _teacher_review, _production_authorization, _write_json
from lifecycle_digest import LifecycleContractError, sha256_file
from teacher_review import teacher_review_fingerprint
from production_authorization import production_authorization_fingerprint
from semantic_lifecycle import operator_context, authorization_scope
import run_lesson_pipeline as pipeline


class SemanticLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e = Evidence(Path(self.temp.name))
        # Explicit synthetic teacher role, separately captured from author/scope.
        self.e.write("teacher-authorization", dict(record_version="1.0", principal_id="teacher", allowed_roles=["teacher_approver"]), protected=True)
        self.e.profile["roles"].append(dict(principal_id="teacher", allowed_roles=["teacher_approver"],
            authorization_reference="teacher-authorization", valid_from="2026-01-01T00:00:00Z", valid_until=END,
            revoked_at=None, revocation_reason=None))
        self.e.write("authority_profile", self.e.profile, protected=True)
        self.e.qualification_approval()
        self.e.review(pipeline="RUN-001")
        self.run = self.e.run / "run.json"
        self.scope = operator_context(self.e.context)
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)

    def call(self, command, **options):
        return pipeline.execute(command, self.run, **options)

    def qa(self):
        source = Path(self.e.entries["source_truth_manifest"]["path"])
        content = Path(self.e.entries["content"]["path"])
        self.call("init", mode="PRODUCTION", run_id="RUN-001", source_truth=source, orchestrator_version="2.0")
        self.call("freeze-source-truth")
        evidence = dict(pipeline_run_id="RUN-001", source_truth_manifest_sha256=self.e.sha("source_truth_manifest"),
            content_sha256=self.e.sha("content"), decision="WAIVED_BY_USER", user_identity="SYNTHETIC owner",
            waiver_reference="SYNTHETIC explicit waiver", notes="Does not waive semantic review")
        waiver = self.e.write("waiver", evidence)
        self.call("bind-content", content=content, waiver_evidence=waiver)
        self.call("validate-preproduction")
        self.benchmark = dict(disposition="BENCHMARK_WAIVED_BY_USER", authorization_sha256=None, review_sha256=None,
            evidence_sha256=sha256_file(waiver), waiver_reference=evidence["waiver_reference"])
        disposition = self.e.write("disposition", dict(pipeline_run_id="RUN-001", source_truth_manifest_sha256=self.e.sha("source_truth_manifest"),
            content_sha256=self.e.sha("content"), benchmark=self.benchmark))
        result = self.call("bind-benchmark-disposition", disposition=disposition)
        self.assertEqual(result["state"]["current_state"], "PREPRODUCTION_QA_PASSED")

    def ready(self, disposition="PASS"):
        self.e.review(pipeline="RUN-001", disposition=disposition)
        self.qa()
        self.call("bind-semantic-scope-review")
        return self.call("ready-for-teacher-review")

    def approve(self, disposition="PASS", *, mutate=None):
        self.ready(disposition)
        run = self.call("prepare-teacher-review")
        packet = json.loads(pipeline.path_of(run, "teacher_review_packet").read_bytes())
        review = _teacher_review(Path(self.e.entries["source_truth_manifest"]["path"]).read_bytes(),
            Path(self.e.entries["content"]["path"]).read_bytes(), self.benchmark)
        review["contract_version"] = "2.0"
        row = review["selected_lessons"][0]
        review["selected_lessons"] = [dict(copy.deepcopy(row), lesson_id=item["lesson_id"], selection_reasons=item["selection_reasons"])
            for item in packet["selected_lessons"]]
        review["reviewed_at"] = AT
        review["semantic_scope"] = {key: value for key, value in packet["semantic_scope"].items() if key != "issue_index"}
        review["semantic_scope"].update(human_reviewer=dict(identity="teacher", review_operation_id="teacher-op", authority_reference="teacher_approval_receipt"), resolutions=[])
        for issue in packet["semantic_scope"]["issue_index"]:
            review["semantic_scope"]["resolutions"].append(dict(issue_id=issue["issue_id"], decision="RESOLVED_IN_SCOPE",
                bounded_rationale="SYNTHETIC adjudication of unchanged candidate", source_references=issue["source_references"], resolved_at=AT))
        if mutate:
            mutate(review)
        review["review_fingerprint"] = teacher_review_fingerprint(review)
        path = self.e.write("teacher_review", review)
        self.e.receipt("teacher_approval_receipt", "teacher_approval", "teacher_review", {key:self.e.sha(key) for key in
            ("source_truth_manifest", "outline", "content", "semantic_scope_review", "semantic_scope_operation_receipt")}, "teacher-op", "teacher", pipeline="RUN-001")
        self.call("bind-teacher-review", teacher_review=path)
        return path

    def authorize(self, disposition="PASS"):
        teacher = self.approve(disposition)
        run = self.call("status")
        review = json.loads(teacher.read_bytes())
        auth = _production_authorization(Path(self.e.entries["source_truth_manifest"]["path"]).read_bytes(),
            Path(self.e.entries["content"]["path"]).read_bytes(), teacher.read_bytes(), self.benchmark)
        auth["contract_version"] = "2.0"
        auth["semantic_scope"] = authorization_scope(run, review)
        from production_authorization import _current_repo_commit
        from lifecycle_digest import skill_tree_fingerprint
        auth["lesson_skill"]["installed_skill_fingerprint"] = skill_tree_fingerprint(pipeline.SKILL_ROOT)
        auth["lesson_skill"]["source_repo_commit"] = _current_repo_commit(pipeline.SKILL_ROOT)
        auth["authorization_fingerprint"] = production_authorization_fingerprint(auth)
        path = self.e.write("production_authorization", auth)
        return self.call("authorize-production", authorization=path)

    def reject(self, command, **options):
        before = self.run.read_bytes()
        with self.assertRaises((LifecycleContractError, OSError, ValueError, KeyError)):
            self.call(command, **options)
        self.assertEqual(before, self.run.read_bytes())
        self.assertFalse(Path(str(self.run) + ".lock").exists())
        self.assertFalse(list(self.e.run.glob("*.candidate-*")))

    def test_pass_authorization_and_resume(self):
        run = self.authorize()
        self.assertEqual(run["state"]["current_state"], "PRODUCTION_AUTHORIZED")
        self.assertEqual(run, self.call("status"))

    def test_ambiguity_separate_teacher_resolution(self):
        self.assertEqual(self.authorize("HUMAN_REVIEW_REQUIRED")["state"]["current_state"], "PRODUCTION_AUTHORIZED")

    def test_waiver_cannot_skip_review(self):
        self.qa()
        self.reject("ready-for-teacher-review")

    def test_definite_revision_never_ready(self):
        self.e.review(pipeline="RUN-001", disposition="REVISION_REQUIRED")
        self.qa()
        self.call("bind-semantic-scope-review")
        self.reject("ready-for-teacher-review")
        self.reject("authorize-production", authorization=self.e.run / "absent.json")
        self.reject("generate-production", output_dir=self.e.run / "output")

    def test_unprovisioned_authority_fails_closed(self):
        self.qa()
        self.scope.__exit__(None, None, None)
        self.scope = operator_context(self.e.context)
        self.reject("bind-semantic-scope-review")
        self.scope.__enter__()

    def test_stale_transitive_build_even_rebound_external_inventory(self):
        self.authorize()
        self.e.write("build-code", b"changed build", protected=True)
        self.reject("status")

    def test_revoked_teacher_current_authority(self):
        self.authorize()
        self.e.profile["revoked_authority_ids"].append("teacher_approval_receipt")
        self.e.write("authority_profile", self.e.profile, protected=True)
        self.reject("status")

    def test_raw_review_bytes_stale(self):
        self.ready()
        path = Path(self.e.entries["semantic_scope_review"]["path"])
        path.write_bytes(path.read_bytes() + b"\n")
        self.reject("status")

    def test_real_generator_publication_and_final_stale_rollback(self):
        run = self.authorize()
        from generate_lesson_plans import main, validate_output_dir
        from package_common import DEFAULT_MANIFEST, manifest_template_path, load_manifest
        output = self.e.run / "existing-output"
        output.mkdir()
        sentinel = output / "old.docx"
        sentinel.write_bytes(b"byte-identical original output")
        args = ["--tasks-json", self.e.entries["content"]["path"], "--source-truth", self.e.entries["source_truth_manifest"]["path"],
            "--output-dir", str(output), "--backup-existing", "--run-id", "RUN-001", "--render",
            "--template", str(manifest_template_path(load_manifest(DEFAULT_MANIFEST))), "--manifest", str(DEFAULT_MANIFEST)]
        def stale_after_real_render(*a, **kw):
            result = validate_output_dir(*a, **kw)
            self.e.write("build-code", b"final stale mutation", protected=True)
            return result
        with patch("generate_lesson_plans.validate_output_dir", side_effect=stale_after_real_render):
            with self.assertRaises(ValueError):
                main(args, o2_run=run)
        self.assertEqual(sentinel.read_bytes(), b"byte-identical original output")
        self.assertEqual([sentinel], list(output.iterdir()))
        self.assertFalse(list(output.parent.glob(".existing-output.candidate-*")))
        self.assertFalse(list(output.parent.glob("_existing-output_backup_*")))

    def test_canonical_generation_actual_entry_point(self):
        self.authorize()
        output = self.e.run / "published"
        result = self.call("generate-production", output_dir=output)
        self.assertEqual(result["state"]["current_state"], "PRODUCTION_GENERATED")
        self.assertTrue(list((output / "render/pdf").glob("*.pdf")))
        self.assertEqual(self.call("validate-artifacts")["state"]["current_state"], "ARTIFACT_QA_PASSED")
        from tests.test_lesson_final_acceptance import synthetic_visual
        from types import SimpleNamespace
        run = self.call("prepare-visual-review")
        visual, evidence = synthetic_visual(SimpleNamespace(folder=self.e.run), run)
        self.call("bind-visual-review", visual_review=visual, visual_evidence=evidence)
        accepted = self.call("finalize-acceptance")
        self.assertEqual(accepted["state"]["current_state"], "ACCEPTED")
        self.assertEqual(accepted, self.call("status"))

    def test_installed_copy_external_controller_resume(self):
        self.ready()
        from install import install
        installed = install(pipeline.SKILL_ROOT, Path(self.temp.name) / "skills")
        # Import the installed modules first in a fresh interpreter. The source
        # path is listed only to prevent test fixture setup from prepending it.
        script = """
import sys, json
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[2], sys.argv[3]]
import run_lesson_pipeline as pipeline
import semantic_lifecycle
assert Path(pipeline.__file__).parent == Path(sys.argv[1])
assert Path(semantic_lifecycle.__file__).parent == Path(sys.argv[1])
from semantic_scope_records import Inventory, TrustContext
from datetime import datetime, timezone
config=json.loads(Path(sys.argv[4]).read_bytes())
def provider():
    inventory=Inventory(config['entries'], Path(config['run_root']), (Path(config['protected_root']),))
    return TrustContext(inventory, Path(config['profile']), config['pin'], 1, Path(config['index']), (('controller','controlled','1.0'),), datetime.now(timezone.utc))
with semantic_lifecycle.operator_context(provider):
    run=json.loads(Path(sys.argv[5]).read_bytes())
    # The installed inventory differs from the author's source tree; this is
    # intentionally stale and requires a new run/preproduction QA on installation.
    try: pipeline.execute('status', sys.argv[5])
    except ValueError as error: assert 'STALE' in str(error), str(error)
    else: raise AssertionError('source-run QA cannot grant installed authority')
    semantic_lifecycle.scope(run)
from tests.test_semantic_lifecycle import SemanticLifecycleTests
case=SemanticLifecycleTests('test_canonical_generation_actual_entry_point')
case.setUp()
try: case.test_canonical_generation_actual_entry_point()
finally: case.doCleanups()
"""
        ctx = self.e.context()
        config = self.e.run / "test-controller.json"
        _write_json(config, dict(entries={key:dict(row) for key,row in ctx.inventory.entries.items()}, run_root=str(self.e.run),
            protected_root=str(self.e.protected), profile=str(ctx.profile_path), pin=ctx.profile_pin, index=str(ctx.operation_index_path)))
        result = subprocess.run([sys.executable, "-B", "-c", script, str(installed / "scripts"), str(pipeline.SKILL_ROOT / "scripts"),
            str(Path(__file__).resolve().parents[1]), str(config), str(self.run)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_original_nc02_exact_bytes_and_historical_sources(self):
        from tests.semantic_scope_test_support import ROOT, FIXTURES
        from semantic_scope_review import validate_review
        original = ROOT / "tests/fixtures/lesson-original-nc02.json"
        self.assertEqual(sha256_file(original), "878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352")
        self.e.write("content", original.read_bytes())
        authority = self.e.run / "original-authority"
        shutil.copytree(FIXTURES / "N01/authority", authority)
        for key, path in (("source_truth_manifest", authority / "source-truth.json"), ("outline", authority / "evidence/whole-course-outline.json"),
            ("confirmed-profile", authority / "evidence/confirmed-profile.json")):
            self.e.add(key, path)
        historical_source_bytes = {
            key: Path(self.e.entries[key]["path"]).read_bytes()
            for key in ("source_truth_manifest", "outline", "confirmed-profile")
        }
        content = json.loads(original.read_bytes())
        content_bytes = json.dumps(content, ensure_ascii=False)
        self.assertIn("完成患者血压测量与护理判断。", content_bytes)
        self.assertIn("按无菌操作要求执行输液步骤并观察患者反应。", content_bytes)
        self.e.index["authors"] = []
        self.e.author(content, "content")
        self.e.review(pipeline="RUN-001", disposition="REVISION_REQUIRED")
        report = validate_review(self.e.context(), frozen_lesson_ids=[row["lesson_id"] for row in content["lessons"]], pipeline_run_id="RUN-001")
        self.assertEqual(report["whole_course_disposition"], "REVISION_REQUIRED")
        # Use a contract-valid, hash-bound synthetic waiver so this historical
        # input crosses every mandatory pre-semantic Production gate.
        self.qa()
        run = self.call("bind-semantic-scope-review")
        self.assertEqual(run["state"]["current_state"], "PREPRODUCTION_QA_PASSED")
        self.assertEqual(run["bindings"]["content"]["sha256"], "878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352")
        self.assertEqual(run["bindings"]["benchmark_evidence"]["sha256"], sha256_file(self.e.run / "waiver.json"))
        self.assertEqual(run["bindings"]["benchmark_disposition"]["sha256"], run["state"]["artifacts"]["benchmark_disposition_sha256"])
        self.assertEqual(run["bindings"]["semantic_scope_review"]["sha256"], self.e.sha("semantic_scope_review"))
        waiver = json.loads(Path(run["bindings"]["benchmark_evidence"]["path"]).read_bytes())
        disposition = json.loads(Path(run["bindings"]["benchmark_disposition"]["path"]).read_bytes())
        self.assertEqual(waiver["decision"], "WAIVED_BY_USER")
        self.assertEqual(waiver["source_truth_manifest_sha256"], run["bindings"]["source_truth"]["sha256"])
        self.assertEqual(waiver["content_sha256"], run["bindings"]["content"]["sha256"])
        self.assertEqual(disposition["benchmark"]["disposition"], "BENCHMARK_WAIVED_BY_USER")
        self.assertEqual(disposition["benchmark"]["evidence_sha256"], run["bindings"]["benchmark_evidence"]["sha256"])
        before_ready = self.run.read_bytes()
        with self.assertRaisesRegex(LifecycleContractError, "semantic REVISION_REQUIRED blocks READY"):
            self.call("ready-for-teacher-review")
        self.assertEqual(before_ready, self.run.read_bytes())
        blocked = self.call("status")
        self.assertEqual(blocked["state"]["current_state"], "PREPRODUCTION_QA_PASSED")
        self.assertFalse({"teacher_review_packet", "teacher_review", "teacher_approval_receipt",
                          "production_authorization", "artifact_manifest", "artifact_qa", "acceptance"}
                         & set(blocked["bindings"]))
        self.reject("authorize-production", authorization=self.e.run / "missing-pa.json")
        output = self.e.run / "output"
        output.mkdir()
        sentinel = output / "original-output.bin"
        sentinel.write_bytes(b"original NC-02 output sentinel")
        self.reject("generate-production", output_dir=output)
        self.assertEqual(sentinel.read_bytes(), b"original NC-02 output sentinel")
        self.assertEqual(list(output.iterdir()), [sentinel])
        self.assertFalse(list(output.parent.glob(".output.candidate-*")))
        self.assertFalse(list(output.parent.glob("_output_backup_*")))
        self.assertEqual(original.read_bytes(), Path(self.e.entries["content"]["path"]).read_bytes())
        self.assertEqual(sha256_file(original), "878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352")
        for key, raw in historical_source_bytes.items():
            self.assertEqual(Path(self.e.entries[key]["path"]).read_bytes(), raw)

    def test_teacher_review_packet_cli_reports_validated_contract_version(self):
        from tests.test_lesson_pipeline import PipelineTests

        cli = pipeline.SKILL_ROOT / "scripts/teacher_review_packet.py"
        legacy = PipelineTests("test_unavailable_disposition_direct_ready")
        legacy.setUp()
        try:
            legacy.qa()
            disposition, evidence, _ = legacy.disposition()
            legacy.call("bind-benchmark-disposition", disposition=disposition, benchmark_evidence=evidence)
            legacy_run = legacy.call("prepare-teacher-review")
            legacy_packet = pipeline.path_of(legacy_run, "teacher_review_packet")
            self.assertEqual(json.loads(legacy_packet.read_bytes())["contract_version"], "1.0")
            legacy_result = subprocess.run(
                [sys.executable, "-B", str(cli), "--run", str(legacy.run), "--packet", str(legacy_packet)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(legacy_result.returncode, 0, legacy_result.stdout + legacy_result.stderr)
            self.assertEqual(json.loads(legacy_result.stdout), {"status": "VALID", "contract_version": "1.0"})
        finally:
            legacy.doCleanups()

        o2_run = self.ready()
        o2_run = self.call("prepare-teacher-review")
        o2_packet = pipeline.path_of(o2_run, "teacher_review_packet")
        self.assertEqual(json.loads(o2_packet.read_bytes())["contract_version"], "2.0")
        context = self.e.context()
        config = self.e.run / "teacher-packet-cli-controller.json"
        _write_json(config, dict(
            entries={key: dict(row) for key, row in context.inventory.entries.items()},
            run_root=str(self.e.run),
            protected_root=str(self.e.protected),
            profile=str(context.profile_path),
            pin=context.profile_pin,
            index=str(context.operation_index_path),
        ))
        script = """
import json, runpy, sys
from datetime import datetime, timezone
from pathlib import Path
config_path, cli_path, run_path, packet_path = map(Path, sys.argv[1:])
sys.path.insert(0, str(cli_path.parent))
from semantic_scope_records import Inventory, TrustContext
import semantic_lifecycle
config = json.loads(config_path.read_bytes())
def provider():
    inventory = Inventory(config['entries'], Path(config['run_root']), (Path(config['protected_root']),))
    return TrustContext(inventory, Path(config['profile']), config['pin'], 1, Path(config['index']),
        (('controller', 'controlled', '1.0'),), datetime.now(timezone.utc))
with semantic_lifecycle.operator_context(provider):
    sys.argv = [str(cli_path), '--run', str(run_path), '--packet', str(packet_path)]
    runpy.run_path(str(cli_path), run_name='__main__')
"""
        o2_result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(config), str(cli), str(self.run), str(o2_packet)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(o2_result.returncode, 0, o2_result.stdout + o2_result.stderr)
        self.assertEqual(json.loads(o2_result.stdout), {"status": "VALID", "contract_version": "2.0"})

    def test_missing_human_resolution_blocks_approval(self):
        with self.assertRaises(ValueError):
            self.approve("HUMAN_REVIEW_REQUIRED", mutate=lambda review: review["semantic_scope"].update(resolutions=[]))
        self.assertEqual(self.call("status")["state"]["current_state"], "READY_FOR_TEACHER_REVIEW")

    def test_duplicate_human_resolution_blocks_approval(self):
        def duplicate(review):
            review["semantic_scope"]["resolutions"] *= 2
        with self.assertRaises(ValueError):
            self.approve("HUMAN_REVIEW_REQUIRED", mutate=duplicate)
        self.assertEqual(self.call("status")["state"]["current_state"], "READY_FOR_TEACHER_REVIEW")

    def test_human_revision_blocks_approval(self):
        def revision(review):
            review["semantic_scope"]["resolutions"][0]["decision"] = "REVISION_REQUIRED"
        with self.assertRaises(ValueError):
            self.approve("HUMAN_REVIEW_REQUIRED", mutate=revision)
        self.assertEqual(self.call("status")["state"]["current_state"], "READY_FOR_TEACHER_REVIEW")

    def test_legacy_teacher_cannot_downgrade_o2(self):
        def downgrade(review):
            review.pop("semantic_scope")
            review["contract_version"] = "1.0"
        with self.assertRaises(ValueError):
            self.approve(mutate=downgrade)

    def test_o2_dependency_graph_is_transitive(self):
        from pipeline_state import stale_downstream
        for key in ("outline", "reviewer_configuration", "qualification_approval_receipt", "authority_profile", "semantic_scope_operation_receipt"):
            self.assertTrue({"teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"} <= stale_downstream(key, contract_version="2.0"))

    def test_forged_run_cannot_omit_immutable_authority_dependency(self):
        run = self.ready()
        run["semantic_dependency_inventory"] = [row for row in run["semantic_dependency_inventory"] if row["inventory_key"] != "ingress"]
        run["run_fingerprint"] = pipeline.envelope_fingerprint(run)
        _write_json(self.run, run)
        self.reject("status")

    def test_generator_rejects_fixture_bypass_before_candidate_creation(self):
        run = self.authorize()
        from generate_lesson_plans import main
        output = self.e.run / "not-created"
        with self.assertRaisesRegex(ValueError, "all existing gates"):
            main(["--tasks-json", self.e.entries["content"]["path"], "--source-truth", self.e.entries["source_truth_manifest"]["path"],
                "--output-dir", str(output), "--run-id", "RUN-001", "--render", "--allow-test-fixture-authoring"], o2_run=run)
        self.assertFalse(output.exists())

    def test_ci_job_is_required_with_unchanged_core_timeout(self):
        import yaml
        from tests.semantic_scope_test_support import ROOT
        jobs = yaml.safe_load((ROOT / ".github/workflows/template-package-ci.yml").read_text())["jobs"]
        self.assertEqual(jobs["template-lesson"]["timeout-minutes"], 35)
        step = jobs["ci-gate"]["steps"][0]
        for lane in ("render", "evidence"):
            job = "lesson-semantic-lifecycle-" + lane
            self.assertIn(job, jobs["ci-gate"]["needs"])
            result_key = "SEMANTIC_LIFECYCLE_" + lane.upper() + "_RESULT"
            self.assertEqual(step["env"][result_key], "${{ needs." + job + ".result }}")
            self.assertIn(f'check_job {job} "$RUN_LESSON" "${result_key}"', step["run"])
        render_job = jobs["lesson-semantic-lifecycle-render"]
        self.assertEqual(render_job["timeout-minutes"], 30)
        self.assertEqual(
            {
                (row["lane"], row["suite"], row["os"])
                for row in render_job["strategy"]["matrix"]["include"]
            },
            {
                ("canonical-generation", "lesson-semantic-lifecycle-canonical", os_name)
                for os_name in ("macos-14", "windows-latest")
            }
            | {
                ("installed-copy", "lesson-semantic-lifecycle-installed", os_name)
                for os_name in ("macos-14", "windows-latest")
            }
            | {
                ("final-rollback", "lesson-semantic-lifecycle-rollback", os_name)
                for os_name in ("macos-14", "windows-latest")
            },
        )
        self.assertEqual(jobs["lesson-semantic-lifecycle-evidence"]["timeout-minutes"], 30)

    def test_completed_benchmark_cannot_skip_semantic_readiness(self):
        from tests.test_lesson_pipeline import PipelineTests
        h = PipelineTests()
        h.folder = self.e.run
        h.run = self.run
        h.source_path = Path(self.e.entries["source_truth_manifest"]["path"])
        h.content_path = Path(self.e.entries["content"]["path"])
        h.source = json.loads(h.source_path.read_bytes())
        h.call = self.call
        self.call("init", mode="PRODUCTION", run_id="RUN-001", source_truth=h.source_path, orchestrator_version="2.0")
        disposition, kwargs, _ = h.full_review()
        run = self.call("bind-benchmark-review", disposition=disposition, **kwargs)
        self.assertEqual(run["state"]["current_state"], "BENCHMARK_REVIEW_COMPLETE")
        self.reject("ready-for-teacher-review")
        self.call("bind-semantic-scope-review")
        self.assertEqual(self.call("ready-for-teacher-review")["state"]["current_state"], "READY_FOR_TEACHER_REVIEW")

    def test_whole_course_32_lesson_packet_includes_unselected_ambiguity(self):
        from tests.test_lesson_content_v23 import _integrated_64
        from tests.semantic_scope_fixtures import freeze_original_outline
        from teacher_review_packet import _selection
        from semantic_scope_records import review_fingerprint
        # Fresh production-compatible synthetic authoring record. The frozen O1
        # P12 fixture deliberately uses synthetic fixture mode and is unchanged;
        # it must never bypass the actual Content production validator.
        content = _integrated_64(workorders=False)
        content["authoring_provenance"]["mode"] = "agent"
        content["authoring_provenance"]["authoring_id"] = "synthetic-o2-32-lesson-authoring"
        self.e.write("content", content)
        manifest = freeze_original_outline(self.e.run / "integrated-32-authority", content)
        for key, path in (("source_truth_manifest", manifest), ("outline", manifest.parent / "evidence/whole-course-outline.json"),
            ("confirmed-profile", manifest.parent / "evidence/confirmed-profile.json")):
            self.e.add(key, path)
        self.assertEqual(len(content["lessons"]), 32)
        self.e.index["authors"] = []
        self.e.author(content, "content")
        selected = {row["lesson_id"] for row in _selection(content)}
        index = next(i for i,row in enumerate(content["lessons"]) if row["lesson_id"] not in selected)
        report = self.e.review(pipeline="RUN-001", disposition="HUMAN_REVIEW_REQUIRED")
        issue = report["lessons"][0]["issues"].pop()
        report["lessons"][0]["disposition"] = "PASS"
        excerpt = content["lessons"][index]["teaching_content"][0][:100]
        issue["bounded_excerpt"] = excerpt
        issue["location"]["end"] = len(excerpt)
        report["lessons"][index]["issues"] = [issue]
        report["lessons"][index]["disposition"] = "HUMAN_REVIEW_REQUIRED"
        report["review_fingerprint"] = review_fingerprint(report)
        self.e.write("semantic_scope_review", report)
        self.e.receipt("semantic_scope_operation_receipt", "semantic_scope", "semantic_scope_review",
            {key:self.e.sha(key) for key in ("source_truth_manifest", "outline", "content", "reviewer_configuration", "reviewer_qualification")},
            "review-op", "reviewer", pipeline="RUN-001")
        self.qa()
        self.call("bind-semantic-scope-review")
        self.call("ready-for-teacher-review")
        run = self.call("prepare-teacher-review")
        packet = json.loads(pipeline.path_of(run, "teacher_review_packet").read_bytes())
        self.assertEqual(len(packet["selected_lessons"]), 6)
        self.assertEqual(len(packet["course_map"]), 32)
        self.assertNotIn(content["lessons"][index]["lesson_id"], {row["lesson_id"] for row in packet["selected_lessons"]})
        self.assertEqual(packet["semantic_scope"]["issue_index"][0]["lesson_id"], content["lessons"][index]["lesson_id"])

    def test_frozen_scope_controls_at_actual_o2_entry_points(self):
        from tests.semantic_scope_test_support import FIXTURES
        from semantic_scope_review import validate_review
        cases = (("N02", "REVISION_REQUIRED"), ("N03", "REVISION_REQUIRED"), ("N04", "REVISION_REQUIRED"),
            ("N05", "REVISION_REQUIRED"), ("N06", "REVISION_REQUIRED"), ("P07", "PASS"), ("P08", "PASS"),
            ("P09", "PASS"), ("P10", "PASS"), ("P11", "PASS"), ("A13", "HUMAN_REVIEW_REQUIRED"), ("P14", "PASS"))
        original_e, original_run = self.e, self.run
        try:
            for case, disposition in cases:
                with self.subTest(case=case):
                    root = Path(self.temp.name) / case
                    root.mkdir()
                    self.e = Evidence(root)
                    self.run = self.e.run / "run.json"
                    fixture = FIXTURES / case
                    content = json.loads((fixture / "content.json").read_bytes())
                    # O1 deliberately freezes minimal single-node claims. Build
                    # a fresh complete production input around the unchanged
                    # exact claim, retaining its frozen SQL task/output scope.
                    for lesson in content["lessons"]:
                        if len(lesson["teaching_content"]) == 1:
                            lesson["teaching_content"].extend([
                                "围绕本课分配的数据库查询与索引维护任务，核对 SQL 查询条件并记录查询与索引维护结果。",
                                "比较 SQL 查询结果与原始记录，解释索引对检索的作用并复核本课查询与索引维护记录。",
                            ])
                    from tests.test_lesson_content_v22 import _refresh_review_digests
                    _refresh_review_digests(content)
                    # Fresh synthetic production-compatible authoring operation;
                    # golden files and frozen Source Truth/outline are untouched.
                    content["authoring_provenance"]["mode"] = "agent"
                    content["authoring_provenance"]["authoring_id"] = "synthetic-o2-" + case + "-authoring"
                    self.e.write("content", content)
                    authority = self.e.run / "frozen-case-authority"
                    shutil.copytree(fixture / "authority", authority)
                    for key, path in (("source_truth_manifest", authority / "source-truth.json"), ("outline", authority / "evidence/whole-course-outline.json"),
                        ("confirmed-profile", authority / "evidence/confirmed-profile.json")):
                        self.e.add(key, path)
                    self.e.index["authors"] = []
                    self.e.author(content, "content")
                    self.e.review(pipeline="RUN-001", disposition=disposition)
                    with operator_context(self.e.context):
                        report = validate_review(self.e.context(), frozen_lesson_ids=[row["lesson_id"] for row in content["lessons"]], pipeline_run_id="RUN-001")
                        self.assertEqual(report["whole_course_disposition"], disposition)
                        if disposition == "REVISION_REQUIRED":
                            try:
                                self.qa()
                            except ValueError:
                                pass  # Existing mandatory Content/QA rejection is also a closed boundary.
                            else:
                                self.call("bind-semantic-scope-review")
                                self.reject("ready-for-teacher-review")
                            self.reject("authorize-production", authorization=self.e.run / "missing-pa.json")
                            self.reject("generate-production", output_dir=self.e.run / "output")
                        else:
                            self.qa()
                            self.call("bind-semantic-scope-review")
                            self.assertEqual(self.call("ready-for-teacher-review")["state"]["current_state"], "READY_FOR_TEACHER_REVIEW")
                            self.reject("authorize-production", authorization=self.e.run / "missing-pa.json")
        finally:
            self.e, self.run = original_e, original_run
