"""Real-browser smoke test; run separately from unit tests on a loopback-capable host."""
from pathlib import Path
import subprocess
import sys
import tempfile
import re
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright, expect


def main():
    port = 18765
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'iqscope_web.server:create_app',
                                '--factory', '--host', '127.0.0.1', '--port', str(port)])
    browser = None
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/capabilities', timeout=1) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(.1)
        else:
            raise RuntimeError('Web server did not start')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1280, 'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{port}')
                page.get_by_role('button', name='Essayer la démo synthétique').click()
                expect(page.locator("#status-text")).to_have_text(re.compile("^Analyse terminée"), timeout=30000)
                assert page.locator('#metric-signals').inner_text() == '2'
                assert page.locator('#metric-frames').inner_text() == '0'
                page.locator('.signal summary').last.click()
                assert page.locator('audio').count() >= 1
                assert page.locator('#download').is_visible()
                page.get_by_role('button',name='Voir les capacités').click()
                expect(page.get_by_role('dialog')).to_be_visible()
                page.get_by_role('button',name='Fermer').click()
                page.get_by_role('button',name='Explorer les jeux de données').click()
                expect(page.locator('#dataset-dialog')).to_be_visible()
                expect(page.locator('#dataset-list .capability')).to_have_count(16)
                page.get_by_role('button',name='Fermer le catalogue').click()
                with tempfile.TemporaryDirectory() as directory:
                    from iqscope import demo
                    meta = demo(directory)
                    page.locator('#iq-file').set_input_files(str(meta.with_suffix('.sigmf-data')))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator("#status-text")).to_have_text(re.compile("^Analyse terminée"), timeout=30000)
                    assert page.locator('#metric-signals').inner_text() == '2'
                Path('browser-artifacts').mkdir(exist_ok=True)
                page.screenshot(path='browser-artifacts/desktop.png', full_page=True)
                page.get_by_role('tab',name='SDR en direct').click()
                assert page.locator('#live-panel').is_visible()
                assert page.locator('#live-frequency').input_value() == '100'
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path='browser-artifacts/mobile.png', full_page=True)
                assert not errors, errors
            except BaseException:
                Path('browser-artifacts').mkdir(exist_ok=True)
                page.screenshot(path='browser-artifacts/failure.png',full_page=True)
                raise
            finally:
                browser.close()
                browser = None
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == '__main__':
    main()
