import tempfile
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
        self.assertEqual(len(data['decoders']),3)

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


if __name__ == '__main__':
    unittest.main()
