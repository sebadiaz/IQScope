"""Fractional timing choices must come from preamble evidence, never packet CRC."""
from fractions import Fraction
import unittest
import numpy as np
from scipy import signal
from iqscope_lora import detect_lora_preamble, _interpolated_tone_bin, _refine_fractional_timing
from test_lora import synchronized_preamble
from test_lora_payload import HELLO


class LoRaTimingTests(unittest.TestCase):
    def test_interpolated_tone_frequency_with_noise_and_fft_wrap(self):
        for length in (128,1024):
            n=np.arange(length)
            for frequency in (-.29,.45,17.23,length-.08):
                rng=np.random.default_rng(210)
                values=np.exp(2j*np.pi*frequency*n/length)
                values+=.04*(rng.normal(size=length)+1j*rng.normal(size=length))
                peak=int(np.argmax(abs(np.fft.fft(values))))
                estimate=_interpolated_tone_bin(values,peak)
                error=(estimate-frequency+length/2)%length-length/2
                self.assertLess(abs(error),.02)
        self.assertIsNone(_interpolated_tone_bin(np.exp(2j*np.pi*9*np.arange(128)/128),3))

    def test_phase_selection_is_independent_of_payload_and_crc(self):
        damaged=HELLO[7].copy();damaged[9]=(damaged[9]+4)%128
        tracking=[]
        for symbols,expected in ((HELLO[7],True),(damaged,False)):
            x,fs=synchronized_preamble(sf=7,offset=47,cfo_bins=.45,data_symbols=symbols)
            trial=detect_lora_preamble(x,fs)
            self.assertEqual(bool(trial.get('frames')),expected)
            candidate=next(c for c in trial['candidates'] if c['parameters']['spreading_factor']==7 and c['parameters']['bandwidth_hz']==125000)
            timing=candidate['timing_tracking']
            self.assertEqual(timing['status'],'fractional_timing_refined')
            self.assertEqual(timing['phase_budget'],8)
            self.assertEqual(candidate['data_symbols']['tone_estimator'],'matched_fft_8x')
            tracking.append(timing)
        self.assertEqual(tracking[0]['selected_phase'],tracking[1]['selected_phase'])
        np.testing.assert_allclose(tracking[0]['phase_scores'],tracking[1]['phase_scores'],rtol=0,atol=1e-12)

    def test_channel_filter_is_applied_at_eight_samples_per_chip(self):
        x,fs=synchronized_preamble(sf=7,offset=47,cfo_bins=.19,data_symbols=HELLO[7])
        x=signal.resample_poly(x,4,1);fs*=4
        # At fs=8*BW resample_poly would skip its filter for a 1:1 rate.
        # This strong off-channel tone must be removed before downsampling.
        x+=2*np.exp(2j*np.pi*.3*np.arange(len(x)))
        trial=detect_lora_preamble(x,fs)
        self.assertTrue(any(f['payload_hex']==b'HELLO'.hex() for f in trial.get('frames',[])),trial)

    def test_filter_budget_abstains_without_changing_existing_alignment(self):
        samples=np.zeros(1024,complex);chirp=np.ones(128,complex)
        carrier={'status':'fractional_carrier_corrected','fractional_bin_offset':0}
        aligned,returned,timing=_refine_fractional_timing(samples,125000*4096/333,Fraction(333,4096),125000,128,0,6,chirp,1,samples,carrier)
        self.assertIs(aligned,samples)
        self.assertIs(returned,carrier)
        self.assertEqual(timing['status'],'resampler_filter_budget')

    def test_known_payload_across_sf_polarity_and_fractional_input_delay(self):
        for sf,inverted,cfo in ((7,False,.45),(8,True,-2.2),(9,False,3.3),(10,True,.19)):
            x,fs=synchronized_preamble(inverted,sf=sf,offset=47,cfo_bins=cfo,data_symbols=HELLO[sf])
            dense=signal.resample_poly(x,4,1)
            for phase in range(4):
                with self.subTest(sf=sf,inverted=inverted,phase=phase):
                    trial=detect_lora_preamble(dense[phase::4],fs)
                    frames=trial.get('frames',[])
                    self.assertEqual(len(frames),1,trial)
                    self.assertEqual(frames[0]['payload_hex'],b'HELLO'.hex())
                    candidate=next(c for c in trial['candidates'] if c['payload']['status']=='payload_crc_valid')
                    timing=candidate['timing_tracking']
                    self.assertEqual(timing['status'],'fractional_timing_refined')
                    self.assertLessEqual(timing['filter_taps'],65537)
                    self.assertGreaterEqual(timing['maximum_single_bin_energy_fraction'],.65)
                    self.assertEqual(timing['sample_grid_offset_chips'],timing['selected_phase']/8)
