"""Cross-record QAM calibration research; weak reference bits never fit filters.

Uses hard decisions from named strong captures, with phase-coordinate alignment.
This requires calibration recordings and is not autonomous blind acquisition.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from iqscope_qam import decode_qam16
from iqscope_qam_soft import POINTS
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_receiver_study import reconstruct_symbols, slice_labels
from scripts.qam_phase_study import reference_from_prefix, score_llrs
from scripts.qam_prbs15 import ACQUISITION_BITS
from scripts.qam_fse_study import (
    GUARD, PREFIX, TAP_COUNTS, RIDGES, raw_features, fit_prefix_filter,
    apply_prefix_filter, filtered_soft_output, soft_output,
)

STRONG_NAMES = tuple(f'16qam {letter}.csv' for letter in 'abcde')
WEAK_NAME = '16qam f.csv'
NOISE_NAMES = ('noise a.csv', 'noise b.csv')


def canonical_features(x, fs, fit, taps):
    """Express raw observations in the baseline's constellation phase axes."""
    phase = fit['phase_origin_radians']
    if not np.isfinite(phase):
        raise ValueError('Invalid blind phase origin')
    matrix, frontend = raw_features(x, fs, fit, taps)
    return matrix*np.exp(-1j*phase), dict(frontend, phase_origin_radians=float(phase),
            alignment_scope='blind baseline phase only; no reference-bit alignment')


def checked_records(records):
    if not isinstance(records, dict) or not 1 <= len(records) <= 5 or not set(records).issubset(STRONG_NAMES):
        raise ValueError('Only the named strong calibration recordings may fit filters')
    checked = {}
    width = None
    for name in sorted(records):
        matrix, targets = records[name]
        matrix = np.asarray(matrix, dtype=complex)
        targets = np.asarray(targets, dtype=complex)
        if (matrix.ndim != 2 or not PREFIX*2 <= len(matrix) <= 10000
                or matrix.shape[1] not in TAP_COUNTS or targets.shape != (len(matrix),)
                or not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(targets))
                or np.mean(abs(targets)**2) < 1e-15):
            raise ValueError('Invalid bounded calibration record')
        if width is not None and width != matrix.shape[1]:
            raise ValueError('All calibration vectors must have the same width')
        width = matrix.shape[1]
        checked[name] = (matrix, targets)
    return checked


def fit_calibration(records, ridge):
    records = checked_records(records)
    if ridge not in RIDGES:
        raise ValueError('Invalid calibration regularization')
    width = next(iter(records.values()))[0].shape[1]
    gram = np.zeros((width, width), dtype=complex)
    cross = np.zeros(width, dtype=complex)
    count = 0
    for matrix, targets in records.values():
        observed = matrix[GUARD:-GUARD]
        desired = targets[GUARD:-GUARD]
        gram += observed.conj().T@observed
        cross += observed.conj().T@desired
        count += len(desired)
    scale = float(np.trace(gram).real/width)
    if scale < 1e-15:
        raise ValueError('Zero calibration feature power')
    normal = gram+ridge*scale*np.eye(width)
    coefficients = np.linalg.solve(normal, cross)
    return {'coefficients_i': coefficients.real.tolist(), 'coefficients_q': coefficients.imag.tolist(),
            'tap_count': width, 'ridge_relative_to_mean_gram_diagonal': ridge,
            'calibration_files': list(records), 'fit_symbol_count': count,
            'regularized_condition': float(np.linalg.cond(normal)),
            'target_scope': 'baseline hard QAM decisions on strong calibration records only; no weak samples or reference bits in fit',
            'coefficient_scope': 'full strong-record interiors, fixed for weak inference'}


