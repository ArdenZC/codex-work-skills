from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_lesson_content_v22 import (
    LESSON,
    NURSING_SPECS,
    lesson_acceptance,
    lesson_content_contract,
    lesson_content_quality,
    lesson_generator,
    lesson_package_common,
    make_v22_payload,
    run_script,
    _refresh_review_digests,
    _task,
)
from tests.test_lesson_exemplar_benchmark import (
    build_exemplar_pack,
    make_authoring_selection,
    make_catalog,
    make_holdout_selection,
    validate_authoring_selection_payload,
    validate_holdout_selection_payload,
)
from exemplar_split import build_split


def _specs(count: int) -> tuple[tuple[str, str, str, str, str], ...]:
    return tuple(
        (
            f"项目{index // 5 + 1} 数据结构综合实施",
            f"分析第{index + 1}类数据处理任务",
            f"数据路径边界{index + 1}",
            f"边界分析记录{index + 1}",
            f"后续处理验证{index + 1}",
        )
        for index in range(count)
    )


def _base_payload(
    *,
    theory_hours: int,
    practice_hours: int = 0,
    lesson_count: int,
    course: str = "数据结构综合实施",
    specs: tuple[tuple[str, str, str, str, str], ...] | None = None,
) -> dict:
    return make_v22_payload(
        course=course,
        major="软件工程专业",
        audience="高职三年级",
        theory_hours=theory_hours,
        practice_hours=practice_hours,
        lesson_count=lesson_count,
        lesson_hours=[2] * lesson_count,
        specs=specs or _specs(lesson_count),
    )


def _outline_row(lesson: dict) -> dict:
    progression = lesson["progression"]
    return {
        "lesson_id": lesson["lesson_id"],
        "unit": lesson["unit"],
        "task": lesson["task"],
        "lesson_type": lesson["lesson_type"],
        "hours": lesson["hours"],
        "theory_hours": lesson["theory_hours"],
        "practice_hours": lesson["practice_hours"],
        "prior_learning": progression["prior_learning"],
        "capability_stage": progression["capability_stage"],
        "deliverable": progression["deliverable"],
        "next_bridge": progression["next_bridge"],
        "practice_task_ids": list(lesson.get("practice_task_ids", [])),
    }


