"""Build and install into a clean environment, then run the example with networking denied.

Requires a predownloaded Pillow wheel in TRACE_WHEELHOUSE (default /tmp/activity-trace-wheelhouse).
No package indexes or downloads are used by this script.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
ROOT=Path(__file__).resolve().parents[1]

def run(args,**kwargs):
    result=subprocess.run([str(a) for a in args],check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
    return result.stdout

def main():
    wheelhouse=Path(os.environ.get('TRACE_WHEELHOUSE','/tmp/activity-trace-wheelhouse'))
    assert list(wheelhouse.glob('pillow-11.3.0-*.whl')),'Preload the Pillow wheel as documented in README.md'
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);wheels=tmp/'wheels';wheels.mkdir()
        run([sys.executable,'-m','build','--wheel','--no-isolation','--outdir',wheels,ROOT],cwd=tmp)
        wheel=next(wheels.glob('*.whl'));env=tmp/'installed';venv.EnvBuilder(with_pip=False).create(env)
        python=env/'bin/python';cli=env/'bin/activity-trace'
        run([sys.executable,'-m','pip','--python',python,'install','--no-index','--find-links',wheelhouse,wheel],cwd=tmp)
        site=Path(run([python,'-c','import sysconfig;print(sysconfig.get_paths()["purelib"])'],cwd=tmp).strip())
        # This guard is inside the isolated install so PYTHONPATH is unnecessary.
        (site/'trace_offline_guard.py').write_text('import socket\ndef denied(*args, **kwargs):\n    raise RuntimeError("Network denied in installed example")\nsocket.socket.connect=denied\nsocket.socket.connect_ex=denied\nsocket.create_connection=denied\nsocket.getaddrinfo=denied\n')
        (site/'trace_offline_guard.pth').write_text('import trace_offline_guard\n')
        location=run([python,'-I','-c','import activity_trace_review;print(activity_trace_review.__file__)'],cwd=tmp).strip()
        assert str(env) in location and str(ROOT) not in location
        clean=os.environ.copy();clean.pop('PYTHONPATH',None)
        # Verify network denial really applies to the isolated interpreter.
        probe=subprocess.run([str(python),'-I','-c','import socket;socket.create_connection(("example.invalid",80))'],cwd=tmp,env=clean,capture_output=True,text=True)
        assert probe.returncode!=0 and 'Network denied' in probe.stderr, (probe.returncode,probe.stdout,probe.stderr)
        demo=tmp/'demo';run([cli,'demo',demo],cwd=tmp,env=clean)
        source=demo/'source';before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
        inspected=json.loads(run([cli,'inspect',source],cwd=tmp,env=clean));assert inspected['hashes']==before
        run([cli,'review',source,tmp/'new-review.json'],cwd=tmp,env=clean)
        assert json.loads((tmp/'new-review.json').read_text())['confirmed'] is False
        failed=subprocess.run([str(cli),'export',str(source),str(tmp/'new-review.json'),str(tmp/'should-not-exist')],cwd=tmp,env=clean,capture_output=True)
        assert failed.returncode==2 and not (tmp/'should-not-exist').exists()
        run([cli,'export',source,demo/'example-review.json',tmp/'bundle'],cwd=tmp,env=clean)
        validated=json.loads(run([cli,'validate',tmp/'bundle'],cwd=tmp,env=clean));assert validated['actions']==12
        reopened=json.loads(run([cli,'inspect',tmp/'bundle'],cwd=tmp,env=clean));assert reopened['actions']==12
        run([cli,'export',source,demo/'example-review.json',tmp/'replay'],cwd=tmp,env=clean)
        first={p.name:p.read_bytes() for p in (tmp/'bundle').iterdir()};second={p.name:p.read_bytes() for p in (tmp/'replay').iterdir()};assert first==second
        collision=subprocess.run([str(cli),'export',str(source),str(demo/'example-review.json'),str(tmp/'bundle')],cwd=tmp,env=clean,capture_output=True)
        assert collision.returncode==2
        assert first=={p.name:p.read_bytes() for p in (tmp/'bundle').iterdir()}
        assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
        report={'isolated_install':True,'source_tree_on_import_path':False,'network_connect_denied':True,'package_wheel_bytes':wheel.stat().st_size,
                'actions':validated['actions'],'images':validated['images'],'bundle_bytes':validated['bytes'],
                'source_hashes_unchanged':True,'deterministic_replay':True,'unreviewed_export_rejected':True,'collision_rejected':True}
        (ROOT/'results/installed.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
