"""Deterministic, wholly synthetic demonstration. No recorder or personal data."""
import io
from PIL import Image, ImageDraw, PngImagePlugin
from .core import dumps, load_files, new_review, write_fresh

SECRET_RECT = [16, 16, 240, 32]

def demo_files():
    files = {}
    for i in range(4):
        im = Image.new('RGB', (320, 180), (225-i*10, 235, 245))
        d = ImageDraw.Draw(im)
        d.rectangle((16,16,255,47), fill=(255,220,190))
        d.text((20,24), f'SYNTHETIC_SECRET_IMAGE_{i}', fill=(120,20,20))
        d.text((16,80), f'SYNTHETIC DEMO / screen {i+1}', fill=(20,40,60))
        d.rectangle((16,120,180,150), fill=(40,100+i*20,140))
        info = PngImagePlugin.PngInfo()
        info.add_text('Comment', 'SYNTHETIC_SECRET_METADATA')
        out = io.BytesIO()
        im.save(out, format='PNG', pnginfo=info)
        files[f'screen{i}.png'] = out.getvalue()
    actions = []
    for i in range(12):
        actions.append({'id':f'step{i:02d}', 'timestamp_ms':i*250, 'kind':['observe','click','type'][i%3],
                        'text':{'label':f'Synthetic step {i+1}', 'value':f'SYNTHETIC_SECRET_TEXT_{i}',
                                'url':'https://never-fetch.invalid/SYNTHETIC_SECRET_URL'},
                        'screenshot':f'screen{i//3}.png'})
    files['trace.json'] = dumps({'format':'activity-trace/1','synthetic':True,'actions':actions})
    return files

def example_review(source):
    review = new_review(source)
    review['replacements'] = {a['id']:{'value':'[removed]', 'url':''} for a in source.actions}
    review['screenshots'] = {name:{'rects':[SECRET_RECT.copy()], 'reviewed':True} for name in source.images}
    review['confirmed'] = True
    return review

def create_demo(destination):
    from pathlib import Path
    path = Path(destination)
    if path.exists():
        from .core import Invalid
        raise Invalid('Demo output already exists')
    files = demo_files()
    # Parent is reserved before writing; rollback handled by CLI/tests as needed.
    path.mkdir(parents=True, mode=0o700)
    try:
        write_fresh(files, path/'source')
        (path/'example-review.json').write_bytes(dumps(example_review(load_files(files))))
    except BaseException:
        import shutil
        shutil.rmtree(path)
        raise
