import unittest
import numpy as np
from iqscope_qam_soft import POINTS, bit_llrs, estimate_awgn


class QamSoftTests(unittest.TestCase):
    def test_bit_marginals_improve_noisy_non_gray_decisions(self):
        rng=np.random.default_rng(849)
        labels=rng.integers(0,16,10000)
        mapping=np.array([0,2,5,4,1,3,7,6,10,11,15,13,8,9,14,12])
        variance=.25
        values=POINTS[labels]+np.sqrt(variance/2)*(rng.normal(size=len(labels))+1j*rng.normal(size=len(labels)))
        expected=((mapping[labels,None]>>np.arange(3,-1,-1))&1).reshape(-1)
        nearest=np.argmin(abs(values[:,None]-POINTS),axis=1)
        hard=((mapping[nearest,None]>>np.arange(3,-1,-1))&1).reshape(-1)
        soft=(bit_llrs(values,mapping,noise_variance=variance)<0)
        self.assertLess(np.count_nonzero(soft!=expected),np.count_nonzero(hard!=expected))

    def test_llr_sign_order_saturation_and_codebook(self):
        labels=np.arange(16)
        llrs=bit_llrs(POINTS,noise_variance=.00001)
        expected=((labels[:,None]>>np.arange(3,-1,-1))&1).reshape(-1)
        np.testing.assert_array_equal(llrs<0,expected.astype(bool))
        np.testing.assert_array_equal(bit_llrs(POINTS,15-labels,noise_variance=.00001),-llrs)
        self.assertTrue(np.all(np.isfinite(llrs)))
        self.assertLessEqual(np.max(abs(llrs)),80)
        with self.assertRaises(ValueError):bit_llrs(POINTS,[0]*16)
        with self.assertRaises(ValueError):bit_llrs(POINTS,noise_variance=0)
        with self.assertRaises(ValueError):estimate_awgn(np.ones(10001))
