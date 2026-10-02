from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from tests.test_lesson_content_v22 import DB_SPECS, make_v22_payload
from tests.test_lesson_content_v23 import _bind_v23

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
    validation_status,
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
from source_truth import (  # noqa: E402
    source_truth_content_verified,
    source_truth_fingerprint,
    validate_source_truth_payload,
)
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
    outline_raw = _write_json(evidence / "outline.json", _content()["outline"])
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


def _content(contract_version: str = "2.3") -> dict[str, Any]:
    payload = make_v22_payload(
        course="数据库应用基础",
        major="软件技术",
        audience="高职二年级",
        theory_hours=2,
        lesson_count=1,
        specs=DB_SPECS[:1],
    )
    if contract_version == "2.3":
        payload = _bind_v23(payload, mode="theory_only", theory_hours=2, practice_hours=0)
    elif contract_version != "2.2":
        raise ValueError(f"unsupported test Content version: {contract_version}")
    provenance = payload["authoring_provenance"]
    provenance["mode"] = "agent"
    provenance["authoring_id"] = "lifecycle-contract-fixture-agent"
    from package_common import DEFAULT_SCHEMA, validate_content_v2_input

    validate_content_v2_input(payload, DEFAULT_SCHEMA)
    return payload


def _benchmark(
    disposition: str,
    evidence_sha: str | None = None,
    *,
    authorization_sha: str | None = None,
    review_sha: str | None = None,
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "authorization_sha256": authorization_sha,
        "review_sha256": review_sha,
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
    content = json.loads(content_raw.decode("utf-8"))
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
        "content_contract_version": content["content_contract_version"],
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


def _complete_benchmark_files(
    directory: Path,
    content: Mapping[str, Any],
    content_raw: bytes,
    *,
    status: str = "BENCHMARK_REVIEW_COMPLETE",
    decision: str = "NO_REVISION_REQUIRED",
    context_mode: str = "separate_contexts",
) -> tuple[Path, Path, dict[str, Any]]:
    import benchmark_authorization

    if decision == "REVISION_REQUIRED" and status == "BENCHMARK_REVIEW_COMPLETE":
        status = "BENCHMARK_GAPS_FOUND"
    directory.mkdir(parents=True, exist_ok=True)
    context_flags = (
        {"authoring_exemplars_visible": False, "author_reasoning_visible": False, "holdout_only": True}
        if context_mode == "separate_contexts"
        else {"authoring_exemplars_visible": True, "author_reasoning_visible": True, "holdout_only": False}
    )
    final_digest = content["authoring_provenance"]["final_content_sha256"]
    review: dict[str, Any] = {
        "benchmark_contract_version": "1.0",
        "benchmark_run_id": "BENCH-RUN-001",
        "catalog_id": "CATALOG-001",
        "catalog_fingerprint": "a" * 64,
        "split_id": "SPLIT-001",
        "split_fingerprint": "b" * 64,
        "holdout_pack_fingerprint": "c" * 64,
        "benchmark_availability": "AVAILABLE",
        "source_lesson_content_sha256": sha256_bytes(content_raw),
        "holdout_selection_sha256": "d" * 64,
        "rubric_version": "lesson-teaching-benchmark-v1",
        "review_round": 1,
        "status": status,
        "isolation": {"context_mode": context_mode, **context_flags},
        "lesson_review_count": 1,
        "lesson_reviews": [{"lesson_id": "L01", "review_sha256": "e" * 64}],
        "course_summary": {
            "major_gap_count": 0,
            "minor_gap_count": 0,
            "insufficient_evidence_count": 0,
            "lessons_reviewed": 1,
            "lessons_without_holdout": 0,
            "no_relevant_holdout_lesson_count": 0,
            "context_mode": context_mode,
            "authoring_availability": "AVAILABLE",
            "holdout_availability": "AVAILABLE",
            "decision": decision,
            "status": status,
        },
    }
    review_path = directory / "benchmark-review.json"
    review_raw = _write_json(review_path, review)
    authorization: dict[str, Any] = {
        "benchmark_authorization_version": "1.0",
        "skill_version": "2.3.1",
        "content_contract_version": content["content_contract_version"],
        "benchmark_run_id": "BENCH-RUN-001",
        "review_round": 1,
        "benchmark_status": status,
        "benchmark_decision": decision,
        "catalog_fingerprint": "a" * 64,
        "split_fingerprint": "b" * 64,
        "authoring_pack_fingerprint": "f" * 64,
        "authoring_selection_sha256": "1" * 64,
        "holdout_pack_fingerprint": "c" * 64,
        "holdout_selection_sha256": "d" * 64,
        "benchmark_review_sha256": sha256_bytes(review_raw),
        "source_lesson_content_sha256": sha256_bytes(content_raw),
        "source_final_content_sha256": final_digest,
        "context_mode": context_mode,
        "created_at": "2026-09-29T10:06:00Z",
        "authorization_fingerprint": "",
    }
    authorization["authorization_fingerprint"] = benchmark_authorization.authorization_fingerprint(authorization)
    authorization_path = directory / "benchmark-authorization.json"
    authorization_raw = _write_json(authorization_path, authorization)
    lifecycle_block = _benchmark(
        "BENCHMARK_REVIEW_COMPLETE",
        authorization_sha=sha256_bytes(authorization_raw),
        review_sha=sha256_bytes(review_raw),
    )
    return authorization_path, review_path, lifecycle_block


def _rebind_completed_outer_files(
    teacher_review_path: Path,
    production_authorization_path: Path,
    benchmark_authorization_path: Path,
    benchmark_review_path: Path,
) -> None:
    """Refresh byte references while leaving Benchmark sidecar semantics untouched."""
    benchmark = _benchmark(
        "BENCHMARK_REVIEW_COMPLETE",
        authorization_sha=sha256_file(benchmark_authorization_path),
        review_sha=sha256_file(benchmark_review_path),
    )
    teacher_review = json.loads(teacher_review_path.read_text(encoding="utf-8"))
    teacher_review["benchmark"] = benchmark
    teacher_review["review_fingerprint"] = teacher_review_fingerprint(teacher_review)
    teacher_review_raw = _write_json(teacher_review_path, teacher_review)

    authorization = json.loads(production_authorization_path.read_text(encoding="utf-8"))
    authorization["benchmark"] = benchmark
    authorization["teacher_review_sha256"] = sha256_bytes(teacher_review_raw)
    authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
    _write_json(production_authorization_path, authorization)


def _temporary_skill_repo(directory: Path) -> tuple[Path, str]:
    repository = directory / "repository"
    skill = repository / "教案生成器" / "lesson-plan-docx-generator"
    shutil.copytree(LESSON, skill, ignore=shutil.ignore_patterns("__pycache__"))
    for command in (
        ["init"],
        ["config", "user.name", "Lifecycle Test"],
        ["config", "user.email", "lifecycle@example.invalid"],
        ["config", "core.autocrlf", "false"],
        ["add", "--all"],
        ["commit", "-m", "Test Skill tree"],
    ):
        subprocess.run(["git", "-C", str(repository), *command], check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return skill, commit


def _rebind_source_locator(source: Path, review: Path, authorization_path: Path, locator: str) -> None:
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    source_payload["sources"][0]["locator"] = locator
    source_payload["manifest_fingerprint"] = source_truth_fingerprint(source_payload)
    source_raw = _write_json(source, source_payload)
    review_payload = json.loads(review.read_text(encoding="utf-8"))
    review_payload["source_truth_manifest_sha256"] = sha256_bytes(source_raw)
    review_payload["review_fingerprint"] = teacher_review_fingerprint(review_payload)
    review_raw = _write_json(review, review_payload)
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["source_truth_manifest_sha256"] = sha256_bytes(source_raw)
    authorization["teacher_review_sha256"] = sha256_bytes(review_raw)
    authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
    _write_json(authorization_path, authorization)


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
            self.assertTrue(source_truth_content_verified(payload, verify_source_bytes=True))
            self.assertFalse(source_truth_content_verified(payload, verify_source_bytes=False))
            remote = copy.deepcopy(payload)
            remote["sources"][0]["locator"] = "https://example.org/profile.json"
            remote["manifest_fingerprint"] = source_truth_fingerprint(remote)
            self.assertEqual(validate_source_truth_payload(remote, manifest_path=manifest_path), [])
            self.assertFalse(source_truth_content_verified(remote, verify_source_bytes=True))
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
            # Historical Source Truth 1.0 artifacts remain auditable. Current
            # canonical production requires the outline through the shared scope gate.
            self.assertEqual(validate_source_truth_payload(missing, manifest_path=manifest_path), [])

            missing_profile = copy.deepcopy(payload)
            missing_profile["sources"] = [missing_profile["sources"][1]]
            missing_profile["manifest_fingerprint"] = source_truth_fingerprint(missing_profile)
            errors = validate_source_truth_payload(missing_profile, manifest_path=manifest_path)
            self.assertTrue(any("confirmed_course_profile" in item for item in errors))

            (Path(temp) / "evidence" / "profile.json").write_text("changed", encoding="utf-8")
            errors = validate_source_truth_payload(payload, manifest_path=manifest_path)
            self.assertTrue(any("does not match local source bytes" in item for item in errors))
            (Path(temp) / "evidence" / "profile.json").unlink()
            self.assertEqual(
                validate_source_truth_payload(payload, manifest_path=manifest_path, verify_source_bytes=False),
                [],
            )
            byte_errors = validate_source_truth_payload(payload, manifest_path=manifest_path, verify_source_bytes=True)
            self.assertTrue(byte_errors)
            self.assertEqual(validation_status([], byte_errors), "STALE")

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
            self.assertEqual(
                validation_status(validate_teacher_review_payload(review, require_benchmark_bytes=False), errors),
                "STALE",
            )

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

    def test_completed_benchmark_decision_gates_teacher_approval_authority(self) -> None:
        def create_files(
            directory: Path,
            *,
            benchmark_decision: str,
            teacher_decision: str = "APPROVED",
        ) -> tuple[Path, Path, Path, Path, Path]:
            builder = ProductionAuthorizationTests()
            source, content_path, teacher_path, _evidence, _production_auth, _authorization = builder._valid_files(
                directory,
                benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
                benchmark_decision=benchmark_decision,
            )
            benchmark_auth, benchmark_review = builder._last_benchmark_paths
            review = json.loads(teacher_path.read_text(encoding="utf-8"))
            review["decision"] = teacher_decision
            review["review_fingerprint"] = teacher_review_fingerprint(review)
            _write_json(teacher_path, review)
            return source, content_path, teacher_path, benchmark_auth, benchmark_review

        with tempfile.TemporaryDirectory() as temp:
            files = create_files(
                Path(temp), benchmark_decision="NO_REVISION_REQUIRED", teacher_decision="APPROVED",
            )
            source, content, teacher, benchmark_auth, benchmark_review = files
            _loaded, _raw, errors = validate_teacher_review_files(
                teacher,
                source_truth_path=source,
                content_path=content,
                benchmark_authorization_path=benchmark_auth,
                benchmark_review_path=benchmark_review,
                require_approved=True,
            )
            self.assertEqual(errors, [])

        for teacher_decision in ("APPROVED", "APPROVED_WITH_NOTES"):
            with self.subTest(teacher_decision=teacher_decision), tempfile.TemporaryDirectory() as temp:
                files = create_files(
                    Path(temp), benchmark_decision="REVISION_REQUIRED", teacher_decision=teacher_decision,
                )
                source, content, teacher, benchmark_auth, benchmark_review = files
                _loaded, _raw, errors = validate_teacher_review_files(
                    teacher,
                    source_truth_path=source,
                    content_path=content,
                    benchmark_authorization_path=benchmark_auth,
                    benchmark_review_path=benchmark_review,
                    require_approved=True,
                )
                self.assertTrue(any("requires revision before final production authorization" in item for item in errors), errors)

        # A revision decision remains a valid Teacher Review artifact; it only
        # fails when callers ask this validator to establish approval authority.
        with tempfile.TemporaryDirectory() as temp:
            source, content, teacher, benchmark_auth, benchmark_review = create_files(
                Path(temp), benchmark_decision="REVISION_REQUIRED", teacher_decision="REVISION_REQUIRED",
            )
            self.assertEqual(
                validate_teacher_review_files(
                    teacher,
                    source_truth_path=source,
                    content_path=content,
                    benchmark_authorization_path=benchmark_auth,
                    benchmark_review_path=benchmark_review,
                    require_approved=False,
                )[2],
                [],
            )
            review, _raw = read_json_object(teacher, "teacher_review")
            self.assertEqual(validate_teacher_review_payload(review, require_benchmark_bytes=False), [])

    def test_completed_benchmark_semantics_run_only_for_approval_authority(self) -> None:
        builder = ProductionAuthorizationTests()
        with tempfile.TemporaryDirectory() as temp:
            source, content, teacher, _evidence, _production_auth, _authorization = builder._valid_files(
                Path(temp), benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
            )
            benchmark_auth, benchmark_review = builder._last_benchmark_paths
            benchmark_auth.write_bytes(b'{"malformed":')
            review = json.loads(teacher.read_text(encoding="utf-8"))
            review["benchmark"]["authorization_sha256"] = sha256_file(benchmark_auth)
            review["review_fingerprint"] = teacher_review_fingerprint(review)
            _write_json(teacher, review)

            # Ordinary structural/byte validation does not turn every Teacher
            # Review CLI invocation into a Benchmark authority decision.
            _loaded, _raw, errors = validate_teacher_review_files(
                teacher,
                source_truth_path=source,
                content_path=content,
                benchmark_authorization_path=benchmark_auth,
                benchmark_review_path=benchmark_review,
                require_approved=False,
            )
            self.assertEqual(errors, [])

            _loaded, _raw, errors = validate_teacher_review_files(
                teacher,
                source_truth_path=source,
                content_path=content,
                benchmark_authorization_path=benchmark_auth,
                benchmark_review_path=benchmark_review,
                require_approved=True,
            )
            self.assertTrue(any("cannot load Benchmark Authorization/Review evidence" in item for item in errors), errors)

    def test_completed_benchmark_requires_current_content_final_semantic_digest(self) -> None:
        import benchmark_authorization
        from lifecycle_benchmark import validate_completed_benchmark_evidence

        builder = ProductionAuthorizationTests()
        with tempfile.TemporaryDirectory() as temp:
            source, content_path, teacher, _evidence, _production_auth, _authorization = builder._valid_files(
                Path(temp), benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
            )
            benchmark_auth_path, benchmark_review_path = builder._last_benchmark_paths

            content = json.loads(content_path.read_text(encoding="utf-8"))
            content["authoring_provenance"].pop("final_content_sha256")
            content_raw = _write_json(content_path, content)

            review = json.loads(benchmark_review_path.read_text(encoding="utf-8"))
            review["source_lesson_content_sha256"] = sha256_bytes(content_raw)
            review_raw = _write_json(benchmark_review_path, review)

            authorization = json.loads(benchmark_auth_path.read_text(encoding="utf-8"))
            authorization["source_lesson_content_sha256"] = sha256_bytes(content_raw)
            authorization["benchmark_review_sha256"] = sha256_bytes(review_raw)
            authorization["authorization_fingerprint"] = benchmark_authorization.authorization_fingerprint(authorization)
            authorization_raw = _write_json(benchmark_auth_path, authorization)

            teacher_review = json.loads(teacher.read_text(encoding="utf-8"))
            benchmark = teacher_review["benchmark"]
            benchmark["authorization_sha256"] = sha256_bytes(authorization_raw)
            benchmark["review_sha256"] = sha256_bytes(review_raw)
            errors = validate_completed_benchmark_evidence(
                benchmark,
                benchmark_authorization_path=benchmark_auth_path,
                benchmark_review_path=benchmark_review_path,
                content=content,
                content_raw=content_raw,
            )
            self.assertTrue(any("authoring_provenance.final_content_sha256 is required" in item for item in errors), errors)

    def test_completed_benchmark_crosslink_failures_block_teacher_approval(self) -> None:
        import benchmark_authorization

        builder = ProductionAuthorizationTests()

        def bind_outer_review(teacher: Path, authorization: Path, review: Path) -> None:
            payload = json.loads(teacher.read_text(encoding="utf-8"))
            payload["benchmark"]["authorization_sha256"] = sha256_file(authorization)
            payload["benchmark"]["review_sha256"] = sha256_file(review)
            payload["review_fingerprint"] = teacher_review_fingerprint(payload)
            _write_json(teacher, payload)

        def invalidate_review_schema(authorization_path: Path, review_path: Path, _teacher: Path) -> None:
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            review_payload.pop("catalog_id")
            _write_json(review_path, review_payload)
            authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
            authorization["benchmark_review_sha256"] = sha256_file(review_path)
            authorization["authorization_fingerprint"] = benchmark_authorization.authorization_fingerprint(authorization)
            _write_json(authorization_path, authorization)

        def mutate_authorization_field(field: str, value: Any):
            def mutate(authorization_path: Path, _review_path: Path, _teacher: Path) -> None:
                authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
                authorization[field] = value
                authorization["authorization_fingerprint"] = benchmark_authorization.authorization_fingerprint(authorization)
                _write_json(authorization_path, authorization)

            return mutate

        def corrupt_lifecycle_sha(_authorization: Path, _review: Path, teacher: Path) -> None:
            payload = json.loads(teacher.read_text(encoding="utf-8"))
            payload["benchmark"]["authorization_sha256"] = "0" * 64
            payload["review_fingerprint"] = teacher_review_fingerprint(payload)
            _write_json(teacher, payload)

        cases = (
            ("Review schema", invalidate_review_schema, "Benchmark Review:"),
            ("run mismatch", mutate_authorization_field("benchmark_run_id", "BENCH-RUN-OTHER"), "benchmark_run_id do not match"),
            ("round mismatch", mutate_authorization_field("review_round", 2), "review_round do not match"),
            ("context mismatch", mutate_authorization_field("context_mode", "single_context"), "context_mode does not match"),
            ("Lifecycle SHA mismatch", corrupt_lifecycle_sha, "does not match benchmark authorization file bytes"),
        )

        for label, mutate, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                source, content, teacher, _evidence, _production_auth, _authorization = builder._valid_files(
                    Path(temp), benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
                )
                benchmark_auth, benchmark_review = builder._last_benchmark_paths
                mutate(benchmark_auth, benchmark_review, teacher)
                if label != "Lifecycle SHA mismatch":
                    bind_outer_review(teacher, benchmark_auth, benchmark_review)
                _loaded, _raw, errors = validate_teacher_review_files(
                    teacher,
                    source_truth_path=source,
                    content_path=content,
                    benchmark_authorization_path=benchmark_auth,
                    benchmark_review_path=benchmark_review,
                    require_approved=True,
                )
                self.assertTrue(any(expected in item for item in errors), errors)


class ProductionAuthorizationTests(unittest.TestCase):
    def _rebind_content(
        self,
        content_path: Path,
        review_path: Path,
        authorization_path: Path,
        content: dict[str, Any],
    ) -> None:
        content_raw = _write_json(content_path, content)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["content_sha256"] = sha256_bytes(content_raw)
        review["review_fingerprint"] = teacher_review_fingerprint(review)
        review_raw = _write_json(review_path, review)
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        authorization["content_sha256"] = sha256_bytes(content_raw)
        if content.get("content_contract_version") in {"2.2", "2.3"}:
            authorization["content_contract_version"] = content["content_contract_version"]
        authorization["teacher_review_sha256"] = sha256_bytes(review_raw)
        authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
        _write_json(authorization_path, authorization)

    def _valid_files(
        self,
        directory: Path,
        *,
        content_version: str = "2.3",
        benchmark_disposition: str = "BENCHMARK_UNAVAILABLE",
        benchmark_decision: str = "NO_REVISION_REQUIRED",
    ) -> tuple[Path, Path, Path, Path, Path, dict[str, Any]]:
        _source, source_path = _source_truth(directory / "run")
        source_raw = source_path.read_bytes()
        content = _content(content_version)
        content_path = directory / "run" / "lesson-content.json"
        content_raw = _write_json(content_path, content)
        evidence_path = directory / "run" / "benchmark-evidence.json"
        evidence_raw = _write_json(evidence_path, {"reason": "no verified benchmark fixture supplied"})
        if benchmark_disposition == "BENCHMARK_REVIEW_COMPLETE":
            benchmark_authorization_path, benchmark_review_path, benchmark = _complete_benchmark_files(
                directory / "run" / "benchmark", content, content_raw, decision=benchmark_decision,
            )
        else:
            benchmark = _benchmark(benchmark_disposition, sha256_bytes(evidence_raw))
            benchmark_authorization_path = None
            benchmark_review_path = None
        review = _teacher_review(source_raw, content_raw, benchmark)
        review_path = directory / "run" / "teacher-review.json"
        review_raw = _write_json(review_path, review)
        authorization = _production_authorization(source_raw, content_raw, review_raw, benchmark)
        authorization_path = directory / "run" / "production-authorization.json"
        _write_json(authorization_path, authorization)
        if benchmark_authorization_path is not None and benchmark_review_path is not None:
            # Kept beside the return values by convention for semantic PA calls.
            self._last_benchmark_paths = (benchmark_authorization_path, benchmark_review_path)
        else:
            self._last_benchmark_paths = (None, None)
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

    def test_production_authorization_uses_content_22_and_23_production_gate(self) -> None:
        for version in ("2.2", "2.3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                source, content, review, evidence, auth_path, _authorization = self._valid_files(
                    Path(temp), content_version=version,
                )
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

    def test_skeletal_invalid_and_unreviewed_content_cannot_authorize_with_fresh_sha(self) -> None:
        mutations = (
            ("skeletal contract-invalid", lambda _content: {"lessons": [{"lesson_id": "L01"}]}),
            (
                "2.3 missing production fields",
                lambda content: {**content, "delivery_plan": {key: value for key, value in content["delivery_plan"].items() if key != "practice_hours"}},
            ),
            (
                "provenance hard gate",
                lambda content: {**content, "authoring_provenance": {**content["authoring_provenance"], "mode": "synthetic_fixture"}},
            ),
            (
                "pedagogical review hard gate",
                lambda content: {**content, "lessons": [{key: value for key, value in content["lessons"][0].items() if key != "pedagogical_review"}]},
            ),
        )
        for label, mutate in mutations:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                source, content_path, review, evidence, auth_path, _authorization = self._valid_files(Path(temp))
                invalid = mutate(json.loads(content_path.read_text(encoding="utf-8")))
                self._rebind_content(content_path, review, auth_path, invalid)
                _loaded, _raw, errors = validate_production_authorization_files(
                    auth_path,
                    source_truth_path=source,
                    content_path=content_path,
                    teacher_review_path=review,
                    benchmark_evidence_path=evidence,
                    skill_root=LESSON,
                    verify_runtime_environment=False,
                )
                self.assertTrue(any("Lesson Content production validation failed" in error for error in errors))

    def test_completed_benchmark_requires_official_semantics_and_crosslinks(self) -> None:
        import benchmark_authorization

        def validate(directory: Path) -> list[str]:
            source, content, review, evidence, auth_path, _authorization = self._valid_files(
                directory,
                benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
            )
            benchmark_authorization_path, benchmark_review_path = self._last_benchmark_paths
            _loaded, _raw, errors = validate_production_authorization_files(
                auth_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=review,
                benchmark_authorization_path=benchmark_authorization_path,
                benchmark_review_path=benchmark_review_path,
                benchmark_evidence_path=evidence,
                skill_root=LESSON,
                verify_runtime_environment=False,
            )
            return errors

        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(validate(Path(temp)), [])

        def mutate_auth(path: Path, changes: dict[str, Any], *, fingerprint: bool = True) -> None:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.update(changes)
            if fingerprint:
                payload["authorization_fingerprint"] = benchmark_authorization.authorization_fingerprint(payload)
            _write_json(path, payload)

        cases = []
        cases.append((
            "arbitrary bytes",
            lambda auth_path, review_path: (auth_path.write_bytes(b"benchmark auth exact bytes"), review_path.write_bytes(b"benchmark review exact bytes")),
            "cannot load Benchmark Authorization/Review evidence",
        ))
        cases.append((
            "malformed JSON",
            lambda auth_path, _review_path: auth_path.write_bytes(b'{"broken":'),
            "cannot load Benchmark Authorization/Review evidence",
        ))
        cases.append((
            "malformed Review JSON",
            lambda _auth_path, review_path: review_path.write_bytes(b'{"broken":'),
            "cannot load Benchmark Authorization/Review evidence",
        ))
        cases.append((
            "authorization fingerprint",
            lambda auth_path, _review_path: mutate_auth(auth_path, {"authorization_fingerprint": "0" * 64}, fingerprint=False),
            "authorization_fingerprint does not match",
        ))

        def invalidate_review_schema(auth_path: Path, review_path: Path) -> None:
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            review_payload.pop("catalog_id")
            review_raw = _write_json(review_path, review_payload)
            mutate_auth(auth_path, {"benchmark_review_sha256": sha256_bytes(review_raw)})

        cases.append(("Review schema", invalidate_review_schema, "Benchmark Review:"))

        cases.append((
            "Authorization review SHA mismatch",
            lambda auth_path, _review_path: mutate_auth(auth_path, {"benchmark_review_sha256": "0" * 64}),
            "Benchmark Authorization benchmark_review_sha256 does not match",
        ))
        cases.append((
            "final Content semantic digest mismatch",
            lambda auth_path, _review_path: mutate_auth(auth_path, {"source_final_content_sha256": "0" * 64}),
            "source_final_content_sha256 does not match reviewed Lesson content",
        ))
        cases.extend((
            (
                "run mismatch",
                lambda auth_path, _review_path: mutate_auth(auth_path, {"benchmark_run_id": "BENCH-RUN-OTHER"}),
                "benchmark_run_id do not match",
            ),
            (
                "round mismatch",
                lambda auth_path, _review_path: mutate_auth(auth_path, {"review_round": 2}),
                "review_round do not match",
            ),
            (
                "context mismatch",
                lambda auth_path, _review_path: mutate_auth(auth_path, {"context_mode": "single_context"}),
                "context_mode does not match",
            ),
        ))

        def revision_required(auth_path: Path, review_path: Path) -> None:
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            review_payload["status"] = "BENCHMARK_GAPS_FOUND"
            review_payload["course_summary"]["status"] = "BENCHMARK_GAPS_FOUND"
            review_payload["course_summary"]["decision"] = "REVISION_REQUIRED"
            review_raw = _write_json(review_path, review_payload)
            mutate_auth(auth_path, {
                "benchmark_status": "BENCHMARK_GAPS_FOUND",
                "benchmark_decision": "REVISION_REQUIRED",
                "benchmark_review_sha256": sha256_bytes(review_raw),
            })

        cases.append(("REVISION_REQUIRED", revision_required, "requires revision before final production authorization"))

        for label, mutation, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                source, content, review, evidence, auth_path, _authorization = self._valid_files(
                    directory,
                    benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
                )
                benchmark_authorization_path, benchmark_review_path = self._last_benchmark_paths
                mutation(benchmark_authorization_path, benchmark_review_path)
                _rebind_completed_outer_files(review, auth_path, benchmark_authorization_path, benchmark_review_path)
                _loaded, _raw, errors = validate_production_authorization_files(
                    auth_path,
                    source_truth_path=source,
                    content_path=content,
                    teacher_review_path=review,
                    benchmark_authorization_path=benchmark_authorization_path,
                    benchmark_review_path=benchmark_review_path,
                    benchmark_evidence_path=evidence,
                    skill_root=LESSON,
                    verify_runtime_environment=False,
                )
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_repo_commit_provenance_matches_canonical_head_and_allows_installed_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            skill, head = _temporary_skill_repo(directory)
            self.assertEqual(_current_repo_commit(skill), head)
            unrelated = skill.parents[1] / "unrelated.txt"
            unrelated.write_text("outside Skill", encoding="utf-8")
            self.assertEqual(_current_repo_commit(skill), head)

            source, content, review, evidence, auth_path, authorization = self._valid_files(directory)
            authorization["lesson_skill"]["installed_skill_fingerprint"] = skill_tree_fingerprint(skill)
            authorization["lesson_skill"]["source_repo_commit"] = head
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            args = {
                "source_truth_path": source,
                "content_path": content,
                "teacher_review_path": review,
                "benchmark_evidence_path": evidence,
                "skill_root": skill,
                "verify_runtime_environment": False,
            }
            self.assertEqual(validate_production_authorization_files(auth_path, **args)[2], [])

            tracked = skill / "SKILL.md"
            tracked_bytes = tracked.read_bytes()
            tracked.write_bytes(tracked_bytes + b"\nmodified after HEAD\n")
            self.assertIsNone(_current_repo_commit(skill))
            authorization["lesson_skill"]["installed_skill_fingerprint"] = skill_tree_fingerprint(skill)
            authorization["lesson_skill"]["source_repo_commit"] = head
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            errors = validate_production_authorization_files(auth_path, **args)[2]
            self.assertTrue(any("source_repo_commit must be null" in error for error in errors), errors)

            authorization["lesson_skill"]["source_repo_commit"] = None
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            self.assertEqual(validate_production_authorization_files(auth_path, **args)[2], [])

            tracked.write_bytes(tracked_bytes)
            self.assertEqual(_current_repo_commit(skill), head)
            authorization["lesson_skill"]["installed_skill_fingerprint"] = skill_tree_fingerprint(skill)
            authorization["lesson_skill"]["source_repo_commit"] = None
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            errors = validate_production_authorization_files(auth_path, **args)[2]
            self.assertTrue(any("source_repo_commit must match" in error for error in errors), errors)
            authorization["lesson_skill"]["source_repo_commit"] = "0" * 40
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            errors = validate_production_authorization_files(auth_path, **args)[2]
            self.assertTrue(any("source_repo_commit must match" in error for error in errors), errors)
            authorization["lesson_skill"]["source_repo_commit"] = head
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            self.assertEqual(validate_production_authorization_files(auth_path, **args)[2], [])

            installed = directory / "installed-skill"
            shutil.copytree(skill, installed, ignore=shutil.ignore_patterns("__pycache__", ".git"))
            self.assertIsNone(_current_repo_commit(installed))
            authorization["lesson_skill"]["installed_skill_fingerprint"] = skill_tree_fingerprint(installed)
            authorization["lesson_skill"]["source_repo_commit"] = None
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            installed_args = {**args, "skill_root": installed}
            self.assertEqual(validate_production_authorization_files(auth_path, **installed_args)[2], [])

            authorization["lesson_skill"]["source_repo_commit"] = head
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            self.assertEqual(validate_production_authorization_files(auth_path, **installed_args)[2], [])

            authorization["lesson_skill"]["source_repo_commit"] = "not-a-commit"
            authorization["authorization_fingerprint"] = production_authorization_fingerprint(authorization)
            _write_json(auth_path, authorization)
            errors = validate_production_authorization_files(auth_path, **installed_args)[2]
            self.assertTrue(any("source_repo_commit" in error for error in errors))
            self.assertEqual(_current_repo_commit(skill), head)

    def test_current_repo_commit_tracks_skill_inventory_and_cache_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill, head = _temporary_skill_repo(Path(temp))
            repo = skill.parents[1]
            self.assertEqual(_current_repo_commit(skill), head)

            tracked = skill / "SKILL.md"
            original = tracked.read_bytes()
            tracked.write_bytes(original + b"\nlocal edit\n")
            self.assertIsNone(_current_repo_commit(skill))
            tracked.write_bytes(original)
            self.assertEqual(_current_repo_commit(skill), head)

            deleted = skill / "AGENTS.md"
            deleted_bytes = deleted.read_bytes()
            deleted.unlink()
            self.assertIsNone(_current_repo_commit(skill))
            deleted.write_bytes(deleted_bytes)
            self.assertEqual(_current_repo_commit(skill), head)

            untracked = skill / "lifecycle-untracked-probe.txt"
            untracked.write_text("untracked ordinary file", encoding="utf-8")
            self.assertIsNone(_current_repo_commit(skill))
            untracked.unlink()

            ignored_name = "lifecycle-ignored-probe.txt"
            exclude_file = repo / ".git" / "info" / "exclude"
            previous_excludes = exclude_file.read_text(encoding="utf-8")
            exclude_file.write_text(previous_excludes + f"\n{ignored_name}\n", encoding="utf-8")
            ignored = skill / ignored_name
            ignored.write_text("ignored ordinary file", encoding="utf-8")
            ignored_status = subprocess.run(
                ["git", "-C", str(repo), "check-ignore", "--quiet", str(ignored)],
                check=False,
            )
            self.assertEqual(ignored_status.returncode, 0)
            self.assertIsNone(_current_repo_commit(skill))
            ignored.unlink()
            exclude_file.write_text(previous_excludes, encoding="utf-8")

            cache_file = skill / "scripts" / "__pycache__" / "generated-cache.pyc"
            cache_file.parent.mkdir(exist_ok=True)
            cache_file.write_bytes(b"cache-only change")
            self.assertEqual(_current_repo_commit(skill), head)

    def test_unverified_https_source_cannot_authorize_until_materialized_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source, content, review, evidence, auth_path, _authorization = self._valid_files(Path(temp))
            args = {
                "source_truth_path": source,
                "content_path": content,
                "teacher_review_path": review,
                "benchmark_evidence_path": evidence,
                "skill_root": LESSON,
                "verify_runtime_environment": False,
            }
            self.assertEqual(validate_production_authorization_files(auth_path, **args)[2], [])
            _rebind_source_locator(source, review, auth_path, "https://example.org/profile.json")
            source_payload = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(validate_source_truth_payload(source_payload, manifest_path=source, verify_source_bytes=True), [])
            self.assertFalse(source_truth_content_verified(source_payload, verify_source_bytes=True))
            with patch("socket.create_connection", side_effect=AssertionError("network fetch attempted")) as connect:
                errors = validate_production_authorization_files(auth_path, **args)[2]
                connect.assert_not_called()
            self.assertTrue(any("source bytes are unverified" in error for error in errors))
            self.assertEqual(validation_status(validate_production_authorization_payload(json.loads(auth_path.read_text(encoding="utf-8"))), errors), "STALE")

            _rebind_source_locator(source, review, auth_path, "evidence/profile.json")
            self.assertEqual(validate_production_authorization_files(auth_path, **args)[2], [])

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
            authorization["lesson_skill"]["source_repo_commit"] = "0" * 40
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
    def test_https_source_keeps_pipeline_authority_stale_without_network_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source, content, review, evidence, auth_path, _authorization = ProductionAuthorizationTests()._valid_files(Path(temp))
            _rebind_source_locator(source, review, auth_path, "https://example.org/profile.json")
            preproduction_qa = source.parent / "preproduction-qa.json"
            _write_json(preproduction_qa, {"result": "passed"})
            foundation = advance_pipeline_state(
                initial_pipeline_state("RUN-001"),
                "SOURCE_TRUTH_FROZEN",
                recorded_at="2026-09-29T10:00:00Z",
                artifact_sha256_updates={"source_truth_manifest_sha256": sha256_file(source)},
            )
            foundation_path = source.parent / "foundation-state.json"
            _write_json(foundation_path, foundation)
            self.assertEqual(
                pipeline_state_module.validate_pipeline_state_files(
                    foundation_path,
                    source_truth_path=source,
                )[2],
                [],
            )
            state = initial_pipeline_state("RUN-001")
            for next_state, artifact_updates in (
                ("SOURCE_TRUTH_FROZEN", {"source_truth_manifest_sha256": sha256_file(source)}),
                ("AUTHORING_COMPLETE", {"content_sha256": sha256_file(content)}),
                ("PREPRODUCTION_QA_PASSED", {"preproduction_qa_sha256": sha256_file(preproduction_qa)}),
                ("READY_FOR_TEACHER_REVIEW", {}),
                ("TEACHER_REVIEW_APPROVED", {"teacher_review_sha256": sha256_file(review)}),
                ("PRODUCTION_AUTHORIZED", {"production_authorization_sha256": sha256_file(auth_path)}),
            ):
                state = advance_pipeline_state(
                    state, next_state, recorded_at="2026-09-29T10:00:00Z",
                    artifact_sha256_updates=artifact_updates,
                )
            state_path = source.parent / "pipeline-state.json"
            _write_json(state_path, state)
            args = {
                "source_truth_path": source,
                "content_path": content,
                "teacher_review_path": review,
                "production_authorization_path": auth_path,
                "benchmark_evidence_path": evidence,
                "artifact_paths": {"preproduction_qa_sha256": preproduction_qa},
                "skill_root": LESSON,
            }
            with patch("socket.create_connection", side_effect=AssertionError("network fetch attempted")) as connect:
                _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
                connect.assert_not_called()
            self.assertTrue(any("Pipeline authority requires offline byte verification" in error for error in errors))
            self.assertTrue(any("Production Authorization requires offline byte verification" in error for error in errors))
            self.assertEqual(validation_status(validate_pipeline_state_payload(state), errors), "STALE")

            _rebind_source_locator(source, review, auth_path, "evidence/profile.json")
            state["artifacts"]["source_truth_manifest_sha256"] = sha256_file(source)
            state["artifacts"]["teacher_review_sha256"] = sha256_file(review)
            state["artifacts"]["production_authorization_sha256"] = sha256_file(auth_path)
            state["transitions"][0]["evidence_sha256"] = sha256_file(source)
            state["transitions"][4]["evidence_sha256"] = sha256_file(review)
            state["transitions"][5]["evidence_sha256"] = sha256_file(auth_path)
            state["state_fingerprint"] = pipeline_state_fingerprint(state)
            _write_json(state_path, state)
            self.assertEqual(pipeline_state_module.validate_pipeline_state_files(state_path, **args)[2], [])

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
        self.assertEqual(len(state["transitions"]), 10)
        self.assertEqual(state["transitions"][0]["evidence_sha256"], "a" * 64)
        self.assertEqual(state["transitions"][-1]["evidence_sha256"], "3" * 64)
        self.assertEqual(validate_pipeline_state_payload(state), [])

    def test_transition_requires_evidence_hash_and_statuses_distinguish_stale(self) -> None:
        state = initial_pipeline_state("RUN-PIPE")
        with self.assertRaisesRegex(LifecycleContractError, "requires artifacts.source_truth_manifest_sha256"):
            advance_pipeline_state(state, "SOURCE_TRUTH_FROZEN", recorded_at="2026-09-29T10:00:00Z")
        progressed = advance_pipeline_state(
            state, "SOURCE_TRUTH_FROZEN", recorded_at="2026-09-29T10:00:00Z",
            artifact_sha256_updates={"source_truth_manifest_sha256": "a" * 64},
        )
        missing_proof = copy.deepcopy(progressed)
        del missing_proof["transitions"][0]["evidence_sha256"]
        missing_proof["state_fingerprint"] = pipeline_state_fingerprint(missing_proof)
        self.assertTrue(validate_pipeline_state_payload(missing_proof))
        changed_proof = copy.deepcopy(progressed)
        changed_proof["transitions"][0]["evidence_sha256"] = "b" * 64
        changed_proof["state_fingerprint"] = pipeline_state_fingerprint(changed_proof)
        self.assertTrue(any("does not match artifacts" in error for error in validate_pipeline_state_payload(changed_proof)))
        self.assertEqual(validation_status([], []), "VALID")
        self.assertEqual(validation_status([], ["old Content SHA"]), "STALE")
        self.assertEqual(validation_status(["bad fingerprint"], []), "INVALID")
        self.assertEqual(validation_status(["bad fingerprint"], ["old Content SHA"]), "INVALID")

    def test_benchmark_prep_transition_has_own_evidence_and_keeps_index_bound(self) -> None:
        state = initial_pipeline_state("RUN-PIPE")
        state = advance_pipeline_state(
            state,
            "SOURCE_TRUTH_FROZEN",
            recorded_at="2026-09-29T10:00:00Z",
            artifact_sha256_updates={"source_truth_manifest_sha256": "a" * 64},
        )
        with self.assertRaisesRegex(LifecycleContractError, "requires artifacts.benchmark_preparation_sha256"):
            advance_pipeline_state(state, "BENCHMARK_PREPARED", recorded_at="2026-09-29T10:01:00Z")
        state = advance_pipeline_state(
            state,
            "BENCHMARK_PREPARED",
            recorded_at="2026-09-29T10:01:00Z",
            artifact_sha256_updates={"benchmark_preparation_sha256": "b" * 64},
        )
        state = advance_pipeline_state(
            state,
            "AUTHORING_COMPLETE",
            recorded_at="2026-09-29T10:02:00Z",
            artifact_sha256_updates={"content_sha256": "c" * 64},
        )
        damaged_index = copy.deepcopy(state)
        damaged_index["artifacts"]["benchmark_preparation_sha256"] = None
        damaged_index["state_fingerprint"] = pipeline_state_fingerprint(damaged_index)
        self.assertTrue(
            any(
                "requires indexed artifacts.benchmark_preparation_sha256" in error
                for error in validate_pipeline_state_payload(damaged_index)
            )
        )

    def test_pipeline_file_authority_requires_current_and_historical_artifacts(self) -> None:
        evidence_cases = (
            ("SOURCE_TRUTH_FROZEN", ("SOURCE_TRUTH_FROZEN",), "source_truth_manifest_sha256"),
            (
                "PREPRODUCTION_QA_PASSED",
                ("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED"),
                "preproduction_qa_sha256",
            ),
            (
                "BENCHMARK_REVIEW_COMPLETE",
                ("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED", "BENCHMARK_REVIEW_COMPLETE"),
                "benchmark_disposition_sha256",
            ),
            (
                "PRODUCTION_GENERATED",
                ("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED", "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED", "PRODUCTION_GENERATED"),
                "artifact_manifest_sha256",
            ),
            (
                "ARTIFACT_QA_PASSED",
                ("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED", "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED", "PRODUCTION_GENERATED", "ARTIFACT_QA_PASSED"),
                "artifact_qa_sha256",
            ),
            (
                "VISUAL_REVIEW_APPROVED",
                ("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED", "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED", "PRODUCTION_GENERATED", "ARTIFACT_QA_PASSED", "VISUAL_REVIEW_APPROVED"),
                "visual_review_sha256",
            ),
            (
                "ACCEPTED",
                ("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED", "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED", "PRODUCTION_GENERATED", "ARTIFACT_QA_PASSED", "VISUAL_REVIEW_APPROVED", "ACCEPTED"),
                "acceptance_sha256",
            ),
        )

        def claimed_state(transitions: tuple[str, ...]) -> dict[str, Any]:
            state = initial_pipeline_state("RUN-PIPE")
            for index, next_state in enumerate(transitions):
                field = pipeline_state_module.TRANSITION_EVIDENCE_FIELDS[next_state]
                digest = state["artifacts"].get(field) or sha256_bytes(f"fake:{next_state}".encode())
                state = advance_pipeline_state(
                    state,
                    next_state,
                    recorded_at=f"2026-09-29T10:{index:02d}:00Z",
                    artifact_sha256_updates={field: digest},
                )
            return state

        for expected_state, transitions, missing_field in evidence_cases:
            with self.subTest(state=expected_state), tempfile.TemporaryDirectory() as temp:
                state = claimed_state(transitions)
                self.assertEqual(state["current_state"], expected_state)
                self.assertEqual(validate_pipeline_state_payload(state), [])
                state_path = Path(temp) / "pipeline-state.json"
                _write_json(state_path, state)
                _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path)
                self.assertTrue(any(f"artifacts.{missing_field}" in error and "artifact file" in error for error in errors), errors)

        # Optional benchmark preparation is not required when no such stage was visited.
        with tempfile.TemporaryDirectory() as temp:
            state = claimed_state(("SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE"))
            state_path = Path(temp) / "pipeline-state.json"
            _write_json(state_path, state)
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path)
            self.assertFalse(any("benchmark_preparation_sha256" in error for error in errors))

        # Once the optional preparation stage is in history, later states still require its file proof.
        with tempfile.TemporaryDirectory() as temp:
            state = claimed_state(("SOURCE_TRUTH_FROZEN", "BENCHMARK_PREPARED", "AUTHORING_COMPLETE"))
            state_path = Path(temp) / "pipeline-state.json"
            _write_json(state_path, state)
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path)
            self.assertTrue(any("artifacts.benchmark_preparation_sha256" in error and "artifact file" in error for error in errors), errors)

    def test_pipeline_cli_never_accepts_naked_hashes_for_accepted(self) -> None:
        transitions = (
            "SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED",
            "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED",
            "PRODUCTION_GENERATED", "ARTIFACT_QA_PASSED", "VISUAL_REVIEW_APPROVED", "ACCEPTED",
        )
        state = initial_pipeline_state("RUN-PIPE")
        for index, next_state in enumerate(transitions):
            field = pipeline_state_module.TRANSITION_EVIDENCE_FIELDS[next_state]
            digest = state["artifacts"].get(field) or sha256_bytes(f"naked:{next_state}".encode())
            state = advance_pipeline_state(
                state,
                next_state,
                recorded_at=f"2026-09-29T10:{index:02d}:00Z",
                artifact_sha256_updates={field: digest},
            )
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "pipeline-state.json"
            _write_json(state_path, state)
            output = io.StringIO()
            with redirect_stdout(output):
                code = pipeline_state_module._main(["validate", str(state_path)])
            self.assertNotEqual(code, 0)
            self.assertNotIn("VALID pipeline_state_sha256", output.getvalue())
            self.assertIn("artifacts.acceptance_sha256", output.getvalue())

    def test_exact_pipeline_artifact_files_pass_and_mutation_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source, content, review, benchmark_evidence, authorization_path, _authorization = ProductionAuthorizationTests()._valid_files(directory)
            preproduction_qa_path = directory / "run" / "preproduction-qa.json"
            artifact_manifest_path = directory / "run" / "artifact-manifest.json"
            artifact_qa_path = directory / "run" / "artifact-qa.json"
            visual_review_path = directory / "run" / "visual-review.json"
            acceptance_path = directory / "run" / "acceptance.json"
            artifacts = {
                "preproduction_qa_sha256": _write_json(preproduction_qa_path, {"result": "passed"}),
                "artifact_manifest_sha256": _write_json(artifact_manifest_path, {"artifact": "lesson-plan.docx"}),
                "artifact_qa_sha256": _write_json(artifact_qa_path, {"result": "passed"}),
                "visual_review_sha256": _write_json(visual_review_path, {"decision": "APPROVED"}),
                "acceptance_sha256": _write_json(acceptance_path, {"decision": "ACCEPTED"}),
            }
            state = initial_pipeline_state("RUN-001")
            for index, next_state in enumerate((
                "SOURCE_TRUTH_FROZEN", "AUTHORING_COMPLETE", "PREPRODUCTION_QA_PASSED",
                "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED",
                "PRODUCTION_GENERATED", "ARTIFACT_QA_PASSED", "VISUAL_REVIEW_APPROVED", "ACCEPTED",
            )):
                evidence_field = pipeline_state_module.TRANSITION_EVIDENCE_FIELDS[next_state]
                if next_state == "SOURCE_TRUTH_FROZEN":
                    evidence = source.read_bytes()
                elif next_state == "AUTHORING_COMPLETE":
                    evidence = content.read_bytes()
                elif next_state == "PREPRODUCTION_QA_PASSED":
                    evidence = artifacts[evidence_field]
                elif next_state == "READY_FOR_TEACHER_REVIEW":
                    evidence = artifacts["preproduction_qa_sha256"]
                elif next_state == "TEACHER_REVIEW_APPROVED":
                    evidence = review.read_bytes()
                elif next_state == "PRODUCTION_AUTHORIZED":
                    evidence = authorization_path.read_bytes()
                else:
                    evidence = artifacts[evidence_field]
                digest = sha256_bytes(evidence)
                state = advance_pipeline_state(
                    state,
                    next_state,
                    recorded_at=f"2026-09-29T10:{index:02d}:00Z",
                    artifact_sha256_updates={evidence_field: digest},
                )
            state_path = directory / "run" / "pipeline-state.json"
            _write_json(state_path, state)
            args = {
                "source_truth_path": source,
                "content_path": content,
                "teacher_review_path": review,
                "production_authorization_path": authorization_path,
                "benchmark_evidence_path": benchmark_evidence,
                "artifact_paths": {field: path for field, path in (
                    ("preproduction_qa_sha256", preproduction_qa_path),
                    ("artifact_manifest_sha256", artifact_manifest_path),
                    ("artifact_qa_sha256", artifact_qa_path),
                    ("visual_review_sha256", visual_review_path),
                    ("acceptance_sha256", acceptance_path),
                )},
                "skill_root": LESSON,
            }
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
            self.assertEqual(errors, [])
            acceptance_path.write_bytes(acceptance_path.read_bytes() + b" ")
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
            self.assertTrue(any("acceptance_sha256 does not match" in error for error in errors), errors)

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
            {"from_state": "INTAKE_CONFIRMED", "to_state": "INTAKE_CONFIRMED", "evidence_sha256": "a" * 64, "recorded_at": "2026-09-29T10:00:00Z"}
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
        expected_downstream = {
            "source_truth": {"content", "benchmark_preparation", "benchmark_review", "benchmark_authorization", "benchmark_disposition", "teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "content": {"benchmark_review", "benchmark_authorization", "benchmark_disposition", "teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "benchmark_preparation": {"benchmark_review", "benchmark_authorization", "benchmark_disposition", "teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "benchmark_review": {"benchmark_authorization", "benchmark_disposition", "teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "benchmark_authorization": {"benchmark_disposition", "teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "benchmark_disposition": {"teacher_review", "production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "teacher_review": {"production_authorization", "final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "production_authorization": {"final_artifacts", "artifact_qa", "visual_review", "acceptance"},
            "final_artifacts": {"artifact_qa", "visual_review", "acceptance"},
            "artifact_qa": {"visual_review", "acceptance"},
            "visual_review": {"acceptance"},
            "acceptance": set(),
        }
        self.assertEqual(set(pipeline_state_module.SUPPORTED_DEPENDENCY_NODES), set(expected_downstream))
        for node, expected in expected_downstream.items():
            with self.subTest(node=node):
                self.assertEqual(stale_downstream(node), expected)
        with self.assertRaisesRegex(LifecycleContractError, "unknown lifecycle dependency node: misspelled"):
            stale_downstream("misspelled")

    def test_approved_state_requires_current_review_and_authorized_state_requires_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            _source, source_path = _source_truth(directory / "run")
            source_raw = source_path.read_bytes()
            content_path = directory / "run" / "lesson-content.json"
            content_raw = _write_json(content_path, _content())
            preproduction_qa_path = directory / "run" / "preproduction-qa.json"
            preproduction_qa_raw = _write_json(preproduction_qa_path, {"result": "passed"})
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
                artifact_sha256_updates={"preproduction_qa_sha256": sha256_bytes(preproduction_qa_raw)},
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
                artifact_paths={"preproduction_qa_sha256": preproduction_qa_path},
            )
            self.assertEqual(errors, [])

            content_path.write_bytes(content_raw + b" ")
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(
                state_path,
                source_truth_path=source_path,
                content_path=content_path,
                teacher_review_path=review_path,
                artifact_paths={"preproduction_qa_sha256": preproduction_qa_path},
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
                artifact_paths={"preproduction_qa_sha256": preproduction_qa_path},
            )
            self.assertTrue(any("requires Source Truth, Content, Teacher Review and Authorization files" in item for item in errors))

    def test_revision_required_benchmark_blocks_pipeline_teacher_approval_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            builder = ProductionAuthorizationTests()
            source, content, teacher, _evidence, _production_auth, _authorization = builder._valid_files(
                directory,
                benchmark_disposition="BENCHMARK_REVIEW_COMPLETE",
                benchmark_decision="REVISION_REQUIRED",
            )
            benchmark_auth, benchmark_review = builder._last_benchmark_paths
            preproduction_qa = source.parent / "preproduction-qa.json"
            preproduction_bytes = _write_json(preproduction_qa, {"result": "passed"})
            benchmark_disposition = source.parent / "benchmark-disposition.json"
            disposition_bytes = _write_json(benchmark_disposition, {"disposition": "BENCHMARK_REVIEW_COMPLETE"})

            state = initial_pipeline_state("RUN-001")
            for index, (next_state, field, evidence) in enumerate((
                ("SOURCE_TRUTH_FROZEN", "source_truth_manifest_sha256", source.read_bytes()),
                ("AUTHORING_COMPLETE", "content_sha256", content.read_bytes()),
                ("PREPRODUCTION_QA_PASSED", "preproduction_qa_sha256", preproduction_bytes),
                ("BENCHMARK_REVIEW_COMPLETE", "benchmark_disposition_sha256", disposition_bytes),
                ("READY_FOR_TEACHER_REVIEW", None, None),
                ("TEACHER_REVIEW_APPROVED", "teacher_review_sha256", teacher.read_bytes()),
            )):
                updates = {field: sha256_bytes(evidence)} if field is not None and evidence is not None else None
                state = advance_pipeline_state(
                    state,
                    next_state,
                    recorded_at=f"2026-09-29T10:{index:02d}:00Z",
                    artifact_sha256_updates=updates,
                )

            self.assertEqual(validate_pipeline_state_payload(state), [])
            state_path = source.parent / "pipeline-state.json"
            _write_json(state_path, state)
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(
                state_path,
                source_truth_path=source,
                content_path=content,
                teacher_review_path=teacher,
                benchmark_authorization_path=benchmark_auth,
                benchmark_review_path=benchmark_review,
                artifact_paths={
                    "preproduction_qa_sha256": preproduction_qa,
                    "benchmark_disposition_sha256": benchmark_disposition,
                },
            )
            self.assertTrue(any("requires revision before final production authorization" in item for item in errors), errors)

    def test_production_authorized_state_binds_valid_authorization_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source, content, review, evidence, authorization_path, _authorization = ProductionAuthorizationTests()._valid_files(directory)
            source_raw = source.read_bytes()
            content_raw = content.read_bytes()
            review_raw = review.read_bytes()
            authorization_raw = authorization_path.read_bytes()
            preproduction_qa_path = directory / "run" / "preproduction-qa.json"
            preproduction_qa_raw = _write_json(preproduction_qa_path, {"result": "passed"})
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
                artifact_sha256_updates={"preproduction_qa_sha256": sha256_bytes(preproduction_qa_raw)},
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
                "artifact_paths": {"preproduction_qa_sha256": preproduction_qa_path},
                "skill_root": LESSON,
            }
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
            self.assertEqual(errors, [])

            authorization_path.write_bytes(authorization_raw + b" ")
            _loaded, _raw, errors = pipeline_state_module.validate_pipeline_state_files(state_path, **args)
            self.assertTrue(any("production_authorization_sha256 does not match" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