def leave_one_record_out(records, ridge):
    records = checked_records(records)
    if len(records) < 2:
        raise ValueError('At least two records are needed for cross-record validation')
    folds = {}
    for held_out, (matrix, targets) in records.items():
        fitted = fit_calibration({name: value for name, value in records.items() if name != held_out}, ridge)
        predicted = apply_prefix_filter(matrix, fitted)[GUARD:-GUARD]
        desired = targets[GUARD:-GUARD]
        mse = float(np.mean(abs(predicted-desired)**2)/np.mean(abs(desired)**2))
        folds[held_out] = {'normalized_mse': mse, 'validation_symbol_count': len(desired), 'filter': fitted}
    return {'mean_normalized_mse': float(np.mean([fold['normalized_mse'] for fold in folds.values()])),
            'folds': folds, 'selection_scope': 'equal mean of held-out strong-record normalized MSEs; weak record excluded'}


def fit_noise_loaded(records, source_powers, target_power, noise_power, noise_covariance, ridge):
    """Wiener transfer with target noise, using no target symbols or labels.

    Unit noise covariance is measured on separate noise-only recordings.
    Remove their contribution from source moments, then synthesize target
    moments with its observable mean power. All covariances use X^H X units.
    """
    records = checked_records(records)
    width = next(iter(records.values()))[0].shape[1]
    covariance = np.asarray(noise_covariance, dtype=complex)
    if (set(source_powers) != set(records) or ridge not in RIDGES
            or not np.isfinite(noise_power) or noise_power <= 0
            or not np.isfinite(target_power) or target_power <= noise_power
            or covariance.shape != (width, width) or not np.all(np.isfinite(covariance))
            or not np.allclose(covariance, covariance.conj().T, atol=1e-10)
            or np.linalg.eigvalsh(covariance)[0] < -1e-10):
        raise ValueError('Invalid noise-loaded calibration moments')
    signal_covariance = np.zeros((width, width), dtype=complex)
    signal_cross = np.zeros(width, dtype=complex)
    fractions = {}
    count = 0
    for name, (matrix, targets) in records.items():
        power = source_powers[name]
        if not np.isfinite(power) or power <= noise_power:
            raise ValueError('Calibration power must exceed representative noise power')
        fraction = 1-noise_power/power
        fractions[name] = float(fraction)
        observed, desired = matrix[GUARD:-GUARD], targets[GUARD:-GUARD]
        signal_covariance += (observed.conj().T@observed/len(observed)
                              - (1-fraction)*covariance)/fraction
        signal_cross += (observed.conj().T@desired/len(observed))/np.sqrt(fraction)
        count += len(observed)
    signal_covariance /= len(records)
    signal_cross /= len(records)
    signal_covariance = (signal_covariance+signal_covariance.conj().T)/2
    eigenvalues, vectors = np.linalg.eigh(signal_covariance)
    floor = max(float(eigenvalues[-1]), 1e-12)*1e-9
    clipped = np.maximum(eigenvalues, floor)
    signal_covariance = (vectors*clipped)@vectors.conj().T
    target_fraction = 1-noise_power/target_power
    target_covariance = target_fraction*signal_covariance+(1-target_fraction)*covariance
    scale = float(np.trace(target_fraction*signal_covariance).real/width)
    normal = target_covariance+ridge*scale*np.eye(width)
    coefficients = np.linalg.solve(normal, np.sqrt(target_fraction)*signal_cross)
    return {'coefficients_i': coefficients.real.tolist(), 'coefficients_q': coefficients.imag.tolist(),
            'tap_count': width, 'ridge_relative_to_mean_gram_diagonal': ridge,
            'calibration_files': list(records), 'fit_symbol_count': count,
            'regularized_condition': float(np.linalg.cond(normal)),
            'source_signal_fractions': fractions, 'target_signal_fraction': float(target_fraction),
            'target_mean_power_raw_units': float(target_power), 'noise_mean_power_raw_units': float(noise_power),
            'signal_covariance_min_eigenvalue_before_projection': float(eigenvalues[0]),
            'signal_covariance_clipped_eigenvalues': int(np.count_nonzero(eigenvalues < floor)),
            'target_scope': 'only target raw mean power; no target symbols or reference bits',
            'coefficient_scope': 'strong-record channel moments plus measured noise covariance and target mean power',
            'assumption': 'same voltage calibration and representative stationary noise across separate recordings; not simultaneous calibrated SNR'}


