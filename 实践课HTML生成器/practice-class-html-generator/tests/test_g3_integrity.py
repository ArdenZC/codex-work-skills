"""Synthetic regressions; no blind holdout fixtures or answers."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
sys.path.insert(0,str(SCRIPTS.parents[2]/'HTML课件生成器'/'courseware-html-generator'/'scripts'))
from apply_reference_gaps import apply_asset_gaps
from reference_behavior import verify_checks, control_flow
from classroom_integrity import closure, prepare_assets, write_asset, reference_gate, package_links
from formula_truth import verify_formula, verify_formulas
from planning_integrity import review_batch, automatic_scores
from render_practice import _teacher_behavior_evidence, _teacher_formula_evidence

class Integrity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def function(self,source):
        (self.root/'module.py').write_text(source,encoding='utf-8')
        return verify_checks(self.root,{'checks':[{'id':'valid','verification_type':'function-call','entrypoint':'module.py','function':'check','args':['x'],'expected':{'equals':'ok'}}]})
    def test_T1_unreachable_behavior(self):
        source='def check(x):\n    return "error"\n    return "ok"\n'
        compile(source,'module','exec')
        self.assertTrue(control_flow(source))
        self.assertEqual(self.function(source)['status'],'REFERENCE_BEHAVIOR_FAIL')
    def test_T2_multibranch(self):
        self.assertEqual(self.function('def check(x):\n    if not x:\n        return "error"\n    return "ok"\n')['status'],'REFERENCE_PASS')
    def web(self,method,value,status,body):
        (self.root/'service.py').write_text('from flask import Flask, request\napp=Flask(__name__)\n@app.route("/probe",methods=["GET","POST"])\ndef probe():\n    x=request.values.get("value","")\n    if not x:\n        return "empty",400\n    return "accepted "+x,200\n',encoding='utf-8')
        c={'id':'request','verification_type':'web-request','entrypoint':'service.py','method':method,'path':'/probe','expected_status':status,'body_contains':[body]}
        c['query_string' if method=='GET' else 'data']={'value':value}
        return verify_checks(self.root,{'checks':[c]})
    def test_T3_get_empty(self): self.assertEqual(self.web('GET','',400,'empty')['status'],'REFERENCE_PASS')
    def test_T4_get_valid(self): self.assertEqual(self.web('GET','x',200,'accepted x')['status'],'REFERENCE_PASS')
    def test_T5_post_branches(self):
        for value,status,body in [('',400,'empty'),('x',200,'accepted x')]:
            self.assertEqual(self.web('POST',value,status,body)['status'],'REFERENCE_PASS')
    def patch(self):
        return apply_asset_gaps({'content':'def check(x):\n    # TODO-BEGIN branch\n    pass\n    # TODO-END branch\n','editable_gaps':[{'patch_kind':'replace-region','marker':'# TODO-BEGIN branch','end_marker':'# TODO-END branch','replacement':'if not x:\n    return "error"\nreturn "ok"','indent_policy':'inherit'}]})
    def test_T6_region(self):
        value,errors=self.patch(); self.assertFalse(errors); self.assertIn('if not x:',value)
    def test_T7_indent(self):
        value,_=self.patch(); self.assertIn('        return "error"',value); compile(value,'x','exec')
    def test_T8_patch_behavior(self): self.assertEqual(self.function(self.patch()[0])['status'],'REFERENCE_PASS')
    def bundle(self,template):
        (self.root/'app').mkdir(exist_ok=True)
        (self.root/'app'/'main.py').write_text('from flask import render_template\ndef page(): return render_template("entry.html")',encoding='utf-8')
        if template:
            (self.root/'app'/'templates').mkdir(); (self.root/'app'/'templates'/'entry.html').write_text('Form',encoding='utf-8')
        return {'starter_bundles':[{'id':'app','root':'app','entrypoint':'main.py','framework':'Flask','files':[{'path':'main.py','role':'student-edit'},{'path':'templates/entry.html','role':'runtime-required'}]}]}
    def test_T9_missing_template(self): self.assertEqual(closure(self.bundle(False),self.root)['status'],'FAIL')
    def test_T10_template_present(self): self.assertEqual(closure(self.bundle(True),self.root)['status'],'PASS')
    def test_T11_teacher_isolation(self):
        content={'starter_assets':[{'id':'secret','path':'test_secret.py','role':'test-only'}]}
        self.assertEqual(closure(content,self.root)['status'],'PASS')
        (self.root/'test_secret.py').write_text('secret')
        self.assertEqual(closure(content,self.root)['status'],'FAIL')
    def asset(self):
        (self.root/'raw.csv').write_bytes(b'x,y\r\n1,2\r\n')
        return {'classroom_assets':[{'id':'data','task_id':'t','title':'Data','source_path':'raw.csv','student_path':'data.csv','classification':'student-classroom-input','sha256':hashlib.sha256((self.root/'raw.csv').read_bytes()).hexdigest()}]}
    def test_T12_missing_classroom(self): self.assertEqual(closure(self.asset(),self.root)['status'],'FAIL')
    def test_T13_passthrough_bytes(self):
        content,lineage=prepare_assets(self.asset(),self.root)
        write_asset(content['starter_assets'][0],self.root/'data.csv',self.root)
        self.assertEqual((self.root/'raw.csv').read_bytes(),(self.root/'data.csv').read_bytes())
        self.assertEqual(closure(content,self.root)['status'],'PASS')
    def formula(self,text,field):
        (self.root/'table.csv').write_text('quantity,sales,customer_type\n2,900,重点\n10,100,普通\n',encoding='utf-8')
        return verify_formula({'id':'f','formula':text,'example_scope':'current-dataset','source_id':'table.csv','semantic_intent':'classify or count based on bound field','bindings':{'input_field':field},'operation_location':'C2'},self.root)
    def test_T14_wrong_classification_column(self): self.assertEqual(self.formula('=IF(A2>500,"重点","普通")','sales')['status'],'FAIL')
    def test_T15_correct_classification_column(self):
        r=self.formula('=IF(B2>500,"重点","普通")','sales'); self.assertEqual(r['status'],'PASS'); self.assertEqual(r['expected_result'],'重点')
    def test_T16_count_numeric(self): self.assertEqual(self.formula('=COUNTIF(B2:B3,"重点")','sales')['status'],'FAIL')
    def test_T17_count_labels(self):
        r=self.formula('=COUNTIF(C2:C3,"重点")','customer_type'); self.assertEqual(r['status'],'PASS'); self.assertEqual(r['expected_result'],1)
    def plan(self): return {'slides':[{'lecture_minutes':5,'activity_minutes':10,'speaker_script':'讲'*410,'activity_plan':{'type':'compare','segments':[{'minutes':5},{'minutes':5}]},'layout':'table'} for _ in range(8)]}
    def test_T18_overfit(self): self.assertTrue(review_batch([self.plan() for _ in range(3)])['template_overfit_warning'])
    def test_T19_adaptive(self):
        c=[self.plan() for _ in range(3)]; c[1]['slides'][0]['lecture_minutes']=8
        for s in c[2]['slides']: s['speaker_script']='解释'*330
        self.assertFalse(review_batch(c)['template_overfit_warning'])
    def test_T20_degraded_score(self): self.assertLess(automatic_scores({},[{'status':'DEGRADED'}])['pedagogical'],30)
    def test_T21_syntax_not_behavior(self): self.assertLess(automatic_scores({'reference_behavior':'FAIL'},[])['objective_dimensions']['reference_behavior'],5)
    def test_syntax_only_rejected(self):
        (self.root/'a.py').write_text('x=1')
        self.assertEqual(verify_checks(self.root,{'checks':[{'id':'s','verification_type':'syntax','path':'a.py'}]})['status'],'REFERENCE_BEHAVIOR_FAIL')
    def test_manual_honesty(self):
        r=verify_checks(self.root,{'checks':[{'id':'m','verification_type':'manual-evidence','observation':'Inspect tool route','procedure':'Open and trace','expected_result':'Declared route is visible'}]})
        self.assertEqual(r['status'],'MANUAL_EVIDENCE_DEFINED')
    def test_aggregates(self):
        for text,result in [('=SUM(B2:B3)',1000),('=AVERAGE(B2:B3)',500),('=SUMIF(B2:B3,">500")',900)]:
            self.assertEqual(self.formula(text,'sales')['expected_result'],result)
    def test_reference_gate_rejects_without_output(self):
        c={'starter_assets':[{'id':'a','path':'main.py','content':'def check(x): return "wrong"'}],'tasks':[{'id':'t','task_kind':'implementation','starter_asset_ids':['a'],'reference_verification':{'checks':[{'id':'f','verification_type':'function-call','entrypoint':'main.py','function':'check','args':['x'],'expected':{'equals':'ok'}}]}}]}
        out=self.root/'out'; self.assertEqual(reference_gate(c,output_dir=out)['status'],'FAIL'); self.assertFalse(out.exists())
    def test_no_links_escape(self):
        (self.root/'student.html').write_text('<a href="../teacher/answer.html">answer</a>')
        self.assertEqual(package_links(self.root)['status'],'FAIL')
    def test_other_patch_kinds(self):
        for kind,expected in [('replace-line','b\n'),('insert-before','b\n# mark\n'),('insert-after','# mark\nb\n')]:
            value,errors=apply_asset_gaps({'content':'# mark\n','editable_gaps':[{'marker':'# mark','replacement':'b','patch_kind':kind}]})
            self.assertFalse(errors); self.assertEqual(value,expected)
        value,errors=apply_asset_gaps({'content':'','editable_gaps':[{'patch_kind':'add-file','replacement':'new'}]})
        self.assertEqual((value,errors),('new',[]))
    def test_query_and_structured_adapters(self):
        (self.root/'setup.sql').write_text('CREATE TABLE points(n); INSERT INTO points VALUES (3),(8);')
        (self.root/'data.json').write_text('{"n":11}')
        checks=[{'id':'sql','verification_type':'query-result','setup_file':'setup.sql','query':'SELECT SUM(n) FROM points','expected':{'rows':[[11]]}}, {'id':'data','verification_type':'structured-data','path':'data.json','expected':{'equals':{'n':11}}}]
        self.assertEqual(verify_checks(self.root,{'checks':checks})['status'],'REFERENCE_PASS')
    def test_unregistered_formula_rejected(self):
        self.assertEqual(verify_formulas({'slides':[{'formula':'=SUM(B2:B3)'}]},self.root)['status'],'FAIL')
    def test_semantic_binding_and_assertion_required(self):
        self.assertEqual(self.formula('=SUM(B2:B3)','quantity')['status'],'FAIL')
        (self.root/'module.py').write_text('def check(): return 1')
        report=verify_checks(self.root,{'checks':[{'id':'f','verification_type':'function-call','entrypoint':'module.py','function':'check'}]})
        self.assertEqual(report['status'],'REFERENCE_BEHAVIOR_FAIL')

    def test_teacher_evidence_hides_machine_metadata(self):
        content={'tasks':[{'id':'task-demo','title':'示例任务'}]}
        behavior={'checks':[{'id':'check-demo','task_id':'task-demo','verification_type':'web-request','passed':True,'status_code':200,'json':{'task_id':'task-demo','message':'ok'}}]}
        formula={'task_id':'task-demo','formula':'=SUM(B2:B3)','bindings':{'input_field':'sales','output_field':'total'},'operation_location':'C2','expected_result':12}
        behavior_html=_teacher_behavior_evidence(content, behavior)
        formula_html=_teacher_formula_evidence(content, formula)
        rendered=behavior_html+formula_html
        self.assertNotIn('task_id', rendered)
        self.assertNotIn('task-demo', rendered)
        self.assertIn('公式', rendered)
        self.assertIn('当前数据期望结果', rendered)

    def test_T1_manual_evidence_defined_is_waiting_for_classroom_check(self):
        rendered = _teacher_behavior_evidence({}, {'checks': [{'verification_type': 'manual-evidence', 'status': 'MANUAL_EVIDENCE_DEFINED'}]})
        self.assertIn('待课堂人工核对', rendered)
        self.assertNotIn('未通过', rendered)

    def test_T2_automated_unavailable_preserves_manual_acceptance_boundary(self):
        rendered = _teacher_behavior_evidence({}, {'checks': [{'verification_type': 'browser', 'status': 'AUTOMATED_UNAVAILABLE'}]})
        self.assertIn('自动化不可用 · 已定义人工验收标准', rendered)
        self.assertNotIn('未通过', rendered)

    def test_T3_manual_pass_is_not_collapsed_into_automated_pass(self):
        rendered = _teacher_behavior_evidence({}, {'checks': [{'verification_type': 'manual-evidence', 'status': 'MANUAL_PASS'}]})
        self.assertIn('课堂人工核对通过', rendered)
        self.assertNotIn('未通过', rendered)

    def test_T4_fail_and_pass_keep_distinct_public_labels(self):
        rendered = _teacher_behavior_evidence({}, {'checks': [
            {'verification_type': 'web-request', 'status': 'FAIL'},
            {'verification_type': 'web-request', 'status': 'PASS'},
        ]})
        self.assertIn('未通过', rendered)
        self.assertIn('通过', rendered)

if __name__=='__main__': unittest.main()
