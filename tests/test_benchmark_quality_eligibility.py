"""SYNTHETIC fixtures prove contract closure, never teaching quality."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_lesson_exemplar_benchmark import (
    SCRIPTS, make_card, make_catalog, refresh_catalog_fingerprint,
)
from exemplar_contract import ContractError, build_exemplar_pack, source_identity_sha256
from exemplar_split import build_split, validate_split_payload
import benchmark_quality_eligibility as quality


def reference(card, field, index=0):
    value = card
    for part in field.split("."):
        value = value[part]
    if isinstance(value, list):
        value = value[index]
    else:
        index = None
    return {"exemplar_id": card["exemplar_id"], "field": field,
            "item_index": index, "value_sha256": quality.evidence_value_fingerprint(value)}


def reviewed_records(catalog, decision="QUALITY_ELIGIBLE"):
    """Explicit fabricated judgments; builder itself supplies no judgments."""
    cards = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    rows = []
    for group, ids in quality.candidate_groups(catalog).items():
        card = cards[sorted(ids)[0]]
        row = {"group_id": group, "qualified_exemplar_ids": sorted(ids),
               "decision": decision, "rationale": "SYNTHETIC contract fixture only."}
        for dimension, status, field in (
            ("authority_excellence_basis", "SUPPORTED", "source.recognition_evidence"),
            ("course_relevance", "DIRECT_MATCH", "scope.course"),
            ("learner_relevance", "MATCH", "scope.learner_profile"),
            ("teaching_context_relevance", "MATCH", "scope.teaching_context"),
            ("pattern_evidence", "SUFFICIENT", "design_patterns"),
            ("transferability", "SUFFICIENT", "design_patterns"),
        ):
            row[dimension] = {"status": status, "rationale": "SYNTHETIC explicit rationale, no quality claim.",
                              "evidence_refs": [reference(card, field)]}
        rows.append(row)
    return rows


class BenchmarkQualityEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(6, cards_per_group=2, nonqualified_count=1)
        self.rows = reviewed_records(self.catalog)
        self.manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        self.split = build_split(self.catalog)

    def errors(self, manifest=None, catalog=None, *, rehash=True):
        manifest = copy.deepcopy(self.manifest if manifest is None else manifest)
        if rehash:
            manifest["eligibility_fingerprint"] = quality.quality_eligibility_fingerprint(manifest)
        return quality.validate_quality_eligibility_payload(manifest, self.catalog if catalog is None else catalog)

    def test_structural_qualified_does_not_automatically_grant_quality(self):
        with self.assertRaises(ContractError):
            quality.build_quality_eligibility(self.catalog, [])
        row = self.manifest["groups"][0]
        row["authority_excellence_basis"]["evidence_refs"] = []
        self.assertTrue(self.errors())  # Tier A is insufficient by itself.

    def test_tier_c_cannot_be_quality_eligible(self):
        self.catalog["exemplars"][0]["source"]["authority_tier"] = "C"
        refresh_catalog_fingerprint(self.catalog)
        self.assertTrue(self.errors())

    def test_discovery_source_cannot_be_quality_eligible(self):
        self.catalog["exemplars"][0]["source"]["source_type"] = "discovery_source"
        refresh_catalog_fingerprint(self.catalog)
        self.assertTrue(self.errors())

    def test_structural_conditional_cannot_be_upgraded(self):
        self.catalog["exemplars"][0]["qualification"]["status"] = "CONDITIONAL"
        refresh_catalog_fingerprint(self.catalog)
        self.manifest["catalog_fingerprint"] = self.catalog["catalog_fingerprint"]
        self.assertTrue(self.errors())

    def test_missing_group_rejected(self):
        self.manifest["groups"].pop()
        self.assertTrue(self.errors())

    def test_extra_and_duplicate_group_rejected(self):
        for group in ("NONEXISTENT", self.manifest["groups"][0]["group_id"]):
            with self.subTest(group=group):
                altered = copy.deepcopy(self.manifest)
                row = copy.deepcopy(altered["groups"][0])
                row["group_id"] = group
                altered["groups"].append(row)
                self.assertTrue(self.errors(altered))

    def test_missing_qualified_card_rejected(self):
        self.manifest["groups"][0]["qualified_exemplar_ids"].pop()
        self.assertTrue(self.errors())

    def test_nonqualified_and_other_group_cards_rejected(self):
        for status in ("CONDITIONAL", "REJECTED", "DISCOVERY_ONLY", "other_group"):
            with self.subTest(status=status):
                catalog = copy.deepcopy(self.catalog)
                manifest = copy.deepcopy(self.manifest)
                card = catalog["exemplars"][-1]
                if status != "other_group":
                    card["qualification"]["status"] = status
                else:
                    card = catalog["exemplars"][2]
                refresh_catalog_fingerprint(catalog)
                manifest["catalog_fingerprint"] = catalog["catalog_fingerprint"]
                manifest["groups"][0]["qualified_exemplar_ids"].append(card["exemplar_id"])
                self.assertTrue(self.errors(manifest, catalog))

    def test_wrong_exemplar_reference_rejected(self):
        for exemplar in ("NO-SUCH-CARD", self.catalog["exemplars"][2]["exemplar_id"], self.catalog["exemplars"][-1]["exemplar_id"]):
            self.manifest["groups"][0]["pattern_evidence"]["evidence_refs"][0]["exemplar_id"] = exemplar
            self.assertTrue(self.errors())

    def test_illegal_evidence_field_rejected(self):
        self.manifest["groups"][0]["pattern_evidence"]["evidence_refs"][0]["field"] = "source.authority_tier"
        self.assertTrue(self.errors())

    def test_out_of_bounds_negative_and_null_list_index_rejected(self):
        for index in (999, -1, None):
            self.manifest["groups"][0]["pattern_evidence"]["evidence_refs"][0]["item_index"] = index
            self.assertTrue(self.errors())

    def test_scalar_index_and_blank_evidence_rejected(self):
        self.manifest["groups"][0]["course_relevance"]["evidence_refs"][0]["item_index"] = 0
        self.assertTrue(self.errors())
        catalog = copy.deepcopy(self.catalog)
        catalog["exemplars"][0]["design_patterns"][0] = "   "
        refresh_catalog_fingerprint(catalog)
        self.assertTrue(self.errors(catalog=catalog))

    def test_catalog_fingerprint_and_identity_mismatch_rejected(self):
        for field, value in (("catalog_fingerprint", "f" * 64), ("catalog_id", "another"),
                             ("qualification_policy_version", "future"), ("quality_policy_version", "future")):
            manifest = copy.deepcopy(self.manifest)
            manifest[field] = value
            self.assertTrue(self.errors(manifest))

    def test_catalog_changed_invalidates_old_manifest(self):
        self.catalog["exemplars"][0]["design_patterns"][0] = "SYNTHETIC changed evidence"
        refresh_catalog_fingerprint(self.catalog)
        self.assertTrue(self.errors())
        self.manifest["catalog_fingerprint"] = self.catalog["catalog_fingerprint"]
        self.assertTrue(self.errors())  # Rebinding alone cannot conceal stale ref value.

    def test_course_mismatch_rejects_eligible(self):
        self.manifest["groups"][0]["course_relevance"]["status"] = "MISMATCH"
        self.assertTrue(self.errors())

    def test_learner_and_context_mismatch_or_insufficient_reject_eligible(self):
        for dimension in ("course_relevance", "learner_relevance", "teaching_context_relevance"):
            for status in ("MISMATCH", "INSUFFICIENT_EVIDENCE"):
                manifest = copy.deepcopy(self.manifest)
                manifest["groups"][0][dimension]["status"] = status
                self.assertTrue(self.errors(manifest))

    def test_insufficient_pattern_evidence_rejects_eligible(self):
        self.manifest["groups"][0]["pattern_evidence"]["status"] = "INSUFFICIENT"
        self.assertTrue(self.errors())

    def test_insufficient_transferability_rejects_eligible(self):
        self.manifest["groups"][0]["transferability"]["status"] = "INSUFFICIENT"
        self.assertTrue(self.errors())

    def test_transferable_with_evidence_and_rationale_passes(self):
        for dimension in ("course_relevance", "teaching_context_relevance"):
            self.manifest["groups"][0][dimension]["status"] = "TRANSFERABLE"
        self.manifest["groups"][0]["learner_relevance"]["status"] = "ADJACENT"
        self.assertEqual([], self.errors())
        for dimension in ("course_relevance", "teaching_context_relevance"):
            for field, value in (("evidence_refs", []), ("rationale", "   ")):
                manifest = copy.deepcopy(self.manifest)
                manifest["groups"][0][dimension][field] = value
                self.assertTrue(self.errors(manifest))

    def test_conditional_sidecar_is_legal_without_sufficient_evidence(self):
        for row in self.rows:
            row["decision"] = "CONDITIONAL"
            row["pattern_evidence"]["status"] = "INSUFFICIENT"
            row["pattern_evidence"]["evidence_refs"] = []
        manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        self.assertEqual([], self.errors(manifest))

    def test_conditional_fails_opt_in_quality_split(self):
        self.rows[0]["decision"] = "CONDITIONAL"
        manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        self.assertTrue(quality.validate_split_quality_eligibility(self.split, self.catalog, manifest))
        self.assertEqual([], validate_split_payload(self.split, self.catalog))

    def test_rejected_fails_quality_split(self):
        self.rows[0]["decision"] = "REJECTED"
        manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        self.assertTrue(quality.validate_split_quality_eligibility(self.split, self.catalog, manifest))

    def test_eligible_can_enter_split_with_both_packs(self):
        packs = {role: build_exemplar_pack(self.catalog, self.split, role) for role in ("authoring", "holdout")}
        self.assertEqual([], quality.validate_split_quality_eligibility(
            self.split, self.catalog, self.manifest,
            authoring_pack=packs["authoring"], holdout_pack=packs["holdout"],
        ))
        packs["holdout"]["exemplars"][0]["design_patterns"][0] = "tampered"
        self.assertTrue(quality.validate_split_quality_eligibility(
            self.split, self.catalog, self.manifest, holdout_pack=packs["holdout"],
        ))

    def test_a_pack_conditional_rejected(self):
        self.assert_pack_decision_rejected("authoring", "CONDITIONAL")

    def test_b_pack_rejected_rejected(self):
        self.assert_pack_decision_rejected("holdout", "REJECTED")

    def assert_pack_decision_rejected(self, role, decision):
        group = self.split[f"{role}_group_ids"][0]
        for row in self.rows:
            if row["group_id"] == group:
                row["decision"] = decision
        manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        pack = build_exemplar_pack(self.catalog, self.split, role)
        errors = quality.validate_split_quality_eligibility(self.split, self.catalog, manifest, **{f"{role}_pack": pack})
        self.assertTrue(any(role in error for error in errors), errors)

    def availability_with_counts(self, authoring, holdout):
        selected = set(self.split["authoring_group_ids"][:authoring] + self.split["holdout_group_ids"][:holdout])
        for row in self.rows:
            row["decision"] = "QUALITY_ELIGIBLE" if row["group_id"] in selected else "CONDITIONAL"
        manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        return quality.quality_aware_availability(self.split, self.catalog, manifest)

    def test_zero_quality_groups_unavailable(self):
        result = self.availability_with_counts(0, 0)
        self.assertEqual("UNAVAILABLE", result["benchmark_quality_availability"])
        self.assertEqual(0, result["authoring_quality_group_count"])

    def test_one_quality_group_partial(self):
        result = self.availability_with_counts(1, 1)
        self.assertEqual("PARTIAL", result["benchmark_quality_availability"])
        self.assertEqual("PARTIAL", result["authoring_quality_availability"])

    def test_sufficient_quality_groups_available(self):
        result = self.availability_with_counts(2, 2)
        self.assertEqual("AVAILABLE", result["benchmark_quality_availability"])
        self.assertEqual("AVAILABLE", result["authoring_quality_availability"])
        self.assertEqual(2, result["holdout_quality_group_count"])

    def test_empty_candidate_catalog_is_valid_unavailable(self):
        catalog = make_catalog(0, nonqualified_count=2)
        manifest = quality.build_quality_eligibility(catalog, [])
        result = quality.quality_aware_availability(build_split(catalog), catalog, manifest)
        self.assertEqual("UNAVAILABLE", result["benchmark_quality_availability"])

    def test_private_source_cannot_be_automatically_eligible(self):
        catalog = make_catalog(0)
        card = make_card(1, authority_tier="PRIVATE", visibility="private_session", source_type="private_user_provided")
        card["source"]["canonical_url"] = None
        card["source"]["provided_source_id"] = "SYNTHETIC private evidence"
        card["source"]["source_identity_sha256"] = source_identity_sha256(card)
        catalog["exemplars"] = [card]
        refresh_catalog_fingerprint(catalog)
        rows = reviewed_records(catalog)
        with self.assertRaisesRegex(ContractError, "private source"):
            quality.build_quality_eligibility(catalog, rows)
        rows[0]["decision"] = "CONDITIONAL"
        quality.build_quality_eligibility(catalog, rows)

    def test_group_order_does_not_change_fingerprint(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["groups"].reverse()
        self.assertEqual(self.manifest["eligibility_fingerprint"], quality.quality_eligibility_fingerprint(manifest))

    def test_exemplar_id_order_does_not_change_fingerprint(self):
        manifest = copy.deepcopy(self.manifest)
        for row in manifest["groups"]:
            row["qualified_exemplar_ids"].reverse()
        self.assertEqual(self.manifest["eligibility_fingerprint"], quality.quality_eligibility_fingerprint(manifest))

    def test_evidence_ref_order_does_not_change_fingerprint(self):
        for row in self.rows:
            card = next(card for card in self.catalog["exemplars"] if card["exemplar_id"] == row["qualified_exemplar_ids"][1])
            row["pattern_evidence"]["evidence_refs"].append(reference(card, "design_patterns"))
        manifest = quality.build_quality_eligibility(self.catalog, self.rows)
        modified = copy.deepcopy(manifest)
        modified["groups"].reverse()
        for row in modified["groups"]:
            row["pattern_evidence"]["evidence_refs"].reverse()
        self.assertEqual(manifest["eligibility_fingerprint"], quality.quality_eligibility_fingerprint(modified))

    def test_semantic_decision_and_rationale_change_fingerprint(self):
        for field in ("decision", "rationale"):
            modified = copy.deepcopy(self.manifest)
            modified["groups"][0][field] = "REJECTED" if field == "decision" else "Different SYNTHETIC rationale"
            self.assertNotEqual(self.manifest["eligibility_fingerprint"], quality.quality_eligibility_fingerprint(modified))

    def test_property_timestamp_self_fingerprint_order_do_not_matter(self):
        modified = dict(reversed(list(self.manifest.items())))
        modified["created_at"] = "2026-09-30T12:00:00+08:00"
        modified["eligibility_fingerprint"] = "f" * 64
        self.assertEqual(self.manifest["eligibility_fingerprint"], quality.quality_eligibility_fingerprint(modified))
        self.assertTrue(self.errors(modified, rehash=False))

    def test_fingerprint_uses_lifecycle_nfc_and_no_float(self):
        from lifecycle_digest import LifecycleContractError
        first = copy.deepcopy(self.manifest)
        second = copy.deepcopy(self.manifest)
        first["groups"][0]["rationale"] = "caf\u00e9"
        second["groups"][0]["rationale"] = "cafe\u0301"
        self.assertEqual(quality.quality_eligibility_fingerprint(first), quality.quality_eligibility_fingerprint(second))
        second["score"] = 80.5
        with self.assertRaises(LifecycleContractError):
            quality.quality_eligibility_fingerprint(second)

    def test_numeric_scores_unknown_fields_and_invalid_cards_rejected(self):
        self.manifest["groups"][0]["score"] = 80
        self.assertTrue(self.errors())
        self.catalog["exemplars"][0]["raw_source"] = "forbidden"
        with self.assertRaises(ContractError):
            quality.build_quality_eligibility(self.catalog, self.rows)

    def test_no_network_calls_for_build_validate_and_helpers(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch("urllib.request.urlopen", side_effect=AssertionError("HTTP forbidden")):
            manifest = quality.build_quality_eligibility(self.catalog, self.rows)
            self.assertEqual([], quality.validate_quality_eligibility_payload(manifest, self.catalog))
            self.assertEqual([], quality.validate_split_quality_eligibility(self.split, self.catalog, manifest))
            quality.quality_aware_availability(self.split, self.catalog, manifest)

    def test_cli_build_validate_tamper_and_alias_protection(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-quality-") as folder:
            root = Path(folder).resolve()
            catalog, records, output = (root / name for name in ("catalog.json", "records.json", "eligibility.json"))
            catalog.write_text(json.dumps(self.catalog), encoding="utf-8")
            records.write_text(json.dumps({"groups": self.rows}), encoding="utf-8")
            command = [sys.executable, "-B", str(SCRIPTS / "benchmark_quality_eligibility.py")]
            def run(*args):
                return subprocess.run([*command, *args], capture_output=True, text=True)
            result = run("build", "--catalog", str(catalog), "--records", str(records), "--output", str(output))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = run("validate", "--catalog", str(catalog), "--eligibility", str(output))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("offline", result.stdout)
            before = catalog.read_bytes()
            result = run("build", "--catalog", str(catalog), "--records", str(records), "--output", str(catalog))
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, catalog.read_bytes())
            output.write_text('{"groups":[]}', encoding="utf-8")
            self.assertNotEqual(0, run("validate", "--catalog", str(catalog), "--eligibility", str(output)).returncode)
            output.write_text("{ malformed", encoding="utf-8")
            self.assertNotEqual(0, run("validate", "--catalog", str(catalog), "--eligibility", str(output)).returncode)


if __name__ == "__main__":
    unittest.main()
