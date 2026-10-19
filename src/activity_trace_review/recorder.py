"""Opt-in recorder for the bundled, network-isolated task page only."""
import asyncio
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

from .core import Invalid, dumps, load_files

MAX_ACTIONS = 16
MAX_SECONDS = 300


@contextmanager
def workbench_process(export_root):
    process = subprocess.Popen(
        [sys.executable, '-m', 'activity_trace_review.cli', 'serve', '--port', '0',
         '--export-root', str(export_root)], stdout=subprocess.PIPE, text=True)
    try:
        line = process.stdout.readline().strip()
        if not line.startswith('Workbench: '):
            raise Invalid('Workbench failed to start')
        yield line.removeprefix('Workbench: ')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()


class CaptureSession:
    def __init__(self, page, workbench_url, destination):
        self.page = page
        self.url = workbench_url
        self.origin, self.token = workbench_url.split('/#')
        self.destination = Path(destination)
        if self.destination.exists():
            raise Invalid('Recording destination must be fresh')
        self.actions = []
        self.images = {}
        self.active = False
        self.started = False
        self.finished = False
        self.pending = asyncio.Lock()
        self.start_time = None

    async def install(self):
        await self.page.expose_binding('recorderStart', self.start)
        await self.page.expose_binding('recorderEvent', self.capture)
        await self.page.expose_binding('recorderStop', self.stop)
        await self.page.goto(self.origin + '/session.html')

    def check_page(self, source):
        if source['page'] != self.page or source['frame'] != self.page.main_frame:
            raise Invalid('Only the controlled session can record')
        if self.page.url != self.origin + '/session.html':
            raise Invalid('Recording is restricted to the bundled task page')

    async def start(self, source):
        self.check_page(source)
        if self.started or not await self.page.locator('#consent').is_checked():
            raise Invalid('Explicit consent is required; launch again for a new session')
        self.started = self.active = True
        self.start_time = asyncio.get_running_loop().time()
        return {'maxActions': MAX_ACTIONS, 'maxSeconds': MAX_SECONDS}

    async def capture(self, source, event):
        self.check_page(source)
        async with self.pending:
            if not self.active or len(self.actions) >= MAX_ACTIONS:
                return False
            elapsed = int((asyncio.get_running_loop().time() - self.start_time) * 1000)
            if elapsed >= MAX_SECONDS * 1000:
                self.active = False
                return False
            if (type(event) is not dict or set(event) != {'kind', 'label', 'value'}
                    or event['kind'] not in ('click', 'type')
                    or any(type(event[k]) is not str or len(event[k]) > 4096 for k in event)):
                raise Invalid('Invalid controlled-page event')
            # Restore the supported layout so sticky consent controls cannot overlap
            # the panel in a screenshot. Fail closed after resize/zoom beyond it.
            await self.page.evaluate('window.scrollTo(0, 0)')
            layout = await self.page.evaluate('({width: innerWidth, height: innerHeight})')
            if layout['width'] < 1000 or layout['height'] < 900:
                raise Invalid('Capture requires the launched 1000 by 900 viewport; restore its size and relaunch')
            # The page makes its task surface inert until the screenshot completes.
            image = await self.page.locator('#surface').screenshot(type='png', animations='disabled')
            # Stop revokes consent immediately, including a screenshot in flight.
            if not self.active or not await self.page.evaluate('window.captureActive === true'):
                return False
            index = len(self.actions)
            name = f'capture{index:02d}.png'
            self.images[name] = image
            self.actions.append({'id': f'step{index:02d}', 'timestamp_ms': elapsed,
                                 'kind': event['kind'], 'text': {'label': event['label'], 'value': event['value']},
                                 'screenshot': name})
            return True

    async def stop(self, source):
        self.check_page(source)
        self.active = False
        async with self.pending:
            if self.finished:
                raise Invalid('Session already stopped')
            self.finished = True
            if not self.actions:
                return {'count': 0, 'url': None}
            files = {**self.images, 'trace.json': dumps({'format': 'activity-trace/1',
                     'synthetic': False, 'actions': self.actions})}
            load_files(files)  # All normal review limits apply before any persistence.
            self.destination.mkdir(mode=0o700)
            for name, data in files.items():
                with (self.destination / name).open('xb') as stream:
                    stream.write(data)
            body = dumps({'files': {name: base64.b64encode(data).decode('ascii') for name, data in files.items()}})
            request = urllib.request.Request(self.origin + '/api/import', data=body,
                headers={'Content-Type': 'application/json', 'X-Review-Token': self.token})
            # Local HTTP only; raw source remains available if import fails.
            with urllib.request.urlopen(request, timeout=15) as response:
                json.load(response)
            return {'count': len(self.actions), 'url': self.url}


async def run_browser(url, destination):
    try:
        from playwright.async_api import async_playwright, Error
    except ImportError as error:
        raise Invalid('Install capture dependencies: pip install -e ".[capture]"; python -m playwright install chromium') from error
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=False, args=['--disable-background-networking'])
        except Error as error:
            raise Invalid('Could not open Chromium. Install its browser binary and run record in a graphical desktop session. ' + str(error)) from error
        context = await browser.new_context(viewport={'width': 1000, 'height': 900},
                                            service_workers='block', accept_downloads=True)
        origin = url.split('/#')[0]
        await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page = await context.new_page()
        session = CaptureSession(page, url, destination)
        await session.install()
        print(f'Controlled session opened. Raw capture on explicit stop: {Path(destination).absolute()}', flush=True)
        print('Check consent, Start, interact, then Stop and review. Close the browser or Ctrl+C to exit.', flush=True)
        try:
            while browser.is_connected() and context.pages:
                await asyncio.sleep(.25)
        finally:
            session.active = False
            await browser.close()


def record(destination, export_root):
    if Path(destination).exists():
        raise Invalid('Recording destination must be fresh')
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/tmp/activity-trace-browsers')
    with workbench_process(export_root) as url:
        asyncio.run(run_browser(url, destination))
