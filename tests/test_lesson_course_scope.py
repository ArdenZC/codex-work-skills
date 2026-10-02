from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from tests.test_lesson_content_v22 import (
    DB_SPECS,
    NURSING_SPECS,
    _refresh_review_digests,
    _scored_v22_payload,
    make_v22_payload,
)
from tests.test_lesson_content_v23 import _bind_v23
from tests.test_lesson_content_v2 import LESSON, ROOT, run_script
from tests.test_lesson_lifecycle_contracts import _write_json

SCRIPTS = LESSON / "scripts"
if str(SCRIPTS) not in os.sys.path:
    os.sys.path.insert(0, str(SCRIPTS))

from course_scope_grounding import (  # noqa: E402
    CourseScopeGroundingError,
    load_frozen_course_outline,
    validate_course_scope_grounding,
)
from lifecycle_digest import sha256_bytes  # noqa: E402
from package_common import canonical_json_sha256, validate_test_fixture_content_v2_input  # noqa: E402
from source_truth import source_truth_fingerprint  # noqa: E402
import content_quality  # noqa: E402
import render_qa  # noqa: E402


DOMAIN_SPECS = {
    "database": (
        "数据库应用基础",
        "软件技术专业",
        ("项目一 SQL 查询与索引", "完成数据库查询与索引维护", "SQL查询与数据库索引", "查询与索引维护记录", "后续执行计划分析"),
    ),
    "nursing": (
        "基础护理",
        "护理专业",
        NURSING_SPECS[2],
    ),
    "accounting": (
        "会计实务",
        "大数据与会计专业",
        ("项目一 会计凭证处理", "整理会计凭证并核对借贷账簿", "会计凭证录入与账簿核对", "会计凭证与账簿核对表", "后续财务报表编制"),
    ),
    "mechanical": (
        "机械制图与测绘",
        "机械制造专业",
        ("项目一 零件测绘", "完成机械零件测绘与尺寸公差校验", "机械零件测绘与尺寸公差", "零件测绘与尺寸校验记录", "后续零件工艺分析"),
    ),
    "java": (
        "Java 程序设计",
        "软件技术专业",
        ("项目一 Java 类与测试", "完成Java类设计与单元测试", "Java类设计与单元测试", "Java类和单元测试报告", "后续接口集成测试"),
    ),
    "python": (
        "Python 数据处理",
        "计算机应用专业",
        ("项目一 Python 数据处理", "使用Python完成体温数据清洗与统计", "Python数据处理与统计分析", "体温数据处理脚本与统计结果", "后续数据可视化"),
    ),
}


def _domain_content(domain: str, *, version: str = "2.2") -> dict:
    course, major, spec = DOMAIN_SPECS[domain]
    payload = make_v22_payload(
        course=course,
        major=major,
        audience="高职二年级",
        theory_hours=2,
        lesson_count=1,
        specs=(spec,),
    )
    if version == "2.3":
        _bind_v23(payload, mode="theory_only", theory_hours=2, practice_hours=0)
    elif version != "2.2":
        raise ValueError(version)
    return payload


