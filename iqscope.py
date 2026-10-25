"""Offline IQ discovery. Never equates a plausible demodulation with decoded content."""
import argparse
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy import ndimage, signal
from scipy.io import wavfile


def read_iq(path, sample_rate=None, limit_seconds=10):
    path = Path(path)
    meta_path = path if path.suffix == '.sigmf-meta' else path.with_suffix('.sigmf-meta')
    center = 0.0
    dtype = '<c8'
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        glob = meta['global']
        if glob.get('core:offset', 0) or glob.get('core:num_channels', 1) != 1:
            raise ValueError('Only single-channel, zero-offset SigMF data is supported')
        if len(meta.get('captures', [])) > 1:
            raise ValueError('Multiple capture segments are not supported yet')
        sample_rate = float(glob['core:sample_rate'])
        datatype = glob['core:datatype']
        types = {'cf32_le': '<c8', 'cf32_be': '>c8', 'ci16_le': '<i2', 'ci16_be': '>i2', 'cu8': 'u1'}
        if datatype not in types:
            raise ValueError(f'Unsupported SigMF datatype: {datatype}')
        dtype = types[datatype]
        captures = meta.get('captures', [])
        if captures:
            center = float(captures[0].get('core:frequency', 0))
            if captures[0].get('core:sample_start', 0):
                raise ValueError('Capture must start at sample zero')
        path = meta_path.with_suffix('.sigmf-data')
    if sample_rate is None or not math.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError('Raw cf32 IQ requires a positive --sample-rate; use SigMF for automatic metadata')
    count = int(sample_rate * limit_seconds)
    if np.dtype(dtype).kind != 'c':
        raw = np.fromfile(path, dtype=dtype, count=2 * count)
        if len(raw) % 2:
            raise ValueError('Incomplete interleaved IQ sample')
        raw = raw.astype(np.float32)
        if dtype == 'u1':
            raw = (raw - 127.5) / 127.5
        else:
            raw /= 32768
        x = raw[::2] + 1j * raw[1::2]
    else:
        x = np.fromfile(path, dtype=dtype, count=count)
    if len(x) < 1024 or not np.all(np.isfinite(x)):
        raise ValueError('Need at least 1024 finite complex samples')
    return x, sample_rate, center


def discover(x, fs, threshold_db=9):
    nfft = min(4096, len(x))
    f, p = signal.welch(x, fs, nperseg=nfft, return_onesided=False)
    f, p = np.fft.fftshift(f), np.fft.fftshift(p)
    db = 10 * np.log10(np.maximum(p, 1e-30))
    noise = float(np.percentile(db, 30))
    mask = db > noise + threshold_db
    # Join spectral ripples while retaining narrow carriers.
    mask = ndimage.binary_closing(mask, structure=np.ones(25))
    labels, number = ndimage.label(mask)
    found = []
    for idx in range(1, number + 1):
        bins = np.flatnonzero(labels == idx)
        if len(bins) < 2:
            continue
        weights = p[bins]
        offset = float(np.sum(f[bins] * weights) / weights.sum())
        found.append({'offset_hz': offset,
                      'bandwidth_hz': float((bins[-1] - bins[0] + 1) * fs / nfft),
                      'spectral_snr_db': float(np.max(db[bins]) - noise),
                      'band_edges_hz': [float(f[bins[0]]), float(f[bins[-1]])]})
    return sorted(found, key=lambda item: item['offset_hz']), f, db, noise


def channelize(x, fs, item):
    mixed = x * np.exp(-2j * np.pi * item['offset_hz'] * np.arange(len(x)) / fs)
    # Guard band accommodates detector uncertainty; resampling includes anti-alias filtering.
    target = min(fs, max(12000, 3 * item['bandwidth_hz']))
    decimation = max(1, int(fs / target))
    cutoff = min(fs * .45, max(1000, item['bandwidth_hz'] * .7))
    taps = signal.firwin(129, cutoff, fs=fs)
    filtered = signal.lfilter(taps, [1], mixed)
    return signal.resample_poly(filtered, 1, decimation), fs / decimation


