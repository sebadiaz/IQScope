import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest
import numpy as np
from scipy.io import wavfile

spec = importlib.util.spec_from_file_location('udxf_probe',Path(__file__).parents[1]/'scripts/udxf_audio_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class UdxfAudioTests(unittest.TestCase):
    def test_prefix_bound_is_respected_even_without_http_range(self):
        stream = io.BytesIO(b'x'*20000)
        self.assertEqual(len(probe.read_prefix(stream,4096)),4096)
        self.assertEqual(stream.tell(),4096)
        with self.assertRaises(ValueError):
            probe.read_prefix(stream,3*1024*1024)

    def test_analytic_audio_is_labelled_without_rf_claim(self):
        from test_cw import fixture,TEXT
        x,fs = fixture()
        result = probe.inspect_audio(x.real,fs)
        self.assertEqual(result['input_kind'],'receiver_audio_not_rf_iq')
        self.assertIsNone(result['independently_verified_text'])
        self.assertTrue(any(c['text']==TEXT for c in result['cw_trial']['candidates']),result)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional corpus-probe dependency')
    def test_bounded_audio_decode_and_resampling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'mono.wav'
            wavfile.write(path,16000,np.sin(2*np.pi*650*np.arange(48000)/16000).astype(np.float32))
            audio,fs = probe.decode_audio(path,seconds=2)
            self.assertEqual(fs,8000)
            self.assertEqual(len(audio),16000)
            self.assertEqual(probe.inspect_audio(audio,fs)['cw_trial']['candidates'],[])
