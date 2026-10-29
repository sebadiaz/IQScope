"""Carrier synchronization against known impairments, independent of payload fitting."""
import unittest
import numpy as np
from scipy import signal
from iqscope_lora import _correct_fractional_carrier, detect_lora_preamble
from test_lora import synchronized_preamble
from test_lora_payload import HELLO


class LoRaCarrierTests(unittest.TestCase):
    def test_phase_lag_estimates_only_fractional_cfo_for_both_polarities(self):
        length=128
        n=np.arange(length)
        chirp=np.exp(1j*np.pi*(n*n/length-n))
        for polarity in (1,-1):
            for offset in (-2.2,.19,.45,3.3,7.1):
                samples=np.tile(chirp if polarity==1 else chirp.conj(),8)
                samples*=np.exp(2j*np.pi*offset*np.arange(len(samples))/length)
                corrected,evidence=_correct_fractional_carrier(samples,0,8,length,125000)
                expected=(offset+.5)%1-.5
                self.assertEqual(evidence['status'],'fractional_carrier_corrected')
                self.assertAlmostEqual(evidence['fractional_bin_offset'],expected,places=10)
                self.assertAlmostEqual(evidence['offset_hz'],expected*125000/length,places=8)
                lag=np.vdot(corrected[:-length],corrected[length:])
                self.assertAlmostEqual(float(np.angle(lag)),0,places=10)

    def test_incoherent_noise_and_zero_input_do_not_supply_carrier_estimate(self):
        rng=np.random.default_rng(192)
        for samples in (np.zeros(1024,complex),rng.normal(size=1024)+1j*rng.normal(size=1024)):
            unchanged,evidence=_correct_fractional_carrier(samples,0,8,128,125000)
            self.assertIs(unchanged,samples)
            self.assertEqual(evidence['status'],'insufficient_preamble_coherence')
            self.assertNotIn('offset_hz',evidence)

    def test_crc_payload_survives_fractional_delay_cfo_noise_and_inversion(self):
        # Frozen TX vector. These 32 known impairments previously decoded 25/32.
        # The same correct bytes must be recovered in every case; a CRC alone
        # is not sufficient for this test.
        for inverted in (False,True):
            for cfo in (0,.45,3.3,7.1):
                x,fs=synchronized_preamble(inverted,sf=7,offset=47,cfo_bins=cfo,data_symbols=HELLO[7])
                dense=signal.resample_poly(x,4,1)
                for phase in range(4):
                    with self.subTest(inverted=inverted,cfo=cfo,phase=phase):
                        y=dense[phase::4].copy()
                        rng=np.random.default_rng(184)
                        y+=.03*(rng.normal(size=len(y))+1j*rng.normal(size=len(y)))
                        trial=detect_lora_preamble(y,fs)
                        frames=trial.get('frames',[])
                        self.assertEqual(len(frames),1,trial)
                        self.assertEqual(frames[0]['payload_hex'],b'HELLO'.hex())
                        candidate=next(c for c in trial['candidates'] if c['payload']['status']=='payload_crc_valid')
                        self.assertEqual(candidate['carrier_tracking']['status'],'fractional_carrier_corrected')
                        self.assertGreaterEqual(min(candidate['data_symbols']['symbol_energy_fractions']),.65)
                        self.assertGreaterEqual(candidate['data_symbols']['quarter_chirp_correlation'],.8)

    def test_carrier_correction_does_not_validate_wrong_crc(self):
        symbols=[17,13,125,1,1,17,5,5,54,102,33,71,85,27,107,0,81,76]
        x,fs=synchronized_preamble(sf=7,offset=47,cfo_bins=.45,data_symbols=symbols)
        trial=detect_lora_preamble(x,fs)
        self.assertNotIn('frames',trial)
        candidate=next(c for c in trial['candidates'] if c['parameters']['spreading_factor']==7 and c['parameters']['bandwidth_hz']==125000)
        self.assertEqual(candidate['payload']['status'],'payload_crc_mismatch')
