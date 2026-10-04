"""Bounded deterministic performance inputs; never captures activity."""
import io
import json
import random
from PIL import Image, ImageDraw

def workload(images=64, dimension=512, actions=128, seed=1307):
    rng=random.Random(seed);files={}
    for i in range(images):
        image=Image.new('RGB',(dimension,dimension),(230,240,235));draw=ImageDraw.Draw(image)
        for _ in range(32):
            x,y=rng.randrange(dimension),rng.randrange(dimension)
            draw.rectangle((x,y,min(x+50,dimension-1),min(y+30,dimension-1)),fill=tuple(rng.randrange(256) for _ in range(3)))
        out=io.BytesIO();image.save(out,format='PNG');files[f'frame{i:02d}.png']=out.getvalue()
    data=[{'id':f'event{i:03d}','timestamp_ms':i*10,'kind':'observe','text':{'label':f'Synthetic workload {i}','value':'PLANTED_SECRET'},'screenshot':f'frame{i%images:02d}.png'} for i in range(actions)]
    files['trace.json']=json.dumps({'format':'activity-trace/1','synthetic':True,'actions':data}).encode()
    return files
