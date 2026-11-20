"""Offline IQ discovery. Never equates a plausible demodulation with decoded content."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy import ndimage, signal
from iqscope_decoders import analog_trials, capabilities, decode_adsb
from iqscope_formats import read_wave_iq, read_sdriq
from iqscope_iq_windows import read_iq_window
from iqscope_rtl433 import search_rtl433
from iqscope_rtty import search_rtty
from iqscope_cw import search_cw
from iqscope_fsk import search_fsk
from iqscope_fsk4 import search_fsk4
from iqscope_ao40 import search_ao40_samples, write_ao40_artifacts
from iqscope_qam import search_qam16, write_qam_artifacts
from iqscope_psk import search_psk, write_psk_artifacts
from iqscope_ax25 import decode_ax25, decode_psk_ax25, write_psk_ax25_artifacts
from iqscope_afsk_fm import search_afsk_fm, write_afsk_fm_artifact
from iqscope_ais import search_ais,write_ais_artifacts
from iqscope_apt import search_apt,write_apt_artifacts
from iqscope_pocsag import decode_pocsag, write_pocsag_artifact
from iqscope_ofdm import detect_cyclic_prefix
from iqscope_lora import detect_lora_preamble


def read_iq(path, sample_rate=None, limit_seconds=10, start_seconds=0, start_sample=None):
    x,fs,center,_=read_iq_window(path,sample_rate,limit_seconds,start_seconds,start_sample)
    return x,fs,center


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


def analyze_samples(x, fs, center, out, source='live', threshold_db=9, max_signals=12, experimental_lora=False):
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
    rtl433 = search_rtl433(x, fs, detections, center)
    if rtl433['messages']:
        (out / 'rtl433-messages.json').write_text(json.dumps(rtl433, indent=2), encoding='utf-8')
        rtl433['artifact'] = 'rtl433-messages.json'
    digital = decode_adsb(x, fs)
    rtty = search_rtty(x, fs, center)
    cw = search_cw(x, fs, center)
    fsk = search_fsk(x, fs, detections, center)
    fsk4 = search_fsk4(x, fs, detections, center)
    ao40=search_ao40_samples(x,fs)
    write_ao40_artifacts(ao40,out)
    qam=search_qam16(x,fs,detections,center)
    write_qam_artifacts(qam,out)
    psk = search_psk(x, fs, detections, center)
    psk_ax25 = decode_psk_ax25(psk['candidates'])
    write_psk_ax25_artifacts(psk_ax25, out)
    ax25 = decode_ax25(fsk.get('candidates',[]))
    fm_ax25 = search_afsk_fm(x,fs,detections,center)
    write_afsk_fm_artifact(fm_ax25,out)
    ais=search_ais(x,fs,detections,center)
    write_ais_artifacts(ais,out)
    apt=search_apt(x,fs,detections,center)
    write_apt_artifacts(apt,out)
    for item in results:
        low,high = item['band_edges_hz']
        indexes = [index for index,frame in enumerate(fm_ax25['frames'])
                   if low<=frame['channel']['offset_hz']<=high]
        if indexes:
            family='NBFM / AFSK1200 / AX.25'
            item.update(status='crc_validated_frames',validated_content=dict(
                decoder=fm_ax25['decoder'],family=family,frame_indexes=indexes,frame_count=len(indexes),
                validation='AX.25 FCS and bounded control inspection; no connection-state or sender authentication'))
            item['hypotheses']=[h for h in item['hypotheses'] if h['family']!='unknown']+[
                dict(family=family,confidence='FCS-validated frame recovery; link mode may remain unresolved')]
        ais_indexes=[index for index,frame in enumerate(ais['frames']) if low<=frame['channel']['offset_hz']<=high]
        if ais_indexes:
            item.setdefault('validated_protocols',[]).append(dict(decoder='ais_gmsk',family='AIS / GMSK',
                frame_indexes=ais_indexes,frame_count=len(ais_indexes),validation='CRC-16/X-25 and AIS fields; positions are declarations'))
            if not indexes:item.update(status='crc_validated_frames',validated_content=item['validated_protocols'][-1])
            item['hypotheses']=[h for h in item['hypotheses'] if h['family']!='unknown']+[
                dict(family='AIS / GMSK',confidence='FCS-validated frames; declared message fields')]
    pocsag = decode_pocsag(fsk.get('candidates',[]))
    write_pocsag_artifact(pocsag, out)
    ofdm = detect_cyclic_prefix(x,fs)
    if experimental_lora:
        from iqscope_lora_experimental import detect_guarded_lora
        lora=detect_guarded_lora(x,fs)
    else:
        lora = detect_lora_preamble(x,fs)
        lora['mode']='standard'
    size = min(512, len(x))
    starts = np.unique(np.linspace(0, len(x)-size, min(96, max(1, len(x)//size)), dtype=int))
    window = np.hanning(size)
    slices = np.array([x[start:start+size] * window for start in starts])
    waterfall = 10*np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(slices, axis=1), axes=1))**2 / (fs*np.sum(window**2)), 1e-30))
    report = {'schema_version': '0.2', 'analysis_options':{'experimental_lora':experimental_lora}, 'source': str(source), 'sample_rate': fs,
              'center_frequency_hz': center, 'analyzed_seconds': len(x) / fs,
              'noise_floor_db_per_hz': noise, 'capabilities': capabilities(),
              'limitations': ['Stationary spectral detector; overlapping, hopping and weak bursts may be missed.',
                             'AM/FM audio are unvalidated candidates. ADS-B, AIS, AX.25 and supported LoRa PHY frames have CRC checks; RTTY/CW text candidates have timing or framing evidence only.',
                             'At most 12 spectral bands receive audio trials; other detections remain visible.'],
              'signals': results, 'wideband_trials': [digital, rtty, cw, fsk, fsk4, ax25, fm_ax25, ofdm, lora, rtl433, psk, psk_ax25, ao40, qam, pocsag, ais, apt],
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
    write_psk_artifacts(psk, out)
    for index,frame in enumerate(lora.get('frames',[]),1):
        name=f'lora-payload-{index}.bin'
        (out/name).write_bytes(bytes.fromhex(frame['payload_hex']))
        frame['artifact']=name
    if lora['candidates']:
        report['lora_artifact'] = 'lora-preamble-candidates.json'
        (out/'lora-preamble-candidates.json').write_text(json.dumps(lora,indent=2))
    if ofdm['candidates']:
        report['ofdm_artifact'] = 'ofdm-candidates.json'
        (out/'ofdm-candidates.json').write_text(json.dumps(ofdm,indent=2))
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    np.savetxt(out / 'spectrum.csv', np.column_stack((frequencies + center, spectrum)),
               delimiter=',', header='frequency_hz,power_db_per_hz', comments='')
    return report


def analyze(path, out, sample_rate=None, seconds=10, threshold_db=9, experimental_lora=False, start_seconds=0, start_sample=None):
    x, fs, center, window = read_iq_window(path, sample_rate, seconds, start_seconds, start_sample)
    report = analyze_samples(x, fs, center, out, source=path, threshold_db=threshold_db,experimental_lora=experimental_lora)
    report['source_window']=window
    report['source_sample_start']=window['start_sample']
    report['source_sample_end']=window['end_sample']
    report['source_sample_reference']='original_file_complex_samples'
    for trial in report['wideband_trials']:
        trial['source_window_reference']=dict(start_sample=window['start_sample'],end_sample=window['end_sample'],
            sample_rate=fs,start_seconds=window['start_seconds'],decoder_time_reference='relative to this IQ window start')
    path = Path(path)
    meta_path = path if path.suffix=='.sigmf-meta' else path.with_suffix('.sigmf-meta')
    if path.suffix.lower() not in ('.wav','.sdriq') and meta_path.exists():
        global_meta = json.loads(meta_path.read_text()).get('global',{})
        if global_meta.get('iqscope:byte_order_status')=='unverified_hypothesis':
            report['interpretation_status'] = 'unverified_byte_order_and_header_layout'
            report['interpretation_datatype'] = global_meta['core:datatype']
            report['sample_rate_source'] = global_meta.get('iqscope:sample_rate_source')
            for trial in report['wideband_trials']:
                if trial['decoder'] in ('ofdm_cp','lora_preamble'):
                    trial['input_interpretation_status'] = report['interpretation_status']
                    trial['input_datatype_hypothesis'] = report['interpretation_datatype']
                    trial['sample_rate_source'] = report['sample_rate_source']
                    for frame in trial.get('frames',[]):
                        frame['input_interpretation_status']=report['interpretation_status']
                        frame['input_datatype_hypothesis']=report['interpretation_datatype']
                    artifact_key = 'ofdm_artifact' if trial['decoder']=='ofdm_cp' else 'lora_artifact'
                    if report.get(artifact_key):
                        (Path(out)/report[artifact_key]).write_text(json.dumps(trial,indent=2))
            report['limitations'].insert(0,'Candidate byte-order interpretation; endian and original header layout are not independently verified.')
    for trial in report['wideband_trials']:
        artifact=trial.get('artifact')
        if artifact and artifact.endswith('.json'):
            (Path(out)/artifact).write_text(json.dumps(trial,indent=2))
    for decoder,key in (('lora_preamble','lora_artifact'),('ofdm_cp','ofdm_artifact')):
        if report.get(key):
            trial=next(t for t in report['wideband_trials'] if t['decoder']==decoder)
            (Path(out)/report[key]).write_text(json.dumps(trial,indent=2))
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
    scan.add_argument('--experimental-lora',action='store_true',help='Opt in to guarded experimental LoRa decoding')
    scan.add_argument('file')
    scan.add_argument('--out', default='results')
    scan.add_argument('--sample-rate', type=float)
    scan.add_argument('--seconds', type=float, default=10)
    scan.add_argument('--start-seconds',type=float,default=0,help='Seek to this source time before analyzing the bounded IQ window')
    scan.add_argument('--threshold-db', type=float, default=9)
    batch=sub.add_parser('scan',help='Scan bounded overlapping IQ file windows')
    batch.add_argument('file')
    batch.add_argument('--out',default='scan-results')
    batch.add_argument('--sample-rate',type=float)
    batch.add_argument('--seconds',type=float,default=10)
    batch.add_argument('--start-seconds',type=float,default=0)
    batch.add_argument('--start-sample',type=int,help='Resume at the exact next_start_sample from a scan report')
    batch.add_argument('--max-windows',type=int,default=8)
    batch.add_argument('--experimental-lora',action='store_true')
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
        if args.command == 'scan':
            from iqscope_scan import scan_file
            result=scan_file(args.file,args.out,sample_rate=args.sample_rate,seconds=args.seconds,
                             start_seconds=args.start_seconds,start_sample=args.start_sample,max_windows=args.max_windows,
                             experimental_lora=args.experimental_lora)
            print(json.dumps(result,indent=2))
            if result['status']=='failed_window':parser.exit(2,'Scan stopped after a failed window; completed reports were preserved.\n')
            return
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
            report = analyze(args.file, args.out, args.sample_rate, args.seconds, args.threshold_db,experimental_lora=args.experimental_lora,start_seconds=args.start_seconds)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
