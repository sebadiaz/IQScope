import unittest
import numpy as np
from iqscope_lora import detect_lora_preamble
from iqscope_lora_search import select_lora_windows, interval_coverage
from test_lora import synchronized_preamble
from test_lora_payload import HELLO


class TemporalSearchTests(unittest.TestCase):
    def test_late_repeated_payloads_keep_global_times(self):
        packet,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=HELLO[7])
        x=np.zeros(int(3*fs),dtype=complex)
        for time in (.7,1.9):
            start=int(time*fs)
            x[start:start+len(packet)]=packet
        result=detect_lora_preamble(x,fs)
        frames=result.get('frames',[])
        self.assertEqual([f['payload_hex'] for f in frames],['48454c4c4f']*2)
        for frame,onset in zip(frames,(.7,1.9)):
            self.assertAlmostEqual(frame['time_seconds'],onset+12.25*128/125000,delta=.001)
        self.assertTrue(result['temporal_search']['partial'])
        self.assertGreater(result['temporal_search']['window_count'],1)
        self.assertFalse(result['temporal_search']['selection_uses_annotations'])

    def test_scheduler_has_bounded_cost(self):
        windows,evidence=select_lora_windows(np.ones(8000000,dtype=np.float32),250000)
        self.assertLessEqual(len(windows),8)
        self.assertLessEqual(evidence['energy_samples'],262144)
        self.assertTrue(all(w['end_sample']-w['start_sample']<=250000 for w in windows))

    def test_interval_union_and_gap(self):
        self.assertEqual(interval_coverage([(0,1),(.5,1.5)],2),(1.5,.5))
        self.assertEqual(interval_coverage([(1,2),(0,1)],2),(2,0))

    def test_long_noise_abstains(self):
        rng=np.random.default_rng(104)
        x=rng.normal(size=500000)+1j*rng.normal(size=500000)
        result=detect_lora_preamble(x,250000)
        self.assertEqual(result['candidates'],[])
        self.assertNotIn('frames',result)

    def test_late_pipeline_exports_bytes(self):
        import tempfile
        from pathlib import Path
        from iqscope import analyze_samples
        packet,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=HELLO[7])
        x=np.r_[np.zeros(int(1.1*fs),dtype=complex),packet]
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,fs,0,directory)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertEqual(len(trial['frames']),1)
            frame=trial['frames'][0]
            self.assertGreater(frame['time_seconds'],1.1)
            self.assertEqual((Path(directory)/frame['artifact']).read_bytes(),b'HELLO')
