"""Synthetic judgments prove linkage and transaction behavior, never teaching quality."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_benchmark_quality_eligibility import reviewed_records
from tests.test_lesson_exemplar_benchmark import make_catalog, refresh_catalog_fingerprint
import benchmark_quality_eligibility as quality
import benchmark_preparation as prep
from exemplar_contract import ContractError, validate_catalog_payload
from exemplar_split import build_split


def inputs(directory, *, group_count=6, eligible=None, context=None):
    catalog = make_catalog(group_count, cards_per_group=2, nonqualified_count=1,
                           **(context or {}))
    for card in catalog["exemplars"]:
        card["transferable_principles"] = ["SYNTHETIC explicit transfer principle"]
    refresh_catalog_fingerprint(catalog)
    rows = reviewed_records(catalog)
    if eligible is not None:
        for row in rows:
            if row["group_id"] not in eligible:
                row["decision"] = "REJECTED"
    eligibility = quality.build_quality_eligibility(catalog, rows)
    paths = {name: Path(directory) / (name + ".json") for name in prep.ARTIFACT_NAMES}
    paths["preparation"] = Path(directory) / "benchmark-preparation.json"
    for name, payload in (("source_catalog", catalog), ("quality_eligibility", eligibility)):
        paths[name].write_bytes(prep.json_bytes(payload))
    return catalog, eligibility, paths


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.catalog, self.quality, self.paths = inputs(self.temp.name, eligible={"GR-00", "GR-02", "GR-04"})
        self.prepare()

    def prepare(self):
        return prep.prepare_benchmark(self.paths["preparation"], pipeline_run_id="RUN-001",
                                      **{k: v for k, v in self.paths.items() if k != "preparation"})

    def validate(self):
        return prep.validate_preparation_files(self.paths["preparation"],
                    **{k: v for k, v in self.paths.items() if k != "preparation"})[1]

    def alter(self, name, change):
        path = self.paths[name]
        payload = json.loads(path.read_bytes())
        change(payload)
        path.write_bytes(prep.json_bytes(payload))

    def test_only_quality_eligible_groups(self):
        projection = json.loads(self.paths["projected_catalog"].read_bytes())
        self.assertEqual({c["group_id"] for c in projection["exemplars"]}, {"GR-00", "GR-02", "GR-04"})

    def test_all_qualified_cards_in_each_eligible_group(self):
        projection = json.loads(self.paths["projected_catalog"].read_bytes())
        self.assertEqual(len(projection["exemplars"]), 6)
        for card in projection["exemplars"]:
            self.assertEqual(card, next(c for c in self.catalog["exemplars"] if c["exemplar_id"] == card["exemplar_id"]))

    def test_course_context_exact_and_different_deterministic_id(self):
        a = prep.project_catalog(self.catalog, self.quality)
        b = prep.project_catalog(self.catalog, self.quality)
        self.assertEqual(a["course_context"], self.catalog["course_context"])
        self.assertNotEqual(a["catalog_id"], self.catalog["catalog_id"])
        self.assertEqual(a["catalog_id"], b["catalog_id"])

    def test_formal_catalog_validator_and_full_chain(self):
        self.assertEqual(validate_catalog_payload(json.loads(self.paths["projected_catalog"].read_bytes())), [])
        self.assertEqual(self.validate(), [])

    def test_surviving_groups_keep_original_side(self):
        full = build_split(self.catalog)
        filtered = json.loads(self.paths["split"].read_bytes())
        for side in ("authoring", "holdout"):
            self.assertTrue(set(filtered[side + "_group_ids"]) <= set(full[side + "_group_ids"]))

    def test_manual_rebalance_rejected(self):
        self.alter("split", lambda p: p["authoring_group_ids"].append("GR-02"))
        self.assertTrue(self.validate())

    def test_conditional_rejected_discovery_in_eligible_group_excluded(self):
        for status in ("CONDITIONAL", "REJECTED", "DISCOVERY_ONLY"):
            with self.subTest(status=status):
                source = copy.deepcopy(self.catalog)
                source["exemplars"][1]["qualification"]["status"] = status
                refresh_catalog_fingerprint(source)
                eligibility = quality.build_quality_eligibility(source, reviewed_records(source))
                projection = prep.project_catalog(source, eligibility)
                self.assertNotIn(source["exemplars"][1], projection["exemplars"])

    def test_conditional_quality_group_excluded(self):
        rows = reviewed_records(self.catalog)
        rows[0]["decision"] = "CONDITIONAL"
        eligibility = quality.build_quality_eligibility(self.catalog, rows)
        projection = prep.project_catalog(self.catalog, eligibility)
        self.assertNotIn(rows[0]["group_id"], {c["group_id"] for c in projection["exemplars"]})

    def test_private_cannot_be_upgraded(self):
        from exemplar_contract import source_identity_sha256
        source = copy.deepcopy(self.catalog)
        for card in source["exemplars"][:2]:
            card["source"].update(authority_tier="PRIVATE", source_type="private_user_provided",
                                  authority_basis="private_user", visibility="private_session", canonical_url=None,
                                  provided_source_id="SYNTHETIC-private", source_label="SYNTHETIC private user source")
            card["source"]["source_identity_sha256"] = source_identity_sha256(card)
        refresh_catalog_fingerprint(source)
        self.assertEqual(validate_catalog_payload(source), [])
        rows = reviewed_records(source)
        rows[0]["decision"] = "CONDITIONAL"
        eligibility = quality.build_quality_eligibility(source, rows)
        projection = prep.project_catalog(source, eligibility)
        self.assertNotIn(rows[0]["group_id"], {c["group_id"] for c in projection["exemplars"]})
        rows[0]["decision"] = "QUALITY_ELIGIBLE"
        with self.assertRaises(ContractError):
            quality.build_quality_eligibility(source, rows)

    def test_source_card_stale(self):
        self.alter("source_catalog", lambda p: p["exemplars"][0]["design_patterns"].append("changed"))
        self.assertTrue(self.validate())

    def test_source_catalog_identity_stale(self):
        self.alter("source_catalog", lambda p: p.update(catalog_id="new-id"))
        self.assertTrue(self.validate())

    def test_source_catalog_whitespace_bytes_stale(self):
        p = self.paths["source_catalog"]
        p.write_bytes(p.read_bytes() + b"\n")
        self.assertTrue(self.validate())

    def test_quality_fingerprint_stale(self):
        self.alter("quality_eligibility", lambda p: p["groups"][0].update(rationale="changed"))
        self.assertTrue(self.validate())

    def test_quality_bytes_stale(self):
        p = self.paths["quality_eligibility"]
        p.write_bytes(p.read_bytes() + b" ")
        self.assertTrue(self.validate())

    def test_tampered_projection_rejected_even_rehashed(self):
        def change(p):
            p["exemplars"].pop()
            refresh_catalog_fingerprint(p)
        self.alter("projected_catalog", change)
        self.assertTrue(self.validate())

    def test_pack_membership_tamper(self):
        self.alter("authoring_pack", lambda p: p["exemplars"].append(self.catalog["exemplars"][-1]))
        self.assertTrue(self.validate())

    def test_preparation_lineage_naked_hash_rejected(self):
        self.alter("preparation", lambda p: p.update(projected_catalog_file_sha256="a" * 64))
        self.assertTrue(self.validate())
        self.prepare()
        self.alter("preparation", lambda p: p.update(pipeline_run_id="  "))
        self.assertTrue(self.validate())

    def test_zero_and_one_group_do_not_duplicate(self):
        for groups in (set(), {"GR-00"}):
            eligibility = quality.build_quality_eligibility(self.catalog, [
                {**row, "decision": "QUALITY_ELIGIBLE" if row["group_id"] in groups else "REJECTED"}
                for row in reviewed_records(self.catalog)])
            split = build_split(prep.project_catalog(self.catalog, eligibility))
            self.assertEqual(split["authoring_group_count"] + split["holdout_group_count"], len(groups))
            self.assertNotEqual(prep.preparation_disposition(split), "BENCHMARK_READY")

    def test_uneven_two_groups_keeps_unavailable_side(self):
        source = make_catalog(20)
        for c in source["exemplars"]:
            c["transferable_principles"] = ["SYNTHETIC"]
        refresh_catalog_fingerprint(source)
        full = build_split(source)
        groups = set(full["authoring_group_ids"][:2])
        rows = reviewed_records(source)
        for row in rows:
            row["decision"] = "QUALITY_ELIGIBLE" if row["group_id"] in groups else "REJECTED"
        split = build_split(prep.project_catalog(source, quality.build_quality_eligibility(source, rows)))
        self.assertEqual(split["authoring_availability"], "AVAILABLE")
        self.assertEqual(split["holdout_availability"], "UNAVAILABLE")
        self.assertEqual(prep.preparation_disposition(split), "BENCHMARK_UNAVAILABLE")

    def test_both_available_ready(self):
        source = make_catalog(20)
        for c in source["exemplars"]:
            c["transferable_principles"] = ["SYNTHETIC"]
        refresh_catalog_fingerprint(source)
        split = build_split(prep.project_catalog(source, quality.build_quality_eligibility(source, reviewed_records(source))))
        self.assertEqual(prep.preparation_disposition(split), "BENCHMARK_READY")

    def test_bundle_rolls_back_all_files_on_replace_failure(self):
        before = {k: p.read_bytes() for k, p in self.paths.items()}
        import exemplar_split
        real = exemplar_split.os.replace
        calls = 0
        def fail_once(a, b):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("SYNTHETIC commit failure")
            return real(a, b)
        with patch.object(exemplar_split.os, "replace", side_effect=fail_once):
            with self.assertRaises(ContractError):
                self.prepare()
        self.assertEqual(before, {k: p.read_bytes() for k, p in self.paths.items()})

    def test_input_output_alias_rejected(self):
        paths = {k: v for k, v in self.paths.items() if k != "preparation"}
        paths["projected_catalog"] = paths["source_catalog"]
        with self.assertRaises(ContractError):
            prep.prepare_benchmark(self.paths["preparation"], pipeline_run_id="RUN-001", **paths)
        installed_root = Path(self.temp.name) / "installed" / "lesson-plan-docx-generator"
        with patch.object(prep, "__file__", str(installed_root / "scripts/benchmark_preparation.py")):
            prep.assert_external_outputs((Path(self.temp.name) / "external-workspace/output.json",))
            with self.assertRaises(ContractError):
                prep.assert_external_outputs((installed_root / "output.json",))


if __name__ == "__main__":
    unittest.main()
