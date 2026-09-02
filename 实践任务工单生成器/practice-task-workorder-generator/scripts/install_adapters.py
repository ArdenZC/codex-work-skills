"""Install namespaced WorkOrder adapters and an optional project-local runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Iterable


ENGINE_NAME = ".practice-task-workorder-generator"
ENGINE_STATE_FILE = Path(".engine-state.json")
ENGINE_STATE_SCHEMA_VERSION = 1
CONTENT_CONTRACT_VERSION = "1.0"
MARKER_ID = "practice-task-workorder-generator"
MARKER_START = f"<!-- codex-skill: {MARKER_ID}:start -->"
MARKER_END = f"<!-- codex-skill: {MARKER_ID}:end -->"
SHARED_SCHEMA = Path("schemas/shared/practice-task-contract.schema.json")

MINIMAL_ENGINE_FILES = (
    Path("SKILL.md"),
    Path("通用提示词.md"),
    Path("AGENTS.md"),
    Path("简介.md"),
)
FULL_ENGINE_RUNTIME_FILES = (
    Path("requirements.txt"),
    Path("manifest.yaml"),
    Path("agents/openai.yaml"),
    Path("schemas/work-order-content.schema.json"),
    SHARED_SCHEMA,
    Path("scripts/content_contract.py"),
    Path("scripts/content_quality.py"),
    Path("scripts/cross_artifact_quality.py"),
    Path("scripts/check_dependencies.py"),
    Path("scripts/generate_work_orders.py"),
    Path("scripts/render_qa.py"),
    Path("scripts/validate_output.py"),
    Path("scripts/validate_template.py"),
    Path("assets/templates/practice-work-order/v1.0.0/manifest.yaml"),
    Path("assets/templates/practice-work-order/v1.0.0/template.docx"),
)
FULL_ENGINE_INVENTORY_FILES = tuple(dict.fromkeys((*MINIMAL_ENGINE_FILES, *FULL_ENGINE_RUNTIME_FILES)))
REFERENCE_TEXT_SUFFIXES = {".md", ".mdc", ".yml", ".yaml"}
ADAPTER_PATHS = {
    "agents": ("AGENTS.md",),
    "claude": ("CLAUDE.md",),
    "gemini": ("GEMINI.md",),
    "copilot": (".github/copilot-instructions.md",),
    "aider": ("CONVENTIONS.md", ".aider.conf.yml"),
}
SOURCE_ADAPTERS = {
    "agents": Path("AGENTS.md"),
    "claude": Path("CLAUDE.md"),
    "gemini": Path("GEMINI.md"),
    "copilot": Path(".github/copilot-instructions.md"),
    "aider": Path("CONVENTIONS.md"),
}
ADAPTER_PAYLOAD = """Practice Task WorkOrder integration rules:

- Read the canonical Practice Task Contract V1 first; it is the upstream fact source.
- Do not redesign or silently edit the upstream Practice Task.
- Preserve practice_task_id, lesson_ids, practice_hours, deliverables, acceptance criteria, tools/materials, and safety/compliance constraints.
- Keep classroom attendance at 10 points and task items at 90 points; total is 100. The Agent assigns individual task-item scores; Python only validates their sum.
- Leave the student task-result area blank and never generate a teacher answer, standard SQL, or final clinical/accounting result.
- Run WorkOrder Content QA, Cross-Artifact QA, and Output QA before delivering the DOCX.
- Use the canonical practice-work-order v1.0.0 template; Phase 3 / 64-hour expansion is out of scope.
"""


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _shared_schema_source(source_root: Path) -> Path:
    candidates = (
        source_root / SHARED_SCHEMA,
        source_root.parents[1] / SHARED_SCHEMA,
        source_root.parents[2] / SHARED_SCHEMA,
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise FileNotFoundError("canonical shared Practice Task schema is unavailable")


def _marker_block(payload: str) -> str:
    return f"{MARKER_START}\n{payload.strip()}\n{MARKER_END}"


def merge_marker_section(existing: str, payload: str) -> str:
    """Idempotently replace this Skill's block and fail closed if malformed."""

    starts = [match.start() for match in re.finditer(re.escape(MARKER_START), existing)]
    ends = [match.start() for match in re.finditer(re.escape(MARKER_END), existing)]
    if len(starts) != len(ends) or len(starts) > 1 or (starts and ends[0] < starts[0]):
        raise ValueError(f"Malformed {MARKER_ID} marker block; refusing to mutate the target")
    block = _marker_block(payload)
    if starts:
        prefix = existing[: starts[0]].rstrip("\r\n")
        suffix = existing[ends[0] + len(MARKER_END) :].lstrip("\r\n")
        return (prefix + "\n\n" if prefix else "") + block + ("\n\n" + suffix if suffix else "\n")
    return (existing.rstrip("\r\n") + "\n\n" if existing.strip() else "") + block + "\n"


