"""Fail-closed provenance gate for full-course Content Contract 2.4."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from package_common import DEFAULT_SCHEMA, canonical_json_sha256, lesson_agent_content

SKILL_DIR = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA = SKILL_DIR / "schemas" / "generation-evidence.schema.json"
BENCHMARK_SCHEMA = SKILL_DIR / "schemas" / "benchmark-lesson-review.schema.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _is_reserved_example_url(value: Any) -> bool:
    """Reject documentation-only hostnames as real research evidence."""

    try:
        host = (urlsplit(str(value)).hostname or "").lower().rstrip(".")
    except ValueError:
        return True
    return host in {"example.com", "example.net", "example.org", "localhost"} or host.endswith(
        (".example", ".invalid", ".test", ".localhost", ".local")
    )


def _schema_errors(data: Mapping[str, Any], schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda error: list(map(str, error.absolute_path)))
    ]


def _course_projects(data: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for lesson in data.get("lessons", []):
        result.setdefault(str(lesson.get("unit", "")), []).append(lesson)
    return result


def validate_generation_evidence(
    evidence: Mapping[str, Any],
    content: Mapping[str, Any],
    *,
    content_bytes: bytes | None = None,
    evidence_schema: Path = EVIDENCE_SCHEMA,
) -> list[str]:
    errors = _schema_errors(evidence, evidence_schema)
    if errors:
        return errors
    if content.get("content_contract_version") != "2.4":
        return ["generation evidence is required only for and must bind to Content Contract 2.4"]
    if content_bytes is not None and str(evidence.get("content_sha256", "")).upper() != sha256_bytes(content_bytes):
        errors.append("generation_evidence.content_sha256 does not match the exact Lesson Content bytes")
    case_facts_sha = str(content.get("course_case_facts_sha256", "")).upper()
    if not case_facts_sha or str(evidence.get("course_case_facts_sha256", "")).upper() != case_facts_sha:
        errors.append("generation_evidence.course_case_facts_sha256 does not match the frozen Content case facts")

    lessons = [lesson for lesson in content.get("lessons", []) if isinstance(lesson, dict)]
    lesson_by_id = {str(lesson.get("lesson_id")): lesson for lesson in lessons}
    outline = content.get("outline", [])
    projects = _course_projects(content)
    workflow = evidence["project_workflow"]
    if str(workflow.get("course_case_facts_sha256", "")).upper() != case_facts_sha:
        errors.append("project_workflow.course_case_facts_sha256 does not match the frozen Content case facts")
    if str(workflow.get("outline_sha256", "")).upper() != canonical_json_sha256(outline):
        errors.append("project_workflow.outline_sha256 does not match the frozen full-course outline")
    frozen_outline = workflow.get("frozen_outline", [])
    if str(workflow.get("frozen_outline_sha256", "")).upper() != canonical_json_sha256(frozen_outline):
        errors.append("project_workflow.frozen_outline_sha256 does not match the retained frozen project outline")
    frozen_ids = [str(item.get("lesson_id")) for item in frozen_outline]
    if not frozen_ids or len(frozen_ids) != len(set(frozen_ids)):
        errors.append("project_workflow.frozen_outline must contain unique Lesson IDs")
    frozen_projects: dict[str, list[dict[str, Any]]] = {}
    for row in frozen_outline:
        frozen_projects.setdefault(str(row.get("unit", "")), []).append(row)
    if set(frozen_ids) != set(lesson_by_id):
        errors.append("retained frozen project outline Lesson IDs must exactly match merged Content")
    if set(frozen_projects) != set(projects):
        errors.append("retained frozen outline project groups must match merged Content project groups")
    evidence_projects = workflow["projects"]
    project_ids = [str(item.get("project_id")) for item in evidence_projects]
    if len(project_ids) != len(set(project_ids)):
        errors.append("project_workflow contains duplicate project IDs")
    if set(project_ids) != set(projects):
        errors.append("project_workflow projects must exactly match the frozen outline's project/unit groups")
    expected_mode = workflow.get("mode")
    seen_agents: set[str] = set()
    all_returned: list[str] = []
    project_ids_set = set(projects)
    for project in evidence_projects:
        project_id = str(project.get("project_id"))
        expected_lessons = projects.get(project_id, [])
        if str(project.get("course_case_facts_sha256", "")).upper() != case_facts_sha:
            errors.append(f"project {project_id} did not bind the frozen shared course case facts")
        expected_ids = [str(item.get("lesson_id")) for item in expected_lessons]
        actual_ids = list(map(str, project.get("lesson_ids", [])))
        returned_ids = list(map(str, project.get("returned_lesson_ids", [])))
        if actual_ids != expected_ids:
            errors.append(f"project {project_id} lesson scope differs from the frozen outline")
        if returned_ids != expected_ids:
            errors.append(f"project {project_id} returned Lesson IDs differ from its assigned scope")
        all_returned.extend(returned_ids)
        owner = str(project.get("owner", ""))
        if expected_mode == "project_subagents":
            if not owner.startswith("subagent:") or len(owner) <= len("subagent:"):
                errors.append(f"project {project_id} requires an actual subagent owner record")
            elif owner in seen_agents:
                errors.append(f"project {project_id} reuses a project-specific subagent")
            seen_agents.add(owner)
        elif owner != "main_agent_fallback":
            errors.append(f"project {project_id} fallback execution must be recorded as main_agent_fallback")
        frozen_expected = frozen_projects.get(project_id, [])
        frozen_expected_ids = [str(row.get("lesson_id")) for row in frozen_expected]
        if actual_ids != frozen_expected_ids:
            errors.append(f"project {project_id} assigned scope differs from the retained frozen outline")
        expected_input = canonical_json_sha256(frozen_expected)
        expected_output = canonical_json_sha256(expected_lessons)
        if str(project.get("input_sha256", "")).upper() != expected_input:
            errors.append(f"project {project_id} input_sha256 does not bind its outline work package")
        if str(project.get("output_sha256", "")).upper() != expected_output:
            errors.append(f"project {project_id} output_sha256 does not bind returned Lesson content")
        for row in frozen_expected:
            lesson = lesson_by_id.get(str(row.get("lesson_id")))
            if lesson is None:
                continue
            progression = lesson.get("progression", {}) if isinstance(lesson.get("progression"), Mapping) else {}
            for field, observed in (
                ("unit", lesson.get("unit")),
                ("task", lesson.get("task")),
                ("lesson_type", lesson.get("lesson_type")),
                ("hours", lesson.get("hours")),
                ("theory_hours", lesson.get("theory_hours")),
                ("practice_hours", lesson.get("practice_hours")),
            ):
                if observed != row.get(field):
                    errors.append(f"merged Lesson {row.get('lesson_id')}.{field} conflicts with its frozen project row")
            if progression.get("capability_stage") != row.get("capability_stage"):
                errors.append(f"merged Lesson {row.get('lesson_id')}.capability_stage conflicts with its frozen project row")
        total = sum(float(item.get("hours", 0)) for item in expected_lessons)
        theory = sum(float(item.get("theory_hours", 0)) for item in expected_lessons)
        practice = sum(float(item.get("practice_hours", 0)) for item in expected_lessons)
        for field, expected in (("hours", total), ("theory_hours", theory), ("practice_hours", practice)):
            try:
                actual = float(project.get(field))
            except (TypeError, ValueError):
                actual = -1
            if actual != expected:
                errors.append(f"project {project_id}.{field} expected {expected}, got {actual}")
    if sorted(all_returned) != sorted(lesson_by_id):
        errors.append("project merge omitted or duplicated Lesson IDs")
    if len(all_returned) != len(set(all_returned)):
        errors.append("project merge returned duplicate Lesson IDs")

    exemplar = evidence["exemplar_research"]
    if exemplar.get("status") in {"search_blocked", "not_executed"}:
        errors.append(f"pre-writing exemplar search cannot pass with status={exemplar.get('status')}")
    queries = {str(item["query_id"]): item for item in exemplar.get("queries", [])}
    sources = {str(item["source_id"]): item for item in exemplar.get("sources", [])}
    if not sources and exemplar.get("status") not in {"searched_no_accessible_design", "searched_no_qualified_exemplar"}:
        errors.append("exemplar research status claims comparison without a read source")
    if sources and exemplar.get("status") in {"searched_no_accessible_design", "searched_no_qualified_exemplar"}:
        errors.append("exemplar research cannot claim no usable source while retaining comparison sources")
    if exemplar.get("status") == "completed_with_qualified_exemplar" and not any(
        item.get("excellence_status") == "verified_excellent" for item in sources.values()
    ):
        errors.append("completed_with_qualified_exemplar requires at least one source with verifiable excellence evidence")
    searched_projects: set[str] = set()
    searched_lesson_ids: set[str] = set()
    chinese_projects: set[str] = set()
    for query in queries.values():
        scoped = set(map(str, query.get("project_ids", [])))
        if not scoped or scoped - project_ids_set:
            errors.append(f"exemplar query {query.get('query_id')} has invalid project scope")
        searched_projects.update(scoped)
        query_lessons = set(map(str, query.get("lesson_ids", [])))
        if not query_lessons or query_lessons - set(lesson_by_id):
            errors.append(f"exemplar query {query.get('query_id')} has invalid Lesson scope")
        for lesson_id in query_lessons:
            if str(lesson_by_id.get(lesson_id, {}).get("unit", "")) not in scoped:
                errors.append(f"exemplar query {query.get('query_id')} Lesson scope conflicts with project scope")
        searched_lesson_ids.update(query_lessons)
        if query.get("language") == "zh":
            chinese_projects.update(scoped)
    if searched_projects != project_ids_set:
        errors.append("pre-writing exemplar search must cover every frozen project")
    if searched_lesson_ids != set(lesson_by_id):
        errors.append("pre-writing exemplar search must record Lesson-level coverage for the full course")
    if chinese_projects != project_ids_set:
        errors.append("each project must record at least one Chinese-first exemplar search")
    for source_id, source in sources.items():
        if _is_reserved_example_url(source.get("url")) or _is_reserved_example_url(source.get("discovery_url")):
            errors.append(f"exemplar {source_id} uses a reserved placeholder URL and cannot support a completed comparison")
        if source.get("excellence_status") == "verified_excellent":
            basis = str(source.get("excellence_evidence", "")).casefold()
            if not any(marker in basis for marker in ("评审", "示范", "获奖", "省级", "国家级", "official rubric", "official award")):
                errors.append(f"exemplar {source_id} has no credible excellence evidence")
        if source.get("source_type") == "ordinary_public_design" and source.get("excellence_status") == "verified_excellent":
            errors.append(f"ordinary public design {source_id} cannot be labeled excellent without independent quality evidence")
        if not any(
            source.get("discovery_url") in item.get("result_urls", [])
            for item in queries.values()
        ):
            errors.append(f"exemplar {source_id} discovery_url is not present in actual search result evidence")
        if str(source.get("capture_sha256", "")).upper() != sha256_bytes(str(source.get("read_excerpt", "")).encode("utf-8")):
            errors.append(f"exemplar {source_id} capture_sha256 does not match its actually read excerpt")
        if not set(map(str, source.get("lesson_ids", []))) <= set(lesson_by_id):
            errors.append(f"exemplar {source_id} is mapped to unknown Lesson IDs")
        if not set(map(str, source.get("project_ids", []))) <= project_ids_set:
            errors.append(f"exemplar {source_id} is mapped to unknown project IDs")
        mapped_ids = {
            lesson_id
            for project_id in source.get("project_ids", [])
            for lesson_id in [str(item.get("lesson_id")) for item in projects.get(str(project_id), [])]
        }
        if not set(map(str, source.get("lesson_ids", []))) <= mapped_ids:
            errors.append(f"exemplar {source_id} Lesson mapping conflicts with project scope")

    rubric_schema = json.loads(BENCHMARK_SCHEMA.read_text(encoding="utf-8"))
    rubric = set(rubric_schema["properties"]["dimensions"]["items"]["properties"]["dimension"]["enum"])
    comparisons = evidence["lesson_comparisons"]
    comparison_by_id: dict[str, Mapping[str, Any]] = {}
    for item in comparisons:
        lesson_id = str(item.get("lesson_id"))
        if lesson_id in comparison_by_id:
            errors.append(f"duplicate post-draft comparison for {lesson_id}")
        comparison_by_id[lesson_id] = item
    if set(comparison_by_id) != set(lesson_by_id):
        errors.append("post-draft comparison Lesson IDs must exactly match the course")
    limited_comparison = False
    for lesson_id, item in comparison_by_id.items():
        lesson = lesson_by_id.get(lesson_id)
        if lesson is None:
            continue
        comparison_status = item.get("comparison_status")
        if comparison_status == "SEARCH_BLOCKED":
            errors.append(f"{lesson_id} exemplar comparison cannot pass with SEARCH_BLOCKED")
        elif comparison_status == "SEARCHED_NO_QUALIFIED_EXEMPLAR":
            limited_comparison = True
            if item.get("comparison_type") != "search_no_qualified_exemplar" or item.get("source_ids"):
                errors.append(f"{lesson_id} without a qualified exemplar must not claim a completed source comparison")
            if not any(lesson_id in query.get("lesson_ids", []) for query in queries.values()):
                errors.append(f"{lesson_id} no-exemplar status is missing a lesson-scoped search record")
        elif comparison_status == "EXEMPLAR_COMPARISON_DONE":
            if item.get("comparison_type") != "daily_non_blind":
                errors.append(f"{lesson_id} completed comparison must be labeled daily_non_blind")
        else:
            errors.append(f"{lesson_id} has an unsupported exemplar comparison status")
        expected_content_digest = canonical_json_sha256(lesson_agent_content(lesson))
        if str(item.get("lesson_content_sha256", "")).upper() != expected_content_digest:
            errors.append(f"{lesson_id} comparison digest does not bind the final lesson content")
        source_ids = set(map(str, item.get("source_ids", [])))
        if comparison_status == "EXEMPLAR_COMPARISON_DONE" and (not source_ids or source_ids - set(sources)):
            errors.append(f"{lesson_id} comparison must cite a read exemplar source")
        if comparison_status == "SEARCHED_NO_QUALIFIED_EXEMPLAR" and source_ids:
            errors.append(f"{lesson_id} no-exemplar comparison cannot cite an unavailable source")
        for source_id in source_ids & set(sources):
            if lesson_id not in set(map(str, sources[source_id].get("lesson_ids", []))):
                errors.append(f"{lesson_id} comparison cites exemplar {source_id} outside its mapped lesson scope")
        dimensions = item.get("dimensions", [])
        found = [str(row.get("dimension")) for row in dimensions]
        if set(found) != rubric or len(found) != len(rubric):
            errors.append(f"{lesson_id} comparison must cover each existing rubric dimension exactly once")
        for row in dimensions:
            if row.get("conclusion") == "revise" and row.get("status") not in {"PARTIAL", "GAP"}:
                errors.append(f"{lesson_id}.{row.get('dimension')} cannot recommend revision without an actual gap")
        revision = item.get("revision", {})
        draft_sha = str(revision.get("draft_content_sha256", "")).upper()
        final_sha = str(revision.get("final_content_sha256", "")).upper()
        pedagogical = lesson.get("pedagogical_review", {})
        if canonical_json_sha256(pedagogical.get("draft_content", {})) != draft_sha:
            errors.append(f"{lesson_id} draft review digest does not match pedagogical_review.draft_content")
        if canonical_json_sha256(pedagogical.get("revised_content", {})) != final_sha:
            errors.append(f"{lesson_id} final review digest does not match pedagogical_review.revised_content")
        material_gap = any(
            row.get("status") in {"PARTIAL", "GAP"} and row.get("conclusion") == "revise"
            for row in item.get("dimensions", [])
        )
        if bool(revision.get("necessary")) != material_gap:
            errors.append(f"{lesson_id} revision.necessary must agree with 15-dimension revise conclusions")
        if revision.get("necessary") and (not revision.get("changed") or draft_sha == final_sha):
            errors.append(f"{lesson_id} has a substantive issue but no substantive revision")
        if revision.get("necessary") and not any(
            record.get("decision") == "needs_revision"
            for record in pedagogical.get("review_history", [])
            if isinstance(record, Mapping)
        ):
            errors.append(f"{lesson_id} must record its required rewrite in pedagogical_review.review_history")
        if not revision.get("necessary") and revision.get("changed"):
            errors.append(f"{lesson_id} records an unnecessary change; retain the draft when there is no material issue")
        if not revision.get("necessary") and draft_sha != final_sha:
            errors.append(f"{lesson_id} draft/final digest differs without a recorded issue")

    course = evidence["course_review"]
    content_total = float(content.get("total_hours", 0))
    expected_theory = float((content.get("delivery_plan") or {}).get("theory_hours", 0))
    expected_practice = float((content.get("delivery_plan") or {}).get("practice_hours", 0))
    expected_lesson_ids = [str(item.get("lesson_id")) for item in lessons]
    if list(map(str, course.get("lesson_ids", []))) != expected_lesson_ids:
        errors.append("course_review lesson_ids must preserve the merged Content sequence exactly")
    if list(map(str, course.get("project_ids", []))) != list(projects):
        errors.append("course_review project_ids must preserve the frozen project order")
    expected_course_review_status = "limited" if limited_comparison else "passed"
    if course.get("status") != expected_course_review_status:
        errors.append(f"main-Agent course-level review must be {expected_course_review_status} for its exemplar evidence state")
    if course.get("duplicate_lesson_ids") or course.get("project_scope_conflicts"):
        errors.append("course-level merge records duplicate Lesson IDs or project scope conflicts")
    for field, expected in (("declared_hours", content_total), ("lesson_hours", content_total), ("theory_hours", expected_theory), ("practice_hours", expected_practice)):
        try:
            actual = float(course.get(field))
        except (TypeError, ValueError):
            actual = -1
        if actual != expected:
            errors.append(f"course_review.{field} expected {expected}, got {actual}")
    return errors


def load_and_validate_generation_evidence(path: Path, content: Mapping[str, Any], content_path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        evidence = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"generation evidence is not valid JSON: {exc}") from exc
    if not isinstance(evidence, dict):
        raise ValueError("generation evidence root must be an object")
    errors = validate_generation_evidence(evidence, content, content_bytes=content_path.read_bytes())
    if errors:
        raise ValueError("generation evidence rejected: " + "; ".join(errors[:12]))
    return evidence, sha256_bytes(raw)
