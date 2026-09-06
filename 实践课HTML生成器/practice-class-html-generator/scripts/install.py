"""Install the Practice Class Skill as a plain, replaceable skill package."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


SKILL_NAME = "practice-class-html-generator"
REQUIRED = (
    "简介.md", "AGENTS.md", "通用提示词.md", "SKILL.md", "CLAUDE.md", "GEMINI.md",
    "CONVENTIONS.md", "requirements.txt", "README.md", "manifest.yaml", "agents/openai.yaml",
    "docs/content-contract-v1.md", "schemas/practice-class-content.schema.json",
    "scripts/practice_contract.py", "scripts/render_practice.py", "scripts/validate_practice.py",
    "scripts/install.py", "scripts/install_adapters.py", "tests/test_practice_class.py", "tests/browser_smoke.mjs",
)


def install(source: Path, skills_dir: Path, *, replace: bool = False, dry_run: bool = False) -> Path:
    source = source.expanduser().resolve()
    skills_dir = skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME
    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError(source)
    missing = [relative for relative in REQUIRED if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(missing))
    if target.exists() and not replace:
        raise FileExistsError(f"target exists: {target}; use --replace")
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and target must not overlap")
    print(f"source={source}")
    print(f"target={target}")
    if dry_run:
        print("dry-run=yes (no filesystem mutation)")
        return target
    skills_dir.mkdir(parents=True, exist_ok=True)
    stage = skills_dir / f".{SKILL_NAME}.stage"
    if stage.exists():
        raise FileExistsError(f"staging path already exists: {stage}")
    shutil.copytree(source, stage, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"))
    try:
        if target.exists():
            shutil.rmtree(target)
        stage.rename(target)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    print(f"installed={target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.skills_dir, replace=args.replace, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
