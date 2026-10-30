"""Noise-aware fallback remains preamble-gated and requires an exact payload CRC."""
import unittest
import numpy as np
from iqscope_lora import detect_lora_preamble,_matched_peak_evidence
from test_lora import synchronized_preamble
from test_lora_payload import HELLO
from test_lora_quarter import WRONG_CRC


def fixture(seed=510,symbols=HELLO[7],missing=False):
    base,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=.19,data_symbols=symbols,quarter_chirp=not missing)
    rng=np.random.default_rng(seed)
    x=base+.75*(rng.normal(size=len(base))+1j*rng.normal(size=len(base)))
    # A controlled uneven-noise fixture: preserve the downchirp pair while
    # preamble, sync word, quarter and data have independent additive noise.
    x[10*256:12*256]=base[10*256:12*256]
    return x,fs


def candidate(result):
    return next(c for c in result['candidates'] if c['parameters']['spreading_factor']==7 and c['parameters']['bandwidth_hz']==125000)


class LoRaMatchedTests(unittest.TestCase):
    def test_noisy_symbols_recover_exact_bytes(self):
        for seed in range(510,514):
            x,fs=fixture(seed)
            result=detect_lora_preamble(x,fs)
            self.assertEqual(result['frames'][0]['payload_hex'],b'HELLO'.hex())
            c=candidate(result)
            timing=c['timing_tracking']
            self.assertEqual(timing['acceptance_method'],'coherent_preamble_matched_peak')
            self.assertLess(timing['maximum_single_bin_energy_fraction'],.65)
            self.assertGreaterEqual(timing['coherent_single_bin_energy_fraction'],.8)
            self.assertTrue(c['data_symbols']['matched_peak_symbol_evidence'])

    def test_bad_crc_cannot_change_preamble_phase(self):
        x,fs=fixture();valid=detect_lora_preamble(x,fs)
        x,fs=fixture(symbols=WRONG_CRC);invalid=detect_lora_preamble(x,fs)
        self.assertNotIn('frames',invalid)
        self.assertEqual(candidate(invalid)['payload']['status'],'payload_crc_mismatch')
        self.assertEqual(candidate(valid)['timing_tracking'],candidate(invalid)['timing_tracking'])
        self.assertEqual(candidate(valid)['data_symbols']['candidate_data_start_seconds'],candidate(invalid)['data_symbols']['candidate_data_start_seconds'])

    def test_missing_quarter_remains_unvalidated(self):
        x,fs=fixture(missing=True)
        result=detect_lora_preamble(x,fs)
        self.assertEqual(result['frames'][0]['payload_hex'],b'HELLO'.hex())
        self.assertFalse(result['frames'][0]['quarter_chirp_validated'])
        self.assertEqual(candidate(result)['data_symbols']['quarter_chirp_method'],'inferred_from_sync_word')

    def test_white_noise_and_competing_peaks_fail_reliability(self):
        for length in (128,1024):
            for seed in range(64):
                rng=np.random.default_rng(600+seed)
                values=rng.normal(size=length)+1j*rng.normal(size=length)
                power=abs(np.fft.fft(values))**2
                self.assertEqual(_matched_peak_evidence(power,int(power.argmax()))['status'],'unreliable_matched_peak')
        power=np.ones(128);power[10]=1000;power[50]=900
        self.assertEqual(_matched_peak_evidence(power,10)['status'],'unreliable_matched_peak')
        power[50]=1
        self.assertEqual(_matched_peak_evidence(power,10)['status'],'reliable_matched_peak')
        self.assertEqual(_matched_peak_evidence(np.zeros(128),0)['status'],'unreliable_matched_peak')
