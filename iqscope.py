"""Offline IQ discovery. Never equates a plausible demodulation with decoded content."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy import ndimage, signal
from iqscope_decoders import analog_trials, capabilities, decode_adsb
from iqscope_formats import read_wave_iq, read_sdriq
from iqscope_rtty import search_rtty
from iqscope_cw import search_cw
from iqscope_fsk import search_fsk
from iqscope_fsk4 import search_fsk4
from iqscope_ax25 import decode_ax25


def read_iq(path, sample_rate=None, limit_seconds=10):
    path = Path(path)
    if path.suffix.lower() == '.wav':
        return read_wave_iq(path, limit_seconds)
    if path.suffix.lower() == '.sdriq':
        return read_sdriq(path, limit_seconds)
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
    if not math.isfinite(limit_seconds) or limit_seconds <= 0:
        raise ValueError('Analysis duration must be positive and finite')
    if not math.isfinite(center):
        raise ValueError('Center frequency must be finite')
    bytes_per_sample = np.dtype(dtype).itemsize * (1 if np.dtype(dtype).kind == 'c' else 2)
    if path.stat().st_size % bytes_per_sample:
        raise ValueError('File ends with an incomplete IQ sample')
    count = min(8_000_000, int(sample_rate * limit_seconds))
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
    trials = analog_trials(y, rate, item['measurements'], item['bandwidth_hz'], out, index)
    item['hypotheses'] = ([{'family': trial['family'], 'confidence': 'heuristic'} for trial in trials]
                          or [{'family': 'unknown', 'confidence': 'unresolved'}])
    item['status'] = 'unresolved'
    item['validated_content'] = None
    item['decoder_trials'] = trials
    return item


def analyze_samples(x, fs, center, out, source='live', threshold_db=9, max_signals=12):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    detections, frequencies, spectrum, noise = discover(x, fs, threshold_db)
    # Bound the expensive decoder trials; report every detection, including deferred ones.
    priority = sorted(range(len(detections)), key=lambda i: detections[i]['spectral_snr_db'], reverse=True)
    active = set(priority[:max_signals])
    results = []
    for j, item in enumerate(detections):
        i = j + 1
        item.update(id=i, frequency_hz=center + item['offset_hz'])
        if j in active:
            item = analyze_channel(x, fs, item, out, i)
        else:
            item.update(status='budget_deferred', hypotheses=[], decoder_trials=[], validated_content=None)
        results.append(item)
    digital = decode_adsb(x, fs)
    rtty = search_rtty(x, fs, center)
    cw = search_cw(x, fs, center)
    fsk = search_fsk(x, fs, detections, center)
    fsk4 = search_fsk4(x, fs, detections, center)
    ax25 = decode_ax25(fsk.get('candidates',[]))
    size = min(512, len(x))
    starts = np.unique(np.linspace(0, len(x)-size, min(96, max(1, len(x)//size)), dtype=int))
    window = np.hanning(size)
    slices = np.array([x[start:start+size] * window for start in starts])
    waterfall = 10*np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(slices, axis=1), axes=1))**2 / (fs*np.sum(window**2)), 1e-30))
    report = {'schema_version': '0.2', 'source': str(source), 'sample_rate': fs,
              'center_frequency_hz': center, 'analyzed_seconds': len(x) / fs,
              'noise_floor_db_per_hz': noise, 'capabilities': capabilities(),
              'limitations': ['Stationary spectral detector; overlapping, hopping and weak bursts may be missed.',
                             'AM/FM audio are unvalidated candidates. ADS-B and AX.25 UI frames have CRC checks; RTTY/CW text candidates have timing or framing evidence only.',
                             'At most 12 spectral bands receive audio trials; other detections remain visible.'],
              'signals': results, 'wideband_trials': [digital, rtty, cw, fsk, fsk4, ax25],
              'spectrum': {'frequency_hz': frequencies.tolist(), 'power_db': spectrum.tolist()},
              'waterfall': {'power_db': waterfall.tolist(), 'time_seconds': (starts/fs).tolist(),
                            'sampled_windows': True}}
    if rtty.get('candidates'):
        (out / 'rtty-candidate.txt').write_text(rtty['candidates'][0]['text'], encoding='utf-8')
    if cw.get('candidates'):
        (out / 'cw-candidate.txt').write_text(cw['candidates'][0]['text'], encoding='utf-8')
    for trial,family_prefix in ((fsk,'fsk'),(fsk4,'fsk4')):
        for index,candidate in enumerate(trial.get('candidates',[])):
            prefix = family_prefix if index==0 else f'{family_prefix}-{index+1}'
            bit_name,packed_name = prefix+'-bits.txt',prefix+'-packed.bin'
            (out / bit_name).write_text(candidate['bits'], encoding='ascii')
            bits = np.fromiter((int(bit) for bit in candidate['bits']),dtype=np.uint8)
            (out / packed_name).write_bytes(np.packbits(bits,bitorder='big').tobytes())
            candidate['artifacts'] = {'bits':bit_name,'packed':packed_name}
            if 'symbols' in candidate:
                symbol_name = prefix+'-symbols.txt'
                (out / symbol_name).write_text(candidate['symbols'],encoding='ascii')
                candidate['artifacts']['symbols'] = symbol_name
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    np.savetxt(out / 'spectrum.csv', np.column_stack((frequencies + center, spectrum)),
               delimiter=',', header='frequency_hz,power_db_per_hz', comments='')
    return report


def analyze(path, out, sample_rate=None, seconds=10, threshold_db=9):
    x, fs, center = read_iq(path, sample_rate, seconds)
    report = analyze_samples(x, fs, center, out, source=path, threshold_db=threshold_db)
    path = Path(path)
    meta_path = path if path.suffix=='.sigmf-meta' else path.with_suffix('.sigmf-meta')
    if path.suffix.lower() not in ('.wav','.sdriq') and meta_path.exists():
        global_meta = json.loads(meta_path.read_text()).get('global',{})
        if global_meta.get('iqscope:byte_order_status')=='unverified_hypothesis':
            report['interpretation_status'] = 'unverified_byte_order_and_header_layout'
            report['interpretation_datatype'] = global_meta['core:datatype']
            report['sample_rate_source'] = global_meta.get('iqscope:sample_rate_source')
            report['limitations'].insert(0,'Candidate byte-order interpretation; endian and original header layout are not independently verified.')
            (Path(out)/'report.json').write_text(json.dumps(report,indent=2))
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
    convert = sub.add_parser('convert', help='Export a bounded IQ excerpt as SigMF')
    convert.add_argument('file')
    convert.add_argument('--out', required=True, help='Output prefix, without extension')
    convert.add_argument('--seconds', type=float, default=3)
    convert.add_argument('--sample-rate', type=float)
    annotations = sub.add_parser('dataset-annotations', help='Read sweep-level source annotations, not IQ')
    annotations.add_argument('dataset', choices=['fpv_analog'])
    annotations.add_argument('file')
    sub.add_parser('datasets', help='List dataset sources and actual integration status')
    dataset = sub.add_parser('dataset-import', help='Export a bounded dataset excerpt as SigMF')
    dataset.add_argument('dataset', choices=['panoradio_hf','imec_lte_wifi_dvbt'])
    dataset.add_argument('file')
    dataset.add_argument('--record', type=int, default=0)
    dataset.add_argument('--out', required=True)
    sub.add_parser('decoders')
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8765)
    make = sub.add_parser('demo')
    make.add_argument('--out', default='demo')
    args = parser.parse_args()
    try:
        if args.command == 'dataset-annotations':
            from iqscope_datasets import fpv_annotations
            print(json.dumps(fpv_annotations(args.file), indent=2))
            return
        if args.command == 'datasets':
            from iqscope_datasets import catalog
            print(json.dumps(catalog(), indent=2))
            return
        if args.command == 'dataset-import':
            from iqscope_datasets import export_panoradio_window, export_imec_hypotheses
            if args.dataset=='imec_lte_wifi_dvbt':
                if args.record:
                    raise ValueError('Record selection applies only to Panoradio windows')
                result = export_imec_hypotheses(args.file,args.out)
            else:
                result = export_panoradio_window(args.file,args.out,args.record)
            print(json.dumps(result,indent=2))
            return
        if args.command == 'convert':
            x, fs, center = read_iq(args.file, args.sample_rate, args.seconds)
            prefix = Path(args.out)
            prefix.parent.mkdir(parents=True, exist_ok=True)
            data_path = Path(str(prefix)+'.sigmf-data')
            meta_path = Path(str(prefix)+'.sigmf-meta')
            if data_path.exists() or meta_path.exists():
                raise ValueError('Output already exists; choose another prefix')
            x.astype('<c8').tofile(data_path)
            meta_path.write_text(json.dumps({'global': {'core:datatype': 'cf32_le', 'core:sample_rate': fs, 'core:version': '1.2.0'}, 'captures': [{'core:sample_start': 0, 'core:frequency': center}], 'annotations': []}, indent=2))
            print(json.dumps({'metadata': str(meta_path), 'samples': len(x), 'seconds': len(x)/fs}))
            return
        if args.command == 'serve':
            from iqscope_web.server import serve
            serve(args.port)
            return
        if args.command == 'decoders':
            print(json.dumps(capabilities(), indent=2))
            return
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
