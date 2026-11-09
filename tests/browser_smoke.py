"""Real-browser smoke test; run separately from unit tests on a loopback-capable host."""
from pathlib import Path
import subprocess
import os
import sys
import tempfile
import re
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright, expect


def main():
    port = 18765
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'browser_live_server:create_app',
                                '--factory', '--host', '127.0.0.1', '--port', str(port)],
                                env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parent)+os.pathsep+os.environ.get('PYTHONPATH','')})
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
            page = browser.new_page(viewport={'width':1280, 'height':1000},accept_downloads=True)
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
                # Published ADS-B messages on independent synthetic PPM IQ.
                from test_adsb_fields import reference_aircraft_iq
                import numpy as np
                with tempfile.TemporaryDirectory() as adsb_directory:
                    adsb_path = Path(adsb_directory)/'aircraft.cf32'
                    reference_aircraft_iq().astype('<c8').tofile(adsb_path)
                    previous_rate = page.locator('#file-rate').input_value()
                    page.locator('#iq-file').set_input_files(str(adsb_path))
                    page.locator('#file-rate').fill('2000000')
                    page.get_by_role('button', name='Analyser automatiquement').click()
                    expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'), timeout=30000)
                    expect(page.locator('#metric-frames')).to_have_text('3')
                    expect(page.locator('.adsb-callsign')).to_contain_text('KLM1023')
                    expect(page.locator('.adsb-position')).to_contain_text('52.25720')
                    expect(page.locator('.adsb-position')).to_contain_text('3.91937')
                    expect(page.locator('.adsb-position-pending')).to_have_count(1)
                    Path('browser-artifacts').mkdir(exist_ok=True)
                    page.screenshot(path='browser-artifacts/adsb-fields.png', full_page=True)
                    from test_adsb_velocity import reference_velocity_iq
                    from urllib.parse import urljoin
                    velocity_path = Path(adsb_directory)/'velocity.cf32'
                    reference_velocity_iq().astype('<c8').tofile(velocity_path)
                    page.locator('#iq-file').set_input_files(str(velocity_path))
                    page.get_by_role('button', name='Analyser automatiquement').click()
                    expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'), timeout=30000)
                    expect(page.locator('#metric-frames')).to_have_text('2')
                    expect(page.locator('.adsb-ground-speed')).to_contain_text('159.2 kt')
                    expect(page.locator('.adsb-ground-track')).to_contain_text('182.88')
                    expect(page.locator('.adsb-airspeed')).to_contain_text('TAS : 375.0 kt')
                    expect(page.locator('.adsb-heading')).to_contain_text('243.98')
                    expect(page.locator('.adsb-heading')).to_contain_text('non déterminée')
                    expect(page.locator('.adsb-vertical-rate').first).to_contain_text('-832 ft/min (GNSS)')
                    expect(page.locator('.adsb-vertical-rate').last).to_contain_text('-2304 ft/min (barométrique)')
                    expect(page.locator('.adsb-position')).to_have_count(0)
                    report_response = page.request.get(urljoin(page.url, page.locator('#download').get_attribute('href')))
                    assert report_response.ok
                    adsb_trial = next(t for t in report_response.json()['wideband_trials'] if t['decoder']=='adsb_1090es')
                    assert adsb_trial['frames'][0]['fields']['velocity']['vertical_rate_source']=='GNSS'
                    assert adsb_trial['frames'][1]['fields']['velocity']['airspeed_kind']=='TAS'
                    page.screenshot(path='browser-artifacts/adsb-velocity.png', full_page=True)
                    page.locator('#file-rate').fill(previous_rate)
                with tempfile.TemporaryDirectory() as directory:
                    from iqscope import demo
                    meta = demo(directory)
                    page.locator('#iq-file').set_input_files(str(meta.with_suffix('.sigmf-data')))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator("#status-text")).to_have_text(re.compile("^Analyse terminée"), timeout=30000)
                    assert page.locator('#metric-signals').inner_text() == '2'
                reference=Path('corpus-cache/rtl433-reference/gfile001.cu8')
                if os.environ.get('IQSCOPE_TEST_RTL433')=='1':
                    import numpy as np
                    import json
                    for capture,expected_model,temperature,humidity in [(reference,'Fineoffset-WH2',24.6,33),(reference.with_name('wh25.cu8'),'Fineoffset-WH25',23.2,57)]:
                        raw=np.fromfile(capture,dtype='u1').astype(np.float32)
                        x=((raw[::2]-127.5)+1j*(raw[1::2]-127.5))/127.5
                        with tempfile.TemporaryDirectory() as directory:
                            data=Path(directory)/'sensor.sigmf-data'
                            meta=data.with_suffix('.sigmf-meta')
                            x.astype('<c8').tofile(data)
                            meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':250000}}))
                            page.locator('#iq-file').set_input_files(str(data))
                            page.locator('#meta-file').set_input_files(str(meta))
                            page.get_by_role('button',name='Analyser automatiquement').click()
                            card=page.locator('.rtl433-message').first
                            expect(card).to_contain_text(expected_model,timeout=30000)
                            expect(card).to_contain_text(str(temperature))
                            expect(card).to_contain_text(str(humidity))
                            if expected_model=='Fineoffset-WH25':
                                expect(card).to_contain_text('1001.1')
                            expect(card).to_contain_text('Non revérifiée par IQScope')
                            with page.expect_download() as event:
                                page.get_by_role('link',name='Télécharger les valeurs des capteurs (JSON)').click()
                            downloaded=json.loads(Path(event.value.path()).read_text())
                            assert downloaded['messages'][0]['fields']['temperature_C']==temperature
                            assert downloaded['messages'][0]['fields']['humidity']==humidity
                            if expected_model=='Fineoffset-WH25':
                                assert downloaded['messages'][0]['fields']['pressure_hPa']==1001.1
                            assert downloaded['messages'][0]['independently_validated'] is False
                # PSK uses synthetic references: no claim of real-radio validation.
                from test_psk import fixture as psk_fixture, equivalent as psk_equivalent
                from test_psk_rrc import fixture as psk_rrc_fixture
                for order,shape in [(2,'rectangular_trial'),(4,'rectangular_trial'),(2,'rrc_trial'),(4,'rrc_trial')]:
                    import numpy as np
                    import json
                    if shape=='rrc_trial':
                        x,fs,expected,_=psk_rrc_fixture(order,clock_ppm=175)
                    else:
                        x,fs,expected=psk_fixture(order)
                    with tempfile.TemporaryDirectory() as directory:
                        data=Path(directory)/'psk.sigmf-data'
                        meta=data.with_suffix('.sigmf-meta')
                        x.astype('<c8').tofile(data)
                        meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                        page.locator('#iq-file').set_input_files(str(data))
                        page.locator('#meta-file').set_input_files(str(meta))
                        page.get_by_role('button',name='Analyser automatiquement').click()
                        card=page.locator('.psk-candidate').first
                        modulation='BPSK' if order==2 else 'QPSK'
                        expect(card).to_contain_text(f'{modulation} · symboles candidats, sans CRC',timeout=30000)
                        expect(card).to_contain_text('Protocole non identifié')
                        expect(card.locator('canvas')).to_be_visible()
                        expect(card.locator('.psk-pulse-shape')).to_contain_text('RRC' if shape=='rrc_trial' else 'rectangulaires')
                        expect(card.locator('.psk-bits')).to_have_text(re.compile('^[01]+$'))
                        with page.expect_download() as event:
                            page.get_by_role('link',name='Télécharger le rapport PSK',exact=True).click()
                        decoded=json.loads(Path(event.value.path()).read_text())['candidates'][0]
                        assert psk_equivalent(decoded['symbols'],expected,order)
                        assert decoded['evidence']['checksum']=='not_checked'
                        assert decoded['parameters']['pulse_shape']==shape
                        assert page.locator('#metric-frames').inner_text()=='0'
                from test_qam import fixture as qam_fixture, equivalent as qam_equivalent
                x,fs,expected,_=qam_fixture(clock_ppm=175)
                with tempfile.TemporaryDirectory() as directory:
                    data=Path(directory)/'qam.sigmf-data';meta=data.with_suffix('.sigmf-meta')
                    x.astype('<c8').tofile(data)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(data))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    card=page.locator('.qam16-candidate').first
                    expect(card).to_contain_text('16-QAM · symboles candidats, sans CRC',timeout=30000)
                    expect(card).to_contain_text('Protocole non identifié')
                    expect(card.locator('canvas')).to_be_visible()
                    expect(card.locator('.qam16-bits')).to_have_text(re.compile('^[01]+$'))
                    with page.expect_download() as event:
                        page.get_by_role('link',name='Télécharger le rapport 16-QAM',exact=True).click()
                    decoded=json.loads(Path(event.value.path()).read_text())['candidates'][0]
                    assert qam_equivalent(decoded['symbols'],expected)
                    assert decoded['evidence']['checksum']=='not_checked'
                    with page.expect_download() as event:
                        page.get_by_role('link',name='Télécharger 16-QAM · fiabilité des bits',exact=True).click()
                    soft=json.loads(Path(event.value.path()).read_text())
                    assert soft==decoded['soft_bits']
                    assert len(soft['llr'])==decoded['bit_count']
                    assert soft['status']=='likelihood_model_estimated'
                    assert page.locator('#metric-frames').inner_text()=='0'
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
                    from test_lora import synchronized_preamble
                    from test_lora_payload import RATE_VECTORS
                    x,fs = synchronized_preamble(offset=0,cfo_bins=0,data_symbols=RATE_VECTORS['8-4-1-bit-errors'])
                    import numpy as np
                    x = np.r_[np.zeros(int(1.1*fs),dtype=complex),x]
                    raw = Path(directory)/'lora.sigmf-data'
                    meta = Path(directory)/'lora.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.lora-candidate').first).to_contain_text('SF8',timeout=30000)
                    assert page.locator('#metric-frames').inner_text()=='1'
                    link = page.get_by_role('link',name='Télécharger le rapport LoRa')
                    response = page.request.get(urljoin(page.url,link.get_attribute('href')))
                    assert response.ok and response.json()['candidates']
                    assert len(response.json()['frames'])==1
                    assert response.json()['frames'][0]['time_seconds']>1
                    assert response.json()['temporal_search']['window_count']>1
                    expect(page.locator('.lora-search-coverage')).to_contain_text('Recherche LoRa partielle')
                    expect(page.locator('.lora-sync-evidence').first).to_contain_text('Paire de chirps opposés candidate')
                    expect(page.locator('.lora-sync-word').first).to_contain_text('0x34')
                    expect(page.locator('.lora-header').first).to_contain_text('5 octets annoncés')
                    expect(page.locator('.lora-header').first).to_contain_text('codage 4/8')
                    expect(page.locator('.lora-fec-corrections').first).to_contain_text('1 bit de codeword corrigé')
                    expect(page.locator('.lora-data-symbols').first).to_contain_text('24 symboles CSS bruts candidats')
                    assert any(c.get('sync_word',{}).get('value_hex')=='34' for c in response.json()['candidates'])
                    assert any(c.get('data_symbols',{}).get('symbol_bins')==RATE_VECTORS['8-4-1-bit-errors'] for c in response.json()['candidates'])
                    expect(page.locator('.lora-payload-text').first).to_have_text('HELLO')
                    binary=page.get_by_role('link',name='Télécharger la charge utile LoRa')
                    response=page.request.get(urljoin(page.url,binary.get_attribute('href')))
                    assert response.ok and response.body()==b'HELLO'
                expect(page.locator('#status-text')).to_have_text(re.compile('^Analyse terminée'),timeout=30000)
                with tempfile.TemporaryDirectory() as directory:
                    expect(page.locator('#experimental-lora')).not_to_be_checked()
                    page.locator('#experimental-lora').check()
                    from test_lora_matched import fixture as inferred_fixture
                    x,fs=inferred_fixture(missing=True)
                    raw=Path(directory)/'inferred.sigmf-data'
                    meta=Path(directory)/'inferred.sigmf-meta'
                    x.astype('<c8').tofile(raw)
                    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs}}))
                    page.locator('#iq-file').set_input_files(str(raw))
                    page.locator('#meta-file').set_input_files(str(meta))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.lora-experimental-mode')).to_contain_text('LoRa expérimental activé',timeout=30000)
                    expect(page.locator('.lora-inferred-boundary')).to_contain_text('quart de chirp non confirmé',timeout=30000)
                    expect(page.locator('.lora-payload-text')).to_have_text('HELLO')
                    link=page.get_by_role('link',name='Télécharger le rapport LoRa')
                    response=page.request.get(urljoin(page.url,link.get_attribute('href')))
                    assert response.ok and response.json()['frames'][0]['quarter_chirp_validated'] is False
                    assert response.json()['mode']=='experimental_guarded'
                    assert response.json()['frames'][0]['experimental_mode'] is True
                    payload=page.get_by_role('link',name='Télécharger la charge utile LoRa')
                    binary=page.request.get(urljoin(page.url,payload.get_attribute('href')))
                    assert binary.ok and binary.body()==b'HELLO'
                    page.locator('#experimental-lora').uncheck()
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
                if os.environ.get('IQSCOPE_TEST_PSK_RADIO')=='1':
                    import hashlib
                    page.locator('#input-kind').select_option('audio')
                    page.locator('#seconds').fill('20')
                    page.locator('#iq-file').set_input_files(str(Path('corpus-cache/psk-radio/pwsat2.wav').resolve()))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.psk-ax25-integrity')).to_have_count(4,timeout=30000)
                    expect(page.locator('.psk-gain-recovery')).to_have_count(1)
                    expect(page.locator('.ax25-addresses').first).to_contain_text('PWSAT2')
                    expect(page.locator('#metric-frames')).to_have_text('4')
                    expect(page.locator('#center-label')).to_contain_text('aucune fréquence RF')
                    with page.expect_download() as event:
                        page.get_by_role('link',name='Télécharger la charge utile AX.25 BPSK',exact=True).first.click()
                    payload=Path(event.value.path()).read_bytes()
                    assert len(payload)==180
                    assert hashlib.sha256(payload).hexdigest()=='4171091c943892f60041564c49e595dc1888a0c19fcc19914b904cf31d92b86c'
                if os.environ.get('IQSCOPE_TEST_PSK_RADIO')=='1':
                    page.locator('#iq-file').set_input_files(str(Path('corpus-cache/psk-radio/picsat.wav').resolve()))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.psk-context-recovery')).to_be_visible(timeout=30000)
                    expect(page.locator('.ax25-addresses').first).to_contain_text('PICSAT-2')
                    expect(page.locator('.psk-candidate')).to_have_count(1)
                    expect(page.locator('#metric-frames')).to_have_text('1')
                    with page.expect_download() as payload_event:
                        page.get_by_role('link',name='Télécharger la charge utile AX.25 BPSK',exact=True).click()
                    payload=Path(payload_event.value.path()).read_bytes()
                    assert len(payload)==114
                    assert hashlib.sha256(payload).hexdigest()=='2c95b8abea7c459f8ca46c6315375036017b3d93d5f4f47f3e76a1eae61674f7'
                    with page.expect_download() as event:
                        page.get_by_role('link',name='Télécharger le rapport AX.25 BPSK',exact=True).click()
                    diagnostic=json.loads(Path(event.value.path()).read_text())
                    assert len(diagnostic['frames'])==1 and diagnostic['frames'][0]['fcs_valid']
                    assert diagnostic['length_rejected']>0
                    assert diagnostic['crc_rejected']==0
                if os.environ.get('IQSCOPE_TEST_PSK_RADIO')=='1':
                    page.locator('#iq-file').set_input_files(str(Path('corpus-cache/psk-radio/ao73.wav').resolve()))
                    page.get_by_role('button',name='Analyser automatiquement').click()
                    expect(page.locator('.ao40-frame')).to_have_count(1,timeout=30000)
                    expect(page.locator('.ao40-frame')).to_contain_text('256 octets')
                    expect(page.locator('.ao40-validation')).to_contain_text('Aucun CRC')
                    expect(page.locator('.funcube-telemetry')).to_contain_text('Profil FUNcube-1 FM candidat')
                    expect(page.locator('.funcube-measurement').filter(has_text='Tension batterie')).to_have_text('Tension batterie : 8140 mV')
                    expect(page.locator('.funcube-measurement').filter(has_text='Courant système')).to_have_text('Courant système : 206 mA')
                    expect(page.locator('.funcube-sequence')).to_contain_text('2543')
                    with page.expect_download() as telemetry_event:
                        page.get_by_role('link',name='Télécharger la télémétrie FUNcube (JSON)',exact=True).click()
                    telemetry=json.loads(Path(telemetry_event.value.path()).read_text())
                    assert telemetry['sequence_number']==2543 and telemetry['source_validity']['eps']
                    assert telemetry['identity_confirmed'] is False
                    expect(page.locator('#metric-frames')).to_have_text('0')
                    with page.expect_download() as event:
                        page.get_by_role('link',name='Télécharger la charge utile AO-40',exact=True).click()
                    payload=Path(event.value.path()).read_bytes()
                    assert len(payload)==256
                    assert hashlib.sha256(payload).hexdigest()=='220bb05857d4220084ca46bcb7e48759226935627a25767144d588dc4a43b112'
                live_requests=[]
                page.on('request',lambda request: live_requests.append(request.post_data_json) if request.url.endswith('/api/live/analyze') and request.method=='POST' else None)
                page.get_by_role('tab',name='SDR en direct').click()
                assert page.locator('#live-panel').is_visible()
                assert page.locator('#live-frequency').input_value() == '100'
                page.locator('#auto-live').uncheck()
                expect(page.locator('#live-experimental-lora')).not_to_be_checked()
                page.locator('#live-experimental-lora').check()
                with page.expect_request(lambda request: request.url.endswith('/api/live/analyze') and request.method=='POST' and request.post_data_json.get('experimental_lora') is True,timeout=30000) as live_request:
                    page.locator('#auto-live').check()
                assert live_request.value.post_data_json['experimental_lora'] is True
                expect(page.locator('.lora-experimental-mode')).to_contain_text('LoRa expérimental activé',timeout=30000)
                expect(page.locator('.lora-payload-text')).to_have_text('HELLO',timeout=30000)
                expect(page.locator('#live-coverage')).to_contain_text('Fenêtre analysée',timeout=30000)
                request_count=len(live_requests)
                page.wait_for_timeout(4500)
                assert len(live_requests)==request_count,'Unchanged SDR window was automatically analyzed again'
                with page.expect_request(lambda request: request.url.endswith('/api/live/analyze') and request.method=='POST' and request.post_data_json.get('experimental_lora') is False,timeout=30000):
                    page.locator('#live-experimental-lora').uncheck()
                expect(page.locator('.lora-experimental-mode')).to_have_count(0,timeout=30000)
                expect(page.locator('#live-coverage')).to_contain_text('Recouvrement',timeout=30000)
                page.locator('#auto-live').uncheck()
                binary=page.get_by_role('link',name='Télécharger la charge utile LoRa')
                response=page.request.get(urljoin(page.url,binary.get_attribute('href')))
                assert response.ok and response.body()==b'HELLO'

                expect(page.locator('#live-packet-list .live-packet')).to_have_count(1,timeout=30000)
                expect(page.locator('.live-packet-observations')).to_contain_text('standard')
                expect(page.locator('.live-packet-observations')).to_contain_text('expérimental')
                history=page.request.get(urljoin(page.url,'/api/live/frames')).json()
                assert len(history['events'])==1 and history['events'][0]['observation_count']>=2
                assert history['events'][0]['payload_hex']==b'HELLO'.hex()
                with page.expect_download() as packet_download:
                    page.get_by_role('link',name='Télécharger ce paquet LoRa').click()
                with tempfile.TemporaryDirectory() as download_directory:
                    target=Path(download_directory)/'history-payload.bin'
                    packet_download.value.save_as(str(target))
                    assert target.read_bytes()==b'HELLO'

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
