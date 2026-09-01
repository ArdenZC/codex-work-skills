"""Transactional, namespaced project-adapter installer for the Lesson Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from path_safety import paths_overlap


ENGINE_NAME = ".lesson-plan-docx-generator"
ENGINE_STATE_FILE = Path(".engine-state.json")
ENGINE_STATE_SCHEMA_VERSION = 1
CONTENT_CONTRACT_VERSION = "2.1"
MARKER_ID = "lesson-plan-docx-generator"
MARKER_START = f"<!-- codex-skill: {MARKER_ID}:start -->"
MARKER_END = f"<!-- codex-skill: {MARKER_ID}:end -->"
MINIMAL_ENGINE_FILES = (
    Path("SKILL.md"),
    Path("通用提示词.md"),
    Path("AGENTS.md"),
    Path("CONVENTIONS.md"),
)
FULL_ENGINE_RUNTIME_FILES = (
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
    Path("schemas/lesson-plan-input.schema.json"),
    Path("schemas/practice-task-contract.schema.json"),
    Path("assets/templates/lesson-plan/v1.1.2/manifest.yaml"),
    Path("assets/templates/lesson-plan/v1.1.2/template.docx"),
)
# Kept as a compatibility name for callers that inspected the old sentinel
# tuple; it now represents the complete health inventory rather than three
# representative files.
FULL_ENGINE_SENTINELS = FULL_ENGINE_RUNTIME_FILES
FULL_ENGINE_INVENTORY_FILES = tuple(dict.fromkeys((*MINIMAL_ENGINE_FILES, *FULL_ENGINE_RUNTIME_FILES)))
REFERENCE_TEXT_SUFFIXES = {".md", ".mdc", ".yml", ".yaml"}
RUNTIME_REFERENCE = re.compile(
    r"(?<![./\w-])"
    r"(?:(?:<skill>|lesson-plan-docx-generator|course-gradebook-generator|\.lesson-plan-docx-generator|\.course-gradebook-generator)[/\\])?"
    r"((?:scripts|docs|examples|schemas|assets)/[^\s`\"'<>（）(),，。；：！？]+)"
)
SHARED_SOURCES = {
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "GEMINI.md": "GEMINI.md",
    ".github/copilot-instructions.md": ".github/copilot-instructions.md",
    "CONVENTIONS.md": "CONVENTIONS.md",
}
ADAPTER_PATHS = {
    "agents": ("AGENTS.md",),
    "claude": ("CLAUDE.md",),
    "gemini": ("GEMINI.md",),
    "cursor": (".cursor/rules/lesson-plan-generator.mdc",),
    "cline": (".clinerules/lesson-plan-generator.md",),
    "continue": (".continue/rules/lesson-plan-generator.md",),
    "windsurf": (".windsurf/rules/lesson-plan-generator.md",),
    "copilot": (".github/copilot-instructions.md",),
    "aider": ("CONVENTIONS.md", ".aider.conf.yml"),
}


def ignore_patterns(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc") or name == ".DS_Store"}


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _backup_path(path: Path) -> Path:
    while True:
        candidate = path.with_name(f"{path.name}.backup_{uuid.uuid4().hex}")
        if not _exists(candidate):
            return candidate


def _rewrite_references(text: str, *, copy_engine: bool = True, namespace: bool = True) -> str:
    """Point adapter instructions at files available in the installed engine."""

    replacements = {}
    if namespace:
        replacements.update(
            {
                "SKILL.md": f"{ENGINE_NAME}/SKILL.md",
                "通用提示词.md": f"{ENGINE_NAME}/通用提示词.md",
                "AGENTS.md": f"{ENGINE_NAME}/AGENTS.md",
                "CLAUDE.md": f"{ENGINE_NAME}/CLAUDE.md",
                "GEMINI.md": f"{ENGINE_NAME}/GEMINI.md",
                "CONVENTIONS.md": f"{ENGINE_NAME}/CONVENTIONS.md",
            }
        )
    for bare, namespaced in replacements.items():
        # Do not rewrite an already namespaced path a second time.
        text = re.sub(rf"(?<![./\w-]){re.escape(bare)}", namespaced, text)

    # Match the finite set of runtime path forms documented by this Skill,
    # including ``<skill>/scripts/...``.  Already namespaced paths are not
    # matched because the path component is preceded by ``/``.
    unavailable = "the full Lesson runtime (install with --copy-engine)"

    def replace_runtime(match: re.Match[str]) -> str:
        path = match.group(1).replace("\\", "/")
        return f"{ENGINE_NAME}/{path}" if copy_engine else unavailable

    return RUNTIME_REFERENCE.sub(replace_runtime, text)


def _payload_for_engine(source: Path, *, copy_engine: bool) -> bytes:
    if source.suffix.lower() in REFERENCE_TEXT_SUFFIXES:
        return _rewrite_references(
            source.read_text(encoding="utf-8"),
            copy_engine=copy_engine,
            namespace=False,
        ).encode("utf-8")
    return source.read_bytes()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_inventory_from_source(source_root: Path) -> dict[str, str]:
    """Hash the bytes that a full installed engine actually receives."""

    inventory: dict[str, str] = {}
    for relative in FULL_ENGINE_INVENTORY_FILES:
        source = source_root / relative
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError(f"Lesson engine source is missing or unsafe: {source}")
        inventory[relative.as_posix()] = _sha256_bytes(_payload_for_engine(source, copy_engine=True))
    return dict(sorted(inventory.items()))


def _runtime_fingerprint(inventory: dict[str, str]) -> str:
    canonical = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(canonical)


def _engine_state_payload(source_root: Path) -> bytes:
    inventory = _runtime_inventory_from_source(source_root)
    state = {
        "schema_version": ENGINE_STATE_SCHEMA_VERSION,
        "skill": "lesson-plan-docx-generator",
        "content_contract_version": CONTENT_CONTRACT_VERSION,
        "runtime_fingerprint": _runtime_fingerprint(inventory),
        "runtime_inventory": inventory,
    }
    return (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_engine_state(engine_target: Path) -> dict[str, object] | None:
    state_path = engine_target / ENGINE_STATE_FILE
    if state_path.is_symlink() or not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _installed_inventory_matches(engine_target: Path, state: dict[str, object]) -> bool:
    inventory = state.get("runtime_inventory")
    if not isinstance(inventory, dict):
        return False
    expected_keys = {relative.as_posix() for relative in FULL_ENGINE_INVENTORY_FILES}
    if set(inventory) != expected_keys:
        return False
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in inventory.values()):
        return False
    if state.get("schema_version") != ENGINE_STATE_SCHEMA_VERSION:
        return False
    if state.get("skill") != "lesson-plan-docx-generator":
        return False
    if state.get("content_contract_version") != CONTENT_CONTRACT_VERSION:
        return False
    if state.get("runtime_fingerprint") != _runtime_fingerprint(inventory):
        return False
    for relative_name, expected_hash in inventory.items():
        relative = Path(relative_name)
        path = engine_target / relative
        if path.is_symlink() or not path.is_file() or _sha256_file(path) != expected_hash:
            return False
    return True


def _marker_block(payload: str) -> str:
    body = payload.strip("\r\n")
    return f"{MARKER_START}\n{body}\n{MARKER_END}"


def merge_marker_section(existing: str, payload: str) -> str:
    """Replace this installer's marker while preserving every other section."""

    block = _marker_block(payload)
    starts = [match.start() for match in re.finditer(re.escape(MARKER_START), existing)]
    ends = [match.start() for match in re.finditer(re.escape(MARKER_END), existing)]
    if len(starts) != len(ends) or len(starts) > 1 or (starts and ends[0] < starts[0]):
        raise ValueError(f"Malformed {MARKER_ID} marker block; refusing to mutate the target")
    if starts:
        start, end = starts[0], ends[0]
        prefix = existing[:start].rstrip("\r\n")
        suffix = existing[end + len(MARKER_END) :]
        return (prefix + "\n\n" if prefix else "") + block + suffix
    if not existing.strip():
        return block + "\n"
    return existing.rstrip("\r\n") + "\n\n" + block + "\n"


