"""Bounded remote ZIP inspection and complex64 hypotheses; no payload decoding."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
from fpv_metadata_probe import RangeReader

URL = 'https://zenodo.org/records/22019720/files/Day1-1.zip?download=1'
EXPECTED_BYTES = 5454861376
MAX_PREFIX_BYTES = 2048000 * 8
RECORDINGS = {
    'ism915': ('Day1-1/Day1-1/loraism-outdoor_915e6MHz.iq', 5901395536),
    'uhf450': ('Day1-1/Day1-1/UHF_outdoor_450e6MHz.iq', 3837802152),
    'vhf144': ('Day1-1/Day1-1/VHF-outdoor_144e6MHz.iq', 6702519808),
    'vhf150': ('Day1-1/Day1-1/VHF-outdoor_150e6MHz.iq', 10118790768),
}


def select_recording(members, recording):
    name, size = RECORDINGS[recording]
    matches = [member for member in members if member.filename == name]
    if len(matches) != 1 or matches[0].file_size != size or matches[0].is_dir():
        raise ValueError('Selected recording identity or size differs from inspected inventory')
    return matches[0]


def export_prefix(body, target):
    """Write byte-identical SigMF hypotheses; never choose an encoding implicitly."""
    from iqscope import read_iq
    if not 8192 <= len(body) <= MAX_PREFIX_BYTES or len(body) % 8:
        raise ValueError('Expected 1024 or more complete complex float32 pairs, at most one second (16,384,000 bytes)')
    target = Path(target)
    outputs = {}
    for order in ('le', 'be'):
        meta = {'global': {'core:datatype': 'cf32_' + order,
            'core:sample_rate': 2048000, 'core:version': '1.2.0',
            'core:description': 'Iraq RF complex64 hypothesis; I/Q order and header layout unverified',
            'iqscope:byte_order_status': 'unverified_hypothesis',
            'iqscope:sample_rate_source': 'Zenodo publisher master metadata'},
            'captures': [{'core:sample_start': 0}], 'annotations': []}
        outputs[Path(str(target) + '.' + order + '.sigmf-data')] = body
        outputs[Path(str(target) + '.' + order + '.sigmf-meta')] = json.dumps(meta, indent=2).encode()
    if any(path.exists() for path in outputs):
        raise ValueError('Output exists; choose a new output prefix')
    target.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, data in outputs.items():
            with path.open('xb') as handle:
                created.append(path)
                handle.write(data)
        checks = []
        for order in ('le', 'be'):
            path = Path(str(target) + '.' + order + '.sigmf-meta')
            expected = np.frombuffer(body, dtype='<c8' if order == 'le' else '>c8')
            if not np.all(np.isfinite(expected)):
                checks.append({'datatype': 'cf32_' + order, 'metadata': str(path),
                    'sample_count': len(expected), 'read_back_equal': None,
                    'read_back_status': 'rejected_nonfinite_interpretation',
                    'stored_bytes_exact': Path(str(target) + '.' + order + '.sigmf-data').read_bytes() == body})
                continue
            values, rate, _ = read_iq(path)
            exact = np.array_equal(values, expected, equal_nan=True)
            if not exact or rate != 2048000:
                raise ValueError('IQScope read-back differs from the candidate interpretation')
            checks.append({'datatype': 'cf32_' + order, 'metadata': str(path),
                           'sample_count': len(values), 'read_back_equal': exact,
                           'stored_bytes_exact': Path(str(target) + '.' + order + '.sigmf-data').read_bytes() == body})
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return checks


def analyze_hypothesis(target, order):
    """Analyze only an explicitly requested interpretation, retaining its warning."""
    from iqscope import analyze
    metadata = Path(str(target) + '.' + order + '.sigmf-meta')
    out = Path(str(target) + '.' + order + '.analysis')
    report = analyze(metadata, out)
    if report.get('interpretation_status') != 'unverified_byte_order_and_header_layout':
        raise ValueError('Analysis lost the unverified interpretation warning')
    report['frequency_reference'] = 'baseband_hz'
    report['center_frequency_verified'] = False
    report['limitations'].insert(0, f"Only {report['analyzed_seconds']:.6g} s of candidate IQ; no verified RF center. Absence of a candidate does not establish absence of a protocol.")
    (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    return {'requested_hypothesis': order, 'interpretation_status': report['interpretation_status'],
            'analyzed_seconds': report['analyzed_seconds'], 'spectral_bands': len(report['signals']),
            'trials': [{'decoder': trial.get('decoder'), 'status': trial.get('status'),
                        'candidate_count': len(trial.get('candidates', [])),
                        'frame_count': len(trial.get('frames', []))}
                       for trial in report['wideband_trials']],
            'report': str(out / 'report.json'), 'spectrum': str(out / 'spectrum.csv')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-prefix', type=Path)
    parser.add_argument('--recording', choices=tuple(RECORDINGS), default='ism915')
    parser.add_argument('--out', type=Path, default=Path('corpus-cache/iraq-iq/candidate'))
    parser.add_argument('--analyze-hypothesis', choices=('le', 'be'))
    parser.add_argument('--seconds', type=float, default=0.004, help='Prefix duration under the declared 2.048 MS/s rate, from .004 to 1 second')
    args = parser.parse_args()
    if not np.isfinite(args.seconds) or not 0.004 <= args.seconds <= 1:
        parser.error('--seconds must be finite and between .004 and 1')
    prefix_limit = int(args.seconds * 2048000) * 8
    network_budget = min(16*1024*1024, max(1024*1024, prefix_limit+65536))
    if args.local_prefix:
        with args.local_prefix.open('rb') as handle:
            body = handle.read(MAX_PREFIX_BYTES+1)
        result = {'sigmf_hypotheses': export_prefix(body, args.out)}
        if args.analyze_hypothesis:
            result['analysis'] = analyze_hypothesis(args.out, args.analyze_hypothesis)
        print(json.dumps(result))
        return
    result = {'recording_id': args.recording, 'filename_frequency_is_hint_only': True, 'source_url': URL, 'scope': 'ZIP index and bounded prefix of one IQ member',
              'prefix_limit_bytes': prefix_limit, 'network_budget_bytes': network_budget,
              'archive_integrity_verified': False, 'member_crc_verified': False,
              'sample_layout_status': 'unverified_hypotheses', 'hypotheses': []}
    try:
        with RangeReader(URL, budget=network_budget) as remote:
            if remote.size != EXPECTED_BYTES:
                raise ValueError('Archive size differs from inspected Zenodo inventory')
            with zipfile.ZipFile(remote) as archive:
                members = archive.infolist()
                candidates = [m for m in members if m.filename.lower().endswith('.iq') and not m.is_dir()]
                result.update(member_count=len(members), iq_member_count=len(candidates),
                              iq_members=[{'name':m.filename,'bytes':m.file_size,'compression':m.compress_type} for m in candidates[:100]])
                if not candidates:
                    raise ValueError('No IQ member found in the first archive')
                member = select_recording(members, args.recording)
                if member.flag_bits & 1:
                    raise ValueError('Encrypted ZIP member is outside this importer')
                with archive.open(member) as stream:
                    body = stream.read(prefix_limit)
                result.update(selected_member=member.filename, prefix_bytes=len(body),
                              prefix_sha256=hashlib.sha256(body).hexdigest(), bytes_received=remote.received)
                # Never extract a remote path; keep only a bounded local prefix outside artifacts.
                cache = Path('corpus-cache/iraq-iq')
                cache.mkdir(parents=True, exist_ok=True)
                (cache/'prefix.bin').write_bytes(body)
                result['sigmf_hypotheses'] = export_prefix(body, args.out)
                if args.analyze_hypothesis:
                    result['analysis'] = analyze_hypothesis(args.out, args.analyze_hypothesis)
                for endian in ('<','>'):
                    values = np.frombuffer(body[:len(body)//8*8], dtype=endian+'c8')
                    finite = np.isfinite(values)
                    valid = values[finite].astype(np.complex128)
                    result['hypotheses'].append({'datatype':'cf32_le' if endian=='<' else 'cf32_be',
                        'complex_samples':len(values), 'finite_fraction':float(finite.mean()) if len(values) else 0,
                        'rms':float(np.sqrt(np.mean(np.abs(valid)**2))) if len(valid) else None,
                        'maximum_magnitude':float(np.max(np.abs(valid))) if len(valid) else None,
                        'sample_rate_hz_publisher_declared':2048000,
                        'interpretation':'Headerless interleaved I/Q hypothesis only; no automatic selection or protocol claim'})
    except Exception as exc:
        result['error'] = str(exc)
    path = Path('corpus-cache/iraq-iq/observation.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
