import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

scripts=Path(__file__).parents[1]/'scripts'
with patch.object(sys,'path',[str(scripts)]+sys.path):
    from lora_sync_gate import evaluate_sync_spectra


def spectra(polarity=1):
    result=np.ones((3,128))
    for row,symbol in enumerate((0,72,48)):
        result[row,(10+polarity*symbol)%128]=100
    return result


class AlphabetSyncResearchTests(unittest.TestCase):
    def test_legal_alphabet_in_both_polarities_is_recognized(self):
        for polarity in (-1,1):
            for model in ('global','local','pooled_local'):
                result=evaluate_sync_spectra(spectra(polarity),polarity,model)
                self.assertEqual(result['status'],'score_gate_passed')
                self.assertEqual(result['value_hex'],'96')
                self.assertEqual(result['symbol_bin_errors'],[0,0])

    def test_equal_legal_choices_and_off_alphabet_peaks_are_rejected(self):
        p=spectra();p[1,(10+80)%128]=100
        self.assertEqual(evaluate_sync_spectra(p)['status'],'score_gate_rejected')
        p=spectra();p[1]=1;p[1,13]=100
        self.assertEqual(evaluate_sync_spectra(p)['status'],'score_gate_rejected')

    def test_gain_does_not_change_research_decisions(self):
        for model in ('global','local','pooled_local'):
            baseline=evaluate_sync_spectra(spectra(),noise_model=model)
            for gain in (1e-200,1e200):
                result=evaluate_sync_spectra(spectra()*gain,noise_model=model)
                self.assertEqual(result['status'],baseline['status'])
                self.assertEqual(result['value_hex'],baseline['value_hex'])
                self.assertAlmostEqual(result['relative_word_score_mass'],baseline['relative_word_score_mass'])

    def test_preamble_continuation_is_an_explicit_counterexample(self):
        p=np.ones((3,128));p[:,0]=100
        for model in ('global','local','pooled_local'):
            result=evaluate_sync_spectra(p,noise_model=model)
            self.assertEqual(result['status'],'score_gate_passed')
            self.assertEqual(result['value_hex'],'00')
        # These scores alone therefore cannot establish the packet boundary.

    def test_noise_and_invalid_input(self):
        rng=np.random.default_rng(1001)
        for _ in range(16):
            self.assertEqual(evaluate_sync_spectra(rng.exponential(size=(3,128)))['status'],'score_gate_rejected')
        for p in (np.ones((2,128)),np.full((3,128),np.nan),-np.ones((3,128))):
            with self.assertRaises(ValueError):evaluate_sync_spectra(p)
