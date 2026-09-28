from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_lesson_content_v23 import (
    LESSON,
    _integrated_64,
    _validate_v23,
    lesson_acceptance,
    lesson_content_contract,
    lesson_generator,
    run_script,
)
from render_qa import find_renderer


ROOT = Path(__file__).resolve().parents[1]


class LessonReleaseScaleE2ETests(unittest.TestCase):
    def test_64_hour_generator_retains_and_verifies_32_docx_and_pdfs(self) -> None:
        renderer = find_renderer()
        if renderer is None:
            if os.environ.get("LESSON_RELEASE_RENDER_REQUIRED") == "1":
                self.fail("the release render lane requires LibreOffice")
            self.skipTest("LibreOffice is not installed")

        payload = _integrated_64(workorders=True)
        _validate_v23(payload)
        source_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        expected_docx = [
            lesson_content_contract.lesson_filename(index, item["unit"], item["task"])
            for index, item in enumerate(payload["lessons"], 1)
        ]
        expected_pdf = [f"render/pdf/{Path(name).stem}.pdf" for name in expected_docx]

        with tempfile.TemporaryDirectory(prefix="lesson-64h-release-e2e-") as temp_name:
            root = Path(temp_name)
            source = root / "lesson-content.json"
            output = root / "output"
            source.write_bytes(source_bytes)
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--render",
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)

            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            docx_paths = sorted(output.glob("*.docx"))
            pdf_paths = sorted((output / "render" / "pdf").glob("*.pdf"))
            records = manifest["artifacts"]

            self.assertEqual(qa["status"], "passed", qa)
            self.assertEqual(qa["production_status"], "production_pass", qa)
            self.assertEqual(qa["render"]["status"], "passed", qa["render"])
            self.assertEqual(qa["required_anchor_count"], 70)
            self.assertEqual(qa["preserved_anchor_count"], 70)
            self.assertEqual(qa["checks"]["anchors"]["required"], 70)
            self.assertEqual(qa["checks"]["anchors"]["preserved"], 70)
            self.assertEqual(qa["render"]["files_checked"], 32)
            self.assertEqual(len(docx_paths), 32)
            self.assertEqual(len({path.name for path in docx_paths}), 32)
            self.assertEqual([path.name for path in docx_paths], expected_docx)
            self.assertEqual(len(pdf_paths), 32)
            self.assertEqual(len({path.name for path in pdf_paths}), 32)
            self.assertEqual([path.relative_to(output).as_posix() for path in pdf_paths], expected_pdf)
            self.assertEqual(len(records), 32)
            self.assertEqual([record["lesson_id"] for record in records], [f"L{index:02d}" for index in range(1, 33)])
            self.assertEqual([record["final_docx_path"] for record in records], expected_docx)
            self.assertEqual([record["final_pdf_path"] for record in records], expected_pdf)
            self.assertTrue(all(record["actual_pdf_page_count"] > 0 for record in records))
            self.assertTrue(all(record["final_pdf_sha256"] for record in records))
            for record in records:
                pdf = output / record["final_pdf_path"]
                self.assertEqual(
                    hashlib.sha256(pdf.read_bytes()).hexdigest().upper(),
                    record["final_pdf_sha256"].upper(),
                )

            expected_files = {
                *expected_docx,
                *expected_pdf,
                "practice-task-contract.json",
                "qa-report.json",
                "artifact-manifest.json",
                "reference-evidence.json",
            }
            actual_files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(actual_files, expected_files)
            self.assertFalse(any("candidate" in path for path in actual_files))
            self.assertEqual(list(root.glob(f".{output.name}.candidate-*")), [])
            self.assertEqual(
                lesson_generator._verify_artifact_manifest(output, manifest, source),
                "production_pass",
            )
            inventory = {
                "docx_files": [path.relative_to(output).as_posix() for path in docx_paths],
                "docx_count": len(docx_paths),
            }
            acceptance = lesson_acceptance._artifact_manifest_gate(
                payload,
                qa,
                inventory,
                output,
                manifest,
                source,
            )
            self.assertEqual(acceptance["status"], "PASS", acceptance)
            self.assertEqual(acceptance["observed"]["records"], 32)

    def test_generator_failure_cleans_candidate_and_preserves_previous_output(self) -> None:
        payload = _integrated_64(workorders=True)
        _validate_v23(payload)
        with tempfile.TemporaryDirectory(prefix="lesson-failed-transaction-") as temp_name:
            root = Path(temp_name)
            source = root / "lesson-content.json"
            source.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            output = root / "output"
            output.mkdir()
            sentinel = output / "owner-existing-file.txt"
            sentinel.write_text("preserve existing published output\n", encoding="utf-8")

            with patch.dict(os.environ, {"LESSON_ALLOW_TEST_FIXTURE_AUTHORING": "1"}):
                with patch.object(
                    sys,
                    "argv",
                    [
                        str(LESSON / "scripts" / "generate_lesson_plans.py"),
                        "--tasks-json",
                        str(source),
                        "--output-dir",
                        str(output),
                        "--backup-existing",
                        "--allow-test-fixture-authoring",
                    ],
                ):
                    with patch.object(
                        lesson_generator,
                        "validate_output_dir",
                        side_effect=RuntimeError("injected output QA failure"),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "injected output QA failure"):
                            lesson_generator.main()

            self.assertEqual([path.name for path in output.iterdir()], [sentinel.name])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve existing published output\n")
            self.assertEqual(list(root.glob(f".{output.name}.candidate-*")), [])


if __name__ == "__main__":
    unittest.main()
