"""Controlled temporary repositories for deterministic tests; no real authority."""

from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from typing import Any
from tests.test_lesson_lifecycle_contracts import _content, _write_json
from tests.semantic_scope_fixtures import freeze_original_outline
from lifecycle_digest import canonical_json_bytes, sha256_bytes
from source_truth import source_truth_fingerprint
from semantic_scope_records import (
    Inventory,
    TrustContext,
    managed_service_identity_fingerprint,
    review_fingerprint,
    qualification_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/semantic-scope"
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
AT = "2026-10-06T10:00:00Z"
END = "2027-01-01T00:00:00Z"


class Evidence:
    def __init__(self, root: Path, reviewer_type: str = "human"):
        self.reviewer_principal = "reviewer"
        self.approver_principal = "approver"
        self.run = root / "candidate"
        self.protected = root / "operator"
        self.run.mkdir()
        self.protected.mkdir()
        self.entries: dict[str, dict[str, Any]] = {}
        self.index = dict(
            index_version="1.0",
            controller_id="controller",
            policy_epoch=1,
            receipts=[],
            authors=[],
            adjudications=[],
            qualification_runs=[],
        )
        self.profile = dict(
            profile_version="1.0",
            authority_profile_id="profile",
            policy_epoch=1,
            operator_reference="operator",
            controller_id="controller",
            controller_implementation="controlled",
            controller_version="1.0",
            ingress_procedure_reference="ingress",
            evidence_repository_reference="repository",
            roles=[],
            revoked_authority_ids=[],
            created_at="2026-01-01T00:00:00Z",
        )
        for key in ("operator", "ingress", "repository", "approval-procedure"):
            self.write(key, {"reference": key}, protected=True)
        for principal, roles in [
            ("author", ["author"]),
            (self.reviewer_principal, ["scope_reviewer"]),
            (self.approver_principal, ["qualification_approver"]),
            ("adjudicator", ["corpus_adjudicator"]),
        ]:
            ref = principal + "-authorization"
            self.write(
                ref,
                dict(record_version="1.0", principal_id=principal, allowed_roles=roles),
                protected=True,
            )
            self.profile["roles"].append(
                dict(
                    principal_id=principal,
                    allowed_roles=roles,
                    authorization_reference=ref,
                    valid_from="2026-01-01T00:00:00Z",
                    valid_until=END,
                    revoked_at=None,
                    revocation_reason=None,
                )
            )
        self.write("authority_profile", self.profile, protected=True)
        for key in (
            "build-code",
            "context-policy",
            "prompt",
            "system",
            "tools",
            "human_procedure",
            "interface",
        ):
            self.write(key, (key + " exact immutable bytes").encode(), protected=True)
        self.write(
            "build",
            dict(manifest_version="1.0", files=[self.binding("build-code")]),
            protected=True,
        )
        self.config = dict(
            configuration_version="1.0",
            reviewer_type=reviewer_type,
            implementation="fixture-reviewer",
            version="1.0",
            implementation_build_sha256=self.sha("build"),
            context_policy=dict(
                policy_sha256=self.sha("context-policy"),
                whole_course=True,
                verified_sources_only=True,
                author_reasoning_hidden=True,
                candidate_read_only=True,
            ),
            agent=None,
            human=None,
        )
        if reviewer_type == "human":
            self.config["human"] = dict(
                procedure_id="whole-course-scope",
                procedure_version="1.0",
                procedure_sha256=self.sha("human_procedure"),
                interface_policy_sha256=self.sha("interface"),
            )
        else:
            self.config["agent"] = dict(
                model_reference="neutral-model",
                model_revision="immutable-revision-123",
                provider_reference=None,
                semantic_prompt_sha256=self.sha("prompt"),
                system_instructions_sha256=self.sha("system"),
                decoding=dict(
                    temperature="0",
                    top_p="1",
                    seed="42",
                    max_output_tokens=1000,
                    additional_parameters=[],
                ),
                tool_permissions_sha256=self.sha("tools"),
            )
        self.write(
            "reviewer_configuration", canonical_json_bytes(self.config), protected=True
        )
        content = _content()
        self.write("content", content)
        manifest = freeze_original_outline(self.run / "authority", content)
        self.add("source_truth_manifest", manifest)
        self.add("outline", manifest.parent / "evidence/whole-course-outline.json")
        self.add(
            "confirmed-profile", manifest.parent / "evidence/confirmed-profile.json"
        )
        self.author(content, "content")
        self.training = dict(
            record_version="1.0",
            authorization_id="training",
            principal_id="reviewer",
            authorized_scope="semantic_scope_review",
            procedure_id="whole-course-scope",
            procedure_version="1.0",
            procedure_sha256=self.sha("human_procedure"),
            issuer_principal="approver",
            issued_at="2026-10-02T10:00:00Z",
            valid_from="2026-10-02T10:00:00Z",
            valid_until=END,
            authorization_reference="reviewer-authorization",
            revoked_at=None,
            revocation_reason=None,
        )
        if reviewer_type == "human":
            self.write("human_training_authorization", self.training, protected=True)
            self.qualification = self.qualification_payload(True)
            self.write_qualification()
            self.qualification_approval()
        self.write("operation_index", self.index, protected=True)

    def enable_managed_alias(self):
        """Create synthetic operator-provisioned Reviewer A / approver B roles."""
        self.reviewer_principal = "managed-agent:reviewer-a"
        self.approver_principal = "managed-agent:qualification-approver-b"
        self.profile["roles"] = [
            role
            for role in self.profile["roles"]
            if role["principal_id"] not in {"reviewer", "approver"}
        ]
        for principal, role_name in (
            (self.reviewer_principal, "scope_reviewer"),
            (self.approver_principal, "qualification_approver"),
        ):
            reference = principal + "-authorization"
            self.write(
                reference,
                dict(
                    record_version="1.0",
                    principal_id=principal,
                    allowed_roles=[role_name],
                ),
                protected=True,
            )
            self.profile["roles"].append(
                dict(
                    principal_id=principal,
                    allowed_roles=[role_name],
                    authorization_reference=reference,
                    valid_from="2026-01-01T00:00:00Z",
                    valid_until=END,
                    revoked_at=None,
                    revocation_reason=None,
                )
            )
        self.write("authority_profile", self.profile, protected=True)
        self.write(
            "service-observation-policy",
            b"Fixture: exact managed endpoint and response identity fields; fallback denied.",
            protected=True,
        )
        self.write(
            "approver-prompt",
            b"Fixture: inspect opaque operation evidence; no expected labels or truth.",
            protected=True,
        )
        self.config["configuration_version"] = "1.1"
        self.config["agent"] = {
            **self.config["agent"],
            "model_reference": "gpt-6.1-sol",
            "model_revision": None,
            "provider_reference": "fixture-managed-service",
            "agent_identity_mode": "managed_alias",
            "service_observation_policy_sha256": self.sha("service-observation-policy"),
            "qualification_approver_prompt_sha256": self.sha("approver-prompt"),
            "fallback_policy": "deny",
        }
        self.write(
            "reviewer_configuration", canonical_json_bytes(self.config), protected=True
        )

    def managed_observation(self, operation_id, requested_at, observed_at=None):
        observed_at = observed_at or requested_at
        return dict(
            observation_version="1.0",
            operation_id=operation_id,
            provider_service_reference="fixture-managed-service",
            requested_alias="gpt-6.1-sol",
            reported_model_identifier="gpt-6.1-sol",
            reported_model_revision=None,
            service_fingerprint="fixture-service-behavior-window-2026-10",
            service_api_version="2026-10",
            request_id="request-" + sha256_bytes(("request-id:" + operation_id).encode())[:18],
            client_build_sha256=self.sha("build"),
            observation_policy_sha256=self.sha("service-observation-policy"),
            request_sha256=sha256_bytes(("request:" + operation_id).encode()),
            response_sha256=sha256_bytes(("response:" + operation_id).encode()),
            fallback_detected=False,
            requested_at=requested_at,
            observed_at=observed_at,
        )

    def add(self, key: str, path: Path, protected: bool = False):
        self.entries[key] = dict(
            inventory_key=key,
            path=str(path),
            sha256=sha256_bytes(path.read_bytes()),
            storage_class="protected_external" if protected else "run",
        )

    def write(self, key: str, value: Any, protected: bool = False):
        path = (
            Path(self.entries[key]["path"])
            if key in self.entries
            else (self.protected if protected else self.run)
            / (key.replace(":", "_") + ".json")
        )
        if isinstance(value, bytes):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        else:
            _write_json(path, value)
        self.add(
            key,
            path,
            (
                protected
                if key not in self.entries
                else self.entries[key]["storage_class"] == "protected_external"
            ),
        )
        return path

    def sha(self, key):
        return self.entries[key]["sha256"]

    def binding(self, key):
        return dict(inventory_key=key, sha256=self.sha(key))

    def context(self):
        self.write("operation_index", self.index, protected=True)
        return TrustContext(
            Inventory(self.entries.copy(), self.run, (self.protected,)),
            Path(self.entries["authority_profile"]["path"]),
            self.sha("authority_profile"),
            1,
            Path(self.entries["operation_index"]["path"]),
            (("controller", "controlled", "1.0"),),
            NOW,
        )

    def author(self, content, key):
        self.index["authors"].append(
            dict(
                authoring_id=content["authoring_provenance"]["authoring_id"],
                operation_id="author-op-" + str(len(self.index["authors"])),
                principal_id="author",
                content_sha256=self.sha(key),
            )
        )

    def qualification_payload(self, human):
        managed = self.config["configuration_version"] == "1.1"
        payload = dict(
            contract_version="1.1" if managed else "1.0",
            qualification_id="qualification",
            qualification_purpose=(
                "human_scope_authority" if human else "agent_corpus_evaluation"
            ),
            reviewer_configuration_sha256=self.sha("reviewer_configuration"),
            reviewer_implementation="fixture-reviewer",
            reviewer_version="1.0",
            corpus_contract_version=None if human else "1.0",
            corpus_sha256=None if human else self.sha("qualification_corpus"),
            blind_holdout_sha256=None if human else self.sha("blind_holdout_truth"),
            qualification_runs=[],
            golden_results=[],
            holdout_results=[],
            disposition="QUALIFIED",
            qualified_at=("2026-10-06T18:00:00Z" if managed else AT),
            valid_until=("2026-10-07T18:00:00Z" if managed else END),
            human_authority=(
                dict(
                    principal_id="reviewer",
                    teacher_authority_reference="reviewer-authorization",
                    procedure_id="whole-course-scope",
                    procedure_version="1.0",
                    procedure_sha256=self.sha("human_procedure"),
                    training_authorization_sha256=self.sha(
                        "human_training_authorization"
                    ),
                )
                if human
                else None
            ),
            qualification_fingerprint="",
        )
        if managed:
            sample = self.managed_observation("fingerprint-seed", "2026-10-06T18:00:00Z")
            payload["service_identity_fingerprint"] = managed_service_identity_fingerprint(sample)
        return payload

    def write_qualification(self):
        self.qualification["qualification_fingerprint"] = qualification_fingerprint(
            self.qualification
        )
        self.write("reviewer_qualification", self.qualification, protected=True)

    def receipt(
        self,
        key,
        kind,
        subject,
        bindings,
        op,
        actor,
        *,
        content_key="content",
        pipeline="run",
        recorded=AT,
    ):
        active = kind in ("semantic_scope", "teacher_approval")
        author = (
            next(
                (
                    a
                    for a in self.index["authors"]
                    if a["content_sha256"] == self.sha(content_key)
                ),
                None,
            )
            if active
            else None
        )
        receipt = dict(
            contract_version=(
                "1.1"
                if self.config["configuration_version"] == "1.1"
                and kind in {"semantic_scope", "qualification"}
                else "1.0"
            ),
            receipt_id=key,
            operation_id=op,
            controller_id="controller",
            actor_principal=actor,
            review_kind=kind,
            authority_profile_sha256=self.sha("authority_profile"),
            subject_sha256=self.sha(subject),
            subject_inventory_key=subject,
            pipeline_run_id=pipeline if active else None,
            input_bindings=bindings,
            author_principal=author["principal_id"] if active else None,
            author_operation_id=author["operation_id"] if active else None,
            isolation=(
                dict(
                    separate_invocation=True,
                    author_reasoning_hidden=True,
                    candidate_read_only=True,
                )
                if kind == "semantic_scope"
                else None
            ),
            decision="REVIEW_RECORDED" if kind == "semantic_scope" else "APPROVED",
            approval_procedure_reference="approval-procedure",
            recorded_at=recorded,
        )
        self.capture(key, receipt)
        return receipt

    def capture(self, key, receipt):
        self.write(key, receipt, protected=True)
        self.index["receipts"] = [
            r
            for r in self.index["receipts"]
            if r["receipt_id"] != receipt["receipt_id"]
        ]
        self.index["receipts"].append(
            {
                **{
                    k: receipt[k]
                    for k in (
                        "receipt_id",
                        "operation_id",
                        "actor_principal",
                        "subject_inventory_key",
                        "subject_sha256",
                    )
                },
                "receipt_inventory_key": key,
                "receipt_sha256": self.sha(key),
            }
        )

    def qualification_approval(self):
        if self.config["configuration_version"] == "1.1":
            from reviewer_qualification import build_managed_qualification_review_packet

            q_sha = self.sha("reviewer_qualification")
            config_sha = self.sha("reviewer_configuration")
            packet_raw = build_managed_qualification_review_packet(
                self.context(), candidate_principal=self.reviewer_principal
            )
            packet = json.loads(packet_raw)
            operation_refs = [row["operation_ref"] for row in packet["operations"]]
            self.write("managed-qualification-review-packet", packet_raw, protected=True)
            response = dict(
                response_version="1.0",
                decision="APPROVED",
                rationale="Synthetic independent evidence review passed.",
                reviewed_operation_refs=operation_refs,
                checks=[
                    dict(
                        check_id=check,
                        passed=True,
                        supporting_operation_refs=operation_refs,
                    )
                    for check in (
                        "operation_coverage",
                        "artifact_binding",
                        "service_identity_consistency",
                        "truth_blindness",
                        "separate_authority",
                    )
                ],
            )
            self.write("managed-qualification-approver-response", response, protected=True)
            op = "managed-qualification-approver-operation"
            reviewed_at = "2026-10-06T18:10:00Z"
            service_observation = self.managed_observation(
                op, "2026-10-06T18:05:00Z", "2026-10-06T18:06:00Z"
            )
            self.write(
                "managed-qualification-approver-observation",
                canonical_json_bytes(service_observation),
                protected=True,
            )
            evidence = dict(
                evidence_version="1.0",
                qualification_sha256=q_sha,
                reviewer_configuration_sha256=config_sha,
                reviewer_principal=self.reviewer_principal,
                approver_principal=self.approver_principal,
                operation_id=op,
                approval_prompt_sha256=self.sha("approver-prompt"),
                review_packet_inventory_key="managed-qualification-review-packet",
                review_packet_sha256=self.sha("managed-qualification-review-packet"),
                service_observation_inventory_key="managed-qualification-approver-observation",
                service_observation_sha256=self.sha("managed-qualification-approver-observation"),
                response_inventory_key="managed-qualification-approver-response",
                response_sha256=self.sha("managed-qualification-approver-response"),
                decision="APPROVED",
                rationale=response["rationale"],
                reviewed_at=reviewed_at,
            )
            self.write("managed-qualification-approval-evidence", evidence, protected=True)
            self.receipt(
                "qualification_approval_receipt",
                "qualification",
                "reviewer_qualification",
                dict(
                    reviewer_configuration=config_sha,
                    qualification_corpus=self.sha("qualification_corpus"),
                    blind_holdout_truth=self.sha("blind_holdout_truth"),
                    corpus_approval_receipt=self.sha("corpus_approval_receipt"),
                    managed_qualification_approval_evidence=self.binding(
                        "managed-qualification-approval-evidence"
                    ),
                ),
                op,
                self.approver_principal,
                recorded="2026-10-06T18:12:00Z",
            )
            return
        self.receipt(
            "qualification_approval_receipt",
            "qualification",
            "reviewer_qualification",
            dict(
                human_training_authorization=self.sha("human_training_authorization"),
                human_procedure=self.sha("human_procedure"),
            ),
            "qual-approval",
            self.approver_principal,
        )

    def refresh_managed_qualification_approval_for_test(
        self, *, operation_id: str, reviewed_at: str
    ) -> None:
        """Capture a fresh, valid second-principal approval for a rewritten fixture.

        This deliberately reuses the validated operation set while rebinding the
        protected approval packet to the current qualification bytes. It lets
        replay tests prove that even a fresh approval cannot refresh old runs.
        """
        q_sha = self.sha("reviewer_qualification")
        config_sha = self.sha("reviewer_configuration")
        packet = json.loads(
            Path(self.entries["managed-qualification-review-packet"]["path"]).read_bytes()
        )
        packet["qualification_sha256"] = q_sha
        packet["reviewer_configuration_sha256"] = config_sha
        self.write("managed-qualification-review-packet", packet, protected=True)

        rationale = "Synthetic independent re-review for " + operation_id
        response = json.loads(
            Path(self.entries["managed-qualification-approver-response"]["path"]).read_bytes()
        )
        response["rationale"] = rationale
        self.write("managed-qualification-approver-response", response, protected=True)

        reviewed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        requested_at = (reviewed - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        observed_at = (reviewed - timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write(
            "managed-qualification-approver-observation",
            canonical_json_bytes(
                self.managed_observation(operation_id, requested_at, observed_at)
            ),
            protected=True,
        )
        evidence = dict(
            evidence_version="1.0",
            qualification_sha256=q_sha,
            reviewer_configuration_sha256=config_sha,
            reviewer_principal=self.reviewer_principal,
            approver_principal=self.approver_principal,
            operation_id=operation_id,
            approval_prompt_sha256=self.sha("approver-prompt"),
            review_packet_inventory_key="managed-qualification-review-packet",
            review_packet_sha256=self.sha("managed-qualification-review-packet"),
            service_observation_inventory_key="managed-qualification-approver-observation",
            service_observation_sha256=self.sha("managed-qualification-approver-observation"),
            response_inventory_key="managed-qualification-approver-response",
            response_sha256=self.sha("managed-qualification-approver-response"),
            decision="APPROVED",
            rationale=rationale,
            reviewed_at=reviewed_at,
        )
        self.write("managed-qualification-approval-evidence", evidence, protected=True)
        recorded = (reviewed + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.receipt(
            "qualification_approval_receipt",
            "qualification",
            "reviewer_qualification",
            dict(
                reviewer_configuration=config_sha,
                qualification_corpus=self.sha("qualification_corpus"),
                blind_holdout_truth=self.sha("blind_holdout_truth"),
                corpus_approval_receipt=self.sha("corpus_approval_receipt"),
                managed_qualification_approval_evidence=self.binding(
                    "managed-qualification-approval-evidence"
                ),
            ),
            operation_id,
            self.approver_principal,
            recorded=recorded,
        )

    def review(
        self,
        *,
        case=None,
        operation="review-op",
        pipeline="run",
        disposition="PASS",
        purpose="production_candidate",
        key="semantic_scope_review",
        receipt_key="semantic_scope_operation_receipt",
        at=AT,
    ):
        ck = "content" if case is None else case["inputs"]["content"]["inventory_key"]
        mk = (
            "source_truth_manifest"
            if case is None
            else case["inputs"]["source_truth_manifest"]["inventory_key"]
        )
        ok = "outline" if case is None else case["inputs"]["outline"]["inventory_key"]
        content = json.loads(Path(self.entries[ck]["path"]).read_bytes())
        manifest = json.loads(Path(self.entries[mk]["path"]).read_bytes())
        source = manifest["sources"][1]
        ref = dict(
            source_id=source["source_id"],
            sha256=source["sha256"],
            pointer="",
            start=None,
            end=None,
        )
        lessons = []
        for i, lesson in enumerate(content["lessons"]):
            issues = []
            if i == 0 and disposition != "PASS":
                excerpt = lesson["teaching_content"][0][:100]
                issues = [
                    dict(
                        issue_id="issue-1",
                        category=(
                            "ambiguous_scope"
                            if disposition == "HUMAN_REVIEW_REQUIRED"
                            else "foreign_instruction"
                        ),
                        disposition=disposition,
                        location=dict(
                            field="/teaching_content",
                            index=0,
                            start=0,
                            end=len(excerpt),
                        ),
                        bounded_excerpt=excerpt,
                        rationale="Externally supplied fixture judgment.",
                        source_references=[ref],
                    )
                ]
            lessons.append(
                dict(
                    lesson_id=lesson["lesson_id"],
                    disposition=disposition if i == 0 else "PASS",
                    rationale="Fixture judgment against allocated task/output.",
                    source_references=[ref],
                    issues=issues,
                )
            )
        payload = dict(
            contract_version="1.0",
            review_id=key,
            pipeline_run_id=pipeline,
            review_purpose=purpose,
            content_contract_version=content["content_contract_version"],
            source_truth_manifest_sha256=self.sha(mk),
            outline_sha256=self.sha(ok),
            content_sha256=self.sha(ck),
            authoring_id=content["authoring_provenance"]["authoring_id"],
            reviewer=dict(
                type=self.config["reviewer_type"],
                identity=self.reviewer_principal,
                operation_id=operation,
                implementation="fixture-reviewer",
                version="1.0",
                configuration_sha256=self.sha("reviewer_configuration"),
                qualification_sha256=(
                    self.sha("reviewer_qualification")
                    if purpose == "production_candidate"
                    else None
                ),
            ),
            whole_course_disposition=disposition,
            lessons=lessons,
            reviewed_at=at,
            review_fingerprint="",
        )
        payload["review_fingerprint"] = review_fingerprint(payload)
        self.write(key, payload, protected=case is not None)
        observation_binding = None
        if self.config["configuration_version"] == "1.1":
            observation_key = key + "-service-observation"
            self.write(
                observation_key,
                canonical_json_bytes(self.managed_observation(operation, at)),
                protected=True,
            )
            observation_binding = self.binding(observation_key)
        bindings = dict(
            source_truth_manifest=self.sha(mk),
            outline=self.sha(ok),
            content=self.sha(ck),
            reviewer_configuration=self.sha("reviewer_configuration"),
            reviewer_qualification=payload["reviewer"]["qualification_sha256"],
        )
        if observation_binding:
            bindings["managed_service_observation"] = observation_binding
        self.receipt(
            receipt_key,
            "semantic_scope",
            key,
            bindings,
            operation,
            self.reviewer_principal,
            content_key=ck,
            pipeline=pipeline,
            recorded=at,
        )
        return payload

    def agent_qualification(
        self, miss: tuple[str, str] | None = None, *, shared_source=False
    ):
        metadata = json.loads((FIXTURES / "fixture-files.json").read_bytes())
        for row in metadata:
            src = ROOT / row["path"]
            dest = self.protected / "frozen" / row["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            self.add(row["inventory_key"], dest, True)
        for key in ("qualification_corpus", "blind_holdout_truth"):
            src = FIXTURES / (key.replace("_", "-") + ".json")
            self.write(key, src.read_bytes(), protected=True)
        corpus = json.loads(
            Path(self.entries["qualification_corpus"]["path"]).read_bytes()
        )
        holdout = json.loads(
            Path(self.entries["blind_holdout_truth"]["path"]).read_bytes()
        )
        cases = corpus["cases"] + holdout["cases"]
        if shared_source:
            common = self.protected / "shared-case-authority"
            common.mkdir()
            source = common / "shared-source.txt"
            source.write_bytes(
                b"Shared legitimate course reference, not labels or results."
            )
            self.add("shared-case-source", source, True)
            for case in corpus["cases"]:
                if case["case_id"] not in ("N02", "P07"):
                    continue
                inputs = case["inputs"]
                manifest_key = inputs["source_truth_manifest"]["inventory_key"]
                manifest = json.loads(
                    Path(self.entries[manifest_key]["path"]).read_bytes()
                )
                for row in manifest["sources"]:
                    entry = next(
                        item
                        for item in [inputs["outline"], *inputs["sources"]]
                        if item["sha256"] == row["sha256"]
                    )
                    dest = common / case["case_id"] / row["locator"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.entries[entry["inventory_key"]]["path"], dest)
                    self.add(entry["inventory_key"], dest, True)
                    row["locator"] = case["case_id"] + "/" + row["locator"]
                manifest["sources"].append(
                    dict(
                        source_id="shared-case-source",
                        source_type="user_attachment",
                        label="Shared legitimate source",
                        locator="shared-source.txt",
                        sha256=self.sha("shared-case-source"),
                        provenance="Synthetic controlled shared dependency",
                    )
                )
                manifest["manifest_fingerprint"] = source_truth_fingerprint(manifest)
                path = common / (case["case_id"] + "-manifest.json")
                _write_json(path, manifest)
                self.add(manifest_key, path, True)
                inputs["source_truth_manifest"]["sha256"] = self.sha(manifest_key)
                inputs["sources"].append(self.binding("shared-case-source"))
            self.write("qualification_corpus", corpus, protected=True)

        self.index["authors"] = []
        for case in cases:
            ck = case["inputs"]["content"]["inventory_key"]
            self.author(json.loads(Path(self.entries[ck]["path"]).read_bytes()), ck)
        self.receipt(
            "corpus_approval_receipt",
            "corpus_approval",
            "qualification_corpus",
            dict(
                qualification_corpus=self.sha("qualification_corpus"),
                blind_holdout_truth=self.sha("blind_holdout_truth"),
            ),
            "corpus-approval",
            "adjudicator",
            recorded="2026-10-02T10:00:00Z",
        )
        self.qualification = self.qualification_payload(False)
        for repetition in range(1, 4):
            run_id = "evaluation-" + str(repetition)
            run_day = 2 + repetition
            if self.config["configuration_version"] == "1.1" and repetition == 3:
                run_day = 6
            date = f"2026-10-{run_day:02d}"
            at = date + "T10:30:00Z"
            run = dict(
                run_id=run_id,
                repetition=repetition,
                started_at=date + "T10:00:00Z",
                completed_at=date + "T11:00:00Z",
                operations=[],
            )
            exposures = []
            for case in cases:
                op = (
                    "qualop-" + sha256_bytes((run_id + case["case_id"]).encode())[:24]
                    if self.config["configuration_version"] == "1.1"
                    else run_id + "-" + case["case_id"]
                )
                disposition = (
                    miss[1]
                    if miss and case["case_id"] == miss[0] and repetition == 1
                    else case["expected_disposition"]
                )
                review = self.review(
                    case=case,
                    operation=op,
                    pipeline=run_id,
                    disposition=disposition,
                    purpose="qualification",
                    key=op + "-review",
                    receipt_key=op + "-receipt",
                    at=at,
                )
                operation_record = dict(
                        case_id=case["case_id"],
                        review_operation_id=op,
                        review_inventory_key=op + "-review",
                        review_sha256=self.sha(op + "-review"),
                        receipt_inventory_key=op + "-receipt",
                        receipt_sha256=self.sha(op + "-receipt"),
                    )
                if self.config["configuration_version"] == "1.1":
                    observation_key = op + "-review-service-observation"
                    operation_record.update(
                        service_observation_inventory_key=observation_key,
                        service_observation_sha256=self.sha(observation_key),
                    )
                run["operations"].append(operation_record)
                inputs = case["inputs"]
                exposures.append(
                    dict(
                        case_id=case["case_id"],
                        review_operation_id=op,
                        input_inventory_keys=sorted(
                            {"reviewer_configuration"}
                            | {
                                entry["inventory_key"]
                                for entry in (
                                    inputs["content"],
                                    inputs["source_truth_manifest"],
                                    inputs["outline"],
                                    *inputs["sources"],
                                )
                            }
                        ),
                        labels_hidden=True,
                        prior_reasoning_hidden=True,
                        fresh_context=True,
                    )
                )
                adjudication = dict(
                    case_id=case["case_id"],
                    run_id=run_id,
                    review_operation_id=op,
                    review_sha256=self.sha(op + "-review"),
                    critical_truth_sha256=case["critical_truth_sha256"],
                    critical_truth_satisfied=True,
                    bounded_rationale="Externally adjudicated synthetic observation.",
                    adjudicator_principal="adjudicator",
                    recorded_at=(
                        date + "T18:00:00Z"
                        if self.config["configuration_version"] == "1.1"
                        and repetition == 3
                        else date + "T10:40:00Z"
                    ),
                )
                self.write(op + "-adjudication", adjudication, protected=True)
                self.index["adjudications"].append(
                    dict(
                        operation_id=op + "-adjudicate",
                        actor_principal="adjudicator",
                        subject_inventory_key=op + "-adjudication",
                        subject_sha256=self.sha(op + "-adjudication"),
                    )
                )
                result_array = self.qualification[
                    "golden_results" if case in corpus["cases"] else "holdout_results"
                ]
                if repetition == 1:
                    result_array.append(
                        dict(
                            case_id=case["case_id"],
                            expected_disposition=case["expected_disposition"],
                            expected_critical_truth_sha256=case[
                                "critical_truth_sha256"
                            ],
                            observations=[],
                            hard_miss=False,
                        )
                    )
                result = next(
                    r for r in result_array if r["case_id"] == case["case_id"]
                )
                result["observations"].append(
                    dict(
                        run_id=run_id,
                        review_operation_id=op,
                        observed_disposition=disposition,
                        critical_truth_satisfied=True,
                        adjudication_inventory_key=op + "-adjudication",
                        adjudication_sha256=self.sha(op + "-adjudication"),
                    )
                )
                result["hard_miss"] |= disposition != case["expected_disposition"]
            self.qualification["qualification_runs"].append(run)
            self.index["qualification_runs"].append(
                dict(run_id=run_id, operations=exposures)
            )
        self.qualification["disposition"] = "NOT_QUALIFIED" if miss else "QUALIFIED"
        self.write_qualification()
        if self.config["configuration_version"] == "1.1":
            self.qualification_approval()
            return
        self.receipt(
            "qualification_approval_receipt",
            "qualification",
            "reviewer_qualification",
            dict(
                reviewer_configuration=self.sha("reviewer_configuration"),
                qualification_corpus=self.sha("qualification_corpus"),
                blind_holdout_truth=self.sha("blind_holdout_truth"),
                corpus_approval_receipt=self.sha("corpus_approval_receipt"),
            ),
            "qual-approval",
            "approver",
        )
