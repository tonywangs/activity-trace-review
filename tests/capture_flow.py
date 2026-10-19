"""Real Chromium interactions with public facts; no hand-authored action trace.

Automation operates the visible consent controls as the test participant. This is
browser integration evidence, not evidence of an unaided human usability study.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from PIL import Image
from playwright.async_api import async_playwright, expect
from activity_trace_review.recorder import CaptureSession, workbench_process, MAX_ACTIONS
from activity_trace_review.validate import validate_bundle

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/tmp/activity-trace-browsers')
SECRET = 'TEST_ONLY_EXCLUDE_71d2'
BEFORE = 'TEST_ONLY_BEFORE_START'
AFTER = 'TEST_ONLY_AFTER_STOP'


async def recorded_click(page, selector, count):
    await page.locator(selector).click()
    await expect(page.locator('#count')).to_have_text(f'{count} / 16 actions')
    await expect(page.locator('#surface')).not_to_have_attribute('inert', '')


async def exercise(url, tmp):
    evidence = tmp / 'evidence'
    evidence.mkdir()
    external = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--disable-background-networking'])
        context = await browser.new_context(viewport={'width': 1000, 'height': 950}, service_workers='block', accept_downloads=True)
        origin = url.split('/#')[0]
        async def route(request):
            if request.request.url.startswith(origin + '/'):
                await request.continue_()
            else:
                external.append(request.request.url)
                await request.abort()
        await context.route('**/*', route)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        session = CaptureSession(page, url, tmp / 'raw')
        await session.install()
        await expect(page.locator('#start')).to_be_disabled()
        # Direct start without consent is rejected by Python as well as the UI.
        denied = await page.evaluate('async () => {try {await recorderStart(); return false;} catch {return true;}}')
        assert denied and not session.active
        await page.locator('#note').fill(BEFORE)
        await page.locator('#commit').click()
        assert not session.actions and not session.images
        await page.locator('#note').fill('')
        await page.locator('#commit').click()
        await page.locator('#consent').check()
        await page.locator('#start').click()
        await expect(page.locator('#captureStatus')).to_contain_text('RECORDING')
        await page.screenshot(path=str(evidence / 'recording.png'), full_page=True)
        await page.set_viewport_size({'width': 1000, 'height': 700})
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        stop_box = await page.locator('#stop').bounding_box()
        assert 0 <= stop_box['y'] < 700 and await page.locator('#stop').is_visible()
        await page.set_viewport_size({'width': 1000, 'height': 950})
        await page.evaluate('window.scrollTo(0, 0)')
        # Synthetic DOM dispatch is explicitly excluded from recording.
        await page.locator('#sun').dispatch_event('click')
        assert not session.actions
        await recorded_click(page, '#sun', 1)
        await recorded_click(page, '#keep', 2)
        await page.locator('#note').fill(SECRET)
        await recorded_click(page, '#commit', 3)
        await page.locator('#note').fill('Sun is larger than Earth.')
        await recorded_click(page, '#commit', 4)
        await recorded_click(page, '#earth', 5)
        await page.locator('#stop').click()
        await expect(page.locator('#reviewLink')).to_be_visible()
        await expect(page.locator('#captureStatus')).to_contain_text('OFF — Stopped. 5 actions saved')
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp / 'raw').iterdir()}
        await page.locator('#note').fill(AFTER)
        await page.locator('#commit').click()
        await page.locator('#sun').click()
        await page.wait_for_timeout(150)
        assert len(session.actions) == 5 and len(session.images) == 5 and not session.active
        assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp / 'raw').iterdir()}
        trace = json.loads((tmp / 'raw' / 'trace.json').read_text())
        assert not trace['synthetic']
        assert [a['kind'] for a in trace['actions']] == ['click', 'click', 'type', 'type', 'click']
        assert trace['actions'][2]['text']['value'] == SECRET
        assert BEFORE not in json.dumps(trace) and AFTER not in json.dumps(trace)
        # Review the recorded source with the actual workbench controls.
        review = await context.new_page()
        await review.goto(url)
        await expect(review.locator('#position')).to_have_text('1 / 5')
        await expect(review.locator('#sourceBadge')).to_have_text('NON-SYNTHETIC INPUT')
        # Keep actions 2..4, excluding the initial and final planet selections.
        await review.locator('#segmentStart').select_option('step01')
        await review.locator('#segmentEnd').select_option('step03')
        await review.locator('#addSegment').click()
        await review.locator('#segmentList li').first.locator('button').click()
        await expect(review.locator('#counts')).to_have_text('3/5')
        for i in (1, 2, 3):
            await review.locator('#timeline .action').nth(i).click()
            if i == 2:
                await review.locator('textarea[data-field=value]').fill('[removed]')
                # Mask the whole notes column, including both draft and committed text.
                for field, value in [('rectX', '450'), ('rectY', '0'), ('rectW', '450'), ('rectH', '420')]:
                    await review.locator('#' + field).fill(value)
                await review.locator('#addRect').click()
            await review.locator('#reviewed').check()
        await review.locator('#confirmed').check()
        async with review.expect_download() as download:
            await review.locator('#saveReview').click()
        await (await download.value).save_as(evidence / 'review.json')
        await review.locator('#destination').fill('captured-example')
        async with review.expect_download() as download:
            await review.locator('#export').click()
        await (await download.value).save_as(tmp / 'example.zip')
        await expect(review.locator('#status')).to_contain_text('Published captured-example')
        await review.locator('#verifyExport').click()
        await expect(review.locator('#status')).to_contain_text('Integrity verified: 3 actions, 3 images')
        await review.locator('#timeline .action').nth(2).click()
        await review.wait_for_function("document.querySelector('#canvas').getContext('2d').getImageData(600,200,1,1).data[0] === 0")
        await review.screenshot(path=str(evidence / 'reviewed.png'), full_page=True)
        bundle = tmp / 'exports' / 'captured-example'
        info = validate_bundle(bundle)
        output = json.loads((bundle / 'trace.json').read_text())
        assert len(output['actions']) == 3 and output['synthetic'] is False
        assert [a['timestamp_ms'] for a in output['actions']] == [a['timestamp_ms'] for a in trace['actions'][1:4]]
        assert [a['text']['value'] for a in output['actions']] == ['Sun: Approximate diameter: 1.4 million km', '[removed]', 'Sun is larger than Earth.']
        assert set(p.name for p in bundle.iterdir()) == {'trace.json','manifest.json','image0001.png','image0002.png','image0003.png'}
        # Independent source-aware pixel oracle: no exporter redaction functions used.
        for n, source_index in enumerate((1, 2, 3), 1):
            with Image.open(bundle / f'image{n:04d}.png') as actual, Image.open(tmp / 'raw' / f'capture{source_index:02d}.png') as original:
                actual = actual.convert('RGB'); original = original.convert('RGB')
                assert actual.size == original.size == (900, 420), (actual.size, original.size)
                for y in range(420):
                    for x in range(900):
                        expected = (0,0,0) if source_index == 2 and x >= 450 else original.getpixel((x,y))
                        assert actual.getpixel((x,y)) == expected
        for path in bundle.iterdir():
            for excluded in (SECRET, BEFORE, AFTER, 'step00', 'step04'):
                assert excluded.encode() not in path.read_bytes()
        shutil.copytree(tmp / 'raw', evidence / 'source')
        shutil.copytree(bundle, evidence / 'bundle')
        # Stop while a screenshot is in progress: pending data must be discarded.
        race_page = await context.new_page()
        race = CaptureSession(race_page, url, tmp / 'race')
        await race.install()
        await race_page.locator('#consent').check(); await race_page.locator('#start').click()
        await expect(race_page.locator('#captureStatus')).to_contain_text('RECORDING')
        entered, release = asyncio.Event(), asyncio.Event()
        original_screenshot = race_page.locator('#surface').__class__.screenshot
        async def delayed_screenshot(locator, *args, **kwargs):
            entered.set(); await release.wait()
            return await original_screenshot(locator, *args, **kwargs)
        from unittest.mock import patch
        with patch('playwright.async_api.Locator.screenshot', delayed_screenshot):
            await race_page.locator('#keep').click()
            await asyncio.wait_for(entered.wait(), 5)
            await race_page.locator('#stop').click()
            assert not await race_page.evaluate('window.captureActive')
            release.set()
            await expect(race_page.locator('#captureStatus')).to_contain_text('0 actions saved')
        assert not race.actions and not race.images and not (tmp / 'race').exists()
        # Automatic count bound is exercised with actual trusted button interactions.
        cap_page = await context.new_page()
        capped = CaptureSession(cap_page, url, tmp / 'capped')
        await capped.install()
        await cap_page.locator('#consent').check(); await cap_page.locator('#start').click()
        await expect(cap_page.locator('#captureStatus')).to_contain_text('RECORDING')
        for i in range(MAX_ACTIONS):
            await cap_page.locator('#keep').click()
            await expect(cap_page.locator('#count')).to_have_text(f'{i+1} / 16 actions')
        await expect(cap_page.locator('#captureStatus')).to_contain_text('16-action limit reached')
        assert len(capped.actions) == 16 and not capped.active
        # Browser timer boundary without a five-minute sleep; real events before/after.
        timed_page = await context.new_page()
        await timed_page.clock.install()
        timed = CaptureSession(timed_page, url, tmp / 'timed')
        await timed.install()
        await timed_page.locator('#consent').check(); await timed_page.locator('#start').click()
        await expect(timed_page.locator('#captureStatus')).to_contain_text('RECORDING')
        await recorded_click(timed_page, '#keep', 1)
        await timed_page.clock.fast_forward(300001)
        await expect(timed_page.locator('#captureStatus')).to_contain_text('Five-minute limit reached')
        await timed_page.locator('#sun').click()
        assert len(timed.actions) == 1 and not timed.active
        # Backend elapsed-time guard is independent of the page timer.
        expired_page = await context.new_page()
        expired = CaptureSession(expired_page, url, tmp / 'expired')
        await expired.install()
        await expired_page.locator('#consent').check(); await expired_page.locator('#start').click()
        await expect(expired_page.locator('#captureStatus')).to_contain_text('RECORDING')
        expired.start_time -= 301
        await expired_page.locator('#keep').click()
        await expect(expired_page.locator('#captureStatus')).to_contain_text('Capture limit reached')
        assert not expired.actions and not expired.images and not expired.active
        assert not external and not errors, (external, errors)
        report = {'browser': browser.version, 'automated_participant': True,
                  'input': 'Public NASA Earth/Sun facts in bundled offline task page',
                  'captured_actions': 5, 'exported_actions': info['actions'],
                  'explicit_opt_in_checked': True, 'before_start_and_after_stop_excluded': True,
                  'pending_capture_discarded_on_stop': True, 'action_limit_checked': 16,
                  'untrusted_dom_events_ignored': True, 'all_export_pixels_checked': 1134000,
                  'timer_limit_checked_with_browser_clock': True, 'backend_time_guard_checked': True,
                  'stop_control_visible_after_scroll': True,
                  'external_requests_attempted': external, 'browser_errors': errors,
                  'excluded_text': [SECRET, BEFORE, AFTER],
                  'limitations': ['Automated browser participant, not a human usability study.',
                                  'Only bundled panel buttons and committed notes are recorded.']}
        (evidence / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        await browser.close()
        destination = ROOT / 'results' / 'capture'
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(evidence, destination)
        print(json.dumps(report, sort_keys=True))


def main():
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with workbench_process(tmp / 'exports') as url:
            asyncio.run(exercise(url, tmp))


if __name__ == '__main__':
    main()
