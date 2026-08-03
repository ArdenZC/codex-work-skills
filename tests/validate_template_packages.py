from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
LESSON_SCRIPTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "scripts"
GRADE_SCRIPTS = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "scripts"
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
        "name": "course-gradebook-v1.0.0",
        "manifest": ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "manifest.yaml",
        "schema": ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "schemas" / "gradebook-input.schema.json",
    },
    {
        "name": "course-gradebook-v1.1.0",
        "manifest": ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "assets" / "templates" / "course-gradebook" / "v1.1.0" / "manifest.yaml",
        "schema": ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "schemas" / "gradebook-input.schema.json",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _libreoffice_version() -> str:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        shutil.which("soffice.com"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        "/usr/bin/libreoffice",
        "/usr/local/bin/libreoffice",
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"<version lookup failed: {exc}>"
        output = (result.stdout or result.stderr).strip()
        return output.splitlines()[0] if output else f"<exit {result.returncode}>"
    return "<not found>"


def _validator_failure_diagnostics(result: subprocess.CompletedProcess[str]) -> str:
    environment = {
        "platform": platform.platform(),
        "python": sys.version,
        "libreoffice": _libreoffice_version(),
    }
    try:
        import openpyxl

        environment["openpyxl"] = openpyxl.__version__
    except Exception as exc:
        environment["openpyxl"] = f"<import failed: {exc}>"

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return (
            "validator output was not valid JSON\n"
            f"environment={json.dumps(environment, ensure_ascii=False)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    checks = report.get("checks", {}) if isinstance(report, dict) else {}
    protected = checks.get("protected_signature_differences", [])
    if not isinstance(protected, list):
        protected = [protected]
    diagnostics = {
        "environment": environment,
        "errors": report.get("errors", []) if isinstance(report, dict) else [],
        "protected_signature_differences": protected[:50],
        "named_ranges_xls_errors": (
            checks.get("named_ranges_xls", {}).get("errors", [])
            if isinstance(checks.get("named_ranges_xls", {}), dict)
            else []
        ),
        "named_ranges_xlsx_errors": (
            checks.get("named_ranges_xlsx", {}).get("errors", [])
            if isinstance(checks.get("named_ranges_xlsx", {}), dict)
            else []
        ),
    }
    return json.dumps(diagnostics, ensure_ascii=False, indent=2)


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
    if package["name"].startswith("lesson-plan-"):
        scripts_path = str(LESSON_SCRIPTS)
        if scripts_path in sys.path:
            sys.path.remove(scripts_path)
        sys.path.insert(0, scripts_path)
        sys.modules.pop("package_common", None)
        from package_common import anchor_mode, validate_legacy_manifest_contract, validate_semantic_manifest_contract

        mode = anchor_mode(manifest)
        if mode == "legacy_coordinates":
            validate_legacy_manifest_contract(manifest)
        else:
            validate_semantic_manifest_contract(manifest)
    if package["name"].startswith("course-gradebook-"):
        scripts_path = str(GRADE_SCRIPTS)
        if scripts_path in sys.path:
            sys.path.remove(scripts_path)
        sys.path.insert(0, scripts_path)
        for module_name in ("package_common", "named_range_contracts", "named_range_utils", "xls_named_range_utils"):
            sys.modules.pop(module_name, None)
        from package_common import validate_manifest_contract

        validate_manifest_contract(manifest)
        result = subprocess.run(
            [
                sys.executable,
                str(GRADE_SCRIPTS / "validate_template.py"),
                "--template",
                str(canonical),
                "--manifest",
                str(manifest_path),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValueError(
                f"{package['name']}: template validator failed:\n"
                f"{_validator_failure_diagnostics(result)}"
            )
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
