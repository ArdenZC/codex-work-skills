from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ADAPTER_PATHS = {
    "agents": ("AGENTS.md",),
    "claude": ("CLAUDE.md",),
    "gemini": ("GEMINI.md",),
    "cursor": (".cursor/rules/course-gradebook-generator.mdc",),
    "cline": (".clinerules/course-gradebook-generator.md",),
    "continue": (".continue/rules/course-gradebook-generator.md",),
    "windsurf": (".windsurf/rules/course-gradebook-generator.md",),
    "copilot": (".github/copilot-instructions.md",),
    "aider": ("CONVENTIONS.md", ".aider.conf.yml"),
}

def copy_file(source_root: Path, target_root: Path, relative: str, replace: bool, dry_run: bool) -> None:
    source = source_root / relative
    target = target_root / relative
    if target.exists() and not replace:
        print(f"skip existing={target}")
        return
    if dry_run:
        print(f"copy {source} -> {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_name(f"{target.name}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.move(str(target), str(backup))
        print(f"backup={backup}")
    shutil.copy2(str(source), str(target))
    print(f"installed={target}")

def copy_engine(source_root: Path, target_root: Path, replace: bool, dry_run: bool) -> None:
    target = target_root / ".lesson-plan-docx-generator" if "course-gradebook-generator" == "lesson-plan-generator" else target_root / ".course-gradebook-generator"
    if target.exists() and not replace:
        print(f"skip existing engine={target}")
        return
    if dry_run:
        print(f"copy-tree {source_root} -> {target}")
        return
    if target.exists():
        backup = target_root / f"{target.name}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.move(str(target), str(backup))
        print(f"backup={backup}")
    shutil.copytree(source_root, target, ignore=ignore_patterns)
    print(f"installed-engine={target}")

def ignore_patterns(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc") or name == ".DS_Store"}

def main() -> None:
    parser = argparse.ArgumentParser(description="Install common AI-agent adapters for this skill.")
    parser.add_argument("--target-dir", required=True, help="Project directory receiving the adapter files.")
    parser.add_argument("--adapter", action="append", choices=["all", *ADAPTER_PATHS.keys()], help="Repeat for multiple adapters. Defaults to all.")
    parser.add_argument("--replace", action="store_true", help="Back up and replace existing files.")
    parser.add_argument("--copy-engine", action="store_true", help="Copy this entire skill into the target project's .lesson-plan-docx-generator or .course-gradebook-generator directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without copying files.")
    args = parser.parse_args()

    source_root = Path(__file__).resolve().parents[1]
    target_root = Path(args.target_dir).expanduser().resolve()
    selected = args.adapter or ["all"]
    names = list(ADAPTER_PATHS) if "all" in selected else list(dict.fromkeys(selected))

    print(f"source={source_root}")
    print(f"target={target_root}")
    copy_file(source_root, target_root, "AGENTS.md", args.replace, args.dry_run)
    copy_file(source_root, target_root, "通用提示词.md", args.replace, args.dry_run)
    for name in names:
        for relative in ADAPTER_PATHS[name]:
            copy_file(source_root, target_root, relative, args.replace, args.dry_run)
    if args.copy_engine:
        if target_root == source_root:
            raise ValueError("--copy-engine target must be different from the skill directory.")
        copy_engine(source_root, target_root, args.replace, args.dry_run)

if __name__ == "__main__":
    main()
