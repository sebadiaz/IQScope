"""Coherent discovery improves preamble evidence without validating content."""
import unittest
import numpy as np
from iqscope_lora import detect_lora_preamble, _coherent_preamble_run, _opposite_chirp_pair


def chirp(length):
    n=np.arange(length)
    return np.exp(1j*np.pi*(n*n/length-n))


class LoRaCoherentTests(unittest.TestCase):
    def test_weak_repeated_chirps_use_coherent_evidence_and_never_claim_bytes(self):
        for sf,inverted in ((7,False),(8,True),(10,False)):
            length=2**sf
            up=chirp(length)
            x=np.tile(up.conj() if inverted else up,10)
            x*=np.exp(2j*np.pi*.27*np.arange(len(x))/length)
            rng=np.random.default_rng(230)
            x+=.7*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
            trial=detect_lora_preamble(x,125000)
            matches=[c for c in trial['candidates'] if c['parameters']['spreading_factor']==sf and c['parameters']['chirp_polarity']==(-1 if inverted else 1)]
            self.assertTrue(matches,trial)
            evidence=matches[0]['evidence']['discovery']
            self.assertEqual(evidence['method'],'six_chirp_coherent_average')
            self.assertLess(evidence['raw_median_three_bin_energy_fraction'],.65)
            self.assertGreaterEqual(evidence['combined_three_bin_energy_fraction'],.65)
            self.assertGreaterEqual(evidence['preamble_lag_coherence'],.3)
            self.assertNotIn('frames',trial)

    def test_inconsistent_phase_progression_cannot_supply_coherent_evidence(self):
        up=chirp(128)
        phases=np.r_[0,np.cumsum(2*np.pi*np.arange(5)/5)]
        matrix=np.exp(1j*phases[:,None])*up
        candidate,search=_coherent_preamble_run(matrix,np.zeros(6,int),np.ones(6),up,1)
        self.assertIsNone(candidate)
        self.assertEqual(search['checked_windows'],1)

    def test_periodic_tone_cannot_match_chirp_and_search_budget_is_enforced(self):
        matrix=np.ones((40,128),complex)
        candidate,search=_coherent_preamble_run(matrix,np.zeros(40,int),np.full(40,3/128),chirp(128),1)
        self.assertIsNone(candidate)
        self.assertEqual(search['checked_windows'],32)
        self.assertTrue(search['budget_reached'])

    def test_coherent_opposite_pair_requires_two_chirps(self):
        up=chirp(128)
        rng=np.random.default_rng(231)
        pair=np.tile(up.conj(),2)
        pair+=.45*(rng.normal(size=len(pair))+1j*rng.normal(size=len(pair)))
        x=np.r_[np.zeros(128),pair,np.zeros(128)]
        legacy=_opposite_chirp_pair(x,up,1,128,125000)
        improved=_opposite_chirp_pair(x,up,1,128,125000,coherent_fallback=True)
        self.assertEqual(legacy['status'],'no_consistent_opposite_pair')
        self.assertEqual(improved['method'],'coherent_opposite_pair')
        self.assertGreaterEqual(improved['minimum_three_bin_energy_fraction'],.65)
        self.assertGreaterEqual(improved['combined_three_bin_energy_fraction'],.8)
        self.assertGreaterEqual(improved['pair_coherence'],.5)
        single=np.r_[np.zeros(128),pair[:128],np.zeros(256)]
        self.assertEqual(_opposite_chirp_pair(single,up,1,128,125000,coherent_fallback=True)['status'],'no_consistent_opposite_pair')

    def test_noise_and_periodic_wideband_waveform_abstain(self):
        for seed in range(4):
            rng=np.random.default_rng(232+seed)
            noise=rng.normal(size=12000)+1j*rng.normal(size=12000)
            periodic=np.tile(rng.normal(size=128)+1j*rng.normal(size=128),80)
            for x in (noise,periodic):
                trial=detect_lora_preamble(x,125000)
                self.assertEqual(trial['candidates'],[])
                self.assertNotIn('frames',trial)

    def test_pipeline_exports_weak_evidence_without_validated_payload_file(self):
        import json,tempfile
        from pathlib import Path
        from iqscope import analyze_samples
        up=chirp(128);x=np.tile(up,10)
        x*=np.exp(2j*np.pi*.27*np.arange(len(x))/128)
        rng=np.random.default_rng(230)
        x+=.7*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,125000,0,directory)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertTrue(any(c['evidence']['discovery']['method']=='six_chirp_coherent_average' for c in trial['candidates']))
            self.assertNotIn('frames',trial)
            artifact=json.loads((Path(directory)/report['lora_artifact']).read_text())
            self.assertNotIn('frames',artifact)
            self.assertFalse(list(Path(directory).glob('lora-payload-*.bin')))
