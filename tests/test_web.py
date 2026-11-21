import tempfile
import io
import shutil
from unittest.mock import patch, Mock
import asyncio
import unittest
from pathlib import Path

import numpy as np
import httpx

from iqscope_web.server import create_app

HEADERS = {'X-IQScope':'local'}


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.context = self.app.router.lifespan_context(self.app)
        await self.context.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver')
        # Keep an in-process ASGI test loop advancing even on runtimes that
        # restrict cross-thread socket wakeups. No network sockets are opened.
        async def tick():
            while True:
                await asyncio.sleep(.01)
        self.ticker = asyncio.create_task(tick())

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.context.__aexit__(None, None, None)
        self.ticker.cancel()
        try:
            await self.ticker
        except asyncio.CancelledError:
            pass
        self.temp.cleanup()

    async def wait_job(self, identifier, attempts=150):
        for _ in range(attempts):
            result = (await self.client.get(f'/api/jobs/{identifier}')).json()
            if result['status'] in ('completed','failed'):
                return result
            await asyncio.sleep(.03)
        self.fail('Analysis did not finish')

    async def test_ui_and_decoder_inventory(self):
        page = (await self.client.get('/'))
        self.assertEqual(page.status_code,200)
        self.assertIn('SDR en direct',page.text)
        self.assertIn("default-src 'self'",page.headers['content-security-policy'])
        data = (await self.client.get('/api/capabilities')).json()
        self.assertEqual(len(data['decoders']),20)
        self.assertEqual(next(d for d in data['decoders'] if d['id']=='afsk1200_fm_ax25')['family'], 'NBFM / AFSK1200 / AX.25')
        self.assertEqual(next(d for d in data['decoders'] if d['id']=='pocsag')['family'], 'POCSAG paging')

    async def test_kiss_download_preserves_received_frame_bytes(self):
        from iqscope_afsk_fm import write_afsk_fm_artifact
        from iqscope_ax25 import parse_ui
        from test_ax25 import frame
        from test_kiss import read_kiss
        packet=frame(payload=bytes.fromhex('c0dbdcdd'))
        trial={'frames':[{'hex':packet.hex(),'fields':parse_ui(packet[:-2])}]}
        directory=Path(self.temp.name)/'kiss-job'
        directory.mkdir()
        self.app.state.service.jobs['kiss-job']={'status':'completed'}
        write_afsk_fm_artifact(trial,directory)
        response=await self.client.get('/api/jobs/kiss-job/artifacts/'+trial['kiss_artifact'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(read_kiss(response.content),[(0,0,packet[:-2])])
        self.assertIn('attachment;',response.headers['content-disposition'])
        self.assertEqual((await self.client.get('/api/jobs/kiss-job/artifacts/missing.kiss')).status_code,404)

    async def test_automatic_ais_iq_import_and_byte_exports(self):
        from test_ais import fixture,PACKET
        x,fs=fixture()
        identifier=(await self.client.post('/api/uploads',content=x.astype('<c8').tobytes(),headers=HEADERS)).json()['upload_id']
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':fs},headers=HEADERS)
        job=await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        trial=next(t for t in job['result']['wideband_trials'] if t['decoder']=='ais_gmsk')
        self.assertEqual(trial['frames'][0]['fields']['mmsi'],477553000)
        base=f"/api/jobs/{job['id']}/artifacts/"
        self.assertEqual((await self.client.get(base+trial['artifact'])).json(),trial)
        self.assertEqual((await self.client.get(base+trial['frames'][0]['wire_artifact'])).content,PACKET)

    async def test_automatic_apt_iq_import_png_and_numeric_pixels(self):
        from test_apt import fixture,png_pixels
        x,fs,_=fixture(lines=7)
        identifier=(await self.client.post('/api/uploads',content=x.astype('<c8').tobytes(),headers=HEADERS)).json()['upload_id']
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':fs},headers=HEADERS)
        job=await self.wait_job(response.json()['id'],attempts=500)
        self.assertEqual(job['status'],'completed',job.get('error'))
        trial=next(t for t in job['result']['wideband_trials'] if t['decoder']=='noaa_apt')
        image=trial['images'][0];base=f"/api/jobs/{job['id']}/artifacts/"
        self.assertEqual((await self.client.get(base+trial['artifact'])).json(),trial)
        png=await self.client.get(base+image['artifacts']['full'])
        self.assertEqual(png.headers['content-type'],'image/png')
        pixels=png_pixels(png.content)
        self.assertEqual(pixels.shape,(image['height'],2080))
        self.assertEqual((await self.client.get(base+image['artifacts']['pixels'])).content,pixels.tobytes())
        np.testing.assert_array_equal(np.loadtxt(io.StringIO((await self.client.get(base+image['artifacts']['csv'])).text),delimiter=','),pixels)
        self.assertEqual(trial['source_window_reference']['start_sample'],0)
        self.assertEqual((await self.client.get(base+'../outside.png')).status_code,404)

    async def test_automatic_rds_iq_import_station_text_and_group_octets(self):
        from test_rds import fixture,packet
        x,fs,groups=fixture()
        identifier=(await self.client.post('/api/uploads',content=x.astype('<c8').tobytes(),headers=HEADERS)).json()['upload_id']
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':fs},headers=HEADERS)
        job=await self.wait_job(response.json()['id'],attempts=500)
        self.assertEqual(job['status'],'completed',job.get('error'))
        trial=next(t for t in job['result']['wideband_trials'] if t['decoder']=='rds_fm')
        self.assertEqual(trial['stations'][0]['ps']['text'],'YLE X3M ')
        self.assertEqual(trial['stations'][0]['radiotext']['text'],'HELLO RDS')
        base=f"/api/jobs/{job['id']}/artifacts/"
        self.assertEqual((await self.client.get(base+trial['artifact'])).json(),trial)
        self.assertEqual(trial['source_window_reference']['start_sample'],0)
        for frame in trial['frames']:
            data=(await self.client.get(base+frame['wire_artifact'])).content
            self.assertEqual(data,bytes.fromhex(frame['hex']));self.assertIn(data,[packet(g) for g in groups])

    async def test_recording_list_and_bounded_import_artifacts(self):
        from test_formats import make_wave
        from iqscope import read_iq
        listing = (await self.client.get('/api/recordings/vksdr')).json()
        self.assertEqual(len(listing['entries']),5)
        self.assertEqual(listing['download_limit_bytes'],2*1024*1024)
        self.assertIsNone(listing['entries'][0]['reference_center_frequency_hz'])
        self.assertEqual((await self.client.post('/api/recordings/vksdr/unknown/analyze',headers=HEADERS)).status_code,404)
        payload = np.random.default_rng(101).integers(-1000,1000,50000,dtype=np.int16).astype('<i2').tobytes()
        response = io.BytesIO(make_wave(payload,fs=24000))
        response.status = 200
        response.headers = {'Content-Type':'audio/wav'}
        opener = Mock()
        opener.open.return_value = response
        with patch('iqscope_recordings.urllib.request.build_opener',return_value=opener):
            submitted = await self.client.post('/api/recordings/vksdr/noaa15_pds/analyze',json={'url':'http://127.0.0.1/private'},headers=HEADERS)
            self.assertEqual(submitted.status_code,202)
            job = await self.wait_job(submitted.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://bucket.vksdr.com/iq/'))
        self.assertEqual(request.get_header('Range'),'bytes=0-2097151')
        report = job['result']
        self.assertEqual(report['source_kind'],'remote_iq_excerpt')
        self.assertIsNone(report['recording_provenance']['header_center_frequency_hz'])
        self.assertEqual(report['center_frequency_hz'],0)
        self.assertEqual(report['sample_rate'],24000)
        for name in report['recording_artifacts'].values():
            artifact = await self.client.get(f"/api/jobs/{job['id']}/artifacts/{name}")
            self.assertEqual(artifact.status_code,200,name)
        self.assertEqual((await self.client.get(f"/api/jobs/{job['id']}/artifacts/source-prefix.wav")).status_code,404)
        x,fs,center = read_iq(Path(self.temp.name)/job['id']/'excerpt.sigmf-data')
        self.assertEqual(len(x),24000)
        self.assertEqual(center,0)

    async def test_recording_download_error_is_reported_as_failed_job(self):
        opener = Mock()
        opener.open.side_effect = TimeoutError('source timeout')
        with patch('iqscope_recordings.urllib.request.build_opener',return_value=opener):
            response = await self.client.post('/api/recordings/vksdr/uhf_fo/analyze',headers=HEADERS)
            job = await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'failed')
        self.assertIn('source timeout',job['error'])

    async def test_upload_deletion_releases_quota_and_protects_active_jobs(self):
        identifier = (await self.client.post('/api/uploads',content=b'x'*2048,headers=HEADERS)).json()['upload_id']
        path = self.app.state.service.uploads[identifier]
        self.app.state.service.jobs['busy'] = {'status':'running'}
        blocked = await self.client.delete(f'/api/uploads/{identifier}',headers=HEADERS)
        self.assertEqual(blocked.status_code,409)
        self.assertTrue(path.exists())
        del self.app.state.service.jobs['busy']
        removed = await self.client.delete(f'/api/uploads/{identifier}',headers=HEADERS)
        self.assertEqual(removed.status_code,200)
        self.assertFalse(path.exists())
        self.assertNotIn(identifier,self.app.state.service.upload_sizes)
        self.assertEqual((await self.client.delete(f'/api/uploads/{identifier}',headers=HEADERS)).status_code,404)

    async def test_demo_job_and_audio_artifact(self):
        response=(await self.client.post('/api/analyses',json={'demo':True},headers=HEADERS))
        self.assertEqual(response.status_code,202)
        job=(await self.wait_job(response.json()['id']))
        self.assertEqual(job['status'],'completed',job.get('error'))
        self.assertEqual(len(job['result']['signals']),2)
        artifact=(await self.client.get(f"/api/jobs/{job['id']}/artifacts/signal-002-fm-candidate.wav"))
        self.assertEqual(artifact.status_code,200)
        self.assertEqual(artifact.content[:4],b'RIFF')
        self.assertGreater(len(job['result']['waterfall']['power_db']),1)

    async def test_iq_file_windows_seek_and_navigate_by_exact_sample_index(self):
        from test_formats import make_wave
        data=np.arange(20000,dtype='<i2').tobytes()
        identifier=(await self.client.post('/api/uploads',content=make_wave(data),headers={**HEADERS,'X-IQScope-Filename':'window.wav'})).json()['upload_id']
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'seconds':.1,'start_seconds':.2},headers=HEADERS)
        job=await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        report=job['result'];window=report['source_window']
        self.assertEqual((window['start_sample'],window['end_sample'],window['total_samples']),(4800,7200,10000))
        saved=(await self.client.get(f"/api/jobs/{job['id']}/artifacts/report.json")).json()
        self.assertEqual(saved,report)
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'seconds':.1,'start_sample':window['next_start_sample']},headers=HEADERS)
        second=await self.wait_job(response.json()['id'])
        self.assertEqual(second['status'],'completed',second.get('error'))
        self.assertEqual((second['result']['source_sample_start'],second['result']['source_sample_end']),(7200,9600))
        self.assertIsNone(second['result']['source_window']['next_start_sample'])
        self.assertEqual(second['result']['source_window']['remaining_samples'],400)
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'start_sample':9999},headers=HEADERS)
        last=await self.wait_job(response.json()['id'])
        self.assertEqual(last['status'],'failed')
        self.assertIn('remaining',last['error'])

    async def test_automatic_scan_exposes_nested_reports_and_rejects_escaping_artifacts(self):
        data=np.zeros(12000,dtype='<c8').tobytes()
        identifier=(await self.client.post('/api/uploads',content=data,headers=HEADERS)).json()['upload_id']
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':24000,'seconds':.1,'scan':True,'max_windows':2},headers=HEADERS)
        job=await self.wait_job(response.json()['id'],attempts=1000)
        self.assertEqual(job['status'],'completed',job.get('error'))
        result=job['result'];self.assertEqual(result['status'],'window_budget_exhausted')
        self.assertEqual(len(result['windows']),2)
        artifact=await self.client.get(f"/api/jobs/{job['id']}/artifacts/scan/window-002/report.json")
        self.assertEqual(artifact.status_code,200)
        self.assertEqual(artifact.json()['source_sample_start'],1200)
        encoded=await self.client.get(f"/api/jobs/{job['id']}/artifacts/scan%2Fwindow-002%2Freport.json")
        self.assertEqual(encoded.status_code,200)
        self.assertEqual(encoded.json(),artifact.json())
        summary=await self.client.get(f"/api/jobs/{job['id']}/artifacts/scan/scan-report.json")
        self.assertEqual(summary.json(),result)
        outside=Path(self.temp.name)/'outside.json';outside.write_text('{}')
        (Path(self.temp.name)/job['id']/'scan'/'escape.json').symlink_to(outside)
        for name in ['scan/escape.json','scan/%2e%2e/%2e%2e/outside.json','scan%5c..%5coutside.json']:
            self.assertEqual((await self.client.get(f"/api/jobs/{job['id']}/artifacts/{name}")).status_code,404)

    async def test_scan_cancellation_endpoint_stops_between_windows(self):
        import threading
        from iqscope_scan import scan_file as actual_scan
        from test_scan import lightweight_analyzer
        entered=threading.Event();release=threading.Event()
        def slow_analyzer(*args,**kwargs):
            entered.set();release.wait(timeout=10)
            return lightweight_analyzer(*args,**kwargs)
        def controlled(*args,**kwargs):return actual_scan(*args,**kwargs,analyzer=slow_analyzer)
        identifier=(await self.client.post('/api/uploads',content=np.zeros(12000,dtype='<c8').tobytes(),headers=HEADERS)).json()['upload_id']
        with patch('iqscope_web.server.scan_file',side_effect=controlled):
            response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':24000,'seconds':.1,'scan':True},headers=HEADERS)
            job_id=response.json()['id']
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                cancelled=await self.client.post(f'/api/jobs/{job_id}/cancel',headers=HEADERS)
                self.assertTrue(cancelled.json()['cancel_requested'])
            finally:release.set()
            job=await self.wait_job(job_id)
        self.assertEqual(job['result']['status'],'cancelled')
        self.assertEqual(len(job['result']['windows']),1)

    async def test_scan_catalogue_preserves_grouped_bytes_and_window_provenance(self):
        from iqscope_scan import scan_file as actual_scan
        from test_scan import lightweight_analyzer
        from test_scan_events import ax25
        from test_ax25 import frame
        def analyzer(*args,**kwargs):
            report=lightweight_analyzer(*args,**kwargs)
            observed=ax25((3000-kwargs['start_sample'])/24000)
            observed['time_end_seconds']=observed['time_seconds']+.02
            report['wideband_trials'][0]['frames']=[observed]
            return report
        def controlled(*args,**kwargs):return actual_scan(*args,**kwargs,analyzer=analyzer)
        identifier=(await self.client.post('/api/uploads',content=np.zeros(12000,dtype='<c8').tobytes(),headers=HEADERS)).json()['upload_id']
        with patch('iqscope_web.server.scan_file',side_effect=controlled):
            response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':24000,'seconds':.2,'scan':True,'max_windows':2},headers=HEADERS)
            job=await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        catalogue=job['result']['event_catalogue']
        self.assertEqual((catalogue['event_count'],catalogue['accepted_observations']),(1,2))
        prefix=f"/api/jobs/{job['id']}/artifacts/scan/"
        saved=await self.client.get(prefix+catalogue['report_artifact'])
        self.assertEqual(saved.json(),catalogue)
        event=catalogue['events'][0]
        binary=await self.client.get(prefix+event['binary_artifact'])
        self.assertEqual(binary.content,frame())
        self.assertEqual([o['window_index'] for o in event['observations']],[1,2])

    async def test_unsupported_seek_modes_and_noninteger_sample_offsets_are_rejected(self):
        response=await self.client.post('/api/analyses',json={'demo':True,'start_seconds':1},headers=HEADERS)
        self.assertEqual(response.status_code,400)
        identifier=(await self.client.post('/api/uploads',content=b'x'*2048,headers={**HEADERS,'X-IQScope-Filename':'audio.wav'})).json()['upload_id']
        response=await self.client.post('/api/analyses',json={'upload_id':identifier,'input_kind':'audio','start_seconds':1},headers=HEADERS)
        self.assertEqual(response.status_code,400)
        for value in (True,1.5,-1):
            response=await self.client.post('/api/analyses',json={'upload_id':identifier,'start_sample':value},headers=HEADERS)
            self.assertEqual(response.status_code,422)

    async def test_upload_raw_iq(self):
        rng=np.random.default_rng(13)
        x=(rng.normal(size=4096)+1j*rng.normal(size=4096)).astype('<c8')
        response=(await self.client.post('/api/uploads',content=x.tobytes(),headers=HEADERS))
        self.assertEqual(response.status_code,200)
        identifier=response.json()['upload_id']
        bad=(await self.client.post('/api/analyses',json={'upload_id':identifier},headers=HEADERS))
        self.assertEqual(bad.status_code,400)
        good=(await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':128000},headers=HEADERS))
        self.assertEqual((await self.wait_job(good.json()['id']))['status'],'completed')

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    async def test_explicit_audio_upload_cw_and_preview(self):
        from test_cw import fixture,TEXT
        from scipy.io import wavfile
        x,fs = fixture()
        stream = io.BytesIO()
        wavfile.write(stream,fs,x.real.astype(np.float32))
        headers = {**HEADERS,'X-IQScope-Filename':'cw.wav'}
        identifier = (await self.client.post('/api/uploads',content=stream.getvalue(),headers=headers)).json()['upload_id']
        iq = await self.client.post('/api/analyses',json={'upload_id':identifier},headers=HEADERS)
        self.assertEqual((await self.wait_job(iq.json()['id']))['status'],'failed')
        response = await self.client.post('/api/analyses',json={'upload_id':identifier,'input_kind':'audio','seconds':20},headers=HEADERS)
        self.assertEqual(response.status_code,202)
        job = await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        self.assertEqual(job['result']['source_kind'],'receiver_audio')
        self.assertIsNone(job['result']['center_frequency_hz'])
        self.assertEqual(job['result']['wideband_trials'][0]['candidates'][0]['text'],TEXT)
        preview = await self.client.get(f"/api/jobs/{job['id']}/artifacts/audio-preview.wav")
        self.assertEqual(preview.status_code,200)
        self.assertEqual(preview.content[:4],b'RIFF')

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    async def test_audio_rtty_text_download_preserves_ita2(self):
        from test_rtty import fixture,TEXT
        from scipy.io import wavfile
        x,fs = fixture(inverted=True)
        audio = np.real(x*np.exp(2j*np.pi*1000*np.arange(len(x))/fs)).astype(np.float32)
        stream = io.BytesIO()
        wavfile.write(stream,fs,audio)
        identifier = (await self.client.post('/api/uploads',content=stream.getvalue(),headers={**HEADERS,'X-IQScope-Filename':'rtty.wav'})).json()['upload_id']
        response = await self.client.post('/api/analyses',json={'upload_id':identifier,'input_kind':'audio'},headers=HEADERS)
        job = await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        trial = next(t for t in job['result']['wideband_trials'] if t['decoder']=='rtty_ita2')
        self.assertEqual(trial['candidates'][0]['text'],TEXT)
        self.assertIn('audio_frequency_hz',trial['candidates'][0]['channel'])
        artifact = await self.client.get(f"/api/jobs/{job['id']}/artifacts/rtty-candidate.txt")
        self.assertEqual(artifact.status_code,200)
        self.assertEqual(artifact.content,TEXT.encode())

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    async def test_audio_afsk_ax25_crc_frame_export(self):
        from test_afsk import fixture,TEXT
        from scipy.io import wavfile
        audio,fs = fixture()
        stream = io.BytesIO()
        wavfile.write(stream,fs,audio.astype(np.float32))
        identifier = (await self.client.post('/api/uploads',content=stream.getvalue(),headers={**HEADERS,'X-IQScope-Filename':'afsk.wav'})).json()['upload_id']
        response = await self.client.post('/api/analyses',json={'upload_id':identifier,'input_kind':'audio'},headers=HEADERS)
        job = await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        trial = next(t for t in job['result']['wideband_trials'] if t['decoder']=='afsk1200_ax25')
        self.assertEqual(len(trial['frames']),4)
        self.assertEqual(trial['frames'][0]['fields']['text'],TEXT)
        artifact = await self.client.get(f"/api/jobs/{job['id']}/artifacts/ax25-frames.json")
        self.assertEqual(artifact.status_code,200)
        self.assertEqual(artifact.json()['frames'],trial['frames'])

    async def test_audio_mode_validation_and_missing_dependency(self):
        headers = {**HEADERS,'X-IQScope-Filename':'audio.mp3'}
        identifier = (await self.client.post('/api/uploads',content=b'x'*2048,headers=headers)).json()['upload_id']
        for body in ({'upload_id':identifier},
                     {'upload_id':identifier,'input_kind':'audio','seconds':21},
                     {'upload_id':identifier,'input_kind':'audio','metadata':{}}):
            response = await self.client.post('/api/analyses',json=body,headers=HEADERS)
            self.assertEqual(response.status_code,400,response.text)
        with patch('iqscope_web.server.shutil.which',return_value=None):
            response = await self.client.post('/api/analyses',json={'upload_id':identifier,'input_kind':'audio'},headers=HEADERS)
            self.assertEqual(response.status_code,400)
            self.assertIn('ffmpeg',response.text)

    async def test_sigmf_upload_and_invalid_metadata(self):
        x=np.tile(np.array([16384,-8192],dtype='<i2'),4096)
        identifier=(await self.client.post('/api/uploads',content=x.tobytes(),headers=HEADERS)).json()['upload_id']
        meta={'global':{'core:datatype':'ci16_le','core:sample_rate':128000}}
        response=(await self.client.post('/api/analyses',json={'upload_id':identifier,'metadata':meta},headers=HEADERS))
        self.assertEqual((await self.wait_job(response.json()['id']))['status'],'completed')
        meta['global']['core:sample_rate']=-1
        self.assertEqual((await self.client.post('/api/analyses',json={'upload_id':identifier,'metadata':meta},headers=HEADERS)).status_code,400)

    async def test_cross_origin_and_unknown_artifact_rejected(self):
        self.assertEqual((await self.client.post('/api/analyses',json={'demo':True})).status_code,403)
        response=(await self.client.post('/api/analyses',json={'demo':True},headers={**HEADERS,'Origin':'https://example.org'}))
        self.assertEqual(response.status_code,403)
        self.assertEqual((await self.client.get('/api/jobs/unknown/artifacts/report.json')).status_code,404)
        self.assertEqual((await self.client.get('/',headers={'Host':'example.org'})).status_code,403)

    async def test_live_requires_source_and_supported_rate(self):
        self.assertFalse((await self.client.get('/api/live/status')).json()['running'])
        self.assertEqual((await self.client.post('/api/live/analyze',headers=HEADERS)).status_code,409)
        self.assertEqual((await self.client.post('/api/live/start',json={'sample_rate':123},headers=HEADERS)).status_code,400)

    async def test_failed_job_is_reported_without_crashing_server(self):
        raw=np.zeros(2048,dtype='<c8').tobytes()
        identifier=(await self.client.post('/api/uploads',content=raw,headers=HEADERS)).json()['upload_id']
        response=(await self.client.post('/api/analyses',json={'upload_id':identifier,'metadata':{'global':{'core:sample_rate':128000,'core:datatype':'unsupported'}}},headers=HEADERS))
        result=(await self.wait_job(response.json()['id']))
        self.assertEqual(result['status'],'failed')
        self.assertIn('Unsupported',result['error'])

    async def test_live_snapshot_analysis_reports_source_interval(self):
        receiver = self.app.state.service.receiver
        fs = receiver.fs
        t = np.arange(8192)/fs
        receiver.blocks.append(np.exp(2j*np.pi*100000*t).astype(np.complex64))
        receiver.total = 20000
        receiver.buffered = 8192
        receiver.connected = True
        response = await self.client.post('/api/live/analyze', headers=HEADERS)
        self.assertEqual(response.status_code, 202)
        result = await self.wait_job(response.json()['id'])
        self.assertEqual(result['status'], 'completed', result.get('error'))
        self.assertEqual(result['result']['source_sample_start'], 20000-8192)
        self.assertEqual(result['result']['source_sample_end'],20000)
        self.assertEqual(result['result']['source_session_id'],receiver.session_id)
        self.assertEqual(result['result']['source_sample_reference'],'received_samples_in_session')
        self.assertEqual(result['result']['source_window_limits'],{'samples':4096000,'seconds':4})
        state=(await self.client.get('/api/live/status')).json()
        self.assertEqual(state['window_sample_limit'],4096000)
        self.assertEqual(state['window_seconds_limit'],4)
        self.assertEqual(state['buffered_seconds'],8192/fs)
        self.assertIn('snapshot', result['result']['continuity_note'])

    async def test_browser_fixture_injection_precedes_static_mount_and_is_not_a_production_route(self):
        from browser_live_server import create_app as create_fixture_app
        fixture=create_fixture_app()
        async with fixture.router.lifespan_context(fixture):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture),base_url='http://testserver') as client:
                response=await client.post('/test/long-frame',headers=HEADERS)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['buffered_seconds'],4)
                self.assertEqual(response.json()['window_sample_limit'],1024000)
        self.assertFalse(any(getattr(route,'path',None)=='/test/long-frame' for route in self.app.routes))

    async def test_live_long_fm_frame_and_kiss_use_the_retained_source_window(self):
        from test_live_afsk import long_frame_receiver, PAYLOAD
        from test_kiss import read_kiss
        receiver=long_frame_receiver();receiver.connected=True;receiver.error=None
        self.app.state.service.receiver=receiver
        self.app.state.service.live_history.reset(receiver.session_id)
        self.app.state.service.live_ax25_history.reset(receiver.session_id)
        submitted=await self.client.post('/api/live/analyze',headers=HEADERS)
        self.assertEqual(submitted.status_code,202)
        job=await self.wait_job(submitted.json()['id'],attempts=1000)
        self.assertEqual(job['status'],'completed',job.get('error'))
        report=job['result']
        self.assertGreater(report['source_sample_start'],0)
        self.assertEqual(report['source_sample_end']-report['source_sample_start'],1024000)
        self.assertEqual(report['source_window_limits'],{'samples':1024000,'seconds':4})
        trial=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_fm_ax25')
        self.assertEqual(len(trial['frames']),1)
        frame=trial['frames'][0]
        self.assertTrue(frame['fcs_valid'])
        self.assertEqual(bytes.fromhex(frame['fields']['payload_hex']),PAYLOAD)
        response=await self.client.get(f"/api/jobs/{job['id']}/artifacts/{trial['kiss_artifact']}")
        self.assertEqual(response.status_code,200)
        self.assertEqual(read_kiss(response.content),[(0,0,bytes.fromhex(frame['hex'])[:-2])])
        schedule=(await self.client.get('/api/live/status')).json()['analysis_schedule']
        self.assertFalse(schedule['due'])
        self.assertEqual(schedule['step_samples'],512000)
        changed=(await self.client.get('/api/live/status?experimental_lora=true')).json()['analysis_schedule']
        self.assertTrue(changed['due'])
        self.assertEqual(changed['reason'],'mode_changed')
        history=(await self.client.get('/api/live/ax25/frames')).json()
        self.assertEqual(len(history['events']),1)
        event=history['events'][0]
        self.assertEqual(event['hex'],frame['hex'])
        self.assertEqual(event['id'],frame['live_event_id'])
        self.assertEqual(report['live_ax25_history_summary']['new_event_estimates'],1)
        saved=(await self.client.get(f"/api/jobs/{job['id']}/artifacts/{trial['artifact']}")).json()
        self.assertEqual(saved['frames'][0]['live_event_id'],event['id'])
        # The bounded event history owns its bytes; it outlives evicted jobs.
        self.app.state.service.jobs.pop(job['id'])
        shutil.rmtree(Path(self.temp.name)/job['id'])
        retained=await self.client.get('/api/live/ax25/frames.kiss')
        self.assertEqual(retained.status_code,200)
        self.assertEqual(read_kiss(retained.content),[(0,0,bytes.fromhex(frame['hex'])[:-2])])

    async def test_saved_ax25_history_reopens_in_another_application_without_live_mutation(self):
        from test_live_ax25_history import received
        from test_kiss import read_kiss
        from test_ax25 import frame
        import base64
        with tempfile.TemporaryDirectory() as old_root:
            old_app=create_app(old_root)
            async with old_app.router.lifespan_context(old_app):
                old_service=old_app.state.service
                old_service.live_ax25_history.observe(old_service.receiver.session_id,[received()],48000,145000000,0,96000)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=old_app),base_url='http://testserver') as old_client:
                    archive=(await old_client.get('/api/live/ax25/frames')).content
        response=await self.client.post('/api/archives/ax25/open',content=archive,headers=HEADERS)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['history']['events'][0]['hex'],frame().hex())
        self.assertEqual(read_kiss(base64.b64decode(response.json()['kiss_base64'])),[(0,0,frame()[:-2])])
        self.assertEqual((await self.client.get('/api/live/ax25/frames')).json()['events'],[])
        self.assertEqual(self.app.state.service.jobs,{})
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    async def test_invalid_and_oversized_archive_uploads_are_rejected(self):
        response=await self.client.post('/api/archives/ax25/open',content=b'bad JSON',headers=HEADERS)
        self.assertEqual(response.status_code,400)
        response=await self.client.post('/api/archives/ax25/open',content=b'x'*(1024*1024+1),headers=HEADERS)
        self.assertEqual(response.status_code,413)
        self.assertEqual((await self.client.get('/api/live/ax25/frames')).json()['events'],[])

    async def test_live_ax25_history_empty_exports_and_receiver_restart(self):
        from test_live_ax25_history import received
        initial=(await self.client.get('/api/live/ax25/frames')).json()
        self.assertEqual(initial['events'],[])
        self.assertEqual((await self.client.get('/api/live/ax25/frames.kiss')).content,b'')
        service=self.app.state.service
        service.live_ax25_history.observe(service.receiver.session_id,[received()],10000,145000000,0,20000)
        self.assertEqual(len((await self.client.get('/api/live/ax25/frames')).json()['events']),1)
        with patch('iqscope_web.live.threading.Thread') as thread:
            thread.return_value.is_alive.return_value=False
            response=await self.client.post('/api/live/start',json={'sample_rate':256000},headers=HEADERS)
        self.assertEqual(response.status_code,200)
        restarted=(await self.client.get('/api/live/ax25/frames')).json()
        self.assertNotEqual(restarted['session_id'],initial['session_id'])
        self.assertEqual(restarted['events'],[])
        self.assertEqual((await self.client.get('/api/live/ax25/frames.kiss')).content,b'')

    async def test_failed_live_job_does_not_advance_the_sample_cursor(self):
        receiver=self.app.state.service.receiver
        receiver.fs=256000;receiver.connected=True
        receiver._append_samples(np.zeros(64000,dtype=np.complex64))
        self.assertTrue((await self.client.get('/api/live/status')).json()['analysis_schedule']['due'])
        with patch('iqscope_web.server.analyze_samples',side_effect=RuntimeError('test decoder failure')):
            submitted=await self.client.post('/api/live/analyze',headers=HEADERS)
            job=await self.wait_job(submitted.json()['id'])
        self.assertEqual(job['status'],'failed')
        self.assertIsNone(self.app.state.service.live_cursor)
        self.assertTrue((await self.client.get('/api/live/status')).json()['analysis_schedule']['due'])

    async def test_wave_and_sdriq_uploads_use_embedded_metadata(self):
        import io
        import struct
        import wave
        import zlib
        raw = np.tile(np.array([16384,-8192],dtype='<i2'),4096).tobytes()
        buffer = io.BytesIO()
        with wave.open(buffer,'wb') as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(raw)
        header = struct.pack('<IQQII',24000,100000000,0,16,0)
        header += struct.pack('<I',zlib.crc32(header))
        for name,payload in [('recording.wav',buffer.getvalue()),('recording.sdriq',header+raw)]:
            uploaded = await self.client.post('/api/uploads',content=payload,headers={**HEADERS,'X-IQScope-Filename':name})
            self.assertEqual(uploaded.status_code,200)
            response = await self.client.post('/api/analyses',json={'upload_id':uploaded.json()['upload_id']},headers=HEADERS)
            self.assertEqual(response.status_code,202,response.text)
            job = await self.wait_job(response.json()['id'])
            self.assertEqual(job['status'],'completed',job.get('error'))
            self.assertEqual(job['result']['sample_rate'],24000)

    async def test_dataset_catalog_available_to_ui(self):
        response = await self.client.get('/api/datasets')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['entries']),21)
        page = await self.client.get('/')
        self.assertIn('Explorer les jeux de données',page.text)

    async def test_rtty_candidate_report_and_text_export(self):
        from test_rtty import fixture, TEXT
        x,fs = fixture()
        uploaded = await self.client.post('/api/uploads',content=x.astype('<c8').tobytes(),headers=HEADERS)
        response = await self.client.post('/api/analyses',json={'upload_id':uploaded.json()['upload_id'],'sample_rate':fs},headers=HEADERS)
        job = await self.wait_job(response.json()['id'])
        self.assertEqual(job['status'],'completed',job.get('error'))
        rtty = next(t for t in job['result']['wideband_trials'] if t['decoder']=='rtty_ita2')
        self.assertEqual(rtty['status'],'framing_consistent_candidate')
        self.assertEqual(rtty['candidates'][0]['text'],TEXT)
        artifact = await self.client.get(f"/api/jobs/{job['id']}/artifacts/rtty-candidate.txt")
        self.assertEqual(artifact.status_code,200)
        self.assertEqual(artifact.text,TEXT)

    async def test_experimental_lora_is_opt_in_and_exports_exact_bytes(self):
        from test_lora import synchronized_preamble
        from test_lora_payload import HELLO
        x,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=HELLO[7])
        uploaded=await self.client.post('/api/uploads',content=x.astype('<c8').tobytes(),headers=HEADERS)
        identifier=uploaded.json()['upload_id']
        for enabled in (False,True):
            response=await self.client.post('/api/analyses',json={'upload_id':identifier,'sample_rate':fs,'experimental_lora':enabled},headers=HEADERS)
            job=await self.wait_job(response.json()['id'])
            self.assertEqual(job['status'],'completed',job.get('error'))
            self.assertEqual(job['result']['analysis_options']['experimental_lora'],enabled)
            trial=next(t for t in job['result']['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertEqual(trial['mode'],'experimental_guarded' if enabled else 'standard')
            frame=trial['frames'][0]
            artifact=await self.client.get(f"/api/jobs/{job['id']}/artifacts/{frame['artifact']}")
            self.assertEqual(artifact.content,b'HELLO')
            if enabled:self.assertTrue(frame['experimental_mode'])

    async def test_experimental_lora_audio_combination_is_rejected(self):
        response=await self.client.post('/api/analyses',json={'input_kind':'audio','experimental_lora':True},headers=HEADERS)
        self.assertEqual(response.status_code,400)
        self.assertIn('IQ',response.json()['detail'])

    async def test_live_experimental_option_exports_exact_snapshot_payload(self):
        from scipy import signal
        from test_lora import synchronized_preamble
        from test_lora_payload import HELLO
        x,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=HELLO[7])
        fs=256000
        x=np.r_[np.zeros(int(.1*fs)),signal.resample_poly(x,128,125),np.zeros(int(.2*fs))].astype(np.complex64)
        receiver=self.app.state.service.receiver
        receiver.fs=fs;receiver.frequency=868000000;receiver.connected=True
        receiver.blocks.append(x);receiver.buffered=len(x);receiver.total=100000+len(x)
        for enabled in (True,False):
            response=await self.client.post('/api/live/analyze',json={'experimental_lora':enabled},headers=HEADERS)
            self.assertEqual(response.status_code,202,response.text)
            job=await self.wait_job(response.json()['id'])
            self.assertEqual(job['status'],'completed',job.get('error'))
            result=job['result']
            self.assertEqual(result['analysis_options']['experimental_lora'],enabled)
            self.assertEqual(result['source_sample_start'],100000)
            self.assertIn('not lossless',result['continuity_note'])
            trial=next(t for t in result['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertEqual(trial['mode'],'experimental_guarded' if enabled else 'standard')
            frame=trial['frames'][0]
            binary=await self.client.get(f"/api/jobs/{job['id']}/artifacts/{frame['artifact']}")
            self.assertEqual(binary.content,b'HELLO')
            saved=await self.client.get(f"/api/jobs/{job['id']}/artifacts/report.json")
            self.assertEqual(saved.json()['analysis_options']['experimental_lora'],enabled)
            history=(await self.client.get('/api/live/frames')).json()
            self.assertEqual(history['session_id'],receiver.session_id)
            self.assertEqual(len(history['events']),1)
            event=history['events'][0]
            self.assertEqual(event['payload_hex'],b'HELLO'.hex())
            self.assertEqual(event['id'],frame['live_event_id'])
            self.assertEqual(event['observation_count'],1 if enabled else 2)
            self.assertEqual(result['live_history_summary']['merged_observations'],0 if enabled else 1)



if __name__ == '__main__':
    unittest.main()
