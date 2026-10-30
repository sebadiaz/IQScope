"""Noisy quarter-chirp evidence must agree with reference and remain payload-blind."""
import unittest
import numpy as np
from scipy import signal
from iqscope_lora import detect_lora_preamble,_reference_quarter_evidence
from test_lora import synchronized_preamble
from test_lora_payload import HELLO

WRONG_CRC=[17,13,125,1,1,17,5,5,54,102,33,71,85,27,107,0,81,76]


def quarter_fixture(symbols=HELLO[7],noise=.4,missing=False):
    x,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=symbols,quarter_chirp=not missing)
    y=signal.resample_poly(x,1,2)
    if noise:
        rng=np.random.default_rng(250)
        y[12*128:12*128+32]+=noise*(rng.normal(size=32)+1j*rng.normal(size=32))
    return y


def candidate(trial):
    return next(c for c in trial['candidates'] if c['parameters']['spreading_factor']==7 and c['parameters']['bandwidth_hz']==125000)


class LoRaQuarterTests(unittest.TestCase):
    def test_exact_payload_with_noisy_quarter_below_legacy_threshold(self):
        trial=detect_lora_preamble(quarter_fixture(),125000)
        self.assertEqual(trial['frames'][0]['payload_hex'],b'HELLO'.hex())
        data=candidate(trial)['data_symbols']
        self.assertEqual(data['quarter_chirp_method'],'reference_consistent_projection')
        self.assertGreaterEqual(data['quarter_chirp_correlation'],.65)
        self.assertLess(data['quarter_chirp_correlation'],.8)
        evidence=data['quarter_reference_evidence']
        self.assertGreaterEqual(evidence['reference_coherence'],.5)
        self.assertGreaterEqual(evidence['projection_snr'],16)
        self.assertLessEqual(evidence['complex_amplitude_mismatch'],.25)

    def test_boundary_choice_is_independent_of_crc_and_wrong_crc_stays_rejected(self):
        valid=detect_lora_preamble(quarter_fixture(),125000)
        invalid=detect_lora_preamble(quarter_fixture(WRONG_CRC),125000)
        self.assertNotIn('frames',invalid)
        self.assertEqual(candidate(invalid)['payload']['status'],'payload_crc_mismatch')
        first=candidate(valid)['data_symbols'];second=candidate(invalid)['data_symbols']
        self.assertEqual(first['candidate_data_start_seconds'],second['candidate_data_start_seconds'])
        self.assertEqual(first['quarter_chirp_method'],second['quarter_chirp_method'])
        self.assertAlmostEqual(first['quarter_chirp_correlation'],second['quarter_chirp_correlation'],places=12)

    def test_legacy_quarter_gate_keeps_priority(self):
        trial=detect_lora_preamble(quarter_fixture(noise=0),125000)
        self.assertEqual(trial['frames'][0]['payload_hex'],b'HELLO'.hex())
        self.assertEqual(candidate(trial)['data_symbols']['quarter_chirp_method'],'normalized_template_correlation')

    def test_missing_quarter_has_bounded_rejection_diagnostics(self):
        trial=detect_lora_preamble(quarter_fixture(noise=0,missing=True),125000)
        self.assertNotIn('frames',trial)
        data=candidate(trial)['data_symbols']
        self.assertEqual(data['status'],'no_consistent_final_quarter_chirp')
        self.assertEqual(data['quarter_boundary_budget'],5)
        self.assertLess(data['maximum_quarter_chirp_correlation'],.65)
        self.assertLessEqual(len(data['reference_quarter_attempts']),5)

    def test_reference_check_rejects_absence_wrong_phase_and_wrong_amplitude(self):
        n=np.arange(128);down=np.exp(-1j*np.pi*(n*n/128-n));expected=down[:32]
        rng=np.random.default_rng(251)
        reference=np.tile(down,(2,1))+.2*(rng.normal(size=(2,128))+1j*rng.normal(size=(2,128)))
        for observed in (np.zeros(32),-expected,.1*expected,2*expected,expected.conj()):
            result=_reference_quarter_evidence(reference,expected,observed)
            self.assertEqual(result['status'],'reference_quarter_rejected',result)

    def test_noise_quarters_and_incoherent_references_do_not_pass(self):
        n=np.arange(128);down=np.exp(-1j*np.pi*(n*n/128-n));expected=down[:32]
        for seed in range(128):
            rng=np.random.default_rng(260+seed)
            noise=lambda shape:.4*(rng.normal(size=shape)+1j*rng.normal(size=shape))
            reference=np.tile(down,(2,1))+noise((2,128))
            result=_reference_quarter_evidence(reference,expected,noise(32))
            self.assertEqual(result['status'],'reference_quarter_rejected',result)
            result=_reference_quarter_evidence(noise((2,128)),expected,expected)
            self.assertEqual(result['status'],'reference_quarter_rejected',result)
