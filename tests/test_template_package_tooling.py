from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "template_package.py"
PYTHON = Path(sys.executable)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class TemplatePackageToolingTests(unittest.TestCase):
    maxDiff = None

    def run_tool(self, *arguments: str | Path, root: Path = ROOT) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PYTHON), str(TOOL), "--repo-root", str(root), *[str(argument) for argument in arguments]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def json_result(self, result: subprocess.CompletedProcess[str]) -> dict:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"tool output was not JSON: {result.stdout}\nstderr={result.stderr}")
            raise AssertionError from exc

    def make_fixture_repo(
        self,
        temp_root: Path,
        *,
        template_id: str = "demo-template",
        version: str = "1.0.0",
        validator_mode: str = "pass",
        with_changelog: bool = True,
    ) -> tuple[Path, Path, Path]:
        skill_root = temp_root / "技能工具" / "demo-skill"
        package = skill_root / "assets" / "templates" / template_id / f"v{version}"
        package.mkdir(parents=True)
        template = package / "template.txt"
        template.write_text("canonical template\n", encoding="utf-8")
        digest = sha256(template)
        manifest = {
            "template": {
                "id": template_id,
                "name": "Fixture template",
                "version": version,
                "format": "txt",
                "file": "template.txt",
            },
            "generator": {"version": "1.0.0", "supported_major": 1},
            "fingerprint": {"algorithm": "sha256", "sha256": digest, "value": digest},
        }
        (package / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        if with_changelog:
            (package / "CHANGELOG.md").write_text("# Fixture\n", encoding="utf-8")
        scripts = skill_root / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "validate_template.py").write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "if (Path(__file__).resolve().parent.parent / 'validator-fail').exists():\n"
            "    print('fixture validator failed', file=sys.stderr)\n"
            "    raise SystemExit(7)\n"
            "print('fixture validator passed')\n",
            encoding="utf-8",
        )
        return skill_root, package, template

    def make_repo_validator(self, root: Path) -> None:
        tests_dir = root / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "validate_template_packages.py").write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "if (root / 'repo-fail').exists():\n"
            "    print('repo validator failed', file=sys.stderr)\n"
            "    raise SystemExit(9)\n"
            "print('repo validator passed')\n",
            encoding="utf-8",
        )

    def test_discover_current_four_packages_without_libreoffice(self) -> None:
        result = self.run_tool("discover", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self.json_result(result)
        self.assertEqual(payload["count"], 4)
        self.assertEqual({(item["id"], item["version"]) for item in payload["packages"]}, {
            ("lesson-plan", "1.0.0"),
            ("lesson-plan", "1.1.0"),
            ("course-gradebook", "1.0.0"),
            ("course-gradebook", "1.1.0"),
        })
        defaults = {(item["id"], item["version"]) for item in payload["packages"] if item["is_default"]}
        self.assertEqual(defaults, {("lesson-plan", "1.1.0"), ("course-gradebook", "1.1.0")})
        self.assertEqual(payload["errors"], [])

    def test_identity_only_validates_all_current_packages_without_full_pass_claim(self) -> None:
        packages = [
            ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.0.0",
            ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0",
            ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "assets" / "templates" / "course-gradebook" / "v1.0.0",
            ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "assets" / "templates" / "course-gradebook" / "v1.1.0",
        ]
        for package in packages:
            with self.subTest(package=package):
                result = self.run_tool("validate", "--package", package, "--identity-only", "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = self.json_result(result)
                self.assertEqual(payload["status"], "identity_only")
                self.assertFalse(payload["full_validation"])
                self.assertEqual(payload["errors"], [])

    def test_validate_fixture_invokes_real_owner_validator_and_captures_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            result = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = self.json_result(result)
            self.assertEqual(payload["status"], "passed")
            self.assertTrue(payload["full_validation"])
            self.assertEqual(payload["validator"]["exit_code"], 0)
            self.assertIn("fixture validator passed", payload["validator"]["stdout"])
            (package.parent.parent.parent.parent / "validator-fail").write_text("fail\n", encoding="utf-8")
            failed = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assertNotEqual(failed.returncode, 0)
            failed_payload = self.json_result(failed)
            self.assertEqual(failed_payload["validator"]["exit_code"], 7)
            self.assertIn("fixture validator failed", failed_payload["validator"]["stderr"])

    def test_validate_rejects_tampered_fingerprint_before_validator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            manifest_path = package / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["fingerprint"]["sha256"] = "0" * 64
            manifest["fingerprint"]["value"] = "0" * 64
            manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            result = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assertNotEqual(result.returncode, 0)
            payload = self.json_result(result)
            self.assertEqual(payload["status"], "failed")
            self.assertTrue(any("fingerprint mismatch" in error for error in payload["errors"]))
            self.assertIsNone(payload["validator"])

    def test_discover_rejects_duplicate_identity_and_invalid_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            duplicate = root / "另一个技能" / "assets" / "templates" / "demo-template" / "v1.0.0"
            duplicate.parent.mkdir(parents=True)
            shutil.copytree(package, duplicate)
            duplicate_scripts = root / "另一个技能" / "scripts"
            duplicate_scripts.mkdir(parents=True)
            shutil.copy2(skill / "scripts" / "validate_template.py", duplicate_scripts / "validate_template.py")
            invalid = root / "坏包" / "assets" / "templates" / "bad" / "v01.0.0"
            invalid.mkdir(parents=True)
            (invalid / "manifest.yaml").write_text(
                "template:\n  id: bad\n  version: v1.0.0\n  format: txt\n  file: missing.txt\n",
                encoding="utf-8",
            )
            shutil.copy2(skill / "scripts" / "validate_template.py", root / "坏包" / "validate_template.py")
            result = self.run_tool("discover", "--json", root=root)
            self.assertNotEqual(result.returncode, 0)
            payload = self.json_result(result)
            errors = "\n".join(error for item in payload["errors"] for error in item["errors"])
            self.assertIn("duplicate template id/version", errors)
            self.assertIn("invalid semantic version", errors)

    def test_discover_rejects_version_mismatch_missing_template_bad_fingerprint_and_missing_validator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root, template_id="mismatch")
            mismatch = root / "版本错配" / "assets" / "templates" / "mismatch" / "v1.0.1"
            mismatch.parent.mkdir(parents=True)
            shutil.copytree(package, mismatch)
            missing = root / "缺模板" / "assets" / "templates" / "missing" / "v1.0.0"
            missing.parent.mkdir(parents=True)
            shutil.copytree(package, missing)
            missing_manifest = yaml.safe_load((missing / "manifest.yaml").read_text(encoding="utf-8"))
            missing_manifest["template"]["id"] = "missing"
            (missing / "manifest.yaml").write_text(yaml.safe_dump(missing_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            (missing / "template.txt").unlink()
            bad_fingerprint = root / "坏指纹" / "assets" / "templates" / "bad-fingerprint" / "v1.0.0"
            bad_fingerprint.parent.mkdir(parents=True)
            shutil.copytree(package, bad_fingerprint)
            bad_manifest = yaml.safe_load((bad_fingerprint / "manifest.yaml").read_text(encoding="utf-8"))
            bad_manifest["template"]["id"] = "bad-fingerprint"
            bad_manifest["fingerprint"]["sha256"] = "not-a-sha"
            bad_manifest["fingerprint"]["value"] = "not-a-sha"
            (bad_fingerprint / "manifest.yaml").write_text(yaml.safe_dump(bad_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            no_validator = root / "无校验器" / "assets" / "templates" / "no-validator" / "v1.0.0"
            no_validator.parent.mkdir(parents=True)
            shutil.copytree(package, no_validator)
            no_manifest = yaml.safe_load((no_validator / "manifest.yaml").read_text(encoding="utf-8"))
            no_manifest["template"]["id"] = "no-validator"
            (no_validator / "manifest.yaml").write_text(yaml.safe_dump(no_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            shutil.rmtree(skill / "scripts")
            result = self.run_tool("discover", "--json", root=root)
            self.assertNotEqual(result.returncode, 0)
            payload = self.json_result(result)
            errors = "\n".join(error for item in payload["errors"] for error in item["errors"])
            self.assertIn("does not equal manifest version", errors)
            self.assertIn("template file does not exist", errors)
            self.assertIn("fingerprint must be a 64-character", errors)
            self.assertIn("owner validator scripts/validate_template.py was not found", errors)

    def test_scaffold_patch_updates_only_declared_manifest_fields_and_passes_real_validation(self) -> None:
        base = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0"
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            workspace = Path(directory) / "中文工作包" / "lesson-plan"
            output = workspace / "1.1.1"
            result = self.run_tool(
                "scaffold",
                "--base-package",
                base,
                "--version",
                "1.1.1",
                "--output-dir",
                output,
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = self.json_result(result)
            self.assertTrue(report["promotable"])
            self.assertTrue(output.is_dir())
            self.assertTrue((workspace / "v1.0.0" / "manifest.yaml").is_file())
            self.assertFalse((output / "scaffold-report.json").exists())
            self.assertTrue((workspace / "scaffold-report.json").is_file())
            original = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
            generated = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(generated["generator"], original["generator"])
            self.assertEqual(generated["template"]["version"], "1.1.1")
            self.assertEqual(generated["fingerprint"]["sha256"], sha256(output / "template.docx"))
            original["template"].pop("version")
            generated["template"].pop("version")
            for value in (original, generated):
                value["fingerprint"].pop("sha256", None)
                value["fingerprint"].pop("value", None)
            self.assertEqual(generated, original)
            validated = self.run_tool("validate", "--package", output, "--json")
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(self.json_result(validated)["status"], "passed")
            generator_output = Path(directory) / "generator-version" / "1.1.2"
            generated_scaffold = self.run_tool(
                "scaffold",
                "--base-package",
                base,
                "--version",
                "1.1.2",
                "--output-dir",
                generator_output,
                "--generator-version",
                "9.9.9",
                "--json",
            )
            self.assertEqual(generated_scaffold.returncode, 0, generated_scaffold.stderr)
            generated_override = yaml.safe_load((generator_output / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(generated_override["generator"]["version"], "9.9.9")

    def test_scaffold_unsupported_minor_requires_opt_in_and_is_not_promotable(self) -> None:
        base = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0"
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            rejected = root / "reject" / "1.2.0"
            result = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.2.0", "--output-dir", rejected, "--json"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(rejected.exists())
            output = root / "allow" / "1.2.0"
            result = self.run_tool(
                "scaffold",
                "--base-package",
                base,
                "--version",
                "1.2.0",
                "--output-dir",
                output,
                "--allow-unsupported-minor",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = self.json_result(result)
            self.assertFalse(report["promotable"])
            self.assertEqual(report["reason"], "Template minor is not supported by the current generator contract.")

    def test_scaffold_dry_run_and_overlap_do_not_mutate(self) -> None:
        base = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0"
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            output = root / "dry" / "1.1.1"
            result = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.1.1", "--output-dir", output, "--dry-run", "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(self.json_result(result)["dry_run"])
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())
            overlap = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.1.1", "--output-dir", base / "1.1.1", "--json"
            )
            self.assertNotEqual(overlap.returncode, 0)
            self.assertIn("overlaps protected path", overlap.stdout + overlap.stderr)

    def test_promote_success_and_target_exists_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            source = root / "work" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
            base_sha = sha256(base / "template.txt")
            dry_run = self.run_tool("promote", "--package", source, "--dry-run", "--json", root=root)
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertTrue(self.json_result(dry_run)["dry_run"])
            self.assertFalse((root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1").exists())
            self.assertEqual(sha256(base / "template.txt"), base_sha)
            promoted = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assertEqual(promoted.returncode, 0, promoted.stderr)
            target = root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1"
            self.assertTrue(target.is_dir())
            self.assertTrue(source.is_dir())
            self.assertFalse(any(path.name.endswith(".stage") for path in target.parent.iterdir()))
            repeated = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("already exists", repeated.stdout + repeated.stderr)

    def test_promote_repo_validator_failure_rolls_back_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            (root / "repo-fail").write_text("fail\n", encoding="utf-8")
            source = root / "work" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
            promoted = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assertNotEqual(promoted.returncode, 0)
            target = root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1"
            self.assertFalse(target.exists())
            self.assertFalse(any("stage" in path.name or "backup" in path.name for path in target.parent.iterdir()))

    def test_promote_rejects_unsupported_minor_and_validator_failure_without_install(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            unsupported = root / "work" / "demo-template" / "1.1.0"
            scaffold = self.run_tool(
                "scaffold",
                "--base-package",
                base,
                "--version",
                "1.1.0",
                "--output-dir",
                unsupported,
                "--allow-unsupported-minor",
                "--json",
                root=root,
            )
            self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
            promoted = self.run_tool("promote", "--package", unsupported, "--json", root=root)
            self.assertNotEqual(promoted.returncode, 0)
            self.assertFalse((skill / "assets" / "templates" / "demo-template" / "1.1.0").exists())

            valid_patch = root / "work-second" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", valid_patch, "--json", root=root
            )
            self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
            (skill / "validator-fail").write_text("fail\n", encoding="utf-8")
            failed = self.run_tool("promote", "--package", valid_patch, "--json", root=root)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse((skill / "assets" / "templates" / "demo-template" / "v1.0.1").exists())

    def test_archive_is_deterministic_self_describing_and_excludes_build_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            (package / "qa-report.json").write_text("{}\n", encoding="utf-8")
            (package / "scaffold-report.json").write_text("{}\n", encoding="utf-8")
            (package / "__pycache__").mkdir()
            (package / "__pycache__" / "junk.pyc").write_bytes(b"junk")
            (package / "~$office.tmp").write_bytes(b"junk")
            (package / "build.stage").mkdir()
            (package / "build.stage" / "junk.txt").write_text("junk", encoding="utf-8")
            first_dir = root / "dist-a"
            second_dir = root / "dist-b"
            first = self.run_tool("archive", "--package", package, "--output-dir", first_dir, "--json", root=root)
            second = self.run_tool("archive", "--package", package, "--output-dir", second_dir, "--json", root=root)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_payload = self.json_result(first)
            second_payload = self.json_result(second)
            self.assertEqual(first_payload["archive_sha256"], second_payload["archive_sha256"])
            archive_path = first_dir / "demo-template-1.0.0.zip"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, ["CHANGELOG.md", "manifest.yaml", "template.txt"])
                self.assertFalse(any("qa" in name or "stage" in name for name in names))
                self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
            sidecar = (first_dir / "demo-template-1.0.0.zip.sha256").read_text(encoding="ascii")
            self.assertIn(first_payload["archive_sha256"], sidecar)
            metadata = json.loads((first_dir / "demo-template-1.0.0.zip.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["archive_sha256"], first_payload["archive_sha256"])
            self.assertEqual(metadata["template_sha256"], sha256(package / "template.txt"))

    def test_archive_rejects_overlap_tampering_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, template = self.make_fixture_repo(root)
            overlap = self.run_tool("archive", "--package", package, "--output-dir", package / "dist", "--json", root=root)
            self.assertNotEqual(overlap.returncode, 0)
            self.assertIn("overlaps", overlap.stdout + overlap.stderr)
            template.write_text("tampered\n", encoding="utf-8")
            tampered = self.run_tool("archive", "--package", package, "--output-dir", root / "dist", "--json", root=root)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("fingerprint mismatch", tampered.stdout + tampered.stderr)

            _, package, _ = self.make_fixture_repo(root, template_id="symlink-template")
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            link = package / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("the current Windows account cannot create symlinks")
            linked = self.run_tool("archive", "--package", package, "--output-dir", root / "dist-link", "--json", root=root)
            self.assertNotEqual(linked.returncode, 0)
            self.assertIn("symlink", linked.stdout + linked.stderr)

    def test_archive_dry_run_does_not_create_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            output = root / "dist"
            result = self.run_tool("archive", "--package", package, "--output-dir", output, "--dry-run", "--json", root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(self.json_result(result)["dry_run"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