def _parse_simple_aider(existing: str) -> list[str]:
    """Parse only the additive read-list subset; reject complex YAML closed."""

    lines = existing.splitlines()
    if not existing.strip():
        return []
    in_read = False
    paths: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.fullmatch(r"read\s*:\s*", stripped):
            if in_read:
                raise ValueError("complex .aider.conf.yml is not supported")
            in_read = True
            continue
        if in_read and re.fullmatch(r"-\s+[^:#]+", stripped):
            paths.append(stripped[1:].strip().strip('"\''))
            continue
        # Inline maps, other keys, anchors and nested structures require a
        # YAML-aware merge and are intentionally fail-closed.
        raise ValueError("complex or unparseable .aider.conf.yml; refusing to mutate")
    if not in_read:
        raise ValueError(".aider.conf.yml has no simple read list; refusing to mutate")
    return paths


def merge_aider_config(existing: str) -> str:
    required = [
        f"{ENGINE_NAME}/SKILL.md",
        f"{ENGINE_NAME}/通用提示词.md",
        f"{ENGINE_NAME}/AGENTS.md",
        f"{ENGINE_NAME}/CONVENTIONS.md",
    ]
    if not existing.strip():
        return "read:\n" + "".join(f"  - {item}\n" for item in required)
    paths = _parse_simple_aider(existing)
    missing = [item for item in required if item not in paths]
    if not missing:
        return existing if existing.endswith("\n") else existing + "\n"
    return existing.rstrip("\r\n") + "\n" + "".join(f"  - {item}\n" for item in missing)


