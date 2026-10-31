import unittest
import numpy as np
from iqscope_lora import _correct_fractional_carrier,_correct_matched_carrier


def chirp(length):
    n=np.arange(length)
    return np.exp(1j*np.pi*(n*n/length-n))


class MatchedPreambleCarrierTests(unittest.TestCase):
    def test_noise_dominated_raw_lag_can_have_reliable_matched_amplitudes(self):
        for inverted,offset in ((False,.37),(True,-.37),(False,.49)):
            up=chirp(128);template=up.conj() if inverted else up
            rng=np.random.default_rng(817)
            x=np.tile(template,6)*np.exp(2j*np.pi*offset*np.arange(768)/128)
            x+=1.8*(rng.normal(size=768)+1j*rng.normal(size=768))
            self.assertEqual(_correct_fractional_carrier(x,0,6,128,125000,.3)[1]['status'],'insufficient_preamble_coherence')
            _,e=_correct_matched_carrier(x,0,6,128,125000,up,-1 if inverted else 1)
            self.assertEqual(e['status'],'fractional_carrier_corrected')
            error=(e['fractional_bin_offset']-offset+.5)%1-.5
            self.assertLess(abs(error),.06)
            self.assertLess(e['raw_lag_coherence'],.3)
            self.assertGreaterEqual(e['phase_concentration'],.65)

    def test_noise_and_inconsistent_phases_are_rejected(self):
        up=chirp(128)
        for seed in range(16):
            rng=np.random.default_rng(910+seed)
            x=rng.normal(size=768)+1j*rng.normal(size=768)
            self.assertNotEqual(_correct_matched_carrier(x,0,6,128,125000,up,1)[1]['status'],'fractional_carrier_corrected')
        phases=np.r_[0,np.cumsum(2*np.pi*np.arange(5)/5)]
        x=(np.exp(1j*phases[:,None])*up).ravel()
        self.assertNotEqual(_correct_matched_carrier(x,0,6,128,125000,up,1)[1]['status'],'fractional_carrier_corrected')

    def test_payload_changes_cannot_choose_carrier(self):
        up=chirp(128);prefix=np.tile(up,6)*np.exp(2j*np.pi*.23*np.arange(768)/128)
        a,first=_correct_matched_carrier(np.r_[prefix,np.ones(512)],0,6,128,125000,up,1)
        b,second=_correct_matched_carrier(np.r_[prefix,-np.ones(512)],0,6,128,125000,up,1)
        self.assertEqual(first,second)
        np.testing.assert_array_equal(a[:768],b[:768])
        self.assertEqual(first['phase_hypotheses'],384)

    def test_less_than_six_chirps_is_not_accepted(self):
        up=chirp(128)
        self.assertEqual(_correct_matched_carrier(np.tile(up,5),0,5,128,125000,up,1)[1]['status'],'insufficient_matched_preamble_blocks')
