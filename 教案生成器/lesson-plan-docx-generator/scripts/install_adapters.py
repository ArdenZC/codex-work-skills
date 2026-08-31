"""Transactional, namespaced project-adapter installer for the Lesson Skill."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from path_safety import paths_overlap


ENGINE_NAME = ".lesson-plan-docx-generator"
MARKER_ID = "lesson-plan-docx-generator"
MARKER_START = f"<!-- codex-skill: {MARKER_ID}:start -->"
MARKER_END = f"<!-- codex-skill: {MARKER_ID}:end -->"
MINIMAL_ENGINE_FILES = (
    Path("SKILL.md"),
    Path("通用提示词.md"),
    Path("AGENTS.md"),
    Path("CONVENTIONS.md"),
)
FULL_ENGINE_SENTINELS = (
    Path("scripts/generate_lesson_plans.py"),
    Path("schemas/lesson-plan-input.schema.json"),
    Path("assets/templates/lesson-plan/v1.1.2/manifest.yaml"),
)
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
        return [path.relative_to(source_root) for path in source_root.rglob("*") if path.is_file() and not path.is_symlink() and not ignore_patterns("", [path.name])]
    return list(MINIMAL_ENGINE_FILES)


def _detect_existing_engine_mode(engine_target: Path) -> str:
    """Classify an existing project-local engine without following symlinks."""

    if not _exists(engine_target):
        return "none"
    if engine_target.is_symlink() or not engine_target.is_dir():
        return "inconsistent"

    def real_file(relative: Path) -> bool:
        path = engine_target / relative
        return path.is_file() and not path.is_symlink()

    minimal = all(real_file(relative) for relative in MINIMAL_ENGINE_FILES)
    sentinel_states = [real_file(relative) for relative in FULL_ENGINE_SENTINELS]
    if minimal and all(sentinel_states):
        return "full"
    if minimal and not any(sentinel_states):
        return "minimal"
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
    for name in selected:
        for relative in ADAPTER_PATHS[name]:
            source = source_root / relative
            if not source.is_file():
                raise FileNotFoundError(f"Adapter source file not found: {source}")
    _preflight(source_root, target_root, selected, copy_engine)

    files: dict[Path, bytes] = {}
    shared_targets = {relative for name in selected for relative in ADAPTER_PATHS[name] if relative in SHARED_SOURCES}
    for relative in sorted(shared_targets):
        source = source_root / SHARED_SOURCES[relative]
        target = target_root / relative
        if target.is_symlink():
            raise ValueError(f"Refusing to replace symlinked adapter file: {target}")
        payload = _rewrite_references(source.read_text(encoding="utf-8"), copy_engine=copy_engine)
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
                payload = _rewrite_references(source.read_text(encoding="utf-8"), copy_engine=copy_engine).encode("utf-8")
            if target.exists() and not replace and target.read_bytes() != payload:
                # Adapter files are intentionally additive only through their
                # marker-managed shared counterparts; plain files need opt-in.
                raise FileExistsError(f"Adapter target already exists: {target}; use --replace")
            if not target.exists() or target.read_bytes() != payload:
                files[target] = payload

    engine_target = target_root / ENGINE_NAME
    engine_files = _source_files(source_root, copy_engine)
    if engine_target.is_symlink():
        raise ValueError(f"Namespaced engine target must not be a symlink: {engine_target}")
    if engine_target.exists() and not engine_target.is_dir():
        raise ValueError(f"Namespaced engine target is not a directory: {engine_target}")
    existing_engine_mode = _detect_existing_engine_mode(engine_target)
    if existing_engine_mode == "inconsistent" and not (copy_engine and replace):
        raise ValueError(
            f"Namespaced engine is inconsistent: {engine_target}; refusing to mutate it"
        )
    if copy_engine and existing_engine_mode != "none" and not replace:
        # A full engine replacement can otherwise leave stale files behind.
        raise FileExistsError(f"Namespaced engine already exists: {engine_target}; use --replace")
    if not copy_engine and existing_engine_mode == "full":
        # Default installs update project-root adapter rules but preserve a
        # complete runtime byte-for-byte.  Never downgrade or rewrite it.
        engine_files = []
    for relative in engine_files:
        source = source_root / relative
        target = engine_target / relative
        payload = _payload_for_engine(source, copy_engine=copy_engine)
        if not target.exists() or replace or target.read_bytes() != payload:
            files[target] = payload
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
    existing_engine_mode = _detect_existing_engine_mode(engine_target)
    print(f"engine={engine_target}")
    print(f"planned_files={len(files)}")
    if dry_run:
        _apply_files(files, target_root, dry_run=True)
        return
    replace_engine = engine_target if copy_engine and replace and engine_target.exists() else None
    _apply_files(files, target_root, replace_engine=replace_engine)
    if not copy_engine and existing_engine_mode == "full":
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
