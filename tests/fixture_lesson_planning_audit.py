"""Fixture task/output planning checks; lexical signals are only heuristics."""

from __future__ import annotations

import copy
import json
import unittest

from tests.fixture_lesson_plans import AUTHORED_PLANS
from tests.fixture_scope_plans import SCOPE_PLANS
from tests.synthetic_lesson_content_v2_acceptance import _lesson


def body_without_planning_evidence(payload: dict) -> list[tuple[str, str]]:
    """Flag obvious fixture drift using lexical planning consistency signals.

    Lexical overlap cannot prove complete semantic scope or production course
    authority. Future Semantic Scope Review owns free-text semantic judgment.
    """
    from tests.test_lesson_content_v2 import lesson_content_quality as content_quality
    missing = []
    for lesson, row in zip(payload['lessons'], payload['outline'], strict=True):
        nodes = [(f'teaching_content[{i}]', value) for i, value in enumerate(lesson['teaching_content'])]
        for field in ('key_point', 'difficult_point'):
            nodes.extend((f'{field}.content[{i}]', value) for i, value in enumerate(lesson[field]['content']))
        for node_id, value in nodes:
            evidence = [content_quality._progression_anchor_evidence(value, row[f]) for f in ('task', 'deliverable', 'next_bridge')]
            # Existing lexical extraction is only a fixture consistency signal;
            # overlap with the planning snapshot is not semantic authorization.
            if not any(e['substantive_residuals'] or e['acronym_matches'] for e in evidence):
                missing.append((lesson['lesson_id'], node_id))
    return missing


