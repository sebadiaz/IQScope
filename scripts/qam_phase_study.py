"""Offline QAM phase/noise experiments; reference bits only score frozen outputs.

Research tooling, deliberately separate from automatic candidate acceptance.
All phase windows are reported; none is selected using verification bits.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.special import logsumexp, ndtr
from iqscope_qam import decode_qam16
from iqscope_qam_soft import POINTS, _samples, estimate_awgn, bit_llrs
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_prbs15 import check_prbs15, prbs15_period, ACQUISITION_BITS
from scripts.qam_receiver_study import reconstruct_symbols, slice_labels


def blind_phase_search(values, window=127):
    """Bounded local phase search with each target excluded from its own cost.

    Uses future as well as past neighbours: this is an offline experiment,
    not a causal realtime tracker. No reference labels enter the search.
    """
    values = _samples(values)
    if len(values) < 256 or not isinstance(window, int) or window % 2 != 1 or not 9 <= window <= 511:
        raise ValueError('Expected at least 256 symbols and an odd window in 9..511')
    model = estimate_awgn(values)
    gain = model['gain_i'] + 1j * model['gain_q']
    normalized = values / gain
    angles = np.linspace(-.3, .3, 61)
    costs = np.empty((len(angles), len(values)))
    for index, angle in enumerate(angles):
        rotated = normalized * np.exp(-1j * angle)
        residual = abs(rotated - POINTS[slice_labels(rotated)]) ** 2
        # Boundary windows contain fewer neighbours, equally for every angle.
        costs[index] = window * uniform_filter1d(residual, window, mode='constant') - residual
    phase = angles[np.argmin(costs, axis=0)]
    output = values * np.exp(-1j * (phase + np.angle(gain)))
    return output, {
        'window_symbols': window, 'trial_angles': len(angles), 'search_radius_radians': .3,
        'phase_std_radians': float(np.std(phase)), 'phase_max_abs_radians': float(np.max(abs(phase))),
        'search_boundary_fraction': float(np.mean(abs(phase) >= .3)),
        'constant_phase_radians': float(np.angle(gain)),
        'fit_scope': 'unlabelled full window; offline neighbour costs exclude the target symbol; no PRBS feedback',
    }


def estimate_elliptical(values):
    """Blind uniform-QAM EM: complex gain and full real 2x2 noise covariance."""
    values = _samples(values)
    initial = estimate_awgn(values)
    gain = np.array([initial['gain_i'], initial['gain_q']])
    covariance = np.eye(2) * initial['noise_variance_complex'] / 2
    observations = np.column_stack((values.real, values.imag))
    # Complex multiplication by each constellation point, as real matrices.
    design = np.array([[[p.real, -p.imag], [p.imag, p.real]] for p in POINTS])
    for _ in range(32):
        precision = np.linalg.inv(covariance)
        residual = observations[:, None, :] - (design @ gain)[None, :, :]
        logits = -.5 * np.einsum('nki,ij,nkj->nk', residual, precision, residual)
        weights = np.exp(logits - logits.max(axis=1, keepdims=True))
        weights /= weights.sum(axis=1, keepdims=True)
        normals = np.einsum('kai,ab,kbj->kij', design, precision, design)
        normal = np.einsum('k,kij->ij', weights.sum(axis=0), normals)
        cross = np.einsum('kai,ab,kb->i', design, precision, weights.T @ observations)
        gain = np.linalg.solve(normal, cross)
        residual = observations[:, None, :] - (design @ gain)[None, :, :]
        covariance = np.einsum('nk,nki,nkj->ij', weights, residual, residual) / len(values)
        covariance += 1e-9 * np.eye(2)
    if not .5 < np.linalg.norm(gain) < 2 or np.linalg.cond(covariance) > 10:
        raise ValueError('Unbounded gain or noise covariance')
    return {'gain_i': float(gain[0]), 'gain_q': float(gain[1]),
            'noise_covariance_iq': covariance.tolist(), 'covariance_condition': float(np.linalg.cond(covariance)),
            'iterations': 32, 'fit_scope': 'unlabelled supplied samples; uniform QAM, constant complex gain, elliptical Gaussian noise'}


def elliptical_llrs(values, mapping, model):
    values = _samples(values)
    mapping = np.asarray(mapping)
    if mapping.shape != (16,) or mapping.dtype.kind not in 'iu' or set(mapping.tolist()) != set(range(16)):
        raise ValueError('Expected a permutation of 0..15')
    covariance = np.asarray(model['noise_covariance_iq'], dtype=float)
    if (covariance.shape != (2, 2) or not np.all(np.isfinite(covariance))
            or not np.allclose(covariance, covariance.T) or np.linalg.eigvalsh(covariance)[0] <= 0):
        raise ValueError('Expected positive definite noise covariance')
    gain = complex(model['gain_i'], model['gain_q'])
    if not np.isfinite(gain) or not .5 < abs(gain) < 2:
        raise ValueError('Invalid complex gain')
    residual = values[:, None] - gain * POINTS[None, :]
    delta = np.stack((residual.real, residual.imag), axis=-1)
    logits = -.5 * np.einsum('nki,ij,nkj->nk', delta, np.linalg.inv(covariance), delta)
    bits = (mapping[:, None] >> np.arange(3, -1, -1)) & 1
    llrs = np.column_stack([logsumexp(logits[:, bits[:, b] == 0], axis=1)
                           - logsumexp(logits[:, bits[:, b] == 1], axis=1) for b in range(4)])
    return np.clip(llrs, -80, 80).reshape(-1)


def reference_from_prefix(values):
    """Known-source calibration. Only the first 2048 bits acquire the mapping."""
    acquired = check_prbs15(slice_labels(values))
    if not acquired.get('mapping_is_bijective') or acquired.get('acquisition_error_count', ACQUISITION_BITS) > .1 * ACQUISITION_BITS:
        raise ValueError('No valid prefix acquisition')
    mapping = np.array(acquired['label_to_nibble'])
    pn = prbs15_period()
    if acquired['canonical_sequence_reversed']:
        pn = pn[::-1]
    reference = pn[(acquired['phase_index'] + np.arange(4 * len(values))) % len(pn)]
    return mapping, reference


def score_llrs(llrs, reference, baseline=None):
    predicted = np.asarray(llrs) < 0
    if predicted.shape != reference.shape:
        raise ValueError('Verification interval changed')
    wrong = predicted[ACQUISITION_BITS:] != reference[ACQUISITION_BITS:]
    result = {'evaluation_bits': len(wrong), 'evaluation_error_count': int(np.count_nonzero(wrong)),
              'evaluation_ber': float(np.mean(wrong))}
    if baseline is not None:
        old_wrong = (baseline[ACQUISITION_BITS:] < 0) != reference[ACQUISITION_BITS:]
        result.update(errors_corrected=int(np.count_nonzero(old_wrong & ~wrong)),
                      new_errors_introduced=int(np.count_nonzero(~old_wrong & wrong)))
    return result


def residual_diagnostics(values, mapping, reference):
    """Reference-assisted diagnostics ONLY. Never returned as a correction."""
    inverse = np.argsort(mapping)
    nibbles = reference.reshape(-1, 4) @ (2 ** np.arange(3, -1, -1))
    expected = POINTS[inverse[nibbles]]
    model = estimate_awgn(values)
    gain = complex(model['gain_i'], model['gain_q'])
    observed = values[ACQUISITION_BITS // 4:]
    ideal = gain * expected[ACQUISITION_BITS // 4:]
    error = observed - ideal
    error -= error.mean()
    power = float(np.mean(abs(error) ** 2))
    covariance = np.cov(np.vstack((error.real, error.imag)), bias=True)
    blocks = len(error) // 128
    obs = observed[:blocks * 128].reshape(blocks, 128)
    exp = ideal[:blocks * 128].reshape(blocks, 128)
    phase = np.angle(np.sum(obs * np.conj(exp), axis=1))
    return {'scope': 'known-reference diagnostics on verification suffix only; never fed into waveform or likelihood fit',
            'complex_residual_power': power, 'covariance_iq': covariance.tolist(),
            'covariance_condition': float(np.linalg.cond(covariance)),
            'lag_correlations': [{'lag_symbols': lag,
                                  'real': float(np.real(corr)), 'imag': float(np.imag(corr))}
                                 for lag in range(1, 9)
                                 for corr in [np.mean(error[lag:] * np.conj(error[:-lag])) / max(power, 1e-15)]],
            'phase_block_symbols': 128, 'phase_block_count': blocks,
            'phase_block_std_radians': float(np.std(phase)),
            'white_noise_phase_std_approx_radians': float(np.sqrt(power / (2 * 128 * np.mean(abs(ideal) ** 2)))),
            'phase_approximation_assumption': 'independent circular Gaussian residual and small phase error; descriptive, not a significance test'}


def predict_awgn_errors(mapping, gain, variance, grid_points=401):
    """Model-only BER, integrating all noisy received values, not capture bits.

    The square grid is bounded; chunks avoid an unbounded grid x 16 temporary.
    Gain/phase removal makes the circular model isotropic again.
    """
    mapping = np.asarray(mapping)
    if mapping.shape != (16,) or mapping.dtype.kind not in 'iu' or set(mapping.tolist()) != set(range(16)):
        raise ValueError('Expected a permutation of 0..15')
    if (not np.isfinite(gain) or not .5 < abs(gain) < 2 or not np.isfinite(variance)
            or not .001 <= variance <= .5 or not isinstance(grid_points, int)
            or not 201 <= grid_points <= 801 or grid_points % 2 != 1):
        raise ValueError('Unbounded AWGN integration parameters')
    normalized_variance = variance / abs(gain) ** 2
    sigma = np.sqrt(normalized_variance / 2)
    levels = np.unique(POINTS.real)
    edges = np.r_[-np.inf, (levels[:-1] + levels[1:]) / 2, np.inf]
    transition = np.diff(ndtr((edges[None, :] - levels[:, None]) / sigma), axis=1)
    bits = (mapping[:, None] >> np.arange(3, -1, -1)) & 1
    hard = 0.
    for source in range(16):
        for target in range(16):
            probability = transition[source // 4, target // 4] * transition[source % 4, target % 4]
            hard += probability * np.count_nonzero(bits[source] != bits[target]) / 64
    radius = float(levels[-1] + 8 * sigma)
    axis = np.linspace(-radius, radius, grid_points)
    step = axis[1] - axis[0]
    mass = 0.
    error = 0.
    for start in range(0, grid_points ** 2, 8192):
        indices = np.arange(start, min(start + 8192, grid_points ** 2))
        samples = axis[indices // grid_points] + 1j * axis[indices % grid_points]
        density = np.exp(-abs(samples[:, None] - POINTS[None, :]) ** 2 / normalized_variance)
        density /= 16 * np.pi * normalized_variance
        mass += float(density.sum()) * step ** 2
        for bit in range(4):
            error += float(np.minimum(density[:, bits[:, bit] == 0].sum(axis=1),
                                       density[:, bits[:, bit] == 1].sum(axis=1)).sum()) * step ** 2 / 4
    return {'symbol_map_bit_error_probability': float(hard), 'bit_map_error_probability': error,
            'integrated_probability_mass': mass, 'grid_points_per_axis': grid_points,
            'normalized_noise_variance': float(normalized_variance),
            'scope': 'uniform independent symbols, memoryless circular Gaussian model; not a bound for coded reception or a proof about the real channel'}


def measure(values):
    mapping, reference = reference_from_prefix(values)
    # This codebook and phase are frozen for ALL methods below.
    model = estimate_awgn(values)
    baseline = bit_llrs(values, mapping, gain=complex(model['gain_i'], model['gain_q']),
                        noise_variance=model['noise_variance_complex'])
    results = {'baseline_circular': dict(score_llrs(baseline, reference), model=model)}
    elliptical = estimate_elliptical(values)
    results['elliptical_noise'] = dict(score_llrs(elliptical_llrs(values, mapping, elliptical), reference, baseline), model=elliptical)
    for window in (31, 127, 511):
        corrected, parameters = blind_phase_search(values, window)
        fitted = estimate_awgn(corrected)
        llrs = bit_llrs(corrected, mapping, gain=complex(fitted['gain_i'], fitted['gain_q']),
                        noise_variance=fitted['noise_variance_complex'])
        results[f'blind_phase_window_{window}'] = dict(score_llrs(llrs, reference, baseline),
                                                      phase_search=parameters, model=fitted)
    return {'mapping_scope': 'baseline prefix only; frozen codebook and PN phase shared by all methods',
            'expected_bits_sha256': hashlib.sha256(np.packbits(reference).tobytes()).hexdigest(),
            'methods': results, 'residual_diagnostics': residual_diagnostics(values, mapping, reference)}


def main():
    root = Path('corpus-cache/qam-lab')
    raw = (root / 'IQ_28_Ghz.zip').read_bytes()
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Unverified laboratory archive')
    results = {'source_url': URL, 'source_sha256': SHA256,
               'scope': 'development-corpus research; fixed phase windows, all outcomes reported; no automatic acceptance change',
               'files': {}}
    with zipfile.ZipFile(root / 'IQ_28_Ghz.zip') as archive:
        for name in sorted(archive.namelist()):
            basename = Path(name).name
            if basename not in {f'16qam {letter}.csv' for letter in 'abcdef'}:
                continue
            x, fs, _ = read_keysight_csv(archive.read(name))
            fits = []
            decoded = decode_qam16(x, fs, trial_observer=lambda fit, labels: fits.append((fit, labels)))
            fit, labels = fits[0]  # fixed first RRC; never selected by verification BER
            values = reconstruct_symbols(x, fs, fit)
            if not np.array_equal(slice_labels(values), labels):
                raise AssertionError('Symbol reconstruction differs from receiver')
            results['files'][basename] = dict(measure(values), generic_status=decoded['status'])
            if basename == '16qam f.csv':
                mapping, _ = reference_from_prefix(values)
                model = results['files'][basename]['methods']['baseline_circular']['model']
                results['files'][basename]['awgn_prediction'] = [
                    predict_awgn_errors(mapping, complex(model['gain_i'], model['gain_q']),
                                        model['noise_variance_complex'], grid)
                    for grid in (401, 801)]
    (root / 'phase-study.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    if set(results['files']) != {f'16qam {letter}.csv' for letter in 'abcdef'}:
        raise AssertionError('Expected all six QAM captures')
    for name, capture in results['files'].items():
        for result in capture['methods'].values():
            if result['evaluation_bits'] != 17904:
                raise AssertionError('Verification interval changed')
            if name != '16qam f.csv' and result['evaluation_error_count']:
                raise AssertionError('Experiment damaged a clean reference')


if __name__ == '__main__':
    main()
