"""Check the repository-facing WorkOrder Skill facade and version references."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


WORKORDER_RELATIVE = Path("实践任务工单生成器") / "practice-task-workorder-generator"
SKILL_VERSION = "2.1.0"
TEMPLATE_VERSION = "1.0.0"
TEMPLATE_REF = "practice-work-order v1.0.0"


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _manifest_fields(path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Read the small scalar surface needed by the docs-only facade check.

    The repository manifest is intentionally simple for these fields. Keeping
    this check on the standard library means the documentation job does not
    need to install the WorkOrder runtime just to compare version references.
    """

    top: dict[str, str] = {}
    sections: dict[str, dict[str, str]] = {}
    section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        top_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?", line)
        if top_match:
            section = top_match.group(1) if not top_match.group(2) else None
            if top_match.group(2):
                top[top_match.group(1)] = _scalar(top_match.group(2))
            else:
                sections.setdefault(section, {})
            continue
        field_match = re.fullmatch(r"  ([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", line)
        if field_match and section:
            sections.setdefault(section, {})[field_match.group(1)] = _scalar(field_match.group(2))
    return top, sections


def check(root: Path) -> list[str]:
    package = root / WORKORDER_RELATIVE
    intro = package / "简介.md"
    skill = package / "SKILL.md"
    manifest_path = package / "manifest.yaml"
    install = package / "scripts" / "install.py"
    errors: list[str] = []
    for path in (intro, skill, manifest_path, install):
        if not path.is_file():
            errors.append(f"missing WorkOrder facade entry: {path.relative_to(root)}")
    if errors:
        return errors

    try:
        top, sections = _manifest_fields(manifest_path)
    except OSError as exc:
        return [f"cannot read WorkOrder manifest: {exc}"]
    template = sections.get("template", {})
    generator = sections.get("generator", {})
    if template.get("id") != "practice-work-order":
        errors.append("WorkOrder manifest template.id must be practice-work-order")
    if str(template.get("version")) != TEMPLATE_VERSION:
        errors.append(f"WorkOrder manifest template.version must be {TEMPLATE_VERSION}")
    if str(generator.get("version")) != SKILL_VERSION:
        errors.append(f"WorkOrder manifest generator.version must be {SKILL_VERSION}")
    if top.get("schema") != "schemas/work-order-content.schema.json":
        errors.append("WorkOrder manifest schema must point to schemas/work-order-content.schema.json")

    readme = (root / "README.md").read_text(encoding="utf-8")
    intro_text = intro.read_text(encoding="utf-8")
    skill_text = skill.read_text(encoding="utf-8")
    install_text = install.read_text(encoding="utf-8")
    for label, text in (
        ("README.md", readme),
        ("实践任务工单生成器/简介.md", intro_text),
        ("实践任务工单生成器/SKILL.md", skill_text),
    ):
        if TEMPLATE_REF not in text:
            errors.append(f"{label} is missing {TEMPLATE_REF}")
    if f"{SKILL_VERSION}" not in readme or f"{SKILL_VERSION}" not in intro_text:
        errors.append("README and WorkOrder 简介 must expose WorkOrder Skill version 2.1.0")
    if "practice-task-workorder-generator" not in readme:
        errors.append("README is missing the WorkOrder Skill reference")
    if "SKILL_NAME = \"practice-task-workorder-generator\"" not in install_text:
        errors.append("WorkOrder install entry is missing its canonical skill name")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    errors = check(args.repo_root.expanduser().resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"WorkOrder facade: Skill {SKILL_VERSION}; template {TEMPLATE_REF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