def _assert_no_symlink_ancestor(target_root: Path, path: Path) -> None:
    current = path.parent
    while current != target_root.parent and current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError(f"Refusing to write through symlinked directory: {current}")
        current = current.parent


def _source_files(source_root: Path, copy_engine: bool) -> list[Path]:
    if copy_engine:
        return sorted(
            (
                path.relative_to(source_root)
                for path in source_root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.name != ENGINE_STATE_FILE.name
                and not ignore_patterns("", [path.name])
            ),
            key=lambda path: path.as_posix(),
        )
    return list(MINIMAL_ENGINE_FILES)


def _required_engine_files(source_root: Path, copy_engine: bool) -> tuple[Path, ...]:
    required = FULL_ENGINE_INVENTORY_FILES if copy_engine else MINIMAL_ENGINE_FILES
    missing = [
        source_root / relative
        for relative in required
        if (source_root / relative).is_symlink() or not (source_root / relative).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Lesson adapter source is incomplete; missing critical runtime files: "
            + ", ".join(str(path) for path in missing)
        )
    return required


def _detect_existing_engine_mode(engine_target: Path, source_root: Path | None = None) -> str:
    """Classify an existing project-local engine without following symlinks."""

    if not _exists(engine_target):
        return "none"
    if engine_target.is_symlink() or not engine_target.is_dir():
        return "inconsistent"

    def real_file(relative: Path) -> bool:
        path = engine_target / relative
        return path.is_file() and not path.is_symlink()

    minimal = all(real_file(relative) for relative in MINIMAL_ENGINE_FILES)
    full_states = [real_file(relative) for relative in FULL_ENGINE_RUNTIME_FILES]
    if minimal and all(full_states):
        state_path = engine_target / ENGINE_STATE_FILE
        if state_path.is_symlink():
            return "inconsistent"
        if not state_path.exists():
            return "full-stale"
        state = _read_engine_state(engine_target)
        if state is None or not _installed_inventory_matches(engine_target, state):
            return "inconsistent"
        if source_root is None:
            return "full-current"
        try:
            source_inventory = _runtime_inventory_from_source(source_root)
        except (FileNotFoundError, OSError, UnicodeError):
            return "full-stale"
        return (
            "full-current"
            if state.get("runtime_fingerprint") == _runtime_fingerprint(source_inventory)
            and state.get("runtime_inventory") == source_inventory
            else "full-stale"
        )
    if minimal and not any(full_states):
        return "minimal" if not (engine_target / ENGINE_STATE_FILE).exists() else "inconsistent"
    return "inconsistent"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _preflight(source_root: Path, target_root: Path, selected: list[str], copy_engine: bool) -> None:
    if not source_root.is_dir() or source_root.is_symlink():
        raise FileNotFoundError(f"Skill source directory not found: {source_root}")
    if not target_root.exists():
        return
    if not target_root.is_dir() or target_root.is_symlink():
        raise NotADirectoryError(f"Adapter target is not a real directory: {target_root}")


