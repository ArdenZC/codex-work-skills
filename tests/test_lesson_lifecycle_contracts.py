from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any

if sys.platform == "darwin":
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())

ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
SCRIPTS = LESSON / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lifecycle_digest import (  # noqa: E402
    LifecycleContractError,
    canonical_json_bytes,
    read_json_object,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
    skill_tree_fingerprint,
)
from pipeline_state import (  # noqa: E402
    advance_pipeline_state,
    initial_pipeline_state,
    pipeline_state_fingerprint,
    stale_downstream,
    validate_pipeline_artifact_bytes,
    validate_pipeline_state_payload,
)
import pipeline_state as pipeline_state_module  # noqa: E402
from production_authorization import (  # noqa: E402
    _current_repo_commit,
    production_authorization_fingerprint,
    runtime_versions,
    validate_production_authorization_files,
    validate_production_authorization_payload,
)
from source_truth import source_truth_fingerprint, validate_source_truth_payload  # noqa: E402
from teacher_review import (  # noqa: E402
    teacher_review_fingerprint,
    validate_teacher_review_files,
    validate_teacher_review_payload,
)


def _digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _write_json(path: Path, payload: Any, *, indent: int | None = 2) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def _source_truth(directory: Path) -> tuple[dict[str, Any], Path]:
    directory.mkdir(parents=True, exist_ok=True)
    evidence = directory / "evidence"
    profile_raw = _write_json(evidence / "profile.json", {"course_name": "数据库应用基础"})
    outline_raw = _write_json(evidence / "outline.json", [{"lesson_id": "L01"}])
    manifest_path = directory / "source-truth.json"
    payload: dict[str, Any] = {
        "contract_version": "1.0",
        "source_truth_id": "ST-001",
        "course_identity": {"course_name": "数据库应用基础", "major": "软件技术", "audience": "高职二年级"},
        "sources": [
            {
                "source_id": "profile",
                "source_type": "confirmed_course_profile",
                "label": "confirmed profile",
                "locator": "evidence/profile.json",
                "sha256": sha256_bytes(profile_raw),
                "provenance": "User-confirmed course information",
            },
            {
                "source_id": "outline",
                "source_type": "whole_course_outline",
                "label": "whole-course outline",
                "locator": "evidence/outline.json",
                "sha256": sha256_bytes(outline_raw),
                "provenance": "User-provided course outline",
            },
        ],
        "created_at": "2026-09-29T10:00:00Z",
        "manifest_fingerprint": "",
    }
    payload["manifest_fingerprint"] = source_truth_fingerprint(payload)
    _write_json(manifest_path, payload)
    return payload, manifest_path


def _content() -> dict[str, Any]:
    return {
        "content_contract_version": "2.3",
        "course_name": "数据库应用基础",
        "major": "软件技术",
        "audience": "高职二年级",
        "lessons": [{"lesson_id": "L01"}, {"lesson_id": "L02"}],
    }


def _benchmark(disposition: str, evidence_sha: str | None = None) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "authorization_sha256": None,
        "review_sha256": None,
        "evidence_sha256": evidence_sha,
        "waiver_reference": "owner-approved waiver LIF-01" if disposition == "BENCHMARK_WAIVED_BY_USER" else None,
    }


