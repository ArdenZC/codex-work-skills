from __future__ import annotations
import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import base64
from tests.semantic_scope_test_support import Evidence, ROOT, FIXTURES
from tests.semantic_scope_fixtures import freeze_original_outline
from semantic_scope_records import (
    RecordError,
    Inventory,
    checked,
    configuration_fingerprint,
    managed_service_identity_fingerprint,
    qualification_fingerprint,
    review_fingerprint,
    validate_configuration,
    validate_managed_service_observation,
    validate_training,
)
from semantic_scope_review import review_status, validate_review
from reviewer_qualification import (
    validate_qualification,
    ORIGINAL_NC02_SHA,
    _managed_approval,
    _validate_case_exposures,
)
from operation_provenance import validate_receipt
from lifecycle_digest import canonical_json_bytes


class SemanticScopeFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="semantic-foundation-")
        self.addCleanup(self.temp.cleanup)
        self.e = Evidence(Path(self.temp.name))
        self.review = self.e.review()

    def status(self):
        return review_status(
            self.e.context(), frozen_lesson_ids=["L01"], pipeline_run_id="run"
        )

    def rewrite_review(self):
        self.review["review_fingerprint"] = review_fingerprint(self.review)
        self.e.write("semantic_scope_review", self.review)
        receipt = json.loads(
            Path(
                self.e.entries["semantic_scope_operation_receipt"]["path"]
            ).read_bytes()
        )
        receipt["subject_sha256"] = self.e.sha("semantic_scope_review")
        self.e.capture("semantic_scope_operation_receipt", receipt)

    def test_pass_full_coverage(self):
        self.assertEqual(self.status().status, "VALID", self.status().errors)

    def test_coverage_rejects_missing_duplicate_unknown_and_reordered(self):
        for ids in [[], ["L01", "L01"], ["unknown"], ["L02", "L01"]]:
            with self.subTest(ids=ids):
                self.review["lessons"] = [
                    {**self.review["lessons"][0], "lesson_id": i} for i in ids
                ]
                if not ids:
                    self.review["lessons"] = []
                self.rewrite_review()
                self.assertEqual(self.status().status, "INVALID")
                self.review = self.e.review()

    def test_disposition_forgery(self):
        self.review["whole_course_disposition"] = "REVISION_REQUIRED"
        self.rewrite_review()
        self.assertEqual(self.status().status, "INVALID")

    def test_issue_enum_location_excerpt_and_derivation(self):
        self.review = self.e.review(disposition="REVISION_REQUIRED")
        original = copy.deepcopy(self.review)
        for field, value in [
            ("category", "nursing_violation"),
            ("bounded_excerpt", "wrong text"),
            ("disposition", "HUMAN_REVIEW_REQUIRED"),
        ]:
            with self.subTest(field=field):
                self.review = copy.deepcopy(original)
                self.review["lessons"][0]["issues"][0][field] = value
                self.rewrite_review()
                self.assertEqual(self.status().status, "INVALID")

    def test_ambiguity_valid_and_cannot_be_pass(self):
        self.review = self.e.review(disposition="HUMAN_REVIEW_REQUIRED")
        self.assertEqual(self.status().status, "VALID", self.status().errors)
        self.review["lessons"][0]["issues"][0]["disposition"] = "REVISION_REQUIRED"
        self.rewrite_review()
        self.assertEqual(self.status().status, "INVALID")

    def test_source_reference_resolution(self):
        for field, value in [
            ("source_id", "unknown"),
            ("pointer", "/unknown"),
            ("sha256", "0" * 64),
            ("start", 1),
        ]:
            with self.subTest(field=field):
                self.review = self.e.review()
                self.review["lessons"][0]["source_references"][0][field] = value
                self.rewrite_review()
                self.assertEqual(self.status().status, "INVALID")

    def test_upstream_one_byte_changes_are_stale(self):
        for key in ("content", "outline", "source_truth_manifest", "confirmed-profile"):
            with self.subTest(key=key):
                path = Path(self.e.entries[key]["path"])
                raw = path.read_bytes()
                path.write_bytes(raw + b" ")
                self.assertEqual(self.status().status, "STALE", self.status().errors)
                path.write_bytes(raw)

    def test_configuration_change_stales_qualification_and_review(self):
        self.e.config["version"] = "2"
        self.e.write(
            "reviewer_configuration",
            canonical_json_bytes(self.e.config),
            protected=True,
        )
        self.assertEqual(self.status().status, "STALE")
        with self.assertRaises(RecordError):
            validate_qualification(self.e.context(), candidate_principal="reviewer")

    def test_other_run_id_rejected(self):
        result = review_status(
            self.e.context(), frozen_lesson_ids=["L01"], pipeline_run_id="other"
        )
        self.assertEqual(result.status, "INVALID")

    def test_canonical_configuration_and_integer_fields(self):
        raw = canonical_json_bytes(self.e.config)
        self.assertEqual(
            configuration_fingerprint(raw), hashlib.sha256(raw).hexdigest()
        )

    def test_configuration_rejects_noncanonical_numbers_duplicate_and_nfc_collision(
        self,
    ):
        raw = canonical_json_bytes(self.e.config)
        for bad in [
            b"\xef\xbb\xbf" + raw,
            raw + b"\n",
            raw.replace(
                b'"configuration_version":"1.0"', b'"configuration_version":1.0'
            ),
            b'{"x":1,"x":2}',
            b'{"\xc3\xa9":1,"e\xcc\x81":2}',
            raw.replace(b"fixture-reviewer", b"fixture-reviewe\xcc\x81r"),
        ]:
            with self.subTest(raw=bad[:40]):
                with self.assertRaises(RecordError):
                    configuration_fingerprint(bad)

    def test_config_dependencies_hash_actual_bytes(self):
        Path(self.e.entries["context-policy"]["path"]).write_bytes(b"changed")
        with self.assertRaises(RecordError):
            validate_configuration(self.e.context().inventory)

    def test_arbitrary_candidate_receipt_never_authorizes(self):
        self.e.index["receipts"] = [
            r
            for r in self.e.index["receipts"]
            if r["receipt_id"] != "semantic_scope_operation_receipt"
        ]
        self.assertEqual(self.status().status, "INVALID")

    def test_receipt_wrong_kind_subject_controller_and_actor(self):
        path = Path(self.e.entries["semantic_scope_operation_receipt"]["path"])
        original = json.loads(path.read_bytes())
        for field, value in [
            ("review_kind", "teacher_approval"),
            ("subject_sha256", "0" * 64),
            ("controller_id", "other"),
            ("actor_principal", "author"),
        ]:
            with self.subTest(field=field):
                changed = {**original, field: value}
                self.e.capture("semantic_scope_operation_receipt", changed)
                self.assertNotEqual(self.status().status, "VALID")

    def test_author_operation_mapping_cannot_be_forged(self):
        self.e.index["authors"][0]["principal_id"] = "reviewer"
        self.assertEqual(self.status().status, "INVALID")

    def test_revoked_and_expired_principal(self):
        for field, value in [
            ("revoked_at", "2026-10-05T10:00:00Z"),
            ("valid_until", "2026-10-05T10:00:00Z"),
        ]:
            with self.subTest(field=field):
                role = self.e.profile["roles"][1]
                old = role[field]
                role[field] = value
                role["revocation_reason"] = "revoked" if field == "revoked_at" else None
                self.e.write("authority_profile", self.e.profile, protected=True)
                self.assertEqual(self.status().status, "INVALID")
                role[field] = old

    def test_profile_pin_and_epoch_rotation_invalidates_old_authority(self):
        context = self.e.context()
        self.e.profile["policy_epoch"] = 2
        self.e.write("authority_profile", self.e.profile, protected=True)
        self.assertEqual(
            review_status(
                context, frozen_lesson_ids=["L01"], pipeline_run_id="run"
            ).status,
            "INVALID",
        )
        self.assertEqual(self.status().status, "INVALID")

    def test_profile_duplicate_principal_and_wrong_controller_allowlist(self):
        with self.assertRaises(RecordError):
            replace(self.e.context(), controller_allowlist=()).load()
        self.e.profile["roles"].append(copy.deepcopy(self.e.profile["roles"][0]))
        self.e.write("authority_profile", self.e.profile, protected=True)
        with self.assertRaises(RecordError):
            self.e.context().load()

    def test_valid_human_has_no_teacher_role(self):
        result = validate_qualification(
            self.e.context(), candidate_principal="reviewer", author_principal="author"
        )
        self.assertEqual(result["disposition"], "QUALIFIED")
        self.assertNotIn(
            "teacher_approver", self.e.profile["roles"][1]["allowed_roles"]
        )

    def test_training_scope_principal_procedure_and_issuer_rejected(self):
        original = copy.deepcopy(self.e.training)
        for field, value in [
            ("authorized_scope", "arbitrary"),
            ("authorized_scope", "teacher_review"),
            ("principal_id", "other"),
            ("procedure_id", "other"),
            ("procedure_version", "2"),
            ("procedure_sha256", "0" * 64),
            ("issuer_principal", "author"),
            ("issuer_principal", "reviewer"),
            ("issuer_principal", "absent"),
        ]:
            with self.subTest(field=field, value=value):
                self.e.training = {**original, field: value}
                self.e.write(
                    "human_training_authorization", self.e.training, protected=True
                )
                self.e.qualification["human_authority"][
                    "training_authorization_sha256"
                ] = self.e.sha("human_training_authorization")
                self.e.write_qualification()
                with self.assertRaises(RecordError):
                    validate_training(
                        self.e.context(),
                        self.e.qualification,
                        self.e.config,
                        author_principal="author",
                    )

    def test_training_expiry_revocation_and_issue_time(self):
        original = copy.deepcopy(self.e.training)
        for field, value in [
            ("valid_until", "2026-10-05T10:00:00Z"),
            ("revoked_at", "2026-10-05T10:00:00Z"),
            ("issued_at", "2026-12-01T00:00:00Z"),
        ]:
            with self.subTest(field=field):
                self.e.training = {**original, field: value}
                self.e.write(
                    "human_training_authorization", self.e.training, protected=True
                )
                self.e.qualification["human_authority"][
                    "training_authorization_sha256"
                ] = self.e.sha("human_training_authorization")
                with self.assertRaises(RecordError):
                    validate_training(
                        self.e.context(), self.e.qualification, self.e.config
                    )
        self.e.training = original
        self.e.write("human_training_authorization", self.e.training, protected=True)
        self.e.qualification["human_authority"]["training_authorization_sha256"] = (
            self.e.sha("human_training_authorization")
        )
        role = self.e.profile["roles"][2]
        role["valid_until"] = "2026-10-01T00:00:00Z"
        self.e.write("authority_profile", self.e.profile, protected=True)
        with self.assertRaises(RecordError):
            validate_training(self.e.context(), self.e.qualification, self.e.config)

    def test_training_cannot_replace_independent_qualification_approval(self):
        self.e.index["receipts"] = [
            r
            for r in self.e.index["receipts"]
            if r["receipt_id"] != "qualification_approval_receipt"
        ]
        with self.assertRaises(RecordError):
            validate_qualification(self.e.context(), candidate_principal="reviewer")

    def test_qualification_self_approval(self):
        receipt = json.loads(
            Path(self.e.entries["qualification_approval_receipt"]["path"]).read_bytes()
        )
        receipt["actor_principal"] = "reviewer"
        self.e.capture("qualification_approval_receipt", receipt)
        with self.assertRaises(RecordError):
            validate_qualification(self.e.context(), candidate_principal="reviewer")

    def test_missing_training_and_arbitrary_teacher_json(self):
        self.e.write(
            "human_training_authorization", {"teacher": "Someone"}, protected=True
        )
        self.assertNotEqual(self.status().status, "VALID")
        with self.assertRaises(RecordError):
            checked(
                self.e.context().inventory.raw("human_training_authorization"),
                "human-training-authorization",
            )

    def test_revoked_qualification_corpus_and_training_ids(self):
        for identifier in ("qualification", "training", "reviewer"):
            with self.subTest(identifier=identifier):
                self.e.profile["revoked_authority_ids"] = [identifier]
                self.e.write("authority_profile", self.e.profile, protected=True)
                with self.assertRaises(RecordError):
                    validate_qualification(
                        self.e.context(), candidate_principal="reviewer"
                    )

    def test_inventory_requires_files_and_rejects_candidate_authority_roots(self):
        with self.assertRaises(RecordError):
            Inventory(self.e.entries, self.e.run, (self.e.run,))
        with self.assertRaises(RecordError):
            self.e.context().inventory.by_sha("0" * 64)

    def test_inventory_rejects_symlink_and_alias(self):
        target = Path(self.e.entries["content"]["path"])
        alias = self.e.run / "alias.json"
        try:
            alias.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unavailable")
        entries = {
            **self.e.entries,
            "alias": dict(
                inventory_key="alias",
                path=str(alias),
                sha256=self.e.sha("content"),
                storage_class="run",
            ),
        }
        with self.assertRaises(ValueError):
            Inventory(entries, self.e.run, (self.e.protected,))
        entries["alias"]["path"] = str(target)
        with self.assertRaises(ValueError):
            Inventory(entries, self.e.run, (self.e.protected,))

    def test_subject_requires_scope_role_and_missing_training_fails(self):
        role = self.e.profile["roles"][1]
        role["allowed_roles"] = ["teacher_approver"]
        self.e.write(
            role["authorization_reference"],
            dict(
                record_version="1.0",
                principal_id="reviewer",
                allowed_roles=role["allowed_roles"],
            ),
            protected=True,
        )
        self.e.write("authority_profile", self.e.profile, protected=True)
        with self.assertRaises(RecordError):
            validate_training(self.e.context(), self.e.qualification, self.e.config)
        self.e.entries.pop("human_training_authorization")
        with self.assertRaises(RecordError):
            validate_qualification(self.e.context(), candidate_principal="reviewer")

    def test_qualification_expiry_and_direct_role_expiry(self):
        self.e.qualification["valid_until"] = "2026-10-06T11:00:00Z"
        self.e.write_qualification()
        with self.assertRaises(RecordError):
            validate_qualification(self.e.context(), candidate_principal="reviewer")
        self.e.profile["roles"][1]["valid_until"] = "2026-10-06T11:00:00Z"
        self.e.write("authority_profile", self.e.profile, protected=True)
        with self.assertRaises(RecordError):
            self.e.context().role("reviewer", "scope_reviewer")

    def test_teacher_receipt_uses_separate_operation_even_for_same_human(self):
        role = self.e.profile["roles"][1]
        role["allowed_roles"].append("teacher_approver")
        self.e.write(
            role["authorization_reference"],
            dict(
                record_version="1.0",
                principal_id="reviewer",
                allowed_roles=role["allowed_roles"],
            ),
            protected=True,
        )
        self.e.write("authority_profile", self.e.profile, protected=True)
        self.e.qualification_approval()
        self.review = self.e.review()
        teacher = dict(
            contract_version="2.0",
            pipeline_run_id="run",
            content_sha256=self.e.sha("content"),
            source_truth_manifest_sha256=self.e.sha("source_truth_manifest"),
            decision="APPROVED",
            semantic_scope=dict(
                outline_sha256=self.e.sha("outline"),
                review_sha256=self.e.sha("semantic_scope_review"),
                operation_receipt_sha256=self.e.sha("semantic_scope_operation_receipt"),
                human_reviewer=dict(
                    identity="reviewer",
                    review_operation_id="teacher-op",
                    authority_reference="teacher_approval_receipt",
                ),
            ),
        )
        self.e.write("teacher_review", teacher)
        bindings = {
            k: self.e.sha(k)
            for k in (
                "source_truth_manifest",
                "outline",
                "content",
                "semantic_scope_review",
                "semantic_scope_operation_receipt",
            )
        }
        receipt = self.e.receipt(
            "teacher_approval_receipt",
            "teacher_approval",
            "teacher_review",
            bindings,
            "teacher-op",
            "reviewer",
        )
        validate_receipt(
            self.e.context(),
            "teacher_approval_receipt",
            expected_kind="teacher_approval",
            subject_key="teacher_review",
        )
        receipt["operation_id"] = "review-op"
        self.e.capture("teacher_approval_receipt", receipt)
        with self.assertRaises(RecordError):
            validate_receipt(
                self.e.context(),
                "teacher_approval_receipt",
                expected_kind="teacher_approval",
                subject_key="teacher_review",
            )

    def test_original_nc02_hash_and_historical_outline_bytes(self):
        path = ROOT / "tests/fixtures/lesson-original-nc02.json"
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(), ORIGINAL_NC02_SHA
        )
        restored = freeze_original_outline(
            Path(self.temp.name) / "restored", json.loads(path.read_bytes())
        )
        frozen = FIXTURES / "N01/authority"
        for name in (
            "source-truth.json",
            "evidence/confirmed-profile.json",
            "evidence/whole-course-outline.json",
        ):
            self.assertEqual(
                (restored.parent / name).read_bytes(), (frozen / name).read_bytes()
            )

    def test_every_frozen_fixture_hash_is_real(self):
        for row in json.loads((FIXTURES / "fixture-files.json").read_bytes()):
            self.assertEqual(
                hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest(),
                row["sha256"],
                row["inventory_key"],
            )


