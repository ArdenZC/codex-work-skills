from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from typing import Any

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


class TemplatePackageReleaseTests(unittest.TestCase):
    maxDiff = None

    def run_tool(
        self,
        *arguments: str | Path,
        root: Path = ROOT,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        return subprocess.run(
            [str(PYTHON), str(TOOL), "--repo-root", str(root), *[str(argument) for argument in arguments]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )

    def json_result(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"CLI did not emit JSON: {result.stdout}\nstderr={result.stderr}")
            raise AssertionError from exc

    def assert_succeeded(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertEqual(
            result.returncode,
            0,
            f"command={result.args!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        return self.json_result(result)

    def assert_failed(self, result: subprocess.CompletedProcess[str], *messages: str) -> dict[str, Any]:
        self.assertNotEqual(
            result.returncode,
            0,
            f"command unexpectedly succeeded={result.args!r}\nstdout={result.stdout}",
        )
        payload = self.json_result(result)
        text = result.stdout + result.stderr
        for message in messages:
            self.assertIn(message.lower(), text.lower())
        return payload

    def git(self, root: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def make_fixture_repo(
        self,
        root: Path,
        *,
        versions: tuple[str, ...] = ("1.1.1", "1.1.2"),
    ) -> tuple[Path, dict[str, Path]]:
        skill = root / "fixture-skill"
        scripts = skill / "scripts"
        schemas = skill / "schemas"
        template_root = skill / "assets" / "templates" / "demo-template"
        scripts.mkdir(parents=True)
        schemas.mkdir(parents=True)
        template_root.mkdir(parents=True)
        (schemas / "demo.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
        (scripts / "helper.py").write_text('VALUE = "trusted"\n', encoding="utf-8")
        (scripts / "validate_template.py").write_text(
            "from pathlib import Path\n"
            "import os\n"
            "import helper\n"
            "import sys\n"
            "import yaml\n"
            "manifest = Path(sys.argv[sys.argv.index('--manifest') + 1])\n"
            "template = Path(sys.argv[sys.argv.index('--template') + 1])\n"
            "assert helper.VALUE == 'trusted'\n"
            "assert manifest.is_file() and template.is_file()\n"
            "marker = os.environ.get('TEMPLATE_TOOL_TEST_VALIDATOR_MARKER')\n"
            "if not marker and os.environ.get('HOME', '').endswith('.full-validator-marker'):\n"
            "    marker = os.environ['HOME']\n"
            "if marker:\n"
            "    Path(marker).write_text('FULL_VALIDATOR_STARTED', encoding='utf-8')\n"
            "version = str(yaml.safe_load(manifest.read_text(encoding='utf-8'))['template']['version'])\n"
            "if not version.startswith('1.1.'):\n"
            "    raise SystemExit(f'fixture validator does not support {version}')\n"
            "print('fixture trusted validator passed')\n",
            encoding="utf-8",
        )
        (root / ".gitignore").write_text("/dist/\n/installed/\n/release-workspace/\n", encoding="utf-8")
        repo_tests = root / "tests"
        repo_tests.mkdir()
        (repo_tests / "validate_template_packages.py").write_text(
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "packages = list(root.glob('fixture-skill/assets/templates/demo-template/v*/manifest.yaml'))\n"
            "if not packages:\n"
            "    raise SystemExit('fixture canonical package is missing')\n"
            "print(f'validated {len(packages)} fixture packages')\n",
            encoding="utf-8",
        )
        packages: dict[str, Path] = {}
        for version in versions:
            package = template_root / f"v{version}"
            package.mkdir()
            template = package / "template.txt"
            template.write_text(f"fixture template {version}\n", encoding="utf-8")
            template.write_bytes(template.read_bytes().replace(b"\r\n", b"\n"))
            digest = sha256(template)
            manifest = {
                "template": {
                    "id": "demo-template",
                    "name": "Fixture template",
                    "version": version,
                    "format": "txt",
                    "file": "template.txt",
                },
                "generator": {"version": "1.0.0", "supported_major": 1},
                "schema": "schemas/demo.schema.json",
                "fingerprint": {"algorithm": "sha256", "sha256": digest, "value": digest},
            }
            (package / "manifest.yaml").write_text(
                yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            (package / "CHANGELOG.md").write_text(f"# {version}\n", encoding="utf-8")
            (package / "README.md").write_text(f"fixture README {version}\n", encoding="utf-8")
            (package / "binary.dat").write_bytes(b"\x00\x01\x02\x03\x04")
            packages[version] = package
        for path in template_root.rglob("*"):
            if path.is_file():
                path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        self.git(root, "init", "-q", "-b", "master")
        self.git(root, "config", "user.name", "Template Release Tests")
        self.git(root, "config", "user.email", "template-release-tests@example.invalid")
        self.git(root, "add", "--", ".")
        self.git(root, "commit", "-qm", "fixture")
        remote = root.parent / f"{root.name}-origin.git"
        self.git(root.parent, "init", "--bare", "-q", remote)
        origin_url = "https://github.com/ArdenZC/codex-work-skills.git"
        self.git(root, "remote", "add", "origin", origin_url)
        self.git(root, "config", f"url.{remote.as_uri()}.insteadOf", origin_url)
        self.git(root, "push", "-q", "origin", "master")
        return skill, packages

    def make_external_package(self, source: Path, root: Path, version: str) -> Path:
        destination = root / "release-workspace" / "demo-template" / f"v{version}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        template = destination / "template.txt"
        template.write_text(f"fixture external template {version}\n", encoding="utf-8")
        manifest_path = destination / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["template"]["version"] = version
        digest = sha256(template)
        manifest["fingerprint"]["sha256"] = digest
        manifest["fingerprint"]["value"] = digest
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return destination

    def create_release(self, root: Path, package: Path, output_name: str) -> Path:
        output = root / "dist" / "template-packages" / output_name
        result = self.run_tool(
            "release",
            "--package",
            package,
            "--output-dir",
            output,
            "--json",
            root=root,
        )
        payload = self.assert_succeeded(result)
        self.assertEqual(payload["status"], "passed")
        plan = output / f"demo-template-{package.name.removeprefix('v')}.release-plan.json"
        self.assertTrue(plan.is_file())
        return output

    def create_archive(self, root: Path, package: Path, output_name: str) -> Path:
        output = root / "dist" / "template-packages" / output_name
        result = self.run_tool(
            "archive",
            "--package",
            package,
            "--output-dir",
            output,
            "--json",
            root=root,
        )
        payload = self.assert_succeeded(result)
        self.assertFalse(payload["dry_run"])
        self.assertTrue((output / f"demo-template-{package.name.removeprefix('v')}.zip").is_file())
        return output

    def test_release_preserves_lexical_repo_root_for_aliased_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-root-alias-") as directory:
            container = Path(directory)
            real_root = container / "real-repository"
            real_root.mkdir()
            _, packages = self.make_fixture_repo(real_root, versions=("1.1.1",))
            alias = container / "repository-alias"
            try:
                alias.symlink_to(real_root, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("the current platform cannot create directory symlinks")

            package = alias / packages["1.1.1"].relative_to(real_root)
            output = alias / "dist" / "template-packages" / "aliased-root"
            result = self.run_tool(
                "release",
                "--package",
                package,
                "--output-dir",
                output,
                "--json",
                root=alias,
            )
            payload = self.assert_succeeded(result)
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(len(list(output.glob("*.zip"))), 1)

    def copy_bundle(self, source: Path, destination: Path) -> Path:
        destination.mkdir(parents=True)
        for path in source.iterdir():
            if path.is_file():
                shutil.copy2(path, destination / path.name)
        archive = next(destination.glob("*.zip"))
        return archive

    def test_real_current_lesson_and_gradebook_release_verify_install_list(self) -> None:
        output_dirs: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="template-release-real-install-") as directory:
            install_root = Path(directory) / "installed"
            try:
                targets = [
                    (
                        ROOT / "教案生成器/lesson-plan-docx-generator/assets/templates/lesson-plan/v1.1.0",
                        "real-lesson",
                        "E91FAE69BA85B9E8B22B11F20A80BCA8E1659C007D33695E00B30D16822D4047",
                    ),
                    (
                        ROOT / "平时成绩记分册生成器/course-gradebook-generator/assets/templates/course-gradebook/v1.1.0",
                        "real-gradebook",
                        "541BF82DB114070708A1E86ADA7F2ACC8B9B4C5478F05B845B32665CE8C68110",
                    ),
                ]
                for package, name, expected_sha in targets:
                    output = ROOT / "dist" / "template-packages" / "release-test" / name
                    output_dirs.append(output)
                    release = self.run_tool(
                        "release",
                        "--package",
                        package,
                        "--output-dir",
                        output,
                        "--json",
                    )
                    payload = self.assert_succeeded(release)
                    self.assertEqual(payload["archive_sha256"], expected_sha)
                    verified = self.assert_succeeded(
                        self.run_tool("verify-release", "--release-dir", output, "--json")
                    )
                    self.assertEqual(verified["status"], "passed")
                    installed = self.assert_succeeded(
                        self.run_tool(
                            "install",
                            "--release-dir",
                            output,
                            "--install-root",
                            install_root,
                            "--json",
                        )
                    )
                    self.assertEqual(installed["version"], "1.1.0")
                listed = self.assert_succeeded(
                    self.run_tool(
                        "list-installed",
                        "--install-root",
                        install_root,
                        "--verify",
                        "--json",
                    )
                )
                self.assertEqual({item["template_id"] for item in listed["templates"]}, {"lesson-plan", "course-gradebook"})
                self.assertTrue(all(item["verified"] for item in listed["templates"]))
            finally:
                for output in reversed(output_dirs):
                    if output.exists():
                        shutil.rmtree(output)

    def test_fixture_release_install_upgrade_rollback_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-fixture-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            first = self.create_release(root, packages["1.1.1"], "fixture-111")
            second = self.create_release(root, packages["1.1.2"], "fixture-112")
            plan = json.loads((first / "demo-template-1.1.1.release-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["tag"], "template/demo-template/v1.1.1")
            self.assertEqual(plan["assets"], [
                "demo-template-1.1.1.zip",
                "demo-template-1.1.1.zip.sha256",
                "demo-template-1.1.1.metadata.json",
            ])
            self.assertEqual(plan["sha256"], "demo-template-1.1.1.zip.sha256")
            self.assertTrue(all(not Path(value).is_absolute() for value in plan["assets"] + [plan["plan"]]))
            self.assertEqual(plan["source_commit"], self.git(root, "rev-parse", "HEAD"))
            install_root = root / "installed" / "template-packages"
            installed = self.assert_succeeded(
                self.run_tool("install", "--release-dir", first, "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(installed["version"], "1.1.1")
            post_failure = self.run_tool(
                "upgrade",
                "--release-dir",
                second,
                "--install-root",
                install_root,
                "--json",
                root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_POST_INSTALL_VALIDATION": "1"},
            )
            self.assert_failed(post_failure, "post-install")
            self.assertFalse((install_root / "demo-template" / "versions" / "1.1.2").exists())
            installation_path = install_root / "demo-template" / "versions" / "1.1.1" / ".installation.json"
            installation = json.loads(installation_path.read_text(encoding="utf-8"))
            self.assertEqual(set(installation), {
                "schema_version", "template_id", "version", "archive_sha256", "entry_package", "files"
            })
            self.assertTrue(all(set(item) == {"path", "sha256"} for item in installation["files"]))
            active = json.loads((install_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(set(active), {
                "schema_version", "template_id", "active_version", "previous_version", "updated_by_tool_version"
            })
            state_failure = self.run_tool(
                "upgrade",
                "--release-dir",
                second,
                "--install-root",
                install_root,
                "--json",
                root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_ACTIVE_STATE": "1"},
            )
            self.assert_failed(state_failure, "active state")
            after_failure = self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(after_failure["templates"][0]["active_version"], "1.1.1")
            self.assertFalse((install_root / "demo-template" / "versions" / "1.1.2").exists())
            upgraded = self.assert_succeeded(
                self.run_tool("upgrade", "--release-dir", second, "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(upgraded["version"], "1.1.2")
            listing = self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", install_root, "--verify", "--json", root=root)
            )
            self.assertEqual(listing["templates"][0]["active_version"], "1.1.2")
            self.assertEqual({item["version"] for item in listing["templates"][0]["versions"]}, {"1.1.1", "1.1.2"})
            same_version = self.run_tool(
                "upgrade",
                "--release-dir",
                second,
                "--install-root",
                install_root,
                "--json",
                root=root,
            )
            self.assert_failed(same_version, "newer than the active version")
            downgrade = self.run_tool(
                "upgrade",
                "--release-dir",
                first,
                "--install-root",
                install_root,
                "--json",
                root=root,
            )
            self.assert_failed(downgrade, "newer than the active version")
            rollback_failure = self.run_tool(
                "rollback",
                "--template-id",
                "demo-template",
                "--to-version",
                "1.1.1",
                "--install-root",
                install_root,
                "--json",
                root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_ACTIVE_STATE": "1"},
            )
            self.assert_failed(rollback_failure, "rollback transaction")
            unchanged = self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(unchanged["templates"][0]["active_version"], "1.1.2")
            rolled = self.assert_succeeded(
                self.run_tool(
                    "rollback",
                    "--template-id",
                    "demo-template",
                    "--to-version",
                    "1.1.1",
                    "--install-root",
                    install_root,
                    "--json",
                    root=root,
                )
            )
            self.assertEqual(rolled["version"], "1.1.1")
            final_state = json.loads((install_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(final_state["active_version"], "1.1.1")
            self.assertEqual(final_state["previous_version"], "1.1.2")
            self.assertTrue((install_root / "demo-template" / "versions" / "1.1.2").is_dir())
            upward = self.run_tool(
                "rollback",
                "--template-id",
                "demo-template",
                "--to-version",
                "1.1.2",
                "--install-root",
                install_root,
                "--json",
                root=root,
            )
            self.assert_succeeded(upward)
            toggled_state = json.loads((install_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(toggled_state["active_version"], "1.1.2")
            self.assertEqual(toggled_state["previous_version"], "1.1.1")
            toggled_back = self.assert_succeeded(
                self.run_tool(
                    "rollback",
                    "--template-id",
                    "demo-template",
                    "--install-root",
                    install_root,
                    "--json",
                    root=root,
                )
            )
            self.assertEqual(toggled_back["version"], "1.1.1")

    def test_first_install_rejects_every_preexisting_versions_entry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-first-install-entries-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            first = self.create_release(root, packages["1.1.1"], "first-install-111")
            second = self.create_release(root, packages["1.1.2"], "first-install-112")

            cases = ("note", ".keep", "unknown-version", "version-link")
            for case in cases:
                with self.subTest(case=case):
                    install_root = root / "installed" / "template-packages" / case
                    template_dir = install_root / "demo-template"
                    versions_dir = template_dir / "versions"
                    versions_dir.mkdir(parents=True)
                    entry = versions_dir / case
                    if case in {"note", ".keep"}:
                        entry.write_text("preserve me\n", encoding="utf-8")
                    elif case == "unknown-version":
                        entry.mkdir()
                    else:
                        try:
                            entry.symlink_to(root / ".gitignore")
                        except OSError as exc:
                            self.skipTest(f"symlink creation unavailable: {exc}")

                    rejected = self.run_tool(
                        "install",
                        "--release-dir",
                        first,
                        "--install-root",
                        install_root,
                        "--json",
                        root=root,
                    )
                    self.assert_failed(rejected, "versions exist without an active installation")
                    self.assertTrue(entry.exists() or entry.is_symlink())
                    self.assertFalse((versions_dir / "1.1.1").exists())
                    self.assertFalse((template_dir / "active.json").exists())
                    self.assertFalse((template_dir / ".lock").exists())
                    self.assertEqual(
                        [item.name for item in versions_dir.iterdir()],
                        [case],
                    )

            empty_root = root / "installed" / "template-packages" / "empty"
            (empty_root / "demo-template" / "versions").mkdir(parents=True)
            installed = self.assert_succeeded(
                self.run_tool(
                    "install",
                    "--release-dir",
                    first,
                    "--install-root",
                    empty_root,
                    "--json",
                    root=root,
                )
            )
            self.assertEqual(installed["version"], "1.1.1")
            listed = self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", empty_root, "--json", root=root)
            )
            self.assertEqual(listed["templates"][0]["active_version"], "1.1.1")
            upgraded = self.assert_succeeded(
                self.run_tool(
                    "upgrade",
                    "--release-dir",
                    second,
                    "--install-root",
                    empty_root,
                    "--json",
                    root=root,
                )
            )
            self.assertEqual(upgraded["version"], "1.1.2")

    def test_fixture_scaffold_validate_promote_then_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-promote-") as directory:
            root = Path(directory)
            skill, packages = self.make_fixture_repo(root, versions=("1.1.0",))
            source = root / "work" / "template-packages" / "demo-template" / "1.1.1"
            scaffold = self.run_tool(
                "scaffold",
                "--base-package",
                packages["1.1.0"],
                "--version",
                "1.1.1",
                "--output-dir",
                source,
                "--json",
                root=root,
            )
            self.assert_succeeded(scaffold)
            validated = self.assert_succeeded(self.run_tool("validate", "--package", source, "--json", root=root))
            self.assertEqual(validated["status"], "passed")
            promoted = self.assert_succeeded(self.run_tool("promote", "--package", source, "--json", root=root))
            self.assertEqual(promoted["status"], "passed")
            canonical = skill / "assets" / "templates" / "demo-template" / "v1.1.1"
            self.assertTrue(canonical.is_dir())
            shutil.rmtree(root / "work")
            self.git(root, "add", "--", canonical.relative_to(root).as_posix())
            self.git(root, "commit", "-qm", "commit promoted canonical package")
            output = self.create_release(root, canonical, "promoted")
            verified = self.assert_succeeded(self.run_tool("verify-release", "--release-dir", output, "--json", root=root))
            self.assertEqual(verified["version"], "1.1.1")

    def test_provenance_requires_committed_canonical_source_and_head_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-provenance-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root, versions=("1.1.0", "1.1.1"))
            external = self.make_external_package(packages["1.1.1"], root, "1.1.9")
            external_output = root / "dist" / "template-packages" / "external-release"
            external_release = self.run_tool(
                "release",
                "--package",
                external,
                "--output-dir",
                external_output,
                "--json",
                root=root,
            )
            self.assert_failed(external_release, "canonical repository package")
            self.assertFalse(external_output.exists())

            first = self.create_release(root, packages["1.1.1"], "clean-first")
            second = self.create_release(root, packages["1.1.1"], "clean-second")
            first_archive = next(first.glob("*.zip"))
            second_archive = next(second.glob("*.zip"))
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            first_plan = json.loads(next(first.glob("*.release-plan.json")).read_text(encoding="utf-8"))
            self.assertEqual(first_plan["source_commit"], self.git(root, "rev-parse", "HEAD"))

            for source_name in ("manifest.yaml", "README.md", "CHANGELOG.md"):
                source = packages["1.1.1"] / source_name
                original = source.read_bytes()
                source.write_bytes(original.replace(b"\n", b"\r\n"))
                output = root / "dist" / "template-packages" / f"crlf-{source_name.replace('.', '-')}"
                try:
                    crlf_failure = self.run_tool(
                        "release",
                        "--package",
                        packages["1.1.1"],
                        "--output-dir",
                        output,
                        "--json",
                        root=root,
                    )
                    self.assert_failed(crlf_failure, "byte-for-byte")
                    for name in (
                        "demo-template-1.1.1.zip",
                        "demo-template-1.1.1.zip.sha256",
                        "demo-template-1.1.1.metadata.json",
                        "demo-template-1.1.1.release-plan.json",
                    ):
                        self.assertFalse((output / name).exists())
                finally:
                    source.write_bytes(original)

            binary = packages["1.1.1"] / "binary.dat"
            original_binary = binary.read_bytes()
            binary.write_bytes(original_binary[:1] + b"\xff" + original_binary[2:])
            binary_failure = self.run_tool(
                "release",
                "--package",
                packages["1.1.1"],
                "--output-dir",
                root / "dist" / "template-packages" / "binary-modified",
                "--json",
                root=root,
            )
            self.assert_failed(binary_failure, "clean worktree")
            binary.write_bytes(original_binary)

            template = packages["1.1.1"] / "template.txt"
            original_template = template.read_bytes()
            template.write_bytes(original_template + b"unstaged mutation\n")
            unstaged = self.run_tool(
                "release",
                "--package",
                packages["1.1.1"],
                "--output-dir",
                root / "dist" / "template-packages" / "unstaged",
                "--json",
                root=root,
            )
            self.assert_failed(unstaged, "clean worktree")
            template.write_bytes(original_template)

            template.write_bytes(original_template + b"staged mutation\n")
            self.git(root, "add", "--", template.relative_to(root).as_posix())
            staged = self.run_tool(
                "release",
                "--package",
                packages["1.1.1"],
                "--output-dir",
                root / "dist" / "template-packages" / "staged",
                "--json",
                root=root,
            )
            self.assert_failed(staged, "clean worktree")
            self.git(root, "restore", "--staged", "--", template.relative_to(root).as_posix())
            template.write_bytes(original_template)

            manifest_path = packages["1.1.1"] / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["template"]["base_manifest"] = "../v1.1.0/manifest.yaml"
            manifest["template"]["base_template"] = "../v1.1.0/template.txt"
            manifest_path.write_bytes(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode("utf-8"))
            self.git(root, "add", "--", manifest_path.relative_to(root).as_posix())
            self.git(root, "commit", "-qm", "add fixture dependency closure")
            dependency_template = packages["1.1.0"] / "template.txt"
            original_dependency = dependency_template.read_bytes()
            dependency_template.write_bytes(original_dependency + b"dependency mutation\n")
            dependency_failure = self.run_tool(
                "release",
                "--package",
                packages["1.1.1"],
                "--output-dir",
                root / "dist" / "template-packages" / "dependency-modified",
                "--json",
                root=root,
            )
            self.assert_failed(dependency_failure, "clean worktree")
            dependency_template.write_bytes(original_dependency)

            untracked = packages["1.1.1"] / "notes-secret.txt"
            untracked.write_bytes(b"must not enter a release\n")
            untracked_failure = self.run_tool(
                "release",
                "--package",
                packages["1.1.1"],
                "--output-dir",
                root / "dist" / "template-packages" / "untracked-file",
                "--json",
                root=root,
            )
            self.assert_failed(untracked_failure, "clean worktree")
            untracked.unlink()

    def test_provenance_release_source_snapshot_closes_archive_toc_tou(self) -> None:
        from unittest.mock import patch

        from tools.template_tooling import release as release_module

        with tempfile.TemporaryDirectory(prefix="template-release-source-snapshot-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root, versions=("1.1.1",))
            source = packages["1.1.1"] / "CHANGELOG.md"
            original = source.read_bytes()
            output = root / "dist" / "template-packages" / "toc-tou-before"
            original_archive = release_module.archive_package

            def mutate_before_archive(*args: Any, **kwargs: Any) -> dict[str, Any]:
                source.write_bytes(original + b"TOCTOU before archive\n")
                return original_archive(*args, **kwargs)

            try:
                with patch.object(release_module, "archive_package", side_effect=mutate_before_archive):
                    with self.assertRaisesRegex(Exception, "byte-for-byte"):
                        release_module.release_package(root, package=packages["1.1.1"], output_dir=output)
            finally:
                source.write_bytes(original)
            for name in (
                "demo-template-1.1.1.zip",
                "demo-template-1.1.1.zip.sha256",
                "demo-template-1.1.1.metadata.json",
                "demo-template-1.1.1.release-plan.json",
            ):
                self.assertFalse((output / name).exists())

            after_output = root / "dist" / "template-packages" / "toc-tou-after"

            def mutate_after_archive(*args: Any, **kwargs: Any) -> dict[str, Any]:
                result = original_archive(*args, **kwargs)
                source.write_bytes(original + b"TOCTOU after archive\n")
                return result

            try:
                with patch.object(release_module, "archive_package", side_effect=mutate_after_archive):
                    passed = release_module.release_package(
                        root,
                        package=packages["1.1.1"],
                        output_dir=after_output,
                    )
                self.assertEqual(passed["status"], "passed")
                with zipfile.ZipFile(after_output / "demo-template-1.1.1.zip") as archive:
                    self.assertEqual(archive.read("demo-template/v1.1.1/CHANGELOG.md"), original)
            finally:
                source.write_bytes(original)

    def test_install_upgrade_and_rollback_lock_release_failure_restore_filesystem(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-lock-release-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            first = self.create_release(root, packages["1.1.1"], "first")
            second = self.create_release(root, packages["1.1.2"], "second")

            first_root = root / "installed" / "template-packages" / "first"
            failed_install = self.run_tool(
                "install", "--release-dir", first, "--install-root", first_root, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_LOCK_RELEASE": "1"},
            )
            self.assert_failed(failed_install, "lock release")
            self.assertFalse((first_root / "demo-template" / "active.json").exists())
            self.assertFalse((first_root / "demo-template" / "versions" / "1.1.1").exists())
            self.assertFalse((first_root / "demo-template" / ".lock").exists())

            upgrade_root = root / "installed" / "template-packages" / "upgrade"
            self.assert_succeeded(self.run_tool("install", "--release-dir", first, "--install-root", upgrade_root, "--json", root=root))
            failed_upgrade = self.run_tool(
                "upgrade", "--release-dir", second, "--install-root", upgrade_root, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_LOCK_RELEASE": "1"},
            )
            self.assert_failed(failed_upgrade, "lock release")
            upgrade_state = json.loads((upgrade_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(upgrade_state["active_version"], "1.1.1")
            self.assertFalse((upgrade_root / "demo-template" / "versions" / "1.1.2").exists())
            self.assertFalse((upgrade_root / "demo-template" / ".lock").exists())

            rollback_root = root / "installed" / "template-packages" / "rollback"
            self.assert_succeeded(self.run_tool("install", "--release-dir", first, "--install-root", rollback_root, "--json", root=root))
            self.assert_succeeded(self.run_tool("upgrade", "--release-dir", second, "--install-root", rollback_root, "--json", root=root))
            failed_rollback = self.run_tool(
                "rollback", "--template-id", "demo-template", "--install-root", rollback_root, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_LOCK_RELEASE": "1"},
            )
            self.assert_failed(failed_rollback, "lock release")
            rollback_state = json.loads((rollback_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(rollback_state["active_version"], "1.1.2")
            self.assertEqual(rollback_state["previous_version"], "1.1.1")
            self.assertFalse((rollback_root / "demo-template" / ".lock").exists())
            self.assertEqual(list((rollback_root / "demo-template" / "versions").glob(".*.stage")), [])

    def test_release_owner_is_skill_scoped_for_external_versions_and_unsupported_minor_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-owner-compat-") as directory:
            root = Path(directory)
            skill, packages = self.make_fixture_repo(root, versions=("1.1.0",))
            external_111 = self.make_external_package(packages["1.1.0"], root, "1.1.1")
            external_112 = self.make_external_package(packages["1.1.0"], root, "1.1.2")
            external_119 = self.make_external_package(packages["1.1.0"], root, "1.1.9")
            canonical_release = self.create_release(root, packages["1.1.0"], "canonical")
            release_111 = self.create_archive(root, external_111, "external-111")
            release_112 = self.create_archive(root, external_112, "external-112")
            release_119 = self.create_archive(root, external_119, "external-119")
            self.assertEqual(
                self.assert_succeeded(self.run_tool("verify-release", "--release-dir", release_119, "--json", root=root))["version"],
                "1.1.9",
            )

            metadata = json.loads(next(release_111.glob("*.metadata.json")).read_text(encoding="utf-8"))
            canonical_metadata = json.loads(next(canonical_release.glob("*.metadata.json")).read_text(encoding="utf-8"))
            self.assertNotEqual(metadata["template_sha256"], canonical_metadata["template_sha256"])
            self.assertEqual(metadata["template_sha256"], next(
                record["template_sha256"]
                for record in metadata["packages"]
                if record["manifest"].rsplit("/", 1)[0] == metadata["entry_package"]
            ))

            install_root = root / "installed" / "template-packages"
            self.assert_succeeded(self.run_tool("install", "--release-dir", canonical_release, "--install-root", install_root, "--json", root=root))
            self.assert_succeeded(self.run_tool("upgrade", "--release-dir", release_111, "--install-root", install_root, "--json", root=root))
            self.assert_succeeded(self.run_tool("upgrade", "--release-dir", release_112, "--install-root", install_root, "--json", root=root))

            first_rollback = self.assert_succeeded(
                self.run_tool("rollback", "--template-id", "demo-template", "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(first_rollback["version"], "1.1.1")
            second_rollback = self.assert_succeeded(
                self.run_tool("rollback", "--template-id", "demo-template", "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(second_rollback["version"], "1.1.2")
            explicit = self.assert_succeeded(
                self.run_tool(
                    "rollback", "--template-id", "demo-template", "--to-version", "1.1.0",
                    "--install-root", install_root, "--json", root=root,
                )
            )
            self.assertEqual(explicit["version"], "1.1.0")
            final = json.loads((install_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(final["active_version"], "1.1.0")
            self.assertEqual(final["previous_version"], "1.1.2")
            listed = self.assert_succeeded(self.run_tool("list-installed", "--install-root", install_root, "--verify", "--json", root=root))
            self.assertEqual({item["version"] for item in listed["templates"][0]["versions"]}, {"1.1.0", "1.1.1", "1.1.2"})
            self.assertEqual(sorted(path.name for path in (skill / "assets" / "templates" / "demo-template").iterdir()), ["v1.1.0"])

            unsupported = self.make_external_package(packages["1.1.0"], root, "1.2.0")
            failed = self.run_tool("archive", "--package", unsupported, "--output-dir", root / "dist" / "template-packages" / "unsupported", "--json", root=root)
            self.assert_failed(failed, "full template validation failed")

    def test_release_entry_template_sha_is_self_owned_and_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-entry-sha-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root, versions=("1.1.0",))
            external = self.make_external_package(packages["1.1.0"], root, "1.1.1")
            source = self.create_archive(root, external, "source")
            tampered = root / "dist" / "template-packages" / "tampered"
            shutil.copytree(source, tampered)
            archive = next(tampered.glob("*.zip"))
            metadata_path = next(tampered.glob("*.metadata.json"))
            sidecar = next(tampered.glob("*.zip.sha256"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            entries: list[tuple[str, bytes]] = []
            with zipfile.ZipFile(archive, "r") as original:
                for info in original.infolist():
                    content = original.read(info)
                    if info.filename == metadata["entry_package"] + "/template.txt":
                        content = b"changed release template\n"
                    entries.append((info.filename, content))
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as rebuilt:
                for name, content in entries:
                    info = zipfile.ZipInfo(name)
                    info.date_time = (1980, 1, 1, 0, 0, 0)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    info.flag_bits = 0x800
                    rebuilt.writestr(info, content)
            entry_template_path = metadata["entry_package"] + "/template.txt"
            entry_content = b"changed release template\n"
            new_template_sha = hashlib.sha256(entry_content).hexdigest().upper()
            for record in metadata["files"]:
                if record["path"] == entry_template_path:
                    record["sha256"] = new_template_sha
                    record["size"] = len(entry_content)
            metadata["archive_sha256"] = sha256(archive)
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            sidecar.write_text(f"{metadata['archive_sha256']}  {archive.name}\n", encoding="ascii")
            failed = self.run_tool("verify-release", "--release-dir", tampered, "--json", root=root)
            self.assert_failed(failed, "fingerprint mismatch")

    def test_rollback_default_dry_run_and_corrupt_target_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-rollback-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            first = self.create_release(root, packages["1.1.1"], "first")
            second = self.create_release(root, packages["1.1.2"], "second")
            install_root = root / "installed" / "template-packages"
            self.assert_succeeded(self.run_tool("install", "--release-dir", first, "--install-root", install_root, "--json", root=root))
            self.assert_succeeded(self.run_tool("upgrade", "--release-dir", second, "--install-root", install_root, "--json", root=root))

            planned = self.assert_succeeded(
                self.run_tool("rollback", "--template-id", "demo-template", "--install-root", install_root, "--dry-run", "--json", root=root)
            )
            self.assertEqual(planned["status"], "planned")
            state = json.loads((install_root / "demo-template" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_version"], "1.1.2")

            rolled = self.assert_succeeded(
                self.run_tool("rollback", "--template-id", "demo-template", "--install-root", install_root, "--json", root=root)
            )
            self.assertEqual(rolled["version"], "1.1.1")

            missing_root = root / "installed" / "template-packages" / "missing-target"
            self.assert_succeeded(self.run_tool("install", "--release-dir", first, "--install-root", missing_root, "--json", root=root))
            self.assert_succeeded(self.run_tool("upgrade", "--release-dir", second, "--install-root", missing_root, "--json", root=root))
            missing_version = missing_root / "demo-template" / "versions" / "1.1.1"
            shutil.rmtree(missing_version)
            missing = self.run_tool("rollback", "--template-id", "demo-template", "--install-root", missing_root, "--json", root=root)
            self.assert_failed(missing, "not installed")

            corrupt_root = root / "installed" / "template-packages" / "corrupt-target"
            self.assert_succeeded(self.run_tool("install", "--release-dir", first, "--install-root", corrupt_root, "--json", root=root))
            self.assert_succeeded(self.run_tool("upgrade", "--release-dir", second, "--install-root", corrupt_root, "--json", root=root))
            corrupt_file = corrupt_root / "demo-template" / "versions" / "1.1.1" / "bundle" / "demo-template" / "v1.1.1" / "template.txt"
            corrupt_file.write_text("corrupt\n", encoding="utf-8")
            corrupted = self.run_tool("rollback", "--template-id", "demo-template", "--install-root", corrupt_root, "--json", root=root)
            self.assert_failed(corrupted, "inventory")

    def test_list_installed_default_checks_inventory_without_full_validator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-inventory-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root, versions=("1.1.1",))
            release = self.create_release(root, packages["1.1.1"], "inventory")
            install_root = root / "installed" / "template-packages"
            self.assert_succeeded(self.run_tool("install", "--release-dir", release, "--install-root", install_root, "--json", root=root))
            version_dir = install_root / "demo-template" / "versions" / "1.1.1"
            template = version_dir / "bundle" / "demo-template" / "v1.1.1" / "template.txt"
            original = template.read_bytes()
            marker = root / "FULL_VALIDATOR_STARTED.full-validator-marker"
            marker_env = {
                "TEMPLATE_TOOL_TEST_VALIDATOR_ENV_JSON": json.dumps(
                    {"HOME": str(marker)}
                )
            }

            normal = self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", install_root, "--json", root=root, env=marker_env)
            )
            self.assertEqual(normal["integrity"], "passed")
            self.assertEqual(normal["templates"][0]["integrity"], "passed")
            self.assertEqual(normal["templates"][0]["versions"][0]["integrity"], "passed")
            self.assertFalse(marker.exists())

            template.write_bytes(original + b"tampered\n")
            modified = self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
            self.assert_failed(modified, "inventory")
            template.write_bytes(original)

            template.unlink()
            missing = self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
            self.assert_failed(missing, "inventory")
            template.write_bytes(original)

            extra = template.with_name("unexpected.txt")
            extra.write_text("extra\n", encoding="utf-8")
            added = self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
            self.assert_failed(added, "inventory")
            extra.unlink()

            link = template.with_name("link.txt")
            try:
                link.symlink_to(template)
            except OSError:
                pass
            else:
                symlinked = self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
                self.assert_failed(symlinked, "symlink")
                link.unlink()

            self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", install_root, "--json", root=root, env=marker_env)
            )
            self.assertFalse(marker.exists())
            verified = self.assert_succeeded(
                self.run_tool("list-installed", "--install-root", install_root, "--verify", "--json", root=root, env=marker_env)
            )
            self.assertTrue(verified["templates"][0]["verified"])
            self.assertTrue(marker.exists())

    def test_list_installed_empty_and_corrupt_inventory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-list-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            empty_root = root / "installed" / "template-packages"
            empty = self.assert_succeeded(self.run_tool("list-installed", "--install-root", empty_root, "--json", root=root))
            self.assertEqual(empty["count"], 0)
            source = self.create_release(root, packages["1.1.1"], "source")
            self.assert_succeeded(self.run_tool("install", "--release-dir", source, "--install-root", empty_root, "--json", root=root))
            inventory_path = empty_root / "demo-template" / "versions" / "1.1.1" / ".installation.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["unexpected"] = True
            inventory_path.write_text(json.dumps(inventory) + "\n", encoding="utf-8")
            failed = self.run_tool("list-installed", "--install-root", empty_root, "--json", root=root)
            self.assert_failed(failed, "inventory")

    def test_installation_state_schema_allows_valid_tool_versions_but_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-state-compat-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            install_root = root / "installed" / "template-packages"
            self.assert_succeeded(self.run_tool("install", "--release-dir", source, "--install-root", install_root, "--json", root=root))
            active_path = install_root / "demo-template" / "active.json"
            state = json.loads(active_path.read_text(encoding="utf-8"))
            for tool_version in ("0.1.9", "0.3.0"):
                state["updated_by_tool_version"] = tool_version
                active_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
                self.assert_succeeded(self.run_tool("list-installed", "--install-root", install_root, "--json", root=root))
            for invalid in ("v0.2", "０.２.０", "foo"):
                state["updated_by_tool_version"] = invalid
                active_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
                failed = self.run_tool("list-installed", "--install-root", install_root, "--json", root=root)
                self.assert_failed(failed, "updated_by_tool_version")
            state["updated_by_tool_version"] = "0.2.0"
            active_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

    def test_release_dry_run_plan_and_existing_output_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-dry-run-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = root / "dist" / "template-packages" / "dry-run"
            planned = self.assert_succeeded(
                self.run_tool(
                    "release",
                    "--package",
                    packages["1.1.1"],
                    "--output-dir",
                    output,
                    "--dry-run",
                    "--json",
                    root=root,
                )
            )
            self.assertEqual(planned["status"], "planned")
            self.assertFalse(output.exists())
            self.create_release(root, packages["1.1.1"], "real")
            duplicate = self.run_tool(
                "release",
                "--package",
                packages["1.1.1"],
                "--output-dir",
                root / "dist" / "template-packages" / "real",
                "--json",
                root=root,
            )
            self.assert_failed(duplicate, "already exists")

    def test_release_cleanup_failure_reports_original_and_cleanup_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-cleanup-error-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = root / "dist" / "template-packages" / "cleanup-failure"
            sidecar_name = "demo-template-1.1.1.zip.sha256"
            failed = self.run_tool(
                "release", "--package", packages["1.1.1"], "--output-dir", output, "--json", root=root,
                env={
                    "TEMPLATE_TOOL_TEST_FAIL_RELEASE_VERIFY": "1",
                    "TEMPLATE_TOOL_TEST_FAIL_RELEASE_CLEANUP": sidecar_name,
                },
            )
            self.assert_failed(failed, "injected release verification failure", "failed to remove")
            self.assertTrue((output / sidecar_name).is_file())
            self.assertFalse((output / "demo-template-1.1.1.zip").exists())
            self.assertFalse((output / "demo-template-1.1.1.metadata.json").exists())

    def test_release_output_symlink_escape_is_rejected(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory(prefix="template-release-output-path-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            external = root.parent / f"template-release-output-external-{root.name}"
            external.mkdir()
            try:
                output_parent = root / "dist" / "template-packages"
                output_parent.mkdir(parents=True)
                link = output_parent / "escape"
                link.symlink_to(external, target_is_directory=True)
                failed = self.run_tool(
                    "release",
                    "--package",
                    packages["1.1.1"],
                    "--output-dir",
                    link,
                    "--json",
                    root=root,
                )
                self.assert_failed(failed, "symlink")
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            finally:
                if external.exists():
                    shutil.rmtree(external)

    def test_release_verification_rejects_sidecar_metadata_zip_and_contract_faults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-faults-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            for label in ("sidecar", "metadata", "zip", "extra-key", "unsupported-contract", "missing-asset", "missing-zip", "extra-zip"):
                target = root / "external" / label
                archive = self.copy_bundle(source, target)
                sidecar = archive.with_name(archive.name + ".sha256")
                metadata_path = archive.with_name(archive.stem + ".metadata.json")
                if label == "sidecar":
                    sidecar.write_text("0" * 64 + "  " + archive.name + "\n", encoding="ascii")
                elif label == "metadata":
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    metadata["archive_sha256"] = "0" * 64
                    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
                elif label == "zip":
                    archive.write_bytes(b"not a zip")
                elif label == "missing-asset":
                    sidecar.unlink()
                elif label == "missing-zip":
                    archive.unlink()
                elif label == "extra-zip":
                    with zipfile.ZipFile(archive, "a") as bundle:
                        bundle.writestr("extra.txt", b"unexpected")
                elif label == "unsupported-contract":
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    metadata["tool_version"] = "9.9.9"
                    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
                else:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    metadata["unexpected"] = True
                    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
                failed = self.run_tool("verify-release", "--archive", archive, "--json", root=root)
                self.assert_failed(failed, "regular file" if label in {"missing-asset", "missing-zip"} else "archive")

    def test_release_verification_rejects_symlinked_bundle_files(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory(prefix="template-release-bundle-links-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            source_files = {path.name: path for path in source.iterdir() if path.is_file()}
            names = (
                "demo-template-1.1.1.zip",
                "demo-template-1.1.1.zip.sha256",
                "demo-template-1.1.1.metadata.json",
            )
            try:
                for linked_name in names:
                    link_dir = root / "external" / linked_name.replace(".", "-")
                    link_dir.mkdir(parents=True)
                    for name, source_path in source_files.items():
                        shutil.copy2(source_path, link_dir / name)
                    linked_path = link_dir / linked_name
                    linked_path.unlink()
                    linked_path.symlink_to(source_files[linked_name])
                    archive_path = linked_path if linked_name.endswith(".zip") else link_dir / names[0]
                    failed = self.run_tool(
                        "verify-release",
                        "--archive",
                        archive_path,
                        "--sha256-file",
                        link_dir / names[1],
                        "--metadata",
                        link_dir / names[2],
                        "--json",
                        root=root,
                    )
                    self.assert_failed(failed, "regular file")
                    shutil.rmtree(link_dir)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

    def test_release_verification_rejects_zip_slip_entry_mismatched_identity_and_missing_dependency(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-structure-faults-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            original_archive = next(source.glob("*.zip"))

            zip_slip = root / "external" / "zip-slip"
            archive = self.copy_bundle(source, zip_slip)
            with zipfile.ZipFile(archive, "r") as old, zipfile.ZipFile(archive.with_suffix(".new"), "w") as new:
                for info in old.infolist():
                    new.writestr(info, old.read(info))
                new.writestr("../escape.txt", b"escape")
            archive.with_suffix(".new").replace(archive)
            archive_digest = sha256(archive)
            zip_slip_meta_path = archive.with_name(archive.stem + ".metadata.json")
            zip_slip_meta = json.loads(zip_slip_meta_path.read_text(encoding="utf-8"))
            zip_slip_meta["archive_sha256"] = archive_digest
            zip_slip_meta_path.write_text(json.dumps(zip_slip_meta) + "\n", encoding="utf-8")
            archive.with_name(archive.name + ".sha256").write_text(
                f"{archive_digest}  {archive.name}\n", encoding="ascii"
            )
            failed = self.run_tool("verify-release", "--archive", archive, "--json", root=root)
            self.assert_failed(failed, "zip")

            mismatch = root / "external" / "entry-mismatch"
            mismatch_archive = self.copy_bundle(source, mismatch)
            mismatch_meta_path = mismatch_archive.with_name(mismatch_archive.stem + ".metadata.json")
            mismatch_meta = json.loads(mismatch_meta_path.read_text(encoding="utf-8"))
            mismatch_meta["entry_package"] = "demo-template/v9.9.9"
            mismatch_meta_path.write_text(json.dumps(mismatch_meta) + "\n", encoding="utf-8")
            failed = self.run_tool("verify-release", "--archive", mismatch_archive, "--json", root=root)
            self.assert_failed(failed, "entry_package")

            nfc = root / "external" / "nfc"
            nfc_archive = self.copy_bundle(source, nfc)
            nfc_meta_path = nfc_archive.with_name(nfc_archive.stem + ".metadata.json")
            nfc_meta = json.loads(nfc_meta_path.read_text(encoding="utf-8"))
            nfc_meta["files"][0]["path"] = "demo-template/v1.1.1/e\u0301.txt"
            nfc_meta_path.write_text(json.dumps(nfc_meta) + "\n", encoding="utf-8")
            failed = self.run_tool("verify-release", "--archive", nfc_archive, "--json", root=root)
            self.assert_failed(failed, "NFC")

            casefold = root / "external" / "casefold"
            casefold_archive = self.copy_bundle(source, casefold)
            casefold_meta_path = casefold_archive.with_name(casefold_archive.stem + ".metadata.json")
            casefold_meta = json.loads(casefold_meta_path.read_text(encoding="utf-8"))
            duplicate = dict(casefold_meta["files"][0])
            duplicate["path"] = duplicate["path"].swapcase()
            casefold_meta["files"] = sorted(casefold_meta["files"] + [duplicate], key=lambda item: (item["path"].casefold(), item["path"]))
            casefold_meta_path.write_text(json.dumps(casefold_meta) + "\n", encoding="utf-8")
            failed = self.run_tool("verify-release", "--archive", casefold_archive, "--json", root=root)
            self.assert_failed(failed, "collision")

            missing = root / "external" / "missing-dependency"
            missing_archive = self.copy_bundle(source, missing)
            missing_meta_path = missing_archive.with_name(missing_archive.stem + ".metadata.json")
            missing_meta = json.loads(missing_meta_path.read_text(encoding="utf-8"))
            entry_manifest = str(missing_meta["entry_package"]) + "/manifest.yaml"
            with zipfile.ZipFile(missing_archive, "r") as old:
                entries = {info.filename: old.read(info) for info in old.infolist()}
            manifest = yaml.safe_load(entries[entry_manifest].decode("utf-8"))
            manifest["template"]["base_manifest"] = "../missing/manifest.yaml"
            manifest["template"]["base_template"] = "../missing/template.txt"
            entries[entry_manifest] = yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode("utf-8")
            temporary = missing_archive.with_suffix(".rewrite")
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as new:
                for name in sorted(entries, key=lambda item: (item.casefold(), item)):
                    info = zipfile.ZipInfo(name)
                    info.date_time = (1980, 1, 1, 0, 0, 0)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    new.writestr(info, entries[name])
            temporary.replace(missing_archive)
            records = []
            with zipfile.ZipFile(missing_archive, "r") as rewritten:
                for info in rewritten.infolist():
                    content = rewritten.read(info)
                    records.append({"path": info.filename, "sha256": hashlib.sha256(content).hexdigest().upper(), "size": len(content)})
            archive_digest = sha256(missing_archive)
            missing_meta["archive_sha256"] = archive_digest
            missing_meta["files"] = records
            missing_meta_path.write_text(json.dumps(missing_meta) + "\n", encoding="utf-8")
            missing_archive.with_name(missing_archive.name + ".sha256").write_text(
                f"{archive_digest}  {missing_archive.name}\n", encoding="ascii"
            )
            failed = self.run_tool("verify-release", "--archive", missing_archive, "--json", root=root)
            self.assert_failed(failed, "dependency")

    def test_release_zip_resource_limits_and_streaming_validation(self) -> None:
        from tools.template_tooling.archive import _validate_zip_resource_limits
        from tools.template_tooling.release import (
            MAX_COMPRESSION_RATIO,
            MAX_RELEASE_ENTRIES,
            MAX_RELEASE_ENTRY_SIZE,
            MAX_RELEASE_TOTAL_SIZE,
        )

        def info(name: str, size: int, compressed: int) -> zipfile.ZipInfo:
            value = zipfile.ZipInfo(name)
            value.file_size = size
            value.compress_size = compressed
            value.external_attr = 0o100644 << 16
            return value

        with self.assertRaisesRegex(Exception, "too many entries"):
            _validate_zip_resource_limits([info(str(index), 1, 1) for index in range(MAX_RELEASE_ENTRIES + 1)])
        with self.assertRaisesRegex(Exception, "too large"):
            _validate_zip_resource_limits([info("large", MAX_RELEASE_ENTRY_SIZE + 1, 1)])
        with self.assertRaisesRegex(Exception, "uncompressed size"):
            _validate_zip_resource_limits(
                [info(f"total-{index}", MAX_RELEASE_ENTRY_SIZE, MAX_RELEASE_ENTRY_SIZE) for index in range(5)]
            )
        with self.assertRaisesRegex(Exception, "compression ratio"):
            _validate_zip_resource_limits([info("ratio", MAX_COMPRESSION_RATIO + 1, 1)])

        with tempfile.TemporaryDirectory(prefix="template-release-streaming-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "streaming")
            verified = self.assert_succeeded(self.run_tool("verify-release", "--release-dir", source, "--json", root=root))
            self.assertTrue(verified["full_validation"])

    def test_install_duplicate_mutation_post_failure_lock_and_overlap_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-install-faults-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            install_root = root / "installed" / "template-packages"
            self.assert_succeeded(self.run_tool("install", "--release-dir", source, "--install-root", install_root, "--json", root=root))
            duplicate = self.run_tool("install", "--release-dir", source, "--install-root", install_root, "--json", root=root)
            self.assert_failed(duplicate, "already installed")

            installed_template = install_root / "demo-template" / "versions" / "1.1.1" / "bundle"
            (installed_template / "demo-template" / "v1.1.1" / "template.txt").write_text("tampered\n", encoding="utf-8")
            verify = self.run_tool("list-installed", "--install-root", install_root, "--verify", "--json", root=root)
            self.assert_failed(verify, "inventory")

            failed_root = Path(directory).parent / f"template-release-failed-{root.name}"
            failed = self.run_tool(
                "install",
                "--release-dir",
                source,
                "--install-root",
                failed_root,
                "--json",
                root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_POST_INSTALL_VALIDATION": "1"},
            )
            self.assert_failed(failed, "post-install")
            self.assertFalse((failed_root / "demo-template" / "versions" / "1.1.1").exists())
            self.assertFalse((failed_root / "demo-template").exists())

            lock_root = root / "installed" / "template-packages" / "lock-install"
            lock_path = lock_root / "demo-template" / ".lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("held\n", encoding="utf-8")
            locked = self.run_tool("install", "--release-dir", source, "--install-root", lock_root, "--json", root=root)
            self.assert_failed(locked, "lock")

            concurrent_root = root / "installed" / "template-packages" / "concurrent"
            command = [
                str(PYTHON), str(TOOL), "--repo-root", str(root),
                "install", "--release-dir", str(source), "--install-root", str(concurrent_root), "--json",
            ]
            process_env = os.environ.copy()
            process_env["TEMPLATE_TOOL_TEST_INSTALL_HOLD_SECONDS"] = "2"
            first_process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            lock_file = concurrent_root / "demo-template" / ".lock"
            for _ in range(100):
                if lock_file.exists():
                    break
                time.sleep(0.1)
            concurrent = self.run_tool(
                "install", "--release-dir", source, "--install-root", concurrent_root, "--json", root=root
            )
            self.assert_failed(concurrent, "lock")
            first_stdout, first_stderr = first_process.communicate(timeout=180)
            self.assertEqual(first_process.returncode, 0, first_stdout + first_stderr)

            overlap_root = root / "external" / "source"
            overlap = self.run_tool("install", "--release-dir", source, "--install-root", source, "--json", root=root)
            self.assert_failed(overlap, "install root")

            protected = self.run_tool(
                "install",
                "--release-dir",
                source,
                "--install-root",
                packages["1.1.1"],
                "--json",
                root=root,
            )
            self.assert_failed(protected, "install root")

    def test_install_symlink_quadrants_are_rejected_or_allowed_only_when_independent(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory(prefix="template-release-symlink-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            external = root.parent / f"template-release-independent-{root.name}"
            if external.exists():
                shutil.rmtree(external)
            external.mkdir()
            independent_link = root.parent / f"template-release-independent-link-{root.name}"
            try:
                if independent_link.exists() or independent_link.is_symlink():
                    independent_link.unlink()
                independent_link.symlink_to(external, target_is_directory=True)
                allowed = self.run_tool(
                    "install",
                    "--release-dir",
                    source,
                    "--install-root",
                    independent_link,
                    "--json",
                    root=root,
                )
                self.assert_succeeded(allowed)

                repo_link = root / "repo-link"
                repo_link.symlink_to(root, target_is_directory=True)
                rejected_repo = self.run_tool(
                    "install",
                    "--release-dir",
                    source,
                    "--install-root",
                    repo_link,
                    "--json",
                    root=root,
                )
                self.assert_failed(rejected_repo, "install root")

                external_to_repo = external / "repo-link"
                external_to_repo.symlink_to(root, target_is_directory=True)
                rejected_external = self.run_tool(
                    "install",
                    "--release-dir",
                    source,
                    "--install-root",
                    external_to_repo,
                    "--json",
                    root=root,
                )
                self.assert_failed(rejected_external, "repository")

                repo_allowed = root / "installed" / "template-packages"
                repo_allowed.mkdir(parents=True, exist_ok=True)
                repo_to_external = repo_allowed / "external-alias"
                repo_to_external.symlink_to(external, target_is_directory=True)
                rejected_repo_alias = self.run_tool(
                    "install",
                    "--release-dir",
                    source,
                    "--install-root",
                    repo_to_external,
                    "--json",
                    root=root,
                )
                self.assert_failed(rejected_repo_alias, "symlink")
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            finally:
                if independent_link.exists() or independent_link.is_symlink():
                    independent_link.unlink()
                if external.exists():
                    shutil.rmtree(external)

    @unittest.skipUnless(os.name == "nt", "Windows 8.3 alias regression runs on Windows")
    def test_windows_short_install_root_alias_is_checked_without_escape(self) -> None:
        import ctypes

        with tempfile.TemporaryDirectory(prefix="template-release-8dot3-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "source")
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetShortPathNameW(str(root), buffer, len(buffer))
            if not length or Path(buffer.value) == root:
                self.skipTest("the current Windows volume has no short alias")
            install_root = Path(buffer.value) / "installed" / "template-packages"
            result = self.run_tool("install", "--release-dir", source, "--install-root", install_root, "--json", root=root)
            self.assert_succeeded(result)

    def test_production_gh_cli_command_contracts(self) -> None:
        from unittest.mock import patch

        from tools.template_tooling.github_release import GhCliGitHubReleaseClient

        tag = "template/lesson-plan/v1.1.0"
        tag_object = "44936ee2a3fd7ddbdaec9ef3c92f30776736ea3f"
        source_commit = "b6710e11ec35dec0d4cb8e812ca72303f53410d1"
        repository = "ArdenZC/codex-work-skills"
        with tempfile.TemporaryDirectory(prefix="template-release-gh-cli-") as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log_path = root / "gh-argv.jsonl"
            self.git(root, "init", "-q")
            self.git(root, "remote", "add", "origin", "https://github.com/ArdenZC/codex-work-skills.git")
            fake_code = (
                "import json\n"
                "import os\n"
                "import sys\n"
                f"log_path = {str(log_path)!r}\n"
                f"tag = {tag!r}\n"
                f"tag_object = {tag_object!r}\n"
                f"source_commit = {source_commit!r}\n"
                f"repository = {repository!r}\n"
                "script_name = os.path.basename(sys.argv[0]).casefold()\n"
                "arguments = sys.argv[1:]\n"
                "if script_name in {'api', 'release'}:\n"
                "    arguments = [script_name] + arguments\n"
                "with open(log_path, 'a', encoding='utf-8') as stream:\n"
                "    stream.write(json.dumps(arguments) + '\\n')\n"
                "if arguments[:3] == ['api', '--hostname', 'github.com']:\n"
                "    endpoint = arguments[3] if len(arguments) == 4 else ''\n"
                "    ref_endpoint = f'repos/{repository}/git/ref/tags/{tag}'\n"
                "    object_endpoint = f'repos/{repository}/git/tags/{tag_object}'\n"
                "    if endpoint == ref_endpoint:\n"
                "        print(json.dumps({'object': {'sha': tag_object, 'type': 'tag'}}))\n"
                "    elif endpoint == object_endpoint:\n"
                "        print(json.dumps({'object': {'sha': source_commit, 'type': 'commit'}, 'message': 'Release operation: 2ea187b6841f4a2c8a591f37aaeada7d'}))\n"
                "    else:\n"
                "        raise SystemExit(f'unexpected API endpoint: {endpoint}')\n"
                "elif arguments[:2] == ['release', 'view']:\n"
                "    if arguments[-2:] != ['--repo', repository]:\n"
                "        raise SystemExit(f'missing repository scope: {arguments}')\n"
                "    print('{}')\n"
                "else:\n"
                "    raise SystemExit(f'unexpected gh command: {arguments}')\n"
            )
            if os.name == "nt":
                executable = bin_dir / "gh.exe"
                shutil.copy2(PYTHON, executable)
                (root / "api").write_text(fake_code, encoding="utf-8")
                (root / "release").write_text(fake_code, encoding="utf-8")
            else:
                executable = bin_dir / "gh"
                executable.write_text(f"#!{sys.executable}\n" + fake_code, encoding="utf-8")
                os.chmod(executable, 0o700)

            child_path = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            with patch.dict(os.environ, {"PATH": child_path}):
                client = GhCliGitHubReleaseClient(root, repository=repository)
                annotation = client.tag_annotation(tag)
                self.assertEqual(annotation["object_id"], tag_object)
                self.assertEqual(annotation["target"], source_commit)
                self.assertIn("Release operation: 2ea187b6841f4a2c8a591f37aaeada7d", annotation["message"])
                self.assertTrue(client.release_exists(tag))
                with self.assertRaisesRegex(Exception, "unsafe ref path"):
                    client.tag_annotation("template/lesson-plan/../v1.1.0")

            calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            api_calls = [arguments for arguments in calls if arguments and arguments[0] == "api"]
            self.assertEqual(
                api_calls,
                [
                    [
                        "api",
                        "--hostname",
                        "github.com",
                        f"repos/{repository}/git/ref/tags/{tag}",
                    ],
                    [
                        "api",
                        "--hostname",
                        "github.com",
                        f"repos/{repository}/git/tags/{tag_object}",
                    ],
                ],
            )
            self.assertTrue(all("--repo" not in arguments for arguments in api_calls))
            release_calls = [arguments for arguments in calls if arguments[:2] == ["release", "view"]]
            self.assertEqual(len(release_calls), 1)
            self.assertEqual(release_calls[0][-2:], ["--repo", repository])

    def test_post_mutation_tag_failure_reconciles_and_cleans_owned_tag(self) -> None:
        from tools.template_tooling.github_release import (
            InMemoryGitHubReleaseClient,
            TemplateToolError,
            publish_release_transaction,
        )

        class PostMutationFailureClient(InMemoryGitHubReleaseClient):
            def __init__(self) -> None:
                super().__init__()
                self.annotation_calls = 0

            def create_tag(self, tag: str, source_commit: str, message: str) -> None:
                super().create_tag(tag, source_commit, message)
                raise TemplateToolError("simulated post-mutation create_tag failure")

            def tag_annotation(self, tag: str) -> dict[str, Any]:
                self.annotation_calls += 1
                return super().tag_annotation(tag)

        with tempfile.TemporaryDirectory(prefix="template-release-reconcile-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = self.create_release(root, packages["1.1.1"], "post-mutation-reconcile")
            plan = output / "demo-template-1.1.1.release-plan.json"
            client = PostMutationFailureClient()
            with self.assertRaisesRegex(Exception, "simulated post-mutation create_tag failure"):
                publish_release_transaction(plan, root, client=client)
            self.assertGreaterEqual(client.annotation_calls, 1)
            self.assertEqual(client.tags, {})
            self.assertEqual(client.releases, {})

    def test_fake_github_release_transaction_happy_preexisting_and_cleanup(self) -> None:
        from tools.template_tooling.github_release import InMemoryGitHubReleaseClient, publish_release_transaction

        with tempfile.TemporaryDirectory(prefix="template-release-github-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = self.create_release(root, packages["1.1.1"], "github")
            plan = output / "demo-template-1.1.1.release-plan.json"
            happy_client = InMemoryGitHubReleaseClient()
            happy = publish_release_transaction(plan, root, client=happy_client)
            self.assertEqual(happy["status"], "passed")
            self.assertTrue(happy["remote_assets_identical"])
            self.assertEqual(happy["local_asset_sha256"], happy["remote_asset_sha256"])
            self.assertTrue(happy["operation_id"])
            tag = "template/demo-template/v1.1.1"
            self.assertIn(tag, happy_client.tags)
            self.assertIn(f"Release operation: {happy['operation_id']}", happy_client.tags[tag]["message"])
            self.assertIn(f"<!-- template-release-operation:{happy['operation_id']} -->", happy_client.releases[tag]["body"])
            self.assertEqual(set(happy_client.releases[tag]["assets"]), {
                "demo-template-1.1.1.zip",
                "demo-template-1.1.1.zip.sha256",
                "demo-template-1.1.1.metadata.json",
            })

            preexisting_release = InMemoryGitHubReleaseClient()
            preexisting_release.releases[tag] = {
                "id": 99,
                "name": "existing",
                "tag": tag,
                "body": "existing",
                "prerelease": False,
                "assets": {"demo-template-1.1.1.zip": b"existing"},
            }
            with self.assertRaises(Exception):
                publish_release_transaction(plan, root, client=preexisting_release)
            self.assertEqual(preexisting_release.releases[tag]["assets"]["demo-template-1.1.1.zip"], b"existing")

            preexisting = InMemoryGitHubReleaseClient()
            preexisting.tags[tag] = {
                "object_id": "existing-object",
                "target": "existing",
                "message": "existing",
            }
            with self.assertRaises(Exception):
                publish_release_transaction(plan, root, client=preexisting)
            self.assertEqual(preexisting.tags[tag]["target"], "existing")

            assets = [
                "demo-template-1.1.1.zip",
                "demo-template-1.1.1.zip.sha256",
                "demo-template-1.1.1.metadata.json",
            ]
            for asset in assets:
                failed_upload = InMemoryGitHubReleaseClient(fail_at=f"upload_asset:{asset}")
                with self.assertRaises(Exception):
                    publish_release_transaction(plan, root, client=failed_upload)
                self.assertEqual(failed_upload.tags, {})
                self.assertEqual(failed_upload.releases, {})

            class CorruptDownloadClient(InMemoryGitHubReleaseClient):
                def download_asset(self, tag: str, name: str, destination: Path) -> Path:
                    path = super().download_asset(tag, name, destination)
                    if name == "demo-template-1.1.1.zip":
                        path.write_bytes(b"corrupt")
                    return path

            corrupt_download = CorruptDownloadClient()
            with self.assertRaises(Exception):
                publish_release_transaction(plan, root, client=corrupt_download)
            self.assertEqual(corrupt_download.tags, {})
            self.assertEqual(corrupt_download.releases, {})

            class WrongIdentityClient(InMemoryGitHubReleaseClient):
                def tag_annotation(self, tag: str) -> dict[str, Any]:
                    identity = super().tag_annotation(tag)
                    identity["target"] = "0" * 40
                    return identity

            wrong_identity = WrongIdentityClient()
            with self.assertRaisesRegex(Exception, "ownership could not be proven"):
                publish_release_transaction(plan, root, client=wrong_identity)
            self.assertIn(tag, wrong_identity.tags)
            self.assertEqual(wrong_identity.releases, {})

            failed_download = InMemoryGitHubReleaseClient(fail_at="download_asset:demo-template-1.1.1.metadata.json")
            with self.assertRaises(Exception):
                publish_release_transaction(plan, root, client=failed_download)
            self.assertEqual(failed_download.tags, {})
            self.assertEqual(failed_download.releases, {})

            cleanup_failure = InMemoryGitHubReleaseClient(fail_at={"create_release", "delete_tag"})
            with self.assertRaisesRegex(Exception, "failed to delete created tag"):
                publish_release_transaction(plan, root, client=cleanup_failure)

            cleanup_release_failure = InMemoryGitHubReleaseClient(
                fail_at={"upload_asset:demo-template-1.1.1.zip.sha256", "delete_release"}
            )
            with self.assertRaisesRegex(Exception, "failed to delete created release"):
                publish_release_transaction(plan, root, client=cleanup_release_failure)

            for event in ("create_tag", "create_release"):
                mutated = InMemoryGitHubReleaseClient(fail_at=f"mutate_then_raise:{event}")
                with self.assertRaises(Exception):
                    publish_release_transaction(plan, root, client=mutated)
                self.assertEqual(mutated.tags, {})
                self.assertEqual(mutated.releases, {})
            for asset in assets:
                mutated = InMemoryGitHubReleaseClient(fail_at=f"mutate_then_raise:upload_asset:{asset}")
                with self.assertRaises(Exception):
                    publish_release_transaction(plan, root, client=mutated)
                self.assertEqual(mutated.tags, {})
                self.assertEqual(mutated.releases, {})

            concurrent_tag = InMemoryGitHubReleaseClient(fail_at="concurrent_other:create_tag")
            with self.assertRaisesRegex(Exception, "concurrently"):
                publish_release_transaction(plan, root, client=concurrent_tag)
            self.assertIn(tag, concurrent_tag.tags)
            self.assertEqual(concurrent_tag.releases, {})

            concurrent_release = InMemoryGitHubReleaseClient(fail_at="concurrent_other:create_release")
            with self.assertRaisesRegex(Exception, "concurrently"):
                publish_release_transaction(plan, root, client=concurrent_release)
            self.assertIn(tag, concurrent_release.tags)
            self.assertIn(tag, concurrent_release.releases)
            self.assertEqual(concurrent_release.releases[tag]["assets"], {})

            concurrent_asset = InMemoryGitHubReleaseClient(fail_at="concurrent_other:upload_asset")
            with self.assertRaisesRegex(Exception, "concurrently"):
                publish_release_transaction(plan, root, client=concurrent_asset)
            self.assertIn(tag, concurrent_asset.tags)
            self.assertIn(tag, concurrent_asset.releases)
            self.assertEqual(set(concurrent_asset.releases[tag]["assets"]), {assets[0]})

            replacement_package = self.make_external_package(packages["1.1.1"], root, "1.1.1")
            replacement = self.create_archive(root, replacement_package, "replacement")

            class RemoteSelfConsistentReplacementClient(InMemoryGitHubReleaseClient):
                def download_asset(self, remote_tag: str, name: str, destination: Path) -> Path:
                    destination.mkdir(parents=True, exist_ok=False)
                    target = destination / name
                    shutil.copy2(replacement / name, target)
                    return target

            replacement_verified = self.assert_succeeded(
                self.run_tool("verify-release", "--release-dir", replacement, "--json", root=root)
            )
            self.assertEqual(replacement_verified["status"], "passed")
            replacement_client = RemoteSelfConsistentReplacementClient()
            with self.assertRaisesRegex(Exception, "remote asset SHA"):
                publish_release_transaction(plan, root, client=replacement_client)
            self.assertEqual(replacement_client.tags, {})
            self.assertEqual(replacement_client.releases, {})

    def test_publication_revalidates_local_bundle_against_source_commit(self) -> None:
        from tools.template_tooling.github_release import InMemoryGitHubReleaseClient, publish_release_transaction

        def replace_bundle_and_rewrite_plan(release_dir: Path, replacement_dir: Path) -> Path:
            for replacement in replacement_dir.iterdir():
                if replacement.is_file():
                    shutil.copy2(replacement, release_dir / replacement.name)
            plan_path = next(release_dir.glob("*.release-plan.json"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["archive_sha256"] = sha256(release_dir / plan["archive"])
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            verified = self.assert_succeeded(
                self.run_tool("verify-release", "--release-dir", release_dir, "--json", root=release_dir.parents[2])
            )
            self.assertEqual(verified["status"], "passed")
            return plan_path

        with tempfile.TemporaryDirectory(prefix="template-release-publish-provenance-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            legitimate = self.create_release(root, packages["1.1.1"], "legitimate")
            legitimate_plan = legitimate / "demo-template-1.1.1.release-plan.json"
            untouched_client = InMemoryGitHubReleaseClient()
            self.assertEqual(
                publish_release_transaction(legitimate_plan, root, client=untouched_client)["status"],
                "passed",
            )

            external = self.make_external_package(packages["1.1.1"], root, "1.1.1")
            replacement = self.create_archive(root, external, "replacement-source")
            replaced = root / "dist" / "template-packages" / "replaced-source"
            shutil.copytree(legitimate, replaced)
            replaced_plan = replace_bundle_and_rewrite_plan(replaced, replacement)
            replacement_client = InMemoryGitHubReleaseClient()
            with self.assertRaisesRegex(Exception, "release bundle does not match source_commit"):
                publish_release_transaction(replaced_plan, root, client=replacement_client)
            self.assertEqual(replacement_client.events, [])

        with tempfile.TemporaryDirectory(prefix="template-release-publish-dependency-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root, versions=("1.1.0", "1.1.1"))
            manifest_path = packages["1.1.1"] / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["template"]["base_manifest"] = "../v1.1.0/manifest.yaml"
            manifest["template"]["base_template"] = "../v1.1.0/template.txt"
            manifest_path.write_text(
                yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            manifest_path.write_bytes(manifest_path.read_bytes().replace(b"\r\n", b"\n"))
            self.git(root, "add", "--", manifest_path.relative_to(root).as_posix())
            self.git(root, "commit", "-qm", "add fixture dependency")
            self.git(root, "push", "-q", "origin", "master")

            legitimate = self.create_release(root, packages["1.1.1"], "legitimate-dependency")
            external_root = root / "release-workspace" / "demo-template"
            external_root.mkdir(parents=True)
            shutil.copytree(packages["1.1.1"], external_root / "v1.1.1")
            shutil.copytree(packages["1.1.0"], external_root / "v1.1.9")
            replacement_dependency = external_root / "v1.1.9"
            replacement_template = replacement_dependency / "template.txt"
            replacement_template.write_text("replacement dependency template\n", encoding="utf-8")
            dependency_manifest_path = replacement_dependency / "manifest.yaml"
            dependency_manifest = yaml.safe_load(dependency_manifest_path.read_text(encoding="utf-8"))
            dependency_manifest["template"]["version"] = "1.1.9"
            dependency_digest = sha256(replacement_template)
            dependency_manifest["fingerprint"]["sha256"] = dependency_digest
            dependency_manifest["fingerprint"]["value"] = dependency_digest
            dependency_manifest_path.write_text(
                yaml.safe_dump(dependency_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            replacement_entry_manifest_path = external_root / "v1.1.1" / "manifest.yaml"
            replacement_entry_manifest = yaml.safe_load(
                replacement_entry_manifest_path.read_text(encoding="utf-8")
            )
            replacement_entry_manifest["template"]["base_manifest"] = "../v1.1.9/manifest.yaml"
            replacement_entry_manifest["template"]["base_template"] = "../v1.1.9/template.txt"
            replacement_entry_manifest_path.write_text(
                yaml.safe_dump(replacement_entry_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            replacement = self.create_archive(root, external_root / "v1.1.1", "replacement-dependency")
            replaced = root / "dist" / "template-packages" / "replaced-dependency"
            shutil.copytree(legitimate, replaced)
            replaced_plan = replace_bundle_and_rewrite_plan(replaced, replacement)
            replacement_client = InMemoryGitHubReleaseClient()
            with self.assertRaisesRegex(Exception, "release bundle does not match source_commit"):
                publish_release_transaction(replaced_plan, root, client=replacement_client)
            self.assertEqual(replacement_client.events, [])

    def test_untrusted_external_validator_is_never_executed_during_release_verify(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template-release-untrusted-") as directory:
            root = Path(directory)
            skill, packages = self.make_fixture_repo(root)
            source = self.create_release(root, packages["1.1.1"], "trusted")
            malicious_skill = root / "untrusted-skill"
            malicious_package = malicious_skill / "assets" / "templates" / "demo-template" / "v1.1.1"
            malicious_package.parent.mkdir(parents=True)
            shutil.copytree(packages["1.1.1"], malicious_package)
            marker = root / "MALICIOUS_VALIDATOR_EXECUTED"
            malicious_validator = malicious_skill / "scripts" / "validate_template.py"
            malicious_validator.parent.mkdir(parents=True)
            malicious_validator.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nraise SystemExit(0)\n",
                encoding="utf-8",
            )
            passed = self.run_tool("verify-release", "--release-dir", source, "--json", root=root)
            self.assert_succeeded(passed)
            self.assertFalse(marker.exists())
            spoofed = root / "dist" / "template-packages" / "owner-spoof"
            shutil.copytree(source, spoofed)
            spoofed_metadata = next(spoofed.glob("*.metadata.json"))
            spoofed_payload = json.loads(spoofed_metadata.read_text(encoding="utf-8"))
            spoofed_payload["owner_skill"] = "untrusted-skill"
            spoofed_metadata.write_text(json.dumps(spoofed_payload) + "\n", encoding="utf-8")
            rejected = self.run_tool("verify-release", "--release-dir", spoofed, "--json", root=root)
            self.assert_failed(rejected, "owner")

    def test_publication_repository_identity_is_bound_to_origin_before_mutation(self) -> None:
        from tools.template_tooling.github_release import InMemoryGitHubReleaseClient, publish_release_transaction

        with tempfile.TemporaryDirectory(prefix="template-release-repository-identity-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = self.create_release(root, packages["1.1.1"], "repository-identity")
            plan = output / "demo-template-1.1.1.release-plan.json"
            remote = root.parent / f"{root.name}-origin.git"
            https_origin = "https://github.com/ArdenZC/codex-work-skills.git"

            def set_origin(url: str) -> None:
                self.git(root, "remote", "set-url", "origin", url)
                self.git(root, "config", f"url.{remote.as_uri()}.insteadOf", url)

            https_client = InMemoryGitHubReleaseClient()
            self.assertEqual(
                publish_release_transaction(plan, root, client=https_client)["status"],
                "passed",
            )

            set_origin("git@github.com:ArdenZC/codex-work-skills.git")
            ssh_client = InMemoryGitHubReleaseClient()
            self.assertEqual(
                publish_release_transaction(
                    plan,
                    root,
                    client=ssh_client,
                    repository="ArdenZC/codex-work-skills",
                )["status"],
                "passed",
            )

            set_origin("ssh://git@github.com/ArdenZC/codex-work-skills.git")
            ssh_url_client = InMemoryGitHubReleaseClient()
            self.assertEqual(
                publish_release_transaction(
                    plan,
                    root,
                    client=ssh_url_client,
                    repository="ArdenZC/codex-work-skills",
                )["status"],
                "passed",
            )

            set_origin(https_origin)
            case_client = InMemoryGitHubReleaseClient()
            self.assertEqual(
                publish_release_transaction(
                    plan,
                    root,
                    client=case_client,
                    repository="ardenzc/CODEX-WORK-SKILLS",
                )["status"],
                "passed",
            )

            mismatch = InMemoryGitHubReleaseClient()
            with self.assertRaisesRegex(Exception, "does not match origin"):
                publish_release_transaction(
                    plan,
                    root,
                    client=mismatch,
                    repository="ArdenZC/another-repo",
                )
            self.assertEqual(mismatch.events, [])
            self.assertEqual(mismatch.tags, {})
            self.assertEqual(mismatch.releases, {})

            self.git(root, "remote", "remove", "origin")
            missing = InMemoryGitHubReleaseClient()
            with self.assertRaisesRegex(Exception, "origin"):
                publish_release_transaction(plan, root, client=missing)
            self.assertEqual(missing.events, [])

            self.git(root, "remote", "add", "origin", "not-a-url")
            malformed = InMemoryGitHubReleaseClient()
            with self.assertRaisesRegex(Exception, "malformed"):
                publish_release_transaction(plan, root, client=malformed)
            self.assertEqual(malformed.events, [])

            set_origin("git@example.com:owner/repo.git")
            unsupported = InMemoryGitHubReleaseClient()
            with self.assertRaisesRegex(Exception, "unsupported GitHub origin host"):
                publish_release_transaction(plan, root, client=unsupported)
            self.assertEqual(unsupported.events, [])

    def test_publish_requires_live_remote_master_and_rejects_stale_or_unavailable_origin(self) -> None:
        from tools.template_tooling.github_release import InMemoryGitHubReleaseClient, publish_release_transaction

        with tempfile.TemporaryDirectory(prefix="template-release-master-provenance-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = self.create_release(root, packages["1.1.1"], "master-check")
            plan = output / "demo-template-1.1.1.release-plan.json"
            remote = root.parent / f"{root.name}-origin.git"
            clone = root.parent / f"{root.name}-remote-clone"
            self.git(root.parent, "clone", remote, clone)
            self.git(clone, "config", "user.name", "Remote Advance")
            self.git(clone, "config", "user.email", "remote-advance@example.invalid")
            self.git(clone, "commit", "--allow-empty", "-qm", "remote advance")
            self.git(clone, "push", "-q", "origin", "master")
            with self.assertRaisesRegex(Exception, "remote master"):
                publish_release_transaction(plan, root, client=InMemoryGitHubReleaseClient())

        with tempfile.TemporaryDirectory(prefix="template-release-master-unavailable-") as directory:
            root = Path(directory)
            _, packages = self.make_fixture_repo(root)
            output = self.create_release(root, packages["1.1.1"], "master-unavailable")
            plan = output / "demo-template-1.1.1.release-plan.json"
            self.git(root, "remote", "remove", "origin")
            with self.assertRaisesRegex(Exception, "cannot resolve GitHub origin repository"):
                publish_release_transaction(plan, root, client=InMemoryGitHubReleaseClient())

    def test_release_workflow_contract_is_manual_master_only_and_fail_closed(self) -> None:
        workflow = (ROOT / ".github/workflows/template-release.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s+(push|pull_request):")
        self.assertIn("contents: write", workflow)
        self.assertIn("template_id:", workflow)
        self.assertIn("version:", workflow)
        self.assertIn("ref: master", workflow)
        self.assertIn("origin/master", workflow)
        self.assertIn("template_package.py release", workflow)
        self.assertIn("verify-release", workflow)
        self.assertIn("refs/tags", workflow)
        self.assertIn("gh release view", workflow)
        self.assertIn("github_release", workflow)
        self.assertIn("download", workflow)
        self.assertIn("GH_TOKEN", workflow)
        self.assertIn("concurrency:", workflow)
        self.assertIn("group: template-release-${{ inputs.template_id }}-${{ inputs.version }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertNotIn("--force", workflow)
        self.assertNotIn("--clobber", workflow)
