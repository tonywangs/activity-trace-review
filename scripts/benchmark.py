"""Reproducible bounded workload measurements, not a real-recording benchmark."""
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import resource
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from workloads import workload
from activity_trace_review.core import load_files, new_review, build_bundle, bundle_zip, rgb_png, write_fresh
from activity_trace_review.runtime import deadline
from activity_trace_review.validate import validate_bundle

def run(images,dimension):
    files=workload(images,dimension)
    started=time.perf_counter()
    with deadline():source=load_files(files)
    load_seconds=time.perf_counter()-started
    review=new_review(source);review['confirmed']=True
    review['replacements']={a['id']:{'value':'[removed]'} for a in source.actions}
    review['screenshots']={name:{'rects':[[0,0,32,32]],'reviewed':True} for name in source.images}
    start=time.perf_counter()
    baseline={name:rgb_png(image) for name,image in source.images.items()}
    baseline_seconds=time.perf_counter()-start
    start=time.perf_counter()
    with deadline():exported=build_bundle(source,review);archive=bundle_zip(exported)
    export_seconds=time.perf_counter()-start
    with tempfile.TemporaryDirectory() as tmp:
        dest=Path(tmp)/'bundle';write_fresh(exported,dest);result=validate_bundle(dest)
    start=time.perf_counter()
    with deadline():second=bundle_zip(build_bundle(source,review))
    replay_seconds=time.perf_counter()-start
    assert archive==second
    assert len(load_files(exported).actions)==128
    return {'seed':1307,'actions':128,'images':images,'dimensions':[dimension,dimension],
            'decoded_pixels':images*dimension*dimension,'input_bytes':sum(map(len,files.values())),
            'load_seconds':round(load_seconds,6),'encode_only_unmasked_baseline_seconds':round(baseline_seconds,6),
            'encode_only_unmasked_baseline_bytes':sum(map(len,baseline.values())),
            'export_and_zip_seconds':round(export_seconds,6),'replay_seconds':round(replay_seconds,6),
            'bundle_bytes':result['bytes'],'archive_bytes':len(archive),'archive_sha256':hashlib.sha256(archive).hexdigest(),
            'deterministic_replay':True,'peak_process_rss_kib_cumulative':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}

if __name__=='__main__':
    results={'python':platform.python_version(),'platform':platform.platform(),'Pillow':importlib.metadata.version('Pillow'),
             'measurement':'perf_counter wall time; Linux ru_maxrss KiB, cumulative for benchmark process; one repetition per workload',
             'baseline_scope':'PNG encoding only; excludes validation, selection, metadata, ZIP. Not a comparable end-to-end baseline.',
             'workloads':[run(64,512),run(4,2048)]}
    (ROOT/'results/benchmark.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,sort_keys=True))
