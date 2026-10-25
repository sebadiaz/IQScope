import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy import signal
from iqscope import analyze, demo, discover, read_iq


class PipelineTests(unittest.TestCase):
    def test_discovery_and_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = analyze(demo(root), root / 'results')
            self.assertEqual(len(report['signals']), 2)
            a, b = report['signals']
            self.assertAlmostEqual(a['offset_hz'], -60000, delta=150)
            self.assertAlmostEqual(b['offset_hz'], 45000, delta=200)
            self.assertIsNone(b['validated_content'])
            trial = b['decoder_trials'][0]
            fs, audio = wavfile.read(root / 'results' / trial['audio'])
            f, p = signal.welch(audio[fs//4:], fs, nperseg=8192)
            self.assertAlmostEqual(f[np.argmax(p)], 1000, delta=10)

    def test_noise_is_not_content(self):
        rng = np.random.default_rng(1)
        x = rng.normal(size=100000) + 1j*rng.normal(size=100000)
        detections, *_ = discover(x, 100000)
        self.assertEqual(detections, [])

    def test_missing_metadata(self):
        with self.assertRaises(ValueError):
            read_iq('nonexistent.cf32')

    def test_integer_sigmf(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'a.sigmf-meta'
            path.write_text(json.dumps({'global': {'core:sample_rate': 10000,
                                                   'core:datatype': 'ci16_le'}}))
            np.tile(np.array([16384, -8192], dtype='<i2'), 2048).tofile(root / 'a.sigmf-data')
            x, fs, center = read_iq(path)
            self.assertTrue(np.allclose(x, .5-.25j))
            self.assertEqual(fs, 10000)


if __name__ == '__main__':
    unittest.main()