def build_plan(source_root: Path, target_root: Path, selected: list[str], *, replace: bool = False, copy_engine: bool = False) -> tuple[dict[Path, bytes], Path | None, list[Path]]:
    """Build all bytes and collision decisions without changing the target."""

    source_root, target_root = _absolute(source_root), _absolute(target_root)
    selected = list(ADAPTER_PATHS) if "all" in selected else list(dict.fromkeys(selected))
    if paths_overlap(source_root, target_root):
        raise ValueError(f"Adapter target must not overlap the Skill source: {target_root}")
    _required_engine_files(source_root, copy_engine)
    for name in selected:
        for relative in ADAPTER_PATHS[name]:
            source = source_root / relative
            if not source.is_file():
                raise FileNotFoundError(f"Adapter source file not found: {source}")
    _preflight(source_root, target_root, selected, copy_engine)

    engine_target = target_root / ENGINE_NAME
    if engine_target.is_symlink():
        raise ValueError(f"Namespaced engine target must not be a symlink: {engine_target}")
    if engine_target.exists() and not engine_target.is_dir():
        raise ValueError(f"Namespaced engine target is not a directory: {engine_target}")
    existing_engine_mode = _detect_existing_engine_mode(engine_target, source_root)
    if existing_engine_mode == "inconsistent" and not (copy_engine and replace):
        raise ValueError(
            f"Namespaced engine is inconsistent: {engine_target}; refusing to mutate it"
        )
    if existing_engine_mode == "full-stale" and not (copy_engine and replace):
        raise ValueError(
            "A full Lesson engine is installed but is older/different from the current source. "
            "Run with --copy-engine --replace to upgrade it."
        )
    if copy_engine and existing_engine_mode != "none" and not replace:
        # A full engine replacement can otherwise leave stale files behind.
        raise FileExistsError(f"Namespaced engine already exists: {engine_target}; use --replace")
    adapter_runtime_available = copy_engine or existing_engine_mode == "full-current"

    files: dict[Path, bytes] = {}
    shared_targets = {relative for name in selected for relative in ADAPTER_PATHS[name] if relative in SHARED_SOURCES}
    for relative in sorted(shared_targets):
        source = source_root / SHARED_SOURCES[relative]
        target = target_root / relative
        if target.is_symlink():
            raise ValueError(f"Refusing to replace symlinked adapter file: {target}")
        payload = _rewrite_references(source.read_text(encoding="utf-8"), copy_engine=adapter_runtime_available)
        merged = merge_marker_section(_read_text(target), payload)
        if not target.exists() or target.read_bytes() != merged.encode("utf-8"):
            files[target] = merged.encode("utf-8")

    for name in selected:
        for relative in ADAPTER_PATHS[name]:
            if relative in SHARED_SOURCES:
                continue
            source = source_root / relative
            target = target_root / relative
            if target.is_symlink():
                raise ValueError(f"Refusing to replace symlinked adapter file: {target}")
            if relative == ".aider.conf.yml":
                merged = merge_aider_config(_read_text(target))
                payload = merged.encode("utf-8")
            else:
                payload = _rewrite_references(source.read_text(encoding="utf-8"), copy_engine=adapter_runtime_available).encode("utf-8")
            if target.exists() and not replace and target.read_bytes() != payload:
                # Adapter files are intentionally additive only through their
                # marker-managed shared counterparts; plain files need opt-in.
                raise FileExistsError(f"Adapter target already exists: {target}; use --replace")
            if not target.exists() or target.read_bytes() != payload:
                files[target] = payload

    engine_files = _source_files(source_root, copy_engine)
    if not copy_engine and existing_engine_mode == "full-current":
        # Default installs update project-root adapter rules but preserve a
        # complete runtime byte-for-byte.  Never downgrade or rewrite it.
        engine_files = []
    for relative in engine_files:
        source = source_root / relative
        target = engine_target / relative
        payload = _payload_for_engine(source, copy_engine=copy_engine)
        if not target.exists() or replace or target.read_bytes() != payload:
            files[target] = payload
    if copy_engine:
        state_target = engine_target / ENGINE_STATE_FILE
        state_payload = _engine_state_payload(source_root)
        if not state_target.exists() or replace or state_target.read_bytes() != state_payload:
            files[state_target] = state_payload
        engine_files = [*engine_files, ENGINE_STATE_FILE]
    # Validate every destination's parent chain before the transaction creates
    # its staging directory or any missing project directories.
    for target in files:
        _assert_no_symlink_ancestor(target_root, target)
    return files, engine_target, engine_files


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif _exists(path):
        path.unlink()


def _cleanup_path(path: Path | None, label: str) -> str | None:
    """Best-effort stage cleanup that never replaces the primary error."""

    if path is None:
        return None
    try:
        _remove_path(path)
    except Exception as exc:  # pragma: no cover - filesystem failures vary by platform
        return f"cleanup failed for {label}: {exc}; residual path: {path}"
    return None


