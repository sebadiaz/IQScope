import itertools
import unittest
import numpy as np
from iqscope_qam_soft import POINTS, estimate_awgn, bit_llrs
from scripts.qam_receiver_study import slice_labels
from scripts.qam_sequence_study import (
    PREFIX, bcjr, posterior_llrs, fit_channel, estimate_impulsive, impulsive_llrs,
)


class QamSequenceStudyTests(unittest.TestCase):
    def test_bcjr_matches_exhaustive_sequence_probabilities(self):
        # Includes the unknown preceding symbol: 16**4 possibilities for 3 y.
        sequences = np.array(list(itertools.product(range(16), repeat=4)))
        taps = np.array([.94+.04j, .22-.06j])
        values = np.array([.37+.23j, -.12-.71j, .81-.16j])
        variance = .13
        means = taps[0]*POINTS[sequences[:, 1:]] + taps[1]*POINTS[sequences[:, :-1]]
        weights = np.exp(-np.sum(abs(values-means)**2, axis=1)/variance)
        weights /= weights.sum()
        exact = np.array([np.bincount(sequences[:, n+1], weights=weights, minlength=16) for n in range(3)])
        posterior, _ = bcjr(values, taps, variance)
        np.testing.assert_allclose(posterior, exact, rtol=1e-12, atol=1e-14)

    def test_zero_isi_is_identical_to_memoryless_likelihoods(self):
        rng = np.random.default_rng(18)
        gain = .98+.03j
        values = gain*POINTS[rng.integers(0, 16, 200)] + .08*(rng.normal(size=200)+1j*rng.normal(size=200))
        mapping = rng.permutation(16)
        posterior, _ = bcjr(values, [gain, 0], .03)
        np.testing.assert_allclose(posterior_llrs(posterior, mapping),
                                   bit_llrs(values, mapping, gain=gain, noise_variance=.03), atol=1e-12)

    def test_unknown_two_tap_channel_learned_only_on_prefix(self):
        rng = np.random.default_rng(733)
        labels = rng.integers(0, 16, 5000)
        taps = np.array([.95+.03j, .26+.07j])
        values = taps[0]*POINTS[labels] + taps[1]*np.r_[POINTS[7], POINTS[labels[:-1]]]
        values += np.sqrt(.008/2)*(rng.normal(size=len(labels))+1j*rng.normal(size=len(labels)))
        original = values.copy()
        self.assertGreater(np.count_nonzero(slice_labels(values[PREFIX:]) != labels[PREFIX:]), 500)
        for ridge in (0., .05):
            fitted = fit_channel(values, ridge=ridge)
            estimated = np.array(fitted['taps_i']) + 1j*np.array(fitted['taps_q'])
            np.testing.assert_allclose(estimated, taps, atol=.02)
            posterior, _ = bcjr(values, estimated, fitted['noise_variance_complex'])
            np.testing.assert_array_equal(np.argmax(posterior[PREFIX:], axis=1), labels[PREFIX:])
            changed = values.copy()
            changed[PREFIX:] = rng.normal(size=len(changed)-PREFIX) + 1j*rng.normal(size=len(changed)-PREFIX)
            self.assertEqual(fit_channel(changed, ridge=ridge), fitted)
        full = fit_channel(values, fit_count=None)
        self.assertEqual(full['fit_symbol_count'], len(values))
        estimated = np.array(full['taps_i']) + 1j*np.array(full['taps_q'])
        np.testing.assert_allclose(estimated, taps, atol=.02)
        np.testing.assert_array_equal(values, original)

    def test_impulsive_fit_on_independent_train_and_evaluation_symbols(self):
        rng = np.random.default_rng(280)
        labels = rng.integers(0, 16, 10000)
        variances = np.where(rng.random(len(labels)) < .08, .3, .01)
        values = .97*POINTS[labels] + np.sqrt(variances/2)*(rng.normal(size=len(labels))+1j*rng.normal(size=len(labels)))
        original = values.copy()
        model = estimate_impulsive(values[:4000])
        circular = estimate_awgn(values[:4000])
        self.assertAlmostEqual(model['gain_i'], .97, delta=.015)
        self.assertAlmostEqual(model['noise_variances_complex'][0], .01, delta=.002)
        self.assertAlmostEqual(model['component_probabilities'][1], .08, delta=.025)
        mapping = rng.permutation(16)
        expected = ((mapping[labels[4000:], None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
        mixture = impulsive_llrs(values[4000:], mapping, model)
        baseline = bit_llrs(values[4000:], mapping, gain=complex(circular['gain_i'], circular['gain_q']),
                            noise_variance=circular['noise_variance_complex'])
        # Proper probabilistic score on independent samples, including tails.
        self.assertLess(np.mean(np.logaddexp(0, (2*expected-1)*mixture)),
                        np.mean(np.logaddexp(0, (2*expected-1)*baseline)))
        np.testing.assert_array_equal(values, original)

    def test_equal_noise_components_match_existing_awgn_llrs(self):
        rng = np.random.default_rng(21)
        values = POINTS + .03*(rng.normal(size=16)+1j*rng.normal(size=16))
        model = {'gain_i': .99, 'gain_q': .01, 'noise_variances_complex': [.03, .03],
                 'component_probabilities': [.7, .3]}
        mapping = rng.permutation(16)
        np.testing.assert_allclose(impulsive_llrs(values, mapping, model),
                                   bit_llrs(values, mapping, gain=.99+.01j, noise_variance=.03), atol=1e-12)

    def test_invalid_inference_budgets(self):
        for values, taps, variance in ((np.ones(10001), [1, 0], .1), (POINTS, [1, .8], .1),
                                      (POINTS, [1, 0], 0), (np.full(20, np.nan), [1, 0], .1)):
            with self.assertRaises(ValueError):
                bcjr(values, taps, variance)
        with self.assertRaises(ValueError):
            fit_channel(POINTS)
        with self.assertRaises(ValueError):
            fit_channel(POINTS.repeat(40), iterations=9)
