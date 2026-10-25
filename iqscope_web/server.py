"""Loopback-only HTTP API. Uploads, analysis jobs and rtl_tcp live snapshots."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import math
from pathlib import Path
import tempfile
import threading
import uuid
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from iqscope import analyze, analyze_samples, demo
from iqscope_decoders import capabilities
from .live import LiveReceiver

MAX_UPLOAD = 128 * 1024 * 1024


class AnalyzeRequest(BaseModel):
    upload_id: str | None = None
    sample_rate: float | None = None
    metadata: dict | None = None
    seconds: float = Field(default=10, gt=0, le=120)
    demo: bool = False


class LiveRequest(BaseModel):
    port: int = Field(default=1234, ge=1024, le=65535)
    frequency_hz: int = Field(default=100_000_000, ge=100_000, le=2_000_000_000)
    sample_rate: int = 1_024_000


class AnalysisService:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.uploads = {}
        self.upload_sizes = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.receiver = LiveReceiver()

    def submit(self, function):
        with self.lock:
            if any(job['status'] in ('queued', 'running') for job in self.jobs.values()):
                raise HTTPException(409, 'An analysis is already running')
            if len(self.jobs) >= 32:
                import shutil
                oldest = next(iter(self.jobs))
                del self.jobs[oldest]
                shutil.rmtree(self.root / oldest, ignore_errors=True)
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {'id': job_id, 'status': 'queued', 'result': None, 'error': None}
        out = self.root / job_id
        out.mkdir()

        def work():
            with self.lock:
                self.jobs[job_id]['status'] = 'running'
            try:
                result = function(out)
                with self.lock:
                    self.jobs[job_id].update(status='completed', result=result)
            except Exception as exc:
                with self.lock:
                    self.jobs[job_id].update(status='failed', error=str(exc))
        self.pool.submit(work)
        return {'id': job_id, 'status': 'queued'}

    def close(self):
        self.receiver.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)


def create_app(root=None):
    temporary = tempfile.TemporaryDirectory(prefix='iqscope-') if root is None else None
    service = AnalysisService(root or temporary.name)

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
        if temporary:
            temporary.cleanup()

    app = FastAPI(title='IQScope local', lifespan=lifespan)
    app.state.service = service

    @app.middleware('http')
    async def local_request_guard(request, call_next):
        # Prevent arbitrary websites from driving the local SDR through a browser.
        host = request.headers.get('host', '')
        if host.split(':')[0] not in ('127.0.0.1', 'localhost', 'testserver'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Loopback host required'}, status_code=403)
        if request.method != 'GET':
            origin = request.headers.get('origin')
            if (origin and origin not in (f'http://{host}', f'https://{host}')) or request.headers.get('x-iqscope') != 'local':
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': 'Same-origin IQScope request required'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return response

    @app.get('/api/capabilities')
    def get_capabilities():
        return {'decoders': capabilities(), 'max_upload_bytes': MAX_UPLOAD,
                'live': 'rtl_tcp on 127.0.0.1', 'max_analysis_samples': 8_000_000}

    @app.post('/api/uploads')
    async def upload(request: Request):
        if len(service.upload_sizes) >= 8 or sum(service.upload_sizes.values()) >= 256*1024*1024:
            raise HTTPException(409, 'Temporary upload quota reached; restart the server to clear it')
        identifier = uuid.uuid4().hex
        original_name = unquote(request.headers.get('x-iqscope-filename', 'recording.sigmf-data'))
        suffix = Path(original_name).suffix.lower()
        if suffix not in ('.wav', '.sdriq', '.sigmf-data', '.cf32', '.iq', '.bin'):
            raise HTTPException(400, 'Supported inputs: WAV IQ, .sdriq, SigMF or raw cf32')
        path = service.root / f'{identifier}{suffix}'
        count = 0
        service.upload_sizes[identifier] = 0
        try:
            with path.open('xb') as handle:
                async for block in request.stream():
                    count += len(block)
                    service.upload_sizes[identifier] = count
                    if sum(service.upload_sizes.values()) > 256*1024*1024:
                        raise HTTPException(413, 'Session upload quota exceeded')
                    if count > MAX_UPLOAD:
                        raise HTTPException(413, 'File exceeds 128 MiB limit')
                    handle.write(block)
            if count < 1024:
                raise HTTPException(400, 'IQ file is too short')
        except BaseException:
            path.unlink(missing_ok=True)
            service.upload_sizes.pop(identifier, None)
            raise
        service.uploads[identifier] = path
        service.upload_sizes[identifier] = count
        return {'upload_id': identifier, 'bytes': count}

    @app.post('/api/analyses', status_code=202)
    def start_analysis(body: AnalyzeRequest):
        if not math.isfinite(body.seconds):
            raise HTTPException(400, 'Duration must be finite')
        if body.demo:
            return service.submit(lambda out: analyze(demo(out / 'source'), out))
        source = service.uploads.get(body.upload_id)
        if source is None:
            raise HTTPException(404, 'Upload not found')
        self_describing = source.suffix in ('.wav', '.sdriq')
        if self_describing and body.metadata is not None:
            raise HTTPException(400, 'WAV and .sdriq already contain metadata; omit the SigMF sidecar')
        if not self_describing and body.metadata is None and (body.sample_rate is None or not math.isfinite(body.sample_rate) or not 1000 <= body.sample_rate <= 20_000_000):
            raise HTTPException(400, 'Raw cf32 requires a sample rate between 1 kS/s and 20 MS/s')
        metadata = body.metadata
        if metadata is not None:
            try:
                fs = float(metadata['global']['core:sample_rate'])
                if not math.isfinite(fs) or not 1000 <= fs <= 20_000_000:
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                raise HTTPException(400, 'SigMF sample rate must be between 1 kS/s and 20 MS/s')

        def process(out):
            # Per-job metadata avoids races if the same upload is analyzed twice.
            local = out / ('input'+source.suffix)
            import os
            os.link(source, local)
            if metadata is not None:
                local.with_suffix('.sigmf-meta').write_text(json.dumps(metadata))
            return analyze(local, out, body.sample_rate, body.seconds)
        return service.submit(process)

    @app.get('/api/jobs/{job_id}')
    def get_job(job_id: str):
        with service.lock:
            job = service.jobs.get(job_id)
            if job is None:
                raise HTTPException(404, 'Job not found')
            return dict(job)

    @app.get('/api/jobs/{job_id}/artifacts/{name}')
    def artifact(job_id: str, name: str):
        if job_id not in service.jobs or Path(name).name != name or not name.endswith(('.wav', '.json', '.csv')):
            raise HTTPException(404, 'Artifact not found')
        path = service.root / job_id / name
        if not path.is_file():
            raise HTTPException(404, 'Artifact not found')
        return FileResponse(path, filename=name)

    @app.post('/api/live/start')
    def live_start(body: LiveRequest):
        if body.sample_rate not in (256000, 1024000, 2048000, 2400000):
            raise HTTPException(400, 'Supported rates: 256000, 1024000, 2048000, 2400000')
        service.receiver.start(body.port, body.frequency_hz, body.sample_rate)
        return service.receiver.status()

    @app.post('/api/live/stop')
    def live_stop():
        service.receiver.stop()
        return service.receiver.status()

    @app.get('/api/live/status')
    def live_status():
        return service.receiver.status()

    @app.get('/api/live/spectrum')
    def live_spectrum():
        return {'spectrum': service.receiver.spectrum()}

    @app.post('/api/live/analyze', status_code=202)
    def live_analyze():
        if not service.receiver.connected:
            raise HTTPException(409, 'SDR is not connected')
        data, start = service.receiver.snapshot()
        if data is None or len(data) < 1024:
            raise HTTPException(409, 'Waiting for IQ samples')
        fs, frequency = service.receiver.fs, service.receiver.frequency

        def process(out):
            report = analyze_samples(data, fs, frequency, out, source='rtl_tcp snapshot')
            report['source_sample_start'] = start
            report['continuity_note'] = 'Independent latest-window snapshot, not lossless continuous decoding'
            (out / 'report.json').write_text(json.dumps(report, indent=2))
            return report
        return service.submit(process)

    app.mount('/', StaticFiles(directory=Path(__file__).parent / 'static', html=True), name='ui')
    return app


def serve(port=8765):
    import uvicorn
    uvicorn.run(create_app(), host='127.0.0.1', port=port)
