"""Bounded research: two-tap QAM BCJR and impulsive-noise likelihoods.

No reference bits enter either estimator. All predefined methods are reported
on one frozen prefix calibration, without choosing on verification errors.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.special import logsumexp
from iqscope_qam import decode_qam16
from iqscope_qam_soft import POINTS, _samples, estimate_awgn, bit_llrs
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_receiver_study import reconstruct_symbols, slice_labels
from scripts.qam_phase_study import reference_from_prefix, score_llrs
from scripts.qam_prbs15 import ACQUISITION_BITS

PREFIX = ACQUISITION_BITS // 4
# Edge state = (previous symbol, current symbol), uniform symbol transitions.
DESIGN = np.stack(np.broadcast_arrays(POINTS[None, :], POINTS[:, None]), axis=-1)


def mapping_bits(mapping):
    mapping = np.asarray(mapping)
    if mapping.shape != (16,) or mapping.dtype.kind not in 'iu' or set(mapping.tolist()) != set(range(16)):
        raise ValueError('Expected a permutation of 0..15')
    return (mapping[:, None] >> np.arange(3, -1, -1)) & 1


def posterior_llrs(posterior, mapping):
    bits = mapping_bits(mapping)
    logs = np.log(np.maximum(posterior, 1e-300))
    result = np.column_stack([logsumexp(logs[:, bits[:, bit] == 0], axis=1)
                              - logsumexp(logs[:, bits[:, bit] == 1], axis=1) for bit in range(4)])
    return np.clip(result, -80, 80).reshape(-1)


def bcjr(values, taps, variance, *, statistics=False):
    """Exact 16-state sum-product for y[n]=h0*s[n]+h1*s[n-1]+w[n].

    Scaled probabilities, uniform unknown initial state and terminal state.
    At most 10000 x 16 x 16 branch likelihoods; no FEC or pattern prior.
    """
    values = _samples(values)
    taps = np.asarray(taps, dtype=complex)
    if (taps.shape != (2,) or not np.all(np.isfinite(taps)) or not .5 < abs(taps[0]) < 2
            or abs(taps[1]) > .5 * abs(taps[0]) or not np.isfinite(variance) or not 1e-9 <= variance <= 2):
        raise ValueError('Unbounded two-tap channel or variance')
    means = DESIGN @ taps
    logits = -abs(values[:, None, None] - means[None, :, :]) ** 2 / variance
    logits -= logits.max(axis=(1, 2), keepdims=True)
    kernels = np.exp(np.maximum(logits, -700))
    forward = np.empty((len(values) + 1, 16))
    forward[0] = 1 / 16
    for index, kernel in enumerate(kernels):
        row = forward[index] @ kernel
        forward[index + 1] = row / row.sum()
    posterior = np.empty((len(values), 16))
    backward = np.ones(16)
    joint_sum = np.zeros((16, 16))
    joint_y = np.zeros((16, 16), dtype=complex)
    for index in range(len(values) - 1, -1, -1):
        joint = forward[index, :, None] * kernels[index] * backward[None, :]
        joint /= joint.sum()
        posterior[index] = joint.sum(axis=0)
        if statistics:
            joint_sum += joint
            joint_y += joint * values[index]
        backward = kernels[index] @ backward
        backward /= backward.sum()
    stats = None
    if statistics:
        normal = np.einsum('kl,kli,klj->ij', joint_sum, DESIGN.conj(), DESIGN)
        cross = np.einsum('kl,kli->i', joint_y, DESIGN.conj())
        stats = (normal, cross)
    return posterior, stats


def fit_prefix_channel(values, ridge=.05, iterations=8):
    """Two-tap EM fit on unlabelled prefix only; no hard/PRBS targets."""
    values = _samples(values)
    if len(values) < PREFIX or ridge not in (0., .05) or not isinstance(iterations, int) or not 0 <= iterations <= 8:
        raise ValueError('Invalid prefix-fit budget')
    train = values[:PREFIX]
    initial = estimate_awgn(train)
    taps = np.array([complex(initial['gain_i'], initial['gain_q']), 0])
    variance = initial['noise_variance_complex']
    for _ in range(iterations):
        _, (normal, cross) = bcjr(train, taps, variance, statistics=True)
        penalty = np.diag([1e-8, ridge * len(train)])
        taps = np.linalg.solve(normal + penalty, cross)
        variance = max(float((np.sum(abs(train) ** 2)
                              - 2 * np.real(np.vdot(taps, cross))
                              + np.real(np.vdot(taps, normal @ taps))) / len(train)), 1e-9)
    # Reuse the inference validation even for a zero-iteration fit.
    bcjr(train[:1], taps, variance)
    return {'taps_i': taps.real.tolist(), 'taps_q': taps.imag.tolist(),
            'noise_variance_complex': variance, 'iterations': iterations,
            'postcursor_ridge_per_symbol': ridge, 'fit_symbol_count': PREFIX,
            'fit_scope': 'unlabelled first 512 symbols only; uniform independent QAM prior; no reference or decision targets'}


def estimate_impulsive(values):
    """Blind EM: common complex gain, two circular Gaussian noise components."""
    values = _samples(values)
    initial = estimate_awgn(values)
    gain = complex(initial['gain_i'], initial['gain_q'])
    variances = initial['noise_variance_complex'] * np.array([.5, 3.])
    priors = np.array([.8, .2])
    for _ in range(32):
        distance = abs(values[:, None] - gain * POINTS[None, :]) ** 2
        logits = (np.log(priors / variances)[None, None, :]
                  - distance[:, :, None] / variances[None, None, :])
        logits -= logits.max(axis=(1, 2), keepdims=True)
        weights = np.exp(logits)
        weights /= weights.sum(axis=(1, 2), keepdims=True)
        precision_weights = (weights / variances[None, None, :]).sum(axis=2)
        gain = np.sum(values * np.conj(precision_weights @ POINTS)) / np.sum(precision_weights @ abs(POINTS) ** 2)
        distance = abs(values[:, None] - gain * POINTS[None, :]) ** 2
        counts = weights.sum(axis=(0, 1))
        variances = np.maximum(np.sum(weights * distance[:, :, None], axis=(0, 1)) / counts, 1e-9)
        priors = np.clip(counts / len(values), .02, .98)
        priors /= priors.sum()
    if not .5 < abs(gain) < 2 or not np.all(np.isfinite(variances)) or variances.max() > 2:
        raise ValueError('Unbounded impulsive model')
    order = np.argsort(variances)
    return {'gain_i': float(gain.real), 'gain_q': float(gain.imag),
            'noise_variances_complex': variances[order].tolist(), 'component_probabilities': priors[order].tolist(),
            'iterations': 32, 'fit_scope': 'unlabelled supplied samples; two circular Gaussian noise components, uniform QAM prior'}


def impulsive_llrs(values, mapping, model):
    values = _samples(values)
    bits = mapping_bits(mapping)
    gain = complex(model['gain_i'], model['gain_q'])
    variances = np.asarray(model['noise_variances_complex'])
    priors = np.asarray(model['component_probabilities'])
    if (not np.isfinite(gain) or not .5 < abs(gain) < 2 or variances.shape != (2,) or priors.shape != (2,)
            or not np.all(np.isfinite(variances)) or np.any(variances <= 0)
            or not np.all(np.isfinite(priors)) or np.any(priors <= 0) or not np.isclose(priors.sum(), 1)):
        raise ValueError('Invalid impulsive-noise likelihood model')
    distance = abs(values[:, None] - gain * POINTS[None, :]) ** 2
    metrics = logsumexp(np.log(priors / variances)[None, None, :]
                        - distance[:, :, None] / variances[None, None, :], axis=2)
    result = np.column_stack([logsumexp(metrics[:, bits[:, bit] == 0], axis=1)
                             - logsumexp(metrics[:, bits[:, bit] == 1], axis=1) for bit in range(4)])
    return np.clip(result, -80, 80).reshape(-1)


def residual_distribution(values, mapping, reference):
    """Oracle diagnostics only: results must never feed either estimator."""
    nibbles = reference.reshape(-1, 4) @ (2 ** np.arange(3, -1, -1))
    expected = POINTS[np.argsort(mapping)[nibbles]]
    model = estimate_awgn(values)
    gain = complex(model['gain_i'], model['gain_q'])
    error = values[PREFIX:] - gain * expected[PREFIX:]
    error -= error.mean()
    power = float(np.mean(abs(error) ** 2))
    radial = abs(error) ** 2 / max(power, 1e-15)
    quantiles = np.array([.5, .9, .99, .999])
    return {'scope': 'known-reference suffix diagnostics only; never used for any channel/noise fit',
            'symbol_count': len(error), 'radial_fourth_moment_ratio': float(np.mean(radial ** 2)),
            'gaussian_radial_fourth_moment_ratio': 2.,
            'quantile_probabilities': quantiles.tolist(), 'normalized_radial_quantiles': np.quantile(radial, quantiles).tolist(),
            'gaussian_normalized_radial_quantiles': (-np.log1p(-quantiles)).tolist(),
            'tail_probabilities': [{'normalized_squared_radius': threshold,
                                    'observed_fraction': float(np.mean(radial > threshold)),
                                    'gaussian_fraction': float(np.exp(-threshold))} for threshold in (4, 9)],
            'reference_crosscorrelation_previous_symbol': [float(part) for part in
                (np.mean(error[1:] * np.conj(expected[PREFIX:-1])).real,
                 np.mean(error[1:] * np.conj(expected[PREFIX:-1])).imag)],
            'limits': 'finite development-corpus sample; descriptive moments and tails, not a normality proof'}


def measure(values):
    mapping, reference = reference_from_prefix(values)
    model = estimate_awgn(values)
    baseline = bit_llrs(values, mapping, gain=complex(model['gain_i'], model['gain_q']),
                        noise_variance=model['noise_variance_complex'])
    results = {'baseline_circular': dict(score_llrs(baseline, reference), model=model)}
    impulsive = estimate_impulsive(values)
    results['blind_impulsive_noise'] = dict(score_llrs(impulsive_llrs(values, mapping, impulsive), reference, baseline), model=impulsive)
    for method, ridge, iterations in (('prefix_memoryless', .05, 0), ('prefix_bcjr_ridge', .05, 8), ('prefix_bcjr_unregularized', 0., 8)):
        channel = fit_prefix_channel(values, ridge=ridge, iterations=iterations)
        taps = np.array(channel['taps_i']) + 1j * np.array(channel['taps_q'])
        posterior, _ = bcjr(values, taps, channel['noise_variance_complex'])
        results[method] = dict(score_llrs(posterior_llrs(posterior, mapping), reference, baseline), model=channel)
    return {'mapping_scope': 'baseline prefix only; frozen codebook and PN phase for every method',
            'expected_bits_sha256': hashlib.sha256(np.packbits(reference).tobytes()).hexdigest(),
            'methods': results, 'residual_distribution': residual_distribution(values, mapping, reference)}


def main():
    root = Path('corpus-cache/qam-lab')
    raw = (root / 'IQ_28_Ghz.zip').read_bytes()
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Unverified laboratory archive')
    results = {'source_url': URL, 'source_sha256': SHA256,
               'scope': 'development-corpus study, all predefined models reported; no PRBS feedback or automatic acceptance change',
               'files': {}}
    with zipfile.ZipFile(root / 'IQ_28_Ghz.zip') as archive:
        for name in sorted(archive.namelist()):
            basename = Path(name).name
            if basename not in {f'16qam {letter}.csv' for letter in 'abcdef'}:
                continue
            x, fs, _ = read_keysight_csv(archive.read(name))
            fits = []
            decoded = decode_qam16(x, fs, trial_observer=lambda fit, labels: fits.append((fit, labels)))
            fit, labels = fits[0]
            values = reconstruct_symbols(x, fs, fit)
            if not np.array_equal(slice_labels(values), labels):
                raise AssertionError('Symbol reconstruction differs from receiver')
            results['files'][basename] = dict(measure(values), generic_status=decoded['status'])
    (root / 'sequence-study.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    if set(results['files']) != {f'16qam {letter}.csv' for letter in 'abcdef'}:
        raise AssertionError('Expected six QAM captures')
    for name, capture in results['files'].items():
        for result in capture['methods'].values():
            if result['evaluation_bits'] != 17904:
                raise AssertionError('Verification interval changed')
            if name != '16qam f.csv' and result['evaluation_error_count']:
                raise AssertionError('Experiment damaged a clean reference')


if __name__ == '__main__':
    main()
