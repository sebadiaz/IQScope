import unittest
import tempfile
import json
from pathlib import Path
import numpy as np
from scipy import signal
from iqscope_ofdm import detect_cyclic_prefix


def fixture(useful=64,guard=16,symbols=96):
    rng = np.random.default_rng(105)
    blocks = []
    for _ in range(symbols):
        bins = (2*rng.integers(0,2,useful)-1)+1j*(2*rng.integers(0,2,useful)-1)
        bins[0] = 0
        waveform = np.fft.ifft(bins)*np.sqrt(useful/2)
        blocks.append(np.r_[waveform[-guard:],waveform])
    x = np.r_[rng.normal(size=37)*.1,np.concatenate(blocks)]
    x = signal.lfilter([1,0,.2j], [1],x)
    x *= np.exp(2j*np.pi*.017*np.arange(len(x)))
    x += .04*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    return x,1000000


class OfdmTests(unittest.TestCase):
    def test_prefix_lengths_with_noise_multipath_cfo_and_arbitrary_start(self):
        for useful,guard in ((32,8),(64,16),(128,16),(256,8),(1024,128),(2048,512)):
            x,fs = fixture(useful,guard)
            result = detect_cyclic_prefix(x,fs)
            self.assertTrue(result['candidates'],result)
            best = result['candidates'][0]
            self.assertEqual((best['parameters']['useful_samples'],best['parameters']['guard_samples']),(useful,guard))
            self.assertEqual(best['score_kind'],'heuristic_not_probability')

    def test_noise_colored_noise_tone_and_unrelated_fsk_abstain(self):
        from test_fsk import fixture as fsk_fixture
        rng = np.random.default_rng(106)
        for _ in range(4):
            noise = rng.normal(size=32768)+1j*rng.normal(size=32768)
            for x in (noise,signal.lfilter([1],[1,-.96],noise)):
                self.assertEqual(detect_cyclic_prefix(x,1000000)['candidates'],[])
        tone = np.exp(2j*np.pi*.13*np.arange(32768))
        self.assertEqual(detect_cyclic_prefix(tone,1000000)['candidates'],[])
        x,fs,_ = fsk_fixture()
        self.assertEqual(detect_cyclic_prefix(x,fs)['candidates'],[])

    def test_report_exports_evidence_without_counting_it_as_frames(self):
        from iqscope import analyze_samples
        x,fs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,0,directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='ofdm_cp')
            self.assertTrue(trial['candidates'])
            self.assertNotIn('frames',trial)
            self.assertEqual(json.loads((Path(directory)/report['ofdm_artifact']).read_text())['candidates'],trial['candidates'])

    def test_unverified_input_is_preserved_in_exported_cp_evidence(self):
        from iqscope import analyze
        x,fs = fixture()
        x = x*.1
        words = np.empty((len(x),2),dtype='<i2')
        words[:,0] = np.rint(x.real*32768)
        words[:,1] = np.rint(x.imag*32768)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            words.tofile(root/'input.sigmf-data')
            (root/'input.sigmf-meta').write_text(json.dumps({'global':{'core:datatype':'ci16_le','core:sample_rate':fs,
                'iqscope:byte_order_status':'unverified_hypothesis','iqscope:sample_rate_source':'filename'}}))
            report = analyze(root/'input.sigmf-meta',root/'results')
            artifact = json.loads((root/'results'/report['ofdm_artifact']).read_text())
            self.assertEqual(artifact['input_interpretation_status'],'unverified_byte_order_and_header_layout')
            self.assertEqual(artifact['input_datatype_hypothesis'],'ci16_le')
            self.assertEqual(artifact['sample_rate_source'],'filename')

    def test_sample_budget_and_short_input_are_explicit(self):
        x,fs = fixture()
        result = detect_cyclic_prefix(np.tile(x,40),fs)
        self.assertTrue(result['sample_budget_reached'])
        self.assertEqual(result['analyzed_samples'],262144)
        self.assertLessEqual(len(result['windows_examined']),3)
        self.assertEqual(detect_cyclic_prefix(x[:500],fs)['status'],'not_applicable')
