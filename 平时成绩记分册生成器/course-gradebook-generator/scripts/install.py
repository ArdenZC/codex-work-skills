from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


SKILL_NAME = "course-gradebook-generator"


def default_skills_dir() -> Path:
    return Path.home() / ".codex" / "skills"


def ignore_patterns(_dir: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".DS_Store"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Install 平时成绩记分册生成器 into the local Codex skills directory.")
    parser.add_argument("--skills-dir", default=str(default_skills_dir()), help="Target Codex skills directory. Defaults to ~/.codex/skills.")
    parser.add_argument("--replace", action="store_true", help="Back up and replace an existing installed copy.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned paths without copying files.")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    target_root = Path(args.skills_dir).expanduser().resolve()
    target = target_root / SKILL_NAME

    print(f"source={source}")
    print(f"target={target}")
    if args.dry_run:
        return

    if target.exists():
        if not args.replace:
            raise FileExistsError(f"Target already exists: {target}. Re-run with --replace to back it up and replace it.")
        backup = target_root / f"{SKILL_NAME}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.move(str(target), str(backup))
        print(f"backup={backup}")

    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=ignore_patterns)
    print(f"installed={target}")


if __name__ == "__main__":
    main()
