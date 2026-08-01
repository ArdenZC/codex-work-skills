from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    {
        "name": "lesson-plan-v1.0.0",
        "manifest": ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml",
        "schema": ROOT / "教案生成器" / "lesson-plan-docx-generator" / "schemas" / "lesson-plan-input.schema.json",
    },
    {
        "name": "lesson-plan-v1.1.0",
        "manifest": ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "manifest.yaml",
        "schema": ROOT / "教案生成器" / "lesson-plan-docx-generator" / "schemas" / "lesson-plan-input.schema.json",
    },
    {
        "name": "course-gradebook",
        "manifest": ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "manifest.yaml",
        "schema": ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "schemas" / "gradebook-input.schema.json",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validate_package(package: dict[str, Path | str]) -> str:
    manifest_path = Path(package["manifest"])
    schema_path = Path(package["schema"])
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream)
    if not isinstance(manifest, dict):
        raise ValueError(f"{package['name']}: manifest must be a mapping")

    template_info = manifest.get("template", {})
    fingerprint = manifest.get("fingerprint", {})
    canonical = manifest_path.parent / str(template_info.get("file", ""))
    expected_hash = str(fingerprint.get("sha256") or fingerprint.get("value") or "").upper()
    if not canonical.exists():
        raise FileNotFoundError(f"{package['name']}: canonical template not found: {canonical}")
    if len(expected_hash) != 64:
        raise ValueError(f"{package['name']}: manifest fingerprint is not a SHA-256 value")

    paths = [canonical]
    paths.extend((manifest_path.parent / str(entry)).resolve() for entry in template_info.get("compatibility_entries", []))
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"{package['name']}: compatibility template not found: {path}")
        actual_hash = sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(f"{package['name']}: SHA-256 mismatch for {path.name}: {actual_hash}")

    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    Draft202012Validator.check_schema(schema)
    version = template_info.get("version")
    return f"{package['name']}: version={version} sha256={expected_hash} schema=valid"


def main() -> int:
    try:
        for package in PACKAGES:
            print(validate_package(package))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