def noise_profile(noise_records, target, taps, mode):
    if set(noise_records) != set(NOISE_NAMES) or mode not in NOISE_NAMES+('mean',):
        raise ValueError('Expected both predefined noise recordings')
    names = NOISE_NAMES if mode == 'mean' else (mode,)
    power = 0.
    absolute_covariance = np.zeros((taps, taps), dtype=complex)
    for name in names:
        noise = noise_records[name]
        if not np.isclose(noise['fs'], target['fs'], rtol=1e-12):
            raise ValueError('Noise and target sample rates differ')
        matrix, _ = canonical_features(noise['x'], noise['fs'], target['fit'], taps)
        matrix = matrix[GUARD:-GUARD]
        sample_power = float(np.mean(abs(noise['x'])**2))
        absolute_covariance += sample_power*(matrix.conj().T@matrix/len(matrix))
        power += sample_power
    # Average absolute moments, rather than averaging differently normalized
    # covariances without their measured voltage powers.
    power /= len(names)
    covariance = absolute_covariance/(len(names)*power)
    return power, covariance, {'noise_files': list(names), 'aggregation': mode,
            'noise_mean_power_raw_units': power, 'covariance_condition': float(np.linalg.cond(covariance)),
            'sample_spacing_symbols': .5, 'tap_count': taps}


def fit_banks(strong_features):
    """Build and select models before any weak-reference sequence is generated."""
    if set(strong_features) != set(TAP_COUNTS):
        raise ValueError('Expected every predefined tap count')
    models = {}
    for taps in TAP_COUNTS:
        records = checked_records(strong_features[taps])
        if set(records) != set(STRONG_NAMES):
            raise ValueError('Expected the five predefined calibration recordings')
        for ridge in RIDGES:
            one_name = f'calibration_a_taps{taps}_ridge{ridge}'
            matrix, targets = records[STRONG_NAMES[0]]
            prefix_fit = fit_prefix_filter(matrix, targets[:PREFIX], ridge)
            models[one_name] = {'family': 'calibration_a',
                'selection_mse': prefix_fit['prefix_validation_normalized_mse'],
                'selection_scope': 'record a prefix validation only; full record a used for final refit',
                'filter': fit_calibration({STRONG_NAMES[0]: records[STRONG_NAMES[0]]}, ridge)}
            pool_name = f'calibration_abcde_taps{taps}_ridge{ridge}'
            validation = leave_one_record_out(records, ridge)
            models[pool_name] = {'family': 'calibration_abcde',
                'selection_mse': validation['mean_normalized_mse'],
                'selection_scope': validation['selection_scope'],
                'cross_record_validation': validation,
                'filter': fit_calibration(records, ridge)}
    selected = {family: min((name for name, model in models.items() if model['family'] == family),
                            key=lambda name: (models[name]['selection_mse'], name))
                for family in ('calibration_a', 'calibration_abcde')}
    return models, selected


def evaluate_capture(capture, fitted):
    taps = fitted['tap_count']
    matrix, frontend = canonical_features(capture['x'], capture['fs'], capture['fit'], taps)
    # Reference bits are generated only here, after coefficients are fixed.
    mapping, reference = reference_from_prefix(capture['values'])
    baseline, baseline_model = soft_output(capture['values'], mapping)
    output = apply_prefix_filter(matrix, fitted)
    llrs, likelihood = filtered_soft_output(output, mapping, baseline)
    measured = dict(score_llrs(llrs, reference, baseline), frontend=frontend, likelihood_model=likelihood)
    interior = slice(ACQUISITION_BITS, len(reference)-4*GUARD)
    measured['filtered_evaluation_bits'] = len(reference)-ACQUISITION_BITS-4*GUARD
    measured['filtered_evaluation_error_count'] = int(np.count_nonzero((llrs[interior]<0) != reference[interior]))
    return measured, dict(score_llrs(baseline, reference), model=baseline_model), hashlib.sha256(np.packbits(reference).tobytes()).hexdigest()


