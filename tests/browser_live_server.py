"""Browser-test app with an injected IQ snapshot; never loaded by production."""
import numpy as np
from scipy import signal
from fastapi import APIRouter
from iqscope_web.server import create_app as base_app
from test_lora import synchronized_preamble
from test_lora_payload import HELLO


def create_app():
    app=base_app()
    x,_=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=HELLO[7])
    fs=256000
    x=np.r_[np.zeros(int(.1*fs)),signal.resample_poly(x,128,125),np.zeros(int(.2*fs))].astype(np.complex64)
    receiver=app.state.service.receiver
    receiver.fs=fs;receiver.frequency=100000000;receiver.connected=True
    receiver.blocks.append(x);receiver.buffered=len(x);receiver.total=100000+len(x)

    test_routes=APIRouter()
    boundary_state={}

    @test_routes.post('/test/boundary/start')
    def inject_boundary_start():
        from test_live_afsk import boundary_iq,append_interval
        from iqscope_web.live import LiveReceiver
        iq,fs=boundary_iq()
        replacement=LiveReceiver();replacement.fs=fs;replacement.frequency=145000000
        append_interval(replacement,iq[:4*fs]);replacement.connected=True
        app.state.service.receiver.stop();app.state.service.receiver=replacement
        app.state.service.live_history.reset(replacement.session_id)
        boundary_state.update(samples=iq,next_sample=4*fs)
        return replacement.status()

    @test_routes.post('/test/boundary/advance')
    def advance_boundary():
        from test_live_afsk import append_interval
        receiver=app.state.service.receiver
        start=boundary_state['next_sample'];end=start+receiver.fs
        append_interval(receiver,boundary_state['samples'][start:end])
        boundary_state['next_sample']=end
        return receiver.status()

    @test_routes.post('/test/long-frame')
    def inject_long_frame():
        from test_live_afsk import long_frame_receiver
        replacement=long_frame_receiver()
        # The fake wire source ends after its fixture. Expose its retained
        # snapshot as connected for UI tests; no hardware/socket is involved.
        replacement.connected=True;replacement.error=None
        app.state.service.receiver.stop()
        app.state.service.receiver=replacement
        app.state.service.live_history.reset(replacement.session_id)
        return replacement.status()

    # The production app mounts static files at '/'. Test endpoints must match
    # before that catch-all mount, which otherwise answers POST with 405.
    app.router.routes[0:0]=test_routes.routes
    return app
