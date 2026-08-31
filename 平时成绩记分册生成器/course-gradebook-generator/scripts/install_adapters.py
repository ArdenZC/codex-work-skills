from __future__ import annotations

import argparse
import shutil
import re
import uuid
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

ENGINE_NAME = ".course-gradebook-generator"
SHARED_SOURCES = {
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "GEMINI.md": "GEMINI.md",
    ".github/copilot-instructions.md": ".github/copilot-instructions.md",
    "CONVENTIONS.md": "CONVENTIONS.md",
}
MARKER_START = "<!-- codex-skill: course-gradebook-generator:start -->"
MARKER_END = "<!-- codex-skill: course-gradebook-generator:end -->"


def _rewrite_references(text: str) -> str:
    for bare, namespaced in {
        "SKILL.md": f"{ENGINE_NAME}/SKILL.md",
        "通用提示词.md": f"{ENGINE_NAME}/通用提示词.md",
        "AGENTS.md": f"{ENGINE_NAME}/AGENTS.md",
        "CLAUDE.md": f"{ENGINE_NAME}/CLAUDE.md",
        "GEMINI.md": f"{ENGINE_NAME}/GEMINI.md",
        "CONVENTIONS.md": f"{ENGINE_NAME}/CONVENTIONS.md",
    }.items():
        text = re.sub(rf"(?<![./\w-]){re.escape(bare)}", namespaced, text)
    return text


def _merge_shared(existing: str, payload: str) -> str:
    block = f"{MARKER_START}\n{payload.strip()}\n{MARKER_END}"
    start, end = existing.find(MARKER_START), existing.find(MARKER_END)
    if (start < 0) != (end < 0) or (start >= 0 and end < start):
        raise ValueError("Malformed course-gradebook-generator marker block")
    if start >= 0:
        end += len(MARKER_END)
        return existing[:start].rstrip("\r\n") + "\n\n" + block + existing[end:]
    return block + "\n" if not existing.strip() else existing.rstrip("\r\n") + "\n\n" + block + "\n"


def _merge_aider(existing: str) -> str:
    required = [
        f"{ENGINE_NAME}/SKILL.md",
        f"{ENGINE_NAME}/通用提示词.md",
        f"{ENGINE_NAME}/AGENTS.md",
        f"{ENGINE_NAME}/CONVENTIONS.md",
    ]
    if not existing.strip():
        return "read:\n" + "".join(f"  - {item}\n" for item in required)
    lines = existing.splitlines()
    in_read = False
    paths: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.fullmatch(r"read\s*:\s*", stripped) and not in_read:
            in_read = True
            continue
        if in_read and re.fullmatch(r"-\s+[^:#]+", stripped):
            paths.append(stripped[1:].strip().strip('"\''))
            continue
        raise ValueError("complex or unparseable .aider.conf.yml; refusing to mutate")
    if not in_read:
        raise ValueError(".aider.conf.yml has no simple read list; refusing to mutate")
    missing = [item for item in required if item not in paths]
    return existing.rstrip("\r\n") + ("\n" if missing else "\n") + "".join(f"  - {item}\n" for item in missing)

def copy_file(source_root: Path, target_root: Path, relative: str, replace: bool, dry_run: bool) -> None:
    source = source_root / relative
    target = target_root / relative
    if relative in SHARED_SOURCES:
        payload = _merge_shared(target.read_text(encoding="utf-8") if target.is_file() else "", _rewrite_references(source.read_text(encoding="utf-8")))
        if target.is_file() and target.read_bytes() == payload.encode("utf-8"):
            print(f"unchanged={target}")
            return
    elif relative == ".aider.conf.yml":
        payload = _merge_aider(target.read_text(encoding="utf-8") if target.is_file() else "").encode("utf-8")
        if target.is_file() and target.read_bytes() == payload:
            print(f"unchanged={target}")
            return
    else:
        payload = source.read_bytes()
        if target.exists() and not replace:
            print(f"skip existing={target}")
            return
    if dry_run:
        print(f"copy {source} -> {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_name(f"{target.name}.backup_{uuid.uuid4().hex}")
        shutil.move(str(target), str(backup))
        print(f"backup={backup}")
    target.write_bytes(payload.encode("utf-8") if isinstance(payload, str) else payload)
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