def _parse_simple_aider(existing: str) -> list[str]:
    if not existing.strip():
        return []
    in_read = False
    paths: list[str] = []
    for line in existing.splitlines():
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
        raise ValueError("complex or unparseable .aider.conf.yml; refusing to mutate")
    if not in_read:
        raise ValueError(".aider.conf.yml has no simple read list; refusing to mutate")
    return paths


def merge_aider_config(existing: str) -> str:
    required = [
        f"{ENGINE_NAME}/SKILL.md",
        f"{ENGINE_NAME}/通用提示词.md",
        f"{ENGINE_NAME}/AGENTS.md",
        f"{ENGINE_NAME}/简介.md",
    ]
    if not existing.strip():
        return "read:\n" + "".join(f"  - {item}\n" for item in required)
    paths = _parse_simple_aider(existing)
    missing = [item for item in required if item not in paths]
    return existing if not missing and existing.endswith("\n") else existing.rstrip("\r\n") + "\n" + "".join(f"  - {item}\n" for item in missing)


def _rewrite_references(text: str, *, full_runtime: bool) -> str:
    replacement = {
        "SKILL.md": f"{ENGINE_NAME}/SKILL.md",
        "通用提示词.md": f"{ENGINE_NAME}/通用提示词.md",
        "AGENTS.md": f"{ENGINE_NAME}/AGENTS.md",
        "简介.md": f"{ENGINE_NAME}/简介.md",
    }
    for bare, namespaced in replacement.items():
        text = re.sub(rf"(?<![./\w-]){re.escape(bare)}", namespaced, text)
    if full_runtime:
        text = re.sub(
            r"(?<![./\w-])((?:scripts|docs|examples|schemas|assets)/[^\s`\"'<>（）(),，。；：！？]+)",
            lambda match: f"{ENGINE_NAME}/{match.group(1).replace(chr(92), '/')}",
            text,
        )
    else:
        text = re.sub(
            r"(?<![./\w-])((?:scripts|docs|examples|schemas|assets)/[^\s`\"'<>（）(),，。；：！？]+)",
            "the full WorkOrder runtime (install with --copy-engine)",
            text,
        )
    return text


def _payload_for_engine(source: Path, *, full_runtime: bool) -> bytes:
    if source.suffix.lower() in REFERENCE_TEXT_SUFFIXES:
        return _rewrite_references(source.read_text(encoding="utf-8"), full_runtime=full_runtime).encode("utf-8")
    return source.read_bytes()


def _runtime_inventory_from_source(source_root: Path) -> dict[str, str]:
    shared = _shared_schema_source(source_root)
    inventory: dict[str, str] = {}
    for relative in FULL_ENGINE_INVENTORY_FILES:
        source = shared if relative == SHARED_SCHEMA else source_root / relative
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError(f"WorkOrder engine source is missing or unsafe: {source}")
        inventory[relative.as_posix()] = _sha256_bytes(_payload_for_engine(source, full_runtime=True))
    return dict(sorted(inventory.items()))


