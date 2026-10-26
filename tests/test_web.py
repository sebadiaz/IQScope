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

    async def wait_job(self, identifier):
        for _ in range(150):
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
        self.assertEqual(len(data['decoders']),9)

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
        self.assertIn('snapshot', result['result']['continuity_note'])

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
        self.assertEqual(len(response.json()['entries']),19)
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


if __name__ == '__main__':
    unittest.main()
