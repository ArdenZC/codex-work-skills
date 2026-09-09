"""Task-configured reference adapters. No course or route names are special."""
from __future__ import annotations
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

TYPES = {'syntax', 'command', 'function-call', 'web-request', 'file-output', 'query-result', 'structured-data', 'browser', 'manual-evidence'}

def safe_path(root, relative):
    p = Path(str(relative))
    if not str(relative) or p.is_absolute() or '..' in p.parts or ':' in str(relative):
        raise ValueError('unsafe artifact path: ' + str(relative))
    result = (Path(root) / p).resolve()
    result.relative_to(Path(root).resolve())
    return result

def control_flow(source):
    errors = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        for name in ('body', 'orelse', 'finalbody'):
            block = getattr(node, name, None)
            if not isinstance(block, list):
                continue
            for index, statement in enumerate(block):
                if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)) and index + 1 < len(block):
                    errors.append(f'unreachable statement after terminal at line {statement.lineno}')
            if isinstance(node, ast.If) and block and all(isinstance(s, ast.Pass) for s in block):
                errors.append(f'empty branch at line {node.lineno}')
    return errors

def _worker(root, check):
    """Runs in a disposable subprocess; stdout of imported code is not the protocol."""
    kind = check['verification_type']
    expected = check.get('expected', {})
    if kind in {'function-call', 'web-request'}:
        source = safe_path(root, check['entrypoint'])
        static_errors = []
        try:
            static_errors = control_flow(source.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            return {'passed': False, 'error': f'reference source cannot be statically inspected: {exc}', 'static_errors': static_errors}
        sys.path.insert(0, str(source.parent))
        spec = importlib.util.spec_from_file_location('_reference_app', source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if kind == 'function-call':
            value = getattr(module, check['function'])(*check.get('args', []), **check.get('kwargs', {}))
            if 'equals' not in expected:
                raise ValueError('function-call requires expected.equals')
            return {'actual': value, 'passed': value == expected['equals'] and not static_errors, 'static_errors': static_errors}
        if check.get('framework', 'Flask').casefold() != 'flask':
            raise ValueError('web framework adapter unavailable')
        app = getattr(module, check.get('app_object', 'app'))
        app.testing = True
        with app.test_client() as client:
            args = {k: check[k] for k in ('query_string', 'data', 'json', 'headers') if k in check}
            response = client.open(check['path'], method=check.get('method', 'GET'), **args)
            status = check.get('expected_status', expected.get('status'))
            body = check.get('body_contains', expected.get('body_contains', []))
            wanted_json = check.get('json_equals', expected.get('json_equals'))
            if status is None or (not body and wanted_json is None and not expected.get('json_contains')):
                raise ValueError('web-request requires status and body/JSON assertion')
            actual_json = response.get_json(silent=True)
            ok = response.status_code == status and all(t in response.get_data(as_text=True) for t in body)
            if wanted_json is not None:
                ok = ok and wanted_json == actual_json
            for key, value in expected.get('json_contains', {}).items():
                ok = ok and isinstance(actual_json, dict) and actual_json.get(key) == value
            return {'passed': bool(ok) and not static_errors, 'status_code': response.status_code, 'body': response.get_data(as_text=True)[:4000], 'json': actual_json, 'static_errors': static_errors}
    if kind == 'command':
        command = check['argv']
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError('command requires argv list; shell strings forbidden')
        command = [sys.executable if x == '{python}' else x for x in command]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=check.get('timeout_seconds', 15), shell=False)
        if 'returncode' not in expected or not isinstance(expected.get('stdout_contains'), list) or not expected.get('stdout_contains'):
            raise ValueError('command requires returncode and non-empty stdout_contains assertions')
        return {'passed': result.returncode == expected['returncode'] and all(x in result.stdout for x in expected['stdout_contains']), 'returncode': result.returncode, 'stdout': result.stdout[-4000:], 'stderr': result.stderr[-2000:]}
    if kind == 'query-result':
        import sqlite3
        with sqlite3.connect(':memory:') as db:
            db.executescript(safe_path(root, check['setup_file']).read_text(encoding='utf-8'))
            rows = [list(row) for row in db.execute(check['query'], check.get('parameters', []))]
        return {'passed': rows == expected['rows'], 'actual': rows}
    if kind in {'file-output', 'structured-data'}:
        if kind == 'structured-data' and check.get('formula_fact'):
            shared = Path(__file__).resolve().parents[3] / 'HTML课件生成器' / 'courseware-html-generator' / 'scripts'
            sys.path.insert(0, str(shared))
            from formula_truth import verify_formula
            report = verify_formula(check['formula_fact'], root)
            return {'passed': report['status'] == 'PASS', 'formula_evidence': report}
        p = safe_path(root, check['path'])
        if 'equals' not in expected:
            raise ValueError(f'{kind} requires expected.equals')
        value = json.loads(p.read_text(encoding='utf-8')) if kind == 'structured-data' else p.read_text(encoding='utf-8')
        return {'passed': value == expected['equals'], 'actual': value}
    if kind == 'syntax':
        source = safe_path(root, check['path']).read_text(encoding='utf-8')
        compile(source, check['path'], 'exec')
        return {'passed': True}
    raise ValueError('adapter unavailable: ' + kind)

def verify_checks(root, verification):
    reports = []
    checks = verification.get('checks', []) if isinstance(verification, dict) else []
    if not checks:
        return {'status': 'REFERENCE_BEHAVIOR_FAIL', 'checks': [], 'errors': ['no behavioral evidence defined']}
    ids = set()
    for check in checks:
        kind = check.get('verification_type')
        item = {'id': check.get('id'), 'verification_type': kind}
        if not check.get('id') or check['id'] in ids or kind not in TYPES:
            item.update(status='FAIL', error='invalid/duplicate check id or adapter')
        elif kind in {'manual-evidence', 'browser'}:
            defined = all(check.get(k) for k in ('observation', 'expected_result', 'procedure'))
            item.update(status='MANUAL_EVIDENCE_DEFINED' if defined else 'FAIL', automation='AUTOMATED_UNAVAILABLE', manual_evidence_defined=defined)
        else:
            import tempfile
            with tempfile.TemporaryDirectory(prefix='reference-check-') as temp:
                request = Path(temp) / 'request.json'
                response = Path(temp) / 'response.json'
                request.write_text(json.dumps(check), encoding='utf-8')
                env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONINSPECT'}}
                env['PYTHONNOUSERSITE'] = '1'
                try:
                    run = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', str(Path(root).resolve()), str(request), str(response)], cwd=root, env=env, capture_output=True, text=True, timeout=min(60, check.get('timeout_seconds', 20)))
                    result = json.loads(response.read_text(encoding='utf-8')) if response.exists() else {'passed': False, 'error': run.stderr[-2000:]}
                    item.update(result, status='PASS' if run.returncode == 0 and result.get('passed') else 'FAIL')
                except Exception as exc:
                    item.update(status='FAIL', error=str(exc))
        ids.add(check.get('id'))
        reports.append(item)
    behavioral = [r for r in reports if r['verification_type'] != 'syntax']
    failed = any(r['status'] == 'FAIL' for r in reports) or not behavioral
    required = verification.get('required_scenarios', [])
    if any(scenario not in [c.get('scenario') for c in checks] for scenario in required):
        failed = True
    manual = any(r['status'] == 'MANUAL_EVIDENCE_DEFINED' for r in reports)
    return {'status': 'REFERENCE_BEHAVIOR_FAIL' if failed else ('MANUAL_EVIDENCE_DEFINED' if manual else 'REFERENCE_PASS'), 'checks': reports}

if __name__ == '__main__' and len(sys.argv) == 5 and sys.argv[1] == '--worker':
    try:
        result = _worker(Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')))
    except Exception as exc:
        result = {'passed': False, 'error': f'{type(exc).__name__}: {exc}'}
    Path(sys.argv[4]).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    raise SystemExit(0 if result.get('passed') else 1)