def _apply_files(
    files: dict[Path, bytes],
    target_root: Path,
    *,
    dry_run: bool = False,
    replace_engine: Path | None = None,
) -> list[Path]:
    if dry_run:
        for target in sorted(files):
            print(f"write {target}")
        if replace_engine is not None:
            print(f"replace-tree {replace_engine}")
        return []
    target_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".lesson-adapters.stage-", dir=str(target_root)))
    staged: dict[Path, Path] = {}
    staged_engine: Path | None = None
    engine_targets = (
        {target for target in files if replace_engine is not None and target == replace_engine}
        if replace_engine is not None
        else set()
    )
    if replace_engine is not None:
        engine_targets = {
            target
            for target in files
            if target == replace_engine or replace_engine in target.parents
        }
    backups: list[tuple[Path, Path]] = []
    applied: list[Path] = []
    operation_error: BaseException | None = None
    try:
        for target, payload in files.items():
            _assert_no_symlink_ancestor(target_root, target)
            if target.exists() and target.is_dir():
                raise IsADirectoryError(f"Adapter target is a directory: {target}")
            relative = target.relative_to(target_root)
            stage_path = stage / relative
            stage_path.parent.mkdir(parents=True, exist_ok=True)
            stage_path.write_bytes(payload)
            if target not in engine_targets:
                staged[target] = stage_path
        if replace_engine is not None:
            staged_engine = stage / replace_engine.relative_to(target_root)
            if not staged_engine.is_dir():
                raise RuntimeError(f"staged engine tree is missing: {replace_engine}")
        for target in sorted(staged):
            target.parent.mkdir(parents=True, exist_ok=True)
            if _exists(target):
                backup = _backup_path(target)
                os.replace(str(target), str(backup))
                backups.append((target, backup))
            os.replace(str(staged[target]), str(target))
            applied.append(target)
        if replace_engine is not None and staged_engine is not None:
            backup = _backup_path(replace_engine)
            os.replace(str(replace_engine), str(backup))
            backups.append((replace_engine, backup))
            os.replace(str(staged_engine), str(replace_engine))
            applied.append(replace_engine)
        return applied
    except Exception as commit_error:
        rollback_errors: list[str] = []
        for target in reversed(applied):
            try:
                _remove_path(target)
            except Exception as exc:  # pragma: no cover - filesystem-specific
                rollback_errors.append(f"remove applied target {target}: {exc}; residual path: {target}")
        for target, backup in reversed(backups):
            try:
                if not _exists(backup):
                    rollback_errors.append(
                        f"restore backup {backup} to {target}: backup is missing; residual paths: {backup}, {target}"
                    )
                    continue
                os.replace(str(backup), str(target))
            except Exception as exc:  # pragma: no cover - filesystem-specific
                rollback_errors.append(
                    f"restore backup {backup} to {target}: {exc}; residual paths: {backup}, {target}"
                )
        detail = f"adapter transaction failed: {commit_error}"
        if rollback_errors:
            detail += "; rollback failures: " + " | ".join(rollback_errors)
        else:
            detail += "; previous files restored"
        operation_error = RuntimeError(detail)
        raise operation_error from commit_error
    finally:
        cleanup_error = _cleanup_path(stage, "adapter staging directory")
        if cleanup_error:
            print(f"WARNING: {cleanup_error}", file=sys.stderr)
            if operation_error is not None:
                operation_error.add_note(cleanup_error)


def install(source_root: Path, target_root: Path, *, adapters: list[str] | None = None, replace: bool = False, copy_engine: bool = False, dry_run: bool = False) -> None:
    selected = adapters or ["all"]
    names = list(ADAPTER_PATHS) if "all" in selected else list(dict.fromkeys(selected))
    source_root, target_root = _absolute(source_root), _absolute(target_root)
    files, engine_target, engine_files = build_plan(source_root, target_root, names, replace=replace, copy_engine=copy_engine)
    print(f"source={source_root}")
    print(f"target={target_root}")
    existing_engine_mode = _detect_existing_engine_mode(engine_target, source_root)
    print(f"engine_mode={existing_engine_mode}")
    print(f"engine={engine_target}")
    print(f"planned_files={len(files)}")
    if dry_run:
        _apply_files(files, target_root, dry_run=True)
        return
    replace_engine = engine_target if copy_engine and replace and engine_target.exists() else None
    _apply_files(files, target_root, replace_engine=replace_engine)
    if not copy_engine and existing_engine_mode == "full-current":
        print(f"preserved-full-engine={engine_target}")
    else:
        print(f"installed-engine={engine_target} ({len(engine_files)} files)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install common AI-agent adapters for this skill.")
    parser.add_argument("--target-dir", required=True, help="Project directory receiving the adapter files.")
    parser.add_argument("--adapter", action="append", choices=["all", *ADAPTER_PATHS.keys()], help="Repeat for multiple adapters. Defaults to all.")
    parser.add_argument("--replace", action="store_true", help="Back up and replace existing plain adapter files.")
    parser.add_argument("--copy-engine", action="store_true", help="Copy the full Skill into the target project's namespaced directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without copying files.")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parents[1]
    install(source_root, Path(args.target_dir), adapters=args.adapter, replace=args.replace, copy_engine=args.copy_engine, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
