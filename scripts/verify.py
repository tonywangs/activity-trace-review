"""One offline verification command after installing the documented prerequisites."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]

def main():
    os.chdir(ROOT);(ROOT/'results').mkdir(exist_ok=True)
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/activity-trace-browsers')
    commands=[['-m','unittest','discover','-s','tests','-v'],['tests/browser_flow.py'],
              ['scripts/installed_example.py'],['scripts/benchmark.py'],['scripts/publication_check.py']]
    reports=[];output=[];started=time.perf_counter()
    for args in commands:
        command=[sys.executable,*args]
        print('Running:', ' '.join(args),flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            metrics=Path(tmp)/'time.json'
            result=subprocess.run(['/usr/bin/time','-f','{"elapsed_seconds":%e,"peak_process_rss_kib":%M}',
                                   '-o',str(metrics),*command],cwd=ROOT,capture_output=True,text=True)
            measured=json.loads(metrics.read_text().splitlines()[-1])
        output.append('$ python '+ ' '.join(args)+'\n'+result.stdout+result.stderr)
        report={'command':['python',*args],'exit_code':result.returncode,**measured};reports.append(report)
        print(json.dumps(report),flush=True)
        if result.returncode:
            print(result.stdout+result.stderr,file=sys.stderr)
            break
    (ROOT/'results/tests.log').write_text('\n'.join(output))
    report={'passed':all(r['exit_code']==0 for r in reports) and len(reports)==len(commands),
            'elapsed_seconds':round(time.perf_counter()-started,3),'python':platform.python_version(),
            'platform':platform.platform(),'dependencies':{name:importlib.metadata.version(name) for name in ['Pillow','playwright','build','setuptools','wheel']},
            'rss_scope':'GNU time maximum resident set for each command (largest process, not sum of process tree); KiB on Linux',
            'seeded_export_cases':240,'seed_range':[0,239],'checks':reports}
    (ROOT/'results/verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1

if __name__=='__main__':sys.exit(main())
