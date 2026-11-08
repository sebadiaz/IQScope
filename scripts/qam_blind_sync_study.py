"""Research: independent fine timing and unlabelled fractional QAM equalization.

Gardner is seeded by the same coarse baud/carrier acquisition, but does not use
the baseline's optimized time origin or recovered fine baud. Reference bits
only score frozen outputs. All fixed sensitivity configurations are reported.
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
from iqscope_qam_soft import POINTS, _samples
from iqscope_psk_rrc import rrc_taps
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_receiver_study import reconstruct_symbols, slice_labels, lanczos_samples
from scripts.qam_phase_study import reference_from_prefix, score_llrs
from scripts.qam_fse_study import GUARD, PREFIX, raw_features, filtered_soft_output, soft_output

LOOP_BANDWIDTHS = (.01, .03)
ADAPTATION_STEPS = (.02, .08)
TAPS = 21
PASSES = 4


def interpolation_bank(phases=128, radius=8):
    offsets = np.arange(-radius+1, radius+1)
    fraction = np.arange(phases)/phases
    distance = fraction[:, None]-offsets[None, :]
    weights = np.sinc(distance)*np.sinc(distance/radius)
    weights[abs(distance) >= radius] = 0
    weights /= weights.sum(axis=1, keepdims=True)
    return offsets, weights


def gardner_centers(values, samples_per_symbol, count, bandwidth=.01):
    """128-phase FIR interpolation, normalized Gardner TED and bounded PI clock."""
    values = np.asarray(values, dtype=complex)
    if (values.ndim != 1 or not 1024 <= len(values) <= 864000 or not np.all(np.isfinite(values))
            or not np.isfinite(samples_per_symbol) or not 4 <= samples_per_symbol <= 32
            or not isinstance(count, int) or not PREFIX*2 <= count <= 10000
            or bandwidth not in LOOP_BANDWIDTHS):
        raise ValueError('Invalid bounded Gardner input')
    power = float(np.mean(abs(values)**2))
    if power < 1e-15:
        raise ValueError('Zero timing input power')
    normalized = values/np.sqrt(power)
    offsets, bank = interpolation_bank()
    def sample(position):
        base = int(np.floor(position))
        phase = int(np.floor((position-base)*len(bank)+.5))
        if phase == len(bank):
            base += 1
            phase = 0
        return normalized[np.clip(base+offsets, 0, len(normalized)-1)]@bank[phase]
    damping = 1/np.sqrt(2)
    theta = bandwidth/(damping+.25/damping)
    denominator = 1+2*damping*theta+theta*theta
    proportional = 4*damping*theta/denominator
    integral = 4*theta*theta/denominator
    period = float(samples_per_symbol)
    position = 6*period
    previous_position = position-period
    previous = sample(previous_position)
    frequency = 0.
    centers = np.empty(count)
    errors = np.empty(count)
    frequencies = np.empty(count)
    clipped = 0
    for index in range(count):
        if position >= len(values)-8:
            raise ValueError('Timing output exceeds source support')
        current = sample(position)
        middle = sample((previous_position+position)/2)
        error = float(np.real((previous-current)*np.conj(middle)))
        bounded = float(np.clip(error, -2., 2.))
        clipped += bounded != error
        centers[index] = position
        errors[index] = error
        frequency = float(np.clip(frequency+integral*bounded, -.005, .005))
        frequencies[index] = frequency
        previous, previous_position = current, position
        position += period*(1+frequency+proportional*bounded)
    return centers, {'detector': 'Gardner, Re((previous-current)*conj(midpoint))',
                     'bandwidth': bandwidth, 'proportional_gain': proportional, 'integral_gain': integral,
                     'frequency_deviation_limit_fraction': .005,
                     'frequency_correction_final_fraction': frequency,
                     'frequency_correction_tail_median_fraction': float(np.median(frequencies[-512:])),
                     'timing_error_tail_mean': float(np.mean(errors[-512:])),
                     'timing_error_tail_rms': float(np.sqrt(np.mean(errors[-512:]**2))),
                     'error_clip_fraction': clipped/count,
                     'initial_phase_symbols': 0., 'interpolation_phases': len(bank),
                     'interpolation_radius': 8,
                     'scope': 'unlabelled samples only; same coarse baud seed, independent fine phase/frequency loop'}


def independent_timing(x, fs, coarse_baud, carrier, count, bandwidth):
    x = np.asarray(x, dtype=complex)
    if (x.ndim != 1 or not 1024 <= len(x) <= 288000 or not np.all(np.isfinite(x))
            or not np.isfinite(fs) or not np.isfinite(coarse_baud) or coarse_baud <= 0
            or not 3.96 <= fs/coarse_baud <= 16 or not np.isfinite(carrier)):
        raise ValueError('Invalid timing front end')
    power = float(np.mean(abs(x)**2))
    if power < 1e-20:
        raise ValueError('Zero source power')
    source = x/np.sqrt(power)*np.exp(-2j*np.pi*carrier*np.arange(len(x))/fs)
    up = max(1, int(np.ceil(8*coarse_baud/fs)))
    if up > 1:
        source = signal.resample_poly(source, up, 1)
    rate = fs*up
    filtered = signal.fftconvolve(source, rrc_taps(rate/coarse_baud, .2), mode='same')
    centers, parameters = gardner_centers(filtered, rate/coarse_baud, count, bandwidth)
    values = lanczos_samples(filtered, centers)
    values /= np.sqrt(np.mean(abs(values)**2))
    phase = (np.angle(np.mean(values**4))-np.pi)/4
    values *= np.exp(-1j*phase)
    parameters.update(coarse_baud=coarse_baud, carrier_offset_hz=carrier, resample_up=up,
                      matched_rrc_rolloff=.2, phase_origin_radians=float(phase),
                      recovered_baud_tail_median=float(coarse_baud/(1+parameters['frequency_correction_tail_median_fraction'])))
    return values, centers/rate, parameters


def tracked_raw_features(x, fs, coarse_baud, carrier, centers_seconds, taps=TAPS):
    """Raw half-symbol FIR vectors on the recovered nonuniform timing grid."""
    x = np.asarray(x, dtype=complex)
    centers = np.asarray(centers_seconds)*fs
    if (x.ndim != 1 or not 1024 <= len(x) <= 288000 or not np.all(np.isfinite(x))
            or centers.ndim != 1 or not PREFIX*2 <= len(centers) <= 10000
            or not np.all(np.isfinite(centers)) or np.any(np.diff(centers) <= 0)
            or not np.isfinite(fs) or not np.isfinite(carrier)
            or not np.isfinite(coarse_baud) or coarse_baud <= 0 or not 3.96 <= fs/coarse_baud <= 32
            or taps != TAPS):
        raise ValueError('Invalid tracked raw feature budget')
    power = float(np.mean(abs(x)**2))
    if power < 1e-20:
        raise ValueError('Zero source power')
    corrected = x/np.sqrt(power)*np.exp(-2j*np.pi*carrier*np.arange(len(x))/fs)
    half_length = int(np.ceil(32*fs/coarse_baud))
    filtered = signal.fftconvolve(corrected, signal.firwin(2*half_length+1, .9*coarse_baud,
                                                          fs=fs, window=('kaiser', 7.)), mode='same')
    grid = np.empty(2*len(centers))
    grid[::2] = centers
    grid[1:-1:2] = (centers[:-1]+centers[1:])/2
    grid[-1] = centers[-1]+(centers[-1]-centers[-2])/2
    indices = 2*np.arange(len(centers))[:, None]+np.arange(-(taps//2), taps//2+1)[None, :]
    positions = grid[np.clip(indices, 0, len(grid)-1)]
    if (positions[GUARD:-GUARD].min() < half_length+8
            or positions[GUARD:-GUARD].max() >= len(x)-half_length-8):
        raise ValueError('Timing drift exceeds the fixed boundary guard')
    return lanczos_samples(filtered, positions.reshape(-1)).reshape(len(centers), taps)


def blind_equalizer(matrix, method='mcma', step=.02):
    """Normalized stochastic-gradient CMA/MCMA acquisition followed by RDE.

    Matrix rows use the convention output=X@c. No target decisions, known
    sequence, labels or BER enter these coefficient updates.
    """
    matrix = np.asarray(matrix, dtype=complex)
    if (matrix.ndim != 2 or not PREFIX*2 <= len(matrix) <= 10000 or matrix.shape[1] != TAPS
            or not np.all(np.isfinite(matrix)) or method not in ('cma', 'mcma') or step not in ADAPTATION_STEPS):
        raise ValueError('Invalid blind equalizer input')
    training = matrix[GUARD:-GUARD]
    center_power = float(np.mean(abs(training[:, TAPS//2])**2))
    if center_power < 1e-15:
        raise ValueError('Zero equalizer power')
    coefficients = np.zeros(TAPS, dtype=complex)
    coefficients[TAPS//2] = 1/np.sqrt(center_power)
    conjugates = training.conj()
    energies = np.maximum(np.sum(abs(training)**2, axis=1), 1e-9)
    clips = 0
    updates = 0
    for stage in (method, 'rde'):
        rate = step if stage != 'rde' else step/4
        for _ in range(PASSES):
            for row, conjugate, energy in zip(training, conjugates, energies):
                output = row@coefficients
                squared = abs(output)**2
                if stage == 'cma':
                    error = (1.32-squared)*output
                elif stage == 'mcma':
                    error = (.82-output.real**2)*output.real+1j*(.82-output.imag**2)*output.imag
                else:
                    radius_squared = (.2, 1., 1.8)[int(squared >= .6)+int(squared >= 1.4)]
                    error = (radius_squared-squared)*output
                magnitude = abs(error)
                if magnitude > 2:
                    error *= 2/magnitude
                    clips += 1
                coefficients += rate*error*conjugate/energy
                updates += 1
            if not np.all(np.isfinite(coefficients)) or not .05 < np.linalg.norm(coefficients) < 4:
                raise ValueError('Blind equalizer diverged')
    output = matrix@coefficients
    output /= np.sqrt(np.mean(abs(output[GUARD:-GUARD])**2))
    phase = (np.angle(np.mean(output[GUARD:-GUARD]**4))-np.pi)/4
    output *= np.exp(-1j*phase)
    return output, {'method': method+' -> rde', 'step_acquisition': step, 'step_rde': step/4,
                    'passes_per_stage': PASSES, 'tap_count': TAPS, 'training_symbols_per_pass': len(training),
                    'coefficient_updates': updates, 'update_clip_fraction': clips/updates,
                    'coefficients_i': coefficients.real.tolist(), 'coefficients_q': coefficients.imag.tolist(),
                    'phase_origin_radians': float(phase),
                    'fit_scope': 'unlabelled full-window interior; no known or decided symbol targets; offline repeated passes'}


def align_prefix(values, baseline):
    """Resolve only integer delay/quarter-turn/conjugation on baseline prefix."""
    values = _samples(values)
    baseline = _samples(baseline)
    if len(values) != len(baseline) or len(values) < PREFIX*2:
        raise ValueError('Alignment needs a common bounded symbol interval')
    indices = np.arange(GUARD, PREFIX)
    trials = []
    for lag in range(-3, 4):
        selected = values[indices+lag]
        for conjugated in (False, True):
            candidate = np.conj(selected) if conjugated else selected
            for turn in range(4):
                score = float(np.mean(abs(candidate*np.exp(.5j*np.pi*turn)-baseline[indices])**2))
                trials.append((score, lag, conjugated, turn))
    score, lag, conjugated, turn = min(trials)
    aligned = values[np.clip(np.arange(len(values))+lag, 0, len(values)-1)]
    if conjugated:
        aligned = np.conj(aligned)
    aligned = aligned*np.exp(.5j*np.pi*turn)
    return aligned, {'symbol_lag': lag, 'conjugated': conjugated, 'quarter_turn': turn,
                      'prefix_mse': score, 'scope': 'baseline unlabelled prefix only; no PRBS bits or suffix alignment search'}


def measure(x, fs, fit, acquisition, baseline_values):
    # Keep reference sequence fixed for scoring; no receiver helper receives it.
    mapping, reference = reference_from_prefix(baseline_values)
    baseline, model = soft_output(baseline_values, mapping)
    results = {'baseline_circular': dict(score_llrs(baseline, reference), model=model)}
    def record(name, output, parameters):
        aligned, alignment = align_prefix(output, baseline_values)
        llrs, likelihood = filtered_soft_output(aligned, mapping, baseline)
        results[name] = dict(score_llrs(llrs, reference, baseline), parameters=parameters,
                             alignment=alignment, likelihood_model=likelihood)
    matrix, _ = raw_features(x, fs, fit, TAPS)
    matrix *= np.exp(-1j*fit['phase_origin_radians'])
    for method in ('cma', 'mcma'):
        for step in ADAPTATION_STEPS:
            output, parameters = blind_equalizer(matrix, method, step)
            record(f'baseline_grid_{method}_step{step}', output, parameters)
    for bandwidth in LOOP_BANDWIDTHS:
        output, centers, timing = independent_timing(x, fs, acquisition['clock_baud'],
                                                    acquisition['carrier_offset_hz'], len(baseline_values), bandwidth)
        record(f'gardner_bw{bandwidth}', output, timing)
        tracked = tracked_raw_features(x, fs, acquisition['clock_baud'], acquisition['carrier_offset_hz'], centers)
        tracked *= np.exp(-1j*timing['phase_origin_radians'])
        for method in ('cma', 'mcma'):
            for step in ADAPTATION_STEPS:
                output, parameters = blind_equalizer(tracked, method, step)
                record(f'gardner_bw{bandwidth}_{method}_step{step}', output, dict(equalizer=parameters, timing=timing))
    return {'scope': 'blind timing/equalizer experiments, fixed configurations, no reference-bit optimization',
            'expected_bits_sha256': hashlib.sha256(np.packbits(reference).tobytes()).hexdigest(),
            'primary_methods': ['gardner_bw0.01', 'baseline_grid_mcma_step0.02', 'gardner_bw0.01_mcma_step0.02'],
            'primary_scope': 'predefined after independent synthetic checks; sensitivity variants all reported, not chosen on weak BER',
            'boundary_scope': 'first/last40 LLRs copied from baseline; same17904 full verification bits,17744 filtered bits',
            'methods': results}


def main():
    root = Path('corpus-cache/qam-lab')
    raw = (root/'IQ_28_Ghz.zip').read_bytes()
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Unverified laboratory archive')
    results = {'source_url': URL, 'source_sha256': SHA256, 'files': {}}
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
                raise AssertionError('Symbol reconstruction differs from baseline')
            results['files'][basename] = dict(measure(x, fs, fit, decoded['acquisition'], values), generic_status=decoded['status'])
    (root/'blind-sync-study.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    if set(results['files']) != {f'16qam {letter}.csv' for letter in 'abcdef'}:
        raise AssertionError('Expected all six QAM captures')
    for capture in results['files'].values():
        if len(capture['methods']) != 15 or any(m['evaluation_bits'] != 17904 for m in capture['methods'].values()):
            raise AssertionError('Comparison methods or verification interval changed')


if __name__ == '__main__':
    main()