def study(captures, noise_records):
    if set(captures) != set(STRONG_NAMES+(WEAK_NAME,)):
        raise ValueError('Expected the six predefined captures')
    # Only strong hard decisions are used as targets. Weak data are not passed
    # to fit_banks, and expected PN values never enter this calibration API.
    strong_features = {}
    for taps in TAP_COUNTS:
        strong_features[taps] = {}
        for name in STRONG_NAMES:
            capture = captures[name]
            matrix, _ = canonical_features(capture['x'], capture['fs'], capture['fit'], taps)
            strong_features[taps][name] = (matrix, POINTS[capture['labels']])
    models, selected = fit_banks(strong_features)
    source_powers = {name: float(np.mean(abs(captures[name]['x'])**2)) for name in STRONG_NAMES}
    target_power = float(np.mean(abs(captures[WEAK_NAME]['x'])**2))
    noise_primary = {}
    for family, parent in selected.items():
        calibrated = models[parent]['filter']
        taps = calibrated['tap_count']
        records = {name: strong_features[taps][name] for name in calibrated['calibration_files']}
        powers = {name: source_powers[name] for name in records}
        for mode in NOISE_NAMES+('mean',):
            noise_power, covariance, profile = noise_profile(noise_records, captures[WEAK_NAME], taps, mode)
            name = f'noise_loaded_{family}_{mode}'
            loaded = fit_noise_loaded(records, powers, target_power, noise_power, covariance,
                                      calibrated['ridge_relative_to_mean_gram_diagonal'])
            models[name] = {'family': f'noise_loaded_{family}', 'filter': loaded,
                           'parent_configuration': parent, 'noise_profile': profile,
                           'selection_mse': models[parent]['selection_mse'],
                           'selection_scope': 'tap count/ridge from strong validation; noise measured separately; no target reference feedback'}
            if mode == 'mean':
                noise_primary[family] = name
    weak_methods = {}
    for name, model in models.items():
        measured, baseline, reference_hash = evaluate_capture(captures[WEAK_NAME], model['filter'])
        weak_methods[name] = measured
    # Genuine held-out checks for the selected pooled model: the filter used
    # for each strong recording excludes that entire recording from fitting.
    held_out = {}
    pooled = models[selected['calibration_abcde']]['cross_record_validation']
    for name, fold in pooled['folds'].items():
        measured, strong_baseline, strong_hash = evaluate_capture(captures[name], fold['filter'])
        held_out[name] = dict(measured, baseline=strong_baseline, expected_bits_sha256=strong_hash,
                              calibration_files=fold['filter']['calibration_files'])
    independent = {}
    one_filter = models[selected['calibration_a']]['filter']
    for name in STRONG_NAMES[1:]:
        measured, strong_baseline, strong_hash = evaluate_capture(captures[name], one_filter)
        independent[name] = dict(measured, baseline=strong_baseline, expected_bits_sha256=strong_hash)
    noise_held_out = {}
    for name, fold in pooled['folds'].items():
        base = fold['filter']
        taps = base['tap_count']
        records = {source: strong_features[taps][source] for source in base['calibration_files']}
        power, covariance, _ = noise_profile(noise_records, captures[name], taps, 'mean')
        loaded = fit_noise_loaded(records, {source: source_powers[source] for source in records},
                                  source_powers[name], power, covariance, base['ridge_relative_to_mean_gram_diagonal'])
        measured, strong_baseline, strong_hash = evaluate_capture(captures[name], loaded)
        noise_held_out[name] = dict(measured, baseline=strong_baseline, expected_bits_sha256=strong_hash,
                                    calibration_files=loaded['calibration_files'])
    noise_independent = {}
    for name in STRONG_NAMES[1:]:
        taps = one_filter['tap_count']
        records = {STRONG_NAMES[0]: strong_features[taps][STRONG_NAMES[0]]}
        power, covariance, _ = noise_profile(noise_records, captures[name], taps, 'mean')
        loaded = fit_noise_loaded(records, {STRONG_NAMES[0]: source_powers[STRONG_NAMES[0]]},
                                  source_powers[name], power, covariance, one_filter['ridge_relative_to_mean_gram_diagonal'])
        measured, strong_baseline, strong_hash = evaluate_capture(captures[name], loaded)
        noise_independent[name] = dict(measured, baseline=strong_baseline, expected_bits_sha256=strong_hash)
    return {'scope': 'decision-directed calibration from separate strong recordings; not standalone blind acquisition',
            'selection_scope': 'strong validation selects configurations; noise-loaded coefficients additionally use target raw mean power and separate noise, never target reference symbols or BER',
            'demapper_scope': 'blind gain/noise fitted separately on the unlabelled target interior; no expected target symbols',
            'alignment_scope': 'per-record blind phase origins, clock and carrier estimates; no reference-based weak alignment',
            'boundary_scope': 'same first/last40 baseline symbol LLRs; 17904 full verification bits,17744 filtered bits',
            'selected_by_calibration_validation': selected, 'noise_loaded_primary_mean': noise_primary, 'models': models,
            'weak_capture': {'name': WEAK_NAME, 'generic_status': captures[WEAK_NAME]['status'],
                             'expected_bits_sha256': reference_hash, 'baseline': baseline, 'methods': weak_methods},
            'pooled_selected_held_out_strong': held_out,
            'single_a_selected_independent_strong': independent,
            'noise_loaded_mean_held_out_strong': noise_held_out,
            'noise_loaded_mean_independent_strong': noise_independent}


