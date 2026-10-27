"""LoRa-compatible repeated chirp evidence; no sync word, header or payload decoder."""
from fractions import Fraction
import numpy as np
from scipy import signal


def detect_lora_preamble(x, fs):
    base = {'decoder': 'lora_preamble', 'family': 'LoRa-compatible CSS preamble', 'candidates': []}
    if not np.isfinite(fs) or not 125000 <= fs <= 2400000 or len(x) < 1024:
        return dict(base, status='not_applicable')
    original = len(x)
    limit = min(original, int(fs))
    x = np.asarray(x[:limit], dtype=np.complex128)
    if not np.all(np.isfinite(x)):
        return dict(base, status='not_applicable')
    candidates = []
    trials = 0
    search_windows = []
    for bandwidth in (125000, 250000, 500000):
        if fs < bandwidth:
            continue
        ratio = Fraction(bandwidth / fs).limit_denominator(4096)
        actual = fs * ratio.numerator / ratio.denominator
        if abs(actual - bandwidth) / bandwidth > 1e-6:
            continue
        y = signal.resample_poly(x, ratio.numerator, ratio.denominator)
        for sf in range(7, 13):
            length = 2**sf
            blocks = min(len(y)//length, 256)
            if blocks < 6:
                continue
            search_windows.append({'bandwidth_hz': bandwidth, 'spreading_factor': sf,
                'symbol_blocks': blocks, 'examined_seconds': blocks*length/bandwidth,
                'symbol_budget_reached': len(y)//length > blocks})
            n = np.arange(length)
            # One sample/chip: a cyclic shift of a chirp becomes a tone after dechirping.
            chirp = np.exp(1j*np.pi*(n*n/length-n))
            matrix = y[:blocks*length].reshape(blocks, length)
            for polarity in (1, -1):
                trials += 1
                transformed = np.fft.fft(matrix * np.conj(chirp if polarity == 1 else chirp.conj()), axis=1)
                power = np.abs(transformed)**2
                peaks = np.argmax(power, axis=1)
                concentration = sum(power[np.arange(blocks),(peaks+offset)%length] for offset in (-1,0,1))/np.maximum(power.sum(axis=1), 1e-30)
                best_start, best_count = 0, 0
                run_start = 0
                for index in range(blocks):
                    if concentration[index] < .65:
                        run_start = index+1
                        continue
                    if index > run_start and min((int(peaks[index])-int(peaks[run_start]))%length,
                                                (int(peaks[run_start])-int(peaks[index]))%length) > 1:
                        run_start = index
                    count = index-run_start+1
                    if count > best_count:
                        best_start, best_count = run_start, count
                if best_count < 6:
                    continue
                strength = float(np.median(concentration[best_start:best_start+best_count]))
                candidates.append({'parameters': {'bandwidth_hz': bandwidth, 'spreading_factor': sf,
                    'symbol_seconds': length/bandwidth, 'chirp_polarity': polarity},
                    'time_seconds': best_start*length/bandwidth,
                    'evidence': {'repeated_chirps': best_count, 'median_three_bin_energy_fraction': strength,
                                 'dechirped_peak_bin': int(peaks[best_start]), 'required_chirps': 6},
                    'score': strength, 'score_kind': 'heuristic_not_probability',
                    'validation_scope': 'Repeated CSS chirps compatible with a LoRa preamble; no sync word, header, CRC, payload or LoRaWAN identification'})
    candidates.sort(key=lambda item: item['score'], reverse=True)
    return dict(base, status='repeated_chirp_candidate' if candidates else 'no_consistent_candidate',
                candidates=candidates[:6], trials=trials, analyzed_seconds=len(x)/fs, search_windows=search_windows,
                sample_budget_reached=limit < original,
                limitations=['Centered single-channel search only; no RF center or carrier-offset estimation.',
                    'BW 125/250/500 kHz, SF7–SF12, both chirp directions; six stable concentrated FFT peaks required.',
                    'First second only; at most 256 symbols per BW/SF. Late/short/weak bursts, clock drift and off-center channels may be missed.',
                    'Other repeated CSS waveforms can match; no LoRa packet, sync word, header, coding rate, CRC or payload decoded.'])
