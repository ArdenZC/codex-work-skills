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

from path_safety import paths_overlap


SKILL_NAME = "lesson-plan-docx-generator"
SKILL_VERSION = "2.2.1"
CONTENT_CONTRACT_VERSION = "2.2"
TEMPLATE_VERSION = "1.1.2"
INSTALL_MANIFEST = Path("install-manifest.json")
SHARED_SCHEMA = Path("schemas/shared/practice-task-contract.schema.json")
REQUIRED_RELATIVE_FILES = (
    Path("SKILL.md"),
    Path("通用提示词.md"),
    Path("AGENTS.md"),
    Path("agents/openai.yaml"),
    Path("manifest.yaml"),
    Path("docs/intake-contract-v2.1.1.json"),
    Path("requirements.txt"),
    Path("scripts/generate_lesson_plans.py"),
    Path("scripts/content_contract.py"),
    Path("scripts/content_quality.py"),
    Path("scripts/package_common.py"),
    Path("scripts/path_safety.py"),
    Path("scripts/validate_output.py"),
    Path("scripts/validate_template.py"),
    Path("scripts/render_qa.py"),
    Path("scripts/semantic_bookmarks.py"),
    Path("scripts/bookmark_utils.py"),
    Path("scripts/check_dependencies.py"),
    Path("scripts/install.py"),
    Path("scripts/install_adapters.py"),
    Path("schemas/lesson-plan-input.schema.json"),
    Path("schemas/practice-task-contract.schema.json"),
    Path("assets/templates/lesson-plan/v1.1.2/manifest.yaml"),
    Path("assets/templates/lesson-plan/v1.1.2/template.docx"),
)


def default_skills_dir() -> Path:
    return Path.home() / ".codex" / "skills"


def ignore_patterns(_dir: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".DS_Store"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _unique_backup_path(target_root: Path) -> Path:
    while True:
        candidate = target_root / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}"
        if not _exists(candidate):
            return candidate


