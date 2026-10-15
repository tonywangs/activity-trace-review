"""Fault and SIGKILL tests at every documented publication boundary."""
import hashlib
import types
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
import struct

from activity_trace_review import core as c
from activity_trace_review import transaction as t
from activity_trace_review.demo import demo_files, example_review
from activity_trace_review.validate import validate_bundle, validate_files, BundleError

ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import os,signal,sys
from pathlib import Path
from activity_trace_review.core import Budget,build_bundle,load_files
from activity_trace_review.demo import demo_files,example_review
from activity_trace_review.transaction import publish_bundle
source=load_files(demo_files());files=build_bundle(source,example_review(source))
def hook(stage,path):
    if stage==sys.argv[2]:
        print(stage,flush=True)
        if sys.argv[3]=='kill':os.kill(os.getpid(),signal.SIGKILL)
        if sys.argv[3]=='race':sys.stdin.readline()
publish_bundle(files,sys.argv[1],Budget(seconds=60),hook=hook)
'''


def tree_bytes(path):
    return {p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*') if p.is_file()}


class Transactions(unittest.TestCase):
    def setUp(self):
        self.source=c.load_files(demo_files())
        self.files=c.build_bundle(self.source,example_review(self.source))

    def assert_safe(self, root, dest, published):
        self.assertEqual(dest.exists(),published)
        if published:
            self.assertEqual(validate_bundle(dest)['actions'],12)
            self.assertEqual(tree_bytes(dest),self.files)
        for stage in root.glob('.trace-stage-*'):
            self.assertEqual(stage.stat().st_mode & 0o777,0o700)
            with self.assertRaises(BundleError):validate_bundle(stage)
            if (stage/'payload').exists():
                with self.assertRaises(BundleError):validate_bundle(stage/'payload')
                with self.assertRaises(c.Invalid):c.read_directory(stage/'payload')
            for name,data in tree_bytes(stage).items():
                self.assertNotIn(b'SYNTHETIC_SECRET',data)
                if name.startswith('payload/'):
                    self.assertIn(name[8:],self.files)
                    self.assertEqual(data,self.files[name[8:]])
                    self.assertEqual((stage/name).stat().st_mode & 0o777,0o600)

    def test_injected_exceptions_at_all_stages(self):
        for point in t.STAGES:
            with self.subTest(point=point),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);dest=root/'bundle';sentinel=root/'unrelated';sentinel.write_bytes(b'keep')
                def hook(stage,path):
                    if stage==point:raise OSError('injected failure')
                with self.assertRaises(t.ExportError) as raised:
                    t.publish_bundle(self.files,dest,c.Budget(),hook=hook)
                self.assertIn('Verify',str(raised.exception))
                self.assert_safe(root,dest,point in ('published','parent_synced'))
                self.assertEqual(sentinel.read_bytes(),b'keep')
                # Recovery is a fresh export, never a promotion of staging.
                c.write_fresh(self.files,root/'retry');validate_bundle(root/'retry')

    def test_sigkill_at_all_stages(self):
        evidence=[]
        for point in t.STAGES:
            with self.subTest(point=point),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);dest=root/'bundle'
                result=subprocess.run([sys.executable,'-c',CHILD,str(dest),point,'kill'],capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,-signal.SIGKILL,result.stderr)
                self.assertEqual(result.stdout.strip(),point)
                published=point in ('published','parent_synced')
                self.assert_safe(root,dest,published)
                evidence.append({'stage':point,'returncode':result.returncode,'destination_complete':published,
                                 'staging_bytes':sum(len(v) for stage in root.glob('.trace-stage-*') for v in tree_bytes(stage).values()),
                                 'total_output_bytes':sum(len(v) for v in tree_bytes(root).values()),
                                 'source_hashes':self.source.hashes})
        (ROOT/'results/interruptions.json').write_text(json.dumps(evidence,indent=2)+'\n')

    def test_two_processes_compete_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=root/'bundle'
            processes=[subprocess.Popen([sys.executable,'-c',CHILD,str(dest),'before_publish','race'],
                         stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
            try:
                for process in processes:self.assertEqual(process.stdout.readline().strip(),'before_publish')
                for process in processes:process.stdin.write('go\n');process.stdin.flush()
                results=[process.communicate(timeout=15) for process in processes]
                self.assertEqual(sorted(p.returncode for p in processes),[0,1],results)
                self.assert_safe(root,dest,True)
                self.assertEqual(len(list(root.glob('.trace-stage-*'))),1)
            finally:
                for process in processes:
                    if process.poll() is None:process.kill();process.wait()

    def test_collision_kinds_and_late_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);outside=root/'outside';outside.write_bytes(b'untouched')
            for kind in ('file','directory','nonempty','symlink','dangling'):
                dest=root/kind
                if kind=='file':dest.write_bytes(b'untouched')
                elif kind in ('directory','nonempty'):
                    dest.mkdir()
                    if kind=='nonempty':(dest/'sentinel').write_bytes(b'untouched')
                else:dest.symlink_to(outside if kind=='symlink' else root/'missing')
                for late in (False,True):
                    candidate=dest if not late else root/(kind+'-late')
                    def hook(stage,path):
                        if stage=='before_publish':
                            if kind=='file':candidate.write_bytes(b'untouched')
                            elif kind in ('directory','nonempty'):
                                candidate.mkdir()
                                if kind=='nonempty':(candidate/'sentinel').write_bytes(b'untouched')
                            else:candidate.symlink_to(outside if kind=='symlink' else root/'missing')
                    with self.assertRaises(t.ExportError):
                        t.publish_bundle(self.files,candidate,c.Budget(),hook=hook if late else None)
                    self.assertTrue(os.path.lexists(candidate))
                    if kind=='file':self.assertEqual(candidate.read_bytes(),b'untouched')
                    elif kind=='directory':self.assertEqual(list(candidate.iterdir()),[])
                    elif kind=='nonempty':self.assertEqual((candidate/'sentinel').read_bytes(),b'untouched')
                    else:self.assertTrue(candidate.is_symlink())
                self.assertEqual(outside.read_bytes(),b'untouched')

    def test_unsupported_and_corruption_and_fsync_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(t.sys,'platform','unsupported'),self.assertRaises(t.ExportError):
                c.write_fresh(self.files,root/'unsupported')
            self.assertEqual(list(root.iterdir()),[])
            with patch.object(t,'_rename_noreplace',side_effect=OSError('flag unsupported')),self.assertRaises(t.ExportError):
                c.write_fresh(self.files,root/'no-flag')
            self.assertFalse((root/'no-flag').exists())
            def corrupt(stage,path):
                if stage=='files_synced':(path/'payload'/'image0001.png').write_bytes(b'corrupted')
            with self.assertRaises(t.ExportError):t.publish_bundle(self.files,root/'bad',c.Budget(),hook=corrupt)
            self.assertFalse((root/'bad').exists())
            def fail_parent(stage,path):
                if stage=='published':raise OSError('parent fsync unavailable')
            with self.assertRaises(t.ExportError):t.publish_bundle(self.files,root/'published',c.Budget(),hook=fail_parent)
            validate_bundle(root/'published')
            with patch.object(t.os,'fsync',side_effect=OSError('disk full')),self.assertRaises(t.ExportError):
                c.write_fresh(self.files,root/'disk-full')
            self.assertFalse((root/'disk-full').exists())

    def test_interrupt_timeout_missing_parent_and_missing_libc(self):
        for error in (KeyboardInterrupt(), c.Invalid('Processing time limit exceeded')):
            for point in ('before_publish','published'):
                with self.subTest(error=type(error).__name__,point=point),tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);dest=root/'out'
                    def hook(stage,path):
                        if stage==point:raise error
                    with self.assertRaises(t.ExportError):t.publish_bundle(self.files,dest,c.Budget(),hook=hook)
                    self.assert_safe(root,dest,point=='published')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(t.ExportError,'Verify'):
                c.write_fresh(self.files,root/'missing'/'out')
            self.assertEqual(list(root.iterdir()),[])
            with patch.object(t.ctypes,'CDLL',return_value=types.SimpleNamespace()),self.assertRaises(t.ExportError):
                c.write_fresh(self.files,root/'unsupported-libc')
            self.assertFalse((root/'unsupported-libc').exists())
            with self.assertRaises(t.ExportError):c.write_fresh(self.files,root/'.trace-stage-reserved')
            reserved=root/'.trace-stage-parent';reserved.mkdir()
            with self.assertRaises(t.ExportError):c.write_fresh(self.files,reserved/'out')
            # Ancestor symlinks must not disguise an incomplete payload.
            stage=next(root.glob('.trace-stage-*'))
            if not (stage/'payload').exists():
                stage=next(p for p in root.glob('.trace-stage-*') if (p/'payload').exists())
            alias=root/'alias';alias.symlink_to(stage,target_is_directory=True)
            with self.assertRaises(BundleError):validate_bundle(alias/'payload')
            with self.assertRaises(c.Invalid):c.read_directory(alias/'payload')

    def test_partial_write_and_each_fsync_failure(self):
        original=t.os.fdopen
        class PartialWriter:
            def __init__(self,fd,*args):self.stream=original(fd,*args)
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def write(self,data):
                self.stream.write(data[:17]);self.stream.flush()
                raise OSError('injected partial write / ENOSPC')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=root/'partial'
            with patch.object(t.os,'fdopen',PartialWriter),self.assertRaises(t.ExportError):
                c.write_fresh(self.files,dest)
            self.assertFalse(dest.exists())
            stage=next(root.glob('.trace-stage-*'))
            with self.assertRaises(BundleError):validate_bundle(stage)
            for data in tree_bytes(stage).values():self.assertNotIn(b'SYNTHETIC_SECRET',data)
        # preflight parent, each file, payload directory, and post-rename parent.
        original_sync=t.os.fsync
        for failure in range(1,len(self.files)+4):
            with self.subTest(fsync_call=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);dest=root/'out';calls=0
                def fail(fd):
                    nonlocal calls
                    calls+=1
                    if calls==failure:raise OSError('injected fsync EIO')
                    return original_sync(fd)
                with patch.object(t.os,'fsync',fail),self.assertRaises(t.ExportError):c.write_fresh(self.files,dest)
                self.assert_safe(root,dest,failure==len(self.files)+3)

    def test_verifier_rejects_malformed_records_and_undecodable_png(self):
        def remanifest(files):
            manifest=json.loads(files['manifest.json'])
            manifest['files']={name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                               for name,data in files.items() if name!='manifest.json'}
            files['manifest.json']=c.dumps(manifest)
            return files
        mutations=[lambda x:x['actions'][0].update(timestamp_ms=True),
                   lambda x:x['actions'][-1].update(timestamp_ms=0),
                   lambda x:x['actions'][0].update(screenshot='image9999.png'),
                   lambda x:x['actions'][0].update(id='original'),
                   lambda x:x.update(actions=[3]),lambda x:x.update(synthetic=1)]
        for mutate in mutations:
            files=self.files.copy();trace=json.loads(files['trace.json']);mutate(trace);files['trace.json']=c.dumps(trace)
            with self.assertRaises(BundleError):validate_files(remanifest(files))
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        png=self.files['image0001.png'];files=self.files.copy()
        # Correct container CRCs, but invalid compressed image data. verify() alone accepts this.
        files['image0001.png']=png[:33]+chunk(b'IDAT',b'not zlib')+chunk(b'IEND',b'')
        with self.assertRaises(BundleError):validate_files(remanifest(files))
        for raw in (b'\xff',b'['*2000,b'{"format":NaN}',b'{"a":1,"a":2}'):
            files=self.files.copy();files['manifest.json']=raw
            with self.assertRaises(BundleError):validate_files(files)

if __name__=='__main__':unittest.main()
