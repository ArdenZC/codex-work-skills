"""Production Authorization Contract 1.0 validation for Lesson lifecycle sidecars."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from importlib import metadata as importlib_metadata
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from lifecycle_digest import (
    LifecycleContractError,
    assert_distinct_safe_paths,
    canonical_json_bytes,
    read_json_object,
    schema_errors,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
    skill_tree_fingerprint,
    timezone_aware_timestamp,
)
from source_truth import source_truth_local_file_paths, validate_source_truth_payload
from teacher_review import validate_teacher_review_files


SKILL_DIR = Path(__file__).resolve().parents[1]
FINGERPRINT_EXCLUDED_FIELDS = {"created_at", "authorization_fingerprint"}
SUPPORTED_CONTENT_VERSIONS = {"2.2", "2.3"}


def production_authorization_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(payload, excluded_fields=FINGERPRINT_EXCLUDED_FIELDS)


def _current_repo_commit(root: Path) -> str | None:
    try:
        root_path = root.expanduser().resolve(strict=True)
        top_result = subprocess.run(
            ["git", "-C", str(root_path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if top_result.returncode != 0:
            return None
        repository_root = Path(top_result.stdout.strip()).resolve(strict=True)
        relative_skill = root_path.relative_to(repository_root).as_posix()
        if relative_skill != "教案生成器/lesson-plan-docx-generator":
            return None
        tracked = subprocess.run(
            [
                "git", "-C", str(repository_root), "ls-files", "--error-unmatch", "--",
                f"{relative_skill}/SKILL.md",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if tracked.returncode != 0:
            return None
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or len(value) != 40:
        return None
    return value.lower()


def runtime_versions() -> dict[str, Any]:
    def installed(package: str) -> str:
        try:
            return importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError as exc:
            raise LifecycleContractError(f"required runtime package is not installed: {package}") from exc

    return {
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "python_docx_version": installed("python-docx"),
        "jsonschema_version": installed("jsonschema"),
        "pyyaml_version": installed("PyYAML"),
    }


def _runtime_errors(runtime: Mapping[str, Any], *, verify_environment: bool) -> list[str]:
    if not verify_environment:
        return []
    errors: list[str] = []
    try:
        actual = runtime_versions()
    except (LifecycleContractError, ImportError) as exc:
        return [str(exc)]
    for field, version in actual.items():
        if runtime.get(field) != version:
            errors.append(f"runtime.{field} does not match the current runtime ({version})")
    if runtime.get("render_performed"):
        import shutil

        executable = shutil.which("soffice") or shutil.which("libreoffice")
        if not executable:
            errors.append("runtime.render_performed is true but LibreOffice is unavailable")
        else:
            try:
                result = subprocess.run(
                    [executable, "--version"], check=False, capture_output=True, text=True, timeout=15
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"cannot verify LibreOffice runtime version: {exc}")
            else:
                reported = (result.stdout or result.stderr).strip()
                if result.returncode != 0 or runtime.get("libreoffice_version") != reported:
                    errors.append("runtime.libreoffice_version does not match the current LibreOffice version")
    return errors


def _template_errors(
    authorization: Mapping[str, Any],
    *,
    skill_root: str | Path,
    manifest_path: str | Path | None,
    template_path: str | Path | None,
    other_paths: Mapping[str, str | Path],
) -> list[str]:
    errors: list[str] = []
    canonical_manifest = Path(skill_root).expanduser() / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "manifest.yaml"
    manifest_value = Path(manifest_path).expanduser() if manifest_path is not None else canonical_manifest
    try:
        from exemplar_contract import assert_distinct_file_paths
        from package_common import (
            load_manifest,
            manifest_template_path,
            validate_template_package_identity,
        )

        assert_distinct_safe_paths({**other_paths, "template_manifest": manifest_value})
        if manifest_value.resolve(strict=True) != canonical_manifest.resolve(strict=True):
            errors.append("Production Authorization must bind the canonical Skill Template 1.1.2 manifest")
            return errors
        manifest = load_manifest(manifest_value)
        declared_template = manifest_template_path(manifest)
        actual_template = Path(template_path).expanduser() if template_path is not None else declared_template
        assert_distinct_file_paths({"manifest": manifest_value, "template": actual_template})
        assert_distinct_safe_paths({**other_paths, "template_manifest": manifest_value, "template": actual_template})
        if actual_template.resolve() != declared_template.resolve():
            errors.append("selected template path does not match template.file in its manifest")
        validate_template_package_identity(
            actual_template,
            manifest,
            explicit_manifest=True,
            explicit_template=template_path is not None,
        )
        template_info = manifest.get("template", {})
        if template_info.get("id") != "lesson-plan" or str(template_info.get("version")) != "1.1.2":
            errors.append("Production Authorization requires the canonical lesson-plan template v1.1.2")
        expected = authorization["template"]
        manifest_sha = sha256_file(manifest_value)
        template_sha = sha256_file(actual_template)
        if expected.get("manifest_sha256", "").casefold() != manifest_sha:
            errors.append("template.manifest_sha256 does not match the selected manifest bytes")
        if expected.get("template_sha256", "").casefold() != template_sha:
            errors.append("template.template_sha256 does not match the selected template bytes")
        if expected.get("template_id") != template_info.get("id"):
            errors.append("template.template_id does not match the selected manifest")
        if expected.get("template_version") != str(template_info.get("version")):
            errors.append("template.template_version does not match the selected manifest")
    except (ImportError, OSError, ValueError, LifecycleContractError) as exc:
        errors.append(f"cannot verify template package identity and bytes: {exc}")
    return errors


def validate_production_authorization_payload(payload: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(payload, "production-authorization.schema.json")
    if errors:
        return errors
    if not timezone_aware_timestamp(payload.get("created_at")):
        errors.append("created_at must include a timezone")
    if payload.get("authorization_fingerprint", "").casefold() != production_authorization_fingerprint(payload):
        errors.append("authorization_fingerprint does not match canonical semantic content")
    if payload.get("content_contract_version") not in SUPPORTED_CONTENT_VERSIONS:
        errors.append("content_contract_version must remain Lesson Content 2.2 or 2.3")
    for field in ("authorization_id", "pipeline_run_id"):
        if not str(payload.get(field, "")).strip():
            errors.append(f"{field} must contain non-whitespace text")
    for field in ("python_version", "python_docx_version", "jsonschema_version", "pyyaml_version"):
        if not str(payload.get("runtime", {}).get(field, "")).strip():
            errors.append(f"runtime.{field} must contain non-whitespace text")
    benchmark = payload.get("benchmark", {})
    if benchmark.get("disposition") == "BENCHMARK_NOT_EXECUTED":
        errors.append("BENCHMARK_NOT_EXECUTED is not a valid Production Authorization disposition")
    return errors


def validate_production_authorization_files(
    authorization_path: str | Path,
    *,
    source_truth_path: str | Path,
    content_path: str | Path,
    teacher_review_path: str | Path,
    benchmark_authorization_path: str | Path | None = None,
    benchmark_review_path: str | Path | None = None,
    benchmark_evidence_path: str | Path | None = None,
    skill_root: str | Path = SKILL_DIR,
    template_manifest_path: str | Path | None = None,
    template_path: str | Path | None = None,
    verify_runtime_environment: bool = True,
) -> tuple[dict[str, Any], bytes, list[str]]:
    authorization, authorization_raw = read_json_object(authorization_path, "production_authorization")
    structural_errors = schema_errors(authorization, "production-authorization.schema.json")
    if structural_errors:
        return authorization, authorization_raw, structural_errors
    input_paths: dict[str, str | Path] = {
        "production_authorization": authorization_path,
        "source_truth_manifest": source_truth_path,
        "lesson_content": content_path,
        "teacher_review": teacher_review_path,
    }
    for label, path in (
        ("benchmark_authorization", benchmark_authorization_path),
        ("benchmark_review", benchmark_review_path),
        ("benchmark_evidence", benchmark_evidence_path),
    ):
        if path is not None:
            input_paths[label] = path
    assert_distinct_safe_paths(input_paths)
    source_truth, source_truth_raw = read_json_object(source_truth_path, "source_truth_manifest")
    content, content_raw = read_json_object(content_path, "lesson_content")
    errors = validate_production_authorization_payload(authorization)
    errors.extend(validate_source_truth_payload(source_truth, manifest_path=source_truth_path, verify_source_bytes=True))
    try:
        input_paths.update(source_truth_local_file_paths(source_truth, source_truth_path))
        assert_distinct_safe_paths(input_paths)
    except LifecycleContractError as exc:
        errors.append(f"Source Truth sources must not alias another lifecycle artifact: {exc}")
    source_truth_sha = sha256_bytes(source_truth_raw)
    content_sha = sha256_bytes(content_raw)
    if authorization.get("source_truth_manifest_sha256", "").casefold() != source_truth_sha:
        errors.append("source_truth_manifest_sha256 does not match the Source Truth Manifest bytes")
    if authorization.get("content_sha256", "").casefold() != content_sha:
        errors.append("content_sha256 is stale or does not match the exact Content JSON bytes")
    if authorization.get("content_contract_version") != content.get("content_contract_version"):
        errors.append("content_contract_version does not match the bound Content JSON")
    course_identity = source_truth.get("course_identity", {})
    if not isinstance(course_identity, Mapping):
        course_identity = {}
    for field in ("course_name", "major", "audience"):
        if course_identity.get(field) != content.get(field):
            errors.append(f"Source Truth course_identity.{field} does not match Content {field}")

    benchmark_paths = {
        "benchmark_authorization_path": benchmark_authorization_path,
        "benchmark_review_path": benchmark_review_path,
        "benchmark_evidence_path": benchmark_evidence_path,
    }
    teacher_review, teacher_review_raw, review_errors = validate_teacher_review_files(
        teacher_review_path,
        source_truth_path=source_truth_path,
        content_path=content_path,
        benchmark_authorization_path=benchmark_authorization_path,
        benchmark_review_path=benchmark_review_path,
        benchmark_evidence_path=benchmark_evidence_path,
        require_approved=True,
    )
    errors.extend(review_errors)
    if authorization.get("teacher_review_sha256", "").casefold() != sha256_bytes(teacher_review_raw):
        errors.append("teacher_review_sha256 does not match the exact Teacher Review bytes")
    if authorization.get("pipeline_run_id") != teacher_review.get("pipeline_run_id"):
        errors.append("pipeline_run_id does not match the approved Teacher Review")
    if authorization.get("benchmark") != teacher_review.get("benchmark"):
        try:
            if canonical_json_bytes(authorization.get("benchmark")) != canonical_json_bytes(teacher_review.get("benchmark")):
                errors.append("benchmark disposition and evidence linkage do not match the approved Teacher Review")
        except LifecycleContractError as exc:
            errors.append(f"benchmark linkage cannot be canonicalized: {exc}")

    expected_skill = authorization.get("lesson_skill", {})
    try:
        actual_skill_fingerprint = skill_tree_fingerprint(skill_root)
        if expected_skill.get("installed_skill_fingerprint", "").casefold() != actual_skill_fingerprint:
            errors.append("lesson_skill.installed_skill_fingerprint does not match the installed Skill tree")
    except LifecycleContractError as exc:
        errors.append(f"cannot verify installed Skill tree fingerprint: {exc}")
    current_commit = _current_repo_commit(Path(skill_root).expanduser())
    recorded_commit = expected_skill.get("source_repo_commit")
    if current_commit is not None and (
        not isinstance(recorded_commit, str) or recorded_commit.casefold() != current_commit
    ):
        errors.append("lesson_skill.source_repo_commit must match the repository commit containing this Skill")
    if current_commit is None and recorded_commit is not None:
        errors.append("lesson_skill.source_repo_commit must be null when no repository commit is determinable")

    errors.extend(_runtime_errors(authorization.get("runtime", {}), verify_environment=verify_runtime_environment))
    errors.extend(_template_errors(
        authorization,
        skill_root=skill_root,
        manifest_path=template_manifest_path,
        template_path=template_path,
        other_paths=input_paths,
    ))
    return authorization, authorization_raw, errors


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("authorization", type=Path)
    validate.add_argument("--source-truth", type=Path, required=True)
    validate.add_argument("--content", type=Path, required=True)
    validate.add_argument("--teacher-review", type=Path, required=True)
    validate.add_argument("--benchmark-authorization", type=Path)
    validate.add_argument("--benchmark-review", type=Path)
    validate.add_argument("--benchmark-evidence", type=Path)
    validate.add_argument("--skill-root", type=Path, default=SKILL_DIR)
    validate.add_argument("--template-manifest", type=Path)
    validate.add_argument("--template", type=Path)
    validate.add_argument("--skip-runtime-check", action="store_true")
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("authorization", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "fingerprint":
            payload, _raw = read_json_object(args.authorization, "production_authorization")
            print(production_authorization_fingerprint(payload))
            return 0
        authorization, raw, errors = validate_production_authorization_files(
            args.authorization,
            source_truth_path=args.source_truth,
            content_path=args.content,
            teacher_review_path=args.teacher_review,
            benchmark_authorization_path=args.benchmark_authorization,
            benchmark_review_path=args.benchmark_review,
            benchmark_evidence_path=args.benchmark_evidence,
            skill_root=args.skill_root,
            template_manifest_path=args.template_manifest,
            template_path=args.template,
            verify_runtime_environment=not args.skip_runtime_check,
        )
    except LifecycleContractError as exc:
        errors = [str(exc)]
        raw = b""
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALID production_authorization_sha256={sha256_bytes(raw)} run={authorization['pipeline_run_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