class AgentQualificationTests(unittest.TestCase):
    def evidence(self, miss=None, *, shared_source=False):
        temp = tempfile.TemporaryDirectory(prefix="semantic-agent-")
        self.addCleanup(temp.cleanup)
        e = Evidence(Path(temp.name), "agent")
        e.agent_qualification(miss, shared_source=shared_source)
        return e

    def test_all_golden_repetitions_qualified(self):
        e = self.evidence(shared_source=True)
        q = validate_qualification(
            e.context(), candidate_principal="reviewer", author_principal="author"
        )
        self.assertEqual(q["disposition"], "QUALIFIED")
        cases = self.cases(e)
        self.assertEqual(len(e.index["qualification_runs"]), 3)
        for run, capture in zip(q["qualification_runs"], e.index["qualification_runs"]):
            self.assertEqual(capture["run_id"], run["run_id"])
            self.assertEqual(len(capture["operations"]), len(cases))
            for operation, exposure, case in zip(
                run["operations"], capture["operations"], cases
            ):
                self.assertEqual(exposure["case_id"], case["case_id"])
                self.assertEqual(
                    exposure["review_operation_id"], operation["review_operation_id"]
                )
                inputs = case["inputs"]
                expected = {"reviewer_configuration"} | {
                    row["inventory_key"]
                    for row in (
                        inputs["content"],
                        inputs["source_truth_manifest"],
                        inputs["outline"],
                        *inputs["sources"],
                    )
                }
                self.assertEqual(set(exposure["input_inventory_keys"]), expected)
                self.assertTrue(
                    all(
                        exposure[field] is True
                        for field in (
                            "labels_hidden",
                            "prior_reasoning_hidden",
                            "fresh_context",
                        )
                    )
                )
                self.assertEqual(
                    "shared-case-source" in expected, case["case_id"] in ("N02", "P07")
                )
        self.assertEqual(
            sum(
                "shared-case-source" in row["input_inventory_keys"]
                for run in e.index["qualification_runs"]
                for row in run["operations"]
            ),
            6,
        )

    def cases(self, evidence):
        return [
            case
            for key in ("qualification_corpus", "blind_holdout_truth")
            for case in json.loads(Path(evidence.entries[key]["path"]).read_bytes())[
                "cases"
            ]
        ]

    def test_per_operation_exposure_rejects_leakage_and_bad_bindings(self):
        e = self.evidence()
        e.write("previous-result-cache", {"cached_outcome": "PASS"}, protected=True)
        context = e.context()
        cases = self.cases(e)
        by_case = {case["case_id"]: case for case in cases}
        baseline = copy.deepcopy(e.index)
        leaks = {
            "other content": by_case["N02"]["inputs"]["content"]["inventory_key"],
            "other source truth": by_case["N02"]["inputs"]["source_truth_manifest"][
                "inventory_key"
            ],
            "other outline": by_case["N02"]["inputs"]["outline"]["inventory_key"],
            "other case-only source": by_case["P07"]["inputs"]["sources"][0][
                "inventory_key"
            ],
            "critical truth": by_case["N01"]["critical_truth_inventory_key"],
            "corpus labels": "qualification_corpus",
            "holdout truth": "blind_holdout_truth",
            "previous review": e.qualification["qualification_runs"][0]["operations"][
                0
            ]["review_inventory_key"],
            "adjudication": e.qualification["golden_results"][0]["observations"][0][
                "adjudication_inventory_key"
            ],
            "previous result cache": "previous-result-cache",
            "qualification itself": "reviewer_qualification",
        }
        variants = []
        for name, key in leaks.items():
            variant = copy.deepcopy(baseline)
            variant["qualification_runs"][0]["operations"][0][
                "input_inventory_keys"
            ].append(key)
            variants.append((name, variant))
        variant = copy.deepcopy(baseline)
        holdout_op = next(
            row
            for row in variant["qualification_runs"][0]["operations"]
            if row["case_id"] == "H01"
        )
        holdout_op["input_inventory_keys"].append(
            by_case["H02"]["inputs"]["content"]["inventory_key"]
        )
        variants.append(("holdout cross-case input", variant))
        for name in (
            "missing",
            "duplicate",
            "unknown",
            "reordered",
            "wrong case",
            "wrong operation",
            "wrong run",
            "missing input",
        ):
            variant = copy.deepcopy(baseline)
            operations = variant["qualification_runs"][0]["operations"]
            if name == "missing":
                operations.pop()
            elif name == "duplicate":
                operations.append(copy.deepcopy(operations[0]))
            elif name == "unknown":
                row = copy.deepcopy(operations[0])
                row["case_id"] = "UNKNOWN"
                row["review_operation_id"] = "unknown-operation"
                operations.append(row)
            elif name == "reordered":
                operations[0], operations[1] = operations[1], operations[0]
            elif name == "wrong case":
                operations[0]["case_id"] = "N02"
            elif name == "wrong operation":
                operations[0]["review_operation_id"] = operations[1][
                    "review_operation_id"
                ]
            elif name == "wrong run":
                variant["qualification_runs"][0]["run_id"] = "wrong-run"
            else:
                operations[0]["input_inventory_keys"].remove("reviewer_configuration")
            variants.append((name, variant))
        for field in ("fresh_context", "labels_hidden", "prior_reasoning_hidden"):
            variant = copy.deepcopy(baseline)
            variant["qualification_runs"][0]["operations"][0][field] = False
            variants.append((field + " false", variant))
        variant = copy.deepcopy(baseline)
        capture = variant["qualification_runs"][0]
        operations = capture.pop("operations")
        capture.update(
            review_operation_ids=[row["review_operation_id"] for row in operations],
            input_inventory_keys=sorted(
                {key for row in operations for key in row["input_inventory_keys"]}
            ),
            labels_hidden=True,
            prior_reasoning_hidden=True,
            fresh_context=True,
        )
        variants.append(("legacy run-level union only", variant))
        for name, variant in variants:
            with self.subTest(name=name), self.assertRaises(RecordError):
                # Actual wire schema and pure linkage preflight; authority/hash ingress
                # is covered separately by the public-validator integration test.
                e.write("operation_index", variant, protected=True)
                captured = checked(
                    Path(e.entries["operation_index"]["path"]).read_bytes(),
                    "protected-operation-index",
                )
                _validate_case_exposures(
                    context.inventory,
                    e.qualification,
                    captured,
                    cases,
                    "reviewer_qualification",
                )

    def test_public_qualification_rejects_late_case_leak_before_review_reads(self):
        e = self.evidence()
        cases = self.cases(e)
        e.index["qualification_runs"][2]["operations"][0][
            "input_inventory_keys"
        ].append(cases[1]["inputs"]["content"]["inventory_key"])
        context = e.context()
        with patch(
            "reviewer_qualification.validate_review",
            side_effect=AssertionError("review read before exposure validated"),
        ):
            with self.assertRaisesRegex(RecordError, "per-operation input exposure"):
                validate_qualification(context, candidate_principal="reviewer")

    def _assert_hard_miss_not_qualified(self, miss):
        e = self.evidence(miss)
        q = validate_qualification(
            e.context(), candidate_principal="reviewer", require_approval=False
        )
        self.assertEqual(q["disposition"], "NOT_QUALIFIED")
        with self.assertRaises(RecordError):
            validate_qualification(e.context(), candidate_principal="reviewer")


    def test_hard_miss_n01_pass(self):
        self._assert_hard_miss_not_qualified(("N01", "PASS"))

    def test_hard_miss_n02_human_review_required(self):
        self._assert_hard_miss_not_qualified(("N02", "HUMAN_REVIEW_REQUIRED"))

    def test_hard_miss_p07_revision_required(self):
        self._assert_hard_miss_not_qualified(("P07", "REVISION_REQUIRED"))

    def test_hard_miss_p08_human_review_required(self):
        self._assert_hard_miss_not_qualified(("P08", "HUMAN_REVIEW_REQUIRED"))

    def test_hard_miss_a13_pass(self):
        self._assert_hard_miss_not_qualified(("A13", "PASS"))

    def test_hard_miss_h01_revision_required(self):
        self._assert_hard_miss_not_qualified(("H01", "REVISION_REQUIRED"))

    def test_mutable_model_revision_and_float_settings_rejected(self):
        e = self.evidence()
        for revision in ("latest", "default", "unversioned"):
            e.config["agent"]["model_revision"] = revision
            e.write(
                "reviewer_configuration", canonical_json_bytes(e.config), protected=True
            )
            with self.assertRaises(RecordError):
                validate_configuration(e.context().inventory)

    def test_missing_repeat_and_forged_hard_miss_are_invalid(self):
        e = self.evidence()
        e.qualification["qualification_runs"].pop()
        e.write_qualification()
        with self.assertRaises(RecordError):
            validate_qualification(
                e.context(), candidate_principal="reviewer", require_approval=False
            )
        e = self.evidence(("N01", "PASS"))
        e.qualification["golden_results"][0]["hard_miss"] = False
        e.write_qualification()
        with self.assertRaises(RecordError):
            validate_qualification(
                e.context(), candidate_principal="reviewer", require_approval=False
            )

    def test_revealed_holdout_and_unprotected_adjudication_rejected(self):
        e = self.evidence()
        e.index["qualification_runs"][0]["operations"][0][
            "input_inventory_keys"
        ].append("blind_holdout_truth")
        with self.assertRaises(RecordError):
            validate_qualification(e.context(), candidate_principal="reviewer")
        e = self.evidence()
        e.index["adjudications"].pop()
        with self.assertRaises(RecordError):
            validate_qualification(e.context(), candidate_principal="reviewer")

    def test_truth_cannot_be_exposed_as_a_source_input(self):
        e = self.evidence()
        corpus = json.loads(
            Path(e.entries["qualification_corpus"]["path"]).read_bytes()
        )
        case = corpus["cases"][0]
        case["inputs"]["sources"].append(
            dict(
                inventory_key=case["critical_truth_inventory_key"],
                sha256=case["critical_truth_sha256"],
            )
        )
        e.write("qualification_corpus", corpus, protected=True)
        e.qualification["corpus_sha256"] = e.sha("qualification_corpus")
        e.write_qualification()
        e.receipt(
            "corpus_approval_receipt",
            "corpus_approval",
            "qualification_corpus",
            dict(
                qualification_corpus=e.sha("qualification_corpus"),
                blind_holdout_truth=e.sha("blind_holdout_truth"),
            ),
            "corpus-approval",
            "adjudicator",
            recorded="2026-10-02T10:00:00Z",
        )
        for run in e.index["qualification_runs"]:
            run["operations"][0]["input_inventory_keys"].append(
                case["critical_truth_inventory_key"]
            )
        with self.assertRaisesRegex(RecordError, "input alias"):
            validate_qualification(
                e.context(), candidate_principal="reviewer", require_approval=False
            )

    def test_corpus_revocation_and_self_approval_rejected(self):
        e = self.evidence()
        e.profile["revoked_authority_ids"] = ["qualification-corpus-synthetic"]
        e.write("authority_profile", e.profile, protected=True)
        with self.assertRaises(RecordError):
            validate_qualification(e.context(), candidate_principal="reviewer")
        e = self.evidence()
        r = json.loads(
            Path(e.entries["qualification_approval_receipt"]["path"]).read_bytes()
        )
        r["actor_principal"] = "reviewer"
        e.capture("qualification_approval_receipt", r)
        with self.assertRaises(RecordError):
            validate_qualification(e.context(), candidate_principal="reviewer")


