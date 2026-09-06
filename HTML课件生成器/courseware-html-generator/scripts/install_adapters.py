"""Install namespaced HTML Courseware rules and optional project-local runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


ENGINE_NAME = ".courseware-html-generator"
MARKER_ID = "courseware-html-generator"
MARKER_START = f"<!-- codex-skill: {MARKER_ID}:start -->"
MARKER_END = f"<!-- codex-skill: {MARKER_ID}:end -->"
MINIMAL_ENGINE_FILES = (Path("简介.md"), Path("AGENTS.md"), Path("通用提示词.md"), Path("SKILL.md"))
FULL_ENGINE_FILES = (
    *MINIMAL_ENGINE_FILES,
    Path("README.md"),
    Path("CLAUDE.md"),
    Path("GEMINI.md"),
    Path("CONVENTIONS.md"),
    Path("requirements.txt"),
    Path("manifest.yaml"),
    Path("agents/openai.yaml"),
    Path("docs/content-contract-v1.md"),
    Path("schemas/courseware-content.schema.json"),
    Path("examples/data-structures.example.json"),
    Path("examples/uml.example.json"),
    Path("scripts/content_contract.py"),
    Path("scripts/render_courseware.py"),
    Path("scripts/validate_courseware.py"),
    Path("scripts/install.py"),
    Path("scripts/install_adapters.py"),
)
ADAPTER_PATHS = {
    "agents": Path("AGENTS.md"),
    "claude": Path("CLAUDE.md"),
    "gemini": Path("GEMINI.md"),
    "copilot": Path(".github/copilot-instructions.md"),
    "aider": Path("CONVENTIONS.md"),
    "cursor": Path(".cursor/rules/courseware-html-generator.mdc"),
    "cline": Path(".clinerules/courseware-html-generator.md"),
    "continue": Path(".continue/rules/courseware-html-generator.md"),
    "windsurf": Path(".windsurf/rules/courseware-html-generator.md"),
    "opencode": Path(".opencode/rules/courseware-html-generator.md"),
}
ADAPTER_PAYLOAD = """HTML 课件生成器规则：

