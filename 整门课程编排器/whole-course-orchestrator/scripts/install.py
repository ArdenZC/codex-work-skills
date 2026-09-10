"""Install the whole-course orchestrator with staging and byte-integrity checks."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path


SKILL_NAME = "whole-course-orchestrator"
REQUIRED = (
    "简介.md",
    "AGENTS.md",
    "通用提示词.md",
    "SKILL.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    "README.md",
    "manifest.yaml",
    "agents/openai.yaml",
    "requirements.txt",
    "schemas/teaching-asset-inventory.schema.json",
    "schemas/course-knowledge-graph.schema.json",
    "schemas/session-plan.schema.json",
    "schemas/visual-plan.schema.json",
    "schemas/practice-plan.schema.json",
    "schemas/whole-course-qa.schema.json",
    "schemas/external-source-research.schema.json",
    "scripts/orchestrator_core.py",
    "scripts/mine_teaching_assets.py",
    "scripts/freeze_benchmark.py",
    "scripts/build_knowledge_graph.py",
    "scripts/plan_sessions.py",
    "scripts/plan_visuals.py",
    "scripts/plan_practice.py",
    "scripts/external_research.py",
    "scripts/external_research.py",
    "scripts/review_whole_course.py",
    "scripts/package_course.py",
    "scripts/install.py",
    "tests/__init__.py",
    "tests/test_whole_course.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove(path: Path | None) -> None:
    if path is None or not _exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def install(source: Path, skills_dir: Path, *, replace: bool = False, dry_run: bool = False, keep_backup: bool = False) -> Path:
    source = source.expanduser().resolve()
    skills_dir = skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME
    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError(source)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and target must not overlap")
    missing = [relative for relative in REQUIRED if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(missing))
    if _exists(target) and not replace:
        raise FileExistsError(f"target exists: {target}; use --replace")
    if dry_run:
        print(f"source={source}")
        print(f"target={target}")
        print("dry-run=yes (no filesystem mutation)")
        return target

    skills_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(skills_dir)))
    _remove(stage)
    backup = skills_dir / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}" if _exists(target) else None
    try:
        shutil.copytree(source, stage, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"))
        for relative in REQUIRED:
            source_file = source / relative
            staged_file = stage / relative
            if not staged_file.is_file() or _sha256(source_file) != _sha256(staged_file):
                raise RuntimeError(f"staged integrity mismatch: {relative}")
        if backup is not None:
            os.replace(str(target), str(backup))
        try:
            os.replace(str(stage), str(target))
        except Exception:
            if backup is not None and not _exists(target):
                os.replace(str(backup), str(target))
            raise
        if backup is not None and not keep_backup:
            _remove(backup)
        return target
    finally:
        _remove(stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--keep-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target = install(Path(__file__).resolve().parents[1], args.skills_dir, replace=args.replace, dry_run=args.dry_run, keep_backup=args.keep_backup)
    print(f"target={target}")


if __name__ == "__main__":
    main()
