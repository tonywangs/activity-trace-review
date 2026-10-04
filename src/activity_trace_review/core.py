"""Strict input/review schemas and deterministic, allowlisted bundle construction."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from PIL import Image, ImageDraw

MIB = 1024 * 1024
LIMITS = dict(input_bytes=24*MIB, json_bytes=512*1024, image_bytes=8*MIB,
              dimension=2048, image_pixels=4_194_304, total_pixels=16_777_216,
              actions=128, images=64, text_chars=4096, rectangles=128,
              export_bytes=32*MIB, seconds=10, files=66)
KINDS = {'click', 'type', 'move', 'key', 'wait', 'observe'}
FIELDS = {'label', 'value', 'url', 'key'}
ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
PNG = re.compile(r'[A-Za-z0-9_-]{1,64}\.png\Z')

class Invalid(ValueError):
    pass

class Budget:
    def __init__(self, seconds=None, cancelled=None):
        self.end = time.monotonic() + (LIMITS['seconds'] if seconds is None else seconds)
        self.cancelled = cancelled or (lambda: False)
    def check(self):
        if self.cancelled():
            raise Invalid('Operation cancelled')
        if time.monotonic() >= self.end:
            raise Invalid('Processing time limit exceeded')

def require(condition, message):
    if not condition:
        raise Invalid(message)

def keys(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), f'Invalid {label} fields')

def integer(value, lo, hi):
    return type(value) is int and lo <= value <= hi

def text(value):
    return (type(value) is str and len(value) <= LIMITS['text_chars']
            and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))

def dumps(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')

def loads(data, max_bytes=None):
    require(len(data) <= (LIMITS['json_bytes'] if max_bytes is None else max_bytes), 'JSON byte limit exceeded')
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'Duplicate JSON key')
            result[k] = v
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Invalid('Non-finite JSON')))
    except (ValueError, UnicodeError, RecursionError) as e:
        raise Invalid('Malformed JSON: ' + str(e)[:120]) from e

def rgb_png(image):
    out = io.BytesIO()
    # New image: neither PNG metadata nor Pillow info propagates.
    clean = Image.frombytes('RGB', image.size, image.tobytes())
    clean.save(out, format='PNG', optimize=False, compress_level=9)
    return out.getvalue()

def decode(data):
    require(len(data) <= LIMITS['image_bytes'], 'Image byte limit exceeded')
    try:
        with Image.open(io.BytesIO(data)) as im:
            require(im.format == 'PNG' and im.n_frames == 1, 'Only single-frame PNG is supported')
            w, h = im.size
            require(0 < w <= LIMITS['dimension'] and 0 < h <= LIMITS['dimension']
                    and w*h <= LIMITS['image_pixels'], 'Image dimensions exceed limit')
            require(im.mode in ('RGB', 'RGBA'), 'PNG must be RGB or RGBA')
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if im.mode == 'RGBA':
                bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
                return Image.alpha_composite(bg, im).convert('RGB')
            return im.convert('RGB')
    except Invalid:
        raise
    except Exception as e:
        raise Invalid('Malformed or unsupported PNG') from e

@dataclass
class Source:
    trace: dict
    images: dict[str, Image.Image]
    digest: str
    hashes: dict[str, str]

    @property
    def actions(self):
        return self.trace['actions']

def load_files(files: dict[str, bytes], budget=None):
    budget = budget or Budget()
    budget.check()
    require(type(files) is dict and 1 <= len(files) <= LIMITS['files'], 'File count limit')
    require(all(type(k) is str and (k in ('trace.json', 'manifest.json') or PNG.fullmatch(k))
                and type(v) is bytes for k, v in files.items()), 'Invalid filename or file data')
    require(sum(map(len, files.values())) <= LIMITS['input_bytes'], 'Input byte limit exceeded')
    require('trace.json' in files, 'trace.json is required')
    if 'manifest.json' in files:
        from .validate import validate_files
        try:
            validate_files(files)
        except (ValueError, OSError) as e:
            raise Invalid('Invalid exported bundle: ' + str(e)) from e
    trace = loads(files['trace.json'])
    keys(trace, ['format', 'synthetic', 'actions'], 'trace')
    require(trace['format'] == 'activity-trace/1', 'Unsupported trace version')
    require(type(trace['synthetic']) is bool, 'synthetic must be boolean')
    actions = trace['actions']
    require(type(actions) is list and 1 <= len(actions) <= LIMITS['actions'], 'Action count limit')
    ids, names, previous = set(), set(), -1
    for a in actions:
        budget.check()
        keys(a, ['id', 'timestamp_ms', 'kind', 'text', 'screenshot'], 'action')
        require(type(a['id']) is str and ID.fullmatch(a['id']) and a['id'] not in ids, 'Invalid or duplicate action id')
        ids.add(a['id'])
        require(integer(a['timestamp_ms'], 0, 2**53-1) and a['timestamp_ms'] >= previous,
                'Timestamps must be nondecreasing safe integers')
        previous = a['timestamp_ms']
        require(type(a['kind']) is str and a['kind'] in KINDS, 'Unsupported action kind')
        require(type(a['text']) is dict and set(a['text']) <= FIELDS and all(text(v) for v in a['text'].values()), 'Invalid text fields')
        require(type(a['screenshot']) is str and PNG.fullmatch(a['screenshot']), 'Invalid screenshot reference')
        names.add(a['screenshot'])
    require(len(names) <= LIMITS['images'], 'Image count limit')
    require(set(files) - {'trace.json', 'manifest.json'} == names, 'Missing or unreferenced screenshots')
    images, pixels = {}, 0
    for name in sorted(names):
        budget.check()
        image = decode(files[name])
        pixels += image.width * image.height
        require(pixels <= LIMITS['total_pixels'], 'Total decoded pixel limit exceeded')
        images[name] = image
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items()) if name != 'manifest.json'}
    digest = hashlib.sha256(dumps(hashes)).hexdigest()
    budget.check()
    return Source(trace, images, digest, hashes)

def read_directory(path, budget=None):
    budget = budget or Budget()
    path = Path(path)
    require(path.is_dir() and not path.is_symlink(), 'Input must be a real directory')
    files, total = {}, 0
    for p in path.iterdir():
        budget.check()
        require(len(files) < LIMITS['files'], 'File count limit')
        require(p.name in ('trace.json', 'manifest.json') or PNG.fullmatch(p.name), 'Unexpected input file')
        # O_NOFOLLOW closes the symlink race; bounded reads also handle growing files.
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as f:
            import stat
            require(stat.S_ISREG(os.fstat(f.fileno()).st_mode), 'Only regular files are accepted')
            cap = LIMITS['json_bytes'] if p.suffix == '.json' else LIMITS['image_bytes']
            data = f.read(cap + 1)
        require(len(data) <= cap, 'File byte limit exceeded')
        total += len(data)
        require(total <= LIMITS['input_bytes'], 'Input byte limit exceeded')
        files[p.name] = data
    return load_files(files, budget)

def new_review(source):
    return {'format': 'activity-review/1', 'source': source.digest,
            'segments': [[source.actions[0]['id'], source.actions[-1]['id']]],
            'removed': [], 'replacements': {}, 'screenshots': {}, 'confirmed': False}

def validate_review(source, review, ready=False):
    keys(review, ['format','source','segments','removed','replacements','screenshots','confirmed'], 'review')
    require(review['format'] == 'activity-review/1', 'Unsupported review version')
    require(review['source'] == source.digest, 'Review belongs to a different source')
    require(type(review['confirmed']) is bool, 'Invalid confirmation')
    index = {a['id']: i for i, a in enumerate(source.actions)}
    segments = review['segments']
    require(type(segments) is list and len(segments) <= LIMITS['actions'], 'Invalid segments')
    chosen = set()
    for pair in segments:
        require(type(pair) is list and len(pair) == 2 and all(type(x) is str and x in index for x in pair), 'Invalid segment references')
        lo, hi = map(index.get, pair)
        require(lo <= hi, 'Reversed segment')
        chosen.update(range(lo, hi + 1))
    removed = review['removed']
    require(type(removed) is list and all(type(x) is str and x in index for x in removed)
            and len(set(removed)) == len(removed), 'Invalid removed references')
    replacements = review['replacements']
    require(type(replacements) is dict and set(replacements) <= set(index), 'Invalid replacement references')
    for aid, fields in replacements.items():
        require(type(fields) is dict and set(fields) <= set(source.actions[index[aid]]['text'])
                and all(text(v) for v in fields.values()), 'Invalid replacement fields')
    shots = review['screenshots']
    require(type(shots) is dict and set(shots) <= set(source.images), 'Invalid screenshot references')
    for name, state in shots.items():
        keys(state, ['rects', 'reviewed'], 'screenshot review')
        require(type(state['reviewed']) is bool and type(state['rects']) is list
                and len(state['rects']) <= LIMITS['rectangles'], 'Invalid screenshot state')
        w, h = source.images[name].size
        for rect in state['rects']:
            require(type(rect) is list and len(rect) == 4 and all(type(v) is int for v in rect), 'Rectangle must contain four integers')
            x, y, rw, rh = rect
            require(x >= 0 and y >= 0 and rw > 0 and rh > 0 and x+rw <= w and y+rh <= h, 'Rectangle outside screenshot')
    selected = [a for i, a in enumerate(source.actions) if i in chosen and a['id'] not in removed]
    if ready:
        require(selected, 'No retained actions')
        require(review['confirmed'], 'Confirm retained text and selection before export')
        require(all(shots.get(a['screenshot'], {}).get('reviewed', False) for a in selected),
                'Every retained screenshot needs explicit review')
    return selected

def build_bundle(source, review, budget=None):
    budget = budget or Budget()
    budget.check()
    selected = validate_review(source, review, ready=True)
    names = list(dict.fromkeys(a['screenshot'] for a in selected))
    mapping, files = {}, {}
    for i, name in enumerate(names):
        budget.check()
        new_name = f'image{i+1:04d}.png'
        mapping[name] = new_name
        im = source.images[name].copy()
        draw = ImageDraw.Draw(im)
        for x, y, w, h in review['screenshots'][name]['rects']:
            draw.rectangle((x, y, x+w-1, y+h-1), fill=(0, 0, 0))
        files[new_name] = rgb_png(im)
        require(len(files[new_name]) <= LIMITS['image_bytes'], 'Reencoded image exceeds input image byte limit')
    actions = []
    for i, a in enumerate(selected):
        budget.check()
        actions.append({'id': f'action{i+1:04d}', 'timestamp_ms': a['timestamp_ms'],
                        'kind': a['kind'], 'text': {**a['text'], **review['replacements'].get(a['id'], {})},
                        'screenshot': mapping[a['screenshot']]})
    files['trace.json'] = dumps({'format': 'activity-trace/1', 'synthetic': source.trace['synthetic'], 'actions': actions})
    require(len(files['trace.json']) <= LIMITS['json_bytes'], 'Exported trace exceeds JSON byte limit')
    # No source identities, source hashes, review files, or arbitrary metadata are exported.
    files['manifest.json'] = dumps({'format': 'activity-bundle/1', 'actions': len(actions),
                                  'images': len(names), 'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                                                               for name, data in sorted(files.items())}})
    require(sum(map(len, files.values())) <= min(LIMITS['export_bytes'], LIMITS['input_bytes']), 'Export byte limit exceeded (bundle must remain reimportable)')
    budget.check()
    return files

def bundle_zip(files, budget=None):
    budget = budget or Budget()
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, data in sorted(files.items()):
            budget.check()
            info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
            info.external_attr = 0o100600 << 16
            z.writestr(info, data)
    require(out.tell() <= LIMITS['export_bytes'], 'Archive byte limit exceeded')
    return out.getvalue()

def write_fresh(files, destination, budget=None):
    """Exclusive reservation prevents replacing even an empty existing directory."""
    budget = budget or Budget()
    dest = Path(destination).absolute()
    require(not dest.exists() and not dest.is_symlink(), 'Output already exists')
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.trace-stage-', dir=dest.parent))
    reserved = False
    try:
        for name, data in files.items():
            budget.check()
            require(name in ('trace.json', 'manifest.json') or PNG.fullmatch(name), 'Invalid output filename')
            (staging / name).write_bytes(data)
        budget.check()
        dest.mkdir(mode=0o700)  # atomic collision check, no overwrites
        reserved = True
        for p in staging.iterdir():
            budget.check()
            os.replace(p, dest / p.name)
    except BaseException:
        if reserved:
            shutil.rmtree(dest)
        raise
    finally:
        shutil.rmtree(staging)