def _bind_v23(
    payload: dict,
    *,
    mode: str,
    theory_hours: int,
    practice_hours: int,
    workorders: bool = False,
    task_links: list[list[str]] | None = None,
) -> dict:
    total_hours = theory_hours + practice_hours
    payload["content_contract_version"] = "2.3"
    payload["total_hours"] = total_hours
    payload["delivery_plan"] = {
        "mode": mode,
        "total_hours": total_hours,
        "theory_hours": theory_hours,
        "practice_hours": practice_hours,
    }
    payload["confirmed_course_info"].update(
        {
            "total_hours": total_hours,
            "theory_hours": theory_hours,
            "practice_hours": practice_hours,
            "delivery_mode": mode,
        }
    )
    payload["artifact_plan"] = {
        "lesson_plans": lesson_content_contract.expected_lesson_coverage_hours(payload["delivery_plan"]) > 0,
        "practice_work_orders": workorders,
    }
    for lesson in payload["lessons"]:
        lesson["practice_task_ids"] = []
    if workorders:
        if practice_hours % 2:
            raise ValueError("test task builder requires practice hours divisible by two")
        links = task_links or [[] for _ in range(practice_hours // 2)]
        if len(links) != practice_hours // 2:
            raise ValueError("test task link count does not match practice hours")
        course = payload["course_name"]
        tasks = []
        for index, linked_ids in enumerate(links, 1):
            task_id = f"PT-{index:02d}"
            tasks.append(_task(task_id, 2, course, list(linked_ids)))
            if mode in {"integrated_lessons", "hybrid"}:
                for lesson_id in linked_ids:
                    lesson = next(item for item in payload["lessons"] if item["lesson_id"] == lesson_id)
                    lesson["practice_task_ids"].append(task_id)
        payload["practice_task_contract"] = {
            "contract_version": "1.1",
            "course_profile": {
                "course_name": payload["course_name"],
                "major": payload["major"],
                "audience": payload["audience"],
                "total_hours": total_hours,
                "theory_hours": theory_hours,
                "practice_hours": practice_hours,
                "delivery_mode": mode,
                "default_lesson_hours": payload["default_hours"],
            },
            "practice_hours": practice_hours,
            "granularity": "per_task",
            "tasks": tasks,
        }
    else:
        payload.pop("practice_task_contract", None)
    payload["outline"] = [_outline_row(lesson) for lesson in payload["lessons"]]
    _refresh_review_digests(payload)
    payload["authoring_provenance"]["source_snapshot"] = {
        "confirmed_course_profile_sha256": lesson_package_common.canonical_json_sha256(
            payload["confirmed_course_info"]
        ),
        "whole_course_outline_sha256": lesson_package_common.canonical_json_sha256(payload["outline"]),
        "reference_pool_sha256": lesson_package_common.canonical_json_sha256(payload["reference_pool"]),
    }
    return payload


def _integrated_64(*, workorders: bool) -> dict:
    payload = _base_payload(theory_hours=64, lesson_count=32)
    for lesson in payload["lessons"]:
        lesson["hours"] = 2
        lesson["lesson_type"] = "integrated"
        lesson["theory_hours"] = 1
        lesson["practice_hours"] = 1
    task_links = [
        [f"L{index * 2 + 1:02d}", f"L{index * 2 + 2:02d}"]
        for index in range(16)
    ]
    return _bind_v23(
        payload,
        mode="integrated_lessons",
        theory_hours=32,
        practice_hours=32,
        workorders=workorders,
        task_links=task_links if workorders else None,
    )


def _hybrid_8() -> dict:
    payload = _base_payload(theory_hours=8, lesson_count=4)
    composition = (("theory", 2, 0), ("integrated", 1, 1), ("practice", 0, 2), ("integrated", 1, 1))
    for lesson, (lesson_type, theory, practice) in zip(payload["lessons"], composition):
        lesson["lesson_type"] = lesson_type
        lesson["theory_hours"] = theory
        lesson["practice_hours"] = practice
    return _bind_v23(payload, mode="hybrid", theory_hours=4, practice_hours=4)


def _validate_v23(payload: dict) -> None:
    lesson_generator.validate_test_fixture_content_v2_input(payload)


class LessonContentV23Tests(unittest.TestCase):
    def test_final_lesson_keeps_true_remainder(self) -> None:
        payload = _base_payload(theory_hours=6, lesson_count=3)
        final_stages = [stage["minutes"] for stage in payload["lessons"][-1]["implementation"]]
        one_hour_stage_minutes = (10, 5, 10, 12, 5, 5, 3, 5, 15)
        for lesson in payload["lessons"]:
            lesson["lesson_type"] = "theory"
        payload["lessons"][-1]["hours"] = 1
        payload["lessons"][-1]["theory_hours"] = 1
        for stage, minutes in zip(payload["lessons"][-1]["implementation"], one_hour_stage_minutes):
            stage["minutes"] = minutes
        _bind_v23(payload, mode="theory_only", theory_hours=5, practice_hours=0)
        _validate_v23(payload)
        self.assertEqual([item["hours"] for item in payload["lessons"]], [2, 2, 1])
        payload["lessons"][0]["hours"] = 1
        payload["lessons"][0]["theory_hours"] = 1
        for stage, minutes in zip(payload["lessons"][0]["implementation"], one_hour_stage_minutes):
            stage["minutes"] = minutes
        payload["lessons"][-1]["hours"] = 2
        payload["lessons"][-1]["theory_hours"] = 2
        for stage, minutes in zip(payload["lessons"][-1]["implementation"], final_stages):
            stage["minutes"] = minutes
        payload["outline"] = [_outline_row(item) for item in payload["lessons"]]
        _refresh_review_digests(payload)
        payload["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = (
            lesson_package_common.canonical_json_sha256(payload["outline"])
        )
        with self.assertRaisesRegex(ValueError, "final remainder"):
            _validate_v23(payload)

    def test_integrated_64_without_workorders_keeps_full_coverage(self) -> None:
        payload = _integrated_64(workorders=False)
        _validate_v23(payload)
        metrics = lesson_acceptance.delivery_metrics(payload)
        self.assertEqual(metrics["status"], "PASS", metrics)
        self.assertEqual(len(payload["lessons"]), 32)
        self.assertEqual(sum(item["hours"] for item in payload["lessons"]), 64)
        self.assertEqual(sum(item["theory_hours"] for item in payload["lessons"]), 32)
        self.assertEqual(sum(item["practice_hours"] for item in payload["lessons"]), 32)
        self.assertTrue(all(item["practice_task_ids"] == [] for item in payload["lessons"]))
        self.assertNotIn("practice_task_contract", payload)
        self.assertEqual(metrics["actual"]["total_hours"], 64)
        self.assertEqual(metrics["actual"]["theory_hours"], 32)
        self.assertEqual(metrics["actual"]["practice_hours"], 32)
        self.assertEqual(metrics["actual"]["lesson_coverage_hours"], 64)
        self.assertEqual(metrics["lesson_count"], 32)
        self.assertEqual(metrics["lesson_type_counts"], {"theory": 0, "practice": 0, "integrated": 32})

    def test_integrated_64_with_workorders_has_supplementary_16_tasks(self) -> None:
        payload = _integrated_64(workorders=True)
        _validate_v23(payload)
        metrics = lesson_acceptance.delivery_metrics(payload)
        quality = lesson_content_quality.assess_content_quality(payload)
        handoff = lesson_acceptance.practice_handoff_metrics(payload, quality)
        self.assertEqual(metrics["status"], "PASS", metrics)
        self.assertEqual(handoff["status"], "PASS", handoff)
        self.assertEqual(len(payload["lessons"]), 32)
        self.assertEqual(len(payload["practice_task_contract"]["tasks"]), 16)
        self.assertEqual(sum(task["practice_hours"] for task in payload["practice_task_contract"]["tasks"]), 32)
        self.assertEqual(metrics["actual"]["total_hours"], 64)
        self.assertEqual(metrics["actual"]["theory_hours"], 32)
        self.assertEqual(metrics["actual"]["practice_hours"], 32)
        self.assertEqual(metrics["actual"]["lesson_coverage_hours"], 64)
        self.assertEqual(metrics["lesson_count"], 32)
        self.assertEqual(metrics["lesson_type_counts"], {"theory": 0, "practice": 0, "integrated": 32})
        self.assertEqual(metrics["actual"]["workorder_count"], 16)
        self.assertEqual(handoff["practice_hour_allocation_errors"], [])

    def test_hybrid_workorders_partition_all_practice_hours(self) -> None:
        payload = _hybrid_8()
        _bind_v23(
            payload,
            mode="hybrid",
            theory_hours=4,
            practice_hours=4,
            workorders=True,
            task_links=[["L02", "L04"], ["L03"]],
        )
        _validate_v23(payload)
        quality = lesson_content_quality.assess_content_quality(payload)
        handoff = lesson_acceptance.practice_handoff_metrics(payload, quality)
        self.assertEqual(handoff["status"], "PASS", handoff)
        self.assertEqual(handoff["practice_hour_allocation_errors"], [])
        self.assertEqual(
            [task["lesson_ids"] for task in payload["practice_task_contract"]["tasks"]],
            [["L02", "L04"], ["L03"]],
        )

    def test_integrated_and_hybrid_reject_partial_or_overlapping_allocations(self) -> None:
        all_lessons = [f"L{index:02d}" for index in range(1, 33)]
        all_to_all = _integrated_64(workorders=False)
        _bind_v23(
            all_to_all,
            mode="integrated_lessons",
            theory_hours=32,
            practice_hours=32,
            workorders=True,
            task_links=[all_lessons[:] for _ in range(16)],
        )

        partial = _integrated_64(workorders=False)
        _bind_v23(
            partial,
            mode="integrated_lessons",
            theory_hours=32,
            practice_hours=32,
            workorders=True,
            task_links=[["L01"]]
            + [[f"L{index:02d}", f"L{index + 1:02d}"] for index in range(3, 33, 2)],
        )

        overlap = _hybrid_8()
        _bind_v23(
            overlap,
            mode="hybrid",
            theory_hours=4,
            practice_hours=4,
            workorders=True,
            task_links=[["L02", "L04"], ["L02", "L03"]],
        )

        for label, payload in (("all-to-all", all_to_all), ("partial", partial), ("hybrid-overlap", overlap)):
            with self.subTest(allocation=label):
                allocation_errors = lesson_package_common.practice_hour_allocation_errors_v23(payload)
                self.assertTrue(allocation_errors)
                qa_handoff = lesson_content_quality._v23_practice_handoff_report(payload)
                self.assertEqual(qa_handoff["status"], "failed", qa_handoff)
                acceptance_handoff = lesson_acceptance.practice_handoff_metrics(
                    payload,
                    {
                        "content_quality": {
                            "practice_handoff": {
                                "status": "PASS",
                                "hour_consistent": True,
                                "lesson_task_linkage_complete": True,
                            }
                        }
                    },
                )
                self.assertEqual(acceptance_handoff["status"], "FAIL", acceptance_handoff)
                self.assertTrue(acceptance_handoff["practice_hour_allocation_errors"])

        with self.assertRaisesRegex(ValueError, "allocate exactly 2 practice hours"):
            _validate_v23(all_to_all)
        with self.assertRaisesRegex(
            ValueError,
            "allocate exactly 2 practice hours|completely allocated|practice-bearing Lesson must declare",
        ):
            _validate_v23(partial)
        with self.assertRaisesRegex(ValueError, "allocate exactly 2 practice hours|overlaps"):
            _validate_v23(overlap)

    def test_integrated_16_lesson_undercoverage_is_rejected(self) -> None:
        payload = _integrated_64(workorders=False)
        payload["lessons"] = payload["lessons"][:16]
        payload["outline"] = [_outline_row(lesson) for lesson in payload["lessons"]]
        payload["reference_research"]["queries"] = [
            query for query in payload["reference_research"]["queries"]
            if query["lesson_id"] in {lesson["lesson_id"] for lesson in payload["lessons"]}
        ]
        _refresh_review_digests(payload)
        payload["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = (
            lesson_package_common.canonical_json_sha256(payload["outline"])
        )
        with self.assertRaisesRegex(ValueError, "Lesson count must equal ceil"):
            _validate_v23(payload)

    def test_integrated_lesson_practice_sum_cannot_disappear(self) -> None:
        payload = _integrated_64(workorders=False)
        for lesson in payload["lessons"]:
            lesson["theory_hours"] = 2
            lesson["practice_hours"] = 0
        payload["outline"] = [_outline_row(lesson) for lesson in payload["lessons"]]
        _refresh_review_digests(payload)
        payload["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = (
            lesson_package_common.canonical_json_sha256(payload["outline"])
        )
        with self.assertRaisesRegex(ValueError, "integrated must contain positive"):
            _validate_v23(payload)

    def test_theory_only_64_has_32_lessons(self) -> None:
        payload = _base_payload(theory_hours=64, lesson_count=32)
        _bind_v23(payload, mode="theory_only", theory_hours=64, practice_hours=0)
        _validate_v23(payload)
        self.assertEqual(len(payload["lessons"]), 32)
        self.assertEqual(sum(item["hours"] for item in payload["lessons"]), 64)

    def test_split_lessons_keeps_theory_only_coverage_with_optional_workorders(self) -> None:
        payload = _base_payload(
            theory_hours=32,
            practice_hours=32,
            lesson_count=16,
        )
        task_links = [["L01", "L02"] for _ in range(16)]
        _bind_v23(
            payload,
            mode="split_lessons",
            theory_hours=32,
            practice_hours=32,
            workorders=True,
            task_links=task_links,
        )
        _validate_v23(payload)
        metrics = lesson_acceptance.delivery_metrics(payload)
        self.assertEqual(metrics["status"], "PASS", metrics)
        self.assertEqual(len(payload["lessons"]), 16)
        self.assertEqual(sum(item["hours"] for item in payload["lessons"]), 32)
        self.assertTrue(all(item["lesson_type"] == "theory" for item in payload["lessons"]))
        self.assertTrue(all(item["practice_task_ids"] == [] for item in payload["lessons"]))
        self.assertEqual(len(payload["practice_task_contract"]["tasks"]), 16)

    def test_practice_only_keeps_zero_lesson_behavior(self) -> None:
        for workorders in (False, True):
            with self.subTest(workorders=workorders):
                payload = make_v22_payload(
                    course="护理技能实训",
                    major="护理专业",
                    audience="高职二年级",
                    theory_hours=0,
                    practice_hours=32,
                    lesson_count=0,
                    practice_work_orders=workorders,
                    specs=NURSING_SPECS,
                )
                _bind_v23(
                    payload,
                    mode="practice_only",
                    theory_hours=0,
                    practice_hours=32,
                    workorders=workorders,
                    task_links=[[] for _ in range(16)] if workorders else None,
                )
                _validate_v23(payload)
                metrics = lesson_acceptance.delivery_metrics(payload)
                self.assertEqual(metrics["status"], "PASS", metrics)
                self.assertEqual(payload["lessons"], [])
                self.assertFalse(payload["artifact_plan"]["lesson_plans"])

    def test_hybrid_mixes_lesson_types_and_reconciles_hour_ledger(self) -> None:
        payload = _hybrid_8()
        _validate_v23(payload)
        metrics = lesson_acceptance.delivery_metrics(payload)
        self.assertEqual(metrics["status"], "PASS", metrics)
        self.assertEqual(metrics["actual"]["total_hours"], 8)
        self.assertEqual(metrics["actual"]["theory_hours"], 4)
        self.assertEqual(metrics["actual"]["practice_hours"], 4)
        self.assertEqual(metrics["actual"]["lesson_coverage_hours"], 8)
        self.assertEqual(metrics["lesson_type_counts"], {"theory": 1, "practice": 1, "integrated": 2})

    def test_content_22_keeps_historical_64_32_32_accounting(self) -> None:
        payload = make_v22_payload(
            theory_hours=32,
            practice_hours=32,
            lesson_count=16,
            specs=_specs(16),
        )
        lesson_generator.validate_test_fixture_content_v2_input(payload)
        metrics = lesson_acceptance.delivery_metrics(payload)
        self.assertEqual(payload["content_contract_version"], "2.2")
        self.assertEqual(metrics["status"], "PASS", metrics)
        self.assertEqual(metrics["actual"]["lesson_hours"], 32)
        self.assertEqual(len(payload["lessons"]), 16)

    def test_64h_scale_validates_schema_review_benchmark_selection_and_inventory(self) -> None:
        payload = _integrated_64(workorders=True)
        _validate_v23(payload)
        quality = lesson_content_quality.assess_content_quality(payload)
        self.assertEqual(quality["status"], "passed", quality.get("errors"))
        self.assertEqual(quality["agent_pedagogical_review"]["status"], "passed")
        self.assertEqual(
            quality["coverage"]["reference_metrics"]["pool_size"],
            len(payload["reference_pool"]),
        )
        self.assertEqual(len(payload["outline"]), 32)
        self.assertEqual(payload["authoring_provenance"]["review_rounds"], 1)

        catalog = make_catalog(
            12,
            course_name=payload["course_name"],
            major=payload["major"],
            audience=payload["audience"],
        )
        split = build_split(catalog)
        authoring_pack = build_exemplar_pack(catalog, split, "authoring")
        holdout_pack = build_exemplar_pack(catalog, split, "holdout")
        authoring_selection = make_authoring_selection(catalog, split, authoring_pack, payload)
        source_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        holdout_selection = make_holdout_selection(
            catalog,
            split,
            holdout_pack,
            payload,
            hashlib.sha256(source_bytes).hexdigest(),
        )
        self.assertEqual(len(authoring_selection["lessons"]), 32)
        self.assertEqual(len(holdout_selection["lessons"]), 32)
        self.assertEqual(
            validate_authoring_selection_payload(authoring_selection, catalog, split, authoring_pack, payload),
            [],
        )
        self.assertEqual(
            validate_holdout_selection_payload(
                holdout_selection,
                catalog,
                split,
                holdout_pack,
                payload,
                lesson_content_sha256=hashlib.sha256(source_bytes).hexdigest(),
            ),
            [],
        )

        with tempfile.TemporaryDirectory(prefix="lesson-v23-scale-") as temp_name:
            root = Path(temp_name)
            source = root / "lesson-content.json"
            output = root / "output"
            source.write_bytes(source_bytes)
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            actual_docx = sorted(output.glob("*.docx"))
            self.assertEqual(len(actual_docx), 32)
            self.assertEqual(len({path.name for path in actual_docx}), 32)
            self.assertEqual(
                [path.name.startswith(f"教案{index:02d}_") for index, path in enumerate(actual_docx, 1)],
                [True] * 32,
            )
            self.assertEqual(len(manifest["artifacts"]), 32)
            self.assertEqual(
                [record["lesson_id"] for record in manifest["artifacts"]],
                [f"L{index:02d}" for index in range(1, 33)],
            )
            self.assertEqual(
                [record["final_docx_path"] for record in manifest["artifacts"]],
                [path.name for path in actual_docx],
            )
            self.assertTrue(all("candidate" not in record["final_docx_path"] for record in manifest["artifacts"]))
            self.assertEqual(qa["checks"]["file_count"], {"expected": 32, "actual": 32})
            self.assertEqual(qa["checks"]["total_hours"]["expected"], 64)
            self.assertEqual(qa["checks"]["total_hours"]["actual"], 64)
            self.assertEqual(qa["checks"]["course_hours"]["actual"], 64)
            self.assertEqual(lesson_generator._verify_artifact_manifest(output, manifest, source), "structural_pass")
            inventory = {
                "docx_files": [path.relative_to(output).as_posix() for path in actual_docx],
                "docx_count": len(actual_docx),
            }
            acceptance_gate = lesson_acceptance._artifact_manifest_gate(
                payload,
                qa,
                inventory,
                output,
                manifest,
                source,
            )
            self.assertEqual(acceptance_gate["status"], "PASS", acceptance_gate)
            self.assertEqual(acceptance_gate["observed"]["records"], 32)
            self.assertEqual(list(root.glob(f".{output.name}.candidate-*")), [])

    def test_integrated_8h_generation_retains_four_docx_and_pdfs(self) -> None:
        payload = _base_payload(theory_hours=8, lesson_count=4)
        for lesson in payload["lessons"]:
            lesson["lesson_type"] = "integrated"
            lesson["theory_hours"] = 1
            lesson["practice_hours"] = 1
        _bind_v23(payload, mode="integrated_lessons", theory_hours=4, practice_hours=4)
        _validate_v23(payload)

        with tempfile.TemporaryDirectory(prefix="lesson-v23-render-e2e-") as temp_name:
            root = Path(temp_name)
            source = root / "lesson-content.json"
            output = root / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--render",
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            pdfs = sorted((output / "render" / "pdf").glob("*.pdf"))
            self.assertEqual(qa["status"], "passed", qa)
            self.assertEqual(qa["production_status"], "production_pass", qa)
            self.assertEqual(qa["render"]["status"], "passed", qa["render"])
            self.assertEqual(qa["checks"]["file_count"], {"expected": 4, "actual": 4})
            self.assertEqual(qa["checks"]["total_hours"]["actual"], 8)
            self.assertEqual(qa["checks"]["course_hours"]["actual"], 8)
            self.assertEqual(len(manifest["artifacts"]), 4)
            self.assertEqual(len(list(output.glob("*.docx"))), 4)
            self.assertEqual(len(pdfs), 4)
            self.assertTrue(all(item["final_pdf_sha256"] and item["actual_pdf_page_count"] > 0 for item in manifest["artifacts"]))
            self.assertEqual(lesson_generator._verify_artifact_manifest(output, manifest, source), "production_pass")


if __name__ == "__main__":
    unittest.main()
