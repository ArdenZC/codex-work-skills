"""RC-01 compatibility and installed-copy contracts; synthetic teaching inputs only."""
import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from jsonschema import Draft202012Validator
from unittest.mock import patch

import tests.test_lesson_pipeline as pipeline_tests
from tests.test_lesson_lifecycle_contracts import _content, _write_json
from tests.test_lesson_content_v22 import make_v22_payload, DB_SPECS
from tests.test_lesson_content_v23 import _bind_v23, _base_payload, _hybrid_8
from tests.test_lesson_skill_hardening import install_adapters, lesson_install, LESSON
from lesson_lifecycle_applicability import lesson_lifecycle_applicability, require_lesson_lifecycle_applicable
from lifecycle_digest import LifecycleContractError, schema_errors
from package_common import validate_content_v2_input
import run_lesson_pipeline as pipeline
import acceptance_v3


def practice_content(*, workorders=False):
    content = make_v22_payload(course="数据库应用基础", major="软件技术", audience="高职二年级",
        theory_hours=0, practice_hours=4, lesson_count=0, specs=DB_SPECS)
    _bind_v23(content, mode="practice_only", theory_hours=0, practice_hours=4, workorders=workorders)
    content["authoring_provenance"]["mode"] = "agent"
    return content


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class LessonApplicabilityTests(unittest.TestCase):
    def test_formal_practice_only_content_stays_valid(self):
        content = practice_content()
        validate_content_v2_input(content)
        self.assertEqual(lesson_lifecycle_applicability(content), {
            "status": "NOT_APPLICABLE_TO_LESSON_LIFECYCLE", "lesson_count": 0, "content_contract_version": "2.3"})

    def test_invalid_content_cannot_be_classified_as_merely_inapplicable(self):
        content = practice_content()
        content["total_hours"] = "invalid"
        with self.assertRaises(ValueError) as error:
            lesson_lifecycle_applicability(content)
        self.assertNotIn("outside the canonical Lesson lifecycle", str(error.exception))

    def reject_zero(self, mode):
        h = pipeline_tests.PipelineTests(); h.setUp(); self.addCleanup(h.doCleanups)
        if mode == "PREVIEW": h.preview_init()
        else: h.prepared()
        _write_json(h.content_path, practice_content())
        before = tree_bytes(h.folder)
        with self.assertRaisesRegex(LifecycleContractError, "Content is valid but contains zero Lessons") as error:
            h.call("bind-content", content=h.content_path)
        self.assertIn("outside the canonical Lesson lifecycle", str(error.exception))
        self.assertIn("Practice Task / WorkOrder", str(error.exception))
        self.assertEqual(tree_bytes(h.folder), before)
        run = h.call("status")
        self.assertNotIn("content", run["bindings"])
        self.assertNotEqual(run["state"]["current_state"], "AUTHORING_COMPLETE")
        self.assertFalse(any(p.suffix == ".docx" or "teacher" in p.name for p in h.folder.rglob("*")))

    def test_production_rejects_zero_before_binding_or_transition(self): self.reject_zero("PRODUCTION")
    def test_preview_rejects_zero_before_binding_or_transition(self): self.reject_zero("PREVIEW")

    def test_normal_lesson_bearing_modes_and_content_22_remain_applicable(self):
        modes = [(_content("2.2"), "2.2")]
        for mode, theory, practice in (("theory_only", 2, 0), ("split_lessons", 2, 2), ("integrated_lessons", 1, 1)):
            content = _base_payload(theory_hours=2, lesson_count=1)
            if mode == "integrated_lessons":
                content["lessons"][0].update(lesson_type="integrated", theory_hours=1, practice_hours=1)
            modes.append((_bind_v23(content, mode=mode, theory_hours=theory, practice_hours=practice), "2.3"))
        modes.append((_hybrid_8(), "2.3"))
        for content, version in modes:
            with self.subTest(mode=content["delivery_plan"]["mode"], version=version):
                content["authoring_provenance"]["mode"] = "agent"
                result = require_lesson_lifecycle_applicable(content)
                self.assertEqual(result["status"], "APPLICABLE")
                self.assertEqual(result["lesson_count"], len(content["lessons"]))
                self.assertEqual(result["content_contract_version"], version)

    def test_practice_only_handoff_is_valid_without_fake_lessons(self):
        content = practice_content(workorders=True)
        validate_content_v2_input(content)
        handoff = content["practice_task_contract"]
        Draft202012Validator(json.loads((LESSON.parents[1] / install_adapters.SHARED_SCHEMA).read_text(encoding="utf-8"))).validate(handoff)
        self.assertEqual(content["lessons"], [])
        self.assertEqual(len(handoff["tasks"]), 2)
        self.assertTrue(all(task["lesson_ids"] == [] for task in handoff["tasks"]))
        self.assertEqual(lesson_lifecycle_applicability(content)["status"], "NOT_APPLICABLE_TO_LESSON_LIFECYCLE")

    def test_lesson_bearing_modes_bind_and_advance_canonical_pipeline(self):
        for mode in ("theory_only", "integrated_lessons", "hybrid", "split_lessons"):
            with self.subTest(mode=mode):
                h = pipeline_tests.PipelineTests(); h.setUp(); self.addCleanup(h.doCleanups)
                h.prepared()
                content = _content()
                if mode in {"integrated_lessons", "hybrid"}:
                    content["lessons"][0].update(lesson_type="integrated", theory_hours=1, practice_hours=1)
                    theory, practice = 1, 1
                else: theory, practice = 2, 2 if mode == "split_lessons" else 0
                _bind_v23(content, mode=mode, theory_hours=theory, practice_hours=practice)
                _write_json(h.content_path, content)
                run = h.call("bind-content", content=h.content_path)
                self.assertEqual(run["state"]["current_state"], "AUTHORING_COMPLETE")
                self.assertIn("content", run["bindings"])
                self.assertEqual(h.call("status"), run)

    def test_acceptance_defense_still_rejects_a_noncanonical_zero_lesson_caller(self):
        h = pipeline_tests.PipelineTests(); h.setUp(); self.addCleanup(h.doCleanups)
        h.prepared(); _write_json(h.content_path, practice_content())
        run = h.call("status")
        pipeline.bind(run, "content", h.content_path)
        pipeline.advance(run, "AUTHORING_COMPLETE", ("content_sha256", "content"))
        run["run_fingerprint"] = pipeline.envelope_fingerprint(run)
        self.assertEqual(acceptance_v3.evaluate(run)["final_status"], "FAILED")
        # Independently exercise Acceptance's own defense, even if a noncanonical
        # caller has omitted the pipeline's applicability validation.
        with patch.object(pipeline, "validate_run"), patch.object(pipeline, "validate_run_upstream"):
            report = acceptance_v3.evaluate(run)
        self.assertEqual(report["final_status"], "FAILED")
        self.assertIn("zero-Lesson", report["gate_matrix"][0]["notes"])
        self.assertEqual(schema_errors(report, "lesson-acceptance-v3.schema.json"), [])