class LessonFixturePlanningTests(unittest.TestCase):
    def test_full_fixture_evaluation_remarks_satisfy_content_contract(self):
        from tests.synthetic_lesson_content_v2_acceptance import synthetic_plan_from_brief
        from tests.test_lesson_content_v22 import (
            DB_SPECS, SOFTWARE_SPECS, make_v22_payload, lesson_content_quality,
            lesson_package_common,
        )
        from tests.test_lesson_content_v23 import _bind_v23
        schema = json.loads(lesson_package_common.DEFAULT_SCHEMA.read_text(encoding='utf-8'))
        remark_schema = schema['$defs']['evaluation']['properties']['remarks']['properties']

        historical = synthetic_plan_from_brief(
            '课程：《数据库技术》\n专业：软件技术\n总课时：36\n每次：2学时'
        )
        fixtures = [('database', historical)]
        for name, specs in (('data-structures', DB_SPECS), ('software-modeling', SOFTWARE_SPECS)):
            current = make_v22_payload(theory_hours=len(specs) * 2, specs=specs)
            fixtures.append((name, current))
            revised = copy.deepcopy(current)
            _bind_v23(revised, mode='theory_only', theory_hours=revised['total_hours'], practice_hours=0)
            fixtures.append((name, revised))

        for name, payload in fixtures:
            with self.subTest(fixture=name, version=payload['content_contract_version']):
                lesson_package_common.validate_test_fixture_content_v2_input(payload)
                report = lesson_content_quality.assess_content_quality(payload)
                remark_errors = [error for error in report['errors']
                                 if 'evaluation.remarks.' in error]
                self.assertEqual(remark_errors, [], remark_errors)
                # Diagnostics use the production measurement and reported limit,
                # rather than duplicating the density validator's semantics.
                for lesson in payload['lessons']:
                    for criterion, text in lesson['evaluation']['remarks'].items():
                        actual = lesson_content_quality._meaningful_length(text)
                        with self.subTest(lesson_id=lesson['lesson_id'], criterion=criterion,
                                          actual_length=actual):
                            limit = report['coverage'].get(
                                'evaluation_remark_contract_limit', remark_schema[criterion]['maxLength'])
                            self.assertLessEqual(actual, limit)

    def test_current_instruction_is_invariant_under_lesson_ordinal(self):
        # Moving a plan must not turn its teaching into logs, transactions or
        # backup drills. Compare all current teaching fields.
        plans = [(p.task, p.artifact) for p in SCOPE_PLANS]
        plans.append(('测试给定的当前任务', '测试当前成果记录'))
        for task, artifact in plans:
            expected = None
            for index in (1, 8, 12, 14, 35):
                lesson = _lesson(course='测试', major='测试', audience='测试', index=index,
                    unit='既定单元', task=task, focus='历史规划标签', artifact=artifact,
                    next_focus='未来课专用标签', next_task='未来课任务', previous_artifact=None, score=90)
                current = {f: lesson[f] for f in ('teaching_content', 'key_point',
                    'difficult_point', 'student_analysis', 'goals', 'implementation',
                    'evaluation', 'reflection', 'teaching_methods', 'resources')}
                with self.subTest(task=task, index=index):
                    if expected is None:
                        expected = current
                    self.assertEqual(current, expected)

    def test_future_task_and_focus_do_not_author_current_body(self):
        from tests.test_lesson_content_v22 import DB_SPECS
        unit, task, focus, artifact, _ = DB_SPECS[13]
        def build(next_task, next_focus):
            return _lesson(course='测试', major='测试', audience='测试', index=14,
                unit=unit, task=task, focus=focus, artifact=artifact,
                next_task=next_task, next_focus=next_focus, previous_artifact='需求拆解清单', score=90)
        current = build('评估操作复杂度与性能', '复杂度评估')
        adversarial = build('另一个未分配的新任务', '未来课专用标签')
        self.assertNotEqual(current['progression']['next_bridge'], adversarial['progression']['next_bridge'])
        for field in ('teaching_content', 'key_point', 'difficult_point', 'goals',
                      'implementation', 'reflection', 'student_analysis'):
            self.assertEqual(current[field], adversarial[field])
        self.assertIn('线性与非线性结构', current['teaching_content'][0])
        self.assertNotIn('性能', ' '.join(current['teaching_content']))

    def test_canonical_scope_plans_match_current_frozen_task_and_output(self):
        from tests.test_lesson_content_v22 import DB_SPECS, SOFTWARE_SPECS, make_v22_payload
        plans = {p.task: p for p in SCOPE_PLANS}
        self.assertEqual(len(plans), len(SCOPE_PLANS))
        for specs in (DB_SPECS, SOFTWARE_SPECS):
            payload = make_v22_payload(theory_hours=len(specs)*2, specs=specs)
            for lesson, row in zip(payload['lessons'], payload['outline'], strict=True):
                if row['task'] not in plans:
                    self.assertIn(row['task'], {p['task'] for p in AUTHORED_PLANS})
                    continue
                plan = plans[row['task']]
                with self.subTest(task=row['task']):
                    self.assertEqual(row['deliverable'].removesuffix('成果'), plan.artifact)
                    self.assertEqual(lesson['teaching_content'][0], plan.introduction)
                    self.assertEqual(lesson['teaching_content'][1],
                        f'示范形成{plan.artifact}的关键步骤，说明产物如何回应“{plan.task}”的要求。')
                    self.assertEqual(lesson['teaching_content'][2], plan.practice)
                    self.assertEqual(lesson['key_point']['content'], [plan.key])
                    self.assertEqual(lesson['difficult_point']['content'], [plan.difficulty])

    def test_scope_factory_rejects_another_lessons_output(self):
        plan = SCOPE_PLANS[0]
        with self.assertRaisesRegex(ValueError, 'output conflicts'):
            _lesson(course='测试', major='测试', audience='测试', index=1,
                unit='既定单元', task=plan.task, focus='规划标签', artifact='另一课的成果',
                next_focus='未来', next_task='未来任务', previous_artifact=None, score=90)

    def test_canonical_full_bodies_have_planning_evidence(self):
        from tests.test_lesson_content_v22 import DB_SPECS, SOFTWARE_SPECS, make_v22_payload
        for specs in (DB_SPECS, SOFTWARE_SPECS):
            with self.subTest(specs=specs):
                payload = make_v22_payload(theory_hours=len(specs)*2, specs=specs)
                self.assertEqual(body_without_planning_evidence(payload), [])

    def test_audit_detects_unsourced_body_insertion(self):
        from tests.test_lesson_content_v22 import make_v22_payload
        payload = make_v22_payload(theory_hours=36)
        plan = AUTHORED_PLANS[0]
        lesson = next(l for l in payload['lessons'] if l['task'] == plan['task'])
        lesson['key_point']['content'][0] = '独立讲授患者血压测量及输液护理判断。'
        self.assertIn((lesson['lesson_id'], 'key_point.content[0]'), body_without_planning_evidence(payload))

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
