"""Record actual generator Git and source-byte evidence, never inferred labels."""
import hashlib
from pathlib import Path
import subprocess

def provenance(skill_file, source_root, repair_status='not-run'):
    repo=Path(skill_file).resolve().parents[3]
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True,encoding='utf-8').strip()
    commit=git('rev-parse','HEAD'); dirty=bool(git('status','--porcelain'))
    files={}
    if source_root:
        for path in sorted(Path(source_root).rglob('*')):
            if path.is_file(): files[path.relative_to(source_root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'generator_commit':commit,'dirty':dirty,'dirty_worktree':dirty,'valid':not dirty,
            'source_files_sha256':files,'skill_versions':{'courseware':'1.2.1','practice':'1.2.0'},
            'contract_versions':{'courseware':'1.1','practice':'1.1','integrity':'1.0'},
            'generation_method':'agent-authored-contract/deterministic-renderer','repair_status':repair_status}
