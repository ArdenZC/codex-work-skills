"""Opt-in deterministic Semantic Scope Review records; no production integration.

TrustContext must be supplied by an operator-controlled caller. These helpers
verify process records; they cannot establish filesystem ACLs or human identity.
Candidate metadata is never used to select the profile, pin or operation index.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import unicodedata

from lifecycle_digest import (
    LifecycleContractError,
    assert_distinct_safe_paths,
    canonical_json_bytes,
    schema_errors,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
)


class RecordError(LifecycleContractError):
    """Invalid evidence or authority (never a semantic judgment)."""


class StaleEvidence(RecordError):
    """Structurally valid evidence bound to changed input bytes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def stamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RecordError("invalid date-time") from exc
    require(
        result.tzinfo is not None and result.utcoffset() is not None,
        "timezone required",
    )
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        require(normalized not in result, "duplicate/NFC-colliding JSON keys")
        result[normalized] = value
    return result


def _number(value: str) -> None:
    raise RecordError("floating/non-finite JSON numbers prohibited")


def parse(raw: bytes, *, allow_floats: bool = True) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=float if allow_floats else _number,
            parse_constant=_number,
        )
    except (UnicodeError, ValueError) as exc:
        raise RecordError(f"invalid JSON bytes: {exc}") from exc


@lru_cache(maxsize=1024)
def _schema_check(raw: bytes, schema: str, schema_digest: str) -> tuple[str, ...]:
    return tuple(schema_errors(parse(raw, allow_floats=False), schema + ".schema.json"))


def checked(raw: bytes, schema: str) -> dict[str, Any]:
    # Cache only validation of exact bytes under exact schema bytes. Authority,
    # file hashes and time are always reread; callers receive a new mutable DTO.
    schema_path = (
        Path(__file__).resolve().parents[1] / "schemas" / (schema + ".schema.json")
    )
    errors = _schema_check(raw, schema, sha256_bytes(schema_path.read_bytes()))
    require(not errors, "; ".join(errors))
    return parse(raw, allow_floats=False)


def review_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(
        payload, excluded_fields={"reviewed_at", "review_fingerprint"}
    )


def qualification_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(
        payload, excluded_fields={"qualified_at", "qualification_fingerprint"}
    )


def configuration_fingerprint(raw: bytes) -> str:
    payload = checked(raw, "reviewer-configuration")
    require(
        raw == canonical_json_bytes(payload),
        "configuration bytes must be canonical UTF-8 NFC JSON",
    )
    return sha256_bytes(raw)


def receipt_fingerprint(raw: bytes) -> str:
    """Receipts bind raw bytes; the contract defines no excluded-field cache."""
    checked(raw, "operation-provenance-receipt")
    return sha256_bytes(raw)


@dataclass(frozen=True)
class Inventory:
    """Explicit controller-supplied dependency inventory and allowed roots.

    Roots and paths are configuration, never discovered in a candidate folder.
    The complete inventory is validated for ordinary, non-aliased files; raw
    hashes are reread whenever referenced. A shared dependency reuses one key.
    """

    entries: Mapping[str, Mapping[str, Any]]
    run_root: Path
    protected_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entries", {key: dict(row) for key, row in self.entries.items()}
        )
        errors = schema_errors(
            {"inventory_version": "1.0", "entries": list(self.entries.values())},
            "semantic-dependency-inventory.schema.json",
        )
        require(not errors, "; ".join(errors))
        require(
            all(key == row["inventory_key"] for key, row in self.entries.items()),
            "inventory key mismatch",
        )
        require(bool(self.protected_roots), "explicit protected repositories required")
        run = self.run_root.resolve(strict=True)
        for root in self.protected_roots:
            assert_distinct_safe_paths({"protected_root": root})
            protected = root.resolve(strict=True)
            require(
                not protected.is_relative_to(run) and not run.is_relative_to(protected),
                "protected repository overlaps candidate root",
            )
        paths: dict[str, Path] = {}
        for key, row in self.entries.items():
            path = Path(row["path"])
            require(
                path.is_absolute(),
                "inventory paths must be absolute controller-selected paths",
            )
            roots = (
                (self.run_root,)
                if row["storage_class"] == "run"
                else self.protected_roots
            )
            require(
                any(
                    path.resolve(strict=True).is_relative_to(r.resolve(strict=True))
                    for r in roots
                ),
                f"inventory path outside configured storage: {key}",
            )
            paths[key] = path
            sha256_file(path)  # ordinary file and existing path/alias protections
        assert_distinct_safe_paths(paths)
        object.__setattr__(
            self,
            "entries",
            MappingProxyType(
                {key: MappingProxyType(row) for key, row in self.entries.items()}
            ),
        )

    def namespace(self, aliases: Mapping[str, str]) -> Inventory:
        """A subset/rename view over already checked paths; introduce no new files.

        This avoids repeating quadratic alias checks for every evaluation case.
        Every subsequent read still performs ordinary-file checks and raw hashes.
        """
        require(
            all(key in self.entries for key in aliases.values()),
            "unknown case input key",
        )
        require(len(set(aliases.values())) == len(aliases), "aliased case inputs")
        entries = {
            key: dict(row)
            for key, row in self.entries.items()
            if key not in set(aliases) | set(aliases.values())
        }
        for canonical, original in aliases.items():
            entries[canonical] = {**self.entries[original], "inventory_key": canonical}
        view = object.__new__(Inventory)
        object.__setattr__(
            view,
            "entries",
            MappingProxyType(
                {key: MappingProxyType(row) for key, row in entries.items()}
            ),
        )
        object.__setattr__(view, "run_root", self.run_root)
        object.__setattr__(view, "protected_roots", self.protected_roots)
        return view

    def raw(
        self, key: str, expected: str | None = None, *, protected: bool = False
    ) -> bytes:
        require(key in self.entries, f"missing inventory entry: {key}")
        row = self.entries[key]
        require(
            not protected or row["storage_class"] == "protected_external",
            f"not protected evidence: {key}",
        )
        path = Path(row["path"])
        digest = sha256_file(path)
        raw = path.read_bytes()
        require(sha256_bytes(raw) == digest, f"file changed while reading: {key}")
        if digest != row["sha256"] or (expected is not None and digest != expected):
            raise StaleEvidence(f"changed raw-byte binding: {key}")
        return raw

    def by_sha(self, digest: str, *, protected: bool = False) -> bytes:
        keys = [
            k
            for k, row in self.entries.items()
            if row["sha256"] == digest
            and (not protected or row["storage_class"] == "protected_external")
        ]
        require(bool(keys), f"SHA has no actual inventory dependency: {digest}")
        return self.raw(keys[0], digest, protected=protected)

    def record(
        self, key: str, schema: str, *, protected: bool = False
    ) -> dict[str, Any]:
        return checked(self.raw(key, protected=protected), schema)


