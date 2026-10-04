"""Standalone bundle integrity validator. Does not use export or review helpers.

Integrity is not proof that a human removed all sensitive content. The randomized
pixel oracle in tests is a separate source-aware validation of redaction behavior.
"""
import hashlib
import io
import json
import os
import stat
from pathlib import Path
import re
import struct
from PIL import Image

class BundleError(ValueError):
    pass

def validate_bundle(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise BundleError('Bundle must be a real directory')
    entries = list(path.iterdir())
    if len(entries) > 66 or any(p.is_symlink() or not p.is_file() for p in entries):
        raise BundleError('Invalid bundle entries')
    files = {}
    for p in entries:
        fd=os.open(p,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise BundleError('Invalid file type')
            data=f.read(8*1024*1024+1)
        if len(data)>8*1024*1024:
            raise BundleError('Oversize file')
        files[p.name]=data
    if sum(map(len, files.values())) > 32*1024*1024:
        raise BundleError('Oversize bundle')
    return validate_files(files)

def validate_files(files):
    if type(files) is not dict or len(files) > 66 or sum(map(len,files.values())) > 32*1024*1024:
        raise BundleError('Invalid bundle size')
    def parse(name):
        def obj(pairs):
            out = {}
            for k,v in pairs:
                if k in out:
                    raise BundleError('Duplicate key')
                out[k] = v
            return out
        if len(files[name]) > 512*1024:
            raise BundleError('Oversize JSON')
        return json.loads(files[name], object_pairs_hook=obj)
    try:
        manifest, trace = parse('manifest.json'), parse('trace.json')
        if type(manifest) is not dict or set(manifest) != {'format','actions','images','files'} or manifest['format'] != 'activity-bundle/1' or type(manifest['files']) is not dict:
            raise BundleError('Invalid manifest')
        if set(files) != set(manifest['files']) | {'manifest.json'}:
            raise BundleError('Unexpected or missing artifact')
        for name, record in manifest['files'].items():
            if type(record) is not dict or type(record.get('bytes')) is not int or record != {'bytes':len(files[name]), 'sha256':hashlib.sha256(files[name]).hexdigest()}:
                raise BundleError('Digest or size mismatch')
        if set(trace) != {'format','synthetic','actions'} or trace['format'] != 'activity-trace/1' or type(trace['synthetic']) is not bool:
            raise BundleError('Invalid trace header')
        actions = trace['actions']
        if type(actions) is not list or not 1 <= len(actions) <= 128 or type(manifest['actions']) is not int or len(actions) != manifest['actions']:
            raise BundleError('Invalid action count')
        previous, names = -1, []
        for i, a in enumerate(actions):
            if set(a) != {'id','timestamp_ms','kind','text','screenshot'} or a['id'] != f'action{i+1:04d}':
                raise BundleError('Invalid action')
            if type(a['timestamp_ms']) is not int or not previous <= a['timestamp_ms'] <= 2**53-1 or a['timestamp_ms'] < 0:
                raise BundleError('Invalid timestamp')
            previous = a['timestamp_ms']
            if a['kind'] not in ['click','type','move','key','wait','observe'] or type(a['text']) is not dict or not set(a['text']) <= {'label','value','url','key'}:
                raise BundleError('Invalid action fields')
            if any(type(t) is not str or len(t)>4096 or any(0xD800<=ord(c)<=0xDFFF for c in t) for t in a['text'].values()):
                raise BundleError('Invalid text')
            name = a['screenshot']
            if not isinstance(name,str) or not re.fullmatch(r'image\d{4}\.png', name):
                raise BundleError('Invalid image name')
            if name not in names:
                names.append(name)
        if names != [f'image{i+1:04d}.png' for i in range(len(names))] or type(manifest['images']) is not int or manifest['images'] != len(names) or len(names)>64:
            raise BundleError('Invalid image sequence')
        if set(files) != set(names) | {'trace.json','manifest.json'}:
            raise BundleError('Unreferenced image')
        pixels = 0
        for name in names:
            data = files[name]
            if data[:8] != b'\x89PNG\r\n\x1a\n':
                raise BundleError('Not PNG')
            pos, chunks = 8, []
            while pos < len(data):
                size = struct.unpack('>I',data[pos:pos+4])[0]
                chunk = data[pos+4:pos+8]
                if chunk not in (b'IHDR',b'IDAT',b'IEND') or pos+12+size>len(data):
                    raise BundleError('Metadata or invalid PNG chunk')
                chunks.append(chunk)
                pos += 12+size
            if (pos != len(data) or len(chunks)<3 or chunks[0] != b'IHDR' or chunks[-1] != b'IEND'
                    or any(chunk != b'IDAT' for chunk in chunks[1:-1]) or data[24:26] != b'\x08\x02'):
                raise BundleError('Invalid PNG layout')
            with Image.open(io.BytesIO(data)) as im:
                if im.mode != 'RGB' or im.width>2048 or im.height>2048 or im.width*im.height>4194304:
                    raise BundleError('Invalid image dimensions or mode')
                pixels += im.width*im.height
                if pixels>16777216:
                    raise BundleError('Decoded pixel limit')
                im.verify()
        return {'actions':len(actions),'images':len(names),'bytes':sum(map(len,files.values()))}
    except (KeyError, TypeError, IndexError, struct.error, json.JSONDecodeError) as e:
        raise BundleError('Malformed bundle') from e
