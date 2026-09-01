"""Install a namespaced instruction-only adapter for the Work Order Skill."""

from __future__ import annotations

import argparse
from pathlib import Path


START = "<!-- codex-skill: practice-task-workorder-generator:start -->"
END = "<!-- codex-skill: practice-task-workorder-generator:end -->"
BLOCK = f"""{START}
Practice Task Work Order Skill: read `实践任务工单生成器/practice-task-workorder-generator/简介.md`, `通用提示词.md` and `SKILL.md` before generating. Use Content V1 or the Lesson Practice Task Contract V1 handoff; keep student result fields blank, fixed score 10+90=100, and do not generate answers.
{END}"""


def _update(path: Path, *, replace: bool) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if START in old:
        if not replace:
            return False
        before = old.split(START, 1)[0].rstrip()
        after = old.split(END, 1)[1].lstrip() if END in old else ""
        new = "\n\n".join(part for part in (before, BLOCK, after) if part)
    else:
        new = (old.rstrip() + "\n\n" if old.strip() else "") + BLOCK + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--copy-engine", action="store_true", help="accepted for adapter compatibility; not used in Phase 1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target = args.target_dir.expanduser().resolve()
    paths = [target / "AGENTS.md"]
    if args.copy_engine:
        print("copy-engine is not needed for this instruction-only Phase 1 adapter")
    for path in paths:
        if args.dry_run:
            print(f"would-update={path}")
        elif _update(path, replace=args.replace):
            print(f"updated={path}")
        else:
            print(f"unchanged={path}")


if __name__ == "__main__":
    main()
