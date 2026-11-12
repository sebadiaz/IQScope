"""POCSAG bit recovery from demodulated receiver-audio levels, never RF IQ."""
import numpy as np
from scipy import ndimage

from iqscope_pocsag import decode_pocsag


def decode_pocsag_audio(audio, fs, max_seconds=20, max_edges=50000):
    """Fit three standard clock hypotheses, then require strict batch/BCH checks.

    All transitions constrain a single clock per window. A rate alias may fit
    the transitions but cannot supply content without the downstream checks.
    No nominal 1200-baud assumption, manual trimming or synthetic IQ conversion.
    """
    samples = np.asarray(audio)
    max_seconds = min(20., max(0., max_seconds))
    candidates = []
    diagnostics = []
    valid = (max_seconds*fs >= 1 and samples.ndim == 1 and 8000 <= fs <= 96000
             and len(samples) >= fs*.1 and np.all(np.isfinite(samples)))
    limited = False
    edge_limited = False
    analyzed_seconds = 0.
    if valid:
        limited = len(samples) > int(fs*max_seconds)
        samples = samples[:int(fs*max_seconds)].astype(float)
        analyzed_seconds = len(samples)/fs
        low, high = np.percentile(samples, [20, 80])
        threshold = (low+high)/2
        if high-low > 1e-9:
            # At 8 kHz preserve one-bit events at 2400 baud. At higher rates
            # suppress only very short impulses, not complete symbols.
            samples = ndimage.median_filter(samples, size=2*int(fs/28800)+1)
            indices = np.flatnonzero((samples[:-1] > threshold) != (samples[1:] > threshold))
            edge_limited = len(indices) > max_edges
            if 24 <= len(indices) <= max_edges:
                edges = indices+(threshold-samples[indices])/(samples[indices+1]-samples[indices])
                for nominal in (512, 1200, 2400):
                    period = fs/nominal
                    numbers = np.r_[0, np.cumsum(np.maximum(1, np.round(np.diff(edges)/period)))]
                    period, origin = np.polyfit(numbers, edges, 1)
                    baud = float(fs/period)
                    residual = float(np.sqrt(np.mean(((edges-(origin+period*numbers))/period)**2)))
                    accepted = abs(baud/nominal-1) <= .03 and residual <= .15
                    diagnostic = dict(nominal_baud=nominal, estimated_baud=baud,
                                      transitions=len(edges), clock_residual_rms_symbols=residual,
                                      timing_accepted=accepted)
                    diagnostics.append(diagnostic)
                    if not accepted:
                        continue
                    first = origin+period/2
                    start = max(0, int(np.ceil(-first/period)))
                    stop = int(np.floor((len(samples)-1-first)/period))+1
                    centers = first+np.arange(start, stop)*period
                    if not len(centers):
                        continue
                    bits = np.interp(centers, np.arange(len(samples)), samples) > threshold
                    candidates.append(dict(bits=''.join(map(str, bits.astype(int).tolist())),
                                           parameters=dict(baud=baud, first_symbol_center_seconds=float(centers[0]/fs)),
                                           timing_evidence=diagnostic))
    trial = decode_pocsag(candidates)
    for message in trial['messages']:
        message['frontend'] = 'receiver_audio_discriminator'
        message['frequency_reference'] = 'demodulated_audio_levels_no_RF_frequency'
        message['timing_evidence'] = candidates[message['candidate_index']]['timing_evidence'].copy()
    trial.update(frontend='receiver_audio_discriminator',
                 frequency_reference='demodulated_audio_levels_no_RF_frequency',
                 analyzed_seconds=analyzed_seconds, duration_limited=limited,
                 edge_budget_reached=edge_limited, edge_budget=max_edges,
                 timing_trials=diagnostics)
    trial['limitations'] = [
        'Demodulated FM/discriminator audio levels, not original RF IQ or AFSK tones.',
        'Single global clock fit per bounded window; rate +/-3% and transition residual <=0.15 symbol.',
        'At most 20 seconds and 50000 transitions; no burst search or adaptive baseline/clock tracking.',
        'Only a complete message with exact sync and BCH/parity supplies decoded content; no error correction.',
        'Basic IA5 function 3 and numeric function 0; no identity authentication or inferred RF center.',
    ]
    return trial
