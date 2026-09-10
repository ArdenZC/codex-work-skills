"""Detect research gaps and select supplementary sources without merging provenance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from orchestrator_core import dump_json, load_json


GAP_TYPES = {
    "missing_visual",
    "weak_example",
    "missing_worked_example",
    "outdated_tool_instruction",
    "weak_exercise",
    "missing_misconception",
    "missing_real_case",
    "unclear_definition",
    "missing_comparison",
    "insufficient_practice_material",
}

AUTHORITY_RANK = {
    "official": 4,
    "standard": 4,
    "official-documentation": 4,
    "university-course": 3,
    "academic": 3,
    "professional": 2,
    "community": 1,
}


def detect_gaps(graph: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    assets = inventory.get("assets", [])
    gaps: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        node_id = str(node.get("id"))
        related = [asset for asset in assets if node_id in asset.get("candidate_topics", []) or node_id in asset.get("candidate_knowledge_ids", [])]
        if not any(asset.get("type") in {"diagram", "screenshot", "table", "comparison"} and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-visual", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "missing_visual", "priority": "high"})
        if not any(asset.get("type") in {"worked_example", "case"} and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-example", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "weak_example", "priority": "medium"})
    return gaps


def _score(candidate: dict[str, Any]) -> tuple[float, float, float, float]:
    authority = candidate.get("authority_level", candidate.get("authority", "community"))
    rank = AUTHORITY_RANK.get(str(authority).lower(), 0)
    return (
        float(rank),
        float(candidate.get("relevance", 0) or 0),
        float(candidate.get("student_level_fit", 0) or 0),
        float(candidate.get("teaching_value", candidate.get("visual_value", 0)) or 0),
    )


def _candidate_allowed(candidate: dict[str, Any]) -> tuple[bool, str]:
    if not str(candidate.get("source_url") or candidate.get("url") or "").strip():
        return False, "missing source URL"
    if float(candidate.get("relevance", 0) or 0) < 0.5:
        return False, "relevance below 0.5"
    if float(candidate.get("student_level_fit", 0) or 0) < 0.5:
        return False, "student-level fit below 0.5"
    if float(candidate.get("complexity", 0) or 0) > 0.85:
        return False, "complexity exceeds course scope"
    return True, ""


def _origin_for(candidate: dict[str, Any]) -> str:
    authority = str(candidate.get("authority_level", candidate.get("authority", "community"))).lower()
    if authority in {"official", "standard", "official-documentation"}:
        return "web_official"
    if authority in {"university-course", "academic"}:
        return "web_academic"
    if authority == "professional":
        return "web_professional"
    return "web_community"


def _conflicts(user_facts: list[dict[str, Any]], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(fact.get("canonical_key") or fact.get("id")): fact for fact in user_facts if fact.get("canonical_key") or fact.get("id")}
    conflicts: list[dict[str, Any]] = []
    for candidate in selected:
        claims = candidate.get("claims", [])
        if isinstance(claims, dict):
            claims = [{"canonical_key": key, "claim": value} for key, value in claims.items()]
        for claim in claims if isinstance(claims, list) else []:
            key = str(claim.get("canonical_key") or claim.get("fact_id") or "")
            user = by_key.get(key)
            if not user or str(user.get("claim") or user.get("statement")) == str(claim.get("claim") or claim.get("statement")):
                continue
            conflict_type = "SOURCE_VERSION_CONFLICT" if candidate.get("supersedes_user_version") and _score(candidate)[0] >= 4 else "UNRESOLVED_SOURCE_CONFLICT"
            conflicts.append({
                "code": conflict_type,
                "canonical_key": key,
                "user_claim": user.get("claim", user.get("statement")),
                "external_claim": claim.get("claim", claim.get("statement")),
                "source_url": candidate.get("source_url", candidate.get("url")),
                "action": "keep both claims with provenance; require teacher decision",
            })
    return conflicts


def research(
    gaps: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    enabled: bool = True,
    network_available: bool = True,
    max_per_gap: int = 3,
    user_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    if not enabled:
        return {
            "schema_version": "1.0",
            "research_status": "EXTERNAL_RESEARCH_DISABLED_BY_USER",
            "retrieved_at": timestamp,
            "research_gaps": gaps,
            "sources": [],
            "conflicts": [],
            "provenance_policy": "user-provided sources remain primary; no external candidates were considered",
        }
    if not network_available:
        return {
            "schema_version": "1.0",
            "research_status": "EXTERNAL_RESEARCH_UNAVAILABLE",
            "retrieved_at": timestamp,
            "research_gaps": gaps,
            "sources": [],
            "conflicts": [],
            "provenance_policy": "continue with user-provided sources; external research was not available",
        }

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for gap in gaps:
        matching = [candidate for candidate in candidates if str(gap.get("id")) in candidate.get("gap_ids", []) or str(gap.get("type")) in candidate.get("used_for", []) or str(gap.get("topic")) in candidate.get("topics", [])]
        matching.sort(key=_score, reverse=True)
        accepted = 0
        for candidate in matching:
            allowed, reason = _candidate_allowed(candidate)
            record = {
                "query": candidate.get("query"),
                "source_url": candidate.get("source_url", candidate.get("url")),
                "source_title": candidate.get("source_title", candidate.get("title")),
                "source_type": candidate.get("source_type"),
                "authority_level": candidate.get("authority_level", candidate.get("authority", "community")),
                "used_for": candidate.get("used_for", [gap.get("type")]),
                "gap_ids": candidate.get("gap_ids", [gap.get("id")]),
                "selected": False,
                "selection_reason": reason,
                "origin": _origin_for(candidate),
                "origin_type": "external-authoritative" if _score(candidate)[0] >= 4 else "external-reference",
                "retrieved_at": candidate.get("retrieved_at", timestamp),
                "license_note": candidate.get("license_note"),
                "claims": candidate.get("claims", []),
            }
            if not allowed:
                rejected.append(record)
                continue
            if accepted >= max_per_gap:
                record["selection_reason"] = "per-gap research budget exhausted"
                rejected.append(record)
                continue
            record["selected"] = True
            record["selection_reason"] = "passed scope/authority/teaching-value filter"
            selected.append(record)
            accepted += 1
    return {
        "schema_version": "1.0",
        "research_status": "completed",
        "retrieved_at": timestamp,
        "research_gaps": gaps,
        "sources": selected + rejected,
        "selected_source_count": len(selected),
        "rejected_source_count": len(rejected),
        "conflicts": _conflicts(user_facts or [], selected),
        "provenance_policy": "user materials define the course; high-quality external sources enrich it and never silently replace it",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaps-json", required=True)
    parser.add_argument("--candidates-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--user-facts-json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    user_facts = load_json(args.user_facts_json) if args.user_facts_json else []
    result = research(load_json(args.gaps_json), load_json(args.candidates_json), enabled=not args.disabled, network_available=not args.offline, user_facts=user_facts)
    dump_json(result, args.output_json)
    if args.json:
        print({"status": result["research_status"], "selected": result.get("selected_source_count", 0), "gaps": len(result["research_gaps"])})


if __name__ == "__main__":
    main()
