"""Bounded independent channel extraction; offsets refer to the original IQ stream."""
import math
import numpy as np
from scipy import signal


def extract_channel(x, fs, offset_hz, *, seconds=5, max_samples=1_250_000):
    if not math.isfinite(fs) or fs < 20_000 or fs > 20_000_000:
        raise ValueError('Channel extraction requires 20 kS/s to 20 MS/s')
    if not math.isfinite(offset_hz) or abs(offset_hz) >= fs / 2:
        raise ValueError('Channel center must be inside the input Nyquist interval')
    # Integer decimation avoids unbounded rational resampling filters.
    down = max(1, math.ceil(fs / 250_000))
    rate = fs / down
    count = min(len(x), int(fs * seconds), max_samples * down)
    samples = np.asarray(x[:count])
    if not len(samples) or not np.all(np.isfinite(samples)):
        raise ValueError('Need finite IQ samples')
    mixed = samples * np.exp(-2j * np.pi * offset_hz * np.arange(count) / fs)
    y = signal.resample_poly(mixed, 1, down) if down > 1 else mixed
    # resample_poly compensates its linear-phase filter delay; edge padding is zero.
    metadata = {'offset_hz': float(offset_hz), 'input_sample_rate': float(fs),
                'sample_rate': float(rate), 'decimation': down,
                'source_sample_start': 0, 'source_sample_end': count,
                'source_interval_end_exclusive': True, 'sample_count': len(y),
                'duration_seconds': count / fs, 'duration_limited': count < len(x),
                'edge_padding': 'zero' if down > 1 else 'none',
                'filter_delay_compensated': True,
                'frequency_estimate': 'spectral_or_baseband_trial_not_protocol_validation'}
    return np.asarray(y, dtype='<c8'), metadata
