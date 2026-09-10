"""Resolve source-backed research gaps and preserve provenance trust states."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from orchestrator_core import dump_json, jaccard, load_json, tokenise


GAP_TYPES = {
    "missing_visual", "weak_example", "missing_worked_example", "outdated_tool_instruction", "weak_exercise",
    "missing_misconception", "missing_real_case", "unclear_definition", "missing_comparison", "insufficient_practice_material",
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

AUTHORITY_STATUS_RANK = {
    "VERIFIED_OFFICIAL": 4,
    "VERIFIED_ACADEMIC": 3,
    "ASSESSED_REFERENCE": 2,
    "UNVERIFIED_OFFICIAL_CLAIM": 1,
    "UNKNOWN": 0,
}

VERIFICATION_BASES = {
    "trusted publisher/domain identity",
    "trusted_publisher_domain",
    "trusted-domain-mapping",
    "well-known-official-domain",
    "explicit-source-registry",
    "manual-verified-metadata",
    "host-verified-publisher",
}


def _asset_is_visual(asset: dict[str, Any]) -> bool:
    return asset.get("type") in {"diagram", "screenshot", "table", "comparison", "image"} or bool(asset.get("shape_graph") or asset.get("rendered_visual_ref"))


def _relation_for(asset: dict[str, Any]) -> str:
    return {
        "definition": "defines",
        "diagram": "illustrates",
        "image": "illustrates",
        "screenshot": "illustrates",
        "worked_example": "demonstrates",
        "case": "demonstrates",
        "exercise": "exercises",
    }.get(str(asset.get("type")), "supports")


def resolve_asset_knowledge_links(graph: dict[str, Any], inventory: dict[str, Any], explicit: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve asset-to-node links without matching a node id to free text.

    Explicit source links win. When they are absent, the fallback uses node
    titles and asset text with a recorded confidence and origin. In
    particular, ``candidate_topics`` is never treated as a node-id lookup.
    """

    assets = {str(item.get("id")): item for item in inventory.get("assets", []) if isinstance(item, dict) and item.get("id")}
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict) and item.get("id")]
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in explicit or []:
        asset_id = str(record.get("asset_id") or "")
        node_id = str(record.get("knowledge_node_id") or record.get("node_id") or "")
        if asset_id in assets and node_id in {str(node.get("id")) for node in nodes} and (asset_id, node_id) not in seen:
            link = dict(record)
            link.update({"asset_id": asset_id, "knowledge_node_id": node_id, "origin": record.get("origin", "agent-explicit")})
            links.append(link)
            seen.add((asset_id, node_id))
    for node in nodes:
        node_id = str(node["id"])
        for asset_id in node.get("source_assets", []) or []:
            asset_id = str(asset_id)
            if asset_id not in assets or (asset_id, node_id) in seen:
                continue
            links.append({"asset_id": asset_id, "knowledge_node_id": node_id, "relation": _relation_for(assets[asset_id]), "confidence": 1.0, "origin": "course-map-source-assets"})
            seen.add((asset_id, node_id))
    for asset_id, asset in assets.items():
        explicit_nodes = asset.get("knowledge_node_ids") or asset.get("candidate_knowledge_ids")
        for node_id in explicit_nodes or []:
            node_id = str(node_id)
            if node_id not in {str(node.get("id")) for node in nodes} or (asset_id, node_id) in seen:
                continue
            links.append({"asset_id": asset_id, "knowledge_node_id": node_id, "relation": _relation_for(asset), "confidence": 0.95, "origin": "asset-explicit"})
            seen.add((asset_id, node_id))
    for node in nodes:
        node_tokens = set(tokenise(node.get("title")))
        if not node_tokens:
            continue
        for asset_id, asset in assets.items():
            if (asset_id, str(node["id"])) in seen:
                continue
            asset_text = f"{asset.get('title', '')} {asset.get('raw_text', '')}"
            confidence = jaccard(node_tokens, set(tokenise(asset_text)))
            if confidence >= 0.25:
                links.append({"asset_id": asset_id, "knowledge_node_id": str(node["id"]), "relation": _relation_for(asset), "confidence": round(confidence, 4), "origin": "title-semantic-matching"})
                seen.add((asset_id, str(node["id"])))
    return {
        "schema_version": "1.1",
        "link_type": "asset_knowledge_links",
        "links": links,
        "resolution_policy": "agent explicit mapping, course-map source_assets, then recorded title/text matching; free-text candidate_topics never maps a node id directly",
    }