class ManagedAliasReviewerIdentityTests(unittest.TestCase):
    @staticmethod
    def _managed_fixture(root):
        evidence = Evidence(root, reviewer_type="agent")
        evidence.enable_managed_alias()
        evidence.agent_qualification()
        return evidence

    def test_managed_qualified_at_cannot_be_redated_after_evidence(self):
        with tempfile.TemporaryDirectory(prefix="managed-alias-redate-") as tmp:
            e = self._managed_fixture(Path(tmp))
            e.qualification["qualified_at"] = "2026-10-08T18:00:00Z"
            e.qualification["valid_until"] = "2026-10-09T18:00:00Z"
            e.write_qualification()
            context = replace(
                e.context(),
                now=datetime(2026, 10, 9, 17, 59, 59, tzinfo=timezone.utc),
            )

            with self.assertRaisesRegex(
                RecordError,
                "managed qualification qualified_at does not equal evidence completion",
            ):
                validate_qualification(
                    context,
                    candidate_principal=e.reviewer_principal,
                    require_approval=False,
                )

    def test_managed_redating_fails_even_with_fresh_independent_approval(self):
        with tempfile.TemporaryDirectory(prefix="managed-alias-redate-approval-") as tmp:
            e = self._managed_fixture(Path(tmp))
            old_observation_sha = e.sha("managed-qualification-approver-observation")
            old_approval_evidence_sha = e.sha("managed-qualification-approval-evidence")
            e.qualification["qualified_at"] = "2026-10-08T18:00:00Z"
            e.qualification["valid_until"] = "2026-10-09T18:00:00Z"
            e.write_qualification()
            e.refresh_managed_qualification_approval_for_test(
                operation_id="managed-qualification-approver-replay-operation",
                reviewed_at="2026-10-08T18:10:00Z",
            )
            self.assertNotEqual(
                e.sha("managed-qualification-approver-observation"),
                old_observation_sha,
            )
            self.assertNotEqual(
                e.sha("managed-qualification-approval-evidence"),
                old_approval_evidence_sha,
            )
            context = replace(
                e.context(),
                now=datetime(2026, 10, 9, 17, 59, 59, tzinfo=timezone.utc),
            )
            excluded = {e.reviewer_principal, "author"}
            approval_receipt = validate_receipt(
                context,
                "qualification_approval_receipt",
                expected_kind="qualification",
                subject_key="reviewer_qualification",
                excluded_principals=excluded,
            )
            _managed_approval(
                context,
                e.qualification,
                "reviewer_qualification",
                e.reviewer_principal,
                excluded,
                approval_receipt,
            )

            with self.assertRaisesRegex(
                RecordError,
                "managed qualification qualified_at does not equal evidence completion",
            ):
                validate_qualification(
                    context, candidate_principal=e.reviewer_principal
                )

    def test_managed_evidence_completion_and_strict_24_hour_boundary(self):
        with tempfile.TemporaryDirectory(prefix="managed-alias-boundary-") as tmp:
            e = self._managed_fixture(Path(tmp))
            self.assertEqual(e.qualification["qualified_at"], "2026-10-06T18:00:00Z")
            before_expiry = replace(
                e.context(),
                now=datetime(2026, 10, 7, 17, 59, 59, tzinfo=timezone.utc),
            )
            self.assertEqual(
                validate_qualification(
                    before_expiry, candidate_principal=e.reviewer_principal
                )["qualified_at"],
                "2026-10-06T18:00:00Z",
            )
            at_expiry = replace(
                before_expiry,
                now=datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc),
            )
            with self.assertRaisesRegex(RecordError, "qualification expired/not-yet-valid"):
                validate_qualification(at_expiry, candidate_principal=e.reviewer_principal)

    def test_managed_qualification_serialization_delay_does_not_move_freshness(self):
        with tempfile.TemporaryDirectory(prefix="managed-alias-serialization-") as tmp:
            e = self._managed_fixture(Path(tmp))
            qualification_path = Path(e.entries["reviewer_qualification"]["path"])
            serialized_at = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)
            serialized_epoch = serialized_at.timestamp()
            # Model a controller that writes the same qualification bytes at 19:00.
            os.utime(qualification_path, (serialized_epoch, serialized_epoch))
            self.assertAlmostEqual(
                qualification_path.stat().st_mtime,
                serialized_epoch,
                delta=1,
            )
            self.assertEqual(e.qualification["qualified_at"], "2026-10-06T18:00:00Z")

            result = validate_qualification(
                e.context(), candidate_principal=e.reviewer_principal
            )
            self.assertEqual(result["qualified_at"], "2026-10-06T18:00:00Z")

    def test_managed_alias_contract_and_fail_closed_production(self):
        with tempfile.TemporaryDirectory(prefix="managed-alias-foundation-") as tmp:
            e = Evidence(Path(tmp), reviewer_type="agent")
            e.enable_managed_alias()
            e.agent_qualification()
            context = e.context()

            qualification = validate_qualification(
                context, candidate_principal=e.reviewer_principal
            )
            self.assertEqual(qualification["contract_version"], "1.1")
            self.assertEqual(e.config["configuration_version"], "1.1")
            self.assertEqual(e.config["agent"]["model_reference"], "gpt-6.1-sol")
            self.assertIsNone(e.config["agent"]["model_revision"])
            self.assertNotEqual(e.reviewer_principal, e.approver_principal)
            approver_evidence = checked(
                context.inventory.raw(
                    "managed-qualification-approval-evidence", protected=True
                ),
                "managed-qualification-approval-evidence",
            )
            approver_observation = checked(
                context.inventory.raw(
                    approver_evidence["service_observation_inventory_key"],
                    protected=True,
                ),
                "managed-reviewer-service-observation",
            )
            reviewer_op = qualification["qualification_runs"][0]["operations"][0]
            reviewer_observation = checked(
                context.inventory.raw(
                    reviewer_op["service_observation_inventory_key"], protected=True
                ),
                "managed-reviewer-service-observation",
            )
            self.assertEqual(
                approver_observation["requested_alias"],
                reviewer_observation["requested_alias"],
            )
            self.assertEqual(
                managed_service_identity_fingerprint(approver_observation),
                managed_service_identity_fingerprint(reviewer_observation),
            )
            self.assertEqual(
                managed_service_identity_fingerprint(approver_observation),
                qualification["service_identity_fingerprint"],
                "two independent managed logical principals may use one alias without claiming model diversity",
            )

            bad_config = copy.deepcopy(e.config)
            bad_config["agent"]["model_revision"] = "gpt-6.1-sol"
            with self.assertRaises(RecordError):
                configuration_fingerprint(canonical_json_bytes(bad_config))

            packet = checked(
                context.inventory.raw(
                    "managed-qualification-review-packet", protected=True
                ),
                "managed-qualification-review-packet",
            )
            case_ids = {
                row["case_id"]
                for row in qualification["golden_results"]
                + qualification["holdout_results"]
            }
            self.assertEqual(len(packet["operations"]), 51)
            refs = [row["operation_ref"] for row in packet["operations"]]
            self.assertEqual(refs, sorted(refs))
            for row in packet["operations"]:
                self.assertEqual(
                    row["service_identity"]["requested_alias"], "gpt-6.1-sol"
                )
                display = base64.b64decode(row["review_report_base64"], validate=True)
                self.assertFalse(any(case_id.encode() in display for case_id in case_ids))
                self.assertNotIn(b"expected_disposition", display)
                self.assertNotIn(b"expected_critical_truth", display)

            original_qualification = copy.deepcopy(e.qualification)
            e.qualification["valid_until"] = "2026-10-07T18:00:01Z"
            e.write_qualification()
            with self.assertRaisesRegex(RecordError, "24-hour maximum"):
                validate_qualification(
                    e.context(), candidate_principal=e.reviewer_principal
                )
            e.qualification = original_qualification
            e.write_qualification()
            context = e.context()
            expires_at = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)
            with self.assertRaisesRegex(RecordError, "expired"):
                validate_qualification(
                    replace(context, now=expires_at),
                    candidate_principal=e.reviewer_principal,
                )

            candidate_q_path = e.run / "candidate-created-qualification.json"
            candidate_q_path.write_bytes(
                Path(e.entries["reviewer_qualification"]["path"]).read_bytes()
            )
            candidate_inventory = Inventory(
                {
                    "candidate-created-qualification": dict(
                        inventory_key="candidate-created-qualification",
                        path=str(candidate_q_path),
                        sha256=hashlib.sha256(candidate_q_path.read_bytes()).hexdigest(),
                        storage_class="run",
                    )
                },
                e.run,
                (e.protected,),
            )
            candidate_context = replace(
                context,
                inventory=candidate_inventory,
            )
            with self.assertRaisesRegex(RecordError, "not protected evidence"):
                validate_qualification(
                    candidate_context,
                    candidate_principal=e.reviewer_principal,
                    qualification_key="candidate-created-qualification",
                )
            with self.assertRaises(RecordError):
                candidate_context.role(
                    "candidate-created-reviewer-b", "qualification_approver"
                )

            e.author(
                json.loads(Path(e.entries["content"]["path"]).read_bytes()),
                "content",
            )
            production = e.review(
                operation="managed-production-review-operation",
                pipeline="managed-production-run",
                purpose="production_candidate",
                key="managed-production-review",
                receipt_key="managed-production-receipt",
                at="2026-10-06T18:20:00Z",
            )
            context = e.context()
            validate_review(
                context,
                review_key="managed-production-review",
                receipt_key="managed-production-receipt",
                frozen_lesson_ids=["L01"],
                pipeline_run_id="managed-production-run",
            )
            receipt = json.loads(
                Path(e.entries["managed-production-receipt"]["path"]).read_bytes()
            )
            observation_binding = receipt["input_bindings"][
                "managed_service_observation"
            ]
            observation = json.loads(
                Path(e.entries[observation_binding["inventory_key"]]["path"]).read_bytes()
            )
            observation["service_fingerprint"] = "changed-provider-service"
            e.write(
                observation_binding["inventory_key"],
                canonical_json_bytes(observation),
                protected=True,
            )
            receipt["input_bindings"]["managed_service_observation"]["sha256"] = e.sha(
                observation_binding["inventory_key"]
            )
            e.capture("managed-production-receipt", receipt)
            with self.assertRaisesRegex(RecordError, "service identity changed since qualification"):
                validate_review(
                    e.context(),
                    review_key="managed-production-review",
                    receipt_key="managed-production-receipt",
                    frozen_lesson_ids=["L01"],
                    pipeline_run_id="managed-production-run",
                )


