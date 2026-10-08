"""Semantic Scope Review 1.0 structure/binding validation, never semantic judgment."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Sequence

from lifecycle_digest import canonical_json_bytes, sha256_bytes
from semantic_scope_records import (
    RecordError,
    StaleEvidence,
    TrustContext,
    checked,
    parse,
    require,
    review_fingerprint,
    stamp,
    managed_service_identity_fingerprint,
    validate_managed_service_observation,
    validate_configuration,
)
from operation_provenance import validate_receipt
from source_truth import validate_source_truth_payload


def derive_disposition(values: Sequence[str]) -> str:
    if "REVISION_REQUIRED" in values:
        return "REVISION_REQUIRED"
    if "HUMAN_REVIEW_REQUIRED" in values:
        return "HUMAN_REVIEW_REQUIRED"
    return "PASS"


def pointer(value: Any, path: str) -> Any:
    if path == "":
        return value
    require(path.startswith("/"), "invalid JSON pointer")
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            require(
                token.isascii()
                and token.isdecimal()
                and (token == "0" or not token.startswith("0")),
                "invalid array pointer",
            )
            require(int(token) < len(value), "array pointer outside source")
            value = value[int(token)]
        else:
            require(
                isinstance(value, dict) and token in value, "unresolved JSON pointer"
            )
            value = value[token]
    return value


def _references(
    rows: list[dict[str, Any]], sources: dict[str, tuple[dict[str, Any], bytes]]
) -> None:
    for ref in rows:
        require(ref["source_id"] in sources, "unknown source ID")
        source, raw = sources[ref["source_id"]]
        require(
            ref["sha256"] == source["sha256"] == sha256_bytes(raw),
            "source reference SHA mismatch",
        )
        try:
            value = parse(raw)
        except RecordError:
            require(ref["pointer"] == "", "non-JSON source pointer must be empty")
            try:
                value = raw.decode("utf-8")
            except UnicodeError:
                value = None
        else:
            value = pointer(value, ref["pointer"])
        start, end = ref["start"], ref["end"]
        require(
            (start is None) == (end is None),
            "source offsets must both be null or integers",
        )
        if start is not None:
            require(
                isinstance(value, str) and 0 <= start < end <= len(value),
                "invalid source text range",
            )


def validate_review(
    context: TrustContext,
    *,
    review_key: str = "semantic_scope_review",
    receipt_key: str = "semantic_scope_operation_receipt",
    frozen_lesson_ids: Sequence[str],
    pipeline_run_id: str,
) -> dict[str, Any]:
    inventory = context.inventory
    review = checked(inventory.raw(review_key), "semantic-scope-review")
    require(
        review["review_fingerprint"] == review_fingerprint(review),
        "review fingerprint mismatch",
    )
    require(review["pipeline_run_id"] == pipeline_run_id, "review run ID mismatch")
    require(stamp(review["reviewed_at"]) <= context.now, "review completion in future")
    ids = [r["lesson_id"] for r in review["lessons"]]
    require(
        len(frozen_lesson_ids) == len(set(frozen_lesson_ids))
        and bool(frozen_lesson_ids),
        "invalid frozen Lesson list",
    )
    require(
        ids == list(frozen_lesson_ids),
        "missing/duplicate/unknown/out-of-order Lesson coverage",
    )
    issues = [i for row in review["lessons"] for i in row["issues"]]
    issue_ids = [i["issue_id"] for i in issues]
    require(len(issue_ids) == len(set(issue_ids)), "duplicate course issue IDs")
    for row in review["lessons"]:
        require(
            row["disposition"]
            == derive_disposition([i["disposition"] for i in row["issues"]]),
            "Lesson disposition forgery",
        )
        for issue in row["issues"]:
            require(
                issue["category"] != "ambiguous_scope"
                or issue["disposition"] == "HUMAN_REVIEW_REQUIRED",
                "ambiguity must escalate",
            )
    require(
        review["whole_course_disposition"]
        == derive_disposition([r["disposition"] for r in review["lessons"]]),
        "whole-course disposition forgery",
    )
    content = parse(inventory.raw("content", review["content_sha256"]))
    outline = parse(inventory.raw("outline", review["outline_sha256"]))
    manifest = parse(
        inventory.raw("source_truth_manifest", review["source_truth_manifest_sha256"])
    )
    manifest_path = inventory.entries["source_truth_manifest"]["path"]
    errors = validate_source_truth_payload(
        manifest, manifest_path=manifest_path, verify_source_bytes=True
    )
    if errors:
        raise StaleEvidence("unverified Source Truth closure: " + "; ".join(errors))
    require(
        content["content_contract_version"] == review["content_contract_version"],
        "Content version mismatch",
    )
    require(
        content["authoring_provenance"]["authoring_id"] == review["authoring_id"],
        "authoring ID mismatch",
    )
    require(
        [l["lesson_id"] for l in content["lessons"]] == ids,
        "Content Lesson coverage mismatch",
    )
    require(
        [l["lesson_id"] for l in outline] == ids,
        "frozen outline Lesson coverage mismatch",
    )
    require(
        canonical_json_bytes(content["outline"]) == canonical_json_bytes(outline),
        "Content outline differs from frozen outline",
    )
    for field in ("course_name", "major", "audience"):
        require(
            content[field] == manifest["course_identity"][field],
            "course identity mismatch",
        )
    sources: dict[str, tuple[dict[str, Any], bytes]] = {}
    from pathlib import Path

    for source in manifest["sources"]:
        raw = inventory.by_sha(source["sha256"])
        source_path = (Path(manifest_path).parent / source["locator"]).resolve(
            strict=True
        )
        require(
            any(
                Path(row["path"]).resolve(strict=True) == source_path
                for row in inventory.entries.values()
            ),
            "source missing inventory path",
        )
        sources[source["source_id"]] = (source, raw)
    outlines = [
        s for s in manifest["sources"] if s["source_type"] == "whole_course_outline"
    ]
    require(
        len(outlines) == 1 and outlines[0]["sha256"] == review["outline_sha256"],
        "outline source digest mismatch",
    )
    config = validate_configuration(inventory)
    if review["reviewer"]["configuration_sha256"] != sha256_bytes(
        inventory.raw("reviewer_configuration")
    ):
        raise StaleEvidence("review config stale")
    for rfield, cfield in (
        ("type", "reviewer_type"),
        ("implementation", "implementation"),
        ("version", "version"),
    ):
        require(
            review["reviewer"][rfield] == config[cfield],
            "reviewer configuration identity mismatch",
        )
    for row, lesson in zip(review["lessons"], content["lessons"]):
        _references(row["source_references"], sources)
        for issue in row["issues"]:
            loc = issue["location"]
            value = pointer(lesson, loc["field"])
            if isinstance(value, list):
                require(
                    loc["index"] is not None and loc["index"] < len(value),
                    "issue array index required",
                )
                value = value[loc["index"]]
            else:
                require(loc["index"] is None, "scalar location prohibits array index")
            require(
                isinstance(value, str) and 0 <= loc["start"] < loc["end"] <= len(value),
                "invalid issue string/range",
            )
            require(
                value[loc["start"] : loc["end"]] == issue["bounded_excerpt"],
                "issue excerpt does not equal located text",
            )
            _references(issue["source_references"], sources)
    receipt = validate_receipt(
        context, receipt_key, expected_kind="semantic_scope", subject_key=review_key
    )
    if review["review_purpose"] == "production_candidate":
        require(
            review["reviewer"]["qualification_sha256"] is not None,
            "production review needs qualification",
        )
        inventory.raw(
            "reviewer_qualification",
            review["reviewer"]["qualification_sha256"],
            protected=True,
        )
        from reviewer_qualification import validate_qualification

        qualification = validate_qualification(
            context,
            candidate_principal=review["reviewer"]["identity"],
            author_principal=receipt["author_principal"],
        )
        require(qualification["disposition"] == "QUALIFIED", "reviewer NOT_QUALIFIED")
        if config["configuration_version"] == "1.1":
            require(
                qualification["contract_version"] == "1.1",
                "managed production review needs managed qualification 1.1",
            )
            observation_binding = receipt["input_bindings"][
                "managed_service_observation"
            ]
            observation = validate_managed_service_observation(
                inventory,
                observation_binding["inventory_key"],
                observation_binding["sha256"],
                config,
                receipt["operation_id"],
                now=context.now,
            )
            require(
                managed_service_identity_fingerprint(observation)
                == qualification["service_identity_fingerprint"],
                "production service identity changed since qualification",
            )
    else:
        require(
            review["reviewer"]["qualification_sha256"] is None,
            "evaluation cannot bind qualification",
        )
    return review


@dataclass(frozen=True)
class ValidationResult:
    status: str
    errors: tuple[str, ...] = ()


def review_status(context: TrustContext, **kwargs: Any) -> ValidationResult:
    """Reread all files and current operator policy; historical evidence is retained."""
    try:
        validate_review(context, **kwargs)
    except StaleEvidence as exc:
        return ValidationResult("STALE", (str(exc),))
    except (RecordError, ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        return ValidationResult("INVALID", (str(exc),))
    return ValidationResult("VALID")
