import unittest
import numpy as np
from scripts.qam_receiver_study import affine_em, circular_em, slice_labels, reconstruct_symbols, variants, POINTS
from iqscope_qam import decode_qam16
from test_qam import fixture


class QamReceiverStudyTests(unittest.TestCase):
    def test_blind_gain_phase_and_noise_from_unlabelled_samples(self):
        rng=np.random.default_rng(228)
        labels=rng.integers(0,16,6000)
        gain=.88*np.exp(.21j)
        noise=.035*(rng.normal(size=len(labels))+1j*rng.normal(size=len(labels)))
        received=gain*POINTS[labels]+noise
        original=received.copy()
        corrected,parameters=circular_em(received)
        np.testing.assert_array_equal(received,original)
        np.testing.assert_array_equal(slice_labels(corrected),labels)
        estimated=parameters['gain_i']+1j*parameters['gain_q']
        self.assertLess(abs(estimated-gain),.005)
        self.assertAlmostEqual(parameters['noise_variance_complex'],2*.035**2,delta=.0002)
    def test_physical_time_reconstruction_matches_decisions(self):
        for fs,baud,offset in ((16000,617,273.4),(200e6,50e6,1e6)):
            x,_,_,_=fixture(fs=fs,baud=baud,offset=offset)
            observed=[]
            decode_qam16(x,fs,trial_observer=lambda fit,labels:observed.append((fit,labels)))
            fit,labels=observed[0]
            np.testing.assert_array_equal(slice_labels(reconstruct_symbols(x,fs,fit)),labels)

    def test_affine_channel_recovered_without_reference_labels(self):
        rng=np.random.default_rng(204)
        labels=rng.integers(0,16,3000)
        points=POINTS[labels]
        source=np.column_stack((points.real,points.imag))
        received=source@np.array([[1.2,.08],[-.06,.78]])+np.array([.07,-.05])
        received+=.025*rng.normal(size=received.shape)
        values=received[:,0]+1j*received[:,1]
        self.assertGreater(np.count_nonzero(slice_labels(values)!=labels),0)
        corrected,_=affine_em(values)
        np.testing.assert_array_equal(slice_labels(corrected),labels)

    def test_evaluation_suffix_never_fits_corrections(self):
        rng=np.random.default_rng(77)
        values=POINTS[rng.integers(0,16,3000)]+.05*(rng.normal(size=3000)+1j*rng.normal(size=3000))
        original=values.copy()
        first=list(variants(values))
        np.testing.assert_array_equal(values,original)
        values[512:]=.3*(rng.normal(size=2488)+1j*rng.normal(size=2488))
        second=list(variants(values))
        for (a,_,parameters),(b,_,changed) in zip(first,second):
            self.assertEqual(a,b)
            self.assertEqual(parameters,changed)
        self.assertFalse(np.array_equal(values,original))
