from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import check_skill_facades  # noqa: E402
import generate_work_orders as generator  # noqa: E402
import install_adapters as adapters  # noqa: E402
from content_contract import (  # noqa: E402
    WorkOrderContractError,
    load_practice_task_contract,
    practice_tasks_to_authoring_skeleton,
    practice_tasks_to_content,
)
from content_quality import validate_content  # noqa: E402
from cross_artifact_quality import validate_cross_artifact  # noqa: E402
from generate_work_orders import DEFAULT_TEMPLATE, generate  # noqa: E402
from install import install as install_skill  # noqa: E402
from validate_output import validate_document  # noqa: E402


def _handoff() -> dict:
    return {
        "contract_version": "1.0",
        "course_name": "数据库技术",
        "practice_hours": 2,
        "granularity": "per_task",
        "tasks": [
            {
                "task_id": "PT-HARD-01",
                "project_id": "P-HARD-01",
                "title": "设计客户订单数据模型",
                "lesson_ids": ["L03", "L04"],
                "practice_hours": 2,
                "scenario": "根据客户订单业务资料设计数据模型。",
                "objectives": ["识别业务对象和关系"],
                "required_inputs": ["订单业务说明"],
                "tools_or_materials": ["建模工具", "订单业务说明", "模型检查表"],
                "steps": ["分析业务对象", "绘制模型并记录依据"],
                "deliverables": ["概念模型图", "模型说明页"],
                "acceptance_criteria": ["概念模型图和模型说明页保持实体关系一致"],
                "safety_or_compliance": ["遵守数据保密要求"],
            }
        ],
    }


def _content() -> dict:
    value = json.loads(
        (ROOT / "examples" / "software.example.json").read_text(encoding="utf-8")
    )[0]
    value["practice_task_id"] = "PT-HARD-01"
    value["task_title"] = value["project_name"]
    value["project_id"] = "P-HARD-01"
    value["safety_or_compliance"] = ["遵守数据保密要求"]
    return value


def _handoff_for_content(content: dict) -> dict:
    deliverables = [
        value
        for item in content["task_items"]
        for value in item["deliverables"]
    ]
    criteria = [
        value
        for item in content["task_items"]
        for value in item["acceptance_criteria"]
    ]
    return {
        "contract_version": "1.0",
        "course_name": content["course_name"],
        "practice_hours": content["practice_hours"],
        "granularity": "per_task",
        "tasks": [
            {
                "task_id": content["practice_task_id"],
                "project_id": content["project_id"],
                "title": content["task_title"],
                "lesson_ids": content["lesson_ids"],
                "practice_hours": content["practice_hours"],
                "scenario": "根据业务说明完成建模实践。",
                "objectives": ["完成业务模型设计"],
                "required_inputs": ["业务说明"],
                "tools_or_materials": ["建模工具", "订单业务说明", "模型检查表"],
                "steps": ["分析业务对象", "绘制模型并记录依据"],
                "deliverables": deliverables,
                "acceptance_criteria": criteria,
                "safety_or_compliance": content["safety_or_compliance"],
            }
        ],
    }


