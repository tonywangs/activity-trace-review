import copy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import signal
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image, PngImagePlugin
from activity_trace_review import core as c
from activity_trace_review.demo import demo_files, example_review, SECRET_RECT
from activity_trace_review.runtime import deadline
from activity_trace_review.validate import validate_bundle, BundleError

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.files=demo_files(); self.source=c.load_files(self.files); self.review=example_review(self.source)
    def test_demo_export_reopen_and_replay(self):
        before=copy.deepcopy(self.files)
        first=c.build_bundle(self.source,self.review)
        self.assertEqual(first,c.build_bundle(self.source,self.review))
        self.assertEqual(c.bundle_zip(first),c.bundle_zip(first))
        reopened=c.load_files(first)
        self.assertEqual(len(reopened.actions),12)
        self.assertEqual(before,self.files)
        self.assertEqual(self.source.hashes,{k:hashlib.sha256(v).hexdigest() for k,v in self.files.items()})
        for data in first.values():self.assertNotIn(b'SYNTHETIC_SECRET',data)
        for im in reopened.images.values():
            for y in range(16,48):
                for x in range(16,256):self.assertEqual(im.getpixel((x,y)),(0,0,0))
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'bundle';c.write_fresh(first,dest)
            self.assertEqual(validate_bundle(dest)['actions'],12)
            self.assertEqual(c.read_directory(dest).digest,reopened.digest)
    def test_review_schema_errors_preserve_current(self):
        original=copy.deepcopy(self.review)
        mutations=[lambda r:r.update(format='activity-review/2'),lambda r:r.update(source='bad'),
            lambda r:r.update(segments=[['step04','step01']]),lambda r:r.update(segments=[['absent','step01']]),
            lambda r:r.update(removed=['absent']),lambda r:r.update(removed=['step00','step00']),
            lambda r:r.update(replacements={'step00':{'nonexistent':'x'}}),lambda r:r.update(replacements={'absent':{}}),
            lambda r:r.update(screenshots={'missing.png':{'rects':[],'reviewed':True}}),
            lambda r:r.update(confirmed=1),lambda r:r.update(extra='bad')]
        for rect in [[-1,0,1,1],[0,0,0,1],[0,0,321,1],[0,0,1.1,2],[True,0,1,1],[1,2,3],['0',0,1,1]]:
            mutations.append(lambda r,rect=rect:r['screenshots']['screen0.png'].update(rects=[rect]))
        for mutate in mutations:
            r=copy.deepcopy(original);mutate(r)
            with self.subTest(review=r),self.assertRaises(c.Invalid):c.validate_review(self.source,r)
            self.assertEqual(self.review,original)
    def test_explicit_review_gates_and_empty_selection(self):
        for mutate in [lambda r:r.update(confirmed=False),lambda r:r.update(segments=[]),
                       lambda r:r['screenshots']['screen0.png'].update(reviewed=False)]:
            r=copy.deepcopy(self.review);mutate(r)
            with self.assertRaises(c.Invalid):c.build_bundle(self.source,r)
        r=copy.deepcopy(self.review);r['segments']=[['step03','step05']];del r['screenshots']['screen0.png']
        self.assertEqual(len(c.load_files(c.build_bundle(self.source,r)).actions),3)
    def test_source_binding_raw_bytes_and_images(self):
        for name in ['trace.json','screen0.png']:
            files=self.files.copy()
            if name=='trace.json':files[name]+=b' '
            else:
                im=c.decode(files[name]);im.putpixel((0,0),(1,2,3));files[name]=c.rgb_png(im)
            source=c.load_files(files)
            with self.assertRaises(c.Invalid):c.validate_review(source,self.review)
    def test_trace_and_json_errors(self):
        original=json.loads(self.files['trace.json'])
        mutations=[lambda t:t.update(format='unknown'),lambda t:t.update(synthetic='true'),lambda t:t.update(actions=[]),
                   lambda t:t['actions'][0].update(id=t['actions'][1]['id']),lambda t:t['actions'][1].update(timestamp_ms=-1),
                   lambda t:t['actions'][0].update(timestamp_ms=True),lambda t:t['actions'][0].update(kind='execute'),
                   lambda t:t['actions'][0].update(screenshot='../secret.png'),lambda t:t['actions'][0].update(screenshot='/secret.png'),
                   lambda t:t['actions'][0].update(screenshot='https://host/a.png'),lambda t:t['actions'][0].update(text={'value':'x'*4097}),
                   lambda t:t['actions'][0].update(extra='no')]
        for mutate in mutations:
            trace=copy.deepcopy(original);mutate(trace);files=self.files.copy();files['trace.json']=c.dumps(trace)
            with self.assertRaises(c.Invalid):c.load_files(files)
        for data in [b'{"x":1,"x":2}',b'{"x":NaN}',b'\xff',b'['*2000,b'x'*(c.LIMITS['json_bytes']+1)]:
            with self.assertRaises(c.Invalid):c.loads(data)
        r=copy.deepcopy(self.review);r['replacements']['step00']['value']='\ud800'
        with self.assertRaises(c.Invalid):c.build_bundle(self.source,r)
    def test_malformed_images_and_limits(self):
        for data in [b'not a png',self.files['screen0.png'][:90]]:
            files=self.files.copy();files['screen0.png']=data
            with self.assertRaises(c.Invalid):c.load_files(files)
        for size,mode in [((2049,1),'RGB'),((2,2),'L')]:
            out=io.BytesIO();Image.new(mode,size).save(out,format='PNG')
            with self.assertRaises(c.Invalid):c.decode(out.getvalue())
        im=Image.new('RGBA',(2,2),(255,0,0,0));out=io.BytesIO();im.save(out,format='PNG')
        self.assertEqual(c.decode(out.getvalue()).getpixel((0,0)),(255,255,255))
        frames=[Image.new('RGB',(2,2),color) for color in ['red','blue']];out=io.BytesIO()
        frames[0].save(out,format='PNG',save_all=True,append_images=frames[1:])
        with self.assertRaises(c.Invalid):c.decode(out.getvalue())
        for limit,value in [('input_bytes',1),('image_bytes',1),('actions',1),('images',1),('total_pixels',1),('files',1)]:
            with patch.dict(c.LIMITS,{limit:value}),self.assertRaises(c.Invalid):c.load_files(self.files)
        with patch.dict(c.LIMITS,{'export_bytes':1}),self.assertRaises(c.Invalid):c.build_bundle(self.source,self.review)
        for name in ['../escape.png','unreferenced.png']:
            files=self.files.copy();files[name]=files['screen0.png']
            with self.assertRaises(c.Invalid):c.load_files(files)
    def test_path_symlink_fifo_and_output_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';c.write_fresh(self.files,source)
            original=(source/'screen0.png').read_bytes();(source/'screen0.png').unlink();(root/'outside.png').write_bytes(original)
            (source/'screen0.png').symlink_to(root/'outside.png')
            with self.assertRaises(OSError):c.read_directory(source)
            (source/'screen0.png').unlink();os.mkfifo(source/'screen0.png')
            with self.assertRaises(c.Invalid):c.read_directory(source)
            (source/'screen0.png').unlink();(source/'screen0.png').write_bytes(original)
            link=root/'link';link.symlink_to(source,target_is_directory=True)
            with self.assertRaises(c.Invalid):c.read_directory(link)
            for dest in [source,link]:
                with self.assertRaises(c.Invalid):c.write_fresh(self.files,dest)
            self.assertEqual((source/'screen0.png').read_bytes(),original)
            dest=root/'race'
            mkdir=Path.mkdir
            def racing(path,*args,**kwargs):
                if path==dest:
                    mkdir(path);(path/'sentinel').write_text('keep')
                return mkdir(path,*args,**kwargs)
            with patch.object(Path,'mkdir',racing),self.assertRaises(FileExistsError):c.write_fresh(self.files,dest)
            self.assertEqual((dest/'sentinel').read_text(),'keep')
            self.assertFalse(list(root.glob('.trace-stage-*')))
    def test_cleanup_cancellation_and_serialization_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=root/'out'
            def broken(*args,**kwargs):raise OSError('injected disk error')
            with patch.object(Path,'write_bytes',broken),self.assertRaises(OSError):c.write_fresh(self.files,dest)
            self.assertFalse(dest.exists());self.assertFalse(list(root.iterdir()))
            with patch.object(c.os,'replace',broken),self.assertRaises(OSError):c.write_fresh(self.files,dest)
            self.assertFalse(dest.exists());self.assertFalse(list(root.iterdir()))
            with patch.object(c.os,'replace',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):c.write_fresh(self.files,dest)
            self.assertFalse(dest.exists());self.assertFalse(list(root.iterdir()))
            with patch.object(c,'dumps',side_effect=TypeError('injected serialization failure')),self.assertRaises(TypeError):
                c.write_fresh(c.build_bundle(self.source,self.review),dest)
            self.assertFalse(dest.exists());self.assertFalse(list(root.iterdir()))
            with self.assertRaises(c.Invalid):c.write_fresh(self.files,dest,c.Budget(cancelled=lambda:True))
            self.assertFalse(list(root.iterdir()))
        with self.assertRaises(c.Invalid):c.build_bundle(self.source,self.review,c.Budget(seconds=0))
        with self.assertRaises(c.Invalid):c.bundle_zip(self.files,c.Budget(cancelled=lambda:True))
        with self.assertRaises(c.Invalid):
            with deadline(.01):time.sleep(.1)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))
    def test_validator_rejects_tampering_and_extra_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'bundle';files=c.build_bundle(self.source,self.review);c.write_fresh(files,root)
            for name,data in [('private.txt',b'secret'),('trace.json',files['trace.json']+b' '),('manifest.json',b'{}')]:
                (root/name).write_bytes(data)
                with self.assertRaises((BundleError,ValueError)):validate_bundle(root)
                if name in files:(root/name).write_bytes(files[name])
                else:(root/name).unlink()


    def test_imported_manifest_structure_and_version(self):
        original=c.build_bundle(self.source,self.review)
        manifest=json.loads(original['manifest.json'])
        mutations=[lambda m:m.update(format='activity-bundle/2'),lambda m:m.update(files=[]),
                   lambda m:m.update(actions=True),lambda m:m.update(images='4'),
                   lambda m:m['files']['trace.json'].update(bytes=float(m['files']['trace.json']['bytes']))]
        for mutate in mutations:
            candidate=copy.deepcopy(manifest);mutate(candidate);files=original.copy();files['manifest.json']=c.dumps(candidate)
            with self.subTest(manifest=candidate),self.assertRaises(c.Invalid):c.load_files(files)
        self.assertEqual(c.build_bundle(self.source,self.review),original)


