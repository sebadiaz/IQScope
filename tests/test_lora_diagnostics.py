import unittest
import numpy as np
from iqscope_lora import _opposite_chirp_pair, _sync_word_candidate


class LoRaFailureDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        n=np.arange(128)
        self.chirp=np.exp(1j*np.pi*(n*n/128-n))

    def test_missing_opposite_pair_reports_measured_gate(self):
        result=_opposite_chirp_pair(np.zeros(2048,dtype=complex),self.chirp,1,1024,125000,True)
        self.assertEqual(result['status'],'no_consistent_opposite_pair')
        self.assertGreater(result['examined_pairs'],0)
        self.assertEqual(result['maximum_bin_compatible_minimum_three_bin_fraction'],0)
        self.assertTrue(result['coherent_fallback_enabled'])
        self.assertEqual(result['coherent_fallback_minimum_individual_fraction'],.65)

    def test_sync_energy_rejection_is_distinct_from_bin_rejection(self):
        pair={'status':'opposite_chirp_pair_candidate','sample_start_at_chip_rate':1280,
              'dechirped_peak_bins':[0,0]}
        result=_sync_word_candidate(np.zeros(2048,dtype=complex),self.chirp,1,0,pair,125000)
        self.assertEqual(result['status'],'no_consistent_sync_word')
        self.assertGreater(result['examined_boundaries'],0)
        self.assertEqual(result['maximum_minimum_three_bin_energy_fraction'],0)
        self.assertEqual(result['energy_accepted_boundaries'],0)
        self.assertIsNone(result['minimum_maximum_symbol_bin_error'])
