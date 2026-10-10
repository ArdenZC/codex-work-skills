"""Synthetic contract tests only; never proof of deployed Operator ACLs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from lifecycle_digest import canonical_json_bytes, schema_errors, sha256_bytes
from operation_provenance import validate_receipt
from qualification_corpus_intake import (
    FROZEN_CASE_CONTENT_SHA256,
    FROZEN_GOLDEN_SHA256,
    FROZEN_HOLDOUT_SHA256,
    ORIGINAL_NC02_SHA256,
    _case_rows,
    _frozen_manifests,
    append_intake_index,
    capture_qualification_corpus_intake,
    validate_qualification_corpus_intake,
)
from semantic_scope_records import Inventory, RecordError, TrustContext, checked, parse
from tests.semantic_scope_test_support import Evidence, FIXTURES, ROOT


SCRIPTS = ROOT / "教案生成器/lesson-plan-docx-generator/scripts"
SCHEMAS = ROOT / "教案生成器/lesson-plan-docx-generator/schemas"
ORIGIN_COMMIT = "c67c2a83433417879b5e2b8c21bbddde8446224a"


class IntakeFixture:
    """Temp protected evidence graph with the exact frozen source bytes."""

    def __init__(self, root: Path):
        self.root = root
        self.run_root = root / "candidate"
        self.trust_root = root / "operator" / "trust"
        self.run_root.mkdir(parents=True)
        self.trust_root.mkdir(parents=True)
        self.entries: dict[str, dict[str, str]] = {}
        self.operator_uid = os.geteuid()
        self.candidate_uid = self.operator_uid + 10000
        self.now = datetime.now(timezone.utc)
        self.operator = "owner-controller:qualification-corpus-custodian"
        self.write_protected("operator-reference", b"Owner-managed operator reference\n")
        self.write_protected("ingress-procedure", b"separate UID; clean controller launch\n")
        self.write_protected("evidence-repository", b"protected append-only evidence store\n")

        fixture_files = json.loads((FIXTURES / "fixture-files.json").read_bytes())
        self.origin_by_case = {}
        for row in fixture_files:
            source = ROOT / row["path"]
            raw = source.read_bytes()
            self.write_protected(row["inventory_key"], raw)
            if row["inventory_key"].endswith(".content"):
                case_id = row["inventory_key"].split(".", 1)[0]
                self.origin_by_case[case_id] = {
                    "git_commit": ORIGIN_COMMIT,
                    "content_path": row["path"],
                }
        self.write_protected(
            "qualification_corpus",
            (FIXTURES / "qualification-corpus.json").read_bytes(),
        )
        self.write_protected(
            "blind_holdout_truth",
            (FIXTURES / "blind-holdout-truth.json").read_bytes(),
        )

        controller_components = []
        for module_name in (
            "semantic_scope_records",
            "semantic_scope_review",
            "operation_provenance",
            "reviewer_qualification",
            "qualification_corpus_intake",
        ):
            key = "controller:" + module_name
            raw = (SCRIPTS / (module_name + ".py")).read_bytes()
            self.write_protected(key, raw)
            controller_components.append(
                {
                    "component_id": module_name,
                    "component_type": "python_module",
                    "inventory_key": key,
                    "sha256": sha256_bytes(raw),
                }
            )
        for schema_name in (
            "managed-reviewer-service-observation-v1.1.schema.json",
            "managed-service-capture-manifest-v1.1.schema.json",
            "managed-service-observation-policy-v1.1.schema.json",
            "operation-provenance-receipt-v1.2.schema.json",
            "operator-authority-profile-v1.1.schema.json",
            "operator-controller-build-inventory-v1.0.schema.json",
            "operator-role-authorization-v1.1.schema.json",
            "protected-operation-index-v1.1.schema.json",
            "qualification-adjudication.schema.json",
            "qualification-corpus-intake-v1.0.schema.json",
            "qualification-corpus.schema.json",
            "reviewer-configuration-v1.1.schema.json",
            "reviewer-qualification-v1.1.schema.json",
            "semantic-scope-review.schema.json",
            "source-truth-manifest.schema.json",
        ):
            key = "controller-schema:" + schema_name
            raw = (SCHEMAS / schema_name).read_bytes()
            self.write_protected(key, raw)
            controller_components.append(
                {
                    "component_id": schema_name,
                    "component_type": "json_schema",
                    "inventory_key": key,
                    "sha256": sha256_bytes(raw),
                }
            )
        build = {
            "build_inventory_version": "1.0",
            "controller_id": "rq03f-intake-controller",
            "components": controller_components,
        }
        build_raw = canonical_json_bytes(build)
        self.write_protected("operator_controller_build", build_raw)
        build_sha = sha256_bytes(build_raw)

        role_specs = (
            (self.operator, ["qualification_corpus_custodian"], "1.1"),
            ("managed-agent:scope-reviewer-a", ["scope_reviewer"], "1.0"),
            ("managed-agent:qualification-approver-b", ["qualification_approver"], "1.0"),
            ("managed-agent:authoring-codex", ["author"], "1.0"),
            ("owner-controller:corpus-adjudicator", ["corpus_adjudicator"], "1.0"),
            ("owner-controller:teacher-approver", ["teacher_approver"], "1.0"),
        )
        roles = []
        for principal, allowed_roles, version in role_specs:
            reference = "authorization:" + principal
            self.write_protected(
                reference,
                canonical_json_bytes(
                    {
                        "record_version": version,
                        "principal_id": principal,
                        "allowed_roles": allowed_roles,
                    }
                ),
            )
            roles.append(
                {
                    "principal_id": principal,
                    "allowed_roles": allowed_roles,
                    "authorization_reference": reference,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_until": "2027-01-01T00:00:00Z",
                    "revoked_at": None,
                    "revocation_reason": None,
                }
            )
        self.profile = {
            "profile_version": "1.1",
            "authority_profile_id": "synthetic-intake-profile",
            "policy_epoch": 1,
            "operator_reference": "operator-reference",
            "controller_id": "rq03f-intake-controller",
            "controller_implementation": "qualification-corpus-intake-controller",
            "controller_version": "1.0",
            "ingress_procedure_reference": "ingress-procedure",
            "evidence_repository_reference": "evidence-repository",
            "roles": roles,
            "revoked_authority_ids": [],
            "created_at": "2026-10-10T00:00:00Z",
            "qualification_corpus_custodian_principal": self.operator,
            "operator_unix_uid": self.operator_uid,
            "non_operator_process_unix_uids": [self.candidate_uid],
            "controller_build_inventory_key": "operator_controller_build",
            "controller_build_inventory_sha256": build_sha,
        }
        self.write_protected("authority_profile", canonical_json_bytes(self.profile), mode=0o600)
        self.index = {
            "index_version": "1.1",
            "controller_id": self.profile["controller_id"],
            "policy_epoch": 1,
            "receipts": [],
            "authors": [],
            "adjudications": [],
            "qualification_runs": [],
            "qualification_corpus_intakes": [],
        }
        self.write_protected("operation_index", canonical_json_bytes(self.index), mode=0o600)

    def write_protected(self, key: str, raw: bytes, *, mode: int = 0o644):
        path = self.trust_root / (key.replace(":", "_") + ".bin")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        os.chmod(path, mode)
        self.entries[key] = {
            "inventory_key": key,
            "path": str(path),
            "sha256": sha256_bytes(raw),
            "storage_class": "protected_external",
        }
        return path

    def write_run(self, key: str, raw: bytes):
        path = self.run_root / (key.replace(":", "_") + ".bin")
        path.write_bytes(raw)
        self.entries[key] = {
            "inventory_key": key,
            "path": str(path),
            "sha256": sha256_bytes(raw),
            "storage_class": "run",
        }
        return path

    def context(self):
        return TrustContext(
            Inventory(self.entries, self.run_root, (self.trust_root,)),
            Path(self.entries["authority_profile"]["path"]),
            self.entries["authority_profile"]["sha256"],
            self.profile["policy_epoch"],
            Path(self.entries["operation_index"]["path"]),
            (("rq03f-intake-controller", "qualification-corpus-intake-controller", "1.0"),),
            self.now,
            operator_principal=self.operator,
            operator_unix_uid=self.operator_uid,
            non_operator_process_unix_uids=(self.candidate_uid,),
        )

    def capture_synthetic_intake(self, *, intake_id="qci-test", operation_id="qci-op-test"):
        context = self.context()
        profile, index = context.load()
        _, corpus, _, holdout = _frozen_manifests(context, "qualification_corpus", "blind_holdout_truth")
        cases = _case_rows(context, corpus, holdout, self.origin_by_case)
        auth_reference = next(
            row["authorization_reference"]
            for row in profile["roles"]
            if row["principal_id"] == self.operator
        )
        intake = {
            "intake_version": "1.0",
            "intake_id": intake_id,
            "operation_id": operation_id,
            "controller_id": profile["controller_id"],
            "operator_principal": self.operator,
            "operator_authorization_reference": auth_reference,
            "operator_authorization_sha256": self.entries[auth_reference]["sha256"],
            "authority_profile_sha256": context.profile_pin,
            "controller_build_inventory_sha256": profile["controller_build_inventory_sha256"],
            "policy_epoch": profile["policy_epoch"],
            "operator_identity_basis": "dedicated_os_account_option_b",
            "operator_unix_uid": self.operator_uid,
            "protected_repository_owner_unix_uid": self.operator_uid,
            "qualification_corpus": {
                **{k: self.entries["qualification_corpus"][k] for k in ("inventory_key", "sha256")},
                "corpus_contract_version": corpus["corpus_contract_version"],
                "corpus_id": corpus["corpus_id"],
                "corpus_version": corpus["corpus_version"],
            },
            "blind_holdout_truth": {
                **{k: self.entries["blind_holdout_truth"][k] for k in ("inventory_key", "sha256")},
                "corpus_contract_version": holdout["corpus_contract_version"],
                "corpus_id": holdout["corpus_id"],
                "corpus_version": holdout["corpus_version"],
            },
            "cases": cases,
            "purpose": "qualification_only",
            "historical_author_claim": "not_made",
            "intake_is_historical_authoring_operation": False,
            "recorded_at": (self.now - timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        intake_raw = canonical_json_bytes(intake)
        key = "qualification_corpus_intake:" + intake_id
        self.write_protected(key, intake_raw, mode=0o600)
        row = {
            "intake_id": intake_id,
            "operation_id": operation_id,
            "operator_principal": self.operator,
            "subject_inventory_key": key,
            "subject_sha256": sha256_bytes(intake_raw),
        }
        index_raw = append_intake_index(index, row)
        self.index = checked(index_raw, "protected-operation-index-v1.1")
        self.write_protected("operation_index", index_raw, mode=0o600)
        return self.context(), intake, intake_raw


class QualificationCorpusIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qualification-corpus-intake-")
        self.addCleanup(self.temp.cleanup)
        self.e = IntakeFixture(Path(self.temp.name))

    def test_frozen_manifest_and_all_17_content_bytes_match_b1(self):
        context = self.e.context()
        corpus_raw, corpus, holdout_raw, holdout = _frozen_manifests(
            context, "qualification_corpus", "blind_holdout_truth"
        )
        rows = _case_rows(context, corpus, holdout, self.e.origin_by_case)
        self.assertEqual(sha256_bytes(corpus_raw), FROZEN_GOLDEN_SHA256)
        self.assertEqual(sha256_bytes(holdout_raw), FROZEN_HOLDOUT_SHA256)
        self.assertEqual(len(rows), 17)
        self.assertEqual({row["case_id"]: row["content"]["sha256"] for row in rows}, FROZEN_CASE_CONTENT_SHA256)
        self.assertEqual(
            next(row["content"]["sha256"] for row in rows if row["case_id"] == "N01"),
            ORIGINAL_NC02_SHA256,
        )
        for row in rows:
            self.assertEqual(row["origin"]["git_commit"], ORIGIN_COMMIT)
            self.assertTrue(row["origin"]["origin_metadata_only"])
            self.assertNotIn("expected_disposition", row)
            self.assertNotIn("critical_truth_sha256", row)

    def test_explicit_versions_preserve_old_closed_contracts(self):
        index10 = json.loads((SCHEMAS / "protected-operation-index.schema.json").read_text())
        index11 = json.loads((SCHEMAS / "protected-operation-index-v1.1.schema.json").read_text())
        receipt11 = json.loads((SCHEMAS / "operation-provenance-receipt-v1.1.schema.json").read_text())
        receipt12 = json.loads((SCHEMAS / "operation-provenance-receipt-v1.2.schema.json").read_text())
        self.assertEqual(index10["properties"]["index_version"]["const"], "1.0")
        self.assertNotIn("qualification_corpus_intakes", index10["properties"])
        self.assertEqual(index11["properties"]["index_version"]["const"], "1.1")
        self.assertIn("qualification_corpus_intakes", index11["properties"])
        self.assertEqual(receipt11["properties"]["contract_version"]["const"], "1.1")
        self.assertNotIn("provenance_basis", receipt11["properties"])
        self.assertEqual(receipt12["properties"]["contract_version"]["const"], "1.2")
        self.assertEqual(len(receipt12["oneOf"]), 1)
        self.assertEqual(receipt12["properties"]["provenance_basis"]["const"],
                         "qualification_historical_corpus_intake")

    def test_index_append_is_strictly_additive_and_rejects_duplicate_ids(self):
        context = self.e.context()
        _, index = context.load()
        new_row = {
            "intake_id": "qci-1",
            "operation_id": "qci-op-1",
            "operator_principal": self.e.operator,
            "subject_inventory_key": "qualification_corpus_intake:qci-1",
            "subject_sha256": "a" * 64,
        }
        appended = checked(append_intake_index(index, new_row), "protected-operation-index-v1.1")
        self.assertEqual(appended["qualification_corpus_intakes"], [new_row])
        for field in ("receipts", "authors", "adjudications", "qualification_runs"):
            self.assertEqual(appended[field], index[field])
        with self.assertRaisesRegex(RecordError, "duplicate qualification corpus intake ID"):
            append_intake_index(appended, {**new_row, "operation_id": "qci-op-2"})
        with self.assertRaisesRegex(RecordError, "duplicate protected operation ID"):
            append_intake_index(appended, {**new_row, "intake_id": "qci-2"})

    def test_operator_capture_appends_adoptable_record_in_temporary_store(self):
        context = self.e.context()
        _, before = context.load()
        result = capture_qualification_corpus_intake(context)
        index_path = Path(self.e.entries["operation_index"]["path"])
        self.e.write_protected(
            "operation_index", index_path.read_bytes(), mode=0o600
        )
        intake_path = Path(result["path"])
        self.e.entries[result["inventory_key"]] = {
            "inventory_key": result["inventory_key"],
            "path": str(intake_path),
            "sha256": sha256_bytes(intake_path.read_bytes()),
            "storage_class": "protected_external",
        }
        updated = self.e.context()
        _, after = updated.load()
        self.assertEqual(len(after["qualification_corpus_intakes"]), 1)
        for field in ("receipts", "authors", "adjudications", "qualification_runs"):
            self.assertEqual(after[field], before[field])
        record = checked(intake_path.read_bytes(), "qualification-corpus-intake-v1.0")
        case = record["cases"][0]
        validated = validate_qualification_corpus_intake(
            updated,
            result["inventory_key"],
            result["sha256"],
            content_sha256=case["content"]["sha256"],
            authoring_id=case["authoring_id"],
            reviewer_principal="managed-agent:scope-reviewer-a",
            reviewer_operation_id="review-after-temporary-intake",
            reviewed_at=result["recorded_at"],
        )
        self.assertEqual(validated["operation_id"], result["operation_id"])
        self.assertEqual(result["operation_index_sha256"], self.e.entries["operation_index"]["sha256"])

    def test_valid_intake_binds_custody_only_and_exact_case_closure(self):
        context, intake, raw = self.e.capture_synthetic_intake()
        self.assertEqual(len(intake["cases"]), 17)
        self.assertEqual(intake["purpose"], "qualification_only")
        self.assertEqual(intake["historical_author_claim"], "not_made")
        self.assertIs(intake["intake_is_historical_authoring_operation"], False)
        self.assertNotIn("authors", intake)
        self.assertNotIn("expected_disposition", raw.decode("utf-8"))
        row = next(case for case in intake["cases"] if case["case_id"] == "N02")
        validated = validate_qualification_corpus_intake(
            context,
            "qualification_corpus_intake:qci-test",
            sha256_bytes(raw),
            content_sha256=row["content"]["sha256"],
            authoring_id=row["authoring_id"],
            reviewer_principal="managed-agent:scope-reviewer-a",
            reviewer_operation_id="review-operation-n02",
            reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
        )
        self.assertEqual(validated["intake_id"], "qci-test")
        self.assertNotEqual(validated["operator_principal"], "managed-agent:scope-reviewer-a")
        case_context = replace(
            context,
            inventory=context.inventory.namespace(
                {
                    "content": row["content"]["inventory_key"],
                    "source_truth_manifest": row["source_truth_manifest"]["inventory_key"],
                    "outline": row["outline"]["inventory_key"],
                }
            ),
        )
        case_validated = validate_qualification_corpus_intake(
            case_context,
            "qualification_corpus_intake:qci-test",
            sha256_bytes(raw),
            content_sha256=row["content"]["sha256"],
            authoring_id=row["authoring_id"],
            reviewer_principal="managed-agent:scope-reviewer-a",
            reviewer_operation_id="review-operation-n02",
            reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
        )
        self.assertEqual(case_validated["intake_id"], "qci-test")
        with self.assertRaisesRegex(RecordError, "review predates corpus intake"):
            validate_qualification_corpus_intake(
                context,
                "qualification_corpus_intake:qci-test",
                sha256_bytes(raw),
                content_sha256=row["content"]["sha256"],
                authoring_id=row["authoring_id"],
                reviewer_principal="managed-agent:scope-reviewer-a",
                reviewer_operation_id="review-operation-before-intake",
                reviewed_at=(self.e.now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            )

    def test_unadopted_candidate_intake_and_case_mismatch_are_rejected(self):
        context, intake, raw = self.e.capture_synthetic_intake()
        n02 = next(case for case in intake["cases"] if case["case_id"] == "N02")
        with self.assertRaisesRegex(RecordError, "Content authoring_id differs"):
            validate_qualification_corpus_intake(
                context,
                "qualification_corpus_intake:qci-test",
                sha256_bytes(raw),
                content_sha256=n02["content"]["sha256"],
                authoring_id="candidate-invented-authoring-id",
                reviewer_principal="managed-agent:scope-reviewer-a",
                reviewer_operation_id="review-operation-n02",
                reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
            )

        unadopted_raw = canonical_json_bytes({**intake, "intake_id": "qci-unadopted"})
        self.e.write_protected("qualification_corpus_intake:qci-unadopted", unadopted_raw)
        context = self.e.context()
        with self.assertRaisesRegex(RecordError, "not uniquely adopted"):
            validate_qualification_corpus_intake(
                context,
                "qualification_corpus_intake:qci-unadopted",
                sha256_bytes(unadopted_raw),
                content_sha256=n02["content"]["sha256"],
                authoring_id=n02["authoring_id"],
                reviewer_principal="managed-agent:scope-reviewer-a",
                reviewer_operation_id="review-operation-n02",
                reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
            )

        candidate_raw = canonical_json_bytes(intake)
        self.e.write_run("candidate-intake", candidate_raw)
        with self.assertRaisesRegex(RecordError, "not protected evidence"):
            validate_qualification_corpus_intake(
                self.e.context(),
                "candidate-intake",
                sha256_bytes(candidate_raw),
                content_sha256=n02["content"]["sha256"],
                authoring_id=n02["authoring_id"],
                reviewer_principal="managed-agent:scope-reviewer-a",
                reviewer_operation_id="review-operation-n02",
                reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
            )

    def test_custodian_role_is_dedicated_and_profile_epoch_rotation_stales_intake(self):
        context, intake, raw = self.e.capture_synthetic_intake()
        principal = intake["operator_principal"]
        role = next(row for row in self.e.profile["roles"] if row["principal_id"] == principal)
        self.assertEqual(role["allowed_roles"], ["qualification_corpus_custodian"])
        self.assertNotIn("author", role["allowed_roles"])
        self.assertNotIn("scope_reviewer", role["allowed_roles"])
        self.assertNotIn("corpus_adjudicator", role["allowed_roles"])

        self.e.profile["policy_epoch"] = 2
        self.e.index["policy_epoch"] = 2
        profile_raw = canonical_json_bytes(self.e.profile)
        self.e.write_protected("authority_profile", profile_raw, mode=0o600)
        self.e.write_protected("operation_index", canonical_json_bytes(self.e.index), mode=0o600)
        context = self.e.context()
        n02 = next(case for case in intake["cases"] if case["case_id"] == "N02")
        with self.assertRaisesRegex(RecordError, "obsolete authority profile"):
            validate_qualification_corpus_intake(
                context,
                "qualification_corpus_intake:qci-test",
                sha256_bytes(raw),
                content_sha256=n02["content"]["sha256"],
                authoring_id=n02["authoring_id"],
                reviewer_principal="managed-agent:scope-reviewer-a",
                reviewer_operation_id="review-operation-n02",
                reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
            )

    def test_authority_revocation_invalidates_adopted_intake(self):
        context, intake, raw = self.e.capture_synthetic_intake()
        self.e.profile["revoked_authority_ids"].append(intake["intake_id"])
        profile_raw = canonical_json_bytes(self.e.profile)
        self.e.write_protected("authority_profile", profile_raw, mode=0o600)
        intake["authority_profile_sha256"] = sha256_bytes(profile_raw)
        intake_raw = canonical_json_bytes(intake)
        intake_key = "qualification_corpus_intake:qci-test"
        self.e.write_protected(intake_key, intake_raw, mode=0o600)
        self.e.index["qualification_corpus_intakes"][0]["subject_sha256"] = sha256_bytes(intake_raw)
        index_raw = canonical_json_bytes(self.e.index)
        self.e.write_protected("operation_index", index_raw, mode=0o600)
        context = self.e.context()
        n02 = next(case for case in intake["cases"] if case["case_id"] == "N02")
        with self.assertRaisesRegex(RecordError, "revoked authority ID"):
            validate_qualification_corpus_intake(
                context,
                intake_key,
                sha256_bytes(intake_raw),
                content_sha256=n02["content"]["sha256"],
                authoring_id=n02["authoring_id"],
                reviewer_principal="managed-agent:scope-reviewer-a",
                reviewer_operation_id="review-operation-n02",
                reviewed_at=self.e.now.isoformat().replace("+00:00", "Z"),
            )

    def test_shared_operator_candidate_uid_and_missing_trust_fail_closed(self):
        context = self.e.context()
        shared = replace(context, non_operator_process_unix_uids=(os.geteuid(),))
        with self.assertRaisesRegex(RecordError, "process identity differs"):
            shared.load()

        candidate_profile = self.e.run_root / "self-profile.json"
        candidate_index = self.e.run_root / "self-index.json"
        candidate_profile.write_bytes(Path(self.e.entries["authority_profile"]["path"]).read_bytes())
        candidate_index.write_bytes(Path(self.e.entries["operation_index"]["path"]).read_bytes())
        self.e.entries["self_profile"] = {
            "inventory_key": "self_profile", "path": str(candidate_profile),
            "sha256": sha256_bytes(candidate_profile.read_bytes()), "storage_class": "run"
        }
        self.e.entries["self_index"] = {
            "inventory_key": "self_index", "path": str(candidate_index),
            "sha256": sha256_bytes(candidate_index.read_bytes()), "storage_class": "run"
        }
        forged = replace(context, profile_path=candidate_profile, operation_index_path=candidate_index)
        with self.assertRaisesRegex(RecordError, "outside protected repository"):
            forged.load()

    def test_candidate_modified_protected_index_bytes_fail_pinned_inventory_check(self):
        context = self.e.context()
        index_path = Path(self.e.entries["operation_index"]["path"])
        index_path.write_bytes(index_path.read_bytes() + b" ")
        with self.assertRaisesRegex(RecordError, "changed raw-byte binding"):
            context.load()

    def test_receipt_1_2_intake_branch_rejects_production_and_teacher_use(self):
        receipt_root = Path(self.temp.name) / "receipt-compat"
        receipt_root.mkdir()
        e = Evidence(receipt_root, reviewer_type="agent")
        e.enable_managed_alias(observation_version="1.1")
        e.review(operation="managed-qualification-review", purpose="qualification")
        receipt_key = "semantic_scope_operation_receipt"
        receipt = json.loads(Path(e.entries[receipt_key]["path"]).read_bytes())
        review_key = "semantic_scope_review"
        review = json.loads(Path(e.entries[review_key]["path"]).read_bytes())
        review["review_purpose"] = "production_candidate"
        review["review_fingerprint"] = ""
        from semantic_scope_records import review_fingerprint

        review["review_fingerprint"] = review_fingerprint(review)
        e.write(review_key, canonical_json_bytes(review), protected=True)
        receipt["subject_sha256"] = e.sha(review_key)
        dummy = e.write("dummy-intake", b"not an adopted intake\n", protected=True)
        receipt.update(
            contract_version="1.2",
            provenance_basis="qualification_historical_corpus_intake",
            historical_author_claim="not_made",
            intake_is_historical_authoring_operation=False,
            author_principal=None,
            author_operation_id=None,
        )
        receipt["input_bindings"]["qualification_corpus_intake"] = {
            "inventory_key": "dummy-intake", "sha256": e.sha("dummy-intake")
        }
        e.capture(receipt_key, receipt)
        with self.assertRaisesRegex(RecordError, "qualification-purpose only"):
            validate_receipt(
                e.context(), receipt_key, expected_kind="semantic_scope",
                subject_key="semantic_scope_review",
            )
        receipt["review_kind"] = "teacher_approval"
        errors = schema_errors(receipt, "operation-provenance-receipt-v1.2.schema.json")
        self.assertTrue(errors)
        self.assertTrue(dummy.is_file())

    def test_receipt_1_2_accepts_adopted_custody_only_for_frozen_qualification_case(self):
        review_root = Path(self.temp.name) / "reviewer-runtime"
        review_root.mkdir()
        e = Evidence(review_root, reviewer_type="agent")
        e.enable_managed_alias(observation_version="1.1")
        trust = IntakeFixture(Path(self.temp.name) / "operator-runtime")

        reviewer_role = next(
            row for row in e.profile["roles"]
            if row["principal_id"] == e.reviewer_principal
        )
        reviewer_auth_raw = Path(
            e.entries[reviewer_role["authorization_reference"]]["path"]
        ).read_bytes()
        trust.write_protected(
            reviewer_role["authorization_reference"], reviewer_auth_raw
        )
        trust.profile["created_at"] = "2026-01-01T00:00:00Z"
        trust.profile["roles"].append(deepcopy(reviewer_role))
        trust.write_protected(
            "authority_profile", canonical_json_bytes(trust.profile), mode=0o600
        )
        _, corpus, _, _ = _frozen_manifests(
            trust.context(), "qualification_corpus", "blind_holdout_truth"
        )
        case = next(row for row in corpus["cases"] if row["case_id"] == "N02")
        for binding in (
            case["inputs"]["content"],
            case["inputs"]["source_truth_manifest"],
            case["inputs"]["outline"],
            *case["inputs"]["sources"],
        ):
            e.entries[binding["inventory_key"]] = trust.entries[binding["inventory_key"]]
        content = json.loads(
            Path(e.entries[case["inputs"]["content"]["inventory_key"]]["path"])
            .read_bytes()
        )
        e.author(content, case["inputs"]["content"]["inventory_key"])
        review_at = trust.now.isoformat(timespec="seconds").replace("+00:00", "Z")
        e.review(
            case=case,
            operation="qualification-review-n02",
            pipeline="qualification-run-1",
            purpose="qualification",
            key="qualification-review-n02",
            receipt_key="qualification-receipt-n02",
            at=review_at,
        )
        context, intake, intake_raw = trust.capture_synthetic_intake()
        intake_key = "qualification_corpus_intake:qci-test"
        receipt_key = "qualification-receipt-n02"
        receipt = json.loads(Path(e.entries[receipt_key]["path"]).read_bytes())
        receipt.update(
            contract_version="1.2",
            authority_profile_sha256=trust.entries["authority_profile"]["sha256"],
            controller_id=trust.profile["controller_id"],
            provenance_basis="qualification_historical_corpus_intake",
            historical_author_claim="not_made",
            intake_is_historical_authoring_operation=False,
            author_principal=None,
            author_operation_id=None,
        )
        receipt["input_bindings"]["qualification_corpus_intake"] = {
            "inventory_key": intake_key,
            "sha256": sha256_bytes(intake_raw),
        }
        e.capture(receipt_key, receipt)

        merged_index = deepcopy(trust.index)
        for field in ("receipts", "authors", "adjudications", "qualification_runs"):
            merged_index[field] = deepcopy(e.index[field])
        merged_index_raw = canonical_json_bytes(merged_index)
        trust.index = checked(merged_index_raw, "protected-operation-index-v1.1")
        trust.write_protected("operation_index", merged_index_raw, mode=0o600)
        entries = dict(e.entries)
        entries.update(trust.entries)
        inventory = Inventory(
            entries,
            e.run,
            (e.protected, trust.trust_root),
        )
        context = TrustContext(
            inventory,
            Path(trust.entries["authority_profile"]["path"]),
            trust.entries["authority_profile"]["sha256"],
            1,
            Path(trust.entries["operation_index"]["path"]),
            (("rq03f-intake-controller", "qualification-corpus-intake-controller", "1.0"),),
            trust.now,
            operator_principal=trust.operator,
            operator_unix_uid=trust.operator_uid,
            non_operator_process_unix_uids=(trust.candidate_uid,),
        )
        case_context = replace(
            context,
            inventory=inventory.namespace(
                {
                    "content": case["inputs"]["content"]["inventory_key"],
                    "source_truth_manifest": case["inputs"]["source_truth_manifest"]["inventory_key"],
                    "outline": case["inputs"]["outline"]["inventory_key"],
                }
            ),
        )
        validated = validate_receipt(
            case_context,
            receipt_key,
            expected_kind="semantic_scope",
            subject_key="qualification-review-n02",
        )
        self.assertEqual(validated["contract_version"], "1.2")
        self.assertIsNone(validated["author_principal"])
        self.assertEqual(validated["provenance_basis"], "qualification_historical_corpus_intake")
        self.assertNotEqual(validated["actor_principal"], intake["operator_principal"])


if __name__ == "__main__":
    unittest.main()
