"""Audit the project artifact set, excluding local environments and build products."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOP={'README.md','pyproject.toml','requirements-dev.txt','.gitignore','LICENSE'}
DIRS={'src','tests','scripts','docs','results'}

def project_files():
    return sorted(p for p in ROOT.rglob('*') if p.is_file() and
        (p.relative_to(ROOT).parts[0] in DIRS or p.relative_to(ROOT).as_posix() in TOP)
        and '__pycache__' not in p.parts and not any(part.endswith('.egg-info') for part in p.parts)
        and p.suffix!='.pyc')

def main():
    files=project_files();size=sum(p.stat().st_size for p in files)
    assert len(files)<=1000 and size<=32*1024*1024
    for p in files:
        relative=p.relative_to(ROOT).as_posix()
        assert not p.is_symlink(),relative
        assert p.stat().st_size<=10*1024*1024,relative
        assert p.suffix!='.log' or relative=='results/tests.log',relative
        assert not any(word in relative.lower() for word in ['handoff','session-transcript','credentials','run-report']),relative
    report={'files':len(files),'bytes':size,'largest_file_bytes':max(p.stat().st_size for p in files),
            'file_limit':1000,'tree_byte_limit':32*1024*1024,'individual_byte_limit':10*1024*1024}
    print(json.dumps(report,sort_keys=True))
    return report

if __name__=='__main__':main()
