"""Loopback-only HTTP API. Uploads, analysis jobs and rtl_tcp live snapshots."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import math
import shutil
from typing import Literal
from pathlib import Path
import tempfile
import threading
import uuid
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from iqscope import analyze, analyze_samples, demo
from iqscope_web.live_history import LiveLoRaHistory
from iqscope_web.live_ax25_history import LiveAX25History
from iqscope_web.ax25_archive import MAX_ARCHIVE_BYTES, open_ax25_archive
from iqscope_decoders import capabilities
from iqscope_audio import analyze_audio
from iqscope_recordings import recordings, import_vksdr
from .live import LiveReceiver, live_analysis_schedule

MAX_UPLOAD = 128 * 1024 * 1024


class AnalyzeRequest(BaseModel):
    upload_id: str | None = None
    sample_rate: float | None = None
    metadata: dict | None = None
    seconds: float = Field(default=10, gt=0, le=120)
    start_seconds: float = Field(default=0,ge=0,le=1e9)
    start_sample: int | None = Field(default=None,ge=0,le=10**15,strict=True)
    demo: bool = False
    input_kind: Literal['iq','audio'] = 'iq'
    experimental_lora: bool = False


class LiveAnalysisRequest(BaseModel):
    experimental_lora: bool = False


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
        self.live_cursor = None
        self.live_history=LiveLoRaHistory(self.receiver.session_id)
        self.live_ax25_history=LiveAX25History(self.receiver.session_id)

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

    @app.get('/api/datasets')
    def get_datasets():
        from iqscope_datasets import catalog
        return catalog()

    @app.get('/api/recordings/vksdr')
    def get_recordings():
        return recordings()

    @app.post('/api/recordings/vksdr/{identifier}/analyze',status_code=202)
    def start_recording(identifier: str):
        if identifier not in {entry['id'] for entry in recordings()['entries']}:
            raise HTTPException(404,'Unknown VKSDR recording')
        return service.submit(lambda out: import_vksdr(identifier,out))

    @app.get('/api/capabilities')
    def get_capabilities():
        return {'decoders': capabilities(), 'max_upload_bytes': MAX_UPLOAD,
                'live': 'rtl_tcp on 127.0.0.1', 'max_analysis_samples': 8_000_000,
                'audio':{'available':bool(shutil.which('ffmpeg')),'formats':['mp3','wav'],'max_seconds':20,'decoders':['cw_morse','rtty_ita2','afsk1200_ax25']}}

    @app.post('/api/uploads')
    async def upload(request: Request):
        if len(service.upload_sizes) >= 8 or sum(service.upload_sizes.values()) >= 256*1024*1024:
            raise HTTPException(409, 'Temporary upload quota reached; restart the server to clear it')
        identifier = uuid.uuid4().hex
        original_name = unquote(request.headers.get('x-iqscope-filename', 'recording.sigmf-data'))
        suffix = Path(original_name).suffix.lower()
        if suffix not in ('.wav', '.sdriq', '.sigmf-data', '.cf32', '.iq', '.bin', '.mp3'):
            raise HTTPException(400, 'Supported inputs: WAV IQ, .sdriq, SigMF, raw cf32, or MP3 in explicit audio mode')
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
                raise HTTPException(400, 'Input file is too short')
        except BaseException:
            path.unlink(missing_ok=True)
            service.upload_sizes.pop(identifier, None)
            raise
        service.uploads[identifier] = path
        service.upload_sizes[identifier] = count
        return {'upload_id': identifier, 'bytes': count}

    @app.delete('/api/uploads/{identifier}')
    def delete_upload(identifier: str):
        with service.lock:
            if any(job['status'] in ('queued','running') for job in service.jobs.values()):
                raise HTTPException(409,'Wait for the active analysis before removing uploads')
            path = service.uploads.pop(identifier,None)
            if path is None:
                raise HTTPException(404,'Upload not found')
            path.unlink(missing_ok=True)
            service.upload_sizes.pop(identifier,None)
        return {'deleted':True}

    @app.post('/api/analyses', status_code=202)
    def start_analysis(body: AnalyzeRequest):
        if not math.isfinite(body.seconds):
            raise HTTPException(400, 'Duration must be finite')
        if body.experimental_lora and body.input_kind=='audio':
            raise HTTPException(400,'Experimental LoRa requires IQ input')
        if body.demo:
            if body.start_seconds or body.start_sample is not None:
                raise HTTPException(400,'The generated demonstration starts at sample zero')
            return service.submit(lambda out: analyze(demo(out / 'source'), out,experimental_lora=body.experimental_lora))
        source = service.uploads.get(body.upload_id)
        if source is None:
            raise HTTPException(404, 'Upload not found')
        if body.input_kind=='audio':
            if body.start_seconds or body.start_sample is not None:
                raise HTTPException(400,'Window seeking is supported for IQ inputs only')
            if source.suffix not in ('.mp3','.wav') or body.metadata is not None:
                raise HTTPException(400, 'Audio mode requires MP3/WAV without a SigMF sidecar')
            if not 1<=body.seconds<=20:
                raise HTTPException(400, 'Audio duration must be between 1 and 20 seconds')
            if not shutil.which('ffmpeg'):
                raise HTTPException(400, 'Audio import requires ffmpeg installed on PATH')
            return service.submit(lambda out: analyze_audio(source,out,body.seconds))
        if source.suffix=='.mp3':
            raise HTTPException(400, 'MP3 is receiver audio; select explicit audio mode')
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
            return analyze(local, out, body.sample_rate, body.seconds,experimental_lora=body.experimental_lora,
                           start_seconds=body.start_seconds,start_sample=body.start_sample)
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
        if job_id not in service.jobs or Path(name).name != name or not name.endswith(('.wav', '.json', '.csv', '.txt', '.bin', '.kiss', '.sigmf-data', '.sigmf-meta')):
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
        service.live_history.reset(service.receiver.session_id)
        service.live_ax25_history.reset(service.receiver.session_id)
        with service.lock:
            service.live_cursor = None
        return service.receiver.status()

    @app.post('/api/live/stop')
    def live_stop():
        service.receiver.stop()
        return service.receiver.status()

    @app.get('/api/live/status')
    def live_status(experimental_lora: bool = False):
        state=service.receiver.status()
        with service.lock:
            cursor=service.live_cursor
        return dict(state,history_revision=service.live_history.version(),ax25_history_revision=service.live_ax25_history.version(),
                    analysis_schedule=live_analysis_schedule(state,cursor,experimental_lora))

    @app.get('/api/live/frames')
    def live_frames():
        return service.live_history.snapshot()

    @app.get('/api/live/ax25/frames')
    def live_ax25_frames():
        return service.live_ax25_history.snapshot()

    @app.get('/api/live/ax25/frames.kiss')
    def live_ax25_kiss():
        return Response(service.live_ax25_history.kiss(),media_type='application/octet-stream',
                        headers={'Content-Disposition':'attachment; filename="iqscope-live-ax25.kiss"'})

    @app.post('/api/archives/ax25/open')
    async def open_ax25_history(request: Request):
        data=bytearray()
        async for chunk in request.stream():
            if len(data)+len(chunk)>MAX_ARCHIVE_BYTES:
                raise HTTPException(413,'AX.25 archive exceeds 1 MiB')
            data.extend(chunk)
        try:
            return open_ax25_archive(bytes(data))
        except ValueError as error:
            raise HTTPException(400,str(error)) from error

    @app.get('/api/live/spectrum')
    def live_spectrum():
        return {'spectrum': service.receiver.spectrum()}

    @app.post('/api/live/analyze', status_code=202)
    def live_analyze(body: LiveAnalysisRequest | None = None):
        context=service.receiver.snapshot_context()
        if not context['connected']:
            raise HTTPException(409, 'SDR is not connected')
        data,start=context['samples'],context['source_sample_start']
        if data is None or len(data) < 1024:
            raise HTTPException(409, 'Waiting for IQ samples')
        fs, frequency = context['sample_rate'],context['center_frequency_hz']
        experimental_lora=body.experimental_lora if body is not None else False

        def process(out):
            report = analyze_samples(data, fs, frequency, out, source='rtl_tcp snapshot',experimental_lora=experimental_lora)
            report['source_sample_start'] = start
            report['source_sample_end'] = start+len(data)
            report['source_session_id'] = context['session_id']
            report['source_sample_reference'] = 'received_samples_in_session'
            report['source_window_limits'] = {'samples':context['window_sample_limit'],
                                              'seconds':context['window_seconds_limit']}
            report['continuity_note'] = 'Independent latest-window snapshot, not lossless continuous decoding'
            lora=next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
            report['live_history_summary']=service.live_history.observe(context['session_id'],lora.get('frames',[]),fs,start,start+len(data),lora.get('mode','standard'))
            if report.get('lora_artifact'):
                (out/report['lora_artifact']).write_text(json.dumps(lora,indent=2))
            fm=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_fm_ax25')
            report['live_ax25_history_summary']=service.live_ax25_history.observe(
                context['session_id'],fm['frames'],fs,frequency,start,start+len(data))
            if fm.get('artifact'):
                (out/fm['artifact']).write_text(json.dumps(fm,indent=2))
            (out / 'report.json').write_text(json.dumps(report, indent=2))
            with service.lock:
                service.live_cursor=dict(session_id=context['session_id'],sample_rate=fs,
                                         end_sample=start+len(data),experimental_lora=experimental_lora)
            return report
        return service.submit(process)

    app.mount('/', StaticFiles(directory=Path(__file__).parent / 'static', html=True), name='ui')
    return app


def serve(port=8765):
    import uvicorn
    uvicorn.run(create_app(), host='127.0.0.1', port=port)
