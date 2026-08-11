from __future__ import annotations

import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import time
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

    def initialize_fixture_git_index(self, root: Path, *tracked_paths: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Template Tool Tests"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "template-tool-tests@example.invalid"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        relative = [str(path.relative_to(root)).replace("\\", "/") for path in tracked_paths]
        subprocess.run(["git", "add", "--", *relative], cwd=root, check=True, capture_output=True)

    def stage_fixture_paths(self, root: Path, *tracked_paths: Path) -> None:
        relative = [str(path.relative_to(root)).replace("\\", "/") for path in tracked_paths]
        subprocess.run(["git", "add", "--", *relative], cwd=root, check=True, capture_output=True)

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

    def json_result(self, result: subprocess.CompletedProcess[str]) -> dict:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"tool output was not JSON: {result.stdout}\nstderr={result.stderr}")
            raise AssertionError from exc

    def assert_process_succeeded(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(
            result.returncode,
            0,
            (
                f"command={result.args!r}\n"
                f"returncode={result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ),
        )

    def assert_process_failed(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(
            result.returncode,
            0,
            (
                f"command={result.args!r}\n"
                f"returncode={result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ),
        )

    def make_fixture_repo(
        self,
        temp_root: Path,
        *,
        template_id: str = "demo-template",
        version: str = "1.0.0",
        validator_mode: str = "pass",
        with_changelog: bool = True,
        init_git: bool = True,
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
            "schema": "schemas/demo.schema.json",
        }
        (package / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        if with_changelog:
            (package / "CHANGELOG.md").write_text("# Fixture\n", encoding="utf-8")
        scripts = skill_root / "scripts"
        scripts.mkdir(exist_ok=True)
        schemas = skill_root / "schemas"
        schemas.mkdir(exist_ok=True)
        (schemas / "demo.schema.json").write_text('{"type": "object"}\n', encoding="utf-8")
        helper = scripts / "helper.py"
        helper_prefix = 'VALUE = "trusted"\n'
        helper.write_text(
            helper_prefix + "#" + "x" * (2048 - len(helper_prefix) - 2) + "\n",
            encoding="utf-8",
        )
        (scripts / "validate_template.py").write_text(
            "from pathlib import Path\n"
            "import os\n"
            "import sys\n"
            "import time\n"
            "import helper\n"
            "assert helper.VALUE == 'trusted'\n"
            "manifest = Path(sys.argv[sys.argv.index('--manifest') + 1])\n"
            "package = manifest.parent\n"
            "start_marker = package / 'validator-start-marker.txt'\n"
            "if start_marker.is_file():\n"
            "    Path(start_marker.read_text(encoding='utf-8').strip()).write_text('started', encoding='utf-8')\n"
            "if (package / 'validator-timeout').exists():\n"
            "    print('超时标准输出', flush=True)\n"
            "    print('超时错误输出', file=sys.stderr, flush=True)\n"
            "    print(str(package), flush=True)\n"
            "    time.sleep(30)\n"
            "marker = os.environ.get('TEMPLATE_TOOL_TEST_BASE_VALIDATOR_MARKER')\n"
            "if marker:\n"
            "    Path(marker).write_text('started', encoding='utf-8')\n"
            "inspect_config = package / 'validator-inspect-target.txt'\n"
            "inspect = inspect_config.read_text(encoding='utf-8').strip() if inspect_config.is_file() else None\n"
            "if inspect:\n"
            "    scripts = Path(__file__).resolve().parent\n"
            "    files = sorted(path.relative_to(scripts).as_posix() for path in scripts.rglob('*') if path.is_file())\n"
            "    Path(inspect).write_text('\\n'.join(files), encoding='utf-8')\n"
            "if (package / 'validator-fail').exists():\n"
            "    print('fixture validator failed', file=sys.stderr)\n"
            "    raise SystemExit(7)\n"
            "print('fixture validator passed')\n",
            encoding="utf-8",
        )
        tracked = [
            package / "manifest.yaml",
            package / "template.txt",
            helper,
            scripts / "validate_template.py",
            schemas / "demo.schema.json",
        ]
        if with_changelog:
            tracked.append(package / "CHANGELOG.md")
        if init_git:
            self.initialize_fixture_git_index(temp_root, *tracked)
        return skill_root, package, template

    def make_repo_validator(self, root: Path) -> None:
        tests_dir = root / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "validate_template_packages.py").write_text(
            "from pathlib import Path\n"
            "import os\n"
            "import sys\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "mutation = os.environ.get('TEMPLATE_TOOL_TEST_REPO_MUTATION')\n"
            "template_roots = sorted(root.glob('**/assets/templates'))\n"
            "template_root = template_roots[0]\n"
            "other = template_root / 'other-template' / 'v1.0.0'\n"
            "target = template_root / 'demo-template' / 'v1.0.1'\n"
            "if mutation in {'other-change', 'other-change-nonzero', 'target-and-other'}:\n"
            "    (other / 'CHANGELOG.md').write_text('mutated by repository validator\\n', encoding='utf-8')\n"
            "    (other / 'repo-validator-output.txt').write_text('unexpected\\n', encoding='utf-8')\n"
            "if mutation == 'other-delete':\n"
            "    (other / 'manifest.yaml').unlink()\n"
            "if mutation == 'other-add':\n"
            "    added = template_root / 'other-template' / 'v9.9.9'\n"
            "    added.mkdir(parents=True)\n"
            "    (added / 'manifest.yaml').write_text('added: true\\n', encoding='utf-8')\n"
            "    (added / 'template.txt').write_text('added\\n', encoding='utf-8')\n"
            "if mutation == 'target-and-other':\n"
            "    (target / 'template.txt').write_text('target mutation\\n', encoding='utf-8')\n"
            "if mutation == 'other-change-nonzero':\n"
            "    print('repository validator mutated another package', file=sys.stderr)\n"
            "    raise SystemExit(17)\n"
            "if (root / 'repo-fail').exists():\n"
            "    print('repo validator failed', file=sys.stderr)\n"
            "    raise SystemExit(9)\n"
            "print('repo validator passed')\n",
            encoding="utf-8",
        )

    def add_fixture_package(self, skill_root: Path, template_id: str = "other-template", version: str = "1.0.0") -> Path:
        root = skill_root.parents[1]
        package = skill_root / "assets" / "templates" / template_id / f"v{version}"
        package.mkdir(parents=True)
        template = package / "template.txt"
        template.write_text(f"{template_id} canonical template\n", encoding="utf-8")
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
            "schema": "schemas/demo.schema.json",
        }
        (package / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        (package / "CHANGELOG.md").write_text("# Other fixture\n", encoding="utf-8")
        self.stage_fixture_paths(
            root,
            package / "manifest.yaml",
            package / "template.txt",
            package / "CHANGELOG.md",
        )
        return package

    def run_repo_validator(
        self,
        root: Path,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        return subprocess.run(
            [str(PYTHON), str(ROOT / "tests" / "validate_template_packages.py"), "--repo-root", str(root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=process_env,
        )

    def make_dependent_fixture_repo(self, root: Path) -> tuple[Path, Path, Path]:
        skill, base, template = self.make_fixture_repo(root)
        target = base.parent / "v1.1.0"
        shutil.copytree(base, target)
        target_manifest = yaml.safe_load((target / "manifest.yaml").read_text(encoding="utf-8"))
        target_manifest["template"]["version"] = "1.1.0"
        target_manifest["template"]["base_manifest"] = "../v1.0.0/manifest.yaml"
        target_manifest["template"]["base_template"] = "../v1.0.0/template.txt"
        (target / "manifest.yaml").write_text(
            yaml.safe_dump(target_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return skill, target, target / "template.txt"

    def prepare_multi_package_promotion(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        skill, base, _ = self.make_fixture_repo(root)
        other = self.add_fixture_package(skill)
        self.make_repo_validator(root)
        source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
        scaffold = self.run_tool(
            "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
        )
        self.assert_process_succeeded(scaffold)
        target = skill / "assets" / "templates" / "demo-template" / "v1.0.1"
        return skill, base, other, source, target

    def test_discover_current_four_packages_without_libreoffice(self) -> None:
        result = self.run_tool("discover", "--json")
        self.assert_process_succeeded(result)
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

    def test_dynamic_repository_validator_discovers_and_validates_new_canonical_patch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            first = self.run_repo_validator(root)
            self.assert_process_succeeded(first)
            self.assertIn("Validated 1 canonical template packages.", first.stdout)
            patch = base.parent / "v1.0.1"
            shutil.copytree(base, patch)
            manifest_path = patch / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["template"]["version"] = "1.0.1"
            manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            second = self.run_repo_validator(root)
            self.assert_process_succeeded(second)
            self.assertIn("Validated 2 canonical template packages.", second.stdout)

    def test_dynamic_repository_validator_catches_new_patch_validator_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            patch = base.parent / "v1.0.1"
            shutil.copytree(base, patch)
            manifest_path = patch / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["template"]["version"] = "1.0.1"
            manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            (patch / "validator-fail-v101").write_text("fail\n", encoding="utf-8")
            (skill / "scripts" / "validate_template.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "manifest = Path(sys.argv[sys.argv.index('--manifest') + 1])\n"
                "if manifest.parent.name == 'v1.0.1' and (manifest.parent / 'validator-fail-v101').exists():\n"
                "    print('patch validator failed', file=sys.stderr)\n"
                "    raise SystemExit(7)\n"
                "print('fixture validator passed')\n",
                encoding="utf-8",
            )
            failed = self.run_repo_validator(root)
            self.assert_process_failed(failed)
            self.assertIn("template validator failed", failed.stdout)
            self.assertIn("1.0.1", failed.stdout)

    def test_untracked_canonical_like_skill_is_reported_and_never_executed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            fake_skill = root / "untrusted-skill"
            fake_package = fake_skill / "assets" / "templates" / "demo-template" / "v1.0.1"
            fake_package.parent.mkdir(parents=True)
            shutil.copytree(base, fake_package)
            manifest_path = fake_package / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["template"]["version"] = "1.0.1"
            manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            marker = root / "MALICIOUS_VALIDATOR_EXECUTED"
            fake_validator = fake_skill / "scripts" / "validate_template.py"
            fake_validator.parent.mkdir(parents=True)
            fake_validator.write_text(
                "from pathlib import Path\n"
                f"Path(r'{marker}').write_text('executed', encoding='utf-8')\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )

            discovered = self.run_tool("discover", "--json", root=root)
            self.assert_process_failed(discovered)
            self.assertIn("no trusted Git-tracked owner validator", discovered.stdout)
            validated = self.run_tool("validate", "--package", fake_package, "--json", root=root)
            self.assert_process_failed(validated)
            self.assertIn("no trusted Git-tracked owner validator", validated.stdout)
            repository = self.run_repo_validator(root)
            self.assert_process_failed(repository)
            self.assertIn("Git-tracked owner validator", repository.stdout)
            self.assertFalse(marker.exists())

    def test_git_index_tracked_new_skill_can_be_discovered_and_validated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            new_skill = root / "new-skill"
            new_package = new_skill / "assets" / "templates" / "new-template" / "v1.0.0"
            new_package.parent.mkdir(parents=True)
            shutil.copytree(base, new_package)
            new_manifest = yaml.safe_load((new_package / "manifest.yaml").read_text(encoding="utf-8"))
            new_manifest["template"]["id"] = "new-template"
            (new_package / "manifest.yaml").write_text(
                yaml.safe_dump(new_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            new_scripts = new_skill / "scripts"
            new_scripts.mkdir(parents=True)
            shutil.copy2(skill / "scripts" / "helper.py", new_scripts / "helper.py")
            shutil.copy2(skill / "scripts" / "validate_template.py", new_scripts / "validate_template.py")
            new_schemas = new_skill / "schemas"
            new_schemas.mkdir(parents=True)
            shutil.copy2(skill / "schemas" / "demo.schema.json", new_schemas / "demo.schema.json")
            self.stage_fixture_paths(
                root,
                new_package / "manifest.yaml",
                new_package / "template.txt",
                new_scripts / "helper.py",
                new_scripts / "validate_template.py",
                new_schemas / "demo.schema.json",
                new_package / "CHANGELOG.md",
            )

            discovered = self.run_tool("discover", "--json", root=root)
            self.assert_process_succeeded(discovered)
            package_info = next(
                item for item in self.json_result(discovered)["packages"] if item["id"] == "new-template"
            )
            self.assertTrue(package_info["is_canonical"])
            self.assertEqual(package_info["errors"], [])
            validated = self.run_tool("validate", "--package", new_package, "--json", root=root)
            self.assert_process_succeeded(validated)
            self.assertEqual(self.json_result(validated)["status"], "passed")

    def test_untracked_scripts_helper_is_rejected_before_validator_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            marker = root / "MALICIOUS_HELPER_EXECUTED"
            helper = skill / "scripts" / "malicious_helper.py"
            helper.write_text(
                "from pathlib import Path\n"
                f"Path(r'{marker}').write_text('executed', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (skill / "scripts" / "validate_template.py").write_text(
                "import malicious_helper\n"
                "print('validator should not have run')\n",
                encoding="utf-8",
            )
            result = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assert_process_failed(result)
            self.assertIn("untrusted", result.stdout.lower())
            self.assertIn("scripts", result.stdout.lower())
            self.assertFalse(marker.exists())

    def test_scripts_reject_ordinary_bytecode_but_ignore_python_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            ordinary_files = (
                Path("yaml.pyc"),
                Path("sitecustomize.pyc"),
                Path("helpers") / "compiled.pyc",
                Path("helpers") / "legacy.pyo",
            )
            for relative in ordinary_files:
                with self.subTest(relative=relative):
                    path = skill / "scripts" / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"not executable Python bytecode")
                    self.stage_fixture_paths(root, path)
                    result = self.run_tool("validate", "--package", package, "--json", root=root)
                    self.assert_process_failed(result)
                    self.assertIn("bytecode", result.stdout.lower())
                    self.assertIn(path.name, result.stdout)
                    path.unlink()
                    subprocess.run(
                        [
                            "git",
                            "rm",
                            "--cached",
                            "--quiet",
                            "--",
                            str(path.relative_to(root)).replace("\\", "/"),
                        ],
                        cwd=root,
                        check=True,
                        capture_output=True,
                    )

            cache = skill / "scripts" / "__pycache__"
            cache.mkdir()
            (cache / "helper.cpython-311.pyc").write_bytes(b"cache")
            (cache / "helper.pyo").write_bytes(b"cache")
            inspected = root / "isolated-scripts.txt"
            (package / "validator-inspect-target.txt").write_text(str(inspected), encoding="utf-8")
            external_package = root / "external-work" / "demo-template" / "v1.0.1"
            external_package.parent.mkdir(parents=True)
            shutil.copytree(package, external_package)
            external_manifest_path = external_package / "manifest.yaml"
            external_manifest = yaml.safe_load(external_manifest_path.read_text(encoding="utf-8"))
            external_manifest["template"]["version"] = "1.0.1"
            external_manifest_path.write_text(
                yaml.safe_dump(external_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = self.run_tool(
                "validate",
                "--package", external_package,
                "--json",
                root=root,
            )
            self.assert_process_succeeded(result)
            self.assertEqual(self.json_result(result)["status"], "passed")
            copied_scripts = inspected.read_text(encoding="utf-8")
            self.assertNotIn("__pycache__", copied_scripts)
            self.assertNotIn(".pyc", copied_scripts)
            self.assertNotIn(".pyo", copied_scripts)

            repository = self.run_repo_validator(root)
            self.assert_process_succeeded(repository)
            archive = self.run_tool(
                "archive",
                "--package", external_package,
                "--output-dir", root / "dist" / "template-packages",
                "--json",
                root=root,
            )
            self.assert_process_succeeded(archive)
            self.assertTrue((root / "dist" / "template-packages" / "demo-template-1.0.1.zip").is_file())

    def test_all_validator_flows_isolate_timestamp_cache_and_python_environment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            scripts = skill / "scripts"
            helper = scripts / "helper.py"
            cache = scripts / "__pycache__"
            cache.mkdir()
            marker = root / "MALICIOUS_CACHE_EXECUTED"
            malicious_source = root / "malicious-helper-source.py"
            malicious_code = (
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
                "VALUE = 'malicious'\n"
            )
            helper_size = helper.stat().st_size
            self.assertLess(len(malicious_code.encode("utf-8")), helper_size)
            malicious_source.write_bytes(
                malicious_code.encode("utf-8")
                + b"#"
                + b"x" * (helper_size - len(malicious_code.encode("utf-8")) - 2)
                + b"\n"
            )
            helper_mtime = helper.stat().st_mtime
            os.utime(malicious_source, (helper_mtime, helper_mtime))
            cache_path = cache / f"helper.{sys.implementation.cache_tag}.pyc"
            py_compile.compile(
                str(malicious_source),
                cfile=str(cache_path),
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
            )
            malicious_source.unlink()

            probe_environment = os.environ.copy()
            for key in tuple(probe_environment):
                if key.startswith("PYTHON"):
                    probe_environment.pop(key, None)
            proof = subprocess.run(
                [str(PYTHON), "-c", "import helper; assert helper.VALUE == 'malicious'"],
                cwd=scripts,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=probe_environment,
            )
            self.assert_process_succeeded(proof)
            self.assertTrue(marker.is_file())
            marker.unlink()

            def script_snapshot() -> dict[str, str]:
                return {
                    path.relative_to(scripts).as_posix(): sha256(path)
                    for path in scripts.rglob("*")
                    if path.is_file()
                }

            cache_before = script_snapshot()
            malicious_pythonpath = root / "malicious-pythonpath"
            malicious_pythonpath.mkdir()
            (malicious_pythonpath / "sitecustomize.py").write_text(
                f"from pathlib import Path\nPath({str(root / 'MALICIOUS_ENV_EXECUTED')!r}).write_text('executed', encoding='utf-8')\n",
                encoding="utf-8",
            )
            malicious_userbase = root / "malicious-userbase"
            malicious_startup = root / "malicious-startup.py"
            malicious_startup.write_text("raise SystemExit('startup should not run')\n", encoding="utf-8")
            validator_env = {
                "PYTHONPATH": str(malicious_pythonpath),
                "PYTHONUSERBASE": str(malicious_userbase),
                "PYTHONSTARTUP": str(malicious_startup),
                "PYTHONINSPECT": "1",
                "PYTHONHOME": str(root / "malicious-pythonhome"),
            }
            injected_env = {"TEMPLATE_TOOL_TEST_VALIDATOR_ENV_JSON": json.dumps(validator_env)}
            temporary_before = {
                path
                for prefix in ("template-tool-validation-*", "template-tool-repo-validation-*")
                for path in Path(tempfile.gettempdir()).glob(prefix)
            }

            canonical = self.run_tool(
                "validate", "--package", package, "--json", root=root, env=injected_env
            )
            self.assert_process_succeeded(canonical)
            canonical_report = self.json_result(canonical)
            self.assertEqual(canonical_report["source_scope"], "canonical")
            self.assertEqual(canonical_report["validation_scope"], "isolated_temp")
            self.assertEqual(canonical_report["validator_environment"], {
                "isolated_python_path": True,
                "user_site_disabled": True,
                "pycache_redirected": True,
            })
            self.assertFalse(marker.exists())
            self.assertFalse(root.joinpath("MALICIOUS_ENV_EXECUTED").exists())

            repository = self.run_repo_validator(root, env=injected_env)
            self.assert_process_succeeded(repository)
            self.assertFalse(marker.exists())
            self.assertFalse(root.joinpath("MALICIOUS_ENV_EXECUTED").exists())

            external_package = root / "external-work" / "demo-template" / "v1.0.1"
            external_package.parent.mkdir(parents=True)
            shutil.copytree(package, external_package)
            external_manifest_path = external_package / "manifest.yaml"
            external_manifest = yaml.safe_load(external_manifest_path.read_text(encoding="utf-8"))
            external_manifest["template"]["version"] = "1.0.1"
            external_manifest_path.write_text(
                yaml.safe_dump(external_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            external = self.run_tool(
                "validate", "--package", external_package, "--json", root=root, env=injected_env
            )
            self.assert_process_succeeded(external)
            external_report = self.json_result(external)
            self.assertEqual(external_report["source_scope"], "external")
            self.assertEqual(external_report["validation_scope"], "isolated_temp")
            self.assertFalse(marker.exists())
            self.assertFalse(root.joinpath("MALICIOUS_ENV_EXECUTED").exists())

            archived = self.run_tool(
                "archive",
                "--package", external_package,
                "--output-dir", root.parent / f"{root.name}-dist-external",
                "--json",
                root=root,
                env=injected_env,
            )
            self.assert_process_succeeded(archived)
            self.assertFalse(marker.exists())
            self.assertFalse(root.joinpath("MALICIOUS_ENV_EXECUTED").exists())

            self.make_repo_validator(root)
            source = root / "work" / "template-packages" / "demo-template" / "1.0.2"
            scaffold = self.run_tool(
                "scaffold",
                "--base-package", package,
                "--version", "1.0.2",
                "--output-dir", source,
                "--json",
                root=root,
                env=injected_env,
            )
            self.assert_process_succeeded(scaffold)
            promoted = self.run_tool(
                "promote", "--package", source, "--json", root=root, env=injected_env
            )
            self.assert_process_succeeded(promoted)
            promoted_report = self.json_result(promoted)
            self.assertEqual(promoted_report["target_validation"]["source_scope"], "canonical")
            self.assertEqual(promoted_report["target_validation"]["validation_scope"], "isolated_temp")
            self.assertTrue((skill / "assets" / "templates" / "demo-template" / "v1.0.2").is_dir())
            self.assertFalse(marker.exists())
            self.assertFalse(root.joinpath("MALICIOUS_ENV_EXECUTED").exists())
            self.assertEqual(cache_before, script_snapshot())
            temporary_after = {
                path
                for prefix in ("template-tool-validation-*", "template-tool-repo-validation-*")
                for path in Path(tempfile.gettempdir()).glob(prefix)
            }
            self.assertEqual(temporary_before, temporary_after)

    def test_validator_commands_fail_closed_without_a_git_index(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root, init_git=False)
            result = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assert_process_failed(result)
            self.assertIn("Git index is required", result.stdout)

    def test_validator_timeout_cleans_isolated_workspace(self) -> None:
        from tools.template_tooling.validation import _subprocess_text, validate_package_path

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            (package / "validator-timeout").write_text("timeout\n", encoding="utf-8")
            before = set(Path(tempfile.gettempdir()).glob("template-tool-validation-*"))
            report = validate_package_path(package, root, timeout=1)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any("timed out" in error for error in report["errors"]))
            self.assertIn("超时标准输出", report["validator"]["stdout"])
            self.assertIn("超时错误输出", report["validator"]["stderr"])
            self.assertIsInstance(report["validator"]["stdout"], str)
            self.assertIsInstance(report["validator"]["stderr"], str)
            self.assertNotIn("template-tool-validation-", json.dumps(report, ensure_ascii=False))
            self.assertEqual(before, set(Path(tempfile.gettempdir()).glob("template-tool-validation-*")))
            self.assertIsInstance(_subprocess_text(b"\xffabc"), str)
            self.assertEqual(_subprocess_text(b"\xffabc"), "�abc")

    def test_symlink_in_validator_scripts_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            link = skill / "scripts" / "linked_helper.py"
            try:
                link.symlink_to(skill / "scripts" / "validate_template.py")
            except (OSError, NotImplementedError):
                self.skipTest("the current platform cannot create symlinks")
            result = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assert_process_failed(result)
            self.assertIn("symlink", result.stdout.lower())

            linked_skill = root / "linked-validator-skill"
            linked_package = linked_skill / "assets" / "templates" / "linked-template" / "v1.0.0"
            linked_package.parent.mkdir(parents=True)
            shutil.copytree(package, linked_package)
            linked_manifest = yaml.safe_load((linked_package / "manifest.yaml").read_text(encoding="utf-8"))
            linked_manifest["template"]["id"] = "linked-template"
            (linked_package / "manifest.yaml").write_text(
                yaml.safe_dump(linked_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            linked_scripts = linked_skill / "scripts"
            linked_scripts.mkdir(parents=True)
            linked_validator = linked_scripts / "validate_template.py"
            try:
                linked_validator.symlink_to(skill / "scripts" / "validate_template.py")
            except (OSError, NotImplementedError):
                self.skipTest("the current platform cannot create validator symlinks")
            linked_result = self.run_tool("validate", "--package", linked_package, "--json", root=root)
            self.assert_process_failed(linked_result)
            self.assertIn("trusted Git-tracked owner validator", linked_result.stdout)

    def test_fingerprint_contract_rejects_all_incomplete_or_ambiguous_forms(self) -> None:
        mutations = {
            "algorithm": lambda value: value.update(algorithm="SHA256"),
            "missing_algorithm": lambda value: value.pop("algorithm"),
            "missing_sha256": lambda value: value.pop("sha256"),
            "missing_value": lambda value: value.pop("value"),
            "mismatch": lambda value: value.update(value="0" * 64),
            "unicode": lambda value: value.update(sha256="０" * 64, value="０" * 64),
            "short": lambda value: value.update(sha256="0" * 63, value="0" * 63),
            "long": lambda value: value.update(sha256="0" * 65, value="0" * 65),
            "unknown": lambda value: value.update(extra="not allowed"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
                root = Path(directory)
                _, package, _ = self.make_fixture_repo(root)
                manifest_path = package / "manifest.yaml"
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest["fingerprint"])
                manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
                result = self.run_tool("discover", "--json", root=root)
                self.assert_process_failed(result)
                self.assertIn("fingerprint", result.stdout)

    def test_untracked_fake_owner_is_ignored_for_external_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            second_skill = root / "另一个技能" / "demo-skill"
            second_package = second_skill / "assets" / "templates" / "demo-template" / "v1.0.0"
            second_package.parent.mkdir(parents=True)
            shutil.copytree(package, second_package)
            second_scripts = second_skill / "scripts"
            second_scripts.mkdir(parents=True)
            shutil.copy2(skill / "scripts" / "validate_template.py", second_scripts / "validate_template.py")
            external = root / "external" / "v1.0.1"
            external.parent.mkdir()
            shutil.copytree(package, external)
            external_manifest = yaml.safe_load((external / "manifest.yaml").read_text(encoding="utf-8"))
            external_manifest["template"]["version"] = "1.0.1"
            (external / "manifest.yaml").write_text(
                yaml.safe_dump(external_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            external_scripts = external.parent / "scripts"
            external_scripts.mkdir()
            (external_scripts / "validate_template.py").write_text(
                "from pathlib import Path\n"
                "Path(__file__).resolve().parent.parent.joinpath('MALICIOUS_VALIDATOR_EXECUTED').write_text('executed')\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )
            validated = self.run_tool("validate", "--package", external, "--json", root=root)
            self.assert_process_succeeded(validated)
            self.assertEqual(self.json_result(validated)["status"], "passed")
            self.assertFalse((external.parent / "MALICIOUS_VALIDATOR_EXECUTED").exists())
            canonical = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assert_process_succeeded(canonical)

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
                self.assert_process_succeeded(result)
                payload = self.json_result(result)
                self.assertEqual(payload["status"], "identity_only")
                self.assertFalse(payload["full_validation"])
                self.assertEqual(payload["errors"], [])

    def test_validate_fixture_invokes_real_owner_validator_and_captures_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            result = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assert_process_succeeded(result)
            payload = self.json_result(result)
            self.assertEqual(payload["status"], "passed")
            self.assertTrue(payload["full_validation"])
            self.assertEqual(payload["validator"]["exit_code"], 0)
            self.assertIn("fixture validator passed", payload["validator"]["stdout"])
            (package / "validator-fail").write_text("fail\n", encoding="utf-8")
            failed = self.run_tool("validate", "--package", package, "--json", root=root)
            self.assert_process_failed(failed)
            failed_payload = self.json_result(failed)
            self.assertEqual(failed_payload["validator"]["exit_code"], 7)
            self.assertIn("fixture validator failed", failed_payload["validator"]["stderr"])

    def test_external_validator_is_not_executed_for_validate_or_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            external_root = root / "external-workspace"
            external_package = external_root / "package" / "v1.0.1"
            external_package.parent.mkdir(parents=True)
            shutil.copytree(base, external_package)
            manifest_path = external_package / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["template"]["version"] = "1.0.1"
            manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            external_scripts = external_root / "scripts"
            external_scripts.mkdir()
            (external_scripts / "validate_template.py").write_text(
                "from pathlib import Path\n"
                "Path(__file__).resolve().parent.parent.joinpath('MALICIOUS_VALIDATOR_EXECUTED').write_text('executed')\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )

            validated = self.run_tool("validate", "--package", external_package, "--json", root=root)
            self.assert_process_succeeded(validated)
            payload = self.json_result(validated)
            self.assertEqual(payload["status"], "passed")
            self.assertNotIn("external-workspace", json.dumps(payload["validator"]["command"], ensure_ascii=False))
            self.assertFalse((external_root / "MALICIOUS_VALIDATOR_EXECUTED").exists())

            archived = self.run_tool(
                "archive", "--package", external_package, "--output-dir", root.parent / f"{root.name}-dist-external", "--json", root=root
            )
            self.assert_process_succeeded(archived)
            self.assertFalse((external_root / "MALICIOUS_VALIDATOR_EXECUTED").exists())

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
            self.assert_process_failed(result)
            payload = self.json_result(result)
            self.assertEqual(payload["status"], "failed")
            self.assertTrue(any("fingerprint mismatch" in error for error in payload["errors"]))
            self.assertIsNone(payload["validator"])

    def test_external_validation_uses_only_system_temp_and_leaves_canonical_tree_untouched(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            output = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", output, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            validated = self.run_tool("validate", "--package", output, "--json", root=root)
            self.assert_process_succeeded(validated)
            report = self.json_result(validated)
            self.assertEqual(report["validation_scope"], "isolated_temp")
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(before, after)
            self.assertFalse(any(".template-tool-validation-" in path.name for path in root.rglob("*")))

    def test_two_external_validations_can_run_concurrently_without_canonical_shadow(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            outputs = []
            for version in ("1.0.1", "1.0.2"):
                output = root / "work" / "template-packages" / "demo-template" / version
                result = self.run_tool(
                    "scaffold", "--base-package", base, "--version", version, "--output-dir", output, "--json", root=root
                )
                self.assert_process_succeeded(result)
                outputs.append(output)
            processes = [
                subprocess.Popen(
                    [str(PYTHON), str(TOOL), "--repo-root", str(root), "validate", "--package", str(output), "--json"],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                for output in outputs
            ]
            results = [process.communicate(timeout=120) for process in processes]
            for stdout, stderr in results:
                self.assertIn('"status": "passed"', stdout, stdout + stderr)
            self.assertFalse(any(".template-tool-validation-" in path.name for path in root.rglob("*")))

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
            self.assert_process_failed(result)
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
            self.assert_process_failed(result)
            payload = self.json_result(result)
            errors = "\n".join(error for item in payload["errors"] for error in item["errors"])
            self.assertIn("does not equal manifest version", errors)
            self.assertIn("template file does not exist", errors)
            self.assertIn("fingerprint.sha256 must be a 64-character", errors)
            self.assertIn("canonical-like package has no trusted Git-tracked owner validator", errors)

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
            self.assert_process_succeeded(result)
            report = self.json_result(result)
            self.assertTrue(report["promotable"])
            self.assertTrue(output.is_dir())
            self.assertTrue((workspace / "v1.0.0" / "manifest.yaml").is_file())
            self.assertFalse((output / "scaffold-report-lesson-plan-1.1.1.json").exists())
            self.assertTrue((workspace / "scaffold-report-lesson-plan-1.1.1.json").is_file())
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
            self.assert_process_succeeded(validated)
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
                "1.1.2",
                "--json",
            )
            self.assert_process_succeeded(generated_scaffold)
            generated_override = yaml.safe_load((generator_output / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(generated_override["generator"]["version"], "1.1.2")

    def test_scaffold_unsupported_minor_requires_opt_in_and_is_not_promotable(self) -> None:
        base = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0"
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            rejected = root / "reject" / "1.2.0"
            result = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.2.0", "--output-dir", rejected, "--json"
            )
            self.assert_process_failed(result)
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
            self.assert_process_succeeded(result)
            report = self.json_result(result)
            self.assertFalse(report["promotable"])
            self.assertEqual(report["reason"], "Template minor is not supported by the current generator contract.")

    def test_scaffold_requires_base_full_validation_before_creating_any_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, template = self.make_fixture_repo(root)
            (base / "validator-fail").write_text("fail\n", encoding="utf-8")
            output = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            before = sha256(template)
            failed = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", output, "--json", root=root
            )
            self.assert_process_failed(failed)
            self.assertIn("base package full validation failed", failed.stdout)
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())
            self.assertFalse(any(path.name.startswith("scaffold-report-") for path in root.rglob("*.json")))
            self.assertEqual(sha256(template), before)
            self.assertFalse(any(".stage" in path.name for path in root.rglob("*")))

    def test_scaffold_rejects_protected_report_paths_and_uses_unique_atomic_reports(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            output = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            protected = self.run_tool(
                "scaffold",
                "--base-package", base,
                "--version", "1.0.1",
                "--output-dir", output,
                "--report-path", base / "new-report.json",
                "--json",
                root=root,
            )
            self.assert_process_failed(protected)
            self.assertIn("scaffold report must be in the output package sibling directory", protected.stdout)
            first = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", output, "--json", root=root
            )
            self.assert_process_succeeded(first)
            output2 = root / "work" / "template-packages" / "demo-template" / "1.0.2"
            second = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.2", "--output-dir", output2, "--json", root=root
            )
            self.assert_process_succeeded(second)
            self.assertTrue((output.parent / "scaffold-report-demo-template-1.0.1.json").is_file())
            self.assertTrue((output2.parent / "scaffold-report-demo-template-1.0.2.json").is_file())
            failed_commit = self.run_tool(
                "scaffold",
                "--base-package", base,
                "--version", "1.0.3",
                "--output-dir", root / "work" / "template-packages" / "demo-template" / "1.0.3",
                "--json",
                root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_REPORT_COMMIT": "1"},
            )
            self.assert_process_failed(failed_commit)
            self.assertIn("injected scaffold report commit failure", failed_commit.stdout)
            self.assertFalse((root / "work" / "template-packages" / "demo-template" / "1.0.3").exists())

    def test_scaffold_report_must_be_output_sibling_and_never_source_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, template = self.make_fixture_repo(root)
            before = sha256(template)
            output_parent = root / "work" / "template-packages" / "demo-template"
            invalid_reports = [
                root / "report.json",
                root / "docs" / "report.json",
                root / "tools" / "report.json",
                root / "tests" / "report.json",
                skill / "scripts" / "report.json",
                output_parent / "1.0.1" / "report.json",
                output_parent / "1.0.2" / ".." / "other-dir" / "report.json",
                output_parent / "report.txt",
            ]
            for index, report in enumerate(invalid_reports, start=1):
                with self.subTest(report=report):
                    output = output_parent / f"1.0.{index}"
                    failed = self.run_tool(
                        "scaffold",
                        "--base-package", base,
                        "--version", f"1.0.{index}",
                        "--output-dir", output,
                        "--report-path", report,
                        "--json",
                        root=root,
                    )
                    self.assert_process_failed(failed)
                    self.assertIn("report", failed.stdout.lower())
                    self.assertFalse(output.exists())
                    self.assertEqual(sha256(template), before)
                    self.assertFalse(any(path.name.endswith(".stage") for path in output_parent.rglob("*")))

            allowed_output = output_parent / "1.0.20"
            allowed_report = output_parent / "scaffold-report-explicit.json"
            allowed = self.run_tool(
                "scaffold",
                "--base-package", base,
                "--version", "1.0.20",
                "--output-dir", allowed_output,
                "--report-path", allowed_report,
                "--json",
                root=root,
            )
            self.assert_process_succeeded(allowed)
            self.assertTrue(allowed_report.is_file())

    def test_scaffold_repo_workspace_is_closed_and_checked_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, template = self.make_fixture_repo(root)
            base_sha = sha256(template)
            validator_marker = root / "BASE_VALIDATOR_STARTED"
            invalid_outputs = [
                root / "1.0.1",
                root / "docs" / "1.0.1",
                root / "tools" / "1.0.1",
                root / "tests" / "1.0.1",
                root / ".github" / "1.0.1",
                skill / "scripts" / "1.0.1",
                skill / "assets" / "1.0.1",
                root / "work" / "1.0.1",
                root / "work" / "template-packages",
            ]
            for output in invalid_outputs:
                with self.subTest(output=output):
                    result = self.run_tool(
                        "scaffold", "--base-package", base, "--version", "1.0.1",
                        "--output-dir", output, "--json", root=root,
                    )
                    self.assert_process_failed(result)
                    self.assertFalse(output.exists())
                    self.assertFalse(output.is_symlink())
            self.assertEqual(sha256(template), base_sha)
            self.assertFalse(list(root.rglob("scaffold-report-*.json")))
            self.assertFalse(list(root.rglob("*.stage")))

            allowed = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            successful = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1",
                "--output-dir", allowed, "--json", root=root,
            )
            self.assert_process_succeeded(successful)
            self.assertTrue(allowed.is_dir())
            self.assertTrue((allowed.parent / "scaffold-report-demo-template-1.0.1.json").is_file())

            dry_output = root / "work" / "template-packages" / "dry-only" / "1.0.2"
            dry = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.2",
                "--output-dir", dry_output, "--dry-run", "--json", root=root,
            )
            self.assert_process_succeeded(dry)
            self.assertFalse(dry_output.exists())
            self.assertFalse(dry_output.parent.exists())

            escape_parent = root / "work" / "template-packages"
            escape_parent.mkdir(parents=True, exist_ok=True)
            docs = root / "docs"
            docs.mkdir(exist_ok=True)
            escape = escape_parent / "escape"
            try:
                escape.symlink_to(docs, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("the current platform cannot create symlinks")
            escaped = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.3",
                "--output-dir", escape / "1.0.3", "--dry-run", "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_BASE_VALIDATOR_MARKER": str(validator_marker)},
            )
            self.assert_process_failed(escaped)
            self.assertIn("scaffold output inside the repository must be below", escaped.stdout)
            self.assertFalse((docs / "1.0.3").exists())
            self.assertFalse(validator_marker.exists())

            external_root = root.parent / f"{root.name}-external-target"
            external_root.mkdir()
            try:
                internal_external = escape_parent / "internal-external-alias"
                internal_external.symlink_to(external_root, target_is_directory=True)
                escaped_external = self.run_tool(
                    "scaffold", "--base-package", base, "--version", "1.0.31",
                    "--output-dir", internal_external / "1.0.31", "--dry-run", "--json", root=root,
                    env={"TEMPLATE_TOOL_TEST_BASE_VALIDATOR_MARKER": str(validator_marker)},
                )
                self.assert_process_failed(escaped_external)
                self.assertIn("scaffold output symlink escapes the repository", escaped_external.stdout)
                self.assertFalse((external_root / "1.0.31").exists())
                self.assertFalse(validator_marker.exists())

                dangerous_links = {
                    "docs": root / "docs",
                    "work": root / "work" / "template-packages",
                    "canonical": base,
                }
                for index, (name, target) in enumerate(dangerous_links.items(), start=4):
                    link = external_root / f"repo-{name}-alias"
                    link.symlink_to(target, target_is_directory=True)
                    result = self.run_tool(
                        "scaffold", "--base-package", base, "--version", f"1.0.{index}",
                        "--output-dir", link / f"1.0.{index}", "--dry-run", "--json", root=root,
                        env={"TEMPLATE_TOOL_TEST_BASE_VALIDATOR_MARKER": str(validator_marker)},
                    )
                    self.assert_process_failed(result)
                    self.assertIn("external scaffold path resolves inside the repository", result.stdout)
                    self.assertFalse((target / f"1.0.{index}").exists())
                    self.assertFalse(validator_marker.exists())

                multi_target = external_root / "multi-target"
                multi_target.symlink_to(root, target_is_directory=True)
                multi_alias = external_root / "multi-alias"
                multi_alias.symlink_to(multi_target, target_is_directory=True)
                multi_result = self.run_tool(
                    "scaffold", "--base-package", base, "--version", "1.0.7",
                    "--output-dir", multi_alias / "1.0.7", "--dry-run", "--json", root=root,
                    env={"TEMPLATE_TOOL_TEST_BASE_VALIDATOR_MARKER": str(validator_marker)},
                )
                self.assert_process_failed(multi_result)
                self.assertIn("external scaffold path resolves inside the repository", multi_result.stdout)
                self.assertFalse((root / "1.0.7").exists())
                self.assertFalse(validator_marker.exists())

                report_alias = external_root / "repo-report-alias"
                report_alias.symlink_to(root / "docs", target_is_directory=True)
                report_result = self.run_tool(
                    "scaffold", "--base-package", base, "--version", "1.0.71",
                    "--output-dir", external_root / "report-boundary" / "demo-template" / "1.0.71",
                    "--report-path", report_alias / "report.json",
                    "--dry-run", "--json", root=root,
                    env={"TEMPLATE_TOOL_TEST_BASE_VALIDATOR_MARKER": str(validator_marker)},
                )
                self.assert_process_failed(report_result)
                self.assertIn("report must be in the output package sibling directory", report_result.stdout)
                self.assertFalse(validator_marker.exists())

                legal_output = external_root / "legal-work" / "demo-template" / "1.0.8"
                legal = self.run_tool(
                    "scaffold", "--base-package", base, "--version", "1.0.8",
                    "--output-dir", legal_output, "--json", root=root,
                )
                self.assert_process_succeeded(legal)
                self.assertTrue(legal_output.is_dir())
                self.assertTrue((legal_output.parent / "scaffold-report-demo-template-1.0.8.json").is_file())

                real_workspace = external_root / "real-workspace"
                real_workspace.mkdir()
                legal_alias = external_root / "legal-alias"
                legal_alias.symlink_to(real_workspace, target_is_directory=True)
                aliased_output = legal_alias / "demo-template" / "1.0.9"
                aliased = self.run_tool(
                    "scaffold", "--base-package", base, "--version", "1.0.9",
                    "--output-dir", aliased_output, "--json", root=root,
                )
                self.assert_process_succeeded(aliased)
                self.assertTrue((real_workspace / "demo-template" / "1.0.9").is_dir())
                self.assertTrue(
                    (real_workspace / "demo-template" / "scaffold-report-demo-template-1.0.9.json").is_file()
                )
            except (OSError, NotImplementedError):
                self.skipTest("the current platform cannot create directory symlinks")
            finally:
                shutil.rmtree(external_root, ignore_errors=True)

    def test_scaffold_generator_version_is_strict_ascii_semver(self) -> None:
        invalid = ("1.1.01", "01.1.1", "１.１.１", "v1.1.1", "latest", "")
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            for index, value in enumerate(invalid, start=1):
                with self.subTest(value=value):
                    output = root / "invalid" / f"1.0.{index}"
                    result = self.run_tool(
                        "scaffold",
                        "--base-package", base,
                        "--version", f"1.0.{index}",
                        "--output-dir", output,
                        "--generator-version", value,
                        "--json",
                        root=root,
                    )
                    self.assert_process_failed(result)
                    self.assertIn("semantic version", result.stdout)
                    self.assertFalse(output.exists())

    def test_scaffold_external_alias_keeps_dependency_in_resolved_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_dependent_fixture_repo(root)
            external_root = root.parent / f"{root.name}-dependency-external"
            external_root.mkdir()
            real_workspace = external_root / "real-workspace"
            real_workspace.mkdir()
            alias = external_root / "workspace-alias"
            try:
                alias.symlink_to(real_workspace, target_is_directory=True)
            except (OSError, NotImplementedError):
                shutil.rmtree(external_root, ignore_errors=True)
                self.skipTest("the current platform cannot create directory symlinks")
            try:
                output = alias / "demo-template" / "v1.1.1"
                result = self.run_tool(
                    "scaffold",
                    "--base-package", base,
                    "--version", "1.1.1",
                    "--output-dir", output,
                    "--json",
                    root=root,
                )
                self.assert_process_succeeded(result)
                workspace_package = real_workspace / "demo-template"
                self.assertTrue((workspace_package / "v1.0.0").is_dir())
                self.assertTrue((workspace_package / "v1.1.1").is_dir())
                self.assertTrue((workspace_package / "scaffold-report-demo-template-1.1.1.json").is_file())
            finally:
                shutil.rmtree(external_root, ignore_errors=True)

    def test_cli_preserves_lexical_repo_root_for_aliased_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            container = Path(directory)
            real_root = container / "real-repository"
            real_root.mkdir()
            _, base, _ = self.make_fixture_repo(real_root)
            alias = container / "repository-alias"
            try:
                alias.symlink_to(real_root, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("the current platform cannot create directory symlinks")

            scaffold_output = alias / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold",
                "--base-package",
                base,
                "--version",
                "1.0.1",
                "--output-dir",
                scaffold_output,
                "--json",
                root=alias,
            )
            self.assert_process_succeeded(scaffold)

            archive_output = alias / "dist" / "template-packages" / "aliased-root"
            archived = self.run_tool(
                "archive",
                "--package",
                base,
                "--output-dir",
                archive_output,
                "--json",
                root=alias,
            )
            self.assert_process_succeeded(archived)
            self.assertEqual(len(list(archive_output.glob("*.zip"))), 1)

    def test_scaffold_dry_run_and_overlap_do_not_mutate(self) -> None:
        base = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0"
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            output = Path(directory) / "dry" / "1.1.1"
            result = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.1.1", "--output-dir", output, "--dry-run", "--json"
            )
            self.assert_process_succeeded(result)
            self.assertTrue(self.json_result(result)["dry_run"])
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())
            overlap = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.1.1",
                "--output-dir", ROOT / "work" / "template-packages", "--json"
            )
            self.assert_process_failed(overlap)
            self.assertIn("below work/template-packages", overlap.stdout + overlap.stderr)

    def test_promote_success_and_target_exists_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            base_sha = sha256(base / "template.txt")
            dry_run = self.run_tool("promote", "--package", source, "--dry-run", "--json", root=root)
            self.assert_process_succeeded(dry_run)
            self.assertTrue(self.json_result(dry_run)["dry_run"])
            self.assertFalse((root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1").exists())
            self.assertEqual(sha256(base / "template.txt"), base_sha)
            promoted = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_succeeded(promoted)
            self.assertEqual(self.json_result(promoted)["repository_package_guard"], {
                "protected_roots": 1,
                "unchanged": True,
            })
            target = root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1"
            self.assertTrue(target.is_dir())
            self.assertTrue(source.is_dir())
            self.assertFalse(any(path.name.endswith(".stage") for path in target.parent.iterdir()))
            repeated = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_failed(repeated)
            self.assertIn("already exists", repeated.stdout + repeated.stderr)

    def test_promote_repository_validator_restores_other_package_mutation(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, other, source, target = self.prepare_multi_package_promotion(root)
            before = tree_inventory(skill / "assets" / "templates")
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_REPO_MUTATION": "other-change"},
            )
            self.assert_process_failed(failed)
            self.assertIn("repository package tree mutation detected", failed.stdout)
            self.assertEqual(tree_inventory(skill / "assets" / "templates"), before)
            self.assertTrue(other.is_dir())
            self.assertFalse(target.exists())
            self.assertFalse(any("stage" in path.name or "backup" in path.name for path in root.rglob("*")))
            self.assertFalse(any("repository-package-snapshots" in path.name for path in root.rglob("*")))

    def test_promote_repository_validator_restores_deleted_other_package_file(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, _, source, target = self.prepare_multi_package_promotion(root)
            before = tree_inventory(skill / "assets" / "templates")
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_REPO_MUTATION": "other-delete"},
            )
            self.assert_process_failed(failed)
            self.assertIn("removed", failed.stdout)
            self.assertEqual(tree_inventory(skill / "assets" / "templates"), before)
            self.assertFalse(target.exists())

    def test_promote_repository_validator_removes_added_other_package(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, _, source, target = self.prepare_multi_package_promotion(root)
            before = tree_inventory(skill / "assets" / "templates")
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_REPO_MUTATION": "other-add"},
            )
            self.assert_process_failed(failed)
            self.assertIn("added", failed.stdout)
            self.assertEqual(tree_inventory(skill / "assets" / "templates"), before)
            self.assertFalse((skill / "assets" / "templates" / "other-template" / "v9.9.9").exists())
            self.assertFalse(target.exists())

    def test_promote_repository_validator_restores_target_and_other_mutations(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, _, source, target = self.prepare_multi_package_promotion(root)
            before = tree_inventory(skill / "assets" / "templates")
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_REPO_MUTATION": "target-and-other"},
            )
            self.assert_process_failed(failed)
            self.assertIn("changed", failed.stdout)
            self.assertEqual(tree_inventory(skill / "assets" / "templates"), before)
            self.assertFalse(target.exists())

    def test_promote_repository_validator_nonzero_mutation_preserves_both_diagnostics(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, _, source, target = self.prepare_multi_package_promotion(root)
            before = tree_inventory(skill / "assets" / "templates")
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_REPO_MUTATION": "other-change-nonzero"},
            )
            self.assert_process_failed(failed)
            self.assertIn("repository package tree mutation detected", failed.stdout)
            self.assertIn("exit code 17", failed.stdout)
            self.assertEqual(tree_inventory(skill / "assets" / "templates"), before)
            self.assertFalse(target.exists())

    def test_promote_repository_package_restore_failure_reports_original_and_restore_errors(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, _, source, target = self.prepare_multi_package_promotion(root)
            before = tree_inventory(skill / "assets" / "templates")
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={
                    "TEMPLATE_TOOL_TEST_REPO_MUTATION": "other-change",
                    "TEMPLATE_TOOL_TEST_FAIL_REPO_PACKAGE_RESTORE": "1",
                },
            )
            self.assert_process_failed(failed)
            self.assertIn("repository package tree mutation detected", failed.stdout)
            self.assertIn("restore failure", failed.stdout)
            self.assertEqual(tree_inventory(skill / "assets" / "templates"), before)
            self.assertFalse(target.exists())

    def test_promote_repo_validator_failure_rolls_back_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            (root / "repo-fail").write_text("fail\n", encoding="utf-8")
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            promoted = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_failed(promoted)
            target = root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1"
            self.assertFalse(target.exists())
            self.assertFalse(any("stage" in path.name or "backup" in path.name for path in target.parent.iterdir()))

    def test_promote_uses_immutable_snapshot_when_source_changes_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            original = (source / "template.txt").read_bytes()
            original_tree = {
                path.relative_to(source).as_posix(): sha256(path)
                for path in source.rglob("*")
                if path.is_file()
            }
            promoted = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_MUTATE_SOURCE_AFTER_SNAPSHOT": "1"},
            )
            self.assert_process_succeeded(promoted)
            target = root / "技能工具" / "demo-skill" / "assets" / "templates" / "demo-template" / "v1.0.1"
            self.assertEqual((target / "template.txt").read_bytes(), original)
            target_tree = {
                path.relative_to(target).as_posix(): sha256(path)
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(target_tree, original_tree)
            self.assertNotEqual((source / "template.txt").read_bytes(), original)
            self.assertEqual(self.json_result(promoted)["target_validation"]["validation_scope"], "isolated_temp")

    def test_promote_rolls_back_when_target_validator_mutates_target_after_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            target = skill / "assets" / "templates" / "demo-template" / "v1.0.1"
            (skill / "scripts" / "validate_template.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "manifest = Path(sys.argv[sys.argv.index('--manifest') + 1])\n"
                f"target = Path(r'{target}')\n"
                "if target.exists() and manifest.parent.name == 'v1.0.1':\n"
                "    (target / 'validator-output.txt').write_text('unexpected\\n', encoding='utf-8')\n"
                "print('fixture validator passed')\n",
                encoding="utf-8",
            )
            before = sha256(base / "template.txt")
            failed = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_failed(failed)
            self.assertIn("target validation changed immutable promotion content", failed.stdout)
            self.assertFalse(target.exists())
            self.assertEqual(sha256(base / "template.txt"), before)
            self.assertFalse(any(path.name.endswith(".stage") for path in target.parent.iterdir()))

    def test_promote_rolls_back_when_repository_validator_mutates_target_after_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            (root / "tests" / "validate_template_packages.py").write_text(
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "target = next(root.glob('**/assets/templates/demo-template/v1.0.1'))\n"
                "(target / 'repo-output.txt').write_text('unexpected\\n', encoding='utf-8')\n"
                "print('repository validator passed')\n",
                encoding="utf-8",
            )
            before = sha256(base / "template.txt")
            failed = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_failed(failed)
            self.assertIn("repository package tree mutation detected", failed.stdout)
            target = skill / "assets" / "templates" / "demo-template" / "v1.0.1"
            self.assertFalse(target.exists())
            self.assertEqual(sha256(base / "template.txt"), before)
            self.assertFalse(any(path.name.endswith(".stage") for path in target.parent.iterdir()))

    def test_promote_canonical_only_failure_is_caught_after_stage_and_target_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            target = skill / "assets" / "templates" / "demo-template" / "v1.0.1"
            (skill / "scripts" / "validate_template.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                f"target = Path(r'{target}')\n"
                "if target.exists() and Path(sys.argv[sys.argv.index('--manifest') + 1]).parent.name == 'v1.0.1':\n"
                "    print('canonical target validator failed', file=sys.stderr)\n"
                "    raise SystemExit(11)\n"
                "print('fixture validator passed')\n",
                encoding="utf-8",
            )
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            before = sha256(base / "template.txt")
            failed = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_failed(failed)
            self.assertIn("final canonical target validation failed", failed.stdout)
            self.assertFalse(target.exists())
            self.assertEqual(sha256(base / "template.txt"), before)
            self.assertFalse(any(path.name.endswith(".stage") for path in target.parent.iterdir()))

    def test_promote_reports_double_error_when_target_rollback_is_injected_to_fail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            (root / "repo-fail").write_text("fail\n", encoding="utf-8")
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            failed = self.run_tool(
                "promote", "--package", source, "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_ROLLBACK": "1"},
            )
            self.assert_process_failed(failed)
            self.assertIn("repository-wide validator failed", failed.stdout)
            self.assertIn("target rollback failed", failed.stdout)

    def test_promote_rejects_unsupported_minor_and_validator_failure_without_install(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            unsupported = root / "work" / "template-packages" / "demo-template" / "1.1.0"
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
            self.assert_process_succeeded(scaffold)
            promoted = self.run_tool("promote", "--package", unsupported, "--json", root=root)
            self.assert_process_failed(promoted)
            self.assertFalse((skill / "assets" / "templates" / "demo-template" / "1.1.0").exists())

            external_root = Path(tempfile.mkdtemp(prefix="模板工具-外部工作包-"))
            try:
                valid_patch = external_root / "demo-template" / "1.0.1"
                scaffold = self.run_tool(
                    "scaffold", "--base-package", base, "--version", "1.0.1",
                    "--output-dir", valid_patch, "--json", root=root
                )
                self.assert_process_succeeded(scaffold)
                (valid_patch / "validator-fail").write_text("fail\n", encoding="utf-8")
                failed = self.run_tool("promote", "--package", valid_patch, "--json", root=root)
                self.assert_process_failed(failed)
                self.assertFalse((skill / "assets" / "templates" / "demo-template" / "v1.0.1").exists())
            finally:
                shutil.rmtree(external_root, ignore_errors=True)

    def test_archive_contains_dependency_closure_and_is_valid_after_extraction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_dependent_fixture_repo(root)
            first_dir = root / "dist" / "template-packages" / "dist-a"
            second_dir = root / "dist" / "template-packages" / "dist-b"
            first = self.run_tool("archive", "--package", package, "--output-dir", first_dir, "--json", root=root)
            second = self.run_tool("archive", "--package", package, "--output-dir", second_dir, "--json", root=root)
            self.assert_process_succeeded(first)
            self.assert_process_succeeded(second)
            first_payload = self.json_result(first)
            second_payload = self.json_result(second)
            self.assertEqual(first_payload["archive_sha256"], second_payload["archive_sha256"])
            archive_path = first_dir / "demo-template-1.1.0.zip"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("demo-template/v1.0.0/manifest.yaml", names)
                self.assertIn("demo-template/v1.1.0/manifest.yaml", names)
                self.assertEqual(names, sorted(names, key=lambda value: (value.casefold(), value)))
            metadata_path = first_dir / "demo-template-1.1.0.metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["entry_package"], "demo-template/v1.1.0")
            self.assertEqual({item["version"] for item in metadata["packages"]}, {"1.0.0", "1.1.0"})
            self.assertFalse((first_dir / "demo-template-1.1.0.zip.json").exists())

    def test_archive_rejects_missing_bad_and_cyclic_dependencies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_dependent_fixture_repo(root)
            base = package.parent / "v1.0.0"
            (base / "manifest.yaml").unlink()
            missing = self.run_tool("archive", "--package", package, "--output-dir", root / "dist" / "template-packages" / "missing-dist", "--json", root=root)
            self.assert_process_failed(missing)
            self.assertIn("dependency", missing.stdout)

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_dependent_fixture_repo(root)
            base = package.parent / "v1.0.0"
            manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
            manifest["fingerprint"]["sha256"] = "0" * 64
            manifest["fingerprint"]["value"] = "0" * 64
            (base / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            bad = self.run_tool("archive", "--package", package, "--output-dir", root / "dist" / "template-packages" / "bad-dist", "--json", root=root)
            self.assert_process_failed(bad)
            self.assertIn("fingerprint", bad.stdout)

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_dependent_fixture_repo(root)
            base = package.parent / "v1.0.0"
            manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
            manifest["template"]["base_manifest"] = "../v1.1.0/manifest.yaml"
            manifest["template"]["base_template"] = "../v1.1.0/template.txt"
            (base / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            cycle = self.run_tool("archive", "--package", package, "--output-dir", root / "dist" / "template-packages" / "cycle-dist", "--json", root=root)
            self.assert_process_failed(cycle)
            self.assertIn("cycle", cycle.stdout)

    def test_archive_rejects_portability_collisions_and_commit_failure_cleans_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            from tools.template_tooling.archive import _assert_unique_portable_names, _validate_archive_name

            for names in (["A.txt", "a.txt"], ["A\u030a.txt", "Å.txt"], ["CON.txt"], ["trailing."]):
                with self.subTest(names=names):
                    with self.assertRaises(Exception):
                        _assert_unique_portable_names(list(names))
            self.assertEqual(_validate_archive_name("模板/合法.txt"), "模板/合法.txt")
            failed = self.run_tool(
                "archive", "--package", package, "--output-dir", root / "dist" / "template-packages" / "commit-failure", "--json", root=root,
                env={"TEMPLATE_TOOL_TEST_FAIL_ARCHIVE_COMMIT_STEP": "2"},
            )
            self.assert_process_failed(failed)
            output = root / "dist" / "template-packages" / "commit-failure"
            self.assertFalse((output / "demo-template-1.0.0.zip").exists())
            self.assertFalse((output / "demo-template-1.0.0.zip.sha256").exists())
            self.assertFalse((output / "demo-template-1.0.0.metadata.json").exists())

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
            first_dir = root / "dist" / "template-packages" / "dist-a"
            second_dir = root / "dist" / "template-packages" / "dist-b"
            first = self.run_tool("archive", "--package", package, "--output-dir", first_dir, "--json", root=root)
            second = self.run_tool("archive", "--package", package, "--output-dir", second_dir, "--json", root=root)
            self.assert_process_succeeded(first)
            self.assert_process_succeeded(second)
            first_payload = self.json_result(first)
            second_payload = self.json_result(second)
            self.assertEqual(first_payload["archive_sha256"], second_payload["archive_sha256"])
            archive_path = first_dir / "demo-template-1.0.0.zip"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, [
                    "demo-template/v1.0.0/CHANGELOG.md",
                    "demo-template/v1.0.0/manifest.yaml",
                    "demo-template/v1.0.0/template.txt",
                ])
                self.assertFalse(any("qa" in name or "stage" in name for name in names))
                self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
            sidecar = (first_dir / "demo-template-1.0.0.zip.sha256").read_text(encoding="ascii")
            self.assertIn(first_payload["archive_sha256"], sidecar)
            metadata = json.loads((first_dir / "demo-template-1.0.0.metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["archive_sha256"], first_payload["archive_sha256"])
            self.assertEqual(metadata["template_sha256"], sha256(package / "template.txt"))

    def test_archive_rejects_overlap_tampering_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, template = self.make_fixture_repo(root)
            overlap = self.run_tool("archive", "--package", package, "--output-dir", package / "dist", "--json", root=root)
            self.assert_process_failed(overlap)
            self.assertIn("repository archive output", overlap.stdout + overlap.stderr)
            template.write_text("tampered\n", encoding="utf-8")
            tampered = self.run_tool("archive", "--package", package, "--output-dir", root / "dist" / "template-packages", "--json", root=root)
            self.assert_process_failed(tampered)
            self.assertIn("fingerprint mismatch", tampered.stdout + tampered.stderr)

            _, package, _ = self.make_fixture_repo(root, template_id="symlink-template")
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            link = package / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("the current Windows account cannot create symlinks")
            linked = self.run_tool(
                "archive", "--package", package,
                "--output-dir", root / "dist" / "template-packages" / "link-output",
                "--json", root=root,
            )
            self.assert_process_failed(linked)
            self.assertIn("symlink", linked.stdout + linked.stderr)

    def test_archive_dry_run_does_not_create_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, _ = self.make_fixture_repo(root)
            output = root / "dist" / "template-packages"
            result = self.run_tool("archive", "--package", package, "--output-dir", output, "--dry-run", "--json", root=root)
            self.assert_process_succeeded(result)
            self.assertTrue(self.json_result(result)["dry_run"])
            self.assertFalse(output.exists())

    def test_archive_rejects_protected_repository_output_paths_before_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, template = self.make_fixture_repo(root)
            marker = root / "FULL_VALIDATOR_STARTED"
            (package / "validator-start-marker.txt").write_text(str(marker), encoding="utf-8")
            protected = [
                root,
                root / "tools",
                root / "tests",
                root / ".github",
                root / "docs",
                skill / "scripts",
                skill / "schemas",
                skill / "assets",
                skill / "assets" / "templates",
                root / "work" / "template-packages",
                root / "dist",
            ]
            before = sha256(template)
            for output in protected:
                with self.subTest(output=output):
                    result = self.run_tool(
                        "archive", "--package", package, "--output-dir", output, "--dry-run", "--json", root=root
                    )
                    self.assert_process_failed(result)
                    self.assertIn("dist/template-packages", result.stdout)
                    self.assertFalse(marker.exists())
                    self.assertEqual(sha256(template), before)
                    self.assertFalse(list(root.rglob("*.stage")))
                    self.assertFalse(list(root.rglob("*.backup")))

            for output in (
                root / "dist" / "template-packages",
                root / "dist" / "template-packages" / "custom-subdir",
            ):
                with self.subTest(allowed_output=output):
                    result = self.run_tool(
                        "archive", "--package", package, "--output-dir", output, "--dry-run", "--json", root=root
                    )
                    self.assert_process_succeeded(result)
                    self.assertTrue(self.json_result(result)["dry_run"])
                    marker.unlink()
                    self.assertFalse(output.exists())

    def test_archive_rejects_repository_and_external_symlink_escapes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, package, _ = self.make_fixture_repo(root)
            marker = root / "FULL_VALIDATOR_STARTED"
            (package / "validator-start-marker.txt").write_text(str(marker), encoding="utf-8")
            allowed_root = root / "dist" / "template-packages"
            allowed_root.mkdir(parents=True)
            external_root = root.parent / f"{root.name}-archive-links"
            external_root.mkdir()
            outside_target = external_root / "outside-target"
            outside_target.mkdir()
            safe_target = external_root / "external-safe-output"
            safe_target.mkdir()
            links = {
                "repo-to-protected": (allowed_root / "repo-to-protected", root / "tools"),
                "external-to-repo": (external_root / "external-to-repo", root / "tests"),
                "repo-to-external": (allowed_root / "repo-to-external", outside_target),
                "external-to-external": (external_root / "external-to-external", safe_target),
            }
            try:
                for link, target in links.values():
                    try:
                        link.symlink_to(target, target_is_directory=True)
                    except (OSError, NotImplementedError):
                        self.skipTest("the current platform cannot create directory symlinks")

                rejected = (
                    links["repo-to-protected"][0] / "archive-output",
                    links["external-to-repo"][0] / "archive-output",
                    links["repo-to-external"][0] / "archive-output",
                )
                for output in rejected:
                    with self.subTest(rejected_output=output):
                        result = self.run_tool(
                            "archive", "--package", package, "--output-dir", output, "--dry-run", "--json", root=root
                        )
                        self.assert_process_failed(result)
                        self.assertFalse(marker.exists())

                allowed = self.run_tool(
                    "archive", "--package", package,
                    "--output-dir", links["external-to-external"][0] / "archive-output",
                    "--dry-run", "--json", root=root,
                )
                self.assert_process_succeeded(allowed)
                self.assertTrue(self.json_result(allowed)["dry_run"])
                self.assertTrue(marker.exists())
                marker.unlink()
            finally:
                shutil.rmtree(external_root, ignore_errors=True)

    def test_archive_rejects_resolved_overlap_with_external_package_closure(self) -> None:
        from tools.template_tooling.paths import tree_inventory

        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, internal_package, _ = self.make_dependent_fixture_repo(root)
            source_root = root.parent / f"{root.name}-archive-resolved-source"
            external_links = root.parent / f"{root.name}-archive-resolved-links"
            safe_target = root.parent / f"{root.name}-archive-resolved-safe"
            shutil.copytree(internal_package.parent, source_root / internal_package.parent.name)
            package = source_root / internal_package.parent.name / internal_package.name
            dependency = package.parent / "v1.0.0"
            marker = root / "FULL_VALIDATOR_STARTED"
            (package / "validator-start-marker.txt").write_text(str(marker), encoding="utf-8")
            before = tree_inventory(source_root)
            external_links.mkdir()
            safe_target.mkdir()
            links = {
                "entry": external_links / "entry-package-link",
                "dependency": external_links / "dependency-link",
                "ancestor": external_links / "package-ancestor-link",
                "multi-hop": external_links / "multi-hop-a",
                "multi-hop-target": external_links / "multi-hop-b",
                "safe": external_links / "safe-output-link",
            }
            try:
                try:
                    links["entry"].symlink_to(package, target_is_directory=True)
                    links["dependency"].symlink_to(dependency, target_is_directory=True)
                    links["ancestor"].symlink_to(package.parent, target_is_directory=True)
                    links["multi-hop-target"].symlink_to(dependency, target_is_directory=True)
                    links["multi-hop"].symlink_to(links["multi-hop-target"], target_is_directory=True)
                    links["safe"].symlink_to(safe_target, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("the current platform cannot create directory symlinks")

                rejected = (
                    ("lexical package inside", package / "lexical-output"),
                    ("lexical package equal", package),
                    ("resolved entry package", links["entry"] / "generated"),
                    ("resolved dependency", links["dependency"] / "generated"),
                    ("package ancestor", links["ancestor"]),
                    ("multilevel dependency", links["multi-hop"] / "generated"),
                )
                archive_name = "demo-template-1.1.0.zip"
                for label, output in rejected:
                    with self.subTest(overlap=label):
                        result = self.run_tool(
                            "archive", "--package", package, "--output-dir", output, "--json", root=root
                        )
                        self.assert_process_failed(result)
                        self.assertIn("overlap", result.stdout + result.stderr)
                        self.assertFalse(marker.exists())
                        self.assertEqual(tree_inventory(source_root), before)
                        resolved_output = output.resolve(strict=False)
                        self.assertFalse((resolved_output / archive_name).exists())
                        self.assertFalse((resolved_output / f"{archive_name}.sha256").exists())
                        self.assertFalse((resolved_output / "demo-template-1.1.0.metadata.json").exists())
                        self.assertFalse(list(source_root.rglob("*.stage")))
                        self.assertFalse(list(source_root.rglob("*.sidecar")))
                        self.assertFalse(list(source_root.rglob("*.metadata")))

                safe = self.run_tool(
                    "archive", "--package", package, "--output-dir", links["safe"], "--json", root=root
                )
                self.assert_process_succeeded(safe)
                safe_payload = self.json_result(safe)
                archive_path = safe_target / archive_name
                sidecar_path = safe_target / f"{archive_name}.sha256"
                metadata_path = safe_target / "demo-template-1.1.0.metadata.json"
                self.assertTrue(archive_path.is_file())
                self.assertTrue(sidecar_path.is_file())
                self.assertTrue(metadata_path.is_file())
                cli_sha = safe_payload["archive_sha256"]
                sidecar_sha = sidecar_path.read_text(encoding="ascii").split()[0]
                metadata_sha = json.loads(metadata_path.read_text(encoding="utf-8"))["archive_sha256"]
                actual_sha = sha256(archive_path)
                self.assertEqual({cli_sha, sidecar_sha, metadata_sha, actual_sha}, {actual_sha})
                self.assertTrue(marker.exists())
            finally:
                shutil.rmtree(source_root, ignore_errors=True)
                shutil.rmtree(external_links, ignore_errors=True)
                shutil.rmtree(safe_target, ignore_errors=True)

    def test_archive_unsafe_output_fails_before_full_validator_and_file_creation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, package, template = self.make_fixture_repo(root)
            marker = root / "FULL_VALIDATOR_STARTED"
            (package / "validator-start-marker.txt").write_text(str(marker), encoding="utf-8")
            output = root / "tools"
            before = sha256(template)
            result = self.run_tool("archive", "--package", package, "--output-dir", output, "--json", root=root)
            self.assert_process_failed(result)
            self.assertIn("repository archive output", result.stdout)
            self.assertFalse(marker.exists())
            self.assertFalse((output / "demo-template-1.0.0.zip").exists())
            self.assertFalse((output / "demo-template-1.0.0.zip.sha256").exists())
            self.assertFalse((output / "demo-template-1.0.0.metadata.json").exists())
            self.assertEqual(sha256(template), before)

    def test_real_lesson_and_gradebook_archive_sha_are_cross_checked_four_ways(self) -> None:
        packages = (
            (
                "lesson-plan",
                ROOT / "教案生成器" / "lesson-plan-docx-generator" / "assets" / "templates" / "lesson-plan" / "v1.1.0",
                "lesson-plan-1.1.0",
            ),
            (
                "course-gradebook",
                ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "assets" / "templates" / "course-gradebook" / "v1.1.0",
                "course-gradebook-1.1.0",
            ),
        )
        with tempfile.TemporaryDirectory(prefix="template-archive-sha-") as directory:
            root = Path(directory)
            for template_id, package, stem in packages:
                with self.subTest(template_id=template_id):
                    shas: list[str] = []
                    for index in (1, 2):
                        output = root / f"{template_id}-{index}"
                        result = self.run_tool(
                            "archive", "--package", package, "--output-dir", output, "--json", root=ROOT
                        )
                        self.assert_process_succeeded(result)
                        payload = self.json_result(result)
                        archive_path = output / f"{stem}.zip"
                        sidecar_path = output / f"{stem}.zip.sha256"
                        metadata_path = output / f"{stem}.metadata.json"
                        cli_sha = payload["archive_sha256"]
                        sidecar_sha = sidecar_path.read_text(encoding="ascii").split()[0]
                        metadata_sha = json.loads(metadata_path.read_text(encoding="utf-8"))["archive_sha256"]
                        actual_sha = sha256(archive_path)
                        for value in (cli_sha, sidecar_sha, metadata_sha, actual_sha):
                            self.assertIsInstance(value, str)
                            self.assertRegex(value, r"^[0-9A-F]{64}$")
                        self.assertEqual(cli_sha, sidecar_sha)
                        self.assertEqual(cli_sha, metadata_sha)
                        self.assertEqual(cli_sha, actual_sha)
                        shas.append(cli_sha)
                    self.assertEqual(shas[0], shas[1])

    def test_repository_validator_reports_complete_validator_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            skill, _, _ = self.make_fixture_repo(root)
            (skill / "scripts" / "validate_template.py").write_text(
                "import sys\n"
                "print('specific validator stdout diagnostic')\n"
                "print('specific validator stderr diagnostic', file=sys.stderr)\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            failed = self.run_repo_validator(root)
            self.assert_process_failed(failed)
            combined = failed.stdout + failed.stderr
            self.assertIn("demo-template 1.0.0", combined)
            self.assertIn("validator exit_code: 7", combined)
            self.assertIn("specific validator stdout diagnostic", combined)
            self.assertIn("specific validator stderr diagnostic", combined)
            self.assertIn("validation_scope: isolated_temp", combined)

    def test_promote_preserves_repository_validator_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="模板工具-") as directory:
            root = Path(directory)
            _, base, _ = self.make_fixture_repo(root)
            self.make_repo_validator(root)
            source = root / "work" / "template-packages" / "demo-template" / "1.0.1"
            scaffold = self.run_tool(
                "scaffold", "--base-package", base, "--version", "1.0.1", "--output-dir", source, "--json", root=root
            )
            self.assert_process_succeeded(scaffold)
            (root / "tests" / "validate_template_packages.py").write_text(
                "import sys\n"
                "print('specific repository stdout diagnostic')\n"
                "print('specific repository stderr diagnostic', file=sys.stderr)\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            failed = self.run_tool("promote", "--package", source, "--json", root=root)
            self.assert_process_failed(failed)
            self.assertIn("exit code 7", failed.stdout)
            self.assertIn("specific repository stdout diagnostic", failed.stdout)
            self.assertIn("specific repository stderr diagnostic", failed.stdout)


if __name__ == "__main__":
    unittest.main()
