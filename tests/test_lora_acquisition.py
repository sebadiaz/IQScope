import unittest
import numpy as np
from iqscope_lora import _phase_grid_preamble_run,_coherent_preamble_run,detect_lora_preamble


def upchirp(length):
    n=np.arange(length)
    return np.exp(1j*np.pi*(n*n/length-n))


def trial(matrix,up):
    transformed=np.fft.fft(matrix*up.conj(),axis=1)
    return _phase_grid_preamble_run(matrix,transformed,up,1)


class LoRaPhaseAcquisitionTests(unittest.TestCase):
    def test_weak_six_chirps_without_legacy_coherence_are_discovered(self):
        up=upchirp(128);rng=np.random.default_rng(817)
        x=np.tile(up,6)*np.exp(2j*np.pi*.37*np.arange(768)/128)
        x+=1.8*(rng.normal(size=768)+1j*rng.normal(size=768))
        matrix=x.reshape(6,128);z=np.fft.fft(matrix*up.conj(),axis=1)
        power=abs(z)**2;peaks=power.argmax(axis=1)
        energy=sum(power[np.arange(6),(peaks+d)%128] for d in (-1,0,1))/power.sum(axis=1)
        self.assertIsNone(_coherent_preamble_run(matrix,peaks,energy,up,1)[0])
        candidate,stats=trial(matrix,up)
        self.assertIsNotNone(candidate)
        self.assertEqual(stats['phase_hypotheses'],48)
        self.assertGreaterEqual(candidate['evidence']['matched_amplitude_phase_concentration'],.65)
        result=detect_lora_preamble(np.r_[x,np.zeros(256)],125000)
        self.assertTrue(result['candidates'])
        self.assertNotIn('frames',result)

    def test_inconsistent_chirp_phases_do_not_match_a_phase_progression(self):
        up=upchirp(128)
        phases=np.r_[0,np.cumsum(2*np.pi*np.arange(5)/5)]
        candidate,_=trial(np.exp(1j*phases[:,None])*up,up)
        self.assertIsNone(candidate)

    def test_noise_tone_and_periodic_wideband_waveform_abstain(self):
        up=upchirp(128)
        for seed in range(16):
            rng=np.random.default_rng(830+seed)
            noise=rng.normal(size=(40,128))+1j*rng.normal(size=(40,128))
            periodic=np.tile(noise[0],(40,1))
            for matrix in (noise,periodic,np.ones((40,128),complex)):
                self.assertIsNone(trial(matrix,up)[0])

    def test_phase_search_has_a_fixed_window_budget(self):
        up=upchirp(128)
        candidate,stats=trial(np.tile(up,(80,1)),up)
        self.assertIsNotNone(candidate)
        self.assertEqual(stats['checked_windows'],32)
        self.assertTrue(stats['budget_reached'])
        self.assertEqual(stats['eligible_windows'],75)
