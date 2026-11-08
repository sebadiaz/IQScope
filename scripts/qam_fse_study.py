"""Research-only fractionally spaced filters, with explicit prefix supervision.

Known-reference prefix filters are aided diagnostics, never blind decoding.
The decision-directed control uses only receiver decisions for its targets.
All predefined configurations are reported; selection uses prefix validation.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import signal
from iqscope_qam import decode_qam16
from iqscope_qam_soft import POINTS, _samples, estimate_awgn, bit_llrs
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_receiver_study import reconstruct_symbols, slice_labels, lanczos_samples
from scripts.qam_phase_study import reference_from_prefix, score_llrs
from scripts.qam_prbs15 import ACQUISITION_BITS

PREFIX = ACQUISITION_BITS // 4
VALIDATION_START = 384
GUARD = 40
VALIDATION_FIT_END = VALIDATION_START-2*GUARD
TAP_COUNTS = (7, 13)
RIDGES = (.001, .01, .1)


def prefix_symbols(mapping, prefix_bits):
    """Only prefix bits may be converted into supervised filter targets."""
    mapping = np.asarray(mapping)
    bits = np.asarray(prefix_bits)
    if (mapping.shape != (16,) or mapping.dtype.kind not in 'iu'
            or set(mapping.tolist()) != set(range(16)) or bits.shape != (ACQUISITION_BITS,)
            or not np.all((bits == 0) | (bits == 1))):
        raise ValueError('Expected a bijective mapping and exactly 2048 prefix bits')
    nibbles = bits.reshape(-1, 4) @ (2 ** np.arange(3, -1, -1))
    return POINTS[np.argsort(mapping)[nibbles.astype(int)]]


def raw_features(x, fs, fit, taps):
    """IQ observations at T/2 spacing before any assumed RRC matched filter.

    A fixed lowpass limits noise aliasing at the two-sample symbol grid.
    Absolute timing/carrier come from the unchanged blind baseline acquisition.
    The symmetric FIR and Lanczos interpolation are offline and noncausal.
    """
    x = np.asarray(x, dtype=complex)
    baud = fit['baud']
    count = fit['symbol_count']
    if (x.ndim != 1 or not 1024 <= len(x) <= 288000 or not np.all(np.isfinite(x))
            or not np.isfinite(fs) or not np.isfinite(baud) or baud <= 0
            or not 3.96 <= fs / baud <= 32 or not PREFIX*2 <= count <= 10000
            or taps not in TAP_COUNTS or not np.isfinite(fit['carrier_offset_hz'])
            or not np.isfinite(fit['first_symbol_center_seconds'])):
        raise ValueError('Invalid bounded IQ feature input')
    power = float(np.mean(abs(x)**2))
    if power < 1e-20:
        raise ValueError('Zero input power')
    corrected = x / np.sqrt(power) * np.exp(-2j*np.pi*fit['carrier_offset_hz']*np.arange(len(x))/fs)
    half_length = int(np.ceil(32 * fs / baud))
    prototype = signal.firwin(2*half_length+1, .9*baud, fs=fs, window=('kaiser', 7.))
    filtered = signal.fftconvolve(corrected, prototype, mode='same')
    offsets = np.arange(-(taps//2), taps//2+1) / 2
    centers = (fit['first_symbol_center_seconds'] + np.arange(count)/baud)*fs
    positions = centers[:, None] + offsets[None, :]*fs/baud
    valid = (positions.min(axis=1) >= half_length+8) & (positions.max(axis=1) < len(x)-half_length-8)
    if not np.all(valid[GUARD:-GUARD]):
        raise ValueError('Fixed guard does not cover filtering/interpolation boundaries')
    matrix = lanczos_samples(filtered, positions.reshape(-1)).reshape(count, taps)
    return matrix, {'input_scope': 'raw normalized IQ; blind baseline clock/carrier only; no RRC matched filter',
                    'sample_spacing_symbols': .5, 'tap_count': taps,
                    'antialias_tap_count': len(prototype), 'antialias_cutoff_hz': .9*baud,
                    'antialias_kaiser_beta': 7., 'interpolator': 'Lanczos radius 8',
                    'preserved_boundary_symbols_each_end': GUARD,
                    'valid_interior_symbols': count-2*GUARD}


def symbol_features(values, taps):
    values = _samples(values)
    if taps not in TAP_COUNTS or len(values) < PREFIX*2:
        raise ValueError('Invalid symbol feature budget')
    indices = np.arange(len(values))[:, None] + np.arange(-(taps//2), taps//2+1)[None, :]
    return values[np.clip(indices, 0, len(values)-1)]


def fit_prefix_filter(matrix, targets, ridge):
    """Fit only rows before symbol 512; choose no parameters from the suffix.

    Row convention: output = matrix @ coefficients. Complex conjugation is
    already included in the normal equations, so this equals a Wiener FIR.
    """
    matrix = np.asarray(matrix, dtype=complex)
    targets = np.asarray(targets, dtype=complex)
    if (matrix.ndim != 2 or not PREFIX*2 <= len(matrix) <= 10000
            or matrix.shape[1] not in TAP_COUNTS or not np.all(np.isfinite(matrix))
            or targets.shape != (PREFIX,) or not np.all(np.isfinite(targets))
            or np.mean(abs(targets)**2) < 1e-15 or ridge not in RIDGES):
        raise ValueError('Expected bounded feature matrix and exactly 512 prefix targets')

    def solve(stop):
        train = matrix[GUARD:stop]
        desired = targets[GUARD:stop]
        gram = train.conj().T @ train
        scale = float(np.trace(gram).real / matrix.shape[1])
        if scale < 1e-15:
            raise ValueError('Zero feature power')
        normal = gram + ridge*scale*np.eye(matrix.shape[1])
        coefficients = np.linalg.solve(normal, train.conj().T @ desired)
        return coefficients, float(np.linalg.cond(normal))

    # An 80-symbol gap also separates the raw waveform supports of these
    # windows (32-symbol antialias half-length plus FIR/interpolator context).
    provisional, _ = solve(VALIDATION_FIT_END)
    validation = matrix[VALIDATION_START:PREFIX] @ provisional
    validation_mse = float(np.mean(abs(validation-targets[VALIDATION_START:])**2)
                           / np.mean(abs(targets[VALIDATION_START:])**2))
    coefficients, condition = solve(PREFIX)
    training_mse = float(np.mean(abs(matrix[GUARD:PREFIX]@coefficients-targets[GUARD:PREFIX])**2))
    return {'coefficients_i': coefficients.real.tolist(), 'coefficients_q': coefficients.imag.tolist(),
            'ridge_relative_to_mean_gram_diagonal': ridge, 'regularized_condition': condition,
            'fit_symbol_count': PREFIX-GUARD, 'fit_prefix_end_exclusive': PREFIX,
            'validation_fit_symbol_count': VALIDATION_FIT_END-GUARD,
            'validation_gap_symbols': VALIDATION_START-VALIDATION_FIT_END,
            'validation_symbol_count': PREFIX-VALIDATION_START,
            'prefix_validation_normalized_mse': validation_mse, 'prefix_training_mse': training_mse,
            'coefficient_scope': 'fit/validation targets and rows strictly before symbol 512; coefficients frozen for suffix'}


def apply_prefix_filter(matrix, fitted):
    coefficients = np.array(fitted['coefficients_i']) + 1j*np.array(fitted['coefficients_q'])
    return np.asarray(matrix) @ coefficients


def soft_output(values, mapping):
    values = _samples(values)
    model = estimate_awgn(values)
    llrs = bit_llrs(values, mapping, gain=complex(model['gain_i'], model['gain_q']),
                    noise_variance=model['noise_variance_complex'])
    return llrs, model


def filtered_soft_output(corrected, mapping, baseline):
    corrected = _samples(corrected)
    baseline = np.asarray(baseline)
    if len(corrected) < PREFIX*2 or baseline.shape != (4*len(corrected),) or not np.all(np.isfinite(baseline)):
        raise ValueError('Invalid common verification interval')
    model = estimate_awgn(corrected[GUARD:-GUARD])
    llrs = bit_llrs(corrected, mapping, gain=complex(model['gain_i'], model['gain_q']),
                    noise_variance=model['noise_variance_complex'])
    llrs[:4*GUARD] = baseline[:4*GUARD]
    llrs[-4*GUARD:] = baseline[-4*GUARD:]
    return llrs, model


def measure(x, fs, fit, values):
    mapping, reference = reference_from_prefix(values)
    aided_targets = prefix_symbols(mapping, reference[:ACQUISITION_BITS])
    decision_targets = POINTS[slice_labels(values[:PREFIX])]
    baseline, baseline_model = soft_output(values, mapping)
    methods = {'baseline_circular': dict(score_llrs(baseline, reference), model=baseline_model)}
    selected = {}
    bank = {taps: raw_features(x, fs, fit, taps) for taps in TAP_COUNTS}
    for family, targets, scope in (
            ('aided_raw_fse', aided_targets, 'KNOWN REFERENCE PREFIX: aided diagnostic, not blind reception'),
            ('decision_raw_fse', decision_targets, 'baseline hard prefix decisions only; no expected bits in filter targets'),
            ('aided_symbol_fir', aided_targets, 'KNOWN REFERENCE PREFIX on already reconstructed symbols; aided control')):
        names = []
        for taps in TAP_COUNTS:
            if family == 'aided_symbol_fir':
                matrix = symbol_features(values, taps)
                frontend = {'input_scope': 'baseline RRC reconstructed symbols', 'sample_spacing_symbols': 1.,
                            'tap_count': taps, 'preserved_boundary_symbols_each_end': GUARD}
            else:
                matrix, frontend = bank[taps]
            for ridge in RIDGES:
                name = f'{family}_taps{taps}_ridge{ridge}'
                fitted = fit_prefix_filter(matrix, targets, ridge)
                corrected = apply_prefix_filter(matrix, fitted)
                # Demapper calibration is blind on the unlabelled interior,
                # as in the current baseline, not on reference suffix symbols.
                # Keep the identical complete verification segment; the FIR
                # boundary region is copied from baseline LLRs, never from PN.
                llrs, model = filtered_soft_output(corrected, mapping, baseline)
                result = dict(score_llrs(llrs, reference, baseline), filter=fitted,
                              frontend=frontend, model=model, target_scope=scope)
                interior = slice(ACQUISITION_BITS, len(reference)-4*GUARD)
                result['filtered_evaluation_bits'] = len(reference)-ACQUISITION_BITS-4*GUARD
                result['filtered_evaluation_error_count'] = int(np.count_nonzero((llrs[interior]<0) != reference[interior]))
                methods[name] = result
                names.append(name)
        # Only the held-out part of the PREFIX selects a configuration.
        selected[family] = min(names, key=lambda name: (methods[name]['filter']['prefix_validation_normalized_mse'], name))
    return {'mapping_scope': 'baseline prefix acquisition once; same codebook, PN phase and verification suffix for all methods',
            'expected_bits_sha256': hashlib.sha256(np.packbits(reference).tobytes()).hexdigest(),
            'selection_scope': '264 prefix fit symbols, 80-symbol validation gap, 128 held-out prefix symbols; refit on 472 prefix symbols; never suffix BER',
            'demapper_scope': 'blind gain/noise on each unlabelled full interior; filter coefficients remain prefix-only',
            'boundary_scope': 'first/last 40 symbol LLRs copied from baseline; last 160 verification bits are not filtered',
            'selected_by_prefix_validation': selected, 'methods': methods}


def main():
    root = Path('corpus-cache/qam-lab')
    raw = (root/'IQ_28_Ghz.zip').read_bytes()
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Unverified laboratory archive')
    results = {'source_url': URL, 'source_sha256': SHA256,
               'scope': 'aided prefix and decision-directed FSE research, all fixed configurations reported; no generic acceptance change',
               'files': {}}
    with zipfile.ZipFile(root/'IQ_28_Ghz.zip') as archive:
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
            results['files'][basename] = dict(measure(x, fs, fit, values), generic_status=decoded['status'])
    (root/'fse-study.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    if set(results['files']) != {f'16qam {letter}.csv' for letter in 'abcdef'}:
        raise AssertionError('Expected all six QAM captures')
    for name, capture in results['files'].items():
        if len(capture['methods']) != 19:
            raise AssertionError('Missing a predefined method')
        for method in capture['methods'].values():
            if method['evaluation_bits'] != 17904:
                raise AssertionError('Verification interval changed')
        if name != '16qam f.csv' and capture['methods']['baseline_circular']['evaluation_error_count']:
            raise AssertionError('Clean baseline regression')


if __name__ == '__main__':
    main()
