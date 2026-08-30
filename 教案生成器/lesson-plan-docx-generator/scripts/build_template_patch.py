"""Build a lesson-plan patch template without changing protected DOCX structure."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path

import yaml

from path_safety import paths_overlap


def _replace_document_text(document_xml: bytes, replacements: list[tuple[str, str]]) -> bytes:
    for old_text, new_text in replacements:
        old_bytes, new_bytes = old_text.encode("utf-8"), new_text.encode("utf-8")
        occurrences = document_xml.count(old_bytes)
        if occurrences <= 0:
            raise ValueError(f"Expected at least one visible occurrence of {old_text!r}, found {occurrences}")
        document_xml = document_xml.replace(old_bytes, new_bytes)
    return document_xml


def _canonical_paths() -> set[Path]:
    skill_dir = Path(__file__).resolve().parents[1]
    package_root = skill_dir / "assets" / "templates" / "lesson-plan"
    protected = {
        skill_dir / "assets" / "lesson-plan-template.docx",
    }
    for version in ("v1.0.0", "v1.1.0", "v1.1.1", "v1.1.2"):
        protected.add(package_root / version)
    return {path.resolve(strict=False) for path in protected}


def _assert_target_safe(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Source template not found: {source}")
    if source.resolve() == target.resolve():
        raise ValueError("Source and target templates must be different files")
    if target.exists() or target.is_symlink():
        raise FileExistsError(
            f"Refusing to overwrite existing target; choose a new path: {target}"
        )
    for protected in _canonical_paths():
        if paths_overlap(target, protected):
            raise ValueError(f"Refusing to write protected canonical template path: {target}")


def build_patch(source: Path, target: Path, replacements: list[tuple[str, str]]) -> None:
    if source.resolve() == target.resolve():
        raise ValueError("Source and target templates must be different files")
    _assert_target_safe(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(temporary, "w") as target_zip:
            for info in source_zip.infolist():
                payload = source_zip.read(info.filename)
                if info.filename == "word/document.xml":
                    payload = _replace_document_text(payload, replacements)
                target_zip.writestr(info, payload)
        os.replace(str(temporary), str(target))
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--manifest", type=Path, help="Read template.patches.visible_text_replacements from a UTF-8 YAML manifest")
    parser.add_argument("--replace", action="append", metavar="OLD=NEW")
    args = parser.parse_args()
    replacements: list[tuple[str, str]] = []
    values = list(args.replace or [])
    if args.manifest:
        manifest = yaml.safe_load(args.manifest.expanduser().resolve().read_text(encoding="utf-8")) or {}
        patches = manifest.get("template", {}).get("patches", {})
        for item in patches.get("visible_text_replacements", []):
            values.append(f"{item['from']}={item['to']}")
    if not values:
        parser.error("provide --manifest or at least one --replace")
    for value in values:
        if "=" not in value:
            parser.error("--replace must use OLD=NEW")
        old_text, new_text = value.split("=", 1)
        if not old_text or not new_text or old_text == new_text:
            parser.error("--replace values must contain two different non-empty strings")
        replacements.append((old_text, new_text))
    build_patch(args.source.expanduser().resolve(), args.target.expanduser().resolve(), replacements)
    print(f"patched={args.target.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
