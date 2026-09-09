"""Install namespaced Practice Class rules into a project."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


MARKER_ID = "practice-class-html-generator"
MARKER_START = f"<!-- codex-skill: {MARKER_ID}:start -->"
MARKER_END = f"<!-- codex-skill: {MARKER_ID}:end -->"
ADAPTER_PATHS = {
    "agents": Path("AGENTS.md"),
    "claude": Path("CLAUDE.md"),
    "gemini": Path("GEMINI.md"),
    "copilot": Path(".github/copilot-instructions.md"),
    "aider": Path("CONVENTIONS.md"),
    "cursor": Path(".cursor/rules/practice-class-html-generator.mdc"),
    "cline": Path(".clinerules/practice-class-html-generator.md"),
    "continue": Path(".continue/rules/practice-class-html-generator.md"),
    "windsurf": Path(".windsurf/rules/practice-class-html-generator.md"),
    "opencode": Path(".opencode/rules/practice-class-html-generator.md"),
}
PAYLOAD = """实践课 HTML 生成器规则：

- 先阅读 `practice-class-html-generator/简介.md`、`通用提示词.md` 和 `SKILL.md`。
- 首选消费上游 Courseware Content Contract 1.1；实践知识点和 core 任务必须保留真实 `source_slide_ids`、学习单元和事实关联。
- 根据课程动态生成 foundation-kit；任务按 core / optional / challenge 分层，互动必须服务知识点和任务。
- 生成后运行合同、HTML 内链和浏览器 smoke QA；内容是否适合学生仍需人工验收。
"""


def merge(existing: str) -> str:
    block = f"{MARKER_START}\n{PAYLOAD.strip()}\n{MARKER_END}"
    start = existing.find(MARKER_START)
    end = existing.find(MARKER_END)
    if start >= 0 or end >= 0:
        if start < 0 or end < start or existing.find(MARKER_START, start + 1) >= 0:
            raise ValueError(f"malformed {MARKER_ID} marker block")
        suffix = existing[end + len(MARKER_END):].lstrip("\r\n")
        return existing[:start].rstrip() + "\n\n" + block + ("\n\n" + suffix if suffix else "\n")
    return (existing.rstrip() + "\n\n" if existing.strip() else "") + block + "\n"


def install(source_root: Path, target_root: Path, *, adapters: list[str] | None = None, copy_engine: bool = False, replace: bool = False, dry_run: bool = False) -> dict[str, str]:
    source_root = source_root.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    selected = adapters or ["all"]
    names = list(ADAPTER_PATHS) if "all" in selected else list(dict.fromkeys(selected))
    unknown = [name for name in names if name not in ADAPTER_PATHS]
    if unknown:
        raise ValueError("unknown adapters: " + ", ".join(unknown))
    plan: list[tuple[Path, str]] = []
    for name in names:
        relative = ADAPTER_PATHS[name]
        target = target_root / relative
        if target.is_symlink():
            raise ValueError(f"refusing to modify symlinked adapter target: {target}")
        if target.exists() and not target.is_file():
            raise ValueError(f"adapter target is not a file: {target}")
        plan.append((relative, merge(target.read_text(encoding="utf-8") if target.is_file() else "")))
    engine = target_root / ".practice-class-html-generator"
    if copy_engine and engine.exists() and not replace:
        raise FileExistsError(f"engine exists: {engine}; use --replace")
    if dry_run:
        return {"status": "dry-run", "mode": "full" if copy_engine else "minimal"}
    target_root.mkdir(parents=True, exist_ok=True)
    for relative, payload in plan:
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8", newline="\n")
    if copy_engine:
        if engine.exists():
            shutil.rmtree(engine)
        shutil.copytree(source_root, engine, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"))
    return {"status": "pass", "mode": "full" if copy_engine else "minimal"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--adapter", action="append", choices=[*ADAPTER_PATHS, "all"], dest="adapters")
    parser.add_argument("--copy-engine", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(install(args.source_root, args.target_dir, adapters=args.adapters, copy_engine=args.copy_engine, replace=args.replace, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
