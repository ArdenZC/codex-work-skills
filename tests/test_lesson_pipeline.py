"""SYNTHETIC external reviews exercise authority linkage, not teaching acceptance."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_benchmark_preparation import inputs
from tests.test_lesson_lifecycle_contracts import (
    _source_truth, _content, _write_json, _teacher_review, _production_authorization,
)
from tests.test_lesson_exemplar_benchmark import (
    make_authoring_selection, make_holdout_selection, make_lesson_reviews, make_review,
)
from lifecycle_digest import LifecycleContractError, sha256_file
from teacher_review import teacher_review_fingerprint
from production_authorization import production_authorization_fingerprint
import run_lesson_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source, self.source_path = _source_truth(self.folder)
        self.content_path = self.folder / "content.json"
        _write_json(self.content_path, _content())
        self.catalog, self.quality, self.paths = inputs(self.folder, eligible=set(),
            context=self.source["course_identity"])
        self.run = self.folder / "production-run.json"
        self.call("init", mode="PRODUCTION", run_id="RUN-001", source_truth=self.source_path)

    def call(self, command, **options):
        return pipeline.execute(command, self.run, **options)

    def rejected(self, command, **options):
        before = self.run.read_bytes()
        with self.assertRaises((LifecycleContractError, ValueError, OSError, KeyError, TypeError)):
            self.call(command, **options)
        self.assertEqual(before, self.run.read_bytes())

    def prepared(self):
        self.call("freeze-source-truth")
        self.call("prepare-benchmark", source_catalog=self.paths["source_catalog"],
                  quality_eligibility=self.paths["quality_eligibility"])

    def qa(self):
        self.prepared()
        self.call("bind-content", content=self.content_path)
        self.call("validate-preproduction")

    def disposition(self, final="BENCHMARK_UNAVAILABLE", *, waiver=False):
        run = self.call("status")
        source_sha, content_sha = sha256_file(self.source_path), sha256_file(self.content_path)
        evidence = {"pipeline_run_id": "RUN-001", "source_truth_manifest_sha256": source_sha,
                    "content_sha256": content_sha, "notes": "SYNTHETIC explicit external disposition evidence"}
        if waiver:
            evidence.update(decision="WAIVED_BY_USER", user_identity="SYNTHETIC owner",
                            waiver_reference="SYNTHETIC external owner consent record")
        else:
            evidence.update(disposition=final, benchmark_preparation_sha256=sha256_file(
                pipeline.path_of(run, "benchmark_preparation")))
        evidence_path = self.folder / "benchmark-evidence.json"
        _write_json(evidence_path, evidence)
        benchmark = {"disposition": final, "authorization_sha256": None, "review_sha256": None,
                     "evidence_sha256": sha256_file(evidence_path),
                     "waiver_reference": evidence.get("waiver_reference")}
        disposition_path = self.folder / "disposition.json"
        _write_json(disposition_path, {"pipeline_run_id": "RUN-001", "source_truth_manifest_sha256": source_sha,
                                       "content_sha256": content_sha, "benchmark": benchmark})
        return disposition_path, evidence_path, benchmark

    def reviewed(self):
        self.qa()
        disposition, evidence, benchmark = self.disposition()
        self.call("bind-benchmark-review", disposition=disposition, benchmark_evidence=evidence)
        self.call("ready-for-teacher-review")
        teacher_path = self.folder / "teacher.json"
        teacher = _teacher_review(self.source_path.read_bytes(), self.content_path.read_bytes(), benchmark)
        _write_json(teacher_path, teacher)
        self.call("bind-teacher-review", teacher_review=teacher_path)
        return teacher_path, benchmark

    def authorize(self):
        teacher_path, benchmark = self.reviewed()
        authorization = _production_authorization(self.source_path.read_bytes(), self.content_path.read_bytes(),
                                                  teacher_path.read_bytes(), benchmark)
        path = self.folder / "production-authorization.json"
        _write_json(path, authorization)
        return self.call("authorize-production", authorization=path)

    def test_successful_production_authorized_and_resume(self):
        result = self.authorize()
        self.assertEqual(result["state"]["current_state"], "PRODUCTION_AUTHORIZED")
        self.assertEqual(self.call("status"), result)

    def test_no_source_truth_rejected_at_init(self):
        with self.assertRaises((LifecycleContractError, OSError)):
            pipeline.execute("init", self.folder / "other.json", mode="PRODUCTION", run_id="RUN-001",
                             source_truth=self.folder / "absent.json")

    def test_invalid_source_truth_fingerprint(self):
        self.source["manifest_fingerprint"] = "a" * 64
        _write_json(self.source_path, self.source)
        self.rejected("freeze-source-truth")

    def test_stale_actual_source_bytes(self):
        (self.folder / "evidence/profile.json").write_text("changed", encoding="utf-8")
        self.rejected("freeze-source-truth")

    def test_missing_quality_does_not_publish_bundle(self):
        self.call("freeze-source-truth")
        self.rejected("prepare-benchmark", source_catalog=self.paths["source_catalog"],
                      quality_eligibility=self.folder / "missing.json")
        self.assertFalse((self.folder / "production-run-artifacts").exists())

    def test_invalid_quality(self):
        self.call("freeze-source-truth")
        _write_json(self.paths["quality_eligibility"], {})
        self.rejected("prepare-benchmark", source_catalog=self.paths["source_catalog"],
                      quality_eligibility=self.paths["quality_eligibility"])

    def test_structural_split_cannot_pretend_preparation(self):
        self.call("freeze-source-truth")
        _write_json(self.paths["quality_eligibility"], {"split_id": "fake structural split"})
        self.rejected("prepare-benchmark", source_catalog=self.paths["source_catalog"],
                      quality_eligibility=self.paths["quality_eligibility"])

    def test_no_structural_bypass_in_production(self):
        self.call("freeze-source-truth")
        self.rejected("bind-content", content=self.content_path)

    def test_not_executed_rejected(self):
        self.qa()
        disposition, evidence, _ = self.disposition("BENCHMARK_NOT_EXECUTED")
        self.rejected("bind-benchmark-review", disposition=disposition, benchmark_evidence=evidence)

    def test_fake_waiver_rejected(self):
        self.qa()
        disposition, evidence, _ = self.disposition("BENCHMARK_WAIVED_BY_USER", waiver=True)
        payload = json.loads(evidence.read_bytes())
        payload.pop("user_identity")
        _write_json(evidence, payload)
        d = json.loads(disposition.read_bytes())
        d["benchmark"]["evidence_sha256"] = sha256_file(evidence)
        _write_json(disposition, d)
        self.rejected("bind-benchmark-review", disposition=disposition, benchmark_evidence=evidence)

    def test_valid_external_waiver_path_without_preparation(self):
        self.call("freeze-source-truth")
        evidence = self.folder / "consent.json"
        _write_json(evidence, {"decision": "WAIVED_BY_USER", "pipeline_run_id": "RUN-001",
            "source_truth_manifest_sha256": sha256_file(self.source_path), "content_sha256": sha256_file(self.content_path),
            "user_identity": "SYNTHETIC owner", "waiver_reference": "SYNTHETIC external consent"})
        self.call("bind-content", content=self.content_path, waiver_evidence=evidence)
        self.call("validate-preproduction")
        benchmark = {"disposition": "BENCHMARK_WAIVED_BY_USER", "authorization_sha256": None,
            "review_sha256": None, "evidence_sha256": sha256_file(evidence), "waiver_reference": "SYNTHETIC external consent"}
        disposition = self.folder / "disposition.json"
        _write_json(disposition, {"pipeline_run_id": "RUN-001", "source_truth_manifest_sha256": sha256_file(self.source_path),
                                 "content_sha256": sha256_file(self.content_path), "benchmark": benchmark})
        self.call("bind-benchmark-review", disposition=disposition)
        self.assertEqual(self.call("status")["state"]["current_state"], "BENCHMARK_REVIEW_COMPLETE")

    def test_invalid_content_rejected(self):
        self.prepared()
        _write_json(self.content_path, {"content_contract_version": "2.3"})
        self.rejected("bind-content", content=self.content_path)

    def test_stale_content_after_qa(self):
        self.qa()
        self.content_path.write_bytes(self.content_path.read_bytes() + b"\n")
        self.rejected("status")

    def test_stale_content_after_teacher(self):
        self.reviewed()
        self.content_path.write_bytes(self.content_path.read_bytes() + b"\n")
        self.rejected("status")

    def test_stale_quality_after_preparation(self):
        self.prepared()
        p = self.paths["quality_eligibility"]
        p.write_bytes(p.read_bytes() + b"\n")
        self.rejected("bind-content", content=self.content_path)

    def test_stale_preparation_projection(self):
        self.prepared()
        run = self.call("status")
        p = pipeline.path_of(run, "projected_catalog")
        p.write_bytes(p.read_bytes() + b"\n")
        self.rejected("status")

    def test_teacher_revision_required(self):
        self.qa()
        disposition, evidence, benchmark = self.disposition()
        self.call("bind-benchmark-review", disposition=disposition, benchmark_evidence=evidence)
        self.call("ready-for-teacher-review")
        teacher = _teacher_review(self.source_path.read_bytes(), self.content_path.read_bytes(), benchmark)
        teacher["decision"] = "REVISION_REQUIRED"
        teacher["review_fingerprint"] = teacher_review_fingerprint(teacher)
        path = self.folder / "teacher.json"
        _write_json(path, teacher)
        self.rejected("bind-teacher-review", teacher_review=path)

    def test_stale_teacher_bytes(self):
        teacher, _ = self.reviewed()
        teacher.write_bytes(teacher.read_bytes() + b"\n")
        self.rejected("status")

    def test_stale_benchmark_evidence(self):
        self.reviewed()
        evidence = self.folder / "benchmark-evidence.json"
        evidence.write_bytes(evidence.read_bytes() + b"\n")
        self.rejected("status")

    def test_fabricated_state_history(self):
        run = self.call("status")
        run["state"]["current_state"] = "PRODUCTION_AUTHORIZED"
        run["run_fingerprint"] = pipeline.envelope_fingerprint(run)
        _write_json(self.run, run)
        self.rejected("status")

    def test_string_skip_command_rejected(self):
        self.rejected("PRODUCTION_AUTHORIZED")

    def test_no_auto_teacher_approval(self):
        self.qa()
        self.rejected("ready-for-teacher-review")
        self.rejected("bind-teacher-review", teacher_review=self.folder / "absent.json")

    def test_preview_cannot_authorize(self):
        run = self.call("status")
        run["mode"] = "PREVIEW"
        run["run_fingerprint"] = pipeline.envelope_fingerprint(run)
        _write_json(self.run, run)
        teacher, benchmark = self.reviewed()
        authorization = _production_authorization(self.source_path.read_bytes(), self.content_path.read_bytes(),
                                                  teacher.read_bytes(), benchmark)
        path = self.folder / "authorization.json"
        _write_json(path, authorization)
        self.rejected("authorize-production", authorization=path)

    def test_invalid_authorization_not_published(self):
        teacher, benchmark = self.reviewed()
        authorization = _production_authorization(self.source_path.read_bytes(), self.content_path.read_bytes(),
                                                  teacher.read_bytes(), benchmark)
        authorization["template"]["template_sha256"] = "a" * 64
        authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
        path = self.folder / "authorization.json"
        _write_json(path, authorization)
        self.rejected("authorize-production", authorization=path)

    def test_runtime_environment_revalidated(self):
        teacher, benchmark = self.reviewed()
        authorization = _production_authorization(self.source_path.read_bytes(), self.content_path.read_bytes(),
                                                  teacher.read_bytes(), benchmark)
        authorization["runtime"]["python_version"] = "0.0.0"
        authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
        path = self.folder / "authorization.json"
        _write_json(path, authorization)
        self.rejected("authorize-production", authorization=path)

    def test_restart_new_process_checks_real_bytes(self):
        self.qa()
        p = self.paths["source_catalog"]
        p.write_bytes(p.read_bytes() + b"\n")
        result = subprocess.run([sys.executable, "-B", str(pipeline.SKILL_ROOT / "scripts/run_lesson_pipeline.py"),
                                 "status", "--run", str(self.run)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STALE", result.stderr)

    def test_lock_rejects_concurrent_writer(self):
        Path(str(self.run) + ".lock").write_text("external lock", encoding="utf-8")
        self.rejected("freeze-source-truth")

    def test_run_id_mismatch_disposition(self):
        self.qa()
        disposition, evidence, _ = self.disposition()
        payload = json.loads(disposition.read_bytes())
        payload["pipeline_run_id"] = "OTHER"
        _write_json(disposition, payload)
        self.rejected("bind-benchmark-review", disposition=disposition, benchmark_evidence=evidence)

    def test_partial_and_unavailable_not_automatic_course_failure(self):
        self.authorize()  # zero eligible groups, externally APPROVED Teacher Review

    def test_legacy_content22_success(self):
        _write_json(self.content_path, _content("2.2"))
        self.authorize()

    def test_preparation_transaction_failure_restores_state(self):
        self.call("freeze-source-truth")
        before = self.run.read_bytes()
        import exemplar_split
        real = exemplar_split.os.replace
        count = 0
        def fail_once(a, b):
            nonlocal count
            count += 1
            if count == 4:
                raise OSError("SYNTHETIC publication failure")
            return real(a, b)
        with patch.object(exemplar_split.os, "replace", side_effect=fail_once):
            with self.assertRaises(ValueError):
                self.call("prepare-benchmark", source_catalog=self.paths["source_catalog"],
                          quality_eligibility=self.paths["quality_eligibility"])
        self.assertEqual(self.run.read_bytes(), before)
        self.assertFalse(any((self.folder / "production-run-artifacts").glob("*.json")))

    def full_review(self, *, major_gap=False, context_mode="separate_contexts"):
        from build_benchmark_authorization import build_authorization
        from validate_benchmark_review import build_course_review_payload
        self.catalog, self.quality, self.paths = inputs(self.folder, group_count=20,
                                                       context=self.source["course_identity"])
        self.qa()
        run = self.call("status")
        read = lambda name: json.loads(pipeline.path_of(run, name).read_bytes())
        catalog, split = read("projected_catalog"), read("split")
        a, b = read("authoring_pack"), read("holdout_pack")
        content = json.loads(self.content_path.read_bytes())
        source_sha = sha256_file(self.content_path)
        authoring = make_authoring_selection(catalog, split, a, content)
        holdout = make_holdout_selection(catalog, split, b, content, source_sha)
        gap = ("L01", "task_design") if major_gap else None
        if major_gap:
            from tests.test_lesson_exemplar_benchmark import DIMENSION_IDS
            gap = ("L01", DIMENSION_IDS[0])
        rows = make_lesson_reviews(holdout, source_sha, gap=gap)
        reviews_dir = self.folder / "lesson-reviews"
        reviews_dir.mkdir()
        for row in rows:
            _write_json(reviews_dir / (row["lesson_id"] + ".json"), row)
        isolation = ({"authoring_exemplars_visible": False, "author_reasoning_visible": False, "holdout_only": True}
                     if context_mode == "separate_contexts" else
                     {"authoring_exemplars_visible": True, "author_reasoning_visible": True, "holdout_only": False})
        review, errors = build_course_review_payload(benchmark_run_id="synthetic-benchmark-run", review_round=1,
            context_mode=context_mode, isolation=isolation, catalog=catalog, split=split, holdout_pack=b,
            holdout_selection=holdout, lesson_content=content, lesson_content_sha256=source_sha,
            lesson_reviews=rows, lesson_review_sha256={row["lesson_id"]: sha256_file(reviews_dir / (row["lesson_id"] + ".json")) for row in rows})
        self.assertEqual(errors, [])
        review_path, a_selection_path, b_selection_path = (self.folder / name for name in ("review.json", "a-selection.json", "b-selection.json"))
        for path, payload in ((review_path, review), (a_selection_path, authoring), (b_selection_path, holdout)):
            _write_json(path, payload)
        kwargs = {"benchmark_review": review_path, "authoring_selection": a_selection_path,
                  "holdout_selection": b_selection_path, "lesson_reviews_dir": reviews_dir}
        if not major_gap and context_mode == "separate_contexts":
            authorization = build_authorization(lesson_content_path=self.content_path,
                catalog_path=pipeline.path_of(run, "projected_catalog"), split_path=pipeline.path_of(run, "split"),
                authoring_pack_path=pipeline.path_of(run, "authoring_pack"), authoring_selection_path=a_selection_path,
                holdout_pack_path=pipeline.path_of(run, "holdout_pack"), holdout_selection_path=b_selection_path,
                benchmark_review_path=review_path, lesson_reviews_dir=reviews_dir)
            authorization_path = self.folder / "benchmark-authorization.json"
            _write_json(authorization_path, authorization)
            benchmark = {"disposition": "BENCHMARK_REVIEW_COMPLETE", "authorization_sha256": sha256_file(authorization_path),
                         "review_sha256": sha256_file(review_path), "evidence_sha256": None, "waiver_reference": None}
            kwargs["benchmark_authorization"] = authorization_path
        else:
            disposition_path, evidence, benchmark = self.disposition("BENCHMARK_PARTIAL")
            benchmark["review_sha256"] = sha256_file(review_path)
            kwargs["benchmark_evidence"] = evidence
        disposition_path = self.folder / "disposition.json"
        _write_json(disposition_path, {"pipeline_run_id": "RUN-001", "source_truth_manifest_sha256": sha256_file(self.source_path),
                                     "content_sha256": source_sha, "benchmark": benchmark})
        return disposition_path, kwargs, benchmark

    def test_full_completed_benchmark_success_with_original_claims_helper(self):
        disposition, kwargs, benchmark = self.full_review()
        # Authorization 1.0 deliberately accepts both released provenance versions.
        from benchmark_authorization import authorization_fingerprint
        path = kwargs["benchmark_authorization"]
        payload = json.loads(path.read_bytes())
        payload["skill_version"] = "2.3.0"
        payload["authorization_fingerprint"] = authorization_fingerprint(payload)
        _write_json(path, payload)
        benchmark["authorization_sha256"] = sha256_file(path)
        d = json.loads(disposition.read_bytes())
        d["benchmark"] = benchmark
        _write_json(disposition, d)
        self.call("bind-benchmark-review", disposition=disposition, **kwargs)
        self.call("ready-for-teacher-review")
        teacher = self.folder / "teacher.json"
        _write_json(teacher, _teacher_review(self.source_path.read_bytes(), self.content_path.read_bytes(), benchmark))
        self.call("bind-teacher-review", teacher_review=teacher)
        authorization = self.folder / "authorization.json"
        _write_json(authorization, _production_authorization(self.source_path.read_bytes(), self.content_path.read_bytes(),
                                                            teacher.read_bytes(), benchmark))
        self.assertEqual(self.call("authorize-production", authorization=authorization)["state"]["current_state"], "PRODUCTION_AUTHORIZED")

    def test_benchmark_revision_required_rejected(self):
        disposition, kwargs, _ = self.full_review(major_gap=True)
        self.rejected("bind-benchmark-review", disposition=disposition, **kwargs)

    def test_single_context_real_partial_review_accepted(self):
        disposition, kwargs, _ = self.full_review(context_mode="single_context")
        self.assertEqual(self.call("bind-benchmark-review", disposition=disposition, **kwargs)["state"]["current_state"],
                         "BENCHMARK_REVIEW_COMPLETE")

    def test_completed_review_shard_mutation_invalidates_resume(self):
        disposition, kwargs, _ = self.full_review()
        self.call("bind-benchmark-review", disposition=disposition, **kwargs)
        shard = kwargs["lesson_reviews_dir"] / "L01.json"
        shard.write_bytes(shard.read_bytes() + b"\n")
        self.rejected("status")

    def test_canonical_output_forbidden(self):
        with self.assertRaises(ValueError):
            pipeline.execute("init", pipeline.SKILL_ROOT / "not-written.json", mode="PRODUCTION",
                             run_id="RUN-001", source_truth=self.source_path)
        run = self.call("status")
        pipeline.bind(run, "lesson_reviews_dir", self.folder)
        run["run_fingerprint"] = pipeline.envelope_fingerprint(run)
        with self.assertRaises(ValueError):
            pipeline.validate_run(run, run_path=self.run)


if __name__ == "__main__":
    unittest.main()
