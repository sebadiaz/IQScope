"""Browser-test app with an injected IQ snapshot; never loaded by production."""
import numpy as np
from scipy import signal
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

    @app.post('/test/long-frame')
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

    return app
