import unittest
import numpy as np
from iqscope_lora import detect_lora_preamble,_opposite_chirp_pair
from test_lora_matched import fixture,candidate
from test_lora_quarter import WRONG_CRC


class LoRaInferredBoundaryTests(unittest.TestCase):
    def test_single_inferred_boundary_is_independent_of_crc(self):
        x,fs=fixture(missing=True)
        good=detect_lora_preamble(x,fs)
        x,fs=fixture(missing=True,symbols=WRONG_CRC)
        bad=detect_lora_preamble(x,fs)
        self.assertNotIn('frames',bad)
        self.assertEqual(candidate(bad)['payload']['status'],'payload_crc_mismatch')
        for result in (good,bad):
            data=candidate(result)['data_symbols']
            self.assertFalse(data['quarter_chirp_validated'])
            self.assertEqual(data['inferred_boundary_evidence']['boundary_hypotheses_decoded'],1)
        self.assertEqual(candidate(good)['data_symbols']['candidate_data_start_seconds'],candidate(bad)['data_symbols']['candidate_data_start_seconds'])
        self.assertEqual(candidate(good)['timing_tracking'],candidate(bad)['timing_tracking'])

    def test_matched_pair_requires_two_repeated_chirps(self):
        n=np.arange(128);up=np.exp(1j*np.pi*(n*n/128-n))
        rng=np.random.default_rng(721)
        noise=lambda size:.8*(rng.normal(size=size)+1j*rng.normal(size=size))
        down=up.conj()
        x=np.r_[noise(128),np.tile(down,2)+noise(256),noise(128)]
        result=_opposite_chirp_pair(x,up,1,128,125000,matched_fallback=True)
        self.assertEqual(result['method'],'matched_opposite_pair')
        self.assertGreaterEqual(result['pair_coherence'],.3)
        x=np.r_[noise(128),down+noise(128),noise(256)]
        self.assertEqual(_opposite_chirp_pair(x,up,1,128,125000,matched_fallback=True)['status'],'no_consistent_opposite_pair')
        for seed in range(32):
            rng=np.random.default_rng(730+seed)
            x=rng.normal(size=512)+1j*rng.normal(size=512)
            self.assertEqual(_opposite_chirp_pair(x,up,1,128,125000,matched_fallback=True)['status'],'no_consistent_opposite_pair')

    def test_pipeline_exposes_inferred_sync_with_exact_export(self):
        import tempfile,json
        from pathlib import Path
        from iqscope import analyze_samples
        x,fs=fixture(missing=True)
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,fs,0,directory)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
            frame=trial['frames'][0]
            self.assertFalse(frame['quarter_chirp_validated'])
            self.assertEqual((Path(directory)/frame['artifact']).read_bytes(),b'HELLO')
            artifact=json.loads((Path(directory)/report['lora_artifact']).read_text())
            self.assertFalse(artifact['frames'][0]['quarter_chirp_validated'])
