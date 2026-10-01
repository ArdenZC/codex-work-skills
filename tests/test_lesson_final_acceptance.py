"""SYNTHETIC authority-linkage closure; never real human/teaching acceptance.

The shared fixture invokes the canonical generator with real retained render,
then all tests restore its actual bytes. No DOCX/PDF fixtures are fabricated.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import tests.test_lesson_pipeline as pipeline_tests
from tests.test_lesson_lifecycle_contracts import _write_json, _production_authorization
from lifecycle_digest import LifecycleContractError, sha256_file, schema_errors
from teacher_review import teacher_review_fingerprint
import run_lesson_pipeline as pipeline
import acceptance_v3 as acceptance
import visual_review_authority as visual
from visual_sampling import visual_sample_selection
from final_artifacts import validate_run_artifacts
from record_visual_inspection import CHECK_NAMES, write_visual_inspection_evidence


def synthetic_visual(h, run, *, failed=False, pages=None):
    packet = json.loads(pipeline.path_of(run, "visual_review_packet").read_bytes())
    evidence = h.folder / "synthetic-visual-inspection.json"
    inspected = pages if pages is not None else {row["file"]: row["required_pages"] for row in packet["required_sample"]}
    checks = {name: "passed" for name in CHECK_NAMES}
    if failed: checks["clipping"] = "failed"
    write_visual_inspection_evidence(output_dir=pipeline.path_of(run, "final_output"),
        qa_report=pipeline.path_of(run, "artifact_qa"), destination=evidence,
        status="failed" if failed else "passed", inspected_pages=inspected, checks=checks,
        notes="SYNTHETIC contract closure only; not actual human visual acceptance")
    authority = visual.build_visual_review_authority(run, evidence_path=evidence,
        decision="REVISION_REQUIRED" if failed else "PASSED", notes="SYNTHETIC externally supplied visual judgment")
    path = h.folder / "synthetic-visual-authority.json"
    _write_json(path, authority)
    return path, evidence


class SamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads((Path(__file__).parent / "fixtures/lesson_visual_sampling_v2_golden.json").read_bytes())

    def test_reviewed_acceptance_v2_golden_outputs_unchanged(self):
        from lesson_acceptance import visual_sample_selection as legacy
        self.assertIs(legacy, visual_sample_selection)
        for case in self.golden["cases"]:
            with self.subTest(count=len(case["data"]["lessons"])):
                args = [case[key] for key in ("data", "qa", "inventory", "manifest")]
                self.assertEqual(visual_sample_selection(*args), case["expected"])

    def sample(self):
        case = self.golden["cases"][-1]
        return visual_sample_selection(*(case[k] for k in ("data", "qa", "inventory", "manifest")))

    def positions(self, reason):
        return [int(row["lesson_id"][1:]) for row in self.sample()["sample"] if reason in row["reasons"]]

    def test_repeat_deterministic(self): self.assertEqual(self.sample(), self.sample())
    def test_first_last(self):
        self.assertEqual(self.positions("first_lesson"), [1])
        self.assertEqual(self.positions("last_lesson"), [32])
    def test_boundaries(self):
        self.assertEqual(self.positions("boundary_before"), [8, 16, 24])
        self.assertEqual(self.positions("boundary_after"), [9, 17, 25])
    def test_project_representatives(self): self.assertEqual(self.positions("each_project"), [1, 9, 17, 25])
    def test_maximum_content(self): self.assertEqual(len(self.positions("maximum_content_chars")), 1)
    def test_maximum_implementation(self): self.assertEqual(len(self.positions("maximum_implementation_density")), 1)
    def test_maximum_evaluation(self): self.assertEqual(self.positions("maximum_evaluation_density"), [11])
    def test_maximum_pages(self): self.assertEqual(self.positions("maximum_pages"), [5, 10, 15, 20, 25, 30])
    def test_supplemental_seeded(self):
        self.assertEqual(len(self.positions("deterministic_random_10_to_20_percent")), 5)
    def test_page_plan_one(self): self.assertEqual(visual.required_pages(1), [1])
    def test_page_plan_two(self): self.assertEqual(visual.required_pages(2), [1, 2])
    def test_page_plan_three_or_more(self):
        for count, expected in ((3, [1,2,3]), (5, [1,3,5]), (6, [1,3,6])):
            self.assertEqual(visual.required_pages(count), expected)
    def test_page_plan_rejects_invalid(self):
        for count in (0, -1, True, 2.0):
            with self.assertRaises(ValueError): visual.required_pages(count)


class FinalLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = pipeline_tests.PipelineTests()
        cls.h.setUp()
        cls.addClassCleanup(cls.h.doCleanups)
        cls.snapshots = {}
        cls.snapshots["authorized"] = cls.h.authorize()
        for command, stage in (("generate-production", "generated"), ("validate-artifacts", "qa"), ("prepare-visual-review", "packet")):
            cls.snapshots[stage] = cls.h.call(command)
        authority, evidence = synthetic_visual(cls.h, cls.snapshots["packet"])
        cls.snapshots["visual"] = cls.h.call("bind-visual-review", visual_review=authority, visual_evidence=evidence)
        cls.snapshots["accepted"] = cls.h.call("finalize-acceptance")
        cls.frozen = {p.relative_to(cls.h.folder): p.read_bytes() for p in cls.h.folder.rglob("*") if p.is_file()}

    def setUp(self):
        # All test mutations stay in this owned temporary workspace. Restoring
        # actual generated evidence avoids repeated render or forged byte fixtures.
        self.h = type(self).h
        self.restore()
        self.addCleanup(self.restore)
        self.choose("packet")

    def restore(self):
        for p in self.h.folder.iterdir():
            if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
            else: p.unlink()
        for relative, raw in self.frozen.items():
            path = self.h.folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def choose(self, stage):
        self.run = copy.deepcopy(self.snapshots[stage])
        _write_json(self.h.run, self.run)
        return self.run

    def reject(self, command, **options):
        before = self.h.run.read_bytes()
        with self.assertRaises((ValueError, RuntimeError, OSError, KeyError, TypeError)):
            self.h.call(command, **options)
        self.assertEqual(before, self.h.run.read_bytes())

    def path(self, name): return pipeline.path_of(self.run, name)
    def report(self, **options): return acceptance.evaluate(self.run, **options)
    def mutate(self, path): path.write_bytes(path.read_bytes() + b"\nSYNTHETIC mutation")

    def test_real_orchestrated_generated_to_accepted_with_notes(self):
        run = self.choose("accepted")
        self.assertEqual(self.h.call("status"), run)
        report = self.report()
        self.assertEqual(report["final_status"], "ACCEPTED_WITH_NOTES")
        self.assertEqual(report["limitations"], ["BENCHMARK_UNAVAILABLE"])
        self.assertEqual({r["status"] for r in report["gate_matrix"]}, {"PASS"})
        self.assertEqual(report["final_artifact_inventory"]["docx_count"], 1)
        self.assertEqual(report["final_artifact_inventory"]["pdf_count"], 1)
        self.assertGreater(report["final_artifact_inventory"]["pdf_total_pages"], 0)
        self.assertEqual(schema_errors(report, "lesson-acceptance-v3.schema.json"), [])

    def test_actual_transition_evidence(self):
        run = self.choose("accepted")
        expected = {"PRODUCTION_GENERATED": "artifact_manifest_sha256", "ARTIFACT_QA_PASSED": "artifact_qa_sha256",
                    "VISUAL_REVIEW_APPROVED": "visual_review_sha256", "ACCEPTED": "acceptance_sha256"}
        for row in run["state"]["transitions"]:
            if row["to_state"] in expected:
                self.assertEqual(row["evidence_sha256"], run["state"]["artifacts"][expected[row["to_state"]]] )

    def test_preview_generation_rejected(self):
        self.choose("authorized")
        # A separate legitimate PREVIEW starts at intake; it never claims authorization.
        other = self.h.folder / "preview.json"
        pipeline.execute("init", other, mode="PREVIEW", run_id="SYNTHETIC-PREVIEW", source_truth=self.h.source_path)
        with self.assertRaises(ValueError): pipeline.execute("generate-production", other)

    def test_generation_before_authorization_rejected(self):
        other = self.h.folder / "early.json"
        pipeline.execute("init", other, mode="PRODUCTION", run_id="SYNTHETIC-EARLY", source_truth=self.h.source_path)
        with self.assertRaises(ValueError): pipeline.execute("generate-production", other)

    def test_generator_failure_state_unchanged(self):
        self.choose("authorized")
        with patch("subprocess.run", wraps=subprocess.run) as call:
            # Intercept only canonical generator invocation; real upstream/runtime
            # validation still runs, including git commands used by Authorization.
            original = subprocess.run
            def invoke(args, **kwargs):
                if any(str(x).endswith("generate_lesson_plans.py") for x in args):
                    return subprocess.CompletedProcess(args, 1, "", "SYNTHETIC injected generator failure")
                return original(args, **kwargs)
            call.side_effect = invoke
            self.reject("generate-production", output_dir=self.h.folder / "failure-final")

    def test_generator_exit_zero_without_manifest_cannot_advance(self):
        self.choose("authorized")
        original = subprocess.run
        def invoke(args, **kwargs):
            if any(str(x).endswith("generate_lesson_plans.py") for x in args):
                return subprocess.CompletedProcess(args, 0, "SYNTHETIC empty success", "")
            return original(args, **kwargs)
        with patch("subprocess.run", side_effect=invoke):
            self.reject("generate-production", output_dir=self.h.folder / "missing-manifest-final")

    def test_output_symlink_escape_rejected(self):
        self.choose("authorized")
        alias = self.h.folder / "symlink-output"
        try:
            alias.symlink_to(self.h.folder.parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest("platform does not permit directory symlinks: " + str(exc))
        self.reject("generate-production", output_dir=alias / "SYNTHETIC-final")

    def test_stale_authorization_generation_rejected(self):
        self.choose("authorized")
        self.mutate(self.path("production_authorization"))
        self.reject("generate-production", output_dir=self.h.folder / "new-final")

    def test_generator_bound_canonical_entrypoint(self):
        self.assertIn("generate_lesson_plans.py", (pipeline.SKILL_ROOT / "scripts/run_lesson_pipeline.py").read_text())
        self.choose("generated")
        self.assertEqual(self.path("artifact_manifest").parent, self.path("final_output"))
        self.assertEqual(self.path("artifact_qa"), self.path("final_output") / "qa-report.json")

    def test_valid_artifact_qa_transition(self):
        self.choose("generated")
        result = self.h.call("validate-artifacts")
        self.assertEqual(result["state"]["current_state"], "ARTIFACT_QA_PASSED")
        self.assertEqual(result["state"]["artifacts"]["artifact_qa_sha256"], sha256_file(self.path("artifact_qa")))

    def artifact_path(self, field):
        manifest = json.loads(self.path("artifact_manifest").read_bytes())
        return self.path("final_output") / manifest["artifacts"][0][field]

    def test_changed_docx_rejected(self):
        self.choose("generated"); self.mutate(self.artifact_path("final_docx_path")); self.reject("validate-artifacts")
    def test_changed_pdf_rejected(self):
        self.choose("generated"); self.mutate(self.artifact_path("final_pdf_path")); self.reject("validate-artifacts")
    def test_missing_pdf_rejected(self):
        self.choose("generated"); self.artifact_path("final_pdf_path").unlink(); self.reject("validate-artifacts")
    def test_qa_bytes_change_rejected(self):
        self.choose("generated"); self.mutate(self.path("artifact_qa")); self.reject("validate-artifacts")
    def test_manifest_change_rejected(self):
        self.choose("generated"); self.mutate(self.path("artifact_manifest")); self.reject("validate-artifacts")
    def test_extra_docx_rejected(self):
        self.choose("generated"); (self.path("final_output") / "extra.docx").write_bytes(b"SYNTHETIC unexpected"); self.reject("validate-artifacts")
    def test_extra_pdf_rejected(self):
        self.choose("generated"); (self.path("final_output") / "extra.pdf").write_bytes(b"SYNTHETIC unexpected"); self.reject("validate-artifacts")

    def test_unrendered_manifest_cannot_pass_final(self):
        self.choose("generated")
        manifest = json.loads(self.path("artifact_manifest").read_bytes())
        qa = json.loads(self.path("artifact_qa").read_bytes())
        manifest["render_status"] = "not_executed"; qa["render"]["status"] = "not_executed"
        _write_json(self.path("artifact_manifest"), manifest); _write_json(self.path("artifact_qa"), qa)
        with self.assertRaises((ValueError,RuntimeError)): validate_run_artifacts(self.run)

    def test_actual_manifest_verifier_rejects_hash_even_if_binding_recomputed(self):
        self.choose("generated")
        manifest = json.loads(self.path("artifact_manifest").read_bytes())
        manifest["artifacts"][0]["final_pdf_sha256"] = "0" * 64
        _write_json(self.path("artifact_manifest"), manifest)
        with self.assertRaises((ValueError,RuntimeError)): validate_run_artifacts(self.run)

    def test_canonical_output_never_overwrites_previous(self):
        self.choose("authorized")
        old = self.path("content").read_bytes()
        self.reject("generate-production", output_dir=self.path("content").parent)
        self.assertEqual(old, self.path("content").read_bytes())

    def test_output_workspace_escape_rejected(self):
        self.choose("authorized"); self.reject("generate-production", output_dir=self.h.folder / ".." / "SYNTHETIC-outside")

    def test_sidecar_output_cannot_alias_actual_source_bytes(self):
        self.choose("qa")
        from source_truth import source_truth_local_file_paths
        source = json.loads(self.path("source_truth").read_bytes())
        destination = next(iter(source_truth_local_file_paths(source, self.path("source_truth")).values()))
        old = destination.read_bytes()
        packet_path = pipeline.path_of(self.snapshots["packet"], "visual_review_packet")
        payload = json.loads(packet_path.read_bytes())
        with self.assertRaises(ValueError):
            pipeline.publish_sidecar(self.run, self.h.run, "visual_review_packet", destination, payload)
        self.assertEqual(destination.read_bytes(), old)

    def test_packet_preparation_no_transition(self):
        self.choose("qa"); before = copy.deepcopy(self.run["state"])
        result = self.h.call("prepare-visual-review")
        self.assertEqual(result["state"], before)
        self.assertIn("visual_review_packet", result["bindings"])

    def test_packet_preparation_is_atomic(self):
        self.choose("qa"); path = self.h.folder / (self.h.run.stem + "-visual-review-packet.json")
        old = path.read_bytes()
        with patch.object(pipeline, "_replace_bundle", side_effect=OSError("SYNTHETIC publication failure")):
            self.reject("prepare-visual-review")
        self.assertEqual(path.read_bytes(), old)

    def test_packet_repreparation_rejected(self): self.reject("prepare-visual-review")

    def test_sample_files_are_manifest_bound(self):
        packet = visual.validate_visual_review_packet(self.path("visual_review_packet"), self.run)
        manifest = json.loads(self.path("artifact_manifest").read_bytes())
        records = {r["final_docx_path"]: r for r in manifest["artifacts"]}
        for row in packet["required_sample"]:
            self.assertEqual(row["lesson_id"], records[row["file"]]["lesson_id"])
            self.assertEqual(row["pdf_file"], records[row["file"]]["final_pdf_path"])

    def test_fake_packet_fingerprint_cannot_choose_file(self):
        packet = json.loads(self.path("visual_review_packet").read_bytes())
        packet["required_sample"][0]["file"] = "unbound.docx"
        packet["packet_fingerprint"] = visual.fingerprint(packet, "packet_fingerprint")
        _write_json(self.path("visual_review_packet"), packet)
        self.run["bindings"]["visual_review_packet"]["sha256"] = sha256_file(self.path("visual_review_packet"))
        self.run["run_fingerprint"] = pipeline.envelope_fingerprint(self.run)
        with self.assertRaisesRegex(ValueError, "exact current rederivation"):
            visual.validate_visual_review_packet(self.path("visual_review_packet"), self.run)

    def test_recomputed_packet_cannot_reduce_required_pages(self):
        packet = json.loads(self.path("visual_review_packet").read_bytes())
        packet["required_sample"][0]["required_pages"] = [1]
        if packet["required_sample"][0]["page_count"] == 1:
            packet["required_sample"][0]["page_count"] = 2
        packet["packet_fingerprint"] = visual.fingerprint(packet, "packet_fingerprint")
        _write_json(self.path("visual_review_packet"), packet)
        self.run["bindings"]["visual_review_packet"]["sha256"] = sha256_file(self.path("visual_review_packet"))
        self.run["run_fingerprint"] = pipeline.envelope_fingerprint(self.run)
        with self.assertRaisesRegex(ValueError, "exact current rederivation"):
            visual.validate_visual_review_packet(self.path("visual_review_packet"), self.run)

    def test_nested_uppercase_pdf_is_unexpected_inventory(self):
        self.choose("generated")
        nested = self.path("final_output") / "nested"
        nested.mkdir()
        (nested / "EXTRA.PDF").write_bytes(b"SYNTHETIC unexpected inventory")
        with self.assertRaises((ValueError, RuntimeError)):
            validate_run_artifacts(self.run)

    def test_required_page_missing_rejected(self):
        packet = json.loads(self.path("visual_review_packet").read_bytes())
        pages = {r["file"]: r["required_pages"][:-1] for r in packet["required_sample"]}
        with self.assertRaises(ValueError): synthetic_visual(self.h, self.run, pages=pages)

    def test_required_file_missing_rejected(self):
        authority, evidence = synthetic_visual(self.h, self.run)
        data = json.loads(evidence.read_bytes()); data["inspected_files"] = []; data["inspected_pages"] = {}
        _write_json(evidence,data)
        with self.assertRaises(ValueError): visual.validate_visual_review_authority(authority,self.run,evidence)

    def test_extra_inspected_pages_allowed(self):
        packet = json.loads(self.path("visual_review_packet").read_bytes())
        pages = {r["file"]: list(range(1,r["page_count"]+1)) for r in packet["required_sample"]}
        authority,evidence=synthetic_visual(self.h,self.run,pages=pages)
        self.assertEqual(visual.validate_visual_review_authority(authority,self.run,evidence)["decision"],"PASSED")

    def test_arbitrary_passed_json_rejected(self):
        fake=self.h.folder/'fake-authority.json';_write_json(fake,{'decision':'PASSED'})
        evidence=self.h.folder/'synthetic-visual-inspection.json'
        self.reject('bind-visual-review',visual_review=fake,visual_evidence=evidence)

    def test_failed_check_cannot_claim_passed_authority(self):
        authority,evidence=synthetic_visual(self.h,self.run,failed=True)
        payload=json.loads(authority.read_bytes());payload['decision']='PASSED'
        payload['authority_fingerprint']=visual.fingerprint(payload,'authority_fingerprint');_write_json(authority,payload)
        with self.assertRaises(ValueError):visual.validate_visual_review_authority(authority,self.run,evidence)

    def test_passed_checks_cannot_claim_revision(self):
        authority,evidence=synthetic_visual(self.h,self.run)
        with self.assertRaises(ValueError):visual.build_visual_review_authority(self.run,evidence_path=evidence,decision='REVISION_REQUIRED',notes='SYNTHETIC')

    def test_valid_visual_revision_diagnostic_and_no_transition(self):
        authority,evidence=synthetic_visual(self.h,self.run,failed=True)
        self.assertEqual(self.report(diagnostic_inputs={'visual_review':authority,'visual_evidence':evidence})['final_status'],'REVISION_REQUIRED')
        self.reject('bind-visual-review',visual_review=authority,visual_evidence=evidence)

    def test_wrong_run_visual_authority_rejected(self):
        authority,evidence=synthetic_visual(self.h,self.run)
        payload=json.loads(authority.read_bytes());payload['pipeline_run_id']='SYNTHETIC-WRONG'
        payload['authority_fingerprint']=visual.fingerprint(payload,'authority_fingerprint');_write_json(authority,payload)
        with self.assertRaises(ValueError):visual.validate_visual_review_authority(authority,self.run,evidence)

    def test_visual_evidence_change_stale(self):
        authority,evidence=synthetic_visual(self.h,self.run);self.mutate(evidence)
        with self.assertRaises(ValueError):visual.validate_visual_review_authority(authority,self.run,evidence)
    def test_pdf_changed_after_inspection_stale(self):
        authority,evidence=synthetic_visual(self.h,self.run);self.mutate(self.artifact_path('final_pdf_path'))
        with self.assertRaises((ValueError,RuntimeError)):visual.validate_visual_review_authority(authority,self.run,evidence)
    def test_docx_changed_after_inspection_stale(self):
        authority,evidence=synthetic_visual(self.h,self.run);self.mutate(self.artifact_path('final_docx_path'))
        with self.assertRaises((ValueError,RuntimeError)):visual.validate_visual_review_authority(authority,self.run,evidence)
    def test_qa_changed_after_inspection_stale(self):
        authority,evidence=synthetic_visual(self.h,self.run);self.mutate(self.path('artifact_qa'))
        with self.assertRaises(ValueError):visual.validate_visual_review_authority(authority,self.run,evidence)

    def test_missing_visual_pending(self):self.assertEqual(self.report()['final_status'],'PENDING_REVIEW')
    def test_generator_pass_alone_not_accepted(self):
        self.choose('generated');self.assertEqual(self.report()['final_status'],'PENDING_REVIEW')
    def test_evaluate_is_read_only(self):
        old=self.h.run.read_bytes()
        with patch.object(pipeline, 'run_lock', side_effect=AssertionError('read-only diagnostics must not create a lock')):
            self.h.call('evaluate-acceptance')
        self.assertEqual(old,self.h.run.read_bytes())
    def test_negative_controls_not_required(self):
        self.choose('accepted');report=self.report();self.assertNotIn('negative_controls',report)
        self.assertEqual(len(report['gate_matrix']),12);self.assertIn(report['final_status'],{'ACCEPTED','ACCEPTED_WITH_NOTES'})
    def test_finalization_before_visual_rejected(self):self.reject('finalize-acceptance')

    def test_acceptance_publication_failure_preserves_evidence(self):
        self.choose('visual');destination=self.h.folder/(self.h.run.stem+'-lesson-acceptance-v3.json');old=destination.read_bytes()
        with patch.object(pipeline,'_replace_bundle',side_effect=OSError('SYNTHETIC publish failure')):self.reject('finalize-acceptance')
        self.assertEqual(destination.read_bytes(),old)

    def test_accepted_resume_fresh_process(self):
        self.choose('accepted')
        result=subprocess.run([sys.executable,'-B',str(pipeline.SKILL_ROOT/'scripts/run_lesson_pipeline.py'),'status','--run',str(self.h.run)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['state'],'ACCEPTED')

    def test_acceptance_self_fingerprint_tamper(self):
        self.choose('accepted');payload=json.loads(self.path('acceptance').read_bytes());payload['acceptance_fingerprint']='0'*64;_write_json(self.path('acceptance'),payload)
        self.reject('status')
    def test_recomputed_acceptance_cannot_hide_limitation(self):
        self.choose('accepted');payload=json.loads(self.path('acceptance').read_bytes());payload['final_status']='ACCEPTED';payload['limitations']=[]
        payload['acceptance_fingerprint']=acceptance.acceptance_fingerprint(payload);_write_json(self.path('acceptance'),payload)
        digest = sha256_file(self.path('acceptance'))
        self.run['bindings']['acceptance']['sha256'] = digest
        self.run['state']['artifacts']['acceptance_sha256'] = digest
        self.run['state']['transitions'][-1]['evidence_sha256'] = digest
        self.h.save_modified_run(self.run)
        with self.assertRaisesRegex(ValueError, 'exact chain rederivation'):
            acceptance.validate_acceptance_file(self.path('acceptance'), self.run)
    def test_acceptance_sha_mismatch(self):
        self.choose('accepted');self.run['state']['artifacts']['acceptance_sha256']='0'*64;self.h.save_modified_run(self.run);self.reject('status')
    def test_fake_accepted_state_failed(self):
        self.choose('generated');self.run['state']['current_state']='ACCEPTED';self.h.save_modified_run(self.run)
        self.assertEqual(self.report()['final_status'],'FAILED')
    def test_content_stale_failed(self):
        self.choose('accepted');self.mutate(self.path('content'));self.assertEqual(self.report()['final_status'],'FAILED')
    def test_output_mutation_after_accepted_failed(self):
        self.choose('accepted');self.mutate(self.artifact_path('final_docx_path'));self.assertEqual(self.report()['final_status'],'FAILED');self.reject('status')
    def test_visual_authority_mutation_after_accepted_failed(self):
        self.choose('accepted');self.mutate(self.path('visual_review'));self.assertEqual(self.report()['final_status'],'FAILED')
    def test_source_truth_change_invalidates_accepted(self):
        self.choose('accepted');self.mutate(self.path('source_truth'));self.assertEqual(self.report()['final_status'],'FAILED')
    def test_teacher_change_invalidates_accepted(self):
        self.choose('accepted');self.mutate(self.path('teacher_review'));self.assertEqual(self.report()['final_status'],'FAILED')
    def test_benchmark_change_invalidates_accepted(self):
        self.choose('accepted');self.mutate(self.path('benchmark_disposition'));self.assertEqual(self.report()['final_status'],'FAILED')


class StatusPolicyTests(unittest.TestCase):
    def all_pass(self): return [{"status":"PASS"} for _ in acceptance.GATES]
    def test_empty_or_incomplete_gate_matrix_is_not_accepted(self):
        for gates in ([], self.all_pass()[:-1]):
            self.assertEqual(acceptance.final_status('PRODUCTION', gates, False, []), 'PENDING_REVIEW')
    def test_full_approved_facts_accepted(self): self.assertEqual(acceptance.final_status('PRODUCTION',self.all_pass(),False,[]),'ACCEPTED')
    def test_teacher_with_notes(self): self.assertEqual(acceptance.final_status('PRODUCTION',self.all_pass(),False,['TEACHER_APPROVED_WITH_NOTES']),'ACCEPTED_WITH_NOTES')
    def test_partial_limitation(self): self.assertEqual(acceptance.final_status('PRODUCTION',self.all_pass(),False,['BENCHMARK_PARTIAL']),'ACCEPTED_WITH_NOTES')
    def test_unavailable_limitation(self): self.assertEqual(acceptance.final_status('PRODUCTION',self.all_pass(),False,['BENCHMARK_UNAVAILABLE']),'ACCEPTED_WITH_NOTES')
    def test_waived_limitation(self): self.assertEqual(acceptance.final_status('PRODUCTION',self.all_pass(),False,['BENCHMARK_WAIVED_BY_USER']),'ACCEPTED_WITH_NOTES')
    def test_preview_never_accepted(self): self.assertEqual(acceptance.final_status('PREVIEW',self.all_pass(),False,[]),'PENDING_REVIEW')
    def test_missing_gate_pending(self):
        gates=self.all_pass();gates[-1]['status']='PENDING';self.assertEqual(acceptance.final_status('PRODUCTION',gates,False,[]),'PENDING_REVIEW')
    def test_not_applicable_is_not_missing_evidence_escape(self):
        gates=self.all_pass();gates[-1]['status']='NOT_APPLICABLE';self.assertEqual(acceptance.final_status('PRODUCTION',gates,False,[]),'PENDING_REVIEW')
    def test_valid_revision_classified(self):self.assertEqual(acceptance.final_status('PRODUCTION',self.all_pass(),True,[]),'REVISION_REQUIRED')


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.h=pipeline_tests.PipelineTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_missing_teacher_pending(self):
        run,_,_,_=self.h.ready_disposition()
        self.assertEqual(acceptance.evaluate(run)['final_status'],'PENDING_REVIEW')

    def test_valid_teacher_revision_diagnostic(self):
        _,_,_,benchmark=self.h.ready_disposition()
        review=self.h.packet_teacher(benchmark);review['decision']='REVISION_REQUIRED'
        review['review_fingerprint']=teacher_review_fingerprint(review)
        path=self.h.folder/'revision-teacher.json';_write_json(path,review)
        old=self.h.run.read_bytes();run=self.h.call('status')
        self.assertEqual(acceptance.evaluate(run,diagnostic_inputs={'teacher_review':path})['final_status'],'REVISION_REQUIRED')
        self.assertEqual(old,self.h.run.read_bytes())

    def test_valid_benchmark_revision_diagnostic(self):
        _,kwargs,_=self.h.full_review(major_gap=True)
        run=self.h.call('status')
        inputs={name:path for name,path in kwargs.items() if name not in {'benchmark_evidence','benchmark_authorization'}}
        self.assertEqual(acceptance.evaluate(run,diagnostic_inputs=inputs)['final_status'],'REVISION_REQUIRED')

    def test_preview_evaluate_pending_and_finalization_rejected(self):
        self.h.preview_init();run=self.h.call('status')
        self.assertEqual(self.h.call('evaluate-acceptance')['final_status'],'PENDING_REVIEW')
        self.h.rejected('finalize-acceptance')
        self.h.rejected('validate-artifacts')
        self.h.rejected('prepare-visual-review')
        self.h.rejected('bind-visual-review',visual_review=self.h.folder/'unused.json',visual_evidence=self.h.folder/'unused-evidence.json')

    def test_zero_lesson_practice_only_cannot_enter_acceptance(self):
        from tests.test_lesson_content_v22 import make_v22_payload,DB_SPECS
        from tests.test_lesson_content_v23 import _bind_v23
        payload=make_v22_payload(course='数据库应用基础',major='软件技术',audience='高职二年级',theory_hours=0,practice_hours=4,lesson_count=0,specs=DB_SPECS)
        _bind_v23(payload,mode='practice_only',theory_hours=0,practice_hours=4,workorders=False)
        payload['authoring_provenance']['mode']='agent';_write_json(self.h.content_path,payload)
        self.h.prepared();self.h.call('bind-content',content=self.h.content_path)
        report=self.h.call('evaluate-acceptance')
        self.assertEqual(report['final_status'],'FAILED')
        self.assertIn('zero-Lesson',report['gate_matrix'][0]['notes'])


class CompletedBenchmarkE2ETests(unittest.TestCase):
    def complete(self, *, disposition_mode="complete", teacher_decision="APPROVED"):
        h=pipeline_tests.PipelineTests();h.setUp();self.addCleanup(h.doCleanups)
        if disposition_mode == "waived":
            _,_,_,benchmark=h.ready_disposition("BENCHMARK_WAIVED_BY_USER")
        else:
            disposition,kwargs,benchmark=h.full_review(**({"context_mode":"single_context"} if disposition_mode == "partial" else {}))
            h.call('bind-benchmark-review',disposition=disposition,**kwargs)
            h.call('ready-for-teacher-review')
        teacher=h.packet_teacher(benchmark);teacher['decision']=teacher_decision
        teacher['review_fingerprint']=teacher_review_fingerprint(teacher)
        path=h.folder/'teacher.json';_write_json(path,teacher)
        h.call('bind-teacher-review',teacher_review=path)
        auth=_production_authorization(h.source_path.read_bytes(),h.content_path.read_bytes(),path.read_bytes(),benchmark)
        auth_path=h.folder/'authorization.json';_write_json(auth_path,auth)
        h.call('authorize-production',authorization=auth_path)
        run=h.call('generate-production')
        manifest=json.loads(pipeline.path_of(run,'artifact_manifest').read_bytes())
        if disposition_mode == "complete":
            self.assertEqual(manifest['lesson_skill_capability'],'2.3-benchmark-linked')
        else:
            self.assertEqual(manifest['teaching_exemplar_benchmark'],{'status':'not_provided'})
        h.call('validate-artifacts');run=h.call('prepare-visual-review')
        authority,evidence=synthetic_visual(h,run)
        h.call('bind-visual-review',visual_review=authority,visual_evidence=evidence)
        report=h.call('evaluate-acceptance')
        expected = 'ACCEPTED' if disposition_mode == 'complete' and teacher_decision == 'APPROVED' else 'ACCEPTED_WITH_NOTES'
        self.assertEqual(report['final_status'],expected)
        self.assertEqual(bool(report['limitations']),expected=='ACCEPTED_WITH_NOTES')
        if disposition_mode != 'waived': self.assertIsNotNone(report['evidence']['benchmark_review_sha256'])
        run=h.call('finalize-acceptance');self.assertEqual(h.call('status'),run)
        return report

    def test_full_benchmark_to_real_render_and_plain_accepted(self): self.complete()
    def test_actual_teacher_notes_accepted_with_notes(self):
        report=self.complete(teacher_decision='APPROVED_WITH_NOTES')
        self.assertEqual(report['limitations'],['TEACHER_APPROVED_WITH_NOTES'])
    def test_actual_partial_benchmark_preserved_through_none_generator(self):
        report=self.complete(disposition_mode='partial')
        self.assertEqual(report['limitations'],['BENCHMARK_PARTIAL'])
    def test_actual_waiver_preserved_through_none_generator(self):
        report=self.complete(disposition_mode='waived')
        self.assertEqual(report['limitations'],['BENCHMARK_WAIVED_BY_USER'])