class OpaqueManagedServiceObservationTests(unittest.TestCase):
    @staticmethod
    def _fixture(root):
        evidence = Evidence(root, reviewer_type="agent")
        evidence.enable_managed_alias(observation_version="1.1")
        return evidence

    @staticmethod
    def _validate(evidence, observation, key="opaque-observation"):
        evidence.write(key, canonical_json_bytes(observation), protected=True)
        context = evidence.context()
        config = validate_configuration(context.inventory)
        return validate_managed_service_observation(
            context.inventory,
            key,
            evidence.sha(key),
            config,
            observation["operation_id"],
            expected_principal=observation["logical_principal"],
            now=context.now,
        )

    def test_observation_10_keeps_strict_unknown_fallback_failure(self):
        with tempfile.TemporaryDirectory(prefix="observation-10-strict-") as tmp:
            e = Evidence(Path(tmp), reviewer_type="agent")
            e.enable_managed_alias()
            observation = e.managed_observation(
                "strict-observation", "2026-10-06T10:00:00Z"
            )
            observation["fallback_detected"] = None
            e.write("strict-observation", canonical_json_bytes(observation), protected=True)
            context = e.context()
            with self.assertRaisesRegex(RecordError, "managed service fallback"):
                validate_managed_service_observation(
                    context.inventory,
                    "strict-observation",
                    e.sha("strict-observation"),
                    validate_configuration(context.inventory),
                    "strict-observation",
                    now=context.now,
                )

    def test_observation_11_accepts_opaque_provider_with_exact_protected_codex_bytes(self):
        with tempfile.TemporaryDirectory(prefix="observation-11-codex-") as tmp:
            e = self._fixture(Path(tmp))
            e.agent_qualification()
            context = e.context()
            qualification = validate_qualification(
                context, candidate_principal=e.reviewer_principal
            )
            self.assertEqual(qualification["disposition"], "QUALIFIED")
            self.assertEqual(qualification["contract_version"], "1.1")

            operation = qualification["qualification_runs"][0]["operations"][0]
            observation_raw = context.inventory.raw(
                operation["service_observation_inventory_key"],
                operation["service_observation_sha256"],
                protected=True,
            )
            observation = json.loads(observation_raw)
            self.assertEqual(observation["observation_version"], "1.1")
            self.assertIsNone(observation["reported_model_identifier"])
            self.assertIsNone(observation["reported_model_revision"])
            self.assertIsNone(observation["request_id"])
            self.assertIsNone(observation["service_fingerprint"])
            self.assertIsNone(observation["service_api_version"])
            self.assertFalse(observation["controller_fallback_performed"])
            self.assertEqual(observation["provider_fallback_status"], "not_observable")
            request_raw = context.inventory.raw(
                observation["request_inventory_key"],
                observation["request_sha256"],
                protected=True,
            )
            trace_raw = context.inventory.raw(
                observation["response_trace_inventory_key"],
                observation["response_sha256"],
                protected=True,
            )
            self.assertEqual(hashlib.sha256(request_raw).hexdigest(), observation["request_sha256"])
            self.assertEqual(hashlib.sha256(trace_raw).hexdigest(), observation["response_sha256"])
            self.assertIn(b'"type":"thread.started"', trace_raw)
            self.assertEqual(
                observation["codex_cli_version"], "codex-cli test-fixture-1.1"
            )

            e.author(
                json.loads(Path(e.entries["content"]["path"]).read_bytes()), "content"
            )
            e.review(
                operation="opaque-production-review-operation",
                pipeline="opaque-production-run",
                purpose="production_candidate",
                key="opaque-production-review",
                receipt_key="opaque-production-receipt",
                at="2026-10-06T18:20:00Z",
            )
            validate_review(
                e.context(),
                review_key="opaque-production-review",
                receipt_key="opaque-production-receipt",
                frozen_lesson_ids=["L01"],
                pipeline_run_id="opaque-production-run",
            )

    def test_controller_fallback_and_provider_reported_true_reject(self):
        with tempfile.TemporaryDirectory(prefix="observation-11-fallback-") as tmp:
            e = self._fixture(Path(tmp))
            base = e.managed_observation(
                "fallback-operation", "2026-10-06T10:00:00Z"
            )
            controller_fallback = dict(base)
            controller_fallback["controller_fallback_performed"] = True
            e.write("controller-fallback-observation", canonical_json_bytes(controller_fallback), protected=True)
            context = e.context()
            with self.assertRaises(RecordError):
                validate_managed_service_observation(
                    context.inventory,
                    "controller-fallback-observation",
                    e.sha("controller-fallback-observation"),
                    validate_configuration(context.inventory),
                    base["operation_id"],
                    expected_principal=base["logical_principal"],
                    now=context.now,
                )

            provider_fallback = dict(base)
            provider_fallback["provider_fallback_status"] = "reported_true"
            e.write("provider-fallback-observation", canonical_json_bytes(provider_fallback), protected=True)
            context = e.context()
            with self.assertRaisesRegex(RecordError, "provider reported internal fallback"):
                validate_managed_service_observation(
                    context.inventory,
                    "provider-fallback-observation",
                    e.sha("provider-fallback-observation"),
                    validate_configuration(context.inventory),
                    base["operation_id"],
                    expected_principal=base["logical_principal"],
                    now=context.now,
                )

    def test_reported_false_and_provider_metadata_require_matching_raw_trace_paths(self):
        with tempfile.TemporaryDirectory(prefix="observation-11-trace-metadata-") as tmp:
            e = self._fixture(Path(tmp))
            pointers = {
                field: []
                for field in (
                    "reported_model_identifier",
                    "reported_model_revision",
                    "service_fingerprint",
                    "service_api_version",
                    "request_id",
                )
            }
            pointers["reported_model_identifier"] = ["/reported_model_identifier"]
            e.update_opaque_policy(
                provider_metadata_json_pointers=pointers,
                provider_fallback_json_pointers=["/provider_fallback"],
            )
            observation = e.managed_observation(
                "trace-metadata-operation",
                "2026-10-06T10:00:00Z",
                reported_metadata={"reported_model_identifier": "reported-model-x"},
                provider_fallback_status="reported_false",
                provider_fallback_evidence={
                    "line_index": 3,
                    "json_pointer": "/provider_fallback",
                },
                trace_fields={
                    "reported_model_identifier": "reported-model-x",
                    "provider_fallback": False,
                },
            )
            validated = self._validate(e, observation)
            self.assertEqual(validated["reported_model_identifier"], "reported-model-x")
            self.assertEqual(validated["provider_fallback_status"], "reported_false")

            forged = dict(observation)
            forged["reported_model_identifier"] = "invented-model"
            e.write(
                "forged-metadata-observation",
                canonical_json_bytes(forged),
                protected=True,
            )
            context = e.context()
            with self.assertRaisesRegex(RecordError, "provider metadata is not trace-derived"):
                validate_managed_service_observation(
                    context.inventory,
                    "forged-metadata-observation",
                    e.sha("forged-metadata-observation"),
                    validate_configuration(context.inventory),
                    forged["operation_id"],
                    expected_principal=forged["logical_principal"],
                    now=context.now,
                )

    def test_observation_11_rejects_principal_mismatch_raw_byte_changes_and_candidate_capture(self):
        with tempfile.TemporaryDirectory(prefix="observation-11-provenance-") as tmp:
            e = self._fixture(Path(tmp))
            observation = e.managed_observation(
                "binding-operation", "2026-10-06T10:00:00Z"
            )
            e.write("bound-observation", canonical_json_bytes(observation), protected=True)
            context = e.context()
            with self.assertRaisesRegex(RecordError, "principal mismatch"):
                validate_managed_service_observation(
                    context.inventory,
                    "bound-observation",
                    e.sha("bound-observation"),
                    validate_configuration(context.inventory),
                    observation["operation_id"],
                    expected_principal="different-principal",
                    now=context.now,
                )

            trace_path = Path(e.entries[observation["response_trace_inventory_key"]]["path"])
            trace_path.write_bytes(trace_path.read_bytes() + b" ")
            context = e.context()
            with self.assertRaisesRegex(RecordError, "changed raw-byte binding"):
                validate_managed_service_observation(
                    context.inventory,
                    "bound-observation",
                    e.sha("bound-observation"),
                    validate_configuration(context.inventory),
                    observation["operation_id"],
                    expected_principal=observation["logical_principal"],
                    now=context.now,
                )

            candidate_observation = e.managed_observation(
                "candidate-observation-operation", "2026-10-06T10:00:00Z"
            )
            e.write(
                "candidate-observation",
                canonical_json_bytes(candidate_observation),
                protected=False,
            )
            context = e.context()
            with self.assertRaisesRegex(RecordError, "not protected evidence"):
                validate_managed_service_observation(
                    context.inventory,
                    "candidate-observation",
                    e.sha("candidate-observation"),
                    validate_configuration(context.inventory),
                    candidate_observation["operation_id"],
                    expected_principal=candidate_observation["logical_principal"],
                    now=context.now,
                )

    def test_request_bytes_are_hash_bound_and_alias_build_policy_versions_are_pinned(self):
        with tempfile.TemporaryDirectory(prefix="observation-11-request-bytes-") as tmp:
            e = self._fixture(Path(tmp))
            observation = e.managed_observation(
                "request-binding-operation", "2026-10-06T10:00:00Z"
            )
            e.write("request-binding-observation", canonical_json_bytes(observation), protected=True)
            request_path = Path(e.entries[observation["request_inventory_key"]]["path"])
            request_path.write_bytes(request_path.read_bytes() + b" ")
            context = e.context()
            with self.assertRaisesRegex(RecordError, "changed raw-byte binding"):
                validate_managed_service_observation(
                    context.inventory,
                    "request-binding-observation",
                    e.sha("request-binding-observation"),
                    validate_configuration(context.inventory),
                    observation["operation_id"],
                    expected_principal=observation["logical_principal"],
                    now=context.now,
                )

        with tempfile.TemporaryDirectory(prefix="observation-11-pins-") as tmp:
            e = self._fixture(Path(tmp))
            base = e.managed_observation("pin-operation", "2026-10-06T10:00:00Z")
            mutations = [
                ("alias", "requested_alias", "different-alias", "managed service/provider alias changed"),
                ("build", "controller_build_sha256", "0" * 64, "controller build changed"),
                ("policy", "observation_policy_sha256", "0" * 64, "managed observation policy changed"),
                ("request-hash", "request_sha256", "0" * 64, "managed capture request_sha256 mismatch"),
            ]
            for label, field, value, message in mutations:
                with self.subTest(label=label):
                    observation = dict(base)
                    observation[field] = value
                    key = "pin-observation-" + label
                    e.write(key, canonical_json_bytes(observation), protected=True)
                    context = e.context()
                    with self.assertRaisesRegex(RecordError, message):
                        validate_managed_service_observation(
                            context.inventory,
                            key,
                            e.sha(key),
                            validate_configuration(context.inventory),
                            observation["operation_id"],
                            expected_principal=observation["logical_principal"],
                            now=context.now,
                        )

            e.managed_observation_version = "1.0"
            downgraded = e.managed_observation(
                "downgraded-observation-operation", "2026-10-06T10:00:00Z"
            )
            e.write("downgraded-observation", canonical_json_bytes(downgraded), protected=True)
            context = e.context()
            with self.assertRaisesRegex(RecordError, "cannot use observation policy 1.1"):
                validate_managed_service_observation(
                    context.inventory,
                    "downgraded-observation",
                    e.sha("downgraded-observation"),
                    validate_configuration(context.inventory),
                    downgraded["operation_id"],
                    now=context.now,
                )

        with tempfile.TemporaryDirectory(prefix="observation-11-missing-policy-") as tmp:
            e = Evidence(Path(tmp), reviewer_type="agent")
            e.enable_managed_alias(observation_version="1.0")
            e.managed_observation_version = "1.1"
            observation = e.managed_observation(
                "missing-policy-operation", "2026-10-06T10:00:00Z"
            )
            e.write("missing-policy-observation", canonical_json_bytes(observation), protected=True)
            context = e.context()
            with self.assertRaises(RecordError):
                validate_managed_service_observation(
                    context.inventory,
                    "missing-policy-observation",
                    e.sha("missing-policy-observation"),
                    validate_configuration(context.inventory),
                    observation["operation_id"],
                    expected_principal=observation["logical_principal"],
                    now=context.now,
                )


if __name__ == "__main__":
    unittest.main()