def analyze_channel(x, fs, item, out, index):
    y, rate = channelize(x, fs, item)
    envelope = np.abs(y)
    cv = float(np.std(envelope) / max(np.mean(envelope), 1e-12))
    discriminator = np.angle(y[1:] * np.conj(y[:-1])) * rate / (2 * np.pi)
    deviation = float(np.percentile(np.abs(discriminator - np.median(discriminator)), 90))
    item['measurements'] = {'envelope_variation': cv, 'frequency_deviation_p90_hz': deviation,
                            'channel_sample_rate': rate}
    # This intentionally reports a hypothesis, never a validated protocol classification.
    fm_candidate = cv < .45 and deviation > 300 and item['bandwidth_hz'] > 5000
    item['hypotheses'] = ([{'family': 'FM or another angle-modulated signal', 'confidence': 'heuristic'}]
                          if fm_candidate else [{'family': 'unknown', 'confidence': 'unresolved'}])
    item['status'] = 'unresolved'
    item['validated_content'] = None
    item['decoder_trials'] = []
    if fm_candidate and len(discriminator) > 100:
        audio = discriminator - np.mean(discriminator)
        cutoff = min(15000, rate * .4)
        audio = signal.sosfilt(signal.butter(5, cutoff, fs=rate, output='sos'), audio)
        # 75 microsecond FM de-emphasis; output is a listening aid, not protocol evidence.
        alpha = math.exp(-1 / (rate * 75e-6))
        audio = signal.lfilter([1-alpha], [1, -alpha], audio)
        ratio = Fraction(48000 / rate).limit_denominator(4096)
        audio = signal.resample_poly(audio, ratio.numerator, ratio.denominator)
        peak = max(float(np.max(np.abs(audio))), 1e-12)
        filename = f'signal-{index:03d}-fm-candidate.wav'
        wavfile.write(out / filename, 48000, (audio / peak * 30000).astype(np.int16))
        item['decoder_trials'].append({'decoder': 'analog_fm', 'status': 'unvalidated_candidate', 'audio': filename})
    return item


def analyze(path, out, sample_rate=None, seconds=10, threshold_db=9):
    x, fs, center = read_iq(path, sample_rate, seconds)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    detections, frequencies, spectrum, noise = discover(x, fs, threshold_db)
    results = []
    for i, item in enumerate(detections, 1):
        item.update(id=i, frequency_hz=center + item['offset_hz'])
        results.append(analyze_channel(x, fs, item, out, i))
    report = {'source': str(path), 'sample_rate': fs, 'center_frequency_hz': center,
              'analyzed_seconds': len(x) / fs, 'noise_floor_db_per_hz': noise,
              'limitations': ['Stationary spectral detector; overlapping, hopping and weak burst signals may be missed.',
                             'FM hypotheses and audio are unvalidated; digital protocol decoders are not implemented.'],
              'signals': results}
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    np.savetxt(out / 'spectrum.csv', np.column_stack((frequencies + center, spectrum)),
               delimiter=',', header='frequency_hz,power_db_per_hz', comments='')
    return report


def demo(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fs = 256000
    t = np.arange(fs * 2) / fs
    rng = np.random.default_rng(42)
    fm = np.exp(1j * (2*np.pi*45000*t + 5*np.sin(2*np.pi*1000*t)))
    carrier = .5 * np.exp(-2j*np.pi*60000*t)
    noise = .05 * (rng.normal(size=len(t)) + 1j*rng.normal(size=len(t)))
    (fm + carrier + noise).astype('<c8').tofile(out / 'demo.sigmf-data')
    (out / 'demo.sigmf-meta').write_text(json.dumps({'global': {'core:datatype': 'cf32_le',
        'core:sample_rate': fs, 'core:version': '1.2.0'}, 'captures': [
        {'core:sample_start': 0, 'core:frequency': 100000000}], 'annotations': []}, indent=2))
    return out / 'demo.sigmf-meta'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('analyze')
    scan.add_argument('file')
    scan.add_argument('--out', default='results')
    scan.add_argument('--sample-rate', type=float)
    scan.add_argument('--seconds', type=float, default=10)
    scan.add_argument('--threshold-db', type=float, default=9)
    make = sub.add_parser('demo')
    make.add_argument('--out', default='demo')
    args = parser.parse_args()
    try:
        if args.command == 'demo':
            path = demo(args.out)
            report = analyze(path, Path(args.out) / 'results')
        else:
            if not math.isfinite(args.seconds) or args.seconds <= 0 or not math.isfinite(args.threshold_db) or args.threshold_db <= 0:
                raise ValueError('Seconds and threshold must be finite and positive')
            report = analyze(args.file, args.out, args.sample_rate, args.seconds, args.threshold_db)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
