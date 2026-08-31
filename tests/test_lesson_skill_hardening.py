from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
SCRIPTS = LESSON / "scripts"
_MISSING = object()
_LESSON_MODULE_NAMES = (
    "path_safety",
    "semantic_bookmarks",
    "content_contract",
    "bookmark_utils",
    "content_quality",
    "package_common",
    "validate_template",
    "render_qa",
    "validate_output",
    "generate_lesson_plans",
    "build_template_patch",
    "install",
    "install_adapters",
    "record_visual_inspection",
    "validate_visual_inspection",
)


@contextmanager
def isolated_lesson_imports():
    """Load legacy script modules without publishing process-global imports."""

    original_path = sys.path[:]
    saved_modules = {name: sys.modules.get(name, _MISSING) for name in _LESSON_MODULE_NAMES}
    try:
        for name in _LESSON_MODULE_NAMES:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(SCRIPTS))
        modules = {
            name: importlib.import_module(name)
            for name in _LESSON_MODULE_NAMES
        }
        yield modules
    finally:
        sys.path[:] = original_path
        for name, previous in saved_modules.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


with isolated_lesson_imports() as _lesson_modules:
    build_template_patch = _lesson_modules["build_template_patch"]
    content_quality = _lesson_modules["content_quality"]
    lesson_install = _lesson_modules["install"]
    install_adapters = _lesson_modules["install_adapters"]
    render_qa = _lesson_modules["render_qa"]
    validate_output = _lesson_modules["validate_output"]
    lesson_generator = _lesson_modules["generate_lesson_plans"]
    CHECK_NAMES = _lesson_modules["record_visual_inspection"].CHECK_NAMES
    write_visual_inspection_evidence = _lesson_modules["record_visual_inspection"].write_visual_inspection_evidence
    validate_visual_inspection = _lesson_modules["validate_visual_inspection"].validate_visual_inspection


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LessonSkillHardeningTests(unittest.TestCase):
    def test_hardening_import_loader_restores_process_global_state(self) -> None:
        original_path = sys.path[:]
        original_modules = {name: sys.modules.get(name, _MISSING) for name in _LESSON_MODULE_NAMES}
        with isolated_lesson_imports():
            self.assertIn(str(SCRIPTS), sys.path)
        self.assertEqual(sys.path, original_path)
        for name, previous in original_modules.items():
            if previous is _MISSING:
                self.assertNotIn(name, sys.modules)
            else:
                self.assertIs(sys.modules.get(name), previous)

    def test_intra_lesson_calibration_covers_domain_positives_and_negatives(self) -> None:
        cases = content_quality.intra_lesson_coherence_calibration()
        self.assertGreaterEqual(len(cases), 8)
        self.assertTrue(all(item["expected"] == item["actual"] for item in cases), cases)

    def test_implementation_item_coherence_checks_all_fields_and_bounded_diagnostics(self) -> None:
        def lesson(domain: str, **stage_overrides):
            if domain == "nursing":
                task = "完成患者生命体征测量与护理记录"
                body = ["测量患者血压、体温并判断异常", "记录护理结果并形成生命体征测量记录"]
                deliverable = "生命体征测量记录与护理结果"
            else:
                task = "完成数据库查询与索引维护"
                body = ["编写 SQL 查询语句并分析查询结果", "形成数据库查询报告"]
                deliverable = "数据库查询报告"
            stage = {
                "id": "task_implementation",
                "label": "任务实施",
                "modality": "小组实训",
                "content": [body[0], body[1]],
                "teacher_actions": ["教师巡视"],
                "student_actions": ["学生讨论"],
                "objective": body[0],
            }
            stage.update(stage_overrides)
            return {
                "lesson_id": "L01",
                "task": task,
                "teaching_content": body,
                "key_point": {"content": [body[0]]},
                "difficult_point": {"content": [body[1]]},
                "progression": {"deliverable": deliverable},
                "implementation": [stage],
            }

        cases = (
            ("nursing mixed content", lesson("nursing", content=["完成血压测量", "记录护理结果", "使用 SQL 创建数据库索引"]), "content", 2),
            ("nursing mixed teacher action", lesson("nursing", teacher_actions=["教师巡视", "演示数据库索引优化"]), "teacher_actions", 1),
            ("database mixed student action", lesson("database", student_actions=["完成 SQL 查询", "测量患者血压"]), "student_actions", 1),
            ("nursing domain label", lesson("nursing", label="数据库索引优化"), "label", 0),
            ("nursing domain modality", lesson("nursing", modality="SQL数据库查询实训"), "modality", 0),
        )
        for name, payload, field, item_index in cases:
            with self.subTest(case=name):
                report = content_quality._intra_lesson_coherence([payload], ["L01"])
                failures = [
                    item
                    for item in report["failures"]
                    if item.get("failed_gate") == "implementation_item_coherence"
                ]
                failure = next(item for item in failures if item["field"] == field and item["item_index"] == item_index)
                self.assertEqual(failure["status"], "failed")
                self.assertEqual(failure["reason"], "substantive item is disconnected from lesson main semantic component")
                self.assertEqual(set(failure["diagnostic"]), {"preview", "text_sha256"})
                value = payload["implementation"][0][field]
                value = value if isinstance(value, str) else value[item_index]
                if len(str(value)) > content_quality.DIAGNOSTIC_PREVIEW_MAX_CHARS:
                    self.assertNotIn(str(value), failure["diagnostic"]["preview"])

        for name, payload in (
            ("nursing positive", lesson("nursing", content=["完成血压测量", "记录护理结果"])),
            ("database positive", lesson("database", content=["编写 SQL 查询", "分析查询结果"])),
        ):
            with self.subTest(case=name):
                report = content_quality._intra_lesson_coherence([payload], ["L01"])
                self.assertEqual(report["status"], "passed", report)
                items = report["lessons"][0]["implementation"]["stages"][0]["items"]
                self.assertTrue(any(item["generic"] for item in items))
                self.assertTrue(all(item["status"] == "passed" for item in items))

    def test_intra_lesson_gate_b_requires_the_main_semantic_component(self) -> None:
        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "lesson-plan-content-v2-it.json").read_text(
                encoding="utf-8"
            )
        )
        lesson = next(item for item in fixture["lessons"] if item["lesson_id"] == "L03")
        report = content_quality._intra_lesson_coherence([lesson], ["L03"])
        self.assertEqual(report["status"], "passed", report)
        lesson_report = report["lessons"][0]
        self.assertEqual(
            set(lesson_report["main_component"]),
            {"task_connected", "deliverable_connected", "members"},
        )
        self.assertTrue(lesson_report["main_component"]["task_connected"])
        self.assertTrue(lesson_report["main_component"]["deliverable_connected"])
        self.assertNotIn("value", lesson_report["core_nodes"][0])
        self.assertIn("diagnostic", lesson_report["core_nodes"][0])
        self.assertIn("preview", lesson_report["core_nodes"][0]["diagnostic"])
        self.assertIn("text_sha256", lesson_report["core_nodes"][0]["diagnostic"])
        gate_b = report["lessons"][0]["gate_b"]
        self.assertTrue(gate_b["shared_cluster"]["cross_body_bridge"])
        self.assertTrue(gate_b["shared_cluster"]["same_component"])

    def test_installer_dry_run_and_replace_are_transactional(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-installer-hardening-") as temp_name:
            root = Path(temp_name) / "skills"
            lesson_install.install(LESSON, root, dry_run=True)
            self.assertFalse(root.exists())
            lesson_install.install(LESSON, root)
            target = root / lesson_install.SKILL_NAME
            (target / "user-marker.txt").write_text("old", encoding="utf-8")
            lesson_install.install(LESSON, root, replace=True)
            backups = list(root.glob("lesson-plan-docx-generator_backup_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "user-marker.txt").read_text(encoding="utf-8"), "old")

    def test_lesson_installer_checks_source_and_staged_runtime_inventory_before_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-installer-inventory-") as temp_name:
            folder = Path(temp_name)
            source = folder / "source"
            shutil.copytree(LESSON, source)
            (source / "scripts" / "content_quality.py").unlink()
            target_root = folder / "missing-source-target"
            with self.assertRaisesRegex(FileNotFoundError, "content_quality.py"):
                lesson_install.install(source, target_root)
            self.assertFalse(target_root.exists())

            target_root = folder / "missing-stage-target"
            real_verify_stage = lesson_install._verify_stage

            def verify_stage_with_missing_runtime(source_path, stage_path):
                (Path(stage_path) / "scripts" / "content_quality.py").unlink()
                return real_verify_stage(source_path, stage_path)

            with patch.object(lesson_install, "_verify_stage", side_effect=verify_stage_with_missing_runtime):
                with self.assertRaisesRegex(RuntimeError, "staged installation is missing required file"):
                    lesson_install.install(LESSON, target_root)
            self.assertFalse((target_root / lesson_install.SKILL_NAME).exists())
            self.assertEqual(list(target_root.glob(f".{lesson_install.SKILL_NAME}.stage-*")), [])

    def test_installer_commit_failure_restores_previous_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-installer-rollback-") as temp_name:
            root = Path(temp_name) / "skills"
            lesson_install.install(LESSON, root)
            target = root / lesson_install.SKILL_NAME
            marker = target / "rollback-marker.txt"
            marker.write_text("keep", encoding="utf-8")
            real_replace = lesson_install.os.replace
            calls = 0

            def fail_commit(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected commit failure")
                return real_replace(source, destination)

            with patch.object(lesson_install.os, "replace", side_effect=fail_commit):
                with self.assertRaisesRegex(RuntimeError, "previous installation restored"):
                    lesson_install.install(LESSON, root, replace=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_installer_cleanup_warning_preserves_success_and_primary_failure(self) -> None:
        warning = "cleanup failed for staging directory: locked; residual path: stage"
        with tempfile.TemporaryDirectory(prefix="lesson-installer-cleanup-success-") as temp_name:
            root = Path(temp_name) / "skills"
            diagnostics = io.StringIO()
            with patch.object(lesson_install, "_remove_stage", return_value=warning):
                with redirect_stderr(diagnostics):
                    target = lesson_install.install(LESSON, root)
            self.assertTrue(target.is_dir())
            self.assertIn("WARNING:", diagnostics.getvalue())
            self.assertIn("residual path:", diagnostics.getvalue())

        with tempfile.TemporaryDirectory(prefix="lesson-installer-cleanup-failure-") as temp_name:
            root = Path(temp_name) / "skills"
            diagnostics = io.StringIO()
            with patch.object(lesson_install, "_verify_stage", side_effect=RuntimeError("injected verify failure")):
                with patch.object(lesson_install, "_remove_stage", return_value=warning):
                    with redirect_stderr(diagnostics):
                        with self.assertRaisesRegex(RuntimeError, "injected verify failure"):
                            lesson_install.install(LESSON, root)
            self.assertIn("WARNING:", diagnostics.getvalue())
            self.assertIn("residual path:", diagnostics.getvalue())

    def test_adapter_transaction_failure_injections_a_through_e_are_independent(self) -> None:
        real_replace = install_adapters.os.replace

        with tempfile.TemporaryDirectory(prefix="lesson-adapter-transaction-") as temp_name:
            folder = Path(temp_name)

            with self.subTest(injection="A-stage validation"):
                root = folder / "a"
                root.mkdir()
                target = root / "existing.txt"
                target.write_bytes(b"old")
                with patch.object(
                    install_adapters,
                    "_assert_no_symlink_ancestor",
                    side_effect=OSError("injected staging validation failure"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "injected staging validation failure"):
                        install_adapters._apply_files({target: b"new"}, root)
                self.assertEqual(target.read_bytes(), b"old")
                self.assertEqual(list(root.glob(".lesson-adapters.stage-*")), [])

            with self.subTest(injection="B-backup"):
                root = folder / "b"
                root.mkdir()
                target = root / "existing.txt"
                target.write_bytes(b"old")
                calls = 0

                def fail_backup(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        raise OSError("injected backup failure")
                    return real_replace(source, destination)

                with patch.object(install_adapters.os, "replace", side_effect=fail_backup):
                    with self.assertRaisesRegex(RuntimeError, "injected backup failure"):
                        install_adapters._apply_files({target: b"new"}, root)
                self.assertEqual(target.read_bytes(), b"old")
                self.assertEqual(list(root.glob("*.backup_*")), [])

            with self.subTest(injection="C-file commit"):
                root = folder / "c"
                root.mkdir()
                target = root / "existing.txt"
                target.write_bytes(b"old")
                calls = 0

                def fail_file_commit(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise OSError("injected file commit failure")
                    return real_replace(source, destination)

                with patch.object(install_adapters.os, "replace", side_effect=fail_file_commit):
                    with self.assertRaisesRegex(RuntimeError, "previous files restored"):
                        install_adapters._apply_files({target: b"new"}, root)
                self.assertEqual(target.read_bytes(), b"old")
                self.assertEqual(list(root.glob("*.backup_*")), [])

            with self.subTest(injection="D-engine swap"):
                root = folder / "d"
                engine = root / install_adapters.ENGINE_NAME
                engine.mkdir(parents=True)
                old_runtime = engine / "scripts" / "old.py"
                old_runtime.parent.mkdir()
                old_runtime.write_bytes(b"old")
                target = engine / "scripts" / "new.py"
                calls = 0

                def fail_engine_swap(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise OSError("injected engine swap failure")
                    return real_replace(source, destination)

                with patch.object(install_adapters.os, "replace", side_effect=fail_engine_swap):
                    with self.assertRaisesRegex(RuntimeError, "previous files restored"):
                        install_adapters._apply_files({target: b"new"}, root, replace_engine=engine)
                self.assertEqual(old_runtime.read_bytes(), b"old")
                self.assertFalse((engine / "scripts" / "new.py").exists())
                self.assertEqual(list(root.glob(f"{install_adapters.ENGINE_NAME}.backup_*")), [])

            with self.subTest(injection="E-rollback accumulation"):
                root = folder / "e"
                root.mkdir()
                first = root / "a.txt"
                second = root / "b.txt"
                first.write_bytes(b"old-a")
                second.write_bytes(b"old-b")
                calls = 0

                def fail_commit_and_restore(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == 4:
                        raise OSError("injected commit failure")
                    if calls in (5, 6):
                        raise OSError(f"injected rollback restore failure {calls}")
                    return real_replace(source, destination)

                real_remove = install_adapters._remove_path

                def fail_first_removal(path):
                    if path == first:
                        raise OSError("injected rollback remove failure")
                    return real_remove(path)

                with patch.object(install_adapters.os, "replace", side_effect=fail_commit_and_restore):
                    with patch.object(install_adapters, "_remove_path", side_effect=fail_first_removal):
                        with self.assertRaisesRegex(RuntimeError, "injected commit failure") as raised:
                            install_adapters._apply_files({first: b"new-a", second: b"new-b"}, root)
                message = str(raised.exception)
                self.assertIn("rollback failures:", message)
                self.assertIn("injected rollback remove failure", message)
                self.assertIn("injected rollback restore failure 5", message)
                self.assertIn("injected rollback restore failure 6", message)
                self.assertIn(str(first), message)
                self.assertIn(str(second), message)
                self.assertEqual(first.read_bytes(), b"new-a")
                self.assertFalse(second.exists())
                self.assertEqual(len(list(root.glob("*.backup_*"))), 2)
                self.assertEqual(list(root.glob(".lesson-adapters.stage-*")), [])

    def test_adapter_stage_cleanup_warning_preserves_success_and_primary_error(self) -> None:
        warning = "cleanup failed for adapter staging directory: locked; residual path: stage"
        real_replace = install_adapters.os.replace
        with tempfile.TemporaryDirectory(prefix="lesson-adapter-cleanup-") as temp_name:
            root = Path(temp_name)
            target = root / "new.txt"
            diagnostics = io.StringIO()
            with patch.object(install_adapters, "_cleanup_path", return_value=warning):
                with redirect_stderr(diagnostics):
                    install_adapters._apply_files({target: b"new"}, root)
            self.assertEqual(target.read_bytes(), b"new")
            self.assertIn("WARNING:", diagnostics.getvalue())
            self.assertIn("residual path:", diagnostics.getvalue())

            old = root / "old.txt"
            old.write_bytes(b"old")
            calls = 0

            def fail_commit(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected primary commit failure")
                return real_replace(source, destination)

            diagnostics = io.StringIO()
            with patch.object(install_adapters.os, "replace", side_effect=fail_commit):
                with patch.object(install_adapters, "_cleanup_path", return_value=warning):
                    with redirect_stderr(diagnostics):
                        with self.assertRaisesRegex(RuntimeError, "injected primary commit failure"):
                            install_adapters._apply_files({old: b"new"}, root)
            self.assertEqual(old.read_bytes(), b"old")
            self.assertIn("WARNING:", diagnostics.getvalue())
            self.assertIn("residual path:", diagnostics.getvalue())

    def test_lesson_adapter_engine_modes_preserve_full_runtime_and_fail_closed(self) -> None:
        def engine_snapshot(engine: Path) -> dict[str, bytes]:
            return {
                str(path.relative_to(engine)): path.read_bytes()
                for path in engine.rglob("*")
                if path.is_file() and not path.is_symlink()
            }

        def tree_snapshot(root: Path) -> dict[str, bytes]:
            return {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file() and not path.is_symlink()
            }

        with tempfile.TemporaryDirectory(prefix="lesson-adapter-engine-modes-") as temp_name:
            folder = Path(temp_name)
            minimal = folder / "minimal"
            install_adapters.install(LESSON, minimal, adapters=["all"])
            minimal_engine = minimal / install_adapters.ENGINE_NAME
            self.assertEqual(install_adapters._detect_existing_engine_mode(minimal_engine), "minimal")
            minimal_before = engine_snapshot(minimal_engine)
            install_adapters.install(LESSON, minimal, adapters=["all"])
            self.assertEqual(engine_snapshot(minimal_engine), minimal_before)

            full = folder / "full"
            output = io.StringIO()
            with redirect_stdout(output):
                install_adapters.install(LESSON, full, adapters=["all"], copy_engine=True)
            full_engine = full / install_adapters.ENGINE_NAME
            self.assertEqual(install_adapters._detect_existing_engine_mode(full_engine, LESSON), "full-current")
            full_before = engine_snapshot(full_engine)
            agents = full / "AGENTS.md"
            agents.write_text("project-owned notes\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                install_adapters.install(LESSON, full, adapters=["agents"])
            self.assertIn("preserved-full-engine=", output.getvalue())
            self.assertEqual(engine_snapshot(full_engine), full_before)
            agents_text = agents.read_text(encoding="utf-8")
            self.assertIn("project-owned notes", agents_text)
            self.assertIn(install_adapters.MARKER_START, agents_text)
            self.assertIn(".lesson-plan-docx-generator/scripts/generate_lesson_plans.py", agents_text)
            self.assertNotIn("the full Lesson runtime (install with --copy-engine)", agents_text)

            legacy = folder / "legacy-full"
            install_adapters.install(LESSON, legacy, adapters=["all"], copy_engine=True)
            legacy_engine = legacy / install_adapters.ENGINE_NAME
            (legacy_engine / install_adapters.ENGINE_STATE_FILE).unlink()
            self.assertEqual(install_adapters._detect_existing_engine_mode(legacy_engine, LESSON), "full-stale")
            legacy_before = tree_snapshot(legacy)
            with self.assertRaisesRegex(ValueError, "A full Lesson engine is installed but is older/different"):
                install_adapters.install(LESSON, legacy, adapters=["agents"])
            self.assertEqual(tree_snapshot(legacy), legacy_before)
            install_adapters.install(LESSON, legacy, adapters=["all"], copy_engine=True, replace=True)
            self.assertEqual(install_adapters._detect_existing_engine_mode(legacy_engine, LESSON), "full-current")

            stale = full_engine / "scripts" / "obsolete-helper.py"
            stale.write_text("stale", encoding="utf-8")
            install_adapters.install(LESSON, full, adapters=["all"], copy_engine=True, replace=True)
            self.assertFalse(stale.exists())
            self.assertEqual(install_adapters._detect_existing_engine_mode(full_engine, LESSON), "full-current")
            install_adapters.install(LESSON, full, adapters=["all"], copy_engine=True, replace=True)
            self.assertEqual(install_adapters._detect_existing_engine_mode(full_engine, LESSON), "full-current")

            modified_source = folder / "modified-source"
            shutil.copytree(LESSON, modified_source)
            runtime_source = modified_source / "scripts" / "content_quality.py"
            runtime_source.write_text(runtime_source.read_text(encoding="utf-8") + "\n# source fingerprint probe\n", encoding="utf-8")
            self.assertEqual(install_adapters._detect_existing_engine_mode(full_engine, modified_source), "full-stale")
            before = tree_snapshot(full)
            with self.assertRaisesRegex(ValueError, "A full Lesson engine is installed but is older/different"):
                install_adapters.install(modified_source, full, adapters=["agents"])
            self.assertEqual(tree_snapshot(full), before)
            install_adapters.install(modified_source, full, adapters=["all"], copy_engine=True, replace=True)
            self.assertEqual(install_adapters._detect_existing_engine_mode(full_engine, modified_source), "full-current")

            installed_runtime = full_engine / "scripts" / "content_quality.py"
            installed_runtime.write_text(installed_runtime.read_text(encoding="utf-8") + "\n# installed mutation\n", encoding="utf-8")
            self.assertEqual(install_adapters._detect_existing_engine_mode(full_engine, modified_source), "inconsistent")

            inconsistent = folder / "inconsistent"
            inconsistent_engine = inconsistent / install_adapters.ENGINE_NAME
            inconsistent_engine.mkdir(parents=True)
            (inconsistent_engine / "SKILL.md").write_text("partial", encoding="utf-8")
            before = tree_snapshot(inconsistent)
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                install_adapters.install(LESSON, inconsistent, adapters=["agents"])
            self.assertEqual(tree_snapshot(inconsistent), before)
            self.assertEqual(install_adapters._detect_existing_engine_mode(inconsistent_engine, LESSON), "inconsistent")

            incomplete_full = folder / "incomplete-full"
            install_adapters.install(LESSON, incomplete_full, adapters=["all"], copy_engine=True)
            incomplete_engine = incomplete_full / install_adapters.ENGINE_NAME
            (incomplete_engine / "scripts" / "content_quality.py").unlink()
            before = tree_snapshot(incomplete_full)
            self.assertEqual(install_adapters._detect_existing_engine_mode(incomplete_engine, LESSON), "inconsistent")
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                install_adapters.install(LESSON, incomplete_full, adapters=["agents"])
            self.assertEqual(tree_snapshot(incomplete_full), before)

    def test_adapter_namespace_markers_and_aider_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-adapter-hardening-") as temp_name:
            target = Path(temp_name) / "project"
            install_adapters.install(LESSON, target, adapters=["all"])
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(agents.count(install_adapters.MARKER_START), 1)
            self.assertIn(".lesson-plan-docx-generator/SKILL.md", agents)
            self.assertNotIn(".lesson-plan-docx-generator/scripts/generate_lesson_plans.py", agents)
            self.assertIn("--copy-engine", agents)
            self.assertTrue((target / ".lesson-plan-docx-generator" / "SKILL.md").is_file())
            self.assertTrue((target / ".lesson-plan-docx-generator" / "CONVENTIONS.md").is_file())
            for minimal_name in ("SKILL.md", "通用提示词.md", "AGENTS.md", "CONVENTIONS.md"):
                minimal_text = (target / ".lesson-plan-docx-generator" / minimal_name).read_text(encoding="utf-8")
                self.assertNotIn("scripts/generate_lesson_plans.py", minimal_text)
                self.assertNotIn("docs/content-contract-v2.md", minimal_text)
                self.assertNotIn("examples/tasks.example.json", minimal_text)
                self.assertNotRegex(minimal_text, r"(?:scripts|docs|examples|schemas|assets)/")
            full_target = Path(temp_name) / "full-project"
            install_adapters.install(LESSON, full_target, adapters=["all"], copy_engine=True)
            full_agents = (full_target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn(".lesson-plan-docx-generator/scripts/generate_lesson_plans.py", full_agents)
            stale = full_target / ".lesson-plan-docx-generator" / "obsolete-helper.py"
            stale.write_text("stale", encoding="utf-8")
            install_adapters.install(LESSON, full_target, adapters=["all"], copy_engine=True, replace=True)
            self.assertFalse(stale.exists())
            self.assertTrue(any(path.name.startswith(".lesson-plan-docx-generator.backup_") for path in full_target.iterdir()))
            install_adapters.install(LESSON, target, adapters=["agents"])
            self.assertEqual((target / "AGENTS.md").read_text(encoding="utf-8").count(install_adapters.MARKER_START), 1)
            aider = target / ".aider.conf.yml"
            before = aider.read_bytes()
            aider.write_text("read: {unsafe: true}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complex"):
                install_adapters.install(LESSON, target, adapters=["aider"])
            self.assertEqual(aider.read_text(encoding="utf-8"), "read: {unsafe: true}\n")
            self.assertNotEqual(before, aider.read_bytes())

    def test_lesson_marker_merge_is_fail_closed_and_idempotent(self) -> None:
        start = install_adapters.MARKER_START
        end = install_adapters.MARKER_END
        empty = install_adapters.merge_marker_section("", "payload")
        self.assertEqual(empty.count(start), 1)
        self.assertEqual(empty.count(end), 1)

        existing = f"unrelated\n{start}\nold\n{end}\nsuffix\n"
        replaced = install_adapters.merge_marker_section(existing, "new")
        self.assertEqual(replaced.count(start), 1)
        self.assertEqual(replaced.count(end), 1)
        self.assertIn("unrelated", replaced)
        self.assertIn("suffix", replaced)
        self.assertEqual(
            install_adapters.merge_marker_section(replaced, "new"),
            replaced,
        )

        malformed_cases = {
            "missing end": f"{start}\nold\n",
            "duplicate blocks": f"{start}\na\n{end}\n{start}\nb\n{end}",
            "nested start": f"{start}\nouter\n{start}\ninner\n{end}",
            "duplicate end": f"{start}\nold\n{end}\n{end}",
            "end before start": f"{end}\n{start}\nold",
        }
        for name, value in malformed_cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "refusing to mutate"):
                    install_adapters.merge_marker_section(value, "replacement")

    def test_adapter_runtime_reference_closure_for_minimal_and_full_modes(self) -> None:
        runtime_path = re.compile(
            r"(?:(?:<skill>|lesson-plan-docx-generator|course-gradebook-generator|"
            r"\.lesson-plan-docx-generator|\.course-gradebook-generator)[/\\])?"
            r"(?:scripts|docs|examples|schemas|assets)/[^\s`\"'<>（）(),，。；：！？]+"
        )

        def references(root: Path) -> list[str]:
            values: list[str] = []
            for name in ("SKILL.md", "通用提示词.md", "AGENTS.md", "CONVENTIONS.md"):
                values.extend(
                    item.rstrip(".,;:!?")
                    for item in runtime_path.findall((root / name).read_text(encoding="utf-8"))
                )
            return values

        with tempfile.TemporaryDirectory(prefix="lesson-adapter-closure-") as temp_name:
            folder = Path(temp_name)
            minimal = folder / "minimal"
            install_adapters.install(LESSON, minimal, adapters=["all"])
            self.assertEqual(references(minimal / install_adapters.ENGINE_NAME), [])

            full = folder / "full"
            install_adapters.install(LESSON, full, adapters=["all"], copy_engine=True)
            for reference in references(full / install_adapters.ENGINE_NAME):
                self.assertTrue((full / reference).is_file(), reference)
            self.assertTrue((full / install_adapters.ENGINE_NAME / "scripts" / "generate_lesson_plans.py").is_file())
            self.assertTrue((full / install_adapters.ENGINE_NAME / "schemas" / "lesson-plan-input.schema.json").is_file())

            gradebook = load_module(
                ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "scripts" / "install_adapters.py",
                "gradebook_runtime_closure_hardening",
            )
            gradebook_root = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator"
            grade_minimal = folder / "grade-minimal"
            for name in gradebook.ADAPTER_PATHS:
                for relative in gradebook.ADAPTER_PATHS[name]:
                    gradebook.copy_file(gradebook_root, grade_minimal, relative, False, False, copy_engine=False)
            gradebook.copy_engine(gradebook_root, grade_minimal, False, False, full=False)
            self.assertEqual(references(grade_minimal / gradebook.ENGINE_NAME), [])

            grade_full = folder / "grade-full"
            for name in gradebook.ADAPTER_PATHS:
                for relative in gradebook.ADAPTER_PATHS[name]:
                    gradebook.copy_file(gradebook_root, grade_full, relative, False, False, copy_engine=True)
            gradebook.copy_engine(gradebook_root, grade_full, False, False, full=True)
            for reference in references(grade_full / gradebook.ENGINE_NAME):
                self.assertTrue((grade_full / reference).is_file(), reference)
            self.assertTrue((grade_full / gradebook.ENGINE_NAME / "scripts" / "generate_gradebook.py").is_file())
            self.assertTrue((grade_full / gradebook.ENGINE_NAME / "schemas" / "gradebook-input.schema.json").is_file())

    def test_gradebook_target_containment_allows_parent_and_sibling(self) -> None:
        gradebook = load_module(
            ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "scripts" / "install_adapters.py",
            "gradebook_containment_hardening",
        )
        with tempfile.TemporaryDirectory(prefix="gradebook-containment-") as temp_name:
            folder = Path(temp_name)
            source = folder / "project" / "course-gradebook-generator"
            source.mkdir(parents=True)
            with self.assertRaises(ValueError):
                gradebook.copy_engine(source, source, False, True, full=True)
            with self.assertRaises(ValueError):
                gradebook.copy_engine(source, source / "tmp" / "project", False, True, full=True)

            parent = source.parent
            gradebook.copy_engine(source, parent, False, True, full=True)
            gradebook.copy_engine(source, folder / "sibling", False, True, full=True)

            alias = folder / "alias"
            try:
                alias.symlink_to(source, target_is_directory=True)
            except (OSError, NotImplementedError):
                pass
            else:
                with self.assertRaises(ValueError):
                    gradebook.copy_engine(source, alias / "nested", False, True, full=True)

    def test_successful_install_reports_cleanup_residue_without_failing(self) -> None:
        source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
        with tempfile.TemporaryDirectory(prefix="lesson-cleanup-success-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            argv = [
                "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--skip-template-validation",
                "--skip-output-validation",
            ]
            diagnostics = io.StringIO()
            with patch.object(
                lesson_generator,
                "_cleanup_path",
                return_value="cleanup failed for candidate directory: candidate is locked; residual path: candidate",
            ):
                with patch.dict(os.environ, {"LESSON_ALLOW_UNSAFE_VALIDATION_SKIP": "1"}):
                    with patch.object(sys, "argv", argv):
                        with redirect_stderr(diagnostics):
                            lesson_generator.main()
            self.assertTrue(output.is_dir())
            self.assertIn("WARNING:", diagnostics.getvalue())
            self.assertIn("residual path:", diagnostics.getvalue())

    def test_gradebook_shared_marker_and_aider_coexistence(self) -> None:
        gradebook = load_module(
            ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "scripts" / "install_adapters.py",
            "gradebook_install_adapters_hardening",
        )
        with tempfile.TemporaryDirectory(prefix="lesson-gradebook-coexist-") as temp_name:
            target = Path(temp_name) / "project"
            install_adapters.install(LESSON, target, adapters=["agents", "aider"])
            gradebook_root = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator"
            gradebook.copy_engine(gradebook_root, target, False, False)
            gradebook.copy_file(gradebook_root, target, "AGENTS.md", False, False)
            first_agents = (target / "AGENTS.md").read_bytes()
            backups_before = set(target.glob("AGENTS.md.backup_*"))
            gradebook.copy_file(gradebook_root, target, "AGENTS.md", False, False)
            self.assertEqual(first_agents, (target / "AGENTS.md").read_bytes())
            self.assertEqual(backups_before, set(target.glob("AGENTS.md.backup_*")))
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue((target / ".course-gradebook-generator" / "SKILL.md").is_file())
            self.assertTrue((target / ".course-gradebook-generator" / "通用提示词.md").is_file())
            self.assertIn(".course-gradebook-generator/SKILL.md", agents)
            gradebook.copy_file(gradebook_root, target, ".aider.conf.yml", False, False)
            aider = (target / ".aider.conf.yml").read_text(encoding="utf-8")
            self.assertIn("lesson-plan-docx-generator:start", agents)
            self.assertIn("course-gradebook-generator:start", agents)
            self.assertIn(".lesson-plan-docx-generator/SKILL.md", aider)
            self.assertIn(".course-gradebook-generator/SKILL.md", aider)

            default_target = Path(temp_name) / "default-project"
            with patch.object(sys, "argv", ["install_adapters.py", "--target-dir", str(default_target)]):
                gradebook.main()
            default_agents = default_target / "AGENTS.md"
            self.assertTrue((default_target / ".course-gradebook-generator" / "SKILL.md").is_file())
            self.assertIn(".course-gradebook-generator/SKILL.md", default_agents.read_text(encoding="utf-8"))
            default_backups = set(default_target.glob("*.backup_*"))
            with patch.object(sys, "argv", ["install_adapters.py", "--target-dir", str(default_target)]):
                gradebook.main()
            self.assertEqual(default_backups, set(default_target.glob("*.backup_*")))

    def test_visual_evidence_validator_rejects_stale_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-visual-hardening-") as temp_name:
            output = Path(temp_name) / "output"
            output.mkdir()
            lesson = output / "教案01_示例.docx"
            lesson.write_bytes(b"docx-bytes")
            qa_report = output / "qa-report.json"
            qa_report.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "output_dir": str(output.resolve()),
                        "validation": {"output": True},
                        "render": {"page_counts": {lesson.name: 2}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            checks = {name: "passed" for name in CHECK_NAMES}
            evidence_path = output / "visual-inspection.json"
            for invalid_pages in (
                {},
                {lesson.name: []},
                {lesson.name: [0]},
                {lesson.name: [-1]},
                {lesson.name: [1.5]},
                {lesson.name: [True]},
                [1],
            ):
                with self.subTest(invalid_pages=invalid_pages):
                    with self.assertRaises(ValueError):
                        write_visual_inspection_evidence(
                            output_dir=output,
                            qa_report=qa_report,
                            destination=evidence_path,
                            status="passed",
                            inspected_pages=invalid_pages,
                            checks=checks,
                            notes="invalid direct API input",
                        )
            self.assertFalse(evidence_path.exists())
            write_visual_inspection_evidence(
                output_dir=output,
                qa_report=qa_report,
                destination=evidence_path,
                status="passed",
                inspected_pages={lesson.name: [1, 2]},
                checks=checks,
                notes="Agent inspected representative pages.",
            )
            validate_visual_inspection(output, qa_report, evidence_path)
            valid_evidence = evidence_path.read_bytes()
            empty_evidence = json.loads(valid_evidence.decode("utf-8"))
            empty_evidence["inspected_files"] = []
            empty_evidence["inspected_pages"] = {}
            evidence_path.write_text(json.dumps(empty_evidence, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least one inspected"):
                validate_visual_inspection(output, qa_report, evidence_path)
            evidence_path.write_bytes(valid_evidence)
            lesson.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "stale"):
                validate_visual_inspection(output, qa_report, evidence_path)

    def test_xml_template_patch_escapes_visible_text_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-template-patch-hardening-") as temp_name:
            folder = Path(temp_name)
            source = folder / "source.docx"
            target = folder / "patched.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "template.docx", source)
            build_template_patch.build_patch(source, target, [("职业价值观", "A&B <测试>")])
            self.assertTrue(target.is_file())
            from docx import Document

            document = Document(target)
            visible = [paragraph.text for paragraph in document.paragraphs]
            def cell_text(cell):
                return [cell.text, *[value for table in cell.tables for row in table.rows for nested in row.cells for value in cell_text(nested)]]

            visible.extend(value for table in document.tables for row in table.rows for cell in row.cells for value in cell_text(cell))
            self.assertIn("A&B <测试>", "\n".join(visible))

    def test_xml_template_patch_does_not_cross_paragraph_boundaries(self) -> None:
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>跨</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>段</w:t></w:r></w:p></w:body></w:document>'
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "found 0"):
            build_template_patch._replace_document_text(xml, [("跨段", "不应替换")])

    def test_render_timeout_is_reported_as_failed_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-render-timeout-") as temp_name:
            output = Path(temp_name)
            (output / "教案01_示例.docx").write_bytes(b"docx")
            timeout = subprocess.TimeoutExpired(["soffice"], 1)
            with patch.object(render_qa, "find_renderer", return_value="soffice"):
                with patch.object(render_qa.subprocess, "run", side_effect=timeout):
                    report = render_qa.render_docx_directory(output, timeout=1)
            self.assertEqual(report["status"], "failed")
            self.assertIn("timed out after 1s", report["errors"][0])

    def test_output_and_render_qa_reject_docx_symlinks_without_opening_or_rendering(self) -> None:
        data = json.loads(
            (ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="lesson-symlink-qa-") as temp_name:
            output = Path(temp_name) / "output"
            output.mkdir()
            expected_name = validate_output.lesson_filename(
                1, data["lessons"][0]["unit"], data["lessons"][0]["task"]
            )
            fake_docx = Mock()
            fake_docx.name = expected_name
            fake_docx.is_symlink.return_value = True
            with patch.object(validate_output.Path, "glob", return_value=[fake_docx]):
                with patch.object(validate_output, "Document", side_effect=AssertionError("DOCX target opened")) as document:
                    with self.assertRaisesRegex(RuntimeError, "target was not opened"):
                        validate_output.validate_output_dir(output, data)
            document.assert_not_called()

            fake_render_docx = Mock()
            fake_render_docx.name = "lesson.docx"
            fake_render_docx.is_symlink.return_value = True
            with patch.object(render_qa.Path, "glob", return_value=[fake_render_docx]):
                with patch.object(render_qa, "find_renderer", return_value="soffice"):
                    with patch.object(render_qa.subprocess, "run") as run:
                        report = render_qa.render_docx_directory(output)
            self.assertEqual(report["status"], "failed")
            self.assertIn("not rendered or opened", report["errors"][0])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
