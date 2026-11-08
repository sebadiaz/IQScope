import unittest
import numpy as np
from scipy import signal
from iqscope_qam_soft import POINTS
from scripts.qam_blind_sync_study import (
    independent_timing, gardner_centers, blind_equalizer, align_prefix,
    tracked_raw_features,
)
from scripts.qam_receiver_study import slice_labels
from test_qam import fixture


class BlindSyncStudyTests(unittest.TestCase):
    def test_independent_timing_tracks_both_clock_error_signs(self):
        for ppm, seed in ((-500, 405), (500, 823)):
            x, fs, labels, actual = fixture(baud=4000, fs=16000, rolloff=.2,
                                          clock_ppm=ppm, symbol_count=5000, seed=seed)
            original = x.copy()
            output, centers, meta = independent_timing(x, fs, 4000., 273.4, 4988, .01)
            # Truth is used here only to verify an independently generated waveform.
            target = POINTS[labels[5:5+len(output)]]
            mse = min(np.mean(abs(output[1000:-100]*1j**turn-target[1000:-100])**2)
                      for turn in range(4))
            self.assertLess(mse, .004)
            self.assertAlmostEqual(meta['recovered_baud_tail_median'], actual, delta=.5)
            self.assertTrue(np.all(np.diff(centers) > 0))
            features = tracked_raw_features(x, fs, 4000., 273.4, centers)
            self.assertEqual(features.shape, (4988, 21))
            np.testing.assert_array_equal(x, original)

    def test_blind_filter_removes_unknown_isi_without_targets(self):
        rng = np.random.default_rng(225)
        labels = rng.integers(0, 16, 5000)
        symbols = POINTS[labels]
        impulses = np.zeros(2*len(symbols), complex)
        impulses[::2] = symbols
        received = signal.lfilter([1, .3+.2j, .25-.1j], [1], impulses)
        positions = 2*np.arange(len(symbols))[:, None]+np.arange(-10, 11)
        matrix = received[np.clip(positions, 0, len(received)-1)]
        original = matrix.copy()
        baseline_errors = np.count_nonzero(slice_labels(matrix[40:-40, 10]) != labels[40:-40])
        self.assertGreater(baseline_errors, 100)
        for method in ('cma', 'mcma'):
            for step in (.02, .08):
                output, meta = blind_equalizer(matrix, method, step)
                errors = min(np.count_nonzero(slice_labels(output[40:-40]*1j**turn) != labels[40:-40])
                             for turn in range(4))
                self.assertEqual(errors, 0)
                self.assertEqual(meta['coefficient_updates'], 8*(len(symbols)-80))
        np.testing.assert_array_equal(matrix, original)

    def test_alignment_uses_only_unlabelled_prefix(self):
        rng = np.random.default_rng(82)
        baseline = POINTS[rng.integers(0, 16, 1500)]
        candidate = np.conj(np.roll(baseline, 2))*1j
        aligned, meta = align_prefix(candidate, baseline)
        np.testing.assert_allclose(aligned[40:-40], baseline[40:-40], atol=1e-14)
        modified = candidate.copy()
        modified[600:] *= 2*np.exp(.3j)
        changed_baseline = baseline.copy()
        changed_baseline[600:] = 0
        self.assertEqual(align_prefix(modified, changed_baseline)[1], meta)

    def test_input_and_source_support_bounds(self):
        for values, period, count, bandwidth in ((np.zeros(10000), 8., 1100, .01),
                (np.ones(10000), 8., 10001, .01), (np.ones(10000), 8., 1100, .02),
                (np.ones(1024), 8., 1100, .01), (np.full(10000, np.nan), 8., 1100, .01)):
            with self.assertRaises(ValueError):
                gardner_centers(values, period, count, bandwidth)
        for matrix in (np.ones((1100, 13)), np.zeros((1100, 21)), np.ones((10001, 21))):
            with self.assertRaises(ValueError):
                blind_equalizer(matrix)
        with self.assertRaises(ValueError):
            tracked_raw_features(np.ones(10000), 16000., 4000., float('nan'), np.arange(1100)/4000)