- 先阅读 `.courseware-html-generator/简介.md`、`通用提示词.md` 和 `SKILL.md`（若目标项目只安装规则，则读取源 Skill 的对应文件）。
- Agent 负责理解教材、PPT、讲义或教案，创作 Courseware Content Contract 1.0；Python renderer 负责确定性 HTML/CSS/JS、离线输出和 QA。
- 同时生成学生展示版和教师逐页备课版。学生页不得出现教师备注、来源措辞、制作信息或任何分钟/控时信息；教师逐字稿必须是自然中文连续讲解。
- 学生页必须支持任意非交互区域点击下一页、稳定 wheel 上下翻页、键盘备用和投影增强；交互按钮不得误翻页。
- 输出必须是无服务器、无 CDN、无外部字体/图片的单文件 HTML；交付前运行合同/输出 QA，并在真实浏览器中验证 click、wheel、file:// 和交互控件。
"""


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _marker_block(payload: str) -> str:
    return f"{MARKER_START}\n{payload.strip()}\n{MARKER_END}"


def merge_marker_section(existing: str, payload: str) -> str:
    starts = [existing.find(MARKER_START)] if MARKER_START in existing else []
    ends = [existing.find(MARKER_END)] if MARKER_END in existing else []
    if len(starts) != len(ends) or (starts and (ends[0] < starts[0] or existing.find(MARKER_START, starts[0] + 1) != -1)):
        raise ValueError(f"Malformed {MARKER_ID} marker block; refusing to mutate target")
    block = _marker_block(payload)
    if starts:
        prefix = existing[: starts[0]].rstrip("\r\n")
        suffix = existing[ends[0] + len(MARKER_END) :].lstrip("\r\n")
        return (prefix + "\n\n" if prefix else "") + block + ("\n\n" + suffix if suffix else "\n")
    return (existing.rstrip("\r\n") + "\n\n" if existing.strip() else "") + block + "\n"


def _engine_state(source_root: Path, files: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files, key=lambda item: item.as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update((source_root / relative).read_bytes())
    return json.dumps({"schema": 1, "skill": MARKER_ID, "mode": "full", "sha256": digest.hexdigest()}, indent=2) + "\n"


def _source_files(source_root: Path, full: bool) -> tuple[Path, ...]:
    files = FULL_ENGINE_FILES if full else MINIMAL_ENGINE_FILES
    missing = [relative for relative in files if not (source_root / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing engine files: " + ", ".join(str(item) for item in missing))
    return files


def _remove(path: Path | None) -> None:
    if path is None or not _exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def install(
    source_root: Path,
    target_root: Path,
    *,
    adapters: list[str] | None = None,
    replace: bool = False,
    copy_engine: bool = False,
    dry_run: bool = False,
) -> dict[str, str]:
    source_root = source_root.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    selected = adapters or ["all"]
    names = list(ADAPTER_PATHS) if "all" in selected else list(dict.fromkeys(selected))
    unknown = [name for name in names if name not in ADAPTER_PATHS]
    if unknown:
        raise ValueError("unknown adapters: " + ", ".join(unknown))
    if source_root == target_root or source_root in target_root.parents or target_root in source_root.parents:
        raise ValueError("source root and target root must not overlap")
    engine_files = _source_files(source_root, copy_engine)
    plan: dict[Path, str] = {}
    for name in names:
        relative = ADAPTER_PATHS[name]
        target = target_root / relative
        if target.is_symlink():
            raise ValueError(f"refusing to modify symlinked adapter target: {target}")
        if _exists(target) and not target.is_file():
            raise ValueError(f"adapter target is not a regular file: {target}")
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        plan[relative] = merge_marker_section(existing, ADAPTER_PAYLOAD)
    engine_target = target_root / ENGINE_NAME
    if copy_engine and _exists(engine_target) and not replace:
        raise FileExistsError(f"engine exists: {engine_target}; use --replace")
    print(f"source={source_root}")
    print(f"target={target_root}")
    if dry_run:
        for relative in sorted(plan, key=lambda item: item.as_posix()):
            print(f"would-update={target_root / relative}")
        if copy_engine:
            print(f"would-update={engine_target}")
        return {"status": "dry-run", "mode": "full" if copy_engine else "minimal"}

    target_root.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".courseware-adapter-stage-", dir=str(target_root.parent)))
    committed: list[tuple[Path, Path | None]] = []
    try:
        for relative, payload in plan.items():
            destination = stage_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(payload, encoding="utf-8", newline="\n")
        staged_engine: Path | None = None
        if copy_engine:
            staged_engine = stage_root / ENGINE_NAME
            for relative in engine_files:
                destination = staged_engine / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_root / relative, destination)
            (staged_engine / ".engine-state.json").write_text(_engine_state(source_root, engine_files), encoding="utf-8", newline="\n")
        for relative in sorted(plan, key=lambda item: item.as_posix()):
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup = destination.with_name(destination.name + ".courseware-backup") if _exists(destination) else None
            if backup is not None:
                _remove(backup)
                os.replace(str(destination), str(backup))
            os.replace(str(stage_root / relative), str(destination))
            committed.append((destination, backup))
        if staged_engine is not None:
            backup = target_root / f"{ENGINE_NAME}.backup"
            if _exists(backup):
                _remove(backup)
            if _exists(engine_target):
                os.replace(str(engine_target), str(backup))
            os.replace(str(staged_engine), str(engine_target))
            committed.append((engine_target, backup if backup.exists() else None))
    except Exception:
        for destination, backup in reversed(committed):
            _remove(destination)
            if backup is not None and _exists(backup):
                os.replace(str(backup), str(destination))
        raise
    finally:
        _remove(stage_root)
    for _, backup in committed:
        _remove(backup)
    return {"status": "pass", "mode": "full" if copy_engine else "minimal"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--adapter", action="append", choices=[*ADAPTER_PATHS, "all"], dest="adapters")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--copy-engine", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = install(
        args.source_root,
        args.target_dir,
        adapters=args.adapters,
        replace=args.replace,
        copy_engine=args.copy_engine,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