@dataclass(frozen=True)
class TrustContext:
    inventory: Inventory
    profile_path: Path
    profile_pin: str
    policy_epoch: int
    operation_index_path: Path
    controller_allowlist: tuple[tuple[str, str, str], ...]
    now: datetime

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        require(
            self.now.tzinfo is not None and self.now.utcoffset() is not None,
            "current check needs timezone",
        )
        for path in (self.profile_path, self.operation_index_path):
            require(
                any(
                    path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
                    for root in self.inventory.protected_roots
                ),
                "authority input outside protected repository",
            )
        assert_distinct_safe_paths(
            {"profile": self.profile_path, "index": self.operation_index_path}
        )
        require(
            sha256_file(self.profile_path) == self.profile_pin,
            "operator profile pin changed: INVALID authority",
        )
        profile = checked(self.profile_path.read_bytes(), "operator-authority-profile")
        require(
            profile["policy_epoch"] == self.policy_epoch,
            "stale policy epoch: INVALID authority",
        )
        require(
            (
                profile["controller_id"],
                profile["controller_implementation"],
                profile["controller_version"],
            )
            in self.controller_allowlist,
            "controller implementation/version not operator-allowlisted",
        )
        require(
            self.inventory.raw("authority_profile", self.profile_pin, protected=True)
            == self.profile_path.read_bytes(),
            "inventory profile differs from launch policy",
        )
        index_raw = self.inventory.raw("operation_index", protected=True)
        require(
            index_raw == self.operation_index_path.read_bytes(),
            "protected index path mismatch",
        )
        index = checked(index_raw, "protected-operation-index")
        require(
            index["controller_id"] == profile["controller_id"]
            and index["policy_epoch"] == self.policy_epoch,
            "protected index controller/epoch mismatch",
        )
        for field in (
            "operator_reference",
            "ingress_procedure_reference",
            "evidence_repository_reference",
        ):
            self.inventory.raw(profile[field], protected=True)
        principals = [r["principal_id"] for r in profile["roles"]]
        require(len(principals) == len(set(principals)), "duplicate profile principals")
        for row in profile["roles"]:
            require(
                stamp(row["valid_from"]) < stamp(row["valid_until"]),
                "invalid role validity",
            )
            require(
                row["revoked_at"] is None or row["revocation_reason"] is not None,
                "revocation requires reason",
            )
            authorization = checked(
                self.inventory.raw(row["authorization_reference"], protected=True),
                "operator-role-authorization",
            )
            require(
                authorization["principal_id"] == row["principal_id"]
                and set(authorization["allowed_roles"]) == set(row["allowed_roles"]),
                "operator role authorization mismatch",
            )
        for field, id_field in (
            ("receipts", "receipt_id"),
            ("authors", "authoring_id"),
            ("adjudications", "operation_id"),
            ("qualification_runs", "run_id"),
        ):
            ids = [r[id_field] for r in index[field]]
            require(len(ids) == len(set(ids)), f"duplicate protected index {field}")
        operations = [
            r["operation_id"]
            for group in ("receipts", "authors", "adjudications")
            for r in index[group]
        ]
        require(
            len(operations) == len(set(operations)), "reused protected operation ID"
        )
        return profile, index

    def not_revoked(self, *identifiers: str) -> None:
        profile, _ = self.load()
        require(
            not set(identifiers).intersection(profile["revoked_authority_ids"]),
            "revoked authority ID",
        )

    def role(
        self,
        principal: str,
        role: str,
        at: datetime | None = None,
        *,
        current_validity: bool = True,
    ) -> dict[str, Any]:
        profile, _ = self.load()
        rows = [r for r in profile["roles"] if r["principal_id"] == principal]
        require(
            len(rows) == 1 and role in rows[0]["allowed_roles"],
            f"{principal} lacks {role} role",
        )
        row = rows[0]
        require(
            not {principal, row["authorization_reference"]}.intersection(
                profile["revoked_authority_ids"]
            ),
            "revoked authority ID",
        )
        require(row["revoked_at"] is None, "revoked principal role")
        checks = [at or self.now]
        if current_validity:
            checks.append(self.now)
        require(
            all(
                stamp(row["valid_from"]) <= t < stamp(row["valid_until"])
                for t in checks
            ),
            "expired/not-yet-valid role",
        )
        return row