def main():
    root = Path('corpus-cache/qam-lab')
    raw = (root/'IQ_28_Ghz.zip').read_bytes()
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Unverified laboratory archive')
    captures = {}
    noise_records = {}
    with zipfile.ZipFile(root/'IQ_28_Ghz.zip') as archive:
        for name in sorted(archive.namelist()):
            basename = Path(name).name
            if basename in NOISE_NAMES:
                x, fs, _ = read_keysight_csv(archive.read(name))
                noise_records[basename] = {'x': x, 'fs': fs}
                continue
            if basename not in STRONG_NAMES+(WEAK_NAME,):
                continue
            x, fs, _ = read_keysight_csv(archive.read(name))
            fits = []
            decoded = decode_qam16(x, fs, trial_observer=lambda fit, labels: fits.append((fit, labels)))
            fit, labels = fits[0]
            values = reconstruct_symbols(x, fs, fit)
            if not np.array_equal(slice_labels(values), labels):
                raise AssertionError('Symbol reconstruction differs from baseline')
            captures[basename] = {'x': x, 'fs': fs, 'fit': fit, 'values': values, 'labels': labels, 'status': decoded['status']}
    results = {'source_url': URL, 'source_sha256': SHA256, **study(captures, noise_records)}
    (root/'calibration-study.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    if len(results['models']) != 2*len(TAP_COUNTS)*len(RIDGES)+6:
        raise AssertionError('Missing a predefined calibration configuration')
    for measured in results['weak_capture']['methods'].values():
        if measured['evaluation_bits'] != 17904 or measured['filtered_evaluation_bits'] != 17744:
            raise AssertionError('Verification interval changed')
    for group in ('pooled_selected_held_out_strong', 'noise_loaded_mean_held_out_strong'):
        for name, measured in results[group].items():
            if name in measured['calibration_files']:
                raise AssertionError('A held-out record entered its calibration model')
            if measured['baseline']['evaluation_error_count']:
                raise AssertionError('Clean baseline regression')


if __name__ == '__main__':
    main()