def _runtime_fingerprint(inventory: dict[str, str]) -> str:
    return _sha256_bytes(json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _engine_state_payload(source_root: Path) -> bytes:
    inventory = _runtime_inventory_from_source(source_root)
    state = {
        "schema_version": ENGINE_STATE_SCHEMA_VERSION,
        "skill": MARKER_ID,
        "content_contract_version": CONTENT_CONTRACT_VERSION,
        "runtime_fingerprint": _runtime_fingerprint(inventory),
        "runtime_inventory": inventory,
    }
    return (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_engine_state(engine_target: Path) -> dict[str, object] | None:
    path = engine_target / ENGINE_STATE_FILE
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _installed_inventory_matches(engine_target: Path, state: dict[str, object]) -> bool:
    inventory = state.get("runtime_inventory")
    expected = {relative.as_posix() for relative in FULL_ENGINE_INVENTORY_FILES}
    if not isinstance(inventory, dict) or set(inventory) != expected:
        return False
    if state.get("schema_version") != ENGINE_STATE_SCHEMA_VERSION or state.get("skill") != MARKER_ID or state.get("content_contract_version") != CONTENT_CONTRACT_VERSION:
        return False
    if state.get("runtime_fingerprint") != _runtime_fingerprint(inventory):
        return False
    return all(
        isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest)
        and (engine_target / relative).is_file()
        and not (engine_target / relative).is_symlink()
        and _sha256_file(engine_target / relative) == digest
        for relative, digest in inventory.items()
    )


def _detect_existing_engine_mode(engine_target: Path, source_root: Path | None = None) -> str:
    if not _exists(engine_target):
        return "none"
    if engine_target.is_symlink() or not engine_target.is_dir():
        return "inconsistent"

    def real_file(relative: Path) -> bool:
        path = engine_target / relative
        return path.is_file() and not path.is_symlink()

    minimal = all(real_file(relative) for relative in MINIMAL_ENGINE_FILES)
    full = all(real_file(relative) for relative in FULL_ENGINE_RUNTIME_FILES)
    if minimal and full:
        if not (engine_target / ENGINE_STATE_FILE).exists():
            return "full-stale"
        state = _read_engine_state(engine_target)
        if state is None or not _installed_inventory_matches(engine_target, state):
            return "inconsistent"
        if source_root is None:
            return "full-current"
        try:
            inventory = _runtime_inventory_from_source(source_root)
        except (FileNotFoundError, OSError, UnicodeError):
            return "full-stale"
        return "full-current" if state.get("runtime_fingerprint") == _runtime_fingerprint(inventory) and state.get("runtime_inventory") == inventory else "full-stale"
    if minimal and not full:
        return "minimal" if not (engine_target / ENGINE_STATE_FILE).exists() else "inconsistent"
    return "inconsistent"


def _source_files(source_root: Path, copy_engine: bool) -> dict[Path, Path]:
    if not copy_engine:
        return {relative: source_root / relative for relative in MINIMAL_ENGINE_FILES}
    files: dict[Path, Path] = {}
    for path in source_root.rglob("*"):
        relative = path.relative_to(source_root)
        if path.is_file() and not path.is_symlink() and path.name != ENGINE_STATE_FILE.name and path.name != ".DS_Store" and "__pycache__" not in path.parts:
            files[relative] = path
    shared = _shared_schema_source(source_root)
    files[SHARED_SCHEMA] = shared
    return files


def _required_engine_files(source_root: Path, copy_engine: bool) -> tuple[Path, ...]:
    required = FULL_ENGINE_INVENTORY_FILES if copy_engine else MINIMAL_ENGINE_FILES
    _shared_schema_source(source_root)
    missing = [source_root / relative for relative in required if relative != SHARED_SCHEMA and ((source_root / relative).is_symlink() or not (source_root / relative).is_file())]
    if missing:
        raise FileNotFoundError("WorkOrder adapter source is incomplete: " + ", ".join(str(path) for path in missing))
    return required


def _assert_no_symlink_ancestor(root: Path, path: Path) -> None:
    current = path.parent
    while current != root.parent and current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError(f"refusing to write through symlinked directory: {current}")
        current = current.parent


def _backup_path(path: Path) -> Path:
    while True:
        candidate = path.with_name(f"{path.name}.backup_{uuid.uuid4().hex}")
        if not _exists(candidate):
            return candidate


def _remove(path: Path | None) -> None:
    if path is None or not _exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _adapter_source_payload(source_root: Path, name: str, destination: Path, *, full_runtime: bool) -> bytes:
    if name == "aider" and destination.name == ".aider.conf.yml":
        return merge_aider_config("").encode("utf-8")
    source = source_root / SOURCE_ADAPTERS[name]
    return (_rewrite_references(source.read_text(encoding="utf-8"), full_runtime=full_runtime) + "\n" + ADAPTER_PAYLOAD).encode("utf-8")


def build_plan(source_root: Path, target_root: Path, selected: list[str], *, replace: bool = False, copy_engine: bool = False) -> tuple[dict[Path, bytes], str | None, str]:
    source_root, target_root = _absolute(source_root), _absolute(target_root)
    if source_root == target_root or source_root in target_root.parents or target_root in source_root.parents:
        raise ValueError(f"Adapter target must not overlap the Skill source: {target_root}")
    selected = list(ADAPTER_PATHS) if "all" in selected else list(dict.fromkeys(selected))
    unknown = [name for name in selected if name not in ADAPTER_PATHS]
    if unknown:
        raise ValueError("unknown adapter(s): " + ", ".join(unknown))
    _required_engine_files(source_root, copy_engine)
    if target_root.exists() and (target_root.is_symlink() or not target_root.is_dir()):
        raise NotADirectoryError(f"Adapter target is not a real directory: {target_root}")
    engine_target = target_root / ENGINE_NAME
    mode = _detect_existing_engine_mode(engine_target, source_root)
    if mode == "inconsistent":
        raise ValueError(f"existing WorkOrder engine is inconsistent: {engine_target}")
    if mode == "full-stale" and not (copy_engine and replace):
        raise ValueError("existing WorkOrder engine is full-stale; use --copy-engine --replace to upgrade it")
    if copy_engine and mode in {"minimal", "full-stale"} and not replace:
        raise ValueError(f"existing WorkOrder engine is {mode}; use --replace to upgrade it")
    engine_action: str | None = None
    if copy_engine:
        engine_action = "full"
    if copy_engine and mode == "full-current" and not replace:
        # Keep the current runtime intact; adapter files can still be refreshed.
        copy_engine = False
        engine_action = None
    elif mode == "none":
        engine_action = "full" if copy_engine else "minimal"
    full_runtime = engine_action == "full" or mode == "full-current"
    files: dict[Path, bytes] = {}
    for name in selected:
        for relative in ADAPTER_PATHS[name]:
            target = target_root / relative
            _assert_no_symlink_ancestor(target_root, target)
            relative_path = Path(relative)
            if name == "aider" and relative_path.name == ".aider.conf.yml":
                existing = target.read_text(encoding="utf-8") if target.is_file() else ""
                files[relative_path] = merge_aider_config(existing).encode("utf-8")
            else:
                source_payload = _adapter_source_payload(source_root, name, relative_path, full_runtime=full_runtime).decode("utf-8")
                existing = target.read_text(encoding="utf-8") if target.is_file() else ""
                files[relative_path] = merge_marker_section(existing, source_payload).encode("utf-8")
    return files, engine_action, mode


def _apply_plan(
    source_root: Path,
    target_root: Path,
    files: dict[Path, bytes],
    *,
    replace_engine: str | None,
    mode: str,
    keep_backup: bool = False,
) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".practice-workorder-adapters.stage-", dir=str(target_root)))
    committed: list[tuple[Path, Path | None]] = []
    try:
        staged_paths: dict[Path, Path] = {}
        for relative, payload in files.items():
            staged = stage / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(payload)
            staged_paths[target_root / relative] = staged
        staged_engine: Path | None = None
        engine_target = target_root / ENGINE_NAME
        if replace_engine is not None:
            staged_engine = stage / ENGINE_NAME
            staged_engine.mkdir()
            full_runtime = replace_engine == "full"
            for relative, source in _source_files(source_root, full_runtime).items():
                destination = staged_engine / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(_payload_for_engine(source, full_runtime=full_runtime))
            if full_runtime:
                state = staged_engine / ENGINE_STATE_FILE
                state.write_bytes(_engine_state_payload(source_root))
        targets = list(staged_paths)
        if staged_engine is not None:
            targets.append(engine_target)
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = _backup_path(target) if _exists(target) else None
            if backup is not None:
                os.replace(str(target), str(backup))
            committed.append((target, backup))
            replacement = staged_engine if target == engine_target else staged_paths[target]
            os.replace(str(replacement), str(target))
    except Exception:
        for target, backup in reversed(committed):
            try:
                _remove(target)
                if backup is not None and _exists(backup):
                    os.replace(str(backup), str(target))
            except Exception:
                pass
        raise
    else:
        if not keep_backup:
            for _, backup in committed:
                _remove(backup)
    finally:
        _remove(stage)


