"""Research: deterministic blind costs and Gaussian moment correction.

No expected bits enter projection or optimization. Stage results and optimizer
failures are retained; lower modulus cost is not treated as a BER guarantee.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import optimize
from iqscope_qam import decode_qam16
from iqscope_qam_soft import POINTS, _samples
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_receiver_study import reconstruct_symbols, slice_labels
from scripts.qam_phase_study import reference_from_prefix, score_llrs
from scripts.qam_fse_study import GUARD, PREFIX, raw_features, filtered_soft_output, soft_output
from scripts.qam_blind_sync_study import TAPS, blind_equalizer, align_prefix

ANCHORS = (0., .01, .1)
MAX_ITERATIONS = 80
TRUST_RADII = (.05, .15)
DEVELOPMENT_SEEDS = (811, 922, 1033)
VALIDATION_SEEDS = (1207, 1439)


def feature_matrix(values):
    matrix = np.asarray(values, dtype=complex)
    if (matrix.ndim != 2 or not 1024 <= len(matrix) <= 10000 or matrix.shape[1] != TAPS
            or not np.all(np.isfinite(matrix))):
        raise ValueError('Expected bounded finite 21-tap feature matrix')
    power = float(np.mean(abs(matrix[GUARD:-GUARD, TAPS//2])**2))
    if not np.isfinite(power) or power < 1e-15:
        raise ValueError('Zero central feature power')
    return matrix, power


def project_baseline(matrix, baseline):
    """Reproduce the unlabelled baseline with a fixed ridge; no hard targets."""
    matrix, _ = feature_matrix(matrix)
    baseline = _samples(baseline)
    if len(matrix) != len(baseline):
        raise ValueError('Projection requires the same interval')
    train, target = matrix[GUARD:-GUARD], baseline[GUARD:-GUARD]
    gram = train.conj().T@train/len(train)
    ridge = 1e-4*float(np.trace(gram).real/TAPS)
    coefficients = np.linalg.solve(gram+ridge*np.eye(TAPS), train.conj().T@target/len(train))
    return coefficients, {'ridge_relative_to_mean_diagonal': 1e-4,
                          'unlabelled_reconstruction_mse': float(np.mean(abs(train@coefficients-target)**2)),
                          'scope': 'full-window baseline complex samples only; no hard decisions or reference bits'}


def objective(matrix, vector, stage, weights, anchor, strength):
    """Value and real-coordinate gradient; convention output=X@c."""
    c = vector[:TAPS]+1j*vector[TAPS:]
    output = matrix@c
    squared = abs(output)**2
    if stage == 'mcma':
        er = output.real**2-.82
        ei = output.imag**2-.82
        loss = .25*(er**2+ei**2)
        error = er*output.real+1j*ei*output.imag
    elif stage == 'rde':
        radius = np.choose((squared >= .6).astype(int)+(squared >= 1.4).astype(int), (.2, 1., 1.8))
        radial = squared-radius
        loss = .25*radial**2
        error = radial*output
    else:
        raise ValueError('Unknown blind objective')
    value = float(weights@loss)
    gradient = matrix.conj().T@(weights*error)
    if strength:
        deviation = matrix@(c-anchor)
        value += .5*strength*float(np.mean(abs(deviation)**2))
        gradient += strength*(matrix.conj().T@deviation)/len(matrix)
    return value, np.r_[gradient.real, gradient.imag]


def batch_equalizer(matrix, *, weighted=False, initial=None, strength=0.):
    matrix, power = feature_matrix(matrix)
    if not isinstance(weighted, bool) or strength not in ANCHORS:
        raise ValueError('Invalid predefined objective configuration')
    if initial is None:
        if strength:
            raise ValueError('Anchoring requires a declared initial filter')
        initial = np.zeros(TAPS, complex)
        initial[TAPS//2] = 1/np.sqrt(power)
    initial = np.asarray(initial, dtype=complex)
    if initial.shape != (TAPS,) or not np.all(np.isfinite(initial)) or not .01 < np.linalg.norm(initial) < 8:
        raise ValueError('Invalid initial coefficients')
    coefficients = initial.copy()
    train = matrix[GUARD:-GUARD]
    weights = 1/np.maximum(np.sum(abs(train)**2, axis=1), 1e-9) if weighted else np.ones(len(train))
    weights /= weights.sum()
    stages = {}
    for stage in ('mcma', 'rde'):
        vector = np.r_[coefficients.real, coefficients.imag]
        args = (stage, weights, initial, strength)
        start, _ = objective(train, vector, *args)
        fitted = optimize.minimize(lambda v: objective(train, v, *args), vector, jac=True,
                                   method='L-BFGS-B', options={'maxiter': MAX_ITERATIONS, 'maxfun': 160,
                                                            'maxls': 20, 'ftol': 1e-11, 'gtol': 1e-7})
        coefficients = fitted.x[:TAPS]+1j*fitted.x[TAPS:]
        if not np.all(np.isfinite(coefficients)) or not .01 < np.linalg.norm(coefficients) < 8:
            raise ValueError('Nonfinite or divergent blind filter')
        end, gradient = objective(train, fitted.x, *args)
        stages[stage] = {'initial_objective': start, 'final_objective': end,
                         'gradient_norm': float(np.linalg.norm(gradient)),
                         'optimizer_success': bool(fitted.success), 'optimizer_status': int(fitted.status),
                         'optimizer_message': str(fitted.message), 'iterations': int(fitted.nit),
                         'function_evaluations': int(fitted.nfev),
                         'coefficients_i': coefficients.real.tolist(), 'coefficients_q': coefficients.imag.tolist()}
    return {'weighted_by_inverse_row_energy': weighted, 'anchor_strength': strength,
            'maximum_iterations_per_stage': MAX_ITERATIONS, 'training_symbols': len(train),
            'fit_scope': 'unlabelled full-window interior only; no error clipping in batch cost', 'stages': stages}


def stage_output(matrix, fitted, stage):
    parameters = fitted['stages'][stage]
    c = np.array(parameters['coefficients_i'])+1j*np.array(parameters['coefficients_q'])
    return normalized_output(matrix@c)


def normalized_output(values):
    output = np.asarray(values, dtype=complex).copy()
    output /= np.sqrt(np.mean(abs(output[GUARD:-GUARD])**2))
    output *= np.exp(-1j*(np.angle(np.mean(output[GUARD:-GUARD]**4))-np.pi)/4)
    return output


def corrected_mcma(matrix, vector, covariance):
    """Deconvolve proper Gaussian noise moments, differentiating v(c) too.

    E[Re(z)^4+Im(z)^4] = clean_fourth + 3*v*clean_power + 1.5*v**2.
    Covariance convention: E[X.conj().T@X]/N.
    """
    c = vector[:TAPS]+1j*vector[TAPS:]
    z = matrix@c
    rc = covariance@c
    noise = float(np.vdot(c, rc).real)
    power = float(np.mean(abs(z)**2))
    fourth = float(np.mean(z.real**4+z.imag**4))
    value = .25*(fourth-(3*noise+2*.82)*power+1.5*noise**2+2*.82*noise+2*.82**2)
    error = z.real**3+1j*z.imag**3-(.82+1.5*noise)*z
    gradient = matrix.conj().T@error/len(matrix)+(.82-1.5*(power-noise))*rc
    return value, np.r_[gradient.real, gradient.imag]


def noise_corrected_equalizer(matrix, covariance, initial, radius=.05):
    matrix, _ = feature_matrix(matrix)
    covariance = np.asarray(covariance, dtype=complex)
    initial = np.asarray(initial, dtype=complex)
    if (covariance.shape != (TAPS, TAPS) or not np.all(np.isfinite(covariance))
            or not np.allclose(covariance, covariance.conj().T, atol=1e-10)
            or np.linalg.eigvalsh(covariance).min() < -1e-10
            or initial.shape != (TAPS,) or not np.all(np.isfinite(initial))
            or radius not in TRUST_RADII):
        raise ValueError('Invalid proper-noise covariance or trust constraint')
    train = matrix[GUARD:-GUARD]
    gram = train.conj().T@train/len(train)
    power = float(np.vdot(initial, gram@initial).real)
    noise = float(np.vdot(initial, covariance@initial).real)
    if not np.isfinite(power) or power < 1e-15 or noise >= .99*power:
        raise ValueError('Initial estimated signal power is not positive')
    origin = np.r_[initial.real, initial.imag]
    limit = radius**2*power
    def constraint(vector):
        delta = vector[:TAPS]+1j*vector[TAPS:]-initial
        return limit-float(np.vdot(delta, gram@delta).real)
    def constraint_gradient(vector):
        delta = vector[:TAPS]+1j*vector[TAPS:]-initial
        g = -2*gram@delta
        return np.r_[g.real, g.imag]
    best_vector = origin.copy()
    best_value = corrected_mcma(train, origin, covariance)[0]
    def evaluate(vector):
        nonlocal best_vector, best_value
        value, gradient = corrected_mcma(train, vector, covariance)
        if np.isfinite(value) and constraint(vector) >= 0 and value < best_value:
            best_vector, best_value = vector.copy(), value
        return value, gradient
    fitted = optimize.minimize(evaluate, origin, method='SLSQP', jac=True,
                               constraints=[{'type': 'ineq', 'fun': constraint, 'jac': constraint_gradient}],
                               options={'maxiter': MAX_ITERATIONS, 'ftol': 1e-10})
    terminal_slack = constraint(fitted.x)
    if np.all(np.isfinite(fitted.x)):
        delta = fitted.x-origin
        size = limit-terminal_slack
        projected = origin+delta*min(1., np.sqrt(limit/max(size, 1e-30))*(1-1e-12))
        evaluate(projected)
    c = best_vector[:TAPS]+1j*best_vector[TAPS:]
    slack = constraint(best_vector)
    if not np.all(np.isfinite(c)) or slack < -1e-7*power:
        raise ValueError('Noise-corrected solver left its output trust constraint')
    value, gradient = corrected_mcma(train, best_vector, covariance)
    return normalized_output(matrix@c), {
        'objective': 'proper-Gaussian-deconvolved MCMA; covariance derivative included',
        'trust_radius_relative_output_rms': radius, 'trust_constraint_slack': slack,
        'optimizer_terminal_constraint_slack': terminal_slack,
        'output_selection': 'lowest unlabelled corrected cost among feasible evaluations and projected terminal step; initial filter included',
        'initial_noise_variance_complex': noise, 'initial_total_power': power,
        'initial_objective': corrected_mcma(train, origin, covariance)[0], 'final_objective': value,
        'gradient_norm_unconstrained': float(np.linalg.norm(gradient)),
        'optimizer_success': bool(fitted.success), 'optimizer_status': int(fitted.status),
        'optimizer_message': str(fitted.message), 'iterations': int(fitted.nit),
        'function_evaluations': int(fitted.nfev),
        'coefficients_i': c.real.tolist(), 'coefficients_q': c.imag.tolist(),
        'scope': 'unlabelled input, measured/declared Gaussian covariance and baseline projection; no expected bits'}


def configurations(matrix, baseline, covariance):
    projection, parameters = project_baseline(matrix, baseline)
    methods = {'baseline_projection': (normalized_output(matrix@projection), parameters),
               'stochastic_mcma_step0.02': blind_equalizer(matrix, 'mcma', .02)}
    for weighted in (False, True):
        fit = batch_equalizer(matrix, weighted=weighted)
        for stage in ('mcma', 'rde'):
            methods[f'cold_weighted{int(weighted)}_{stage}'] = (stage_output(matrix, fit, stage), fit)
    for strength in ANCHORS:
        fit = batch_equalizer(matrix, initial=projection, strength=strength)
        for stage in ('mcma', 'rde'):
            methods[f'warm_anchor{strength}_{stage}'] = (stage_output(matrix, fit, stage), fit)
    for radius in TRUST_RADII:
        methods[f'noise_corrected_trust{radius}'] = noise_corrected_equalizer(matrix, covariance, projection, radius)
    return methods


def measured_covariance(noise_records, x, fs, fit):
    covariance = np.zeros((TAPS, TAPS), complex)
    pseudo = np.zeros((TAPS, TAPS), complex)
    target_power = float(np.mean(abs(x)**2))
    powers = {}
    for name in ('noise a.csv', 'noise b.csv'):
        source, rate = noise_records[name]
        if rate != fs:
            raise ValueError('Noise and target rates differ')
        matrix, _ = raw_features(source, rate, fit, TAPS)
        matrix *= np.exp(-1j*fit['phase_origin_radians'])
        matrix = matrix[GUARD:-GUARD]
        powers[name] = float(np.mean(abs(source)**2))
        scale = powers[name]/target_power
        covariance += scale*(matrix.conj().T@matrix/len(matrix))/2
        pseudo += scale*(matrix.T@matrix/len(matrix))/2
    return covariance, {'noise_source_powers': powers, 'target_source_power': target_power,
                        'pseudo_covariance_relative_frobenius_norm': float(np.linalg.norm(pseudo)/np.linalg.norm(covariance)),
                        'assumption': 'separate recordings representative of target additive noise; proper Gaussian moments, same receiver scale'}


def measure(x, fs, fit, baseline_values, noise_records):
    mapping, reference = reference_from_prefix(baseline_values)
    baseline, model = soft_output(baseline_values, mapping)
    matrix, frontend = raw_features(x, fs, fit, TAPS)
    matrix *= np.exp(-1j*fit['phase_origin_radians'])
    results = {'baseline_circular': dict(score_llrs(baseline, reference), model=model)}
    covariance, noise_profile = measured_covariance(noise_records, x, fs, fit)
    for name, (output, parameters) in configurations(matrix, baseline_values, covariance).items():
        aligned, alignment = align_prefix(output, baseline_values)
        alignment['status'] = 'prefix_matches' if alignment['prefix_mse'] < .25 else 'unreliable_prefix_match_with_fixed_lag_search'
        llrs, model = filtered_soft_output(aligned, mapping, baseline)
        results[name] = dict(score_llrs(llrs, reference, baseline), alignment=alignment,
                             parameters=parameters, likelihood_model=model)
    return {'expected_bits_sha256': hashlib.sha256(np.packbits(reference).tobytes()).hexdigest(),
            'primary_methods': ['warm_anchor0.1_mcma', 'noise_corrected_trust0.05'],
            'selection_scope': 'fixed on independent synthetic controls before new RF measurement; all configurations retained',
            'boundary_scope': 'first/last40 baseline symbol LLRs; same17904 verification bits,17744 treated bits',
            'frontend': frontend, 'noise_profile': noise_profile, 'methods': results}


def synthetic_controls():
    rows = []
    for variance in (.0008, .057):
        for seed in DEVELOPMENT_SEEDS+VALIDATION_SEEDS:
            rng = np.random.default_rng(seed)
            labels = rng.integers(0, 16, 5000)
            samples = np.zeros(2*len(labels), complex)
            samples[::2] = POINTS[labels]
            samples += np.sqrt(variance/2)*(rng.normal(size=len(samples))+1j*rng.normal(size=len(samples)))
            positions = 2*np.arange(len(labels))[:, None]+np.arange(-10, 11)
            matrix = samples[np.clip(positions, 0, len(samples)-1)]
            baseline_values = samples[::2]
            truth = ((labels[:, None] >> np.arange(3, -1, -1)) & 1).reshape(-1)
            selected = slice(PREFIX*4, -GUARD*4)
            baseline, _ = soft_output(baseline_values, np.arange(16))
            methods = {'baseline': {'error_count': int(np.count_nonzero((baseline[selected] < 0) != truth[selected]))}}
            for name, (output, parameters) in configurations(matrix, baseline_values, variance*np.eye(TAPS)).items():
                aligned, alignment = align_prefix(output, baseline_values)
                alignment['status'] = 'prefix_matches' if alignment['prefix_mse'] < .25 else 'unreliable_prefix_match_with_fixed_lag_search'
                llrs, _ = soft_output(aligned, np.arange(16))
                methods[name] = {'error_count': int(np.count_nonzero((llrs[selected] < 0) != truth[selected])),
                                 'alignment': alignment, 'parameters': parameters}
            rows.append(dict(seed=seed, split='development' if seed in DEVELOPMENT_SEEDS else 'validation',
                             noise_variance_complex=variance, evaluation_bits=len(truth[selected]), methods=methods))
    return {'scope': 'independent identity-channel impulses at2sps plus circular AWGN; not RF pulse shaping; no reference-symbol updates',
            'rows': rows}


def main():
    root = Path('corpus-cache/qam-lab')
    raw = (root/'IQ_28_Ghz.zip').read_bytes()
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Unverified laboratory archive')
    results = {'source_url': URL, 'source_sha256': SHA256, 'files': {}}
    with zipfile.ZipFile(root/'IQ_28_Ghz.zip') as archive:
        noise_records = {}
        for name in archive.namelist():
            if Path(name).name in ('noise a.csv', 'noise b.csv'):
                x, fs, _ = read_keysight_csv(archive.read(name))
                noise_records[Path(name).name] = (x, fs)
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
                raise AssertionError('Symbol reconstruction differs from baseline')
            results['files'][basename] = dict(measure(x, fs, fit, values, noise_records), generic_status=decoded['status'])
    results['synthetic_controls'] = synthetic_controls()
    (root/'blind-objective-study.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    if set(results['files']) != {f'16qam {letter}.csv' for letter in 'abcdef'}:
        raise AssertionError('Missing QAM capture')
    for capture in results['files'].values():
        if len(capture['methods']) != 15 or any(m['evaluation_bits'] != 17904 for m in capture['methods'].values()):
            raise AssertionError('Methods or verification interval changed')


if __name__ == '__main__':
    main()