def _teacher_review(source_raw: bytes, content_raw: bytes, benchmark: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = {"rating": 4, "notes": "Evidence-backed finding."}
    course_evidence = {"assessment": "acceptable", "notes": "Course-level review evidence."}
    payload: dict[str, Any] = {
        "contract_version": "1.0",
        "teacher_review_id": "TR-001",
        "pipeline_run_id": "RUN-001",
        "source_truth_manifest_sha256": sha256_bytes(source_raw),
        "content_sha256": sha256_bytes(content_raw),
        "benchmark": benchmark,
        "selected_lessons": [
            {
                "lesson_id": "L01",
                "selection_reasons": ["first_lesson"],
                "directly_teachable": copy.deepcopy(evidence),
                "task_executable": copy.deepcopy(evidence),
                "steps_operable": copy.deepcopy(evidence),
                "evaluation_observable": copy.deepcopy(evidence),
                "reflection_improvable": copy.deepcopy(evidence),
                "notes": "Selected because it establishes the first unit.",
            }
        ],
        "whole_course_review": {
            "progression": copy.deepcopy(course_evidence),
            "scope": copy.deepcopy(course_evidence),
            "theory_practice_coherence": copy.deepcopy(course_evidence),
            "repetition_template_risk": copy.deepcopy(course_evidence),
            "difficulty_fit": copy.deepcopy(course_evidence),
            "overall_notes": "Course review evidence.",
        },
        "decision": "APPROVED",
        "decision_notes": "Approved for the bound Content bytes.",
        "reviewed_at": "2026-09-29T10:05:00Z",
        "review_fingerprint": "",
    }
    payload["review_fingerprint"] = teacher_review_fingerprint(payload)
    return payload


def _production_authorization(
    source_raw: bytes,
    content_raw: bytes,
    review_raw: bytes,
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    from package_common import DEFAULT_MANIFEST, manifest_template_path, load_manifest

    manifest = load_manifest(DEFAULT_MANIFEST)
    template = manifest_template_path(manifest)
    commit = _current_repo_commit(LESSON)
    payload: dict[str, Any] = {
        "contract_version": "1.0",
        "authorization_id": "PA-001",
        "pipeline_run_id": "RUN-001",
        "source_truth_manifest_sha256": sha256_bytes(source_raw),
        "content_sha256": sha256_bytes(content_raw),
        "teacher_review_sha256": sha256_bytes(review_raw),
        "benchmark": copy.deepcopy(benchmark),
        "lesson_skill": {
            "version": "2.3.1",
            "installed_skill_fingerprint": skill_tree_fingerprint(LESSON),
            "source_repo_commit": commit,
        },
        "content_contract_version": "2.3",
        "template": {
            "template_id": "lesson-plan",
            "template_version": "1.1.2",
            "template_sha256": sha256_file(template),
            "manifest_sha256": sha256_file(DEFAULT_MANIFEST),
        },
        "runtime": {
            **runtime_versions(),
            "libreoffice_version": None,
            "render_performed": False,
        },
        "created_at": "2026-09-29T10:10:00Z",
        "authorization_fingerprint": "",
    }
    payload["authorization_fingerprint"] = production_authorization_fingerprint(payload)
    return payload


class LifecycleDigestTests(unittest.TestCase):
    def test_canonical_json_policy_and_fingerprint_stability(self) -> None:
        left = {"z": "e\u0301", "a": [1, 2], "created_at": "one"}
        right = {"a": [1, 2], "created_at": "one", "z": "é"}
        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        volatile = {**right, "created_at": "two"}
        self.assertEqual(
            semantic_fingerprint(left, excluded_fields={"created_at"}),
            semantic_fingerprint(volatile, excluded_fields={"created_at"}),
        )
        self.assertNotEqual(
            semantic_fingerprint(left, excluded_fields={"created_at"}),
            semantic_fingerprint({**right, "a": [2, 1]}, excluded_fields={"created_at"}),
        )
        self.assertEqual(
            semantic_fingerprint({"content_sha256": "A" * 64}),
            semantic_fingerprint({"content_sha256": "a" * 64}),
        )
        with self.assertRaises(LifecycleContractError):
            canonical_json_bytes({"ratio": 1.5})
        with self.assertRaises(LifecycleContractError):
            canonical_json_bytes({"é": 1, "e\u0301": 2})
        compact = json.loads('{"first":1,"second":[2,3]}')
        pretty = json.loads('{\n  "first": 1,\n  "second": [2, 3]\n}')
        self.assertEqual(canonical_json_bytes(compact), canonical_json_bytes(pretty))

    def test_json_loader_rejects_duplicate_nfc_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text('{"é": 1, "e\\u0301": 2}', encoding="utf-8")
            with self.assertRaises(LifecycleContractError):
                read_json_object(path, "duplicate_test")

    def test_array_policy_is_explicit_and_source_hash_changes_fingerprint(self) -> None:
        sources_a = {"sources": [{"source_id": "a"}, {"source_id": "b"}]}
        sources_b = {"sources": [{"source_id": "b"}, {"source_id": "a"}]}
        self.assertEqual(
            semantic_fingerprint(sources_a, unordered_arrays={"sources"}),
            semantic_fingerprint(sources_b, unordered_arrays={"sources"}),
        )
        self.assertNotEqual(semantic_fingerprint(sources_a), semantic_fingerprint(sources_b))
        payload = {"sources": [{"sha256": "a" * 64}]}
        self.assertNotEqual(
            source_truth_fingerprint(payload),
            source_truth_fingerprint({"sources": [{"sha256": "b" * 64}]}),
        )


class SourceTruthContractTests(unittest.TestCase):
    def test_valid_manifest_ignores_timestamp_and_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            payload, manifest_path = _source_truth(Path(temp))
            self.assertEqual(validate_source_truth_payload(payload, manifest_path=manifest_path), [])
            reordered = copy.deepcopy(payload)
            reordered["sources"].reverse()
            self.assertEqual(source_truth_fingerprint(reordered), payload["manifest_fingerprint"])
            upper_digest = copy.deepcopy(payload)
            upper_digest["sources"][0]["sha256"] = upper_digest["sources"][0]["sha256"].upper()
            self.assertEqual(source_truth_fingerprint(upper_digest), payload["manifest_fingerprint"])
            user_attachment = copy.deepcopy(payload)
            attachment_raw = b"separately supplied course attachment"
            (manifest_path.parent / "evidence" / "attachment.bin").write_bytes(attachment_raw)
            user_attachment["sources"].append(
                {
                    "source_id": "attachment",
                    "source_type": "user_attachment",
                    "label": "user attachment",
                    "locator": "evidence/attachment.bin",
                    "sha256": sha256_bytes(attachment_raw),
                    "provenance": "User-supplied course attachment",
                }
            )
            user_attachment["manifest_fingerprint"] = source_truth_fingerprint(user_attachment)
            self.assertEqual(validate_source_truth_payload(user_attachment, manifest_path=manifest_path), [])
            payload["created_at"] = "2026-09-29T11:00:00Z"
            self.assertEqual(source_truth_fingerprint(payload), payload["manifest_fingerprint"])

    def test_duplicate_sources_missing_critical_and_local_hash_mismatch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            payload, manifest_path = _source_truth(Path(temp))
            duplicate = copy.deepcopy(payload)
            duplicate["sources"][1]["source_id"] = duplicate["sources"][0]["source_id"]
            duplicate["manifest_fingerprint"] = source_truth_fingerprint(duplicate)
            errors = validate_source_truth_payload(duplicate, manifest_path=manifest_path)
            self.assertTrue(any("source_id is duplicated" in item for item in errors))

            duplicate_semantic = copy.deepcopy(payload)
            duplicate_semantic["sources"][1]["locator"] = duplicate_semantic["sources"][0]["locator"]
            duplicate_semantic["sources"][1]["source_type"] = duplicate_semantic["sources"][0]["source_type"]
            duplicate_semantic["manifest_fingerprint"] = source_truth_fingerprint(duplicate_semantic)
            errors = validate_source_truth_payload(duplicate_semantic, manifest_path=manifest_path)
            self.assertTrue(any("duplicates a semantic source" in item for item in errors))

            missing = copy.deepcopy(payload)
            missing["sources"] = [missing["sources"][0]]
            missing["manifest_fingerprint"] = source_truth_fingerprint(missing)
            errors = validate_source_truth_payload(missing, manifest_path=manifest_path)
            self.assertTrue(any("whole_course_outline" in item for item in errors))

            missing_profile = copy.deepcopy(payload)
            missing_profile["sources"] = [missing_profile["sources"][1]]
            missing_profile["manifest_fingerprint"] = source_truth_fingerprint(missing_profile)
            errors = validate_source_truth_payload(missing_profile, manifest_path=manifest_path)
            self.assertTrue(any("confirmed_course_profile" in item for item in errors))

            (Path(temp) / "evidence" / "profile.json").write_text("changed", encoding="utf-8")
            errors = validate_source_truth_payload(payload, manifest_path=manifest_path)
            self.assertTrue(any("does not match local source bytes" in item for item in errors))

    def test_unsafe_locator_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload, manifest_path = _source_truth(root / "manifest-root")
            unsafe = copy.deepcopy(payload)
            unsafe["sources"][0]["locator"] = "../outside.json"
            unsafe["manifest_fingerprint"] = source_truth_fingerprint(unsafe)
            errors = validate_source_truth_payload(unsafe, manifest_path=manifest_path)
            self.assertTrue(any("unsafe" in item for item in errors))

            alias = root / "manifest-root" / "evidence" / "profile-link.json"
            try:
                os.symlink(root / "manifest-root" / "evidence" / "profile.json", alias)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")
            linked = copy.deepcopy(payload)
            linked["sources"][0]["locator"] = "evidence/profile-link.json"
            linked["manifest_fingerprint"] = source_truth_fingerprint(linked)
            errors = validate_source_truth_payload(linked, manifest_path=manifest_path)
            self.assertTrue(any("unsafe" in item for item in errors))


class TeacherReviewContractTests(unittest.TestCase):
    def test_review_links_exact_source_and_content_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            _source, source_path = _source_truth(directory / "run")
            source_raw = source_path.read_bytes()
            content = _content()
            content_path = directory / "run" / "lesson-content.json"
            content_raw = _write_json(content_path, content)
            review = _teacher_review(source_raw, content_raw)
            self.assertEqual(
                validate_teacher_review_payload(
                    review,
                    source_truth_manifest_sha256=sha256_bytes(source_raw),
                    content_sha256=sha256_bytes(content_raw),
                    content=content,
                ),
                [],
            )
            review_path = directory / "run" / "review.json"
            _write_json(review_path, review)
            _loaded, _raw, errors = validate_teacher_review_files(
                review_path, source_truth_path=source_path, content_path=content_path
            )
            self.assertEqual(errors, [])
            with self.assertRaises(LifecycleContractError):
                validate_teacher_review_files(
                    content_path,
                    source_truth_path=source_path,
                    content_path=content_path,
                )

            content_path.write_bytes(content_raw + b" ")
            _loaded, _raw, errors = validate_teacher_review_files(
                review_path, source_truth_path=source_path, content_path=content_path
            )
            self.assertTrue(any("content_sha256 is stale" in item for item in errors))

            content_path.write_bytes(content_raw)
            source_path.write_bytes(source_raw + b" ")
            _loaded, _raw, errors = validate_teacher_review_files(
                review_path, source_truth_path=source_path, content_path=content_path
            )
            self.assertTrue(any("source_truth_manifest_sha256 is stale" in item for item in errors))

    def test_duplicate_selection_notes_advisory_and_missing_hashes(self) -> None:
        source_raw = b"{}"
        content = _content()
        content_raw = json.dumps(content).encode("utf-8")
        review = _teacher_review(source_raw, content_raw)
        duplicate = copy.deepcopy(review)
        duplicate["selected_lessons"].append(copy.deepcopy(duplicate["selected_lessons"][0]))
        duplicate["review_fingerprint"] = teacher_review_fingerprint(duplicate)
        errors = validate_teacher_review_payload(duplicate, content=content)
        self.assertTrue(any("duplicate lesson_id" in item for item in errors))

        unicode_duplicate = copy.deepcopy(review)
        unicode_duplicate["selected_lessons"].append(copy.deepcopy(unicode_duplicate["selected_lessons"][0]))
        unicode_duplicate["selected_lessons"][0]["lesson_id"] = "L\u00e901"
        unicode_duplicate["selected_lessons"][1]["lesson_id"] = "Le\u030101"
        unicode_duplicate["review_fingerprint"] = teacher_review_fingerprint(unicode_duplicate)
        errors = validate_teacher_review_payload(unicode_duplicate)
        self.assertTrue(any("duplicate lesson_id" in item for item in errors))

        unknown = copy.deepcopy(review)
        unknown["selected_lessons"][0]["lesson_id"] = "UNKNOWN"
        unknown["review_fingerprint"] = teacher_review_fingerprint(unknown)
        errors = validate_teacher_review_payload(unknown, content=content)
        self.assertTrue(any("unknown Content lesson_id" in item for item in errors))

        blank_evidence = copy.deepcopy(review)
        blank_evidence["selected_lessons"][0]["directly_teachable"]["notes"] = " "
        blank_evidence["review_fingerprint"] = teacher_review_fingerprint(blank_evidence)
        errors = validate_teacher_review_payload(blank_evidence, content=content)
        self.assertTrue(any("must contain evidence text" in item for item in errors))

        notes = copy.deepcopy(review)
        notes["decision"] = "APPROVED_WITH_NOTES"
        notes["reviewed_at"] = "2026-09-30T10:00:00Z"
        notes["review_fingerprint"] = teacher_review_fingerprint(notes)
        self.assertEqual(validate_teacher_review_payload(notes, content=content), [])

        missing = copy.deepcopy(review)
        missing.pop("content_sha256")
        errors = validate_teacher_review_payload(missing)
        self.assertTrue(any("content_sha256" in item for item in errors))

    def test_benchmark_disposition_evidence_and_not_executed_boundary(self) -> None:
        evidence = b"partial benchmark evidence"
        benchmark = _benchmark("BENCHMARK_UNAVAILABLE", sha256_bytes(evidence))
        missing_errors = validate_teacher_review_payload(
            _teacher_review(b"{}", b"{}", benchmark),
            benchmark_evidence_path=None,
        )
        self.assertTrue(any("requires the benchmark evidence file" in item for item in missing_errors))
        with tempfile.TemporaryDirectory() as temp:
            evidence_path = Path(temp) / "evidence.json"
            evidence_path.write_bytes(evidence)
            review = _teacher_review(b"{}", b"{}", benchmark)
            self.assertEqual(
                validate_teacher_review_payload(review, benchmark_evidence_path=evidence_path), []
            )
            waiver = _benchmark("BENCHMARK_WAIVED_BY_USER", sha256_bytes(evidence))
            waiver_review = _teacher_review(b"{}", b"{}", waiver)
            self.assertEqual(
                validate_teacher_review_payload(waiver_review, benchmark_evidence_path=evidence_path), []
            )
            evidence_path.write_bytes(b"changed")
            errors = validate_teacher_review_payload(waiver_review, benchmark_evidence_path=evidence_path)
            self.assertTrue(any("does not match benchmark evidence file bytes" in item for item in errors))

            auth_file = Path(temp) / "benchmark-authorization.json"
            review_file = Path(temp) / "benchmark-review.json"
            auth_raw = b"benchmark auth exact bytes"
            review_raw = b"benchmark review exact bytes"
            auth_file.write_bytes(auth_raw)
            review_file.write_bytes(review_raw)
            complete = _benchmark("BENCHMARK_REVIEW_COMPLETE")
            complete["authorization_sha256"] = sha256_bytes(auth_raw)
            complete["review_sha256"] = sha256_bytes(review_raw)
            complete_review = _teacher_review(b"{}", b"{}", complete)
            self.assertEqual(
                validate_teacher_review_payload(
                    complete_review,
                    benchmark_authorization_path=auth_file,
                    benchmark_review_path=review_file,
                ),
                [],
            )
            review_file.write_bytes(review_raw + b" ")
            errors = validate_teacher_review_payload(
                complete_review,
                benchmark_authorization_path=auth_file,
                benchmark_review_path=review_file,
            )
            self.assertTrue(any("review_sha256 does not match benchmark review file bytes" in item for item in errors))

        invalid = _teacher_review(b"{}", b"{}", _benchmark("BENCHMARK_NOT_EXECUTED", "a" * 64))
        errors = validate_teacher_review_payload(invalid, require_benchmark_bytes=False)
        self.assertTrue(errors)


class ProductionAuthorizationTests(unittest.TestCase):
    def _valid_files(self, directory: Path) -> tuple[Path, Path, Path, Path, Path, dict[str, Any]]:
        _source, source_path = _source_truth(directory / "run")
        source_raw = source_path.read_bytes()
        content = _content()
        content_path = directory / "run" / "lesson-content.json"
        content_raw = _write_json(content_path, content)
        evidence_path = directory / "run" / "benchmark-evidence.json"
        evidence_raw = _write_json(evidence_path, {"reason": "no verified benchmark fixture supplied"})
        benchmark = _benchmark("BENCHMARK_UNAVAILABLE", sha256_bytes(evidence_raw))
        review = _teacher_review(source_raw, content_raw, benchmark)
        review_path = directory / "run" / "teacher-review.json"
        review_raw = _write_json(review_path, review)
        authorization = _production_authorization(source_raw, content_raw, review_raw, benchmark)
        authorization_path = directory / "run" / "production-authorization.json"
        _write_json(authorization_path, authorization)
        return source_path, content_path, review_path, evidence_path, authorization_path, authorization

    def test_authorization_binds_review_template_skill_runtime_and_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source, content, review, evidence, authorization_path, _authorization = self._valid_files(directory)
            authorization, raw, errors = validate_production_authorization_files(
                authorization_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=True,
            )
            self.assertEqual(errors, [])
            self.assertEqual(sha256_bytes(raw), _digest(raw))
            self.assertEqual(authorization["pipeline_run_id"], "RUN-001")

    def test_stale_content_notes_authorize_revision_rejects_and_provenance_binds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source, content, review, evidence, auth_path, authorization = self._valid_files(directory)

            content.write_bytes(content.read_bytes() + b" ")
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            self.assertTrue(any("content_sha256" in item for item in errors))
            _write_json(content, _content())

            review_payload = json.loads(review.read_text(encoding="utf-8"))
            review_payload["decision"] = "APPROVED_WITH_NOTES"
            review_payload["review_fingerprint"] = teacher_review_fingerprint(review_payload)
            review_raw = _write_json(review, review_payload)
            authorization["teacher_review_sha256"] = sha256_bytes(review_raw)
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            self.assertEqual(errors, [])

            review_payload["decision"] = "REVISION_REQUIRED"
            review_payload["review_fingerprint"] = teacher_review_fingerprint(review_payload)
            review_raw = _write_json(review, review_payload)
            authorization["teacher_review_sha256"] = sha256_bytes(review_raw)
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            self.assertTrue(any("only APPROVED or APPROVED_WITH_NOTES" in item for item in errors))

            review_payload["decision"] = "APPROVED"
            review_payload["review_fingerprint"] = teacher_review_fingerprint(review_payload)
            review_raw = _write_json(review, review_payload)
            authorization["teacher_review_sha256"] = sha256_bytes(review_raw)
            authorization["template"]["template_sha256"] = "0" * 64
            authorization["lesson_skill"]["installed_skill_fingerprint"] = "1" * 64
            authorization["lesson_skill"]["source_repo_commit"] = None
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            self.assertTrue(any("template_sha256" in item for item in errors))
            self.assertTrue(any("installed_skill_fingerprint" in item for item in errors))
            self.assertTrue(any("source_repo_commit" in item for item in errors))

    def test_source_and_review_sha_staleness_and_authorization_fingerprint_tamper_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source, content, review, evidence, auth_path, authorization = self._valid_files(Path(temp))
            source_raw = source.read_bytes()
            review_raw = review.read_bytes()

            source.write_bytes(source_raw + b" ")
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            self.assertTrue(any("source_truth_manifest_sha256" in item for item in errors))
            source.write_bytes(source_raw)

            review.write_bytes(review_raw + b" ")
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            self.assertTrue(any("teacher_review_sha256" in item for item in errors))

            authorization["authorization_fingerprint"] = "0" * 64
            _write_json(auth_path, authorization)
            errors = validate_production_authorization_payload(authorization)
            self.assertTrue(any("authorization_fingerprint does not match" in item for item in errors))

    def test_invalid_disposition_missing_sha_and_waiver_evidence_contract(self) -> None:
        base = {
            "contract_version": "1.0",
            "authorization_id": "PA-X",
            "pipeline_run_id": "RUN-X",
            "source_truth_manifest_sha256": "a" * 64,
            "content_sha256": "b" * 64,
            "teacher_review_sha256": "c" * 64,
            "benchmark": _benchmark("BENCHMARK_NOT_EXECUTED", "d" * 64),
            "lesson_skill": {"version": "2.3.1", "installed_skill_fingerprint": "e" * 64, "source_repo_commit": None},
            "content_contract_version": "2.3",
            "template": {"template_id": "lesson-plan", "template_version": "1.1.2", "template_sha256": "f" * 64, "manifest_sha256": "0" * 64},
            "runtime": {"python_version": "3.12.0", "python_docx_version": "1.1", "jsonschema_version": "4.0", "pyyaml_version": "6.0", "libreoffice_version": None, "render_performed": False},
            "created_at": "2026-09-29T10:00:00Z",
            "authorization_fingerprint": "",
        }
        base["authorization_fingerprint"] = production_authorization_fingerprint(base)
        errors = validate_production_authorization_payload(base)
        self.assertTrue(any("benchmark.disposition" in item for item in errors))

        complete = copy.deepcopy(base)
        complete["benchmark"] = _benchmark("BENCHMARK_REVIEW_COMPLETE")
        complete["benchmark"]["authorization_sha256"] = None
        complete["benchmark"]["review_sha256"] = None
        complete["authorization_fingerprint"] = production_authorization_fingerprint(complete)
        errors = validate_production_authorization_payload(complete)
        self.assertTrue(any("authorization_sha256" in item for item in errors))

        missing_review_hash = copy.deepcopy(base)
        missing_review_hash["benchmark"] = _benchmark("BENCHMARK_UNAVAILABLE", "a" * 64)
        missing_review_hash.pop("teacher_review_sha256")
        missing_review_hash["authorization_fingerprint"] = production_authorization_fingerprint(missing_review_hash)
        errors = validate_production_authorization_payload(missing_review_hash)
        self.assertTrue(any("teacher_review_sha256" in item for item in errors))

        missing_waiver_evidence = _teacher_review(b"{}", b"{}", _benchmark("BENCHMARK_WAIVED_BY_USER", None))
        self.assertTrue(validate_teacher_review_payload(missing_waiver_evidence, require_benchmark_bytes=False))

        unsupported_content = copy.deepcopy(base)
        unsupported_content["benchmark"] = _benchmark("BENCHMARK_UNAVAILABLE", "a" * 64)
        unsupported_content["content_contract_version"] = "3.0"
        unsupported_content["authorization_fingerprint"] = production_authorization_fingerprint(unsupported_content)
        errors = validate_production_authorization_payload(unsupported_content)
        self.assertTrue(any("content_contract_version" in item for item in errors))

        missing_skill_identity = copy.deepcopy(unsupported_content)
        missing_skill_identity["content_contract_version"] = "2.3"
        missing_skill_identity["lesson_skill"].pop("installed_skill_fingerprint")
        missing_skill_identity["authorization_fingerprint"] = production_authorization_fingerprint(missing_skill_identity)
        errors = validate_production_authorization_payload(missing_skill_identity)
        self.assertTrue(any("installed_skill_fingerprint" in item for item in errors))

        changed_time = copy.deepcopy(base)
        changed_time["created_at"] = "2026-09-30T10:00:00Z"
        self.assertEqual(
            production_authorization_fingerprint(changed_time),
            production_authorization_fingerprint(base),
        )

        waiver_digest = "a" * 64
        waiver = _benchmark("BENCHMARK_WAIVED_BY_USER", waiver_digest)
        self.assertIsNotNone(waiver["waiver_reference"])
        self.assertEqual(waiver["evidence_sha256"], waiver_digest)


class PipelineStateTests(unittest.TestCase):
    def test_legal_forward_flow_with_optional_benchmark_skipped(self) -> None:
        state = initial_pipeline_state("RUN-PIPE")
        state = advance_pipeline_state(state, "SOURCE_TRUTH_FROZEN", recorded_at="2026-09-29T10:00:00Z", artifact_sha256_updates={"source_truth_manifest_sha256": "a" * 64})
        state = advance_pipeline_state(state, "AUTHORING_COMPLETE", recorded_at="2026-09-29T10:01:00Z", artifact_sha256_updates={"content_sha256": "b" * 64})
        state = advance_pipeline_state(state, "PREPRODUCTION_QA_PASSED", recorded_at="2026-09-29T10:02:00Z", artifact_sha256_updates={"preproduction_qa_sha256": "c" * 64})
        state = advance_pipeline_state(state, "READY_FOR_TEACHER_REVIEW", recorded_at="2026-09-29T10:03:00Z")
        state = advance_pipeline_state(state, "TEACHER_REVIEW_APPROVED", recorded_at="2026-09-29T10:04:00Z", artifact_sha256_updates={"teacher_review_sha256": "d" * 64})
        state = advance_pipeline_state(state, "PRODUCTION_AUTHORIZED", recorded_at="2026-09-29T10:05:00Z", artifact_sha256_updates={"production_authorization_sha256": "e" * 64})
        state = advance_pipeline_state(state, "PRODUCTION_GENERATED", recorded_at="2026-09-29T10:06:00Z", artifact_sha256_updates={"artifact_manifest_sha256": "f" * 64})
        state = advance_pipeline_state(state, "ARTIFACT_QA_PASSED", recorded_at="2026-09-29T10:07:00Z", artifact_sha256_updates={"artifact_qa_sha256": "1" * 64})
        state = advance_pipeline_state(state, "VISUAL_REVIEW_APPROVED", recorded_at="2026-09-29T10:08:00Z", artifact_sha256_updates={"visual_review_sha256": "2" * 64})
        state = advance_pipeline_state(state, "ACCEPTED", recorded_at="2026-09-29T10:09:00Z", artifact_sha256_updates={"acceptance_sha256": "3" * 64})
        self.assertEqual(state["current_state"], "ACCEPTED")
        self.assertEqual(validate_pipeline_state_payload(state), [])

    def test_skip_core_backwards_same_unknown_and_state_tamper_fail(self) -> None:
        state = initial_pipeline_state("RUN-PIPE")
        with self.assertRaises(LifecycleContractError):
            advance_pipeline_state(state, "AUTHORING_COMPLETE", recorded_at="2026-09-29T10:00:00Z")
        with self.assertRaises(LifecycleContractError):
            advance_pipeline_state(state, "INTAKE_CONFIRMED", recorded_at="2026-09-29T10:00:00Z")
        with self.assertRaises(LifecycleContractError):
            advance_pipeline_state(state, "NOT_A_STATE", recorded_at="2026-09-29T10:00:00Z")
        same_state = copy.deepcopy(state)
        same_state["transitions"] = [
            {"from_state": "INTAKE_CONFIRMED", "to_state": "INTAKE_CONFIRMED", "recorded_at": "2026-09-29T10:00:00Z"}
        ]
        same_state["state_fingerprint"] = pipeline_state_fingerprint(same_state)
        errors = validate_pipeline_state_payload(same_state)
        self.assertTrue(any("same-state transition" in item for item in errors))

        progressed = advance_pipeline_state(state, "SOURCE_TRUTH_FROZEN", recorded_at="2026-09-29T10:00:00Z", artifact_sha256_updates={"source_truth_manifest_sha256": "a" * 64})
        tampered = copy.deepcopy(progressed)
        tampered["transitions"][0]["to_state"] = "AUTHORING_COMPLETE"
        tampered["state_fingerprint"] = pipeline_state_fingerprint(tampered)
        errors = validate_pipeline_state_payload(tampered)
        self.assertTrue(any("not a legal forward transition" in item for item in errors))

    def test_artifact_byte_mismatch_and_dependency_invalidation(self) -> None:
        state = initial_pipeline_state("RUN-PIPE")
        state = advance_pipeline_state(state, "SOURCE_TRUTH_FROZEN", recorded_at="2026-09-29T10:00:00Z", artifact_sha256_updates={"source_truth_manifest_sha256": "a" * 64})
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "source.json"
            artifact.write_text("{}", encoding="utf-8")
            errors = validate_pipeline_artifact_bytes(state, {"source_truth_manifest_sha256": artifact})
            self.assertTrue(any("does not match" in item for item in errors))
        stale = stale_downstream("content")
        self.assertTrue({"benchmark_review", "teacher_review", "production_authorization", "final_artifacts", "visual_review", "acceptance"}.issubset(stale))
        stale = stale_downstream("source_truth")
        self.assertTrue({"content", "benchmark_preparation", "teacher_review", "production_authorization", "acceptance"}.issubset(stale))

    def test_approved_state_requires_current_review_and_authorized_state_requires_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            _source, source_path = _source_truth(directory / "run")
            source_raw = source_path.read_bytes()
            content_path = directory / "run" / "lesson-content.json"
            content_raw = _write_json(content_path, _content())
            review = _teacher_review(source_raw, content_raw)
            review_path = directory / "run" / "teacher-review.json"
            review_raw = _write_json(review_path, review)
            state = initial_pipeline_state("RUN-001")
            state = advance_pipeline_state(
                state,
                "SOURCE_TRUTH_FROZEN",
                recorded_at="2026-09-29T10:00:00Z",
                artifact_sha256_updates={"source_truth_manifest_sha256": sha256_bytes(source_raw)},
            )
            state = advance_pipeline_state(
                state,
                "AUTHORING_COMPLETE",
                recorded_at="2026-09-29T10:01:00Z",
                artifact_sha256_updates={"content_sha256": sha256_bytes(content_raw)},
            )
            state = advance_pipeline_state(
                state,
                "PREPRODUCTION_QA_PASSED",
                recorded_at="2026-09-29T10:02:00Z",
                artifact_sha256_updates={"preproduction_qa_sha256": "a" * 64},
            )
            state = advance_pipeline_state(state, "READY_FOR_TEACHER_REVIEW", recorded_at="2026-09-29T10:03:00Z")
            state = advance_pipeline_state(
                state,
                "TEACHER_REVIEW_APPROVED",
                recorded_at="2026-09-29T10:04:00Z",
                artifact_sha256_updates={"teacher_review_sha256": sha256_bytes(review_raw)},
            )
            state_path = directory / "run" / "pipeline-state.json"
            _write_json(state_path, state)
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(
                state_path,
                source_truth_path=source_path,
                content_path=content_path,
                teacher_review_path=review_path,
            )
            self.assertEqual(errors, [])

            content_path.write_bytes(content_raw + b" ")
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(
                state_path,
                source_truth_path=source_path,
                content_path=content_path,
                teacher_review_path=review_path,
            )
            self.assertTrue(any("content_sha256" in item for item in errors))

            authorized_claim = advance_pipeline_state(
                state,
                "PRODUCTION_AUTHORIZED",
                recorded_at="2026-09-29T10:05:00Z",
                artifact_sha256_updates={"production_authorization_sha256": "b" * 64},
            )
            _write_json(state_path, authorized_claim)
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(
                state_path,
                source_truth_path=source_path,
                content_path=content_path,
                teacher_review_path=review_path,
            )
            self.assertTrue(any("requires Source Truth, Content, Teacher Review and Authorization files" in item for item in errors))

    def test_production_authorized_state_binds_valid_authorization_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source, content, review, evidence, authorization_path, _authorization = ProductionAuthorizationTests()._valid_files(directory)
            source_raw = source.read_bytes()
            content_raw = content.read_bytes()
            review_raw = review.read_bytes()
            authorization_raw = authorization_path.read_bytes()
            state = initial_pipeline_state("RUN-001")
            state = advance_pipeline_state(
                state,
                "SOURCE_TRUTH_FROZEN",
                recorded_at="2026-09-29T10:00:00Z",
                artifact_sha256_updates={"source_truth_manifest_sha256": sha256_bytes(source_raw)},
            )
            state = advance_pipeline_state(
                state,
                "AUTHORING_COMPLETE",
                recorded_at="2026-09-29T10:01:00Z",
                artifact_sha256_updates={"content_sha256": sha256_bytes(content_raw)},
            )
            state = advance_pipeline_state(
                state,
                "PREPRODUCTION_QA_PASSED",
                recorded_at="2026-09-29T10:02:00Z",
                artifact_sha256_updates={"preproduction_qa_sha256": "a" * 64},
            )
            state = advance_pipeline_state(state, "READY_FOR_TEACHER_REVIEW", recorded_at="2026-09-29T10:03:00Z")
            state = advance_pipeline_state(
                state,
                "TEACHER_REVIEW_APPROVED",
                recorded_at="2026-09-29T10:04:00Z",
                artifact_sha256_updates={"teacher_review_sha256": sha256_bytes(review_raw)},
            )
            state = advance_pipeline_state(
                state,
                "PRODUCTION_AUTHORIZED",
                recorded_at="2026-09-29T10:05:00Z",
                artifact_sha256_updates={"production_authorization_sha256": sha256_bytes(authorization_raw)},
            )
            state_path = directory / "run" / "pipeline-state.json"
            _write_json(state_path, state)
            args = {
                "source_truth_path": source,
                "content_path": content,
                "teacher_review_path": review,
                "production_authorization_path": authorization_path,
                "benchmark_evidence_path": evidence,
                "skill_root": LESSON,
            }
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
            self.assertEqual(errors, [])

            authorization_path.write_bytes(authorization_raw + b" ")
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
            self.assertTrue(any("production_authorization_sha256 does not match" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