def install(
    source_root: Path,
    target_root: Path,
    *,
    adapters: list[str] | None = None,
    replace: bool = False,
    copy_engine: bool = False,
    dry_run: bool = False,
    keep_backup: bool = False,
) -> dict[str, str]:
    source_root, target_root = _absolute(source_root), _absolute(target_root)
    selected = adapters or ["all"]
    files, replace_engine, mode = build_plan(source_root, target_root, selected, replace=replace, copy_engine=copy_engine)
    next_mode = "full-current" if replace_engine == "full" else "minimal" if replace_engine == "minimal" else mode
    print(f"source={source_root}")
    print(f"target={target_root}")
    print(f"existing_engine_mode={mode}")
    print(f"planned_engine_mode={next_mode}")
    if dry_run:
        for relative in sorted(files):
            print(f"would-update={target_root / relative}")
        if replace_engine is not None:
            print(f"would-update={target_root / ENGINE_NAME}")
        return {"mode": next_mode, "status": "dry-run"}
    _apply_plan(
        source_root,
        target_root,
        files,
        replace_engine=replace_engine,
        mode=mode,
        keep_backup=keep_backup,
    )
    for relative in sorted(files):
        print(f"updated={target_root / relative}")
    if replace_engine is not None:
        print(f"updated={target_root / ENGINE_NAME}")
    return {"mode": next_mode, "status": "pass"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--adapter", action="append", choices=[*ADAPTER_PATHS, "all"], dest="adapters")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--copy-engine", action="store_true")
    parser.add_argument(
        "--keep-backup",
        action="store_true",
        help="retain previous adapter files/runtime after a successful replacement",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    install(
        args.source_root,
        args.target_dir,
        adapters=args.adapters,
        replace=args.replace,
        copy_engine=args.copy_engine,
        dry_run=args.dry_run,
        keep_backup=args.keep_backup,
    )


if __name__ == "__main__":
    main()