def _freeze_outline(folder: Path, content: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    evidence = folder / "evidence"
    profile = {
        field: content[field]
        for field in ("course_name", "major", "audience")
    }
    profile_raw = _write_json(evidence / "confirmed-profile.json", profile)
    outline_raw = _write_json(evidence / "whole-course-outline.json", content["outline"])
    payload = {
        "contract_version": "1.0",
        "source_truth_id": "ST-SCOPE-001",
        "course_identity": profile,
        "sources": [
            {
                "source_id": "confirmed-profile",
                "source_type": "confirmed_course_profile",
                "label": "Confirmed course facts",
                "locator": "evidence/confirmed-profile.json",
                "sha256": sha256_bytes(profile_raw),
                "provenance": "Synthetic regression fixture",
            },
            {
                "source_id": "frozen-outline",
                "source_type": "whole_course_outline",
                "label": "Frozen whole-course outline",
                "locator": "evidence/whole-course-outline.json",
                "sha256": sha256_bytes(outline_raw),
                "provenance": "Synthetic regression fixture",
            },
        ],
        "created_at": "2026-10-01T10:00:00Z",
        "manifest_fingerprint": "",
    }
    payload["manifest_fingerprint"] = source_truth_fingerprint(payload)
    path = folder / "source-truth.json"
    _write_json(path, payload)
    return path


def _replace_source_outline(source_truth_path: Path, outline: list[dict]) -> None:
    manifest = json.loads(source_truth_path.read_text(encoding="utf-8"))
    outline_path = source_truth_path.parent / manifest["sources"][1]["locator"]
    outline_raw = _write_json(outline_path, outline)
    manifest["sources"][1]["sha256"] = sha256_bytes(outline_raw)
    manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
    _write_json(source_truth_path, manifest)


def _substitute_lesson(content: dict, replacement: dict) -> dict:
    payload = copy.deepcopy(content)
    payload["lessons"] = copy.deepcopy(replacement["lessons"])
    payload["outline"] = copy.deepcopy(replacement["outline"])
    for index, lesson in enumerate(payload["lessons"]):
        lesson["lesson_id"] = content["lessons"][index]["lesson_id"]
        payload["outline"][index]["lesson_id"] = content["outline"][index]["lesson_id"]
        for query in payload.get("reference_research", {}).get("queries", []):
            if query.get("lesson_id") == lesson["lesson_id"]:
                query["query"] = (
                    f"{payload['course_name']} {payload['major']} {lesson['task']} reference research"
                )
    _refresh_review_digests(payload)
    payload["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = canonical_json_sha256(
        payload["outline"]
    )
    return payload


class CourseScopeGroundingTests(unittest.TestCase):
    def test_frozen_outline_binds_database_nursing_accounting_and_mechanical_lessons(self) -> None:
        for domain in ("database", "nursing", "accounting", "mechanical"):
            with self.subTest(domain=domain), tempfile.TemporaryDirectory(prefix="lesson-scope-positive-") as temp:
                content = _domain_content(domain)
                source_truth = _freeze_outline(Path(temp) / "source", content)
                report = validate_course_scope_grounding(
                    content,
                    source_truth,
                    content_path=Path(temp) / "content.json",
                    require_local_outline=True,
                )
                self.assertEqual(report["status"], "passed", report)
                self.assertEqual(report["lesson_count"], 1)
                self.assertEqual(report["lessons"][0]["outline_alignment"], "passed")
                self.assertEqual(report["lessons"][0]["scope_anchor_status"], "passed")
                self.assertEqual(report["lessons"][0]["intra_lesson_status"], "passed")

    def test_full_substitution_matrix_fails_against_each_frozen_domain(self) -> None:
        pairs = (
            ("database", "nursing"),
            ("nursing", "database"),
            ("accounting", "java"),
            ("mechanical", "nursing"),
        )
        for course_domain, lesson_domain in pairs:
            with self.subTest(course=course_domain, lesson=lesson_domain), tempfile.TemporaryDirectory(prefix="lesson-scope-substitution-") as temp:
                source = _domain_content(course_domain)
                substituted = _substitute_lesson(source, _domain_content(lesson_domain))
                validate_test_fixture_content_v2_input(substituted)
                source_truth = _freeze_outline(Path(temp) / "source", source)
                report = validate_course_scope_grounding(
                    substituted,
                    source_truth,
                    content_path=Path(temp) / "substituted-content.json",
                    require_local_outline=True,
                )
                self.assertEqual(report["status"], "failed", report)
                self.assertTrue(
                    any(item["code"] in {"content_outline_frozen_mismatch", "lesson_out_of_frozen_outline_scope"}
                        for item in report["failures"]),
                    report,
                )

    def test_rc02_nursing_substitution_is_schema_valid_but_content_qa_fails_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-rc02-") as temp:
            source = _domain_content("database")
            substituted = _substitute_lesson(source, _domain_content("nursing"))
            validate_test_fixture_content_v2_input(substituted)
            source_truth = _freeze_outline(Path(temp) / "source", source)
            report = content_quality.assess_content_quality(
                substituted,
                source_truth_path=str(source_truth),
                content_path=str(Path(temp) / "substituted-content.json"),
                require_local_outline=True,
            )
            self.assertEqual(report["status"], "failed", report["errors"])
            self.assertEqual(report["course_scope_grounding"]["status"], "failed")
            self.assertTrue(any("content_outline_frozen_mismatch" in error for error in report["errors"]))

    def test_lesson_only_substitution_fails_against_unchanged_content_and_frozen_outlines(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-lesson-only-") as temp:
            source = _domain_content("database")
            source_truth = _freeze_outline(Path(temp) / "source", source)
            substituted = copy.deepcopy(source)
            substituted["lessons"][0] = copy.deepcopy(_domain_content("nursing")["lessons"][0])
            substituted["lessons"][0]["lesson_id"] = source["lessons"][0]["lesson_id"]
            report = validate_course_scope_grounding(
                substituted,
                source_truth,
                content_path=Path(temp) / "lesson-only-content.json",
                require_local_outline=True,
            )
            self.assertEqual(report["status"], "failed", report)
            self.assertTrue(
                any(item["code"] == "lesson_out_of_frozen_outline_scope" for item in report["failures"]),
                report,
            )

    def test_partial_nursing_body_insertion_still_fails_intra_lesson_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-partial-") as temp:
            content = _domain_content("database")
            content["lessons"][0]["teaching_content"].insert(
                1,
                "测量患者血压、判断生命体征异常并形成护理记录。",
            )
            content["lessons"][0]["teaching_content"].insert(
                2,
                "依据医嘱完成静脉输液操作，观察滴速与输液反应。",
            )
            content["lessons"][0]["teaching_content"].insert(
                3,
                "执行无菌护理操作并记录患者处置情况。",
            )
            _refresh_review_digests(content)
            source_truth = _freeze_outline(Path(temp) / "source", content)
            report = validate_course_scope_grounding(
                content,
                source_truth,
                content_path=Path(temp) / "content.json",
                require_local_outline=True,
            )
            self.assertEqual(report["status"], "failed", report)
            self.assertEqual(report["lessons"][0]["outline_alignment"], "passed")
            self.assertEqual(report["lessons"][0]["intra_lesson_status"], "failed")
            self.assertTrue(any(item["code"] == "intra_lesson_coherence" for item in report["failures"]))

    def test_legitimate_cross_domain_application_context_passes(self) -> None:
        cases = (
            (
                "database",
                "使用患者信息表练习SQL查询、主键外键设计和索引优化。",
            ),
            (
                "database",
                "使用订单与财务明细数据编写SQL聚合查询，比较分组统计并优化索引。",
            ),
            (
                "python",
                "使用Python读取体温数据，完成缺失值处理、分组统计并验证结果。",
            ),
            (
                "accounting",
                "使用数据库软件录入会计凭证，按会计科目核对借贷金额并形成凭证清单。",
            ),
        )
        for index, (domain, instructional_context) in enumerate(cases):
            with self.subTest(domain=domain, context=instructional_context), tempfile.TemporaryDirectory(prefix="lesson-scope-context-") as temp:
                content = _domain_content(domain)
                content["lessons"][0]["teaching_content"].insert(0, instructional_context)
                _refresh_review_digests(content)
                validate_test_fixture_content_v2_input(content)
                source_truth = _freeze_outline(Path(temp) / "source", content)
                report = validate_course_scope_grounding(
                    content,
                    source_truth,
                    content_path=Path(temp) / "content.json",
                    require_local_outline=True,
                )
                self.assertEqual(report["status"], "passed", report)
                qa_report = content_quality.assess_content_quality(
                    content,
                    source_truth_path=str(source_truth),
                    content_path=str(Path(temp) / "content.json"),
                    require_local_outline=True,
                )
                self.assertEqual(qa_report["course_scope_grounding"]["status"], "passed", qa_report["errors"])

    def test_content_22_and_23_are_both_supported(self) -> None:
        for version in ("2.2", "2.3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory(prefix="lesson-scope-version-") as temp:
                content = _domain_content("database", version=version)
                validate_test_fixture_content_v2_input(content)
                source_truth = _freeze_outline(Path(temp) / "source", content)
                report = validate_course_scope_grounding(
                    content,
                    source_truth,
                    content_path=Path(temp) / "content.json",
                    require_local_outline=True,
                )
                self.assertEqual(report["status"], "passed", report)

    def test_frozen_outline_loader_rejects_bytes_schema_ids_duplicates_and_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-tamper-") as temp:
            folder = Path(temp)
            content = _domain_content("database")
            source_truth = _freeze_outline(folder / "source", content)
            outline = load_frozen_course_outline(source_truth, require_local_bytes=True)
            self.assertEqual(outline.outline, content["outline"])
            self.assertEqual(outline.source_sha256, hashlib.sha256((folder / "source/evidence/whole-course-outline.json").read_bytes()).hexdigest())

            outline_path = folder / "source/evidence/whole-course-outline.json"
            outline_path.write_bytes(b"[]\n")
            with self.assertRaises(CourseScopeGroundingError) as mismatch:
                load_frozen_course_outline(source_truth, require_local_bytes=True)
            self.assertEqual(mismatch.exception.code, "source_truth_invalid")

        with tempfile.TemporaryDirectory(prefix="lesson-scope-outline-alias-") as temp:
            folder = Path(temp)
            content = _domain_content("database")
            source_truth = _freeze_outline(folder / "source", content)
            outline_path = folder / "source/evidence/whole-course-outline.json"
            with self.assertRaises(CourseScopeGroundingError) as alias:
                load_frozen_course_outline(source_truth, content_path=outline_path)
            self.assertEqual(alias.exception.code, "outline_path_unsafe")

        with tempfile.TemporaryDirectory(prefix="lesson-scope-outline-symlink-") as temp:
            folder = Path(temp)
            content = _domain_content("database")
            source_truth = _freeze_outline(folder / "source", content)
            outline_path = folder / "source/evidence/whole-course-outline.json"
            alias_path = folder / "source/evidence/outline-alias.json"
            symlinks_available = True
            try:
                alias_path.symlink_to(outline_path)
            except (OSError, NotImplementedError):
                symlinks_available = False
            if symlinks_available:
                manifest = json.loads(source_truth.read_text(encoding="utf-8"))
                manifest["sources"][1]["locator"] = "evidence/outline-alias.json"
                manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
                _write_json(source_truth, manifest)
                with self.assertRaises(CourseScopeGroundingError) as symlink:
                    load_frozen_course_outline(source_truth)
                self.assertIn(symlink.exception.code, {"source_truth_invalid", "outline_path_unsafe"})

        with tempfile.TemporaryDirectory(prefix="lesson-scope-schema-") as temp:
            folder = Path(temp)
            content = _domain_content("database")
            source_truth = _freeze_outline(folder / "source", content)
            duplicate = copy.deepcopy(content["outline"])
            duplicate.append(copy.deepcopy(duplicate[0]))
            _replace_source_outline(source_truth, duplicate)
            with self.assertRaises(CourseScopeGroundingError) as duplicate_id:
                load_frozen_course_outline(source_truth)
            self.assertEqual(duplicate_id.exception.code, "outline_duplicate_lesson_id")

    def test_snapshot_recalculation_cannot_override_source_truth_and_lesson_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-self-bind-") as temp:
            source = _domain_content("database")
            source_truth = _freeze_outline(Path(temp) / "source", source)
            substituted = _substitute_lesson(source, _domain_content("nursing"))
            substituted["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = canonical_json_sha256(
                substituted["outline"]
            )
            report = validate_course_scope_grounding(
                substituted,
                source_truth,
                content_path=Path(temp) / "substituted.json",
                require_local_outline=True,
            )
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any(item["code"] == "content_outline_frozen_mismatch" for item in report["failures"]))

            manifest = json.loads(source_truth.read_text(encoding="utf-8"))
            manifest["sources"][1]["sha256"] = "0" * 64
            manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
            _write_json(source_truth, manifest)
            report = validate_course_scope_grounding(source, source_truth, require_local_outline=True)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failures"][0]["code"], "source_truth_invalid")

    def test_outline_id_replacement_and_order_change_fail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-outline-ids-") as temp:
            content = _domain_content("database")
            source_truth = _freeze_outline(Path(temp) / "source", content)
            changed = copy.deepcopy(content["outline"])
            changed[0]["lesson_id"] = "L99"
            _replace_source_outline(source_truth, changed)
            report = validate_course_scope_grounding(content, source_truth, require_local_outline=True)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any(item["code"] == "lesson_set_mismatch" for item in report["failures"]))

        with tempfile.TemporaryDirectory(prefix="lesson-scope-outline-order-") as temp:
            specs = tuple(DB_SPECS[:2])
            content = make_v22_payload(theory_hours=4, lesson_count=2, specs=specs)
            source_truth = _freeze_outline(Path(temp) / "source", content)
            _replace_source_outline(source_truth, list(reversed(content["outline"])))
            report = validate_course_scope_grounding(content, source_truth, require_local_outline=True)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any(item["code"] == "lesson_order_mismatch" for item in report["failures"]))

    def test_missing_outline_is_historical_only_and_https_outline_is_preview_unverified(self) -> None:
        missing_authority = validate_course_scope_grounding({}, None, require_local_outline=True)
        self.assertEqual(missing_authority["status"], "failed")
        self.assertEqual(missing_authority["failures"][0]["code"], "source_truth_missing")

        with tempfile.TemporaryDirectory(prefix="lesson-scope-history-") as temp:
            folder = Path(temp)
            content = _domain_content("database")
            source_truth = _freeze_outline(folder / "source", content)
            manifest = json.loads(source_truth.read_text(encoding="utf-8"))
            manifest["sources"] = manifest["sources"][:1]
            manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
            _write_json(source_truth, manifest)
            # General Source Truth 1.0 audit stays compatible, while the current
            # canonical scope helper refuses to authorize the missing outline.
            with self.assertRaises(CourseScopeGroundingError) as missing:
                load_frozen_course_outline(source_truth)
            self.assertEqual(missing.exception.code, "outline_source_missing")

        with tempfile.TemporaryDirectory(prefix="lesson-scope-https-") as temp:
            content = _domain_content("database")
            source_truth = _freeze_outline(Path(temp) / "source", content)
            manifest = json.loads(source_truth.read_text(encoding="utf-8"))
            manifest["sources"][1]["locator"] = "https://example.com/frozen-outline.json"
            manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
            _write_json(source_truth, manifest)
            with patch.object(socket, "socket", side_effect=AssertionError("scope validation must stay offline")):
                preview = validate_course_scope_grounding(content, source_truth, require_local_outline=False)
                production = validate_course_scope_grounding(content, source_truth, require_local_outline=True)
            self.assertEqual(preview["status"], "unverified", preview)
            self.assertEqual(preview["lessons"][0]["scope_anchor_status"], "unverified")
            self.assertEqual(production["status"], "failed", production)
            self.assertEqual(production["failures"][0]["code"], "outline_bytes_unverified")

    def test_pipeline_bind_content_fails_before_binding_and_preview_keeps_unverified_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-pipeline-") as temp:
            folder = Path(temp)
            source = _domain_content("database")
            source_truth = _freeze_outline(folder / "authority", source)
            substituted = _substitute_lesson(source, _domain_content("nursing"))
            substituted["authoring_provenance"]["mode"] = "agent"
            content_path = folder / "substituted.json"
            _write_json(content_path, substituted)
            run_path = folder / "production-run.json"

            import run_lesson_pipeline as pipeline

            pipeline.execute("init", run_path, mode="PRODUCTION", run_id="SCOPE-RUN-001", source_truth=source_truth)
            pipeline.execute("freeze-source-truth", run_path)
            before = json.loads(run_path.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(Exception, "course-scope grounding failed before Content binding"):
                pipeline.execute("bind-content", run_path, content=content_path)
            after = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(after["state"], before["state"])
            self.assertNotIn("content", after["bindings"])

        with tempfile.TemporaryDirectory(prefix="lesson-scope-preview-") as temp:
            folder = Path(temp)
            content = _domain_content("database")
            content["authoring_provenance"]["mode"] = "agent"
            source_truth = _freeze_outline(folder / "authority", content)
            manifest = json.loads(source_truth.read_text(encoding="utf-8"))
            manifest["sources"][1]["locator"] = "https://example.com/course-outline.json"
            manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
            _write_json(source_truth, manifest)
            content_path = folder / "content.json"
            _write_json(content_path, content)
            run_path = folder / "preview-run.json"

            import run_lesson_pipeline as pipeline

            pipeline.execute("init", run_path, mode="PREVIEW", run_id="SCOPE-PREVIEW-001", source_truth=source_truth)
            pipeline.execute("freeze-source-truth", run_path)
            bound = pipeline.execute("bind-content", run_path, content=content_path)
            self.assertEqual(bound["state"]["current_state"], "AUTHORING_COMPLETE")
            status = pipeline.execute("status", run_path)
            self.assertEqual(status["mode"], "PREVIEW")

    def test_real_generator_scope_failure_preserves_old_output_qa_and_transaction_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-scope-generator-transaction-") as temp:
            folder = Path(temp)
            source = _domain_content("database")
            source_truth = _freeze_outline(folder / "authority", source)
            contaminated = _substitute_lesson(source, _domain_content("nursing"))
            content_path = folder / "contaminated.json"
            _write_json(content_path, contaminated)
            output = folder / "output"
            output.mkdir()
            sentinel = output / "sentinel.bin"
            sentinel.write_bytes(b"old-output-sentinel\x00\xff")
            qa_report = folder / "external-qa.json"
            qa_report.write_bytes(b"old-qa-sentinel")
            before = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}

            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(content_path),
                "--source-truth", str(source_truth),
                "--output-dir", str(output),
                "--qa-report", str(qa_report),
                "--backup-existing",
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("course-scope grounding failed before candidate creation", result.stderr)
            after = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
            self.assertEqual(qa_report.read_bytes(), b"old-qa-sentinel")
            self.assertFalse((output / "artifact-manifest.json").exists())
            self.assertFalse((output / "qa-report.json").exists())
            self.assertEqual(list(folder.glob(".output.candidate-*")), [])
            self.assertEqual(list(folder.glob("_output_backup_*")), [])
            self.assertEqual(list(folder.glob("*qa*backup*")), [])

    def test_real_generator_rejects_mechanical_scores_without_mutating_transaction_state(self) -> None:
        cases = (
            ("all_same", (90, 90, 90, 90, 90, 90)),
            ("simple_cycle", (88, 89, 90, 88, 89, 90)),
            ("arithmetic_progression", (88, 88.5, 89, 89.5, 90, 90.5)),
        )
        for flag, scores in cases:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory(
                prefix=f"lesson-score-pattern-{flag}-transaction-"
            ) as temp:
                folder = Path(temp)
                content = _scored_v22_payload(scores)
                self.assertEqual(content["content_contract_version"], "2.2")
                validate_test_fixture_content_v2_input(content)
                content_path = folder / "content.json"
                _write_json(content_path, content)
                source_truth = _freeze_outline(folder / "authority", content)

                qa = content_quality.assess_content_quality(
                    content,
                    source_truth_path=str(source_truth),
                    content_path=str(content_path),
                    require_local_outline=True,
                )
                self.assertEqual(qa["status"], "failed", qa)
                self.assertTrue(qa["coverage"]["score_pattern"][flag], qa)
                self.assertTrue(any("evaluation scores" in message for message in qa["errors"]), qa)

                output = folder / "output"
                output.mkdir()
                sentinel = output / "sentinel.bin"
                sentinel.write_bytes(b"old-output-sentinel\x00\xff")
                old_qa = output / "qa-report.json"
                old_qa.write_bytes(b"old-output-qa-bytes")
                old_manifest = output / "artifact-manifest.json"
                old_manifest.write_bytes(b"old-artifact-manifest-bytes")
                external_qa = folder / "external-qa.json"
                external_qa.write_bytes(b"old-external-qa-bytes")
                before = {
                    path.relative_to(output).as_posix(): path.read_bytes()
                    for path in output.rglob("*")
                    if path.is_file()
                }

                result = run_script(
                    LESSON / "scripts" / "generate_lesson_plans.py",
                    "--tasks-json", str(content_path),
                    "--source-truth", str(source_truth),
                    "--output-dir", str(output),
                    "--qa-report", str(external_qa),
                    "--backup-existing",
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Content quality validation failed", result.stderr)
                after = {
                    path.relative_to(output).as_posix(): path.read_bytes()
                    for path in output.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)
                self.assertEqual(external_qa.read_bytes(), b"old-external-qa-bytes")
                self.assertEqual(sentinel.read_bytes(), b"old-output-sentinel\x00\xff")
                self.assertEqual(old_manifest.read_bytes(), b"old-artifact-manifest-bytes")
                self.assertEqual(old_qa.read_bytes(), b"old-output-qa-bytes")
                residues = [
                    path.name
                    for path in folder.iterdir()
                    if any(token in path.name.casefold() for token in ("candidate", "staging", "stage", "backup"))
                ]
                self.assertEqual(residues, [])

    def test_real_generator_publishes_valid_scoped_content_and_rendered_artifacts(self) -> None:
        if render_qa.find_renderer() is None:
            if os.environ.get("CI"):
                self.fail("CI must render the valid frozen-outline generation regression")
            self.skipTest("LibreOffice is unavailable for the local render regression")
        with tempfile.TemporaryDirectory(prefix="lesson-scope-generator-valid-") as temp:
            folder = Path(temp)
            scores = (90, 91, 90, 92, 90, 93)
            content = _scored_v22_payload(scores)
            self.assertEqual(content["content_contract_version"], "2.2")
            validate_test_fixture_content_v2_input(content)
            content_path = folder / "content.json"
            _write_json(content_path, content)
            source_truth = _freeze_outline(folder / "authority", content)
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(content_path),
                "--source-truth", str(source_truth),
                "--output-dir", str(output),
                "--run-id", "SCOPE-GEN-001",
                "--render",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["content_quality"]["course_scope_grounding"]["status"], "passed")
            self.assertEqual(qa["content_quality"]["status"], "passed", qa["content_quality"])
            score_pattern = qa["content_quality"]["coverage"]["score_pattern"]
            self.assertEqual(score_pattern["values"], [float(score) for score in scores])
            self.assertLess(len(set(score_pattern["values"])), len(score_pattern["values"]))
            self.assertFalse(score_pattern["all_same"])
            self.assertFalse(score_pattern["simple_cycle"])
            self.assertFalse(score_pattern["arithmetic_progression"])
            self.assertFalse(score_pattern["strict_monotonic"])
            self.assertEqual(qa["render"]["status"], "passed", qa["render"])
            self.assertEqual(manifest["production_status"], "production_pass")
            self.assertEqual(len(list(output.glob("*.docx"))), 6)
            self.assertEqual(len(list((output / "render" / "pdf").glob("*.pdf"))), 6)
            self.assertEqual(manifest["run_id"], "SCOPE-GEN-001")


if __name__ == "__main__":
    unittest.main()