class WorkOrderPhase21HardeningTests(unittest.TestCase):
    def test_agent_boundary_handoff_only_never_generates_content_or_docx(self) -> None:
        handoff = _handoff()
        with tempfile.TemporaryDirectory(prefix="workorder-handoff-boundary-") as temp_name:
            root = Path(temp_name)
            handoff_path = root / "practice-task-contract.json"
            skeleton_path = root / "authoring-skeleton.json"
            handoff_path.write_text(json.dumps(handoff, ensure_ascii=False), encoding="utf-8")
            loaded = load_practice_task_contract(handoff_path)
            skeleton = practice_tasks_to_authoring_skeleton(loaded)
            self.assertEqual(skeleton[0]["practice_task_id"], "PT-HARD-01")
            self.assertNotIn("task_items", skeleton[0])
            self.assertNotIn("score", skeleton[0])
            with self.assertRaises(WorkOrderContractError):
                practice_tasks_to_content(
                    loaded,
                    major="软件技术",
                    class_or_audience="高职一年级",
                )

            output_dir = root / "formal-output"
            with redirect_stdout(io.StringIO()) as captured:
                exit_code = generator.main(
                    [
                        "--practice-task-json",
                        str(handoff_path),
                        "--authoring-skeleton-output",
                        str(skeleton_path),
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )
            report = json.loads(captured.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["status"], "handoff_ready")
            self.assertFalse(report["docx_generated"])
            self.assertTrue(skeleton_path.is_file())
            self.assertFalse(output_dir.exists())
            self.assertFalse(any(root.rglob("*.docx")))

    def test_agent_decided_non_mechanical_scores_are_valid(self) -> None:
        content = _content()
        for item, score in zip(content["task_items"], (20, 40, 30)):
            item["score"] = score
        report = validate_content(content)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["metrics"]["task_score"], 90)
        self.assertEqual([item["score"] for item in content["task_items"]], [20, 40, 30])
        self.assertNotEqual([item["score"] for item in content["task_items"]], [30, 30, 30])

    def test_each_substantive_deliverable_needs_acceptance_coverage(self) -> None:
        content = _content()
        item = content["task_items"][0]
        item["deliverables"] = ["概念模型图", "关系模式设计表", "实验报告"]
        item["acceptance_criteria"] = [
            "概念模型图和关系模式设计表的实体、主键及关系映射一致",
            "实验报告记录设计依据和核验结论",
        ]
        self.assertEqual(validate_content(content)["status"], "pass")

        missing = copy.deepcopy(content)
        missing["task_items"][0]["acceptance_criteria"] = [
            "概念模型图和关系模式设计表的实体、主键及关系映射一致"
        ]
        missing_report = validate_content(missing)
        self.assertEqual(missing_report["status"], "fail")
        self.assertTrue(
            any(
                "PT-HARD-01" in error
                and "实验报告" in error
                and "category=acceptance" in error
                for error in missing_report["errors"]
            ),
            missing_report,
        )

        generic = copy.deepcopy(content)
        generic["task_items"][0]["acceptance_criteria"] = ["认真完成任务", "符合要求"]
        generic_report = validate_content(generic)
        self.assertEqual(generic_report["categories"]["acceptance"], "fail")

    def test_cross_artifact_preserves_every_upstream_tool_material(self) -> None:
        content = _content()
        handoff = _handoff_for_content(content)
        for item in content["task_items"]:
            item["tools_or_materials"] = list(handoff["tasks"][0]["tools_or_materials"])
        report = validate_cross_artifact(handoff, content)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["checks"]["tools_materials_preservation"]["status"], "pass")

        missing = copy.deepcopy(content)
        missing["task_items"] = [
            {
                **item,
                "tools_or_materials": ["订单业务说明", "模型检查表"],
            }
            for item in missing["task_items"]
        ]
        missing_report = validate_cross_artifact(handoff, missing)
        self.assertEqual(missing_report["status"], "fail")
        self.assertIn("missing upstream tool/material: 建模工具", " ".join(missing_report["errors"]))

    def test_batch_output_qa_failure_rolls_back_before_publication(self) -> None:
        contents = json.loads(
            (ROOT / "examples" / "software.example.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="workorder-batch-output-rollback-") as temp_name:
            root = Path(temp_name)
            output_dir = root / "published"
            original_validate = generator.validate_document

            def validate_with_third_failure(path: Path, content: dict) -> dict:
                validate_with_third_failure.calls += 1
                if validate_with_third_failure.calls == 3:
                    return {"status": "fail", "errors": ["injected third Output QA failure"]}
                return original_validate(path, content)

            validate_with_third_failure.calls = 0
            with patch.object(generator, "validate_document", side_effect=validate_with_third_failure):
                with self.assertRaisesRegex(WorkOrderContractError, "Output QA failed"):
                    generate(contents, output_dir=output_dir, template=DEFAULT_TEMPLATE)
            self.assertFalse(output_dir.exists())
            self.assertEqual(list(root.glob(".published.batch-*")), [])
            self.assertEqual(list(root.rglob("*.docx")), [])

    def test_batch_render_failure_rolls_back_before_publication(self) -> None:
        contents = json.loads(
            (ROOT / "examples" / "software.example.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="workorder-batch-render-rollback-") as temp_name:
            root = Path(temp_name)
            output_dir = root / "published"
            render_reports = [
                {"status": "pass", "pages": 1, "pdf": "candidate.pdf"},
                {"status": "pass", "pages": 1, "pdf": "candidate.pdf"},
                {"status": "fail", "reason": "injected third render failure"},
            ]
            with patch.object(
                generator,
                "_render_optional",
                side_effect=render_reports,
            ):
                with self.assertRaisesRegex(WorkOrderContractError, "Render QA failed"):
                    generate(contents, output_dir=output_dir, template=DEFAULT_TEMPLATE, render=True)
            self.assertFalse(output_dir.exists())
            self.assertEqual(list(root.glob(".published.batch-*")), [])
            self.assertEqual(list(root.rglob("*.docx")), [])

    def test_batch_failure_preserves_existing_formal_bytes(self) -> None:
        contents = json.loads(
            (ROOT / "examples" / "software.example.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="workorder-batch-existing-") as temp_name:
            root = Path(temp_name)
            output_dir = root / "published"
            output_dir.mkdir()
            old_files = {}
            for content in contents:
                path = output_dir / f"{content['practice_task_id']}_{content['project_name']}.docx"
                payload = f"old-{path.name}".encode("utf-8")
                path.write_bytes(payload)
                old_files[path] = payload
            unrelated = output_dir / "keep.txt"
            unrelated.write_bytes(b"unrelated")

            original_validate = generator.validate_document

            def validate_with_third_failure(path: Path, content: dict) -> dict:
                validate_with_third_failure.calls += 1
                if validate_with_third_failure.calls == 3:
                    return {"status": "fail", "errors": ["injected third Output QA failure"]}
                return original_validate(path, content)

            validate_with_third_failure.calls = 0
            with patch.object(generator, "validate_document", side_effect=validate_with_third_failure):
                with self.assertRaises(WorkOrderContractError):
                    generate(contents, output_dir=output_dir, template=DEFAULT_TEMPLATE, replace=True)
            for path, payload in old_files.items():
                self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(unrelated.read_bytes(), b"unrelated")
            self.assertEqual(list(root.glob(f".{output_dir.name}.batch-*")), [])

    def test_render_skipped_is_failure_when_render_is_requested(self) -> None:
        content = _content()
        with tempfile.TemporaryDirectory(prefix="workorder-render-strict-") as temp_name:
            with patch.object(
                generator,
                "_render_optional",
                return_value={"status": "skipped", "reason": "no renderer"},
            ):
                with self.assertRaisesRegex(WorkOrderContractError, "status=skipped"):
                    generate(
                        [content],
                        output_dir=Path(temp_name) / "published",
                        template=DEFAULT_TEMPLATE,
                        render=True,
                    )

    def test_cross_artifact_hard_negative_does_not_match_common_two_character_words(self) -> None:
        content = _content()
        handoff = _handoff_for_content(content)
        task = handoff["tasks"][0]
        task["title"] = "完成任务"
        content["task_title"] = "检查系统"
        content["project_name"] = "检查系统"
        task["deliverables"] = ["数据表"]
        content["task_items"][0]["deliverables"] = ["记录表"]
        task["acceptance_criteria"] = ["完成任务"]
        content["task_items"][0]["acceptance_criteria"] = ["检查系统"]
        report = validate_cross_artifact(handoff, content)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("task_title_intent" in error for error in report["errors"]))

    def test_lesson_workorder_orchestration_and_unavailable_fallback_are_contractual(self) -> None:
        sources = [
            ROOT.parents[1] / "教案生成器" / "lesson-plan-docx-generator" / name
            for name in ("SKILL.md", "通用提示词.md", "AGENTS.md", Path("agents") / "openai.yaml")
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertIn("practice_work_orders=true", text)
        self.assertIn("调用 WorkOrder Skill", text)
        self.assertIn("WorkOrder Skill unavailable; handoff generated.", text)
        self.assertIn("不得 subprocess 调用 WorkOrder Python", text)
        self.assertIn("不伪造工单 DOCX", text)
        self.assertIn("practice_work_orders", text)
        self.assertNotIn("无条件调用 WorkOrder", text)

    def test_vague_steps_fail_and_action_object_steps_pass(self) -> None:
        vague = _content()
        vague["task_items"][0]["steps"] = ["认真操作", "检查结果", "完成任务"]
        self.assertEqual(validate_content(vague)["categories"]["executability"], "fail")
        concrete = _content()
        concrete["task_items"][0]["steps"] = ["执行 SQL 脚本", "检查查询结果", "提交截图"]
        self.assertEqual(validate_content(concrete)["status"], "pass", validate_content(concrete))

    def test_installer_backup_policy_is_shared_and_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workorder-backup-policy-") as temp_name:
            root = Path(temp_name)
            skills_dir = root / "skills"
            install_skill(ROOT, skills_dir)
            install_skill(ROOT, skills_dir, replace=True)
            self.assertEqual(list(skills_dir.glob("practice-task-workorder-generator_backup_*")), [])
            install_skill(ROOT, skills_dir, replace=True, keep_backup=True)
            self.assertEqual(len(list(skills_dir.glob("practice-task-workorder-generator_backup_*"))), 1)

            project = root / "project"
            adapters.install(ROOT, project, adapters=["agents"])
            adapters.install(ROOT, project, adapters=["agents"], replace=True)
            self.assertEqual(list(project.glob("*.backup_*")), [])
            adapters.install(ROOT, project, adapters=["agents"], replace=True, keep_backup=True)
            self.assertEqual(len(list(project.glob("*.backup_*"))), 1)

    def test_workorder_facade_and_versions_are_aligned(self) -> None:
        self.assertEqual(check_skill_facades.check(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