def validate_configuration(
    inventory: Inventory, key: str = "reviewer_configuration"
) -> dict[str, Any]:
    raw = inventory.raw(key)
    configuration_fingerprint(raw)
    config = checked(raw, "reviewer-configuration")
    build = checked(
        inventory.by_sha(config["implementation_build_sha256"]),
        "reviewer-build-inventory",
    )
    for entry in build["files"]:
        inventory.raw(entry["inventory_key"], entry["sha256"])
    inventory.by_sha(config["context_policy"]["policy_sha256"])
    if config["reviewer_type"] == "agent":
        agent = config["agent"]
        # Mutable aliases are not immutable revisions. Other revisions are opaque,
        # provider-neutral pins; their service meaning belongs to controlled setup.
        require(
            agent["model_revision"].strip().casefold()
            not in {"latest", "default", "current", "auto", "unversioned"},
            "unpinned mutable model revision",
        )
        names = [p["name"] for p in agent["decoding"]["additional_parameters"]]
        require(len(names) == len(set(names)), "duplicate decoding parameter")
        fields = (
            "semantic_prompt_sha256",
            "system_instructions_sha256",
            "tool_permissions_sha256",
        )
    else:
        agent = config["human"]
        fields = ("procedure_sha256", "interface_policy_sha256")
    for field in fields:
        inventory.by_sha(agent[field])
    return config


def validate_training(
    context: TrustContext,
    qualification: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    author_principal: str | None = None,
) -> dict[str, Any]:
    human = qualification["human_authority"]
    raw = context.inventory.raw(
        "human_training_authorization",
        human["training_authorization_sha256"],
        protected=True,
    )
    training = checked(raw, "human-training-authorization")
    principal = human["principal_id"]
    require(training["principal_id"] == principal, "training subject mismatch")
    role = context.role(
        principal, "scope_reviewer", stamp(qualification["qualified_at"])
    )
    require(
        human["teacher_authority_reference"] == role["authorization_reference"],
        "human authorization reference mismatch",
    )
    context.inventory.raw(human["teacher_authority_reference"], protected=True)
    for field in ("procedure_id", "procedure_version", "procedure_sha256"):
        require(
            training[field] == human[field] == config["human"][field],
            f"training {field} mismatch",
        )
    context.inventory.raw(
        "human_procedure", training["procedure_sha256"], protected=True
    )
    require(
        stamp(training["issued_at"])
        <= stamp(training["valid_from"])
        < stamp(training["valid_until"]),
        "training validity order",
    )
    require(
        stamp(training["valid_from"]) <= context.now < stamp(training["valid_until"]),
        "training expired/not-yet-valid",
    )
    require(
        stamp(training["valid_from"])
        <= stamp(qualification["qualified_at"])
        < stamp(training["valid_until"]),
        "training not valid at qualification completion",
    )
    require(training["revoked_at"] is None, "training revoked")
    require(
        training["issuer_principal"] not in {principal, author_principal},
        "training self/author issuance",
    )
    context.role(
        training["issuer_principal"],
        "qualification_approver",
        stamp(training["issued_at"]),
        current_validity=False,
    )
    context.not_revoked(
        training["authorization_id"], training["authorization_reference"]
    )
    context.inventory.raw(training["authorization_reference"], protected=True)
    return training
