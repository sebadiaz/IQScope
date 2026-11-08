import unittest
import numpy as np
from scipy import signal
from iqscope_qam_soft import POINTS
from scripts.qam_receiver_study import slice_labels
from scripts.qam_fse_study import (
    PREFIX, GUARD, raw_features, fit_prefix_filter, apply_prefix_filter,
    prefix_symbols, filtered_soft_output,
)
from test_qam import fixture


class QamFseStudyTests(unittest.TestCase):
    def test_raw_fractional_filter_recovers_independent_distorted_waveform(self):
        x, fs, labels, baud = fixture(fs=16000, baud=4000, symbol_count=2200, seed=894)
        # Unknown frequency-selective channel, before the proposed raw front end.
        received = signal.lfilter([1, .8j, 0, -.35], [1], x)
        original = received.copy()
        fit = {'baud': baud, 'symbol_count': len(labels), 'carrier_offset_hz': 273.4,
               'first_symbol_center_seconds': 3.37/fs}
        for taps in (13, 21):
            features, parameters = raw_features(received, fs, fit, taps)
            targets = POINTS[labels[:PREFIX]]
            gain = np.vdot(targets, features[:PREFIX, taps//2])/np.sum(abs(targets)**2)
            naive = features[:, taps//2]/gain
            self.assertGreater(np.count_nonzero(slice_labels(naive[PREFIX:-GUARD]) != labels[PREFIX:-GUARD]), 500)
            fitted = fit_prefix_filter(features, targets, .001)
            corrected = apply_prefix_filter(features, fitted)
            np.testing.assert_array_equal(slice_labels(corrected[PREFIX:-GUARD]), labels[PREFIX:-GUARD])
            self.assertEqual(parameters['sample_spacing_symbols'], .5)
        np.testing.assert_array_equal(received, original)

    def test_half_symbol_geometry_in_physical_time_units(self):
        for fs in (16000, 200e6):
            baud = fs/4
            tone = .3*baud
            positions = np.arange(5000)
            received = np.exp(2j*np.pi*tone*positions/fs)
            fit = {'baud': baud, 'symbol_count': 1040, 'carrier_offset_hz': 0.,
                   'first_symbol_center_seconds': 6/baud}
            features, parameters = raw_features(received, fs, fit, 7)
            ratio = features[100:-100, 1:]/features[100:-100, :-1]
            np.testing.assert_allclose(ratio, np.exp(2j*np.pi*tone/(2*baud)), atol=2e-4)
            self.assertEqual(parameters['antialias_tap_count'], 257)

    def test_prefix_only_complex_filter_and_validation(self):
        rng = np.random.default_rng(211)
        latent = POINTS[rng.integers(0, 16, (3000, 7))]
        channel = np.eye(7)+.12*(rng.normal(size=(7, 7))+1j*rng.normal(size=(7, 7)))
        features = latent@channel
        original = features.copy()
        targets = latent[:PREFIX, 0].copy()
        fitted = fit_prefix_filter(features, targets, .001)
        recovered = apply_prefix_filter(features, fitted)
        np.testing.assert_array_equal(slice_labels(recovered[PREFIX:]), slice_labels(latent[PREFIX:, 0]))
        altered = features.copy()
        altered[PREFIX:] = 3*(rng.normal(size=altered[PREFIX:].shape)+1j*rng.normal(size=altered[PREFIX:].shape))
        self.assertEqual(fit_prefix_filter(altered, targets, .001), fitted)
        self.assertEqual(fitted['fit_symbol_count'], 472)
        self.assertEqual(fitted['validation_symbol_count'], 128)
        self.assertEqual(fitted['validation_fit_symbol_count'], 264)
        self.assertEqual(fitted['validation_gap_symbols'], 80)
        gap_targets = targets.copy()
        gap_targets[304:384] *= .5j
        gap_fit = fit_prefix_filter(features, gap_targets, .001)
        self.assertEqual(gap_fit['prefix_validation_normalized_mse'], fitted['prefix_validation_normalized_mse'])
        self.assertNotEqual(gap_fit['coefficients_i'], fitted['coefficients_i'])
        np.testing.assert_array_equal(features, original)
        np.testing.assert_array_equal(targets, latent[:PREFIX, 0])
        with self.assertRaises(ValueError):
            fit_prefix_filter(features, latent[:, 0], .001)

    def test_reference_conversion_accepts_only_prefix_and_non_gray_mapping(self):
        rng = np.random.default_rng(521)
        mapping = rng.permutation(16)
        labels = rng.integers(0, 16, PREFIX)
        bits = ((mapping[labels, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
        np.testing.assert_array_equal(prefix_symbols(mapping, bits), POINTS[labels])
        with self.assertRaises(ValueError):
            prefix_symbols(mapping, np.tile(bits, 2))

    def test_identical_verification_interval_and_baseline_boundaries(self):
        rng = np.random.default_rng(88)
        labels = rng.integers(0, 16, 1500)
        values = POINTS[labels]+.025*(rng.normal(size=len(labels))+1j*rng.normal(size=len(labels)))
        baseline = rng.normal(size=4*len(labels))
        llrs, _ = filtered_soft_output(values, np.arange(16), baseline)
        np.testing.assert_array_equal(llrs[:4*GUARD], baseline[:4*GUARD])
        np.testing.assert_array_equal(llrs[-4*GUARD:], baseline[-4*GUARD:])
        truth = ((labels[:, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
        np.testing.assert_array_equal(llrs[4*GUARD:-4*GUARD]<0, truth[4*GUARD:-4*GUARD])
        self.assertEqual(len(llrs), len(baseline))

    def test_invalid_waveform_and_fit_budgets(self):
        fit = {'baud': 4000, 'symbol_count': 1100, 'carrier_offset_hz': 0.,
               'first_symbol_center_seconds': 6/4000}
        for source, fs in ((np.zeros(5000), 16000), (np.full(5000, np.nan), 16000),
                           (np.ones(5000), float('nan')), (np.ones(5000), 12000)):
            with self.assertRaises(ValueError):
                raw_features(source, fs, fit, 7)
        with self.assertRaises(ValueError):
            fit_prefix_filter(np.ones((2000, 13)), np.ones(PREFIX), 0.)