def _required_source_files(source: Path) -> list[Path]:
    missing = [source / relative for relative in REQUIRED_RELATIVE_FILES if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError(
            "Lesson Skill source is incomplete; missing required files: "
            + ", ".join(str(path) for path in missing)
        )
    shared_candidates = (source / SHARED_SCHEMA, source.parents[1] / SHARED_SCHEMA, source.parents[2] / SHARED_SCHEMA)
    shared = next((candidate for candidate in shared_candidates if candidate.is_file() and not candidate.is_symlink()), None)
    if shared is None:
        raise FileNotFoundError(
            "Lesson Skill source is missing canonical shared Practice Task schema: "
            "schemas/shared/practice-task-contract.schema.json"
        )
    return [*(source / relative for relative in REQUIRED_RELATIVE_FILES), shared]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_ignored(path: Path) -> bool:
    return path.name == "__pycache__" or path.name == ".DS_Store" or path.name.endswith(".pyc")


def _shared_source(source: Path) -> Path:
    candidates = (
        source / SHARED_SCHEMA,
        source.parents[1] / SHARED_SCHEMA,
        source.parents[2] / SHARED_SCHEMA,
    )
    shared = next(
        (candidate for candidate in candidates if candidate.is_file() and not candidate.is_symlink()),
        None,
    )
    if shared is None:
        raise FileNotFoundError(
            "Lesson Skill source is missing canonical shared Practice Task schema: "
            "schemas/shared/practice-task-contract.schema.json"
        )
    return shared


def _tree_inventory(root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Lesson Skill tree contains an unsafe symlink: {path}")
        if not path.is_file() or _is_ignored(path):
            continue
        relative = path.relative_to(root).as_posix()
        if relative == INSTALL_MANIFEST.as_posix():
            continue
        inventory[relative] = _sha256(path)
    return dict(sorted(inventory.items()))


def _source_inventory(source: Path) -> dict[str, str]:
    """Hash all installable source bytes, including the canonical shared schema."""

    _required_source_files(source)
    inventory = _tree_inventory(source)
    shared = _shared_source(source)
    inventory[SHARED_SCHEMA.as_posix()] = _sha256(shared)
    return dict(sorted(inventory.items()))


def _inventory_fingerprint(inventory: dict[str, str]) -> str:
    canonical = json.dumps(
        inventory,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
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


def _verify_stage(source: Path, stage: Path) -> None:
    for relative in REQUIRED_RELATIVE_FILES:
        source_file, staged_file = source / relative, stage / relative
        if not staged_file.is_file():
            raise RuntimeError(f"staged installation is missing required file: {relative}")
        if _sha256(source_file) != _sha256(staged_file):
            raise RuntimeError(f"staged installation integrity check failed: {relative}")
    shared_source = _shared_source(source)
    staged_shared = stage / SHARED_SCHEMA
    if shared_source is None or not staged_shared.is_file() or _sha256(shared_source) != _sha256(staged_shared):
        raise RuntimeError("staged installation integrity check failed: canonical shared Practice Task schema")
    source_inventory = _source_inventory(source)
    staged_inventory = _tree_inventory(stage)
    staged_inventory[SHARED_SCHEMA.as_posix()] = _sha256(staged_shared)
    if staged_inventory != source_inventory:
        raise RuntimeError("staged installation integrity check failed: source inventory mismatch")


def inspect_installation(source: Path, skills_root: Path) -> dict[str, object]:
    """Compare a source tree with its installed copy without mutating either."""

    source = _absolute(source)
    skills_root = _absolute(skills_root)
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
        report["reason"] = "installed Lesson Skill is missing"
        return report
    if target.is_symlink() or not target.is_dir():
        report["status"] = "inconsistent"
        report["reason"] = "installed Lesson Skill target is not a real directory"
        return report
    try:
        expected = _source_inventory(source)
    except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
        report["status"] = "inconsistent"
        report["reason"] = f"source inventory unavailable: {exc}"
        return report
    try:
        actual = _tree_inventory(target)
    except (OSError, ValueError) as exc:
        report["status"] = "inconsistent"
        report["reason"] = f"installed Lesson Skill tree is unsafe or unreadable: {exc}"
        return report
    state_path = target / INSTALL_MANIFEST
    state: dict[str, object] | None = None
    try:
        if state_path.is_symlink():
            state = None
        elif state_path.is_file():
            loaded_state = json.loads(state_path.read_text(encoding="utf-8"))
            state = loaded_state if isinstance(loaded_state, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        state = None
    state_inventory = state.get("files") if isinstance(state, dict) else None
    state_matches_actual = (
        isinstance(state_inventory, dict)
        and state_inventory == actual
        and state.get("fingerprint") == _inventory_fingerprint(actual)
    )
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(relative for relative in set(expected) & set(actual) if expected[relative] != actual[relative])
    report["expected_fingerprint"] = _inventory_fingerprint(expected)
    report["actual_fingerprint"] = _inventory_fingerprint(actual)
    report["missing"] = missing
    report["mismatched"] = mismatched
    report["extra"] = extra
    if missing or extra or mismatched:
        if state_matches_actual or (
            not state_path.exists()
            and not state_path.is_symlink()
            and not extra
            and not mismatched
        ):
            report["status"] = "stale"
            report["reason"] = "source inventory is newer than the installed Lesson Skill"
        else:
            report["status"] = "inconsistent"
            report["reason"] = "installed Lesson Skill files do not match the source inventory"
        return report
    if state_path.is_symlink() or not state_path.is_file():
        report["status"] = "stale"
        report["reason"] = "installed Lesson Skill has no formal install manifest"
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
        or state.get("fingerprint") != _inventory_fingerprint(expected)
    ):
        report["status"] = "inconsistent"
        report["reason"] = "formal install manifest is inconsistent with the installed files"
        return report
    report["status"] = "current"
    return report


def _preflight(source: Path, target_root: Path, target: Path, replace: bool) -> None:
    """Perform every rejecting check before the first filesystem mutation."""

    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError(f"Lesson Skill source directory not found: {source}")
    _required_source_files(source)
    if paths_overlap(source, target_root) or paths_overlap(source, target):
        raise ValueError(f"Source and installation target must not overlap: {source} / {target_root}")
    if _exists(target):
        if target.is_dir() and target.is_symlink():
            raise ValueError(f"Refusing to install through a symlink target: {target}")
        if not replace:
            raise FileExistsError(
                f"Target already exists: {target}. Re-run with --replace to back it up and replace it."
            )
    if target_root.is_symlink():
        raise ValueError(f"Refusing to install through a symlink installation root: {target_root}")
    if target_root.exists() and not target_root.is_dir():
        raise NotADirectoryError(f"Installation root is not a directory: {target_root}")


def _remove_stage(stage: Path | None) -> str | None:
    if stage is None:
        return None
    try:
        if stage.is_symlink():
            stage.unlink()
        elif stage.is_dir():
            shutil.rmtree(stage)
        elif stage.exists():
            stage.unlink()
    except Exception as exc:  # pragma: no cover - filesystem failures vary by platform
        return f"cleanup failed for staging directory: {exc}; residual path: {stage}"
    return None


def install(source: Path, target_root: Path, *, replace: bool = False, dry_run: bool = False) -> Path:
    source = _absolute(source)
    target_root = _absolute(target_root)
    target = target_root / SKILL_NAME
    _preflight(source, target_root, target, replace)
    inventory = _source_inventory(source)
    backup = _unique_backup_path(target_root) if _exists(target) else None
    print(f"source={source}")
    print(f"target={target}")
    if backup is not None:
        print(f"backup={backup}")
    if dry_run:
        print("dry-run=yes (no filesystem mutation)")
        return target

    target_root.mkdir(parents=True, exist_ok=True)
    stage: Path | None = None
    moved_backup = False
    operation_error: BaseException | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(target_root)))
        stage.rmdir()
        shutil.copytree(source, stage, ignore=ignore_patterns, symlinks=False)
        shared_candidates = (source / SHARED_SCHEMA, source.parents[1] / SHARED_SCHEMA, source.parents[2] / SHARED_SCHEMA)
        shared_source = next((candidate for candidate in shared_candidates if candidate.is_file() and not candidate.is_symlink()), None)
        if shared_source is None:
            raise FileNotFoundError("canonical shared Practice Task schema is unavailable")
        shared_target = stage / SHARED_SCHEMA
        shared_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_source, shared_target)
        _verify_stage(source, stage)
        (stage / INSTALL_MANIFEST).write_bytes(_install_manifest_payload(inventory))
        if backup is not None:
            os.replace(str(target), str(backup))
            moved_backup = True
        try:
            os.replace(str(stage), str(target))
            stage = None
        except Exception as commit_error:
            rollback_error: Exception | None = None
            if moved_backup:
                try:
                    if _exists(target):
                        if target.is_dir() and not target.is_symlink():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    os.replace(str(backup), str(target))
                    moved_backup = False
                except Exception as exc:  # pragma: no cover - filesystem-specific
                    rollback_error = exc
            detail = f"installation commit failed: {commit_error}"
            detail += (
                f"; rollback failed: {rollback_error}; backup retained at {backup}"
                if rollback_error is not None
                else "; previous installation restored"
            )
            raise RuntimeError(detail) from commit_error
        print(f"installed={target}")
        return target
    except BaseException as exc:
        operation_error = exc
        raise
    finally:
        try:
            cleanup_error = _remove_stage(stage)
        except Exception as exc:  # pragma: no cover - defensive for injected cleanup failures
            cleanup_error = f"cleanup failed for staging directory: {exc}; residual path: {stage}"
        if cleanup_error:
            print(f"WARNING: {cleanup_error}", file=sys.stderr)
            if operation_error is not None:
                operation_error.add_note(cleanup_error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install lesson-plan-docx-generator into the local Codex skills directory.")
    parser.add_argument("--skills-dir", default=str(default_skills_dir()), help="Target Codex skills directory. Defaults to ~/.codex/skills.")
    parser.add_argument("--replace", action="store_true", help="Back up and replace an existing installed copy.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned paths without copying files.")
    parser.add_argument("--doctor", action="store_true", help="Compare the installed Skill with this source tree without changing files.")
    parser.add_argument("--json", action="store_true", help="Print doctor output as JSON.")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    if args.doctor:
        report = inspect_installation(source, Path(args.skills_dir))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"skill={report['skill']}")
            print(f"status={report['status']}")
            if report.get("reason"):
                print(f"reason={report['reason']}")
        raise SystemExit(0 if report["status"] == "current" else 1)
    install(source, Path(args.skills_dir), replace=args.replace, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
