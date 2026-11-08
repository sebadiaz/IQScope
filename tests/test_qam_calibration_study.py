import copy
import unittest
import numpy as np
from scipy import signal
from iqscope_qam_soft import POINTS
from scripts.qam_receiver_study import slice_labels
from scripts.qam_fse_study import GUARD, apply_prefix_filter, soft_output
from scripts.qam_calibration_study import (
    STRONG_NAMES, WEAK_NAME, canonical_features, fit_calibration, leave_one_record_out, fit_noise_loaded,
)
from test_qam import fixture


def synthetic_record(seed, phase, quarter_turn=0, count=2000, extra_noise=0.):
    x, fs, labels, baud = fixture(fs=16000, baud=4000, symbol_count=count, seed=seed)
    x = signal.lfilter([1, .8j, 0, -.35], [1], x*np.exp(1j*phase))
    rng = np.random.default_rng(seed+95)
    x += extra_noise*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    fit = {'baud': baud, 'symbol_count': len(labels), 'carrier_offset_hz': 273.4,
           'first_symbol_center_seconds': 3.37/fs,
           'phase_origin_radians': .83+phase-quarter_turn*np.pi/2}
    matrix, _ = canonical_features(x, fs, fit, 21)
    # The blind receiver may choose a different quadrant for each recording.
    targets = POINTS[labels]*np.exp(1j*quarter_turn*np.pi/2)
    return matrix, targets


