"""SYNTHETIC human evidence tests authority linkage, never teaching quality."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import tests.test_lesson_pipeline as pipeline_tests
from tests.test_lesson_lifecycle_contracts import _write_json, _teacher_review
from tests.test_lesson_content_v22 import make_v22_payload, _refresh_review_digests
from tests.test_lesson_content_v23 import _bind_v23, _specs, _integrated_64
from lifecycle_digest import LifecycleContractError, canonical_json_bytes, sha256_bytes, sha256_file
from source_truth import source_truth_fingerprint
from teacher_review import teacher_review_fingerprint, validate_teacher_review_files
import run_lesson_pipeline as pipeline
import teacher_review_packet as packet


def course(count=7, *, units=None, version="2.3"):
    specs = list(_specs(count))
    if units is not None:
        specs = [(units[i], *spec[1:]) for i, spec in enumerate(specs)]
    result = make_v22_payload(course="数据库应用基础", major="软件技术", audience="高职二年级",
                              theory_hours=2 * count, practice_hours=0, lesson_count=count,
                              lesson_hours=[2] * count, specs=tuple(specs))
    result["authoring_provenance"]["mode"] = "agent"
    if version == "2.3":
        _bind_v23(result, mode="theory_only", theory_hours=2 * count, practice_hours=0)
    return result


def synthetic_shards(content, changes=None):
    from tests.test_lesson_exemplar_benchmark import DIMENSION_IDS
    result = {lesson["lesson_id"]: {"dimensions": [
        {"dimension": dimension, "status": "MEETS", "severity": "none"} for dimension in DIMENSION_IDS
    ]} for lesson in content["lessons"]}
    for lesson_id, dimensions in (changes or {}).items():
        for i, (status, severity) in enumerate(dimensions):
            result[lesson_id]["dimensions"][i].update(status=status, severity=severity)
    return result


class SelectorTests(unittest.TestCase):
    def positions(self, content, reviews=None):
        return [row["course_position"] for row in packet._selection(content, reviews)]

    def reason_position(self, content, reason, reviews=None):
        return [row["course_position"] for row in packet._selection(content, reviews) if reason in row["selection_reasons"]]

    def test_one_all_both_anchors(self):
        rows = packet._selection(course(1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["selection_reasons"], ["first_lesson", "last_lesson", "highest_content_density"])

    def test_four_all(self): self.assertEqual(self.positions(course(4)), [1, 2, 3, 4])
    def test_six_all(self): self.assertEqual(self.positions(course(6)), list(range(1, 7)))
    def test_seven_exact_six(self): self.assertEqual(len(self.positions(course(7))), 6)
    def test_thirty_two_exact_six(self): self.assertEqual(len(self.positions(course(32))), 6)
    def test_first_selected(self): self.assertEqual(self.reason_position(course(32), "first_lesson"), [1])
    def test_last_selected(self): self.assertEqual(self.reason_position(course(32), "last_lesson"), [32])

    def test_boundary_after_representative(self):
        c = course(12, units=["项目1 起点"] * 6 + ["项目2 过渡"] * 6)
        self.assertIn(7, self.positions(c))
        self.assertEqual(self.reason_position(c, "project_boundary_after"), [7])

    def test_nearest_midpoint_boundary_tie_earlier(self):
        c = course(32, units=["项目1 起点"] * 15 + ["项目2 过渡"] + ["项目3 结束"] * 16)
        for field in packet.DENSITY_FIELDS:
            largest = max(c["lessons"], key=lambda row: len(json.dumps(row[field], ensure_ascii=False)))
            c["lessons"][1][field] = copy.deepcopy(largest[field])
        c["lessons"][1]["reflection"]["summary"] += "附加结构记录" * 5
        _refresh_review_digests(c)
        shards = synthetic_shards(c, {"L28": [("GAP", "minor")]})
        # Following positions 16/17 are equidistant from midpoint 16.5;
        # distinct density/gap candidates leave no room for both boundaries.
        self.assertEqual(self.positions(c, shards), [1, 2, 9, 16, 28, 32])
        row = next(r for r in packet._selection(c, shards) if r["course_position"] == 16)
        self.assertIn("project_boundary_before", row["selection_reasons"])
        self.assertIn("project_boundary_after", row["selection_reasons"])

    def test_density_largest(self):
        c = course()
        c["lessons"][3]["reflection"]["summary"] += "可审计的额外结构说明" * 20
        _refresh_review_digests(c)
        self.assertEqual(self.reason_position(c, "highest_content_density"), [4])

    def test_density_tie_earlier(self):
        c = course()
        for row in c["lessons"]:
            for field in packet.DENSITY_FIELDS:
                row[field] = copy.deepcopy(c["lessons"][0][field])
        _refresh_review_digests(c)
        self.assertEqual(self.reason_position(c, "highest_content_density"), [1])

    def test_practice_maximum_task_structure(self):
        c = _integrated_64(workorders=True)
        c["authoring_provenance"]["mode"] = "agent"
        task = c["practice_task_contract"]["tasks"][4]
        task["tools_or_materials"].append("测试用附加记录工具")
        self.assertEqual(self.reason_position(c, "highest_practice_complexity"), [9])

    def test_practice_tie_earlier(self):
        c = _integrated_64(workorders=False)
        c["authoring_provenance"]["mode"] = "agent"
        self.assertEqual(self.reason_position(c, "highest_practice_complexity"), [1])

    def test_no_practice_reason(self): self.assertEqual(self.reason_position(course(), "highest_practice_complexity"), [])
    def test_content_22_no_fabricated_practice(self):
        self.assertEqual(self.reason_position(course(version="2.2"), "highest_practice_complexity"), [])

    def test_content_22_related_tasks_count_without_allocating_hours(self):
        c = make_v22_payload(course="数据库应用基础", major="软件技术", audience="高职二年级",
            theory_hours=14, practice_hours=2, lesson_count=7, lesson_hours=[2] * 7,
            specs=_specs(7), practice_work_orders=True)
        c["authoring_provenance"]["mode"] = "agent"
        rows = packet._selection(c)
        first = next(row for row in rows if row["lesson_id"] == "L01")
        self.assertEqual(first["practice_complexity"], [0, 1, 3, 2, 2, 2])
        self.assertFalse(any("highest_practice_complexity" in row["selection_reasons"] for row in rows))

    def test_content_23_split_related_tasks_do_not_fabricate_allocation(self):
        c = course(7)
        _bind_v23(c, mode="split_lessons", theory_hours=14, practice_hours=2,
                  workorders=True, task_links=[["L01"]])
        rows = packet._selection(c)
        self.assertEqual(rows[0]["practice_complexity"], [0, 1, 3, 2, 2, 2])
        self.assertFalse(any("highest_practice_complexity" in row["selection_reasons"] for row in rows))

    def test_major_gap_precedes_more_minor_gaps(self):
        c = course(32)
        shards = synthetic_shards(c, {"L10": [("PARTIAL", "major")], "L20": [("GAP", "minor")] * 10})
        self.assertEqual(self.reason_position(c, "benchmark_gap", shards), [10])

    def test_gap_tie_earlier(self):
        c = course()
        shards = synthetic_shards(c, {"L03": [("GAP", "minor")], "L04": [("GAP", "minor")]})
        self.assertEqual(self.reason_position(c, "benchmark_gap", shards), [3])

    def test_no_actual_review_no_gap(self): self.assertEqual(self.reason_position(course(), "benchmark_gap"), [])

    def test_all_zero_review_supplemental_matches_no_review(self):
        c = course(10, units=["项目1 起点"] * 10)
        for row in c["lessons"]:
            for field in packet.DENSITY_FIELDS:
                row[field] = copy.deepcopy(c["lessons"][0][field])
        _refresh_review_digests(c)
        reviews = synthetic_shards(c)
        self.assertEqual(self.positions(c, reviews), [1, 2, 3, 5, 7, 10])
        self.assertEqual(self.reason_position(c, "deterministic_supplemental", reviews), [2, 3, 5, 7])
        self.assertEqual(self.reason_position(c, "benchmark_gap", reviews), [])
        self.assertEqual([r["selection_reasons"] for r in packet._selection(c, reviews)],
                         [r["selection_reasons"] for r in packet._selection(c)])

    def test_advisory_signal_candidate(self):
        c = course(7)
        reviews = synthetic_shards(c, {"L04": [("PARTIAL", "advisory")]})
        self.assertEqual(self.reason_position(c, "benchmark_gap", reviews), [4])

    def test_duplicate_candidates_deduplicated(self):
        c = course(10, units=["项目1 起点"] * 10)
        rows = packet._selection(c, synthetic_shards(c))
        self.assertEqual(len(rows), 6)
        self.assertFalse(any("benchmark_gap" in row["selection_reasons"] for row in rows))
        self.assertEqual(len({row["lesson_id"] for row in rows}), 6)

    def test_supplemental_fills_target(self):
        c = course(10, units=["项目1 起点"] * 10)
        for row in c["lessons"]:
            for field in packet.DENSITY_FIELDS: row[field] = copy.deepcopy(c["lessons"][0][field])
        _refresh_review_digests(c)
        self.assertEqual(self.positions(c), [1, 2, 3, 5, 7, 10])
        self.assertEqual(self.reason_position(c, "deterministic_supplemental"), [2, 3, 5, 7])

    def test_short_unanchored_gets_supplemental(self):
        c = course(4, units=["项目1 起点"] * 4)
        rows = packet._selection(c)
        self.assertTrue(all(row["selection_reasons"] for row in rows))
        self.assertTrue(any("deterministic_supplemental" in row["selection_reasons"] for row in rows))

    def test_reason_canonical_order(self):
        c = course(7)
        for row in packet._selection(c, synthetic_shards(c)):
            self.assertEqual(row["selection_reasons"], sorted(row["selection_reasons"], key=packet.REASONS.index))

    def test_repeated_execution_identical(self):
        c = course(32)
        self.assertEqual(packet._selection(c), packet._selection(c))

    def test_property_order_invariant(self):
        c = course()
        shuffled = json.loads(json.dumps(c, sort_keys=True))
        self.assertEqual(packet._selection(c), packet._selection(shuffled))

    def test_unit_unicode_whitespace_normalization(self):
        self.assertEqual(packet.normalized_unit(" 项目1\t Cafe\u0301  "), packet.normalized_unit("项目1 Café"))

    def test_density_excludes_id_and_metadata(self):
        c = course(1)
        row = packet._selection(c)[0]
        expected = len(canonical_json_bytes(packet.digest_projection({field: c["lessons"][0][field] for field in packet.DENSITY_FIELDS})))
        self.assertEqual(row["content_density_bytes"], expected)

    def test_decimal_projection_preserves_snapshot_numbers(self):
        c = course(1)
        result = packet._selection(c)[0]
        self.assertEqual(result["lesson_snapshot"], c["lessons"][0])
        self.assertEqual(packet.digest_projection({"weight": 0.2}), {"weight": {"$packet_decimal": "0.2"}})
        self.assertNotEqual(packet.digest_projection({"weight": 0.2}), packet.digest_projection({"weight": "0.2"}))
        with self.assertRaises(ValueError): packet.digest_projection(float("nan"))

    def test_numeric_string_allocations_do_not_sort_lexically(self):
        c = _integrated_64(workorders=False)
        c["authoring_provenance"]["mode"] = "agent"
        for lesson in c["lessons"]:
            lesson["practice_hours"] = "1.0"
        _bind_v23(c, mode="integrated_lessons", theory_hours=32, practice_hours=32)
        rows = packet._selection(c)
        self.assertEqual(self.reason_position(c, "highest_practice_complexity"), [1])
        self.assertEqual(rows[0]["practice_complexity"][0], 1)
        self.assertEqual(rows[0]["lesson_snapshot"]["practice_hours"], "1.0")

    def test_formal_content_validation_before_selection(self):
        c = course()
        c["lessons"][1]["lesson_id"] = c["lessons"][0]["lesson_id"]
        with self.assertRaises(ValueError): packet._selection(c)


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Build genuine upstream evidence once; each case gets independent files.
        cls.template = pipeline_tests.PipelineTests()
        cls.template.setUp()
        cls.addClassCleanup(cls.template.doCleanups)
        content = course()
        for index, lesson in enumerate(content["lessons"], 1):
            lesson["task"] = f"分析数据路径边界{index}并形成边界分析记录{index}"
            for query in content.get("reference_research", {}).get("queries", []):
                if query.get("lesson_id") == lesson["lesson_id"]:
                    query["query"] = (
                        f"{content['course_name']} {content['major']} {lesson['task']} reference research"
                    )
        _bind_v23(content, mode="theory_only", theory_hours=14, practice_hours=0)
        _write_json(cls.template.content_path, content)
        outline_source = next(
            item for item in cls.template.source["sources"] if item["source_type"] == "whole_course_outline"
        )
        outline_path = cls.template.source_path.parent / outline_source["locator"]
        outline_source["sha256"] = sha256_bytes(_write_json(outline_path, content["outline"]))
        cls.template.source["manifest_fingerprint"] = source_truth_fingerprint(cls.template.source)
        _write_json(cls.template.source_path, cls.template.source)
        cls.template.run.unlink()
        cls.template.call("init", mode="PRODUCTION", run_id="RUN-001", source_truth=cls.template.source_path)
        _, _, _, cls.benchmark_template = cls.template.ready_disposition()
        cls.template.call("prepare-teacher-review")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name) / "inputs"
        shutil.copytree(self.template.folder, folder)
        self.h = pipeline_tests.PipelineTests()
        self.h.folder = folder
        for name in ("source", "catalog", "quality"):
            setattr(self.h, name, copy.deepcopy(getattr(self.template, name)))
        for name in ("source_path", "content_path", "run"):
            setattr(self.h, name, folder / getattr(self.template, name).relative_to(self.template.folder))
        self.h.paths = {name: folder / path.relative_to(self.template.folder)
                        for name, path in self.template.paths.items()}
        self.run = json.loads(self.h.run.read_bytes())
        # Relocate synthetic test locators only. Every actual byte inventory and
        # Source Truth / Content / preparation / Review validator still executes.
        for binding in self.run["bindings"].values():
            binding["path"] = str(folder / Path(binding["path"]).relative_to(self.template.folder))
        self.run["run_fingerprint"] = pipeline.envelope_fingerprint(self.run)
        _write_json(self.h.run, self.run)
        self.benchmark = copy.deepcopy(self.benchmark_template)
        self.path = pipeline.path_of(self.run, "teacher_review_packet")
        self.packet = json.loads(self.path.read_bytes())

    def valid(self): return packet.validate_teacher_review_packet(self.path, self.run)

    def tamper(self, edit, *, fingerprint=True):
        changed = copy.deepcopy(self.packet)
        edit(changed)
        if fingerprint: changed["packet_fingerprint"] = packet.packet_fingerprint(changed)
        _write_json(self.path, changed)
        self.run["bindings"]["teacher_review_packet"]["sha256"] = sha256_file(self.path)
        self.run["run_fingerprint"] = pipeline.envelope_fingerprint(self.run)
        # Standalone semantic validator should catch even a recomputed own hash.
        with self.assertRaises(ValueError): self.valid()

    def test_valid_packet(self): self.assertEqual(self.valid(), self.packet)
    def test_wrong_content_sha(self): self.tamper(lambda p: p.update(content_sha256="a" * 64))
    def test_snapshot_boolean_type_tamper_with_original_fingerprint(self):
        self.tamper(lambda p: p["selected_lessons"][0]["lesson_snapshot"]["pedagogical_review"]["review_history"][0].update(round=True), fingerprint=False)

    def test_snapshot_float_type_tamper_with_original_fingerprint(self):
        self.tamper(lambda p: p["selected_lessons"][0]["lesson_snapshot"].update(hours=2.0), fingerprint=False)

    def test_changed_snapshot(self): self.tamper(lambda p: p["selected_lessons"][0]["lesson_snapshot"].update(task="篡改的任务"))
    def test_changed_course_map(self): self.tamper(lambda p: p["course_map"][0].update(hours=3))
    def test_forged_id(self): self.tamper(lambda p: p["selected_lessons"][0].update(lesson_id="fake"))
    def test_missing_lesson(self): self.tamper(lambda p: p["selected_lessons"].pop())
    def test_extra_lesson(self): self.tamper(lambda p: p["selected_lessons"].append(copy.deepcopy(p["selected_lessons"][0])))
    def test_forged_reason(self): self.tamper(lambda p: p["selected_lessons"][0].update(selection_reasons=["last_lesson"]))
    def test_forged_density(self): self.tamper(lambda p: p["selected_lessons"][0].update(content_density_bytes=1))
    def test_forged_practice(self): self.tamper(lambda p: p["selected_lessons"][0].update(practice_complexity=[2, 0, 0, 0, 0, 0]))
    def test_forged_gap(self): self.tamper(lambda p: p["selected_lessons"][0].update(benchmark_gap_summary={"major_count":0,"minor_count":0,"advisory_count":0,"GAP_count":0,"PARTIAL_count":0,"gap_dimension_ids":[]}))
    def test_disposition_bytes_stale(self):
        path = pipeline.path_of(self.run, "benchmark_disposition")
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError): self.valid()
    def test_fingerprint_tamper(self): self.tamper(lambda p: p.update(packet_fingerprint="b" * 64), fingerprint=False)
    def test_created_at_changes_only_bytes(self):
        later = packet.build_teacher_review_packet(self.run, created_at="2027-01-01T00:00:00Z")
        self.assertEqual(packet.packet_fingerprint(later), packet.packet_fingerprint(self.packet))
        self.assertNotEqual(later["created_at"], self.packet["created_at"])
    def test_position_tamper(self): self.tamper(lambda p: p["selected_lessons"][0].update(course_position=2))
    def test_policy_tamper(self): self.tamper(lambda p: p.update(selection_policy_version="2.0"))
    def test_target_tamper(self): self.tamper(lambda p: p.update(target_count=5))
    def test_no_review_null_gaps(self):
        self.assertIsNone(self.packet["benchmark_review_sha256"])
        self.assertTrue(all(row["benchmark_gap_summary"] is None and "benchmark_gap" not in row["selection_reasons"] for row in self.packet["selected_lessons"]))

    def teacher(self, *, decision="APPROVED"):
        result = _teacher_review(self.h.source_path.read_bytes(), self.h.content_path.read_bytes(), self.benchmark)
        row = result["selected_lessons"][0]
        result["selected_lessons"] = [dict(copy.deepcopy(row), lesson_id=s["lesson_id"], selection_reasons=s["selection_reasons"])
                                      for s in self.packet["selected_lessons"]]
        result["decision"] = decision
        return result

    def write_teacher(self, review):
        review["review_fingerprint"] = teacher_review_fingerprint(review)
        path = self.h.folder / "teacher.json"
        _write_json(path, review)
        return path

    def reject_teacher(self, edit):
        review = self.teacher()
        edit(review)
        path = self.write_teacher(review)
        self.h.rejected("bind-teacher-review", teacher_review=path)

    def test_exact_approved_passes(self):
        result = self.h.call("bind-teacher-review", teacher_review=self.write_teacher(self.teacher()))
        self.assertEqual(result["state"]["current_state"], "TEACHER_REVIEW_APPROVED")
        self.assertEqual(result, self.h.call("status"))
    def test_human_ratings_and_notes_remain_external(self):
        review = self.teacher()
        review["selected_lessons"][0]["directly_teachable"] = {"rating": 2, "notes": "SYNTHETIC externally supplied Teacher assessment"}
        review["decision_notes"] = "SYNTHETIC externally supplied decision"
        self.assertEqual(self.h.call("bind-teacher-review", teacher_review=self.write_teacher(review))["state"]["current_state"], "TEACHER_REVIEW_APPROVED")

    def test_packet_required_on_approved_resume(self):
        run = self.h.call("bind-teacher-review", teacher_review=self.write_teacher(self.teacher()))
        del run["bindings"]["teacher_review_packet"]
        self.h.save_modified_run(run)
        self.h.rejected("status")

    def test_approved_with_notes_passes(self):
        self.assertEqual(self.h.call("bind-teacher-review", teacher_review=self.write_teacher(self.teacher(decision="APPROVED_WITH_NOTES")))["state"]["current_state"], "TEACHER_REVIEW_APPROVED")
    def test_revision_cannot_advance(self): self.reject_teacher(lambda r: r.update(decision="REVISION_REQUIRED"))
    def test_teacher_missing_lesson(self): self.reject_teacher(lambda r: r["selected_lessons"].pop())
    def test_teacher_extra_lesson(self):
        missing = next(row for row in self.packet["course_map"] if row["lesson_id"] not in {x["lesson_id"] for x in self.packet["selected_lessons"]})
        self.reject_teacher(lambda r: r["selected_lessons"].append(dict(copy.deepcopy(r["selected_lessons"][1]), lesson_id=missing["lesson_id"])))
    def test_teacher_replaced_lesson(self):
        missing = next(row for row in self.packet["course_map"] if row["lesson_id"] not in {x["lesson_id"] for x in self.packet["selected_lessons"]})
        self.reject_teacher(lambda r: r["selected_lessons"][1].update(lesson_id=missing["lesson_id"]))
    def test_teacher_wrong_reasons(self): self.reject_teacher(lambda r: r["selected_lessons"][0].update(selection_reasons=["last_lesson"]))
    def test_teacher_reordered(self): self.reject_teacher(lambda r: r["selected_lessons"].reverse())
    def test_cherry_pick_easy_subset(self): self.reject_teacher(lambda r: r.update(selected_lessons=r["selected_lessons"][:2]))
    def test_stale_packet_rejects_binding(self):
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        self.h.rejected("bind-teacher-review", teacher_review=self.write_teacher(self.teacher()))
    def test_missing_packet_canonical_rejected(self):
        del self.run["bindings"]["teacher_review_packet"]
        self.h.save_modified_run(self.run)
        self.h.rejected("bind-teacher-review", teacher_review=self.write_teacher(self.teacher()))
    def test_standalone_historical_contract_compatible(self):
        historical = _teacher_review(self.h.source_path.read_bytes(), self.h.content_path.read_bytes(), self.benchmark)
        path = self.write_teacher(historical)
        _, _, errors = validate_teacher_review_files(path, source_truth_path=self.h.source_path,
            content_path=self.h.content_path, benchmark_evidence_path=pipeline.path_of(self.run, "benchmark_evidence"), require_approved=True)
        self.assertEqual(errors, [])
        self.h.rejected("bind-teacher-review", teacher_review=path)
    def test_preview_prepare_and_bind(self):
        # New PREVIEW run uses the same verified inputs, not a mode rewrite.
        self.h.preview_init()
        _, _, _, self.benchmark = self.h.ready_disposition()
        preview = self.h.call("prepare-teacher-review")
        self.packet = json.loads(pipeline.path_of(preview, "teacher_review_packet").read_bytes())
        result = self.h.call("bind-teacher-review", teacher_review=self.write_teacher(self.teacher()))
        self.assertEqual(result["mode"], "PREVIEW")
        self.assertEqual(result["state"]["current_state"], "TEACHER_REVIEW_APPROVED")
        self.h.rejected("authorize-production", authorization=self.h.folder / "absent.json")
    def test_resume_rederives_packet_even_with_new_binding_hash(self):
        changed = copy.deepcopy(self.packet)
        changed["selected_lessons"][0]["content_density_bytes"] = 1
        changed["packet_fingerprint"] = packet.packet_fingerprint(changed)
        _write_json(self.path, changed)
        self.run["bindings"]["teacher_review_packet"]["sha256"] = sha256_file(self.path)
        self.h.save_modified_run(self.run)
        self.h.rejected("status")
    def test_packet_bytes_change_status_stale(self):
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        self.h.rejected("status")
    def test_content_bytes_change_invalidates_packet_review(self):
        self.h.call("bind-teacher-review", teacher_review=self.write_teacher(self.teacher()))
        self.h.content_path.write_bytes(self.h.content_path.read_bytes() + b"\n")
        self.h.rejected("status")
        self.h.rejected("bind-content", content=self.h.content_path)
    def test_prepare_no_transition(self):
        self.assertEqual(self.run["state"]["current_state"], "READY_FOR_TEACHER_REVIEW")
        self.assertEqual(self.run["state"]["transitions"][-1]["from_state"], "PREPRODUCTION_QA_PASSED")
        self.assertEqual(self.run["state"]["transitions"][-1]["to_state"], "READY_FOR_TEACHER_REVIEW")
        self.assertNotIn("teacher_review_packet", self.run["state"]["artifacts"])
    def test_preparation_cannot_repeat(self): self.h.rejected("prepare-teacher-review")
    def test_atomic_publication_rollback(self):
        del self.run["bindings"]["teacher_review_packet"]
        self.h.save_modified_run(self.run)
        raw_run, raw_packet = self.h.run.read_bytes(), self.path.read_bytes()
        # Bundle helper itself is covered by existing rollback tests; here ensure
        # the orchestrator never commits its candidate before bundle publication.
        with patch.object(pipeline, "_replace_bundle", side_effect=OSError("injected publish failure")):
            with self.assertRaises(OSError): self.h.call("prepare-teacher-review")
        self.assertEqual(self.h.run.read_bytes(), raw_run)
        self.assertEqual(self.path.read_bytes(), raw_packet)


class FullBenchmarkPacketTests(unittest.TestCase):
    def setUp(self):
        self.h = pipeline_tests.PipelineTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def ready(self, **options):
        disposition, kwargs, benchmark = self.h.full_review(**options)
        self.h.call("bind-benchmark-review", disposition=disposition, **kwargs)
        self.h.call("ready-for-teacher-review")
        run = self.h.call("prepare-teacher-review")
        return run, json.loads(pipeline.path_of(run, "teacher_review_packet").read_bytes())

    def test_real_completed_review_shards_used(self):
        run, result = self.ready()
        self.assertEqual(result["benchmark_review_sha256"], sha256_file(pipeline.path_of(run, "benchmark_review")))
        self.assertEqual(result["benchmark"]["disposition"], "BENCHMARK_REVIEW_COMPLETE")
        for row in result["selected_lessons"]:
            self.assertNotIn("benchmark_gap", row["selection_reasons"])
            self.assertIsNotNone(row["benchmark_gap_summary"])
            self.assertEqual(packet.gap_tuple(row["benchmark_gap_summary"]), (0, 0, 0, 0, 0))
            self.assertEqual(row["benchmark_gap_summary"]["gap_dimension_ids"], [])
        self.assertEqual(len(result["selected_lessons"]), len(result["course_map"]))
        packet.validate_teacher_review_packet(pipeline.path_of(run, "teacher_review_packet"), run)

    def test_actual_partial_disposition_zero_review_has_no_gap_candidate(self):
        _, result = self.ready(context_mode="single_context")
        self.assertEqual(result["benchmark"]["disposition"], "BENCHMARK_PARTIAL")
        self.assertFalse(any("benchmark_gap" in row["selection_reasons"] for row in result["selected_lessons"]))

    def test_actual_zero_review_long_course_supplemental(self):
        content = course(10, units=["项目1 起点"] * 10)
        _write_json(self.h.content_path, content)
        outline_source = next(
            row for row in self.h.source["sources"] if row["source_type"] == "whole_course_outline"
        )
        outline_path = self.h.source_path.parent / outline_source["locator"]
        outline_source["sha256"] = sha256_bytes(_write_json(outline_path, content["outline"]))
        self.h.source["manifest_fingerprint"] = source_truth_fingerprint(self.h.source)
        _write_json(self.h.source_path, self.h.source)
        self.h.run.unlink()
        self.h.call("init", mode="PRODUCTION", run_id="RUN-001", source_truth=self.h.source_path)
        _, result = self.ready()
        without_review = packet._selection(content)
        self.assertEqual(len(result["selected_lessons"]), 6)
        self.assertEqual([r["course_position"] for r in result["selected_lessons"]],
                         [r["course_position"] for r in without_review])
        self.assertEqual([r["selection_reasons"] for r in result["selected_lessons"]],
                         [r["selection_reasons"] for r in without_review])
        self.assertTrue(any("deterministic_supplemental" in r["selection_reasons"]
                            for r in result["selected_lessons"]))
        for row in result["selected_lessons"]:
            self.assertEqual(packet.gap_tuple(row["benchmark_gap_summary"]), (0, 0, 0, 0, 0))
            self.assertNotIn("benchmark_gap", row["selection_reasons"])

    def test_actual_review_minor_gap_candidate(self):
        original = pipeline_tests.make_lesson_reviews
        def minor_gap(*args, **kwargs):
            rows = original(*args, **kwargs)
            rows[-1]["dimensions"][0].update(status="GAP", severity="minor",
                gap="SYNTHETIC minor gap", recommended_direction="SYNTHETIC direction")
            return rows
        with patch.object(pipeline_tests, "make_lesson_reviews", side_effect=minor_gap):
            _, result = self.ready(context_mode="single_context")
        candidates = [row for row in result["selected_lessons"] if "benchmark_gap" in row["selection_reasons"]]
        self.assertEqual([r["lesson_id"] for r in candidates], [result["course_map"][-1]["lesson_id"]])
        self.assertEqual(packet.gap_tuple(candidates[0]["benchmark_gap_summary"]), (0, 1, 1, 0, 0))

    def test_actual_review_advisory_only_candidate(self):
        original = pipeline_tests.make_lesson_reviews
        def advisory(*args, **kwargs):
            rows = original(*args, **kwargs)
            rows[-1]["dimensions"][0].update(severity="advisory")
            return rows
        with patch.object(pipeline_tests, "make_lesson_reviews", side_effect=advisory):
            _, result = self.ready()
        candidates = [row for row in result["selected_lessons"] if "benchmark_gap" in row["selection_reasons"]]
        self.assertEqual([r["lesson_id"] for r in candidates], [result["course_map"][-1]["lesson_id"]])
        self.assertEqual(packet.gap_tuple(candidates[0]["benchmark_gap_summary"]), (0, 0, 0, 0, 1))

    def test_actual_zero_review_teacher_invented_gap_rejected(self):
        _, result = self.ready()
        review = _teacher_review(self.h.source_path.read_bytes(), self.h.content_path.read_bytes(), result["benchmark"])
        template = review["selected_lessons"][0]
        review["selected_lessons"] = [dict(copy.deepcopy(template), lesson_id=row["lesson_id"],
            selection_reasons=list(row["selection_reasons"])) for row in result["selected_lessons"]]
        review["selected_lessons"][0]["selection_reasons"].append("benchmark_gap")
        review["review_fingerprint"] = teacher_review_fingerprint(review)
        path = self.h.folder / "invented-gap-teacher.json"
        _write_json(path, review)
        with self.assertRaisesRegex(ValueError, "exactly match"):
            packet.validate_teacher_review_against_packet(review, result)
        self.h.rejected("bind-teacher-review", teacher_review=path)

    def test_zero_to_nonzero_shard_makes_packet_stale(self):
        run, result = self.ready()
        path = next(pipeline.path_of(run, "lesson_reviews_dir").glob("*.json"))
        review = json.loads(path.read_bytes())
        self.assertEqual(packet.gap_tuple(packet.gap_summary(review)), (0, 0, 0, 0, 0))
        review["dimensions"][0].update(status="GAP", severity="minor",
            gap="SYNTHETIC new signal", recommended_direction="SYNTHETIC direction")
        _write_json(path, review)
        with self.assertRaises(ValueError):
            packet.validate_teacher_review_packet(pipeline.path_of(run, "teacher_review_packet"), run)
        self.h.rejected("status")

    def test_review_changed_packet_stale(self):
        run, _ = self.ready()
        path = pipeline.path_of(run, "benchmark_review")
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError): packet.validate_teacher_review_packet(pipeline.path_of(run, "teacher_review_packet"), run)

    def test_shard_changed_packet_stale(self):
        run, _ = self.ready()
        path = next(pipeline.path_of(run, "lesson_reviews_dir").glob("*.json"))
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError): packet.validate_teacher_review_packet(pipeline.path_of(run, "teacher_review_packet"), run)
        self.h.rejected("status")

    def test_no_packet_before_ready(self):
        self.h.qa()
        self.h.rejected("prepare-teacher-review")

    def test_existing_revision_required_gate_preserved(self):
        disposition, kwargs, _ = self.h.full_review(major_gap=True)
        self.h.rejected("bind-benchmark-review", disposition=disposition, **kwargs)
