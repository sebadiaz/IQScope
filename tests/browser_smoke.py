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
                expect(page.locator('#dataset-list .capability')).to_have_count(21)
                expect(page.locator('#dataset-list .recording')).to_have_count(5)
                expect(page.get_by_role('button',name='Analyser l’extrait NOAA-15 (SARSAT-7) PDS')).to_be_visible()
                expect(page.locator('#dataset-list .recording').first).to_contain_text('250 kéch/s')
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
                # Exercise actual candidate text display through the same import UI.
                with tempfile.TemporaryDirectory() as directory:
                    from test_rtty import fixture, TEXT
                    import numpy as np
                    import json
                    x,fs = fixture()
                    raw = Path(directory)/'rtty.sigmf-data'
                    meta = Path(directory)/'rtty.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.rtty-text').first).to_have_text(TEXT,timeout=30000)
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_cw import fixture as cw_fixture, TEXT as CW_TEXT
                    x,fs = cw_fixture()
                    raw = Path(directory)/'cw.sigmf-data'
                    meta = Path(directory)/'cw.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.cw-text').first).to_have_text(CW_TEXT,timeout=30000)
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_fsk import fixture as fsk_fixture
                    x,fs,expected = fsk_fixture(fs=192000)
                    x *= np.exp(2j*np.pi*35000*np.arange(len(x))/fs)
                    raw = Path(directory)/'fsk.sigmf-data'
                    meta = Path(directory)/'fsk.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.fsk-bits').first).to_be_visible(timeout=30000)
                    assert page.locator('.fsk-bits').first.inner_text() in expected
                    expect(page.locator('.fsk-frequency').first).to_have_text(re.compile('0.0353[0-9]+ MHz'))
                    binary_link = page.get_by_role('link',name='Télécharger le binaire compacté')
                    from urllib.parse import urljoin
                    response = page.request.get(urljoin(page.url,binary_link.get_attribute('href')))
                    assert response.ok and len(response.body())>0
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_fsk4 import fixture as fsk4_fixture
                    x,fs,expected = fsk4_fixture(fs=192000)
                    x *= np.exp(-2j*np.pi*35000*np.arange(len(x))/fs)
                    raw = Path(directory)/'fsk4.sigmf-data'
                    meta = Path(directory)/'fsk4.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.fsk4-symbols').first).to_be_visible(timeout=30000)
                    assert page.locator('.fsk4-symbols').first.inner_text() in expected
                    symbol_link = page.get_by_role('link',name='Télécharger les symboles 4-FSK')
                    response = page.request.get(urljoin(page.url,symbol_link.get_attribute('href')))
                    assert response.ok and response.body().decode('ascii') in expected
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_ax25 import fixture as ax25_fixture, TEXT as AX25_TEXT
                    x,fs = ax25_fixture()
                    raw = Path(directory)/'ax25.sigmf-data'
                    meta = Path(directory)/'ax25.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.ax25-text').first).to_have_text(AX25_TEXT,timeout=30000)
                    expect(page.locator('.ax25-addresses').first).to_contain_text('N0CALL-1 → APRS')
                    assert int(page.locator('#metric-frames').inner_text())>=3
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_ofdm import fixture as ofdm_fixture
                    x,fs = ofdm_fixture()
                    raw = Path(directory)/'ofdm.sigmf-data'
                    meta = Path(directory)/'ofdm.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.ofdm-parameters').first).to_have_text('64 échantillons utiles · garde 16 · période 80',timeout=30000)
                    assert page.locator('#metric-frames').inner_text()=='0'
                    link = page.get_by_role('link',name='Télécharger les indices de préfixe cyclique')
                    response = page.request.get(urljoin(page.url,link.get_attribute('href')))
                    assert response.ok and response.json()['candidates']
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_lora import preamble
                    x,fs = preamble()
                    raw = Path(directory)/'lora.sigmf-data'
                    meta = Path(directory)/'lora.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.lora-candidate').first).to_contain_text('SF7',timeout=30000)
                    assert page.locator('#metric-frames').inner_text()=='0'
                    link = page.get_by_role('link',name='Télécharger les indices de préambule CSS')
                    response = page.request.get(urljoin(page.url,link.get_attribute('href')))
                    assert response.ok and response.json()['candidates']
                    assert 'frames' not in response.json()
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_cw import fixture as audio_fixture, TEXT as AUDIO_TEXT
                    from scipy.io import wavfile
                    x,fs = audio_fixture()
                    wave = Path(directory)/'audio.wav'
                    mp3 = Path(directory)/'audio.mp3'
                    wavfile.write(wave,fs,x.real.astype(np.float32))
                    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(wave),str(mp3)],check=True,timeout=20)
                    page.locator('#input-kind').select_option('audio')
                    page.locator('#seconds').fill('20')
                    page.locator('#iq-file').set_input_files(str(mp3))
                    expect(page.locator('#meta-file')).to_be_disabled()
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.cw-text').first).to_have_text(AUDIO_TEXT,timeout=30000)
                    expect(page.locator('#source-badge')).to_have_text('Audio · fréquences audio')
                    expect(page.locator('#center-label')).to_contain_text('aucune fréquence RF')
                    expect(page.locator('#audio-preview')).to_be_visible()
                    response = page.request.get(urljoin(page.url,page.locator('#audio-preview').get_attribute('src')))
                    assert response.ok and response.body()[:4]==b'RIFF'
                    assert page.locator('#metric-frames').inner_text()=='0'
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_rtty import fixture as rtty_audio_fixture, TEXT as RTTY_AUDIO_TEXT
                    x,fs = rtty_audio_fixture(inverted=True)
                    audio = np.real(x*np.exp(2j*np.pi*1000*np.arange(len(x))/fs)).astype(np.float32)
                    wave = Path(directory)/'rtty-audio.wav'
                    mp3 = Path(directory)/'rtty-audio.mp3'
                    wavfile.write(wave,fs,audio)
                    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(wave),str(mp3)],check=True,timeout=20)
                    page.locator('#iq-file').set_input_files(str(mp3))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.rtty-text').first).to_have_text(RTTY_AUDIO_TEXT,timeout=30000)
                    expect(page.locator('#center-label')).to_contain_text('aucune fréquence RF')
                    link = page.get_by_role('link',name='Télécharger le texte RTTY candidat')
                    response = page.request.get(urljoin(page.url,link.get_attribute('href')))
                    assert response.ok and response.body()==RTTY_AUDIO_TEXT.encode()
                    assert page.locator('#metric-frames').inner_text()=='0'
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    from test_afsk import fixture as afsk_fixture, TEXT as AFSK_TEXT
                    audio,fs = afsk_fixture()
                    wave = Path(directory)/'afsk.wav'
                    mp3 = Path(directory)/'afsk.mp3'
                    wavfile.write(wave,fs,audio.astype(np.float32))
                    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(wave),'-ar','24000','-b:a','64k',str(mp3)],check=True,timeout=20)
                    page.locator('#iq-file').set_input_files(str(mp3))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.ax25-text').first).to_have_text(AFSK_TEXT,timeout=30000)
                    expect(page.locator('.ax25-addresses').first).to_contain_text('N0CALL-1 → APRS')
                    assert int(page.locator('#metric-frames').inner_text())>=3
                    expect(page.locator('#center-label')).to_contain_text('aucune fréquence RF')
                    link = page.get_by_role('link',name='Télécharger les trames AX.25 validées')
                    response = page.request.get(urljoin(page.url,link.get_attribute('href')))
                    assert response.ok and len(response.json()['frames'])>=3
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
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
