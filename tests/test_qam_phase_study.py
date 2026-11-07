import unittest
import numpy as np
from iqscope_qam_soft import POINTS, bit_llrs, estimate_awgn
from scripts.qam_phase_study import (
    blind_phase_search, estimate_elliptical, elliptical_llrs,
    reference_from_prefix, residual_diagnostics, score_llrs,
    predict_awgn_errors,
)
from scripts.qam_receiver_study import slice_labels


class QamPhaseStudyTests(unittest.TestCase):
    def test_blind_tracking_recovers_independent_phase_drift(self):
        rng = np.random.default_rng(642)
        labels = rng.integers(0, 16, 6000)
        phase = .28 * np.sin(2 * np.pi * np.arange(len(labels)) / 2000)
        received = POINTS[labels] * np.exp(1j * phase)
        received += .035 * (rng.normal(size=len(labels)) + 1j * rng.normal(size=len(labels)))
        original = received.copy()
        self.assertGreater(np.count_nonzero(slice_labels(received) != labels), 100)
        for window in (31, 127, 511):
            corrected, parameters = blind_phase_search(received, window)
            np.testing.assert_array_equal(slice_labels(corrected), labels)
            # Rotation must not denoise by collapsing samples to decided points.
            np.testing.assert_allclose(abs(corrected), abs(original), atol=1e-14)
            self.assertEqual(parameters['trial_angles'], 61)
        np.testing.assert_array_equal(received, original)

    def test_covariance_fit_improves_independent_noisy_symbols(self):
        rng = np.random.default_rng(381)
        labels = rng.integers(0, 16, 10000)
        covariance = np.array([[.025, .012], [.012, .012]])
        gain = .95 * np.exp(.09j)
        noise = rng.multivariate_normal([0, 0], covariance, len(labels))
        received = gain * POINTS[labels] + noise[:, 0] + 1j * noise[:, 1]
        original = received.copy()
        # Blind fit on one sample set, predictions on independent random data.
        fitted = estimate_elliptical(received[:4000])
        circular = estimate_awgn(received[:4000])
        np.testing.assert_allclose(fitted['noise_covariance_iq'], covariance, atol=.002)
        self.assertLess(abs(complex(fitted['gain_i'], fitted['gain_q']) - gain), .015)
        mapping = np.arange(16)
        expected = ((labels[4000:, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
        elliptical = elliptical_llrs(received[4000:], mapping, fitted) < 0
        baseline = bit_llrs(received[4000:], mapping,
                            gain=complex(circular['gain_i'], circular['gain_q']),
                            noise_variance=circular['noise_variance_complex']) < 0
        self.assertLess(np.count_nonzero(elliptical != expected), np.count_nonzero(baseline != expected) / 2)
        np.testing.assert_array_equal(received, original)

    def test_circular_covariance_matches_existing_llrs(self):
        rng = np.random.default_rng(111)
        values = POINTS + .1 * (rng.normal(size=16) + 1j * rng.normal(size=16))
        mapping = rng.permutation(16)
        model = {'gain_i': .98, 'gain_q': .02, 'noise_covariance_iq': [[.03, 0], [0, .03]]}
        np.testing.assert_allclose(elliptical_llrs(values, mapping, model),
                                   bit_llrs(values, mapping, gain=.98+.02j, noise_variance=.06), atol=1e-12)

    def test_suffix_cannot_change_reference_calibration(self):
        from test_qam_prbs15 import fixture
        labels, _ = fixture()
        received = POINTS[labels].copy()
        mapping, reference = reference_from_prefix(received)
        received[512:] = POINTS[np.random.default_rng(111).integers(0, 16, len(received)-512)]
        changed_mapping, changed_reference = reference_from_prefix(received)
        np.testing.assert_array_equal(mapping, changed_mapping)
        np.testing.assert_array_equal(reference, changed_reference)
        llrs = bit_llrs(received, mapping, noise_variance=.001)
        self.assertGreater(score_llrs(llrs, reference)['evaluation_ber'], .4)
        original = received.copy()
        residual_diagnostics(received, mapping, reference)
        np.testing.assert_array_equal(received, original)

    def test_invalid_budgets_and_covariance(self):
        for values, window in ((np.ones(255), 31), (POINTS.repeat(32), 512),
                               (POINTS.repeat(32), 3), (np.full(300, np.nan), 31)):
            with self.assertRaises(ValueError):
                blind_phase_search(values, window)
        model = {'gain_i': 1, 'gain_q': 0, 'noise_covariance_iq': [[1, 2], [2, 1]]}
        with self.assertRaises(ValueError):
            elliptical_llrs(POINTS, np.arange(16), model)

    def test_model_prediction_matches_independent_monte_carlo(self):
        rng = np.random.default_rng(516)
        mapping = np.array([12, 14, 9, 8, 13, 15, 11, 10, 6, 7, 3, 1, 4, 5, 2, 0])
        coarse = predict_awgn_errors(mapping, .965, .0572, 401)
        fine = predict_awgn_errors(mapping, .965, .0572, 801)
        self.assertAlmostEqual(fine['integrated_probability_mass'], 1, places=10)
        # Grid refinement must change the prediction by less than one error
        # over the laboratory's 17904-bit verification interval.
        self.assertAlmostEqual(coarse['bit_map_error_probability'], fine['bit_map_error_probability'], delta=1/17904)
        self.assertLessEqual(fine['bit_map_error_probability'], fine['symbol_map_bit_error_probability'])
        errors = 0
        hard_errors = 0
        for _ in range(20):
            labels = rng.integers(0, 16, 10000)
            values = .965 * POINTS[labels] + np.sqrt(.0572/2) * (rng.normal(size=10000) + 1j*rng.normal(size=10000))
            truth = ((mapping[labels, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
            errors += np.count_nonzero((bit_llrs(values, mapping, gain=.965, noise_variance=.0572) < 0) != truth)
            hard_labels = slice_labels(values / .965)
            hard = ((mapping[hard_labels, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
            hard_errors += np.count_nonzero(hard != truth)
        self.assertAlmostEqual(errors / 800000, fine['bit_map_error_probability'], delta=.001)
        self.assertAlmostEqual(hard_errors / 800000, fine['symbol_map_bit_error_probability'], delta=.001)