class InstalledLifecycleTests(unittest.TestCase):
    def copy_source(self, root):
        source = root / "source"
        shutil.copytree(LESSON, source, ignore=install_adapters.ignore_patterns)
        shared = source / install_adapters.SHARED_SCHEMA
        shared.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LESSON.parents[1] / install_adapters.SHARED_SCHEMA, shared)
        return source

    def install_full(self, source, target):
        with redirect_stdout(io.StringIO()):
            install_adapters.install(source, target, adapters=["all"], copy_engine=True)
        return target / install_adapters.ENGINE_NAME

    def test_floor_covers_actual_local_production_import_and_schema_closure(self):
        pending = ["run_lesson_pipeline"]; seen = set(); dependencies = set()
        while pending:
            name = pending.pop()
            if name in seen: continue
            seen.add(name)
            path = LESSON / "scripts" / (name + ".py")
            dependencies.add(Path("scripts") / path.name)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [row.name for row in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
                for imported in names:
                    module = imported.split(".")[0]
                    if (LESSON / "scripts" / (module + ".py")).is_file(): pending.append(module)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(".schema.json"):
                    relative = Path("schemas") / node.value
                    if (LESSON / relative).is_file(): dependencies.add(relative)
        self.assertLessEqual(dependencies, set(install_adapters.CRITICAL_PRODUCTION_SOURCE_FILES))
        self.assertTrue(all(p.parts[0] not in {"examples", "tests"} for p in install_adapters.CRITICAL_PRODUCTION_SOURCE_FILES))

    def test_every_lifecycle_critical_file_missing_fails_before_mutation(self):
        floor = install_adapters.CRITICAL_LIFECYCLE_SOURCE_FILES
        self.assertEqual(len(floor), len(set(floor)))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.copy_source(root)
            for relative in floor:
                original = (source / relative).read_bytes()
                (source / relative).unlink()
                try:
                    for entrypoint in ("adapters", "skill"):
                        with self.subTest(file=str(relative), entrypoint=entrypoint):
                            target = root / entrypoint
                            target.mkdir(exist_ok=True)
                            (target / "AGENTS.md").write_bytes(b"existing project data\n")
                            before = tree_bytes(target)
                            with self.assertRaises(FileNotFoundError) as error, redirect_stdout(io.StringIO()):
                                if entrypoint == "adapters":
                                    install_adapters.install(source, target, copy_engine=True)
                                else: lesson_install.install(source, target)
                            self.assertIn(relative.as_posix(), str(error.exception).replace("\\", "/"))
                            self.assertEqual(tree_bytes(target), before)
                            self.assertEqual({p.name for p in target.iterdir()}, {"AGENTS.md"})
                finally: (source / relative).write_bytes(original)
                print("RC-01 critical floor missing-file PASS: " + relative.as_posix() + " (both installers)")

    def test_symlinked_lifecycle_runtime_schema_and_parent_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.copy_source(root)
            for relative in (Path("scripts/acceptance_v3.py"), Path("schemas/pipeline-state.schema.json")):
                with self.subTest(file=str(relative)):
                    path = source / relative; original = path.read_bytes(); backing = root / (path.name + ".real")
                    backing.write_bytes(original); path.unlink()
                    try:
                        try: path.symlink_to(backing)
                        except OSError as error: self.skipTest("directory/file symlinks unavailable: " + str(error))
                        with self.assertRaises(FileNotFoundError): self.install_full(source, root / "project")
                        self.assertFalse((root / "project").exists())
                    finally: path.unlink(); path.write_bytes(original)
            alias = root / "alias"
            alias.symlink_to(source, target_is_directory=True)
            self.assertFalse(install_adapters._is_real_source_file(alias / "scripts", Path("acceptance_v3.py")))

    def test_complete_installed_copy_loads_lifecycle_without_original_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.copy_source(root)
            engine = self.install_full(source, root / "project")
            shutil.rmtree(source)
            env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"}}
            result = subprocess.run([sys.executable, "-E", "-s", "-B", str(engine / "scripts/run_lesson_pipeline.py"), "--help"], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("finalize-acceptance", result.stdout)
            script = '''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/'scripts'))
from jsonschema import Draft202012Validator
import install_adapters
for relative in install_adapters.CRITICAL_LIFECYCLE_RUNTIME_FILES:
 module=importlib.import_module(relative.stem)
 assert Path(module.__file__).resolve().is_relative_to(root.resolve()), module.__file__
for relative in install_adapters.CRITICAL_LIFECYCLE_SCHEMA_FILES:
 Draft202012Validator.check_schema(json.loads((root/relative).read_text(encoding='utf-8')))
import package_common,production_authorization,lifecycle_digest
assert package_common.DEFAULT_SCHEMA.is_relative_to(root)
assert production_authorization._current_repo_commit(root) is None
assert len(lifecycle_digest.skill_tree_fingerprint(root)) == 64
assert not any('codex-work-skills' in path for path in sys.path)
print('installed lifecycle imports, schemas and no-git provenance PASS')
'''
            result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(engine)], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no-git provenance PASS", result.stdout)

    def test_dynamic_inventory_cache_invariance_and_lifecycle_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.copy_source(root)
            engine = self.install_full(source, root / "project")
            before = install_adapters._runtime_inventory_from_source(source)
            self.assertEqual(before, install_adapters._runtime_inventory_from_source(source))
            self.assertGreater(len(before), len(install_adapters.CRITICAL_PRODUCTION_SOURCE_FILES))
            for ignored in (source / "scripts/__pycache__/runtime.pyc", source / "scripts/__pycache__/metadata.json", source / "scripts/loose.pyc", source / ".DS_Store"):
                ignored.parent.mkdir(parents=True, exist_ok=True); ignored.write_bytes(b"ignored cache")
            self.assertEqual(before, install_adapters._runtime_inventory_from_source(source))
            installed_cache = engine / "scripts/__pycache__/metadata.json"
            installed_cache.parent.mkdir(parents=True, exist_ok=True); installed_cache.write_bytes(b"ignored installed cache")
            self.assertEqual(install_adapters._detect_existing_engine_mode(engine, source), "full-current")
            helper = source / "scripts/acceptance_v3.py"
            helper.write_bytes(helper.read_bytes() + b"\n# synthetic lifecycle source change\n")
            after = install_adapters._runtime_inventory_from_source(source)
            self.assertNotEqual(install_adapters._runtime_fingerprint(before), install_adapters._runtime_fingerprint(after))
            self.assertEqual(install_adapters._detect_existing_engine_mode(engine, source), "full-stale")
            helper.write_bytes(helper.read_bytes().removesuffix(b"\n# synthetic lifecycle source change\n"))
            (source / "scripts/new-lifecycle-helper.py").write_bytes(b"# synthetic added runtime\n")
            self.assertNotEqual(before, install_adapters._runtime_inventory_from_source(source))
            self.assertEqual(install_adapters._detect_existing_engine_mode(engine, source), "full-stale")
            installed = engine / "scripts/acceptance_v3.py"
            installed.write_bytes(installed.read_bytes() + b"\n# synthetic installed tamper\n")
            self.assertEqual(install_adapters._detect_existing_engine_mode(engine, source), "inconsistent")

    def test_failed_lifecycle_upgrade_restores_existing_engine_and_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.copy_source(root); target = root / "project"
            engine = self.install_full(source, target)
            before = tree_bytes(target)
            runtime = source / "scripts/acceptance_v3.py"
            runtime.write_bytes(runtime.read_bytes() + b"\n# synthetic lifecycle upgrade\n")
            adapter = source / "AGENTS.md"
            adapter.write_bytes(adapter.read_bytes() + b"\nSynthetic upgrade instructions.\n")
            original_replace = os.replace
            def replace(src, dst):
                if Path(dst) == engine and ".lesson-adapters.stage-" in str(src):
                    raise OSError("SYNTHETIC injected engine publication failure")
                return original_replace(src, dst)
            with patch.object(install_adapters.os, "replace", side_effect=replace), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "previous files restored"):
                    install_adapters.install(source, target, adapters=["all"], copy_engine=True, replace=True)
            self.assertEqual(tree_bytes(target), before)
            self.assertFalse(list(target.glob(".lesson-adapters.stage-*")))
