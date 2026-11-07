import hashlib
import unittest
import numpy as np
from scipy import signal
from scripts.qam_prbs15 import check_prbs15, prbs15_period


def fixture(reverse=False,errors=()):
    # Independent SciPy LFSR; the measurement uses an explicit recurrence.
    pn,_=signal.max_len_seq(15,taps=[14])
    if reverse:pn=pn[::-1]
    bits=pn[(12911+np.arange(12800))%32767].astype(np.uint8)
    bits[list(errors)]^=1
    groups=bits.reshape(-1,4)
    # Interleaved bit significance, Gray axes and an inverted bit.
    words=groups^np.array([1,0,0,0],dtype=np.uint8)
    gray_inverse=np.array([0,1,3,2],dtype=np.uint8)
    i=gray_inverse[2*words[:,0]+words[:,2]]
    q=gray_inverse[2*words[:,3]+words[:,1]]
    return 4*i+q,bits


class QamPrbs15Tests(unittest.TestCase):
    def test_full_period_and_independent_lfsr_recovery(self):
        pn=prbs15_period()
        self.assertEqual(len(pn),32767)
        self.assertEqual(int(pn.sum()),16384)
        for reverse in (False,True):
            labels,bits=fixture(reverse)
            r=check_prbs15(labels)
            self.assertEqual(r['status'],'prbs15_consistent',r)
            self.assertEqual(r['acquisition_error_count'],0)
            self.assertEqual(r['evaluation_error_count'],0)
            self.assertEqual(r['recovered_bits_sha256'],hashlib.sha256(np.packbits(bits).tobytes()).hexdigest())
            self.assertEqual(r['recovered_bits_sha256'],r['predicted_bits_sha256'])

    def test_bit_errors_counted_on_disjoint_suffix(self):
        labels,bits=fixture(errors=(273,4097,10505))
        r=check_prbs15(labels)
        self.assertEqual(r['status'],'prbs15_consistent',r)
        self.assertEqual(r['acquisition_error_count'],1)
        self.assertEqual(r['evaluation_error_count'],2)
        self.assertAlmostEqual(r['evaluation_ber'],2/(len(bits)-2048))

    def test_evaluation_suffix_cannot_choose_fit(self):
        labels,_=fixture()
        original=check_prbs15(labels)
        labels[512:]=np.random.default_rng(38).integers(0,16,len(labels)-512)
        r=check_prbs15(labels)
        self.assertEqual(r['status'],'no_consistent_prbs15')
        for key in ('phase_index','canonical_sequence_reversed','label_to_nibble','acquisition_error_count'):
            self.assertEqual(r[key],original[key])
        self.assertGreater(r['evaluation_ber'],.4)

    def test_unrelated_data_invalid_inputs_and_budget(self):
        labels=np.random.default_rng(493).integers(0,16,12000)
        r=check_prbs15(labels)
        self.assertEqual(r['status'],'no_consistent_prbs15')
        self.assertTrue(r['symbol_budget_reached'])
        self.assertEqual(r['analyzed_symbols'],10000)
        self.assertEqual(check_prbs15(labels[:100])['status'],'not_enough_bits')
        for invalid in ([16]*1024,[-1]*1024,[1.5]*1024,[[0]*16]*64):
            with self.assertRaises(ValueError):check_prbs15(invalid)
