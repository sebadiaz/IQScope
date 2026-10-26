import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from test_formats import make_wave

spec = importlib.util.spec_from_file_location('vksdr_probe',Path(__file__).parents[1]/'scripts/vksdr_corpus.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class VksdrTests(unittest.TestCase):
    def test_prefix_is_bounded_even_if_range_is_ignored(self):
        stream = io.BytesIO(b'x'*20000)
        self.assertEqual(len(probe.read_prefix(stream,4096)),4096)
        self.assertEqual(stream.tell(),4096)
        with self.assertRaises(ValueError):
            probe.read_prefix(stream,5*1024*1024)

    def test_partial_wave_roundtrip_does_not_invent_rf_metadata(self):
        rng = np.random.default_rng(96)
        payload = rng.integers(-1000,1000,50000,dtype=np.int16).astype('<i2').tobytes()
        source = make_wave(payload,fs=24000)
        entry = {'id':'test','source_label':'unverified','url':'https://example.org/SDRSharp_123000000Hz.wav'}
        with tempfile.TemporaryDirectory() as directory:
            result = probe.inspect_prefix(source[:32768],entry,directory)
            self.assertTrue(result['sigmf_roundtrip_exact'])
            self.assertIsNone(result['header_center_frequency_hz'])
            self.assertEqual(result['filename_center_hint_hz'],123000000)
            self.assertFalse(result['whole_source_integrity_verified'])
            self.assertLess(result['sample_count'],len(payload)//4)
            from iqscope_formats import read_wave_iq
            with self.assertRaises(ValueError):
                read_wave_iq(Path(directory)/'test/source-prefix.wav')

    def test_fixed_provider_and_redirects_reject_other_hosts(self):
        from iqscope_recordings import check_url, VKSDRRedirectHandler, recordings
        check_url('https://bucket.vksdr.com/iq/example.wav')
        for url in ('http://bucket.vksdr.com/a','https://example.com/a','https://bucket.vksdr.com@127.0.0.1/a'):
            with self.assertRaises(ValueError):
                check_url(url)
        with self.assertRaises(ValueError):
            VKSDRRedirectHandler().redirect_request(None,None,302,'',{},'https://example.com/a')
        manifest = json.loads((Path(__file__).parents[1]/'corpus/vksdr.json').read_text())
        self.assertEqual([(e['id'],e['url']) for e in recordings()['entries']],[(e['id'],e['url']) for e in manifest['entries']])