def detect_gaps(graph: dict[str, Any], inventory: dict[str, Any], asset_knowledge_links: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    assets = {str(item.get("id")): item for item in inventory.get("assets", []) if isinstance(item, dict) and item.get("id")}
    links = asset_knowledge_links or resolve_asset_knowledge_links(graph, inventory)
    by_node: dict[str, set[str]] = {}
    for link in links.get("links", []):
        by_node.setdefault(str(link.get("knowledge_node_id")), set()).add(str(link.get("asset_id")))
    gaps: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        node_id = str(node.get("id"))
        related_ids = set(str(item) for item in node.get("source_assets", []) or []) | by_node.get(node_id, set())
        related = [assets[item] for item in related_ids if item in assets]
        if not any(_asset_is_visual(asset) and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-visual", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "missing_visual", "priority": "high", "evidence": {"related_asset_ids": sorted(related_ids)}})
        if not any(asset.get("type") in {"worked_example", "case"} and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-example", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "weak_example", "priority": "medium", "evidence": {"related_asset_ids": sorted(related_ids)}})
        if not any(asset.get("type") == "comparison" and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-comparison", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "missing_comparison", "priority": "medium", "evidence": {"related_asset_ids": sorted(related_ids)}})
        if not any(asset.get("type") in {"exercise", "question"} and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-exercise", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "weak_exercise", "priority": "medium", "evidence": {"related_asset_ids": sorted(related_ids)}})
        if not any(asset.get("type") == "misconception" and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-misconception", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "missing_misconception", "priority": "medium", "evidence": {"related_asset_ids": sorted(related_ids)}})
        if not node.get("practice_dependencies") and not any(asset.get("type") in {"exercise", "worked_example", "case"} and asset.get("teaching_value") != "low-value" for asset in related):
            gaps.append({"id": f"gap-{node_id}-practice", "topic": node.get("title"), "knowledge_node_id": node_id, "type": "insufficient_practice_material", "priority": "medium", "evidence": {"related_asset_ids": sorted(related_ids)}})
    return gaps


def _url_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    url = str(candidate.get("source_url") or candidate.get("url") or "").strip()
    parsed = urlparse(url)
    observed = candidate.get("verified_metadata") or candidate.get("observed_metadata") or {}
    metadata = dict(observed) if isinstance(observed, dict) else {}
    if parsed.netloc and "domain" not in metadata:
        metadata["domain"] = parsed.netloc.lower()
        metadata.setdefault("domain_observation", "url-parser-only")
    if url and "url" not in metadata:
        metadata["url"] = url
    return metadata


def _authority_status(candidate: dict[str, Any], metadata: dict[str, Any]) -> tuple[str, str]:
    claimed = str(candidate.get("authority_level", candidate.get("authority", "community"))).lower()
    evidence = candidate.get("authority_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    publisher = metadata.get("publisher") or metadata.get("issuer") or candidate.get("publisher") or candidate.get("issuer") or evidence.get("publisher") or evidence.get("issuer")
    source_type = metadata.get("source_type") or candidate.get("source_type") or evidence.get("source_type")
    publisher_kind = str(metadata.get("publisher_kind") or metadata.get("publisher_type") or evidence.get("publisher_kind") or "").lower()
    basis = str(metadata.get("verification_basis") or evidence.get("verification_basis") or candidate.get("verification_basis") or "").strip().lower()
    trusted = bool(
        candidate.get("verified_identity") is True
        or evidence.get("verified_identity") is True
        or metadata.get("verified_identity") is True
        or basis in VERIFICATION_BASES
        or basis.replace("_", "-") in VERIFICATION_BASES
        or evidence.get("trusted_domain_mapping")
        or candidate.get("trusted_domain_mapping")
        or metadata.get("trusted_domain_mapping")
    )
    # A URL-derived domain is observed locator metadata, not an identity
    # assertion.  Only an explicit publisher/issuer plus a trusted basis can
    # upgrade a candidate to verified identity.
    if claimed in {"official", "standard", "official-documentation"}:
        if trusted and publisher and (metadata.get("domain") or evidence.get("domain")):
            return "VERIFIED_OFFICIAL", "publisher/domain identity is backed by an explicit trusted verification basis"
        return "UNVERIFIED_OFFICIAL_CLAIM", "official authority is only a candidate claim; URL/domain presence is not identity verification"
    if claimed in {"university-course", "academic"} or publisher_kind in {"university", "academic", "higher-education"}:
        if trusted and publisher:
            return "VERIFIED_ACADEMIC", "publisher metadata identifies an academic source and trusted verification evidence is present"
        if publisher and source_type in {"university-course", "academic-paper", "university-publication"} and trusted:
            return "VERIFIED_ACADEMIC", "academic source type and trusted publisher metadata are present"
        return "ASSESSED_REFERENCE", "academic authority is an assessment without verified issuer identity"
    if claimed in {"professional", "community", "reference", "unknown"} or not claimed:
        return "ASSESSED_REFERENCE" if publisher or source_type else "UNKNOWN", "source remains a reference; no official identity was verified"
    return "ASSESSED_REFERENCE", "authority is retained as an assessed reference and is not treated as official identity"


def _score(candidate: dict[str, Any]) -> tuple[float, float, float, float]:
    metadata = _url_metadata(candidate)
    authority_status, _ = _authority_status(candidate, metadata)
    rank = AUTHORITY_STATUS_RANK.get(authority_status, 0)
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


def _origin_for(candidate: dict[str, Any], authority_status: str | None = None) -> str:
    status = authority_status or _authority_status(candidate, _url_metadata(candidate))[0]
    authority = str(candidate.get("authority_level", candidate.get("authority", "community"))).lower()
    if status == "VERIFIED_OFFICIAL":
        return "web_official"
    if status == "VERIFIED_ACADEMIC":
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
            conflicts.append({"code": conflict_type, "canonical_key": key, "user_claim": user.get("claim", user.get("statement")), "external_claim": claim.get("claim", claim.get("statement")), "source_url": candidate.get("source_url", candidate.get("url")), "action": "keep both claims with provenance; require teacher decision"})
    return conflicts


def _record_candidate(candidate: dict[str, Any], gap: dict[str, Any], timestamp: str, *, selected: bool, reason: str) -> dict[str, Any]:
    metadata = _url_metadata(candidate)
    authority_status, authority_reason = _authority_status(candidate, metadata)
    return {
        "query": candidate.get("query"),
        "source_url": candidate.get("source_url", candidate.get("url")),
        "source_title": candidate.get("source_title", candidate.get("title")),
        "source_type": candidate.get("source_type"),
        "authority_level": candidate.get("authority_level", candidate.get("authority", "community")),
        "authority_status": authority_status,
        "authority_status_reason": authority_reason,
        "used_for": candidate.get("used_for", [gap.get("type")]),
        "gap_ids": candidate.get("gap_ids", [gap.get("id")]),
        "selected": selected,
        "selection_reason": reason,
        "origin": _origin_for(candidate, authority_status),
        "origin_type": "external-authoritative" if authority_status in {"VERIFIED_OFFICIAL", "VERIFIED_ACADEMIC"} else "external-reference",
        "retrieved_at": candidate.get("retrieved_at", timestamp),
        "license_note": candidate.get("license_note"),
        "claims": candidate.get("claims", []),
        "verified_metadata": metadata,
        "agent_assessment": {
            "relevance": candidate.get("relevance"),
            "teaching_value": candidate.get("teaching_value", candidate.get("visual_value")),
            "student_level_fit": candidate.get("student_level_fit"),
            "complexity": candidate.get("complexity"),
            "evidence_origin": "agent-assessment",
        },
        "evidence_origin": {
            "authority_level": "candidate-claim",
            "authority_status": authority_status,
            "trust_layers": {
                "candidate_claim": candidate.get("authority_level", candidate.get("authority")),
                "observed_metadata": metadata if metadata else None,
                "verified_identity": authority_status in {"VERIFIED_OFFICIAL", "VERIFIED_ACADEMIC"},
            },
        },
    }


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
    if not gaps:
        return {
            "schema_version": "1.1",
            "research_status": "USER_SOURCE_SUFFICIENT",
            "retrieved_at": timestamp,
            "research_gaps": [],
            "sources": [],
            "selected_source_count": 0,
            "rejected_source_count": 0,
            "conflicts": [],
            "search_performed": False,
            "provenance_policy": "user materials contain the required evidence; no external search is necessary",
        }
    if not enabled:
        return {
            "schema_version": "1.1",
            "research_status": "EXTERNAL_RESEARCH_DISABLED_BY_USER",
            "retrieved_at": timestamp,
            "research_gaps": gaps,
            "sources": [],
            "selected_source_count": 0,
            "rejected_source_count": 0,
            "conflicts": [],
            "search_performed": False,
            "provenance_policy": "user-provided sources remain primary; no external candidates were considered",
        }
    if not network_available:
        return {
            "schema_version": "1.1",
            "research_status": "EXTERNAL_RESEARCH_UNAVAILABLE",
            "retrieved_at": timestamp,
            "research_gaps": gaps,
            "sources": [],
            "selected_source_count": 0,
            "rejected_source_count": 0,
            "conflicts": [],
            "search_performed": False,
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
            if _authority_status(candidate, _url_metadata(candidate))[0] == "UNVERIFIED_OFFICIAL_CLAIM":
                reason = (reason + "; " if reason else "") + "authority claim is unverified; retained as reference only"
            record = _record_candidate(candidate, gap, timestamp, selected=False, reason=reason)
            if not allowed:
                rejected.append(record)
                continue
            if accepted >= max_per_gap:
                record["selection_reason"] = "per-gap research budget exhausted"
                rejected.append(record)
                continue
            record["selected"] = True
            record["selection_reason"] = "passed scope/authority/teaching-value filter; authority trust is recorded separately"
            selected.append(record)
            accepted += 1
    return {
        "schema_version": "1.1",
        "research_status": "COMPLETED",
        "retrieved_at": timestamp,
        "research_gaps": gaps,
        "sources": selected + rejected,
        "selected_source_count": len(selected),
        "rejected_source_count": len(rejected),
        "conflicts": _conflicts(user_facts or [], selected),
        "search_performed": True,
        "authority_trust_model": {
            "layers": ["CLAIMED", "OBSERVED_METADATA", "VERIFIED_IDENTITY"],
            "statuses": sorted(AUTHORITY_STATUS_RANK),
            "policy": "URL/domain presence is observed metadata only; official or academic rank requires explicit trusted publisher identity evidence",
        },
        "provenance_policy": "user materials define the course; high-quality external sources enrich it and never silently replace it",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaps-json", required=True)
    parser.add_argument("--candidates-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--asset-links-json")
    parser.add_argument("--knowledge-graph-json")
    parser.add_argument("--assets-json")
    parser.add_argument("--write-asset-links")
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--user-facts-json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    user_facts = load_json(args.user_facts_json) if args.user_facts_json else []
    result = research(load_json(args.gaps_json), load_json(args.candidates_json), enabled=not args.disabled, network_available=not args.offline, user_facts=user_facts)
    dump_json(result, args.output_json)
    if args.write_asset_links:
        if not args.knowledge_graph_json or not args.assets_json:
            parser.error("--write-asset-links requires --knowledge-graph-json and --assets-json")
        dump_json(resolve_asset_knowledge_links(load_json(args.knowledge_graph_json), load_json(args.assets_json)), args.write_asset_links)
    if args.json:
        print({"status": result["research_status"], "selected": result.get("selected_source_count", 0), "gaps": len(result["research_gaps"])})


if __name__ == "__main__":
    main()