class QamCalibrationStudyTests(unittest.TestCase):
    def test_filter_transfers_to_independent_waveform_with_different_phase(self):
        records = {name: synthetic_record(700+i, phase, i-2)
                   for i, (name, phase) in enumerate(zip(STRONG_NAMES, (-.7, .2, 1.7, -2.1, 2.8)))}
        fitted = fit_calibration(records, .001)
        frozen = copy.deepcopy(fitted)
        weak, truth = synthetic_record(1008, -1.8, -1, count=2200, extra_noise=.06)
        output = apply_prefix_filter(weak, fitted)
        llrs, _ = soft_output(output[GUARD:-GUARD], np.arange(16))
        labels = slice_labels(truth[GUARD:-GUARD])
        expected = ((labels[:, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
        np.testing.assert_array_equal(llrs<0, expected)
        self.assertEqual(fitted, frozen)
        self.assertEqual(fitted['fit_symbol_count'], 5*(2000-2*GUARD))
        self.assertNotIn(WEAK_NAME, fitted['calibration_files'])

    def test_canonical_phase_alignment_without_reference_symbols(self):
        x, fs, labels, baud = fixture(fs=16000, baud=4000, symbol_count=1200)
        fit = {'baud': baud, 'symbol_count': len(labels), 'carrier_offset_hz': 273.4,
               'first_symbol_center_seconds': 3.37/fs, 'phase_origin_radians': .83}
        first, _ = canonical_features(x, fs, fit, 13)
        changed = dict(fit, phase_origin_radians=fit['phase_origin_radians']+.41)
        second, _ = canonical_features(x*np.exp(.41j), fs, changed, 13)
        np.testing.assert_allclose(first, second, atol=2e-14)

    def test_entire_held_out_record_is_excluded_from_its_filter(self):
        rng = np.random.default_rng(655)
        records = {}
        channel = np.eye(7)+.07*(rng.normal(size=(7, 7))+1j*rng.normal(size=(7, 7)))
        for name in STRONG_NAMES[:3]:
            latent = POINTS[rng.integers(0, 16, (1200, 7))]
            records[name] = (latent@channel, latent[:, 0])
        first = leave_one_record_out(records, .001)
        held_out = STRONG_NAMES[0]
        for name, fold in first['folds'].items():
            self.assertNotIn(name, fold['filter']['calibration_files'])
            self.assertEqual(fold['filter']['fit_symbol_count'], 2*(1200-2*GUARD))
            self.assertLess(fold['normalized_mse'], .0001)
        altered = dict(records)
        altered[held_out] = (records[held_out][0], POINTS[rng.integers(0, 16, 1200)])
        second = leave_one_record_out(altered, .001)
        self.assertEqual(first['folds'][held_out]['filter'], second['folds'][held_out]['filter'])
        self.assertGreater(second['folds'][held_out]['normalized_mse'], 1.)

    def test_deterministic_order_and_no_input_mutation(self):
        rng = np.random.default_rng(338)
        records = {}
        for name in STRONG_NAMES[:2]:
            targets = POINTS[rng.integers(0, 16, 1200)]
            matrix = targets[:, None]*np.exp(.1j*np.arange(7))[None, :]
            matrix += .01*(rng.normal(size=matrix.shape)+1j*rng.normal(size=matrix.shape))
            records[name] = (matrix, targets)
        original = copy.deepcopy(records)
        first = fit_calibration(records, .01)
        second = fit_calibration(dict(reversed(list(records.items()))), .01)
        self.assertEqual(first, second)
        for name in records:
            for actual, expected in zip(records[name], original[name]):
                np.testing.assert_array_equal(actual, expected)

    def test_weak_record_and_invalid_budgets_are_rejected(self):
        record = (np.ones((1200, 7), dtype=complex), np.ones(1200, dtype=complex))
        with self.assertRaises(ValueError):
            fit_calibration({WEAK_NAME: record}, .01)
        with self.assertRaises(ValueError):
            fit_calibration({STRONG_NAMES[0]: record}, 0.)
        with self.assertRaises(ValueError):
            fit_calibration({STRONG_NAMES[0]: (record[0], np.ones(1199))}, .01)
        with self.assertRaises(ValueError):
            fit_calibration({STRONG_NAMES[0]: (np.full((1200, 7), np.nan), record[1])}, .01)
        with self.assertRaises(ValueError):
            leave_one_record_out({STRONG_NAMES[0]: record}, .01)

    def test_noise_loading_improves_independent_target_without_target_labels(self):
        rng = np.random.default_rng(776)
        labels = rng.integers(0, 16, 5000)
        symbols = POINTS[labels]
        variance = np.array([.02, .04, .08, .3, 1., 2., 4.])
        def noise(count):
            return (rng.normal(size=(count, 7))+1j*rng.normal(size=(count, 7)))*np.sqrt(variance/2)
        measured_noise = noise(6000)
        covariance = measured_noise.conj().T@measured_noise/len(measured_noise)
        source = np.sqrt(1-1e-6)*symbols[:, None]+.001*noise(len(symbols))
        records = {STRONG_NAMES[0]: (source, symbols)}
        ordinary = fit_calibration(records, .001)
        fitted = fit_noise_loaded(records, {STRONG_NAMES[0]: 1e6}, 2., 1., covariance, .001)
        scaled = fit_noise_loaded(records, {STRONG_NAMES[0]: 9e6}, 18., 9., covariance, .001)
        np.testing.assert_allclose(scaled['coefficients_i'], fitted['coefficients_i'], atol=1e-12)
        np.testing.assert_allclose(scaled['coefficients_q'], fitted['coefficients_q'], atol=1e-12)
        # Target data and labels are created only AFTER the filter is fixed.
        frozen = copy.deepcopy(fitted)
        labels = rng.integers(0, 16, 6000)
        target = np.sqrt(.5)*POINTS[labels, None]+np.sqrt(.5)*noise(len(labels))
        expected = ((labels[:, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
        old, _ = soft_output(apply_prefix_filter(target, ordinary), np.arange(16))
        new, _ = soft_output(apply_prefix_filter(target, fitted), np.arange(16))
        self.assertGreater(np.count_nonzero((old<0) != expected), 100)
        self.assertLess(np.count_nonzero((new<0) != expected), np.count_nonzero((old<0) != expected)/4)
        self.assertEqual(fitted, frozen)
        self.assertEqual(fitted['target_signal_fraction'], .5)

    def test_noise_loading_rejects_inconsistent_power_and_covariance(self):
        record = (np.ones((1200, 7), dtype=complex), np.ones(1200, dtype=complex))
        records = {STRONG_NAMES[0]: record}
        for target_power, noise_power, covariance in ((1., 2., np.eye(7)),
                                                       (2., 1., -np.eye(7)),
                                                       (2., 1., np.full((7, 7), np.nan))):
            with self.assertRaises(ValueError):
                fit_noise_loaded(records, {STRONG_NAMES[0]: 1e6}, target_power, noise_power, covariance, .001)
        with self.assertRaises(ValueError):
            fit_noise_loaded({WEAK_NAME: record}, {WEAK_NAME: 1e6}, 2., 1., np.eye(7), .001)
