import unittest
import numpy as np
from scipy import signal
from iqscope_qam_soft import POINTS
from scripts.qam_blind_sync_study import align_prefix
from scripts.qam_receiver_study import slice_labels
from scripts.qam_blind_objective_study import (
    TAPS, GUARD, objective, corrected_mcma, batch_equalizer, stage_output,
    project_baseline, noise_corrected_equalizer,
)


class BlindObjectiveStudyTests(unittest.TestCase):
    def test_complex_gradients_against_independent_real_differences(self):
        rng = np.random.default_rng(709)
        matrix = .1*(rng.normal(size=(1100, TAPS))+1j*rng.normal(size=(1100, TAPS)))
        vector = .04*rng.normal(size=2*TAPS)
        anchor = .03*(rng.normal(size=TAPS)+1j*rng.normal(size=TAPS))
        weights = rng.uniform(.5, 1.5, len(matrix)); weights /= weights.sum()
        functions = []
        for stage in ('mcma', 'rde'):
            functions.append(lambda v, stage=stage: objective(matrix, v, stage, weights, anchor, .1))
        functions.append(lambda v: corrected_mcma(matrix, v, .005*np.eye(TAPS)))
        for function in functions:
            _, analytic = function(vector)
            numeric = np.empty_like(vector)
            for index in range(len(vector)):
                delta = np.zeros_like(vector); delta[index] = 1e-6
                numeric[index] = (function(vector+delta)[0]-function(vector-delta)[0])/2e-6
            np.testing.assert_allclose(analytic, numeric, atol=1e-9, rtol=1e-5)

    def test_gaussian_correction_removes_population_moment_bias(self):
        rng = np.random.default_rng(810)
        count = 10000
        clean = POINTS[rng.integers(0, 16, count)]
        noise_variance = .15
        noisy = clean+np.sqrt(noise_variance/2)*(rng.normal(size=count)+1j*rng.normal(size=count))
        matrix = np.zeros((count, TAPS), complex); matrix[:, 10] = noisy
        vector = np.zeros(2*TAPS); vector[10] = 1
        covariance = np.zeros((TAPS, TAPS)); covariance[10, 10] = noise_variance
        corrected = corrected_mcma(matrix, vector, covariance)[0]
        clean_cost = .25*np.mean((clean.real**2-.82)**2+(clean.imag**2-.82)**2)
        uncorrected = .25*np.mean((noisy.real**2-.82)**2+(noisy.imag**2-.82)**2)
        self.assertLess(abs(corrected-clean_cost), .01)
        self.assertGreater(abs(uncorrected-clean_cost), .02)

    def test_batch_recovers_isi_and_preserves_inputs(self):
        rng = np.random.default_rng(225)
        labels = rng.integers(0, 16, 5000)
        impulses = np.zeros(2*len(labels), complex); impulses[::2] = POINTS[labels]
        received = signal.lfilter([1, .3+.2j, .25-.1j], [1], impulses)
        positions = 2*np.arange(len(labels))[:, None]+np.arange(-10, 11)
        matrix = received[np.clip(positions, 0, len(received)-1)]
        original = matrix.copy()
        self.assertGreater(np.count_nonzero(slice_labels(matrix[40:-40, 10]) != labels[40:-40]), 100)
        for weighted in (False, True):
            fit = batch_equalizer(matrix, weighted=weighted)
            output = stage_output(matrix, fit, 'rde')
            output, _ = align_prefix(output, POINTS[labels])
            np.testing.assert_array_equal(slice_labels(output[40:-40]), labels[40:-40])
            for parameters in fit['stages'].values():
                self.assertLessEqual(parameters['final_objective'], parameters['initial_objective']+1e-10)
        np.testing.assert_array_equal(matrix, original)

    def test_noise_correction_obeys_output_trust_and_scale(self):
        rng = np.random.default_rng(542)
        matrix = POINTS[rng.integers(0, 16, (1600, TAPS))]
        matrix += .15*(rng.normal(size=matrix.shape)+1j*rng.normal(size=matrix.shape))
        baseline = matrix[:, 10]
        initial, _ = project_baseline(matrix, baseline)
        original = matrix.copy(); original_initial = initial.copy()
        results = []
        for scale in (1., 3.):
            output, fit = noise_corrected_equalizer(matrix*scale, .045*scale**2*np.eye(TAPS), initial/scale)
            c = np.array(fit['coefficients_i'])+1j*np.array(fit['coefficients_q'])
            difference = matrix[GUARD:-GUARD]*scale@(c-initial/scale)
            self.assertLessEqual(np.mean(abs(difference)**2), .05**2*np.mean(abs(baseline[GUARD:-GUARD])**2)+1e-8)
            self.assertLessEqual(fit['final_objective'], fit['initial_objective']+1e-10)
            results.append(output)
        np.testing.assert_allclose(results[0], results[1], atol=.003)
        np.testing.assert_array_equal(matrix, original)
        np.testing.assert_array_equal(initial, original_initial)

    def test_invalid_budgets_and_covariances(self):
        initial = np.zeros(TAPS, complex); initial[10] = 1.
        matrix = np.ones((1100, TAPS), complex)
        for bad in (np.ones((1100, 13)), np.zeros((1100, TAPS)), np.ones((10001, TAPS))):
            with self.assertRaises(ValueError):
                batch_equalizer(bad)
        for covariance in (-np.eye(TAPS), np.ones((13, 13)), np.full((TAPS, TAPS), np.nan), 2*np.eye(TAPS)):
            with self.assertRaises(ValueError):
                noise_corrected_equalizer(matrix, covariance, initial)
        with self.assertRaises(ValueError):
            batch_equalizer(matrix, strength=.1)

    def test_alignment_covers_filter_delay_without_suffix_feedback(self):
        rng = np.random.default_rng(993)
        baseline = POINTS[rng.integers(0, 16, 1500)]
        for delay in (-5, 5):
            candidate = np.conj(np.roll(baseline, delay))*1j
            aligned, metadata = align_prefix(candidate, baseline, max_symbol_lag=6)
            np.testing.assert_allclose(aligned[40:-40], baseline[40:-40], atol=1e-14)
            self.assertEqual(metadata['symbol_lag'], delay)
            altered = candidate.copy()
            altered[600:] *= np.exp(.9j)
            self.assertEqual(align_prefix(altered, baseline, max_symbol_lag=6)[1], metadata)
        with self.assertRaises(ValueError):
            align_prefix(baseline, baseline, max_symbol_lag=9)
