"""Small, fail-closed spreadsheet evaluator with explicit semantic bindings.

Supported grammar: literals, cells/ranges, comparisons, IF/COUNTIF/SUM/SUMIF/AVERAGE.
No eval, guessed field mapping, external workbook access or full Excel claim.
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import re

CELL = re.compile(r'\$?([A-Z]+)\$?([1-9][0-9]*)')
TOKEN = re.compile(r'\s*("(?:[^"]|"")*"|\$?[A-Z]+\$?[1-9][0-9]*|[A-Z]+|(?:\d+(?:\.\d*)?|\.\d+)|<>|>=|<=|[=><(),:+-])')

def column_number(name):
    value=0
    for c in name: value=value*26+ord(c)-64
    return value

def column_letter(index):
    result=''
    while index:
        index,r=divmod(index-1,26); result=chr(65+r)+result
    return result

def scalar(value):
    if isinstance(value,(int,float,bool)): return value
    try: return float(value)
    except (ValueError,TypeError): return value

def table_model(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f: rows=list(csv.reader(f))
    if not rows or len(set(rows[0]))!=len(rows[0]) or any(len(r)!=len(rows[0]) for r in rows):
        raise ValueError('invalid structured table')
    fields=[]
    for i,name in enumerate(rows[0]):
        samples=[scalar(r[i]) for r in rows[1:] if r[i]!='']
        fields.append({'column_index':i+1,'column_letter':column_letter(i+1),'field_name':name,'sample':samples[:3],'value_type':'numeric' if samples and all(isinstance(x,(int,float)) for x in samples) else 'text/category'})
    return {'columns':fields,'rows':rows,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}

class Formula:
    def __init__(self,text,model,derived=None):
        text=text.strip()
        if not text.startswith('='): raise ValueError('formula must start with =')
        text=text[1:]; self.tokens=[]; pos=0
        while pos<len(text):
            m=TOKEN.match(text,pos)
            if not m: raise ValueError('unsupported formula syntax: '+text[pos:])
            self.tokens.append(m.group(1)); pos=m.end()
        self.pos=0; self.model=model; self.derived=derived or {}; self.used=[]
    def take(self):
        if self.pos>=len(self.tokens): raise ValueError('unexpected end of formula')
        t=self.tokens[self.pos]; self.pos+=1; return t
    def peek(self): return self.tokens[self.pos] if self.pos<len(self.tokens) else None
    def cell(self,token):
        m=CELL.fullmatch(token)
        col,row=column_number(m[1]),int(m[2]); self.used.append(col)
        if token.replace('$','') in self.derived: return self.derived[token.replace('$','')]
        rows=self.model['rows']
        if row>len(rows) or col>len(rows[0]): raise ValueError('cell outside current dataset: '+token)
        return scalar(rows[row-1][col-1])
    def expr(self):
        left=self.atom()
        if self.peek() in {'=','<>','>','<','>=','<='}:
            op=self.take(); right=self.atom(); return compare(left,op,right)
        return left
    def atom(self):
        token=self.take()
        if token in {'+','-'}:
            val=self.atom(); return val if token=='+' else -val
        if token.startswith('"'): return token[1:-1].replace('""','"')
        if re.fullmatch(r'\d+(?:\.\d*)?|\.\d+',token): return float(token)
        if CELL.fullmatch(token):
            if self.peek()==':':
                self.take(); end=self.take(); a=CELL.fullmatch(token); b=CELL.fullmatch(end)
                if not b: raise ValueError('invalid range')
                if int(a[2])>int(b[2]) or column_number(a[1])>column_number(b[1]): raise ValueError('reversed range')
                return [self.cell(f'{column_letter(c)}{r}') for r in range(int(a[2]),int(b[2])+1) for c in range(column_number(a[1]),column_number(b[1])+1)]
            return self.cell(token)
        if token not in {'IF','COUNTIF','SUM','SUMIF','AVERAGE'}: raise ValueError('unsupported function: '+token)
        if self.take()!='(': raise ValueError('expected (')
        args=[self.expr()]
        while self.peek()==',': self.take(); args.append(self.expr())
        if self.take()!=')': raise ValueError('expected )')
        flat=lambda xs:[v for x in xs for v in (x if isinstance(x,list) else [x])]
        if token=='IF':
            if len(args)!=3 or not isinstance(args[0],bool): raise ValueError('IF needs comparison and two outcomes')
            return args[1] if args[0] else args[2]
        if token=='COUNTIF':
            if len(args)!=2 or not isinstance(args[0],list): raise ValueError('COUNTIF needs range and criterion')
            return sum(matches(x,args[1]) for x in args[0])
        if token=='SUMIF':
            if len(args) not in {2,3} or not isinstance(args[0],list): raise ValueError('SUMIF needs range and criterion')
            values=args[2] if len(args)==3 else args[0]
            if not isinstance(values,list) or len(values)!=len(args[0]): raise ValueError('SUMIF ranges mismatch')
            return sum(v for x,v in zip(args[0],values) if matches(x,args[1]) and isinstance(v,(int,float)))
        values=[v for v in flat(args) if isinstance(v,(int,float)) and not isinstance(v,bool)]
        if not values: raise ValueError('numeric aggregate has no numeric data')
        return sum(values) if token=='SUM' else sum(values)/len(values)
    def run(self):
        value=self.expr()
        if self.peek() is not None: raise ValueError('unsupported trailing formula syntax')
        return value

def compare(a,op,b):
    if op in {'>','<','>=','<='} and type(a)!=type(b) and not (isinstance(a,(int,float)) and isinstance(b,(int,float))):
        raise ValueError('incompatible comparison types')
    if op=='=': return a==b
    if op=='<>': return a!=b
    if op=='>': return a>b
    if op=='<': return a<b
    if op=='>=': return a>=b
    return a<=b

def matches(value,criterion):
    if isinstance(criterion,str):
        m=re.fullmatch(r'(>=|<=|<>|>|<|=)(.*)',criterion)
        if m: return compare(value,m[1],scalar(m[2]))
        if '*' in criterion or '?' in criterion: raise ValueError('wildcard criteria unsupported; manual evidence required')
    return value==criterion

def verify_formula(fact,root,derived=None):
    report={'id':fact.get('id'),'formula':fact.get('formula'),'scope':fact.get('example_scope'),'errors':[]}
    try:
        if fact.get('example_scope')=='abstract':
            report.update(status='ABSTRACT',label='语法示例'); return report
        if fact.get('example_scope')!='current-dataset': raise ValueError('formula requires explicit example_scope')
        p=(Path(root)/fact['source_id']).resolve(); p.relative_to(Path(root).resolve())
        model=table_model(p)
        binding=fact['bindings']; intended=binding.get('input_fields') or [binding.get('input_field')]
        if not fact.get('semantic_intent') or not intended or any(not x for x in intended): raise ValueError('semantic intent and input bindings required')
        evaluator=Formula(fact['formula'],model,derived)
        result=evaluator.run()
        fields={c['field_name']:c for c in model['columns']}
        used={model['columns'][c-1]['field_name'] for c in evaluator.used}
        if used!=set(intended): raise ValueError(f'formula fields {sorted(used)} differ from semantic bindings {intended}')
        for name,kind in binding.get('field_types',{}).items():
            if fields[name]['value_type']!=kind: raise ValueError('field type mismatch: '+name)
        if not fact.get('operation_location'): raise ValueError('current formula needs operation_location')
        if 'expected_result' in fact and fact['expected_result']!=result: raise ValueError('expected result contradicts evaluated current data')
        # Text criteria over numeric fields are a semantic mismatch even if Excel returns zero.
        if re.match(r'=COUNTIF\(',fact['formula'],re.I) and re.search(r',\s*"[^"<>=0-9][^"]*"\s*\)',fact['formula']):
            if all(fields[f]['value_type']=='numeric' for f in used): raise ValueError('text classification count bound to numeric field')
        report.update(status='PASS',fields=sorted(used),expected_result=result,operation_location=fact['operation_location'],source_sha256=model['sha256'],table_semantics=model['columns'])
    except Exception as exc:
        report['errors'].append(str(exc)); report['status']='FAIL'
    return report

def verify_formulas(content,root):
    facts=content.get('formula_facts',[]); reports=[]; derived={}
    for fact in facts:
        key=fact.get('source_id','')
        report=verify_formula(fact,root,derived.get(key,{})); reports.append(report)
        if report['status']=='PASS' and CELL.fullmatch(fact.get('operation_location','')):
            derived.setdefault(key,{})[fact['operation_location'].replace('$','')]=report['expected_result']
    errors=[e for r in reports for e in r['errors']]
    declared={re.sub(r'\s+','',f.get('formula','')) for f in facts}
    def strings(value):
        if isinstance(value,str): yield value
        elif isinstance(value,list):
            for item in value: yield from strings(item)
        elif isinstance(value,dict):
            for key,item in value.items():
                if key not in {'formula_facts','reference_verification','canonical_facts'}: yield from strings(item)
    for value in strings(content):
        for match in re.finditer(r'=(?:IF|COUNTIF|SUM|SUMIF|AVERAGE)\(',value):
            depth=0; quote=False; end=None
            for pos in range(match.start(),len(value)):
                char=value[pos]
                if char=='"': quote=not quote
                if not quote:
                    if char=='(': depth+=1
                    if char==')':
                        depth-=1
                        if depth==0: end=pos+1; break
            formula=value[match.start():end] if end else ''
            if not formula or re.sub(r'\s+','',formula) not in declared:
                errors.append('displayed spreadsheet formula lacks scoped formula_fact: '+formula)
    return {'status':'FAIL' if errors else 'PASS','formulas':reports,'errors':errors}