class SeededIndependentOracle(unittest.TestCase):
    def test_240_seeded_cases(self):
        """Expected selection and pixels computed directly, without export helpers."""
        for seed in range(240):
            with self.subTest(seed=seed):
                rng=random.Random(seed);files={};originals={};rectangles={}
                image_count=rng.randint(1,4)
                for j in range(image_count):
                    name=f'SOURCE_SECRET_IMAGE_{j}.png';w,h=rng.randint(12,48),rng.randint(12,40)
                    im=Image.new('RGB',(w,h));im.putdata([(rng.randrange(1,255),rng.randrange(1,255),rng.randrange(1,255)) for _ in range(w*h)])
                    # Planted pixel secret occupies a known corner and is always redacted.
                    for y in range(3):
                        for x in range(4):im.putpixel((x,y),(253,1,254))
                    originals[name]=im.copy();out=io.BytesIO();info=PngImagePlugin.PngInfo();info.add_text('private','PLANTED_SECRET_METADATA')
                    im.save(out,format='PNG',pnginfo=info);files[name]=out.getvalue()
                    rects=[[0,0,4,3]]
                    for _ in range(rng.randint(0,4)):
                        x,y=rng.randrange(w),rng.randrange(h);rects.append([x,y,rng.randint(1,w-x),rng.randint(1,h-y)])
                    rectangles[name]=rects
                count=rng.randint(image_count,24);names=list(originals)
                actions=[{'id':f'SOURCE_SECRET_ID_{i}','timestamp_ms':(i//2)*13,'kind':rng.choice(['click','type','observe']),
                          'text':{'label':f'keep {i}','value':f'PLANTED_SECRET_TEXT_{i}','url':'https://never-fetch.invalid/PLANTED_SECRET_URL'},
                          'screenshot':names[i%image_count]} for i in range(count)]
                trace={'format':'activity-trace/1','synthetic':True,'actions':actions};files['trace.json']=json.dumps(trace).encode()
                source=c.load_files(files);before={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}
                intervals=[]
                for _ in range(rng.randint(1,4)):
                    start=rng.randrange(count);end=rng.randrange(start,count);intervals.append((start,end))
                included=[i for i in range(count) if any(lo<=i<=hi for lo,hi in intervals)]
                removed={i for i in included if rng.random()<.3};removed.discard(included[0])
                kept=[i for i in included if i not in removed]
                review={'format':'activity-review/1','source':source.digest,'segments':[[actions[lo]['id'],actions[hi]['id']] for lo,hi in intervals],
                        'removed':[actions[i]['id'] for i in sorted(removed)],
                        'replacements':{a['id']:{'value':f'replacement {i}','url':''} for i,a in enumerate(actions)},
                        'screenshots':{name:{'rects':rectangles[name],'reviewed':True} for name in names},'confirmed':True}
                exported=c.build_bundle(source,review)
                out=json.loads(exported['trace.json']);expected_names=list(dict.fromkeys(actions[i]['screenshot'] for i in kept))
                self.assertEqual(len(out['actions']),len(kept))
                for n,i in enumerate(kept):
                    actual=out['actions'][n];source_action=actions[i]
                    self.assertEqual(actual,{'id':f'action{n+1:04d}','timestamp_ms':source_action['timestamp_ms'],'kind':source_action['kind'],
                        'text':{'label':f'keep {i}','value':f'replacement {i}','url':''},'screenshot':f'image{expected_names.index(source_action["screenshot"])+1:04d}.png'})
                self.assertEqual(set(exported),{'manifest.json','trace.json'}|{f'image{j+1:04d}.png' for j in range(len(expected_names))})
                for j,name in enumerate(expected_names):
                    with Image.open(io.BytesIO(exported[f'image{j+1:04d}.png'])) as actual:
                        expected=originals[name];self.assertEqual(actual.size,expected.size);self.assertEqual(actual.info,{})
                        for y in range(expected.height):
                            for x in range(expected.width):
                                masked=any(rx<=x<rx+rw and ry<=y<ry+rh for rx,ry,rw,rh in rectangles[name])
                                self.assertEqual(actual.getpixel((x,y)),(0,0,0) if masked else expected.getpixel((x,y)))
                for name,data in exported.items():
                    for secret in [b'PLANTED_SECRET',b'SOURCE_SECRET']:
                        self.assertNotIn(secret,name.encode());self.assertNotIn(secret,data)
                self.assertEqual(exported,c.build_bundle(source,copy.deepcopy(review)))
                self.assertEqual(c.bundle_zip(exported),c.bundle_zip(c.build_bundle(source,review)))
                self.assertEqual(before,{k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
                with tempfile.TemporaryDirectory() as tmp:
                    destination=Path(tmp)/'out';c.write_fresh(exported,destination);report=validate_bundle(destination)
                    self.assertEqual(report['actions'],len(kept))

if __name__=='__main__':unittest.main()
