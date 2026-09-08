"""Install the Practice Work Order Skill with staging and rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


SKILL_NAME = "practice-task-workorder-generator"
SKILL_VERSION = "2.2.0"
CONTENT_CONTRACT_VERSION = "1.1"
TEMPLATE_VERSION = "1.0.0"
INSTALL_MANIFEST = Path("install-manifest.json")
SHARED_SCHEMA = Path("schemas/shared/practice-task-contract.schema.json")
REQUIRED = (
    "简介.md",
    "AGENTS.md",
    "通用提示词.md",
    "SKILL.md",
    "requirements.txt",
    "manifest.yaml",
    "agents/openai.yaml",
    "schemas/work-order-content.schema.json",
    "scripts/content_contract.py",
    "scripts/content_quality.py",
    "scripts/cross_artifact_quality.py",
    "scripts/check_dependencies.py",
    "scripts/generate_work_orders.py",
    "scripts/install.py",
    "scripts/install_adapters.py",
    "scripts/render_qa.py",
    "scripts/validate_output.py",
    "scripts/validate_template.py",
    "assets/templates/practice-work-order/v1.0.0/manifest.yaml",
    "assets/templates/practice-work-order/v1.0.0/template.docx",
)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_ignored(path: Path) -> bool:
    return path.name == INSTALL_MANIFEST.name or path.name == ".DS_Store" or path.name == "__pycache__" or path.suffix == ".pyc"


def _tree_inventory(root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"WorkOrder Skill tree contains an unsafe symlink: {path}")
        if not path.is_file() or _is_ignored(path):
            continue
        inventory[path.relative_to(root).as_posix()] = _sha256(path)
    return dict(sorted(inventory.items()))


def _source_inventory(source: Path) -> dict[str, str]:
    _required_source_files(source)
    inventory = _tree_inventory(source)
    inventory[SHARED_SCHEMA.as_posix()] = _sha256(_shared_schema_source(source))
    return dict(sorted(inventory.items()))


def _inventory_fingerprint(inventory: dict[str, str]) -> str:
    canonical = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _install_manifest_payload(inventory: dict[str, str]) -> bytes:
    payload = {
        "schema_version": 1,
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "content_contract_version": CONTENT_CONTRACT_VERSION,
        "template_version": TEMPLATE_VERSION,
        "fingerprint": _inventory_fingerprint(inventory),
        "files": inventory,
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _backup_path(root: Path) -> Path:
    while True:
        path = root / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}"
        if not _exists(path):
            return path


def _shared_schema_source(source: Path) -> Path:
    candidates = (
        source / SHARED_SCHEMA,
        source.parents[1] / SHARED_SCHEMA,
        source.parents[2] / SHARED_SCHEMA,
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise FileNotFoundError(
        "canonical shared Practice Task schema is missing; expected schemas/shared/practice-task-contract.schema.json"
    )


def _required_source_files(source: Path) -> list[Path]:
    missing = [source / relative for relative in REQUIRED if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(str(path) for path in missing))
    return [source / relative for relative in REQUIRED]


def _verify_stage(source: Path, stage: Path, shared_source: Path) -> None:
    for relative in REQUIRED:
        source_file, staged_file = source / relative, stage / relative
        if not staged_file.is_file():
            raise RuntimeError(f"staged installation is missing required file: {relative}")
        if _sha256(source_file) != _sha256(staged_file):
            raise RuntimeError(f"staged installation integrity check failed: {relative}")
    staged_shared = stage / SHARED_SCHEMA
    if not staged_shared.is_file() or _sha256(shared_source) != _sha256(staged_shared):
        raise RuntimeError("staged installation integrity check failed: canonical shared Practice Task schema")


def _remove(path: Path | None) -> None:
    if path is None or not _exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def inspect_installation(source: Path, skills_root: Path) -> dict[str, object]:
    """Compare the source tree with its installed copy without changing files."""

    source = source.expanduser().resolve()
    skills_root = skills_root.expanduser().resolve()
    target = skills_root / SKILL_NAME
    report: dict[str, object] = {
        "skill": SKILL_NAME,
        "source": str(source),
        "target": str(target),
        "status": "missing",
        "expected_fingerprint": None,
        "actual_fingerprint": None,
        "missing": [],
        "mismatched": [],
        "extra": [],
        "reason": None,
    }
    if not _exists(target):
        report["reason"] = "installed WorkOrder Skill is missing"
        return report
    if target.is_symlink() or not target.is_dir():
        report["status"] = "inconsistent"
        report["reason"] = "installed WorkOrder Skill target is not a real directory"
        return report
    try:
        expected = _source_inventory(source)
        actual = _tree_inventory(target)
    except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
        report["status"] = "inconsistent"
        report["reason"] = f"inventory unavailable: {exc}"
        return report
    expected_fingerprint = _inventory_fingerprint(expected)
    actual_fingerprint = _inventory_fingerprint(actual)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(relative for relative in set(expected) & set(actual) if expected[relative] != actual[relative])
    report["expected_fingerprint"] = expected_fingerprint
    report["actual_fingerprint"] = actual_fingerprint
    report["missing"] = missing
    report["mismatched"] = mismatched
    report["extra"] = extra
    if missing or extra or mismatched:
        report["status"] = "stale" if not extra and not mismatched else "inconsistent"
        report["reason"] = "installed WorkOrder Skill files do not match the source inventory"
        return report
    state_path = target / INSTALL_MANIFEST
    if state_path.is_symlink() or not state_path.is_file():
        report["status"] = "stale"
        report["reason"] = "installed WorkOrder Skill has no formal install manifest"
        return report
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        report["status"] = "inconsistent"
        report["reason"] = "formal install manifest is unreadable"
        return report
    if not isinstance(state, dict):
        report["status"] = "inconsistent"
        report["reason"] = "formal install manifest is not an object"
        return report
    if (
        state.get("schema_version") != 1
        or state.get("skill") != SKILL_NAME
        or state.get("skill_version") != SKILL_VERSION
        or state.get("content_contract_version") != CONTENT_CONTRACT_VERSION
        or state.get("template_version") != TEMPLATE_VERSION
        or state.get("files") != expected
        or state.get("fingerprint") != expected_fingerprint
    ):
        report["status"] = "inconsistent"
        report["reason"] = "formal install manifest is inconsistent with the installed files"
        return report
    report["status"] = "current"
    return report


def install(
    source: Path,
    skills_dir: Path,
    *,
    replace: bool = False,
    dry_run: bool = False,
    keep_backup: bool = False,
) -> Path:
    source = source.expanduser().resolve()
    skills_dir = skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME
    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError(source)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and target must not overlap")
    _required_source_files(source)
    shared_source = _shared_schema_source(source)
    if _exists(target) and not replace:
        raise FileExistsError(f"target exists: {target}; use --replace")
    if skills_dir.exists() and skills_dir.is_symlink():
        raise ValueError(f"refusing to install through symlinked directory: {skills_dir}")
    print(f"source={source}")
    print(f"target={target}")
    print(f"shared_schema={shared_source}")
    if dry_run:
        print("dry-run=yes (no filesystem mutation)")
        return target

    skills_dir.mkdir(parents=True, exist_ok=True)
    stage: Path | None = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(skills_dir)))
    stage.rmdir()
    backup = _backup_path(skills_dir) if _exists(target) else None
    moved_backup = False
    operation_error: BaseException | None = None
    try:
        shutil.copytree(
            source,
            stage,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        shared_target = stage / SHARED_SCHEMA
        shared_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_source, shared_target)
        _verify_stage(source, stage, shared_source)
        source_inventory = _source_inventory(source)
        if _tree_inventory(stage) != source_inventory:
            raise RuntimeError("staged installation integrity check failed: source inventory mismatch")
        (stage / INSTALL_MANIFEST).write_bytes(_install_manifest_payload(source_inventory))
        if backup is not None:
            os.replace(str(target), str(backup))
            moved_backup = True
        try:
            os.replace(str(stage), str(target))
            stage = None
        except Exception as commit_error:
            if moved_backup and not _exists(target):
                os.replace(str(backup), str(target))
                moved_backup = False
            raise RuntimeError(f"installation commit failed; previous installation restored: {commit_error}") from commit_error
        print(f"installed={target}")
        if backup is not None and not keep_backup:
            _remove(backup)
        return target
    except BaseException as exc:
        operation_error = exc
        raise
    finally:
        try:
            _remove(stage)
        except Exception as cleanup_error:  # pragma: no cover - filesystem-specific
            message = f"staging cleanup failed; residual path: {stage}: {cleanup_error}"
            print("WARNING: " + message, file=sys.stderr)
            if operation_error is not None:
                operation_error.add_note(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--keep-backup",
        action="store_true",
        help="retain the previous installation after a successful replacement",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--doctor", action="store_true", help="Compare the installed Skill with this source tree without changing files.")
    parser.add_argument("--json", action="store_true", help="Print doctor output as JSON.")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if args.doctor:
        report = inspect_installation(source, args.skills_dir)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"skill={report['skill']}")
            print(f"status={report['status']}")
            if report.get("reason"):
                print(f"reason={report['reason']}")
            if report.get("expected_fingerprint"):
                print(f"source_fingerprint={report['expected_fingerprint']}")
            if report.get("actual_fingerprint"):
                print(f"installed_fingerprint={report['actual_fingerprint']}")
        raise SystemExit(0 if report["status"] == "current" else 1)
    install(
        source,
        args.skills_dir,
        replace=args.replace,
        dry_run=args.dry_run,
        keep_backup=args.keep_backup,
    )


if __name__ == "__main__":
    main()
