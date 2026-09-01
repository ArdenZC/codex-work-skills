"""Install the independent practice-task-workorder-generator Skill atomically."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import uuid
from pathlib import Path


SKILL_NAME = "practice-task-workorder-generator"
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


def _backup_path(root: Path) -> Path:
    while True:
        path = root / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}"
        if not _exists(path):
            return path


def install(source: Path, skills_dir: Path, *, replace: bool = False, dry_run: bool = False) -> Path:
    source = source.expanduser().resolve()
    skills_dir = skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME
    if not source.is_dir():
        raise FileNotFoundError(source)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and target must not overlap")
    missing = [relative for relative in REQUIRED if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(missing))
    if _exists(target) and not replace:
        raise FileExistsError(f"target exists: {target}; use --replace")
    print(f"source={source}")
    print(f"target={target}")
    if dry_run:
        print("dry-run=yes")
        return target
    skills_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(skills_dir)))
    backup = _backup_path(skills_dir) if _exists(target) else None
    try:
        stage.rmdir()
        shutil.copytree(source, stage, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for relative in REQUIRED:
            if not (stage / relative).is_file():
                raise RuntimeError(f"staging lost required file: {relative}")
        if backup:
            os.replace(str(target), str(backup))
        try:
            os.replace(str(stage), str(target))
        except Exception:
            if backup and not _exists(target):
                os.replace(str(backup), str(target))
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
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
