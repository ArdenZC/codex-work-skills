"""Fixture provenance checks independent of the candidate authority threshold."""

from __future__ import annotations

import copy
import unittest

from tests.fixture_lesson_plans import AUTHORED_PLANS
from tests.synthetic_lesson_content_v2_acceptance import _lesson


def body_without_direct_evidence(payload: dict) -> list[tuple[str, str]]:
    from tests.test_lesson_content_v2 import lesson_content_quality as content_quality
    missing = []
    for lesson, row in zip(payload['lessons'], payload['outline'], strict=True):
        nodes = [(f'teaching_content[{i}]', value) for i, value in enumerate(lesson['teaching_content'])]
        for field in ('key_point', 'difficult_point'):
            nodes.extend((f'{field}.content[{i}]', value) for i, value in enumerate(lesson[field]['content']))
        for node_id, value in nodes:
            evidence = [content_quality._progression_anchor_evidence(value, row[f]) for f in ('task', 'deliverable', 'next_bridge')]
            # Existence audit only: this never applies the candidate's length,
            # multiplicity, frequency or short-core PASS threshold.
            if not any(e['substantive_residuals'] or e['acronym_matches'] for e in evidence):
                missing.append((lesson['lesson_id'], node_id))
    return missing


class LessonFixturePlanningTests(unittest.TestCase):
    def test_canonical_full_bodies_have_frozen_evidence_without_candidate_threshold(self):
        from tests.test_lesson_content_v22 import DB_SPECS, SOFTWARE_SPECS, make_v22_payload
        for specs in (DB_SPECS, SOFTWARE_SPECS):
            with self.subTest(specs=specs):
                payload = make_v22_payload(theory_hours=len(specs)*2, specs=specs)
                self.assertEqual(body_without_direct_evidence(payload), [])

    def test_audit_detects_unsourced_body_insertion(self):
        from tests.test_lesson_content_v22 import make_v22_payload
        payload = make_v22_payload(theory_hours=36)
        plan = AUTHORED_PLANS[0]
        lesson = next(l for l in payload['lessons'] if l['task'] == plan['task'])
        lesson['key_point']['content'][0] = '独立讲授患者血压测量及输液护理判断。'
        self.assertIn((lesson['lesson_id'], 'key_point.content[0]'), body_without_direct_evidence(payload))

    def test_authored_plan_selection_uses_task_and_output_not_lesson_number(self):
        for plan in AUTHORED_PLANS:
            for index in (1, 11):
                with self.subTest(task=plan['task'], index=index):
                    lesson = _lesson(course='规划一致性测试', major='测试专业', audience='测试对象', index=index,
                        unit='已有任务单元', task=plan['task'], focus=plan['focus'], artifact=plan['artifact'],
                        next_focus='后续任务', next_task='实施后续任务', previous_artifact=None, score=90)
                    self.assertEqual(lesson['teaching_content'], plan['teaching_content'])
                    self.assertEqual(len(lesson['implementation']), len(plan['stages']))

    def test_authored_factory_rejects_stale_focus_or_output(self):
        plan = AUTHORED_PLANS[0]
        for focus, artifact in (('错误迁入的主题', plan['artifact']), (plan['focus'], '别课产出')):
            with self.subTest(focus=focus, artifact=artifact), self.assertRaisesRegex(ValueError, 'conflicts'):
                _lesson(course='测试', major='测试', audience='测试', index=1, unit='测试', task=plan['task'],
                    focus=focus, artifact=artifact, next_focus='后续', next_task='后续任务', previous_artifact=None, score=90)

    def test_plan_prose_is_not_mutated_by_generated_fixture(self):
        from tests.test_lesson_content_v22 import make_v22_payload
        expected = copy.deepcopy(AUTHORED_PLANS)
        payload = make_v22_payload(theory_hours=36)
        for lesson in payload['lessons']:
            if lesson['task'] in {p['task'] for p in AUTHORED_PLANS}:
                lesson['teaching_content'][0] = '修改生成结果'
                lesson['key_point']['content'][0] = '修改生成结果'
        self.assertEqual(AUTHORED_PLANS, expected)

    def test_neighbor_bridges_come_from_next_planned_task_and_focus(self):
        from tests.test_lesson_content_v22 import DB_SPECS, make_v22_payload
        payload = make_v22_payload(theory_hours=36)
        for index in range(3, 7):
            current, following = payload['lessons'][index:index+2]
            planned = DB_SPECS[index+1]
            self.assertEqual(current['progression']['next_bridge'],
                f"下一课以{DB_SPECS[index][3]}为输入，{planned[1]}，重点衔接{planned[2]}")
            self.assertIn(following['task'], current['progression']['next_bridge'])
            self.assertIn(planned[2], following['progression']['prior_learning'])
            self.assertEqual(current['progression']['next_bridge'], payload['outline'][index]['next_bridge'])


if __name__ == '__main__':
    unittest.main()
