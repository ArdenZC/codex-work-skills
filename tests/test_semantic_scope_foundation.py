from __future__ import annotations
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tests.semantic_scope_test_support import Evidence, ROOT, FIXTURES
from tests.semantic_scope_fixtures import freeze_original_outline
from semantic_scope_records import (
    RecordError,
    Inventory,
    checked,
    configuration_fingerprint,
    qualification_fingerprint,
    review_fingerprint,
    validate_configuration,
    validate_training,
)
from semantic_scope_review import review_status, validate_review
from reviewer_qualification import validate_qualification, ORIGINAL_NC02_SHA
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
    def evidence(self, miss=None):
        temp = tempfile.TemporaryDirectory(prefix="semantic-agent-")
        self.addCleanup(temp.cleanup)
        e = Evidence(Path(temp.name), "agent")
        e.agent_qualification(miss)
        return e

    def test_all_golden_repetitions_qualified(self):
        e = self.evidence()
        q = validate_qualification(
            e.context(), candidate_principal="reviewer", author_principal="author"
        )
        self.assertEqual(q["disposition"], "QUALIFIED")

    def test_hard_miss_negative_positive_ambiguity_and_holdout(self):
        for miss in [
            ("N01", "PASS"),
            ("N02", "HUMAN_REVIEW_REQUIRED"),
            ("P07", "REVISION_REQUIRED"),
            ("P08", "HUMAN_REVIEW_REQUIRED"),
            ("A13", "PASS"),
            ("H01", "REVISION_REQUIRED"),
        ]:
            with self.subTest(miss=miss):
                e = self.evidence(miss)
                q = validate_qualification(
                    e.context(), candidate_principal="reviewer", require_approval=False
                )
                self.assertEqual(q["disposition"], "NOT_QUALIFIED")
                with self.assertRaises(RecordError):
                    validate_qualification(e.context(), candidate_principal="reviewer")

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
        e.index["qualification_runs"][0]["input_inventory_keys"].append(
            "blind_holdout_truth"
        )
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
            run["input_inventory_keys"].append(case["critical_truth_inventory_key"])
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


if __name__ == "__main__":
    unittest.main()
