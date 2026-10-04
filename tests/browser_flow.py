"""Real Chromium workflow; all non-workbench browser requests are blocked."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from activity_trace_review.core import dumps, write_fresh
from activity_trace_review.demo import demo_files
from activity_trace_review.validate import validate_bundle

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/activity-trace-browsers')

def main():
    started=time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);source=tmp/'source';files=demo_files()
        trace=json.loads(files['trace.json']);trace['actions'][0]['text']['label']='<img src="https://never-fetch.invalid/pwn" onerror="window.pwned=1">'
        files['trace.json']=dumps(trace);write_fresh(files,source)
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
        rss_file=tmp/'server-rss.json'
        runner=('import atexit,json,resource,signal,sys;from pathlib import Path;'
                'from activity_trace_review.cli import main;'
                'atexit.register(lambda:Path(sys.argv[1]).write_text(json.dumps(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)));'
                'signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));main(["serve","--port","0"])')
        server=subprocess.Popen([sys.executable,'-c',runner,str(rss_file)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            line=server.stdout.readline().strip();assert line.startswith('Workbench:'),line
            url=line.split(' ',1)[1];origin=url.split('/#')[0];token=url.split('#')[1]
            external=[];errors=[]
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,args=['--disable-background-networking'])
                context=browser.new_context(viewport={'width':1440,'height':1100},accept_downloads=True,service_workers='block')
                def route(req):
                    if req.request.url.startswith(origin+'/'):req.continue_()
                    else:external.append(req.request.url);req.abort()
                context.route('**/*',route)
                page=context.new_page();page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(url);expect(page.locator('#status')).to_contain_text('Start by importing')
                page.locator('#import').set_input_files([str(p) for p in sorted(source.iterdir())])
                expect(page.locator('#position')).to_have_text('1 / 12')
                expect(page.locator('#sourceBadge')).to_have_text('SYNTHETIC INPUT')
                expect(page.locator('#fields textarea[data-field=label]')).to_have_value(trace['actions'][0]['text']['label'])
                assert page.evaluate('window.pwned') is None
                assert page.locator('#fields img').count()==0
                # Canvas synchronization: known background pixel changes across screenshot boundaries.
                page.wait_for_function("() => document.querySelector('#canvas').getContext('2d').getImageData(0,0,1,1).data[0]===225")
                page.locator('body').click(position={'x':5,'y':5});page.keyboard.press('ArrowRight')
                expect(page.locator('#position')).to_have_text('2 / 12')
                page.keyboard.press('End');expect(page.locator('#position')).to_have_text('12 / 12')
                page.wait_for_function("() => document.querySelector('#canvas').getContext('2d').getImageData(0,0,1,1).data[0]===195")
                page.keyboard.press('Home');expect(page.locator('#position')).to_have_text('1 / 12')
                # Keyboard boundaries and segment editing; keep 2..6, remove action 3.
                page.keyboard.press('ArrowRight');page.keyboard.press('[')
                for _ in range(4):page.keyboard.press('ArrowRight')
                page.keyboard.press(']');page.keyboard.press('a')
                expect(page.locator('#segmentList li')).to_have_count(2)
                page.locator('#segmentList li').first.locator('button').click()
                expect(page.locator('#counts')).to_have_text('5/12')
                page.locator('#timeline .action').nth(2).click();page.locator('body').click(position={'x':5,'y':5});page.keyboard.press('d')
                expect(page.locator('#removed')).to_be_checked();expect(page.locator('#counts')).to_have_text('4/12')
                # Edits survive navigation; typing D/R/arrow keys must not trigger app shortcuts.
                for index in [1,3,4,5]:
                    page.locator('#timeline .action').nth(index).click()
                    field=page.locator('textarea[data-field=value]');field.fill('D R replacement');field.press('ArrowLeft')
                    expect(page.locator('#position')).to_have_text(f'{index+1} / 12')
                    expect(page.locator('#removed')).not_to_be_checked()
                    field.fill('[removed]');page.locator('textarea[data-field=url]').fill('')
                # Shared screenshot masks drawn by drag and exact-coordinate controls.
                page.locator('#timeline .action').nth(1).click()
                canvas=page.locator('#canvas');box=canvas.bounding_box()
                scale=box['width']/320
                page.mouse.move(box['x']+16*scale+.1,box['y']+16*scale+.1);page.mouse.down()
                page.mouse.move(box['x']+256*scale+.1,box['y']+48*scale+.1);page.mouse.up()
                expect(page.locator('#rectangles li')).to_have_count(1)
                page.locator('body').click(position={'x':5,'y':5});page.keyboard.press('r');expect(page.locator('#reviewed')).to_be_checked()
                page.locator('#timeline .action').nth(3).click();page.locator('#addRect').click();page.locator('#reviewed').check()
                page.locator('#timeline .action').nth(4).click();expect(page.locator('#reviewed')).to_be_checked();expect(page.locator('#rectangles li')).to_have_count(1)
                expect(page.locator('#export')).to_be_disabled()
                page.locator('#confirmed').check();expect(page.locator('#export')).to_be_enabled()
                # Save by keyboard, then reject a mismatched/invalid review without changing work.
                with page.expect_download() as got:page.keyboard.press('Control+s')
                saved=tmp/'review.json';got.value.save_as(saved);review=json.loads(saved.read_bytes())
                assert review['screenshots']['screen0.png']['rects']==[[16,16,240,32]]
                for mutation in [lambda r:r.update(source='wrong'),lambda r:r.update(format='v999'),lambda r:r['screenshots']['screen0.png'].update(rects=[[-1,0,5,5]])]:
                    bad=copy.deepcopy(review);mutation(bad);path=tmp/'invalid-review.json';path.write_text(json.dumps(bad))
                    page.locator('#loadReview').set_input_files(str(path));expect(page.locator('#status')).to_have_class('error')
                    expect(page.locator('#counts')).to_have_text('4/12');expect(page.locator('#export')).to_be_enabled()
                # Mutate and restore a valid review; reload is an atomic replacement.
                page.locator('#clearRects').click();expect(page.locator('#reviewed')).not_to_be_checked();expect(page.locator('#export')).to_be_disabled()
                page.locator('#loadReview').set_input_files(str(saved));expect(page.locator('#status')).to_have_text('Source-bound review loaded.')
                expect(page.locator('#reviewed')).to_be_checked();expect(page.locator('#export')).to_be_enabled()
                # Failed source import must preserve the current reviewed source.
                malformed=tmp/'trace.json';malformed.write_text('{"format":"wrong"}')
                page.locator('#import').set_input_files(str(malformed));expect(page.locator('#status')).to_have_class('error')
                expect(page.locator('#counts')).to_have_text('4/12');expect(page.locator('#export')).to_be_enabled()
                # Cancel a held export response: no partial download, existing review remains usable.
                held=[]
                page.route('**/api/export',lambda route:held.append(route))
                page.locator('#export').click();expect(page.locator('#cancel')).to_be_enabled();page.locator('#cancel').click()
                expect(page.locator('#status')).to_contain_text('Operation cancelled')
                for pending in held:pending.abort()
                page.unroute('**/api/export')
                expect(page.locator('#export')).to_be_enabled()
                archives=[]
                for n in range(2):
                    with page.expect_download() as got:page.locator('#export').click()
                    archive=tmp/f'bundle{n}.zip';got.value.save_as(archive);archives.append(archive.read_bytes())
                assert archives[0]==archives[1]
                bundle=tmp/'bundle';bundle.mkdir()
                with zipfile.ZipFile(io.BytesIO(archives[0])) as z:
                    assert set(z.namelist())=={'trace.json','manifest.json','image0001.png','image0002.png'}
                    z.extractall(bundle) # test-created, allowlisted names only
                info=validate_bundle(bundle);assert info['actions']==4
                output=json.loads((bundle/'trace.json').read_bytes());assert [a['timestamp_ms'] for a in output['actions']]==[250,750,1000,1250]
                for p in bundle.iterdir():assert b'SYNTHETIC_SECRET' not in p.read_bytes()
                for n,original in [(1,'screen0.png'),(2,'screen1.png')]:
                    with Image.open(bundle/f'image{n:04d}.png') as im,Image.open(source/original) as src:
                        for y in range(im.height):
                            for x in range(im.width):assert im.getpixel((x,y))==((0,0,0) if 16<=x<256 and 16<=y<48 else src.getpixel((x,y)))
                ROOT.joinpath('results').mkdir(exist_ok=True)
                page.screenshot(path=str(ROOT/'results/workbench.png'),full_page=True)
                dom_count=page.locator('*').count()
                # Reload the exported bundle as input, then verify actual black image pixels.
                page.locator('#import').set_input_files([str(p) for p in sorted(bundle.iterdir())]);expect(page.locator('#position')).to_have_text('1 / 4')
                page.wait_for_function("() => document.querySelector('#canvas').getContext('2d').getImageData(20,20,1,1).data[0]===0")
                assert page.locator('#rectangles li').count()==0 # pixels remain black without overlays
                expect(page.locator('#reviewed')).not_to_be_checked();expect(page.locator('#export')).to_be_disabled()
                # Maximum action/image count and decoded-pixel budget, one preview canvas.
                from workloads import workload
                large=tmp/'large';large_files=workload();large_trace=json.loads(large_files['trace.json'])
                large_trace['actions'][0]['id']='__proto__';large_trace['actions'][-1]['id']='constructor'
                large_files['trace.json']=dumps(large_trace);write_fresh(large_files,large)
                page.locator('#import').set_input_files([str(p) for p in sorted(large.iterdir())])
                expect(page.locator('#position')).to_have_text('1 / 128')
                expect(page.locator('#timeline .action')).to_have_count(128)
                page.locator('textarea[data-field=value]').fill('prototype-safe replacement')
                page.locator('body').click(position={'x':5,'y':5});page.keyboard.press('End')
                expect(page.locator('#position')).to_have_text('128 / 128')
                page.locator('textarea[data-field=value]').fill('constructor-safe replacement')
                with page.expect_download() as got:page.locator('#saveReview').click()
                prototype_review=tmp/'prototype-review.json';got.value.save_as(prototype_review)
                special=json.loads(prototype_review.read_text())['replacements']
                assert special['__proto__']['value']=='prototype-safe replacement'
                assert special['constructor']['value']=='constructor-safe replacement'
                assert page.evaluate('Object.prototype.value') is None
                expect(page.locator('#canvas')).to_have_attribute('width','512')
                maximum_dom=page.locator('*').count();assert maximum_dom<800
                assert page.locator('canvas').count()==1
                # API rejects unauthorized, cross-origin, and DNS rebinding requests.
                for headers in [{},{'X-Review-Token':token,'Origin':'https://evil.invalid'},{'X-Review-Token':token,'Host':'evil.invalid'}]:
                    response=context.request.get(origin+'/api/state',headers=headers);assert response.status==400
                assert not external,external;assert not errors,errors
                assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
                server.terminate();server.wait(timeout=5);server_hwm=json.loads(rss_file.read_text())
                report={'chromium':browser.version,'elapsed_seconds':round(time.perf_counter()-started,3),'dom_elements':dom_count,
                        'timeline_buttons':12,'maximum_workload_dom_elements':maximum_dom,'maximum_workload_timeline_buttons':128,'server_peak_rss_kib':server_hwm,'canvas_elements':1,'export_zip_bytes':len(archives[0]),'export_bundle_bytes':info['bytes'],
                        'deterministic_replay':True,'external_requests_attempted':len(external),'external_request_policy':'abort non-loopback-workbench requests',
                        'browser_errors':errors,'workflow':'import, navigation, keyboard editing, segments, removal, text, drag masks, shared review, save/reload, invalid imports, cancellation, export, independent pixel validation, reopen'}
                browser.close()
                print(json.dumps(report,sort_keys=True));(ROOT/'results/browser.json').write_text(json.dumps(report,indent=2)+'\n')
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            errors=server.stderr.read()
            if errors:print(errors,file=sys.stderr)

if __name__=='__main__':main()
