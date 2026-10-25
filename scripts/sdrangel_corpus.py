"""Fetch bounded IQ excerpts from SDRangel, without downloading entire large ZIPs.

Only streaming the first IQ member is supported. This is deliberately not a
universal ZIP extractor. Excerpts are local test data, never committed to Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import urllib.request
import zlib

from iqscope import analyze_samples, read_iq
from iqscope_formats import read_wave_iq


class LimitedReader:
    def __init__(self, stream, limit=64*1024*1024):
        self.stream, self.limit, self.count = stream, limit, 0

    def read(self, count):
        if count > self.limit-self.count:
            raise ValueError('Compressed-download budget exceeded')
        data = self.stream.read(count)
        self.count += len(data)
        return data

    def exact(self, count):
        out = bytearray()
        while len(out) < count:
            part = self.read(count-len(out))
            if not part:
                raise ValueError('ZIP ended before a complete header or payload')
            out.extend(part)
        return bytes(out)


def first_iq_prefix(stream, output_limit=16*1024*1024):
    if not 4096 <= output_limit <= 32*1024*1024:
        raise ValueError('Excerpt limit must be between 4 KiB and 32 MiB')
    reader = LimitedReader(stream)
    for _ in range(32):
        header = reader.exact(30)
        values = struct.unpack('<IHHHHHIIIHH', header)
        signature, version, flags, method, mtime, mdate, crc, compressed, expanded, name_length, extra_length = values
        if signature != 0x04034B50 or flags & 1 or method not in (0,8):
            raise ValueError('Expected a non-encrypted stored/deflated ZIP local member')
        name = reader.exact(name_length).decode('utf-8' if flags & 0x800 else 'cp437')
        extra = reader.exact(extra_length)
        if compressed == 0xFFFFFFFF or expanded == 0xFFFFFFFF:
            index = 0
            for _ in range(64):
                if index+4 > len(extra):
                    break
                kind, length = struct.unpack_from('<HH', extra, index)
                data = extra[index+4:index+4+length]
                if kind == 1:
                    cursor = 0
                    if expanded == 0xFFFFFFFF:
                        expanded = struct.unpack_from('<Q', data, cursor)[0]
                        cursor += 8
                    if compressed == 0xFFFFFFFF:
                        compressed = struct.unpack_from('<Q', data, cursor)[0]
                    break
                index += 4+length
        suffix = Path(name).suffix.lower()
        if suffix not in ('.wav','.sdriq'):
            if flags & 8 or compressed > 1024*1024:
                raise ValueError('An unsupported member precedes the first IQ file')
            reader.exact(compressed)
            continue
        output = bytearray()
        decompressor = zlib.decompressobj(-15) if method == 8 else None
        remaining = compressed if not (flags & 8) else None
        while len(output) < output_limit:
            wanted = min(65536, output_limit-len(output)) if method == 0 else 65536
            if remaining is not None:
                wanted = min(wanted, remaining)
            if wanted <= 0:
                break
            data = reader.read(wanted)
            if not data:
                raise ValueError('ZIP payload is incomplete')
            if remaining is not None:
                remaining -= len(data)
            if decompressor:
                output.extend(decompressor.decompress(data, output_limit-len(output)))
                if decompressor.eof:
                    break
            else:
                if remaining is None:
                    raise ValueError('Stored ZIP members with unknown length are unsupported')
                output.extend(data)
        if not output:
            raise ValueError('Empty IQ member')
        return name, bytes(output), reader.count
    raise ValueError('No IQ member found in the first 32 ZIP entries')


def run(entry, out, output_limit=16*1024*1024):
    url = 'https://www.sdrangel.org/iq/'+entry['file']
    out = Path(out)/entry['id']
    out.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={'User-Agent':'IQScope-corpus/0.3'})
    with urllib.request.urlopen(request, timeout=30) as response:
        name, prefix, downloaded = first_iq_prefix(response, output_limit)
    suffix = Path(name).suffix.lower()
    path = out / ('source-prefix'+suffix)
    if suffix == '.sdriq':
        # Header + complete complex samples. Header CRC remains unchanged.
        if len(prefix) < 32:
            raise ValueError('Truncated SDRangel header')
        widths = []
        for endian in ('<','>'):
            fields = struct.unpack(endian+'IQQIII', prefix[:32])
            if fields[-1] == zlib.crc32(prefix[:28]) & 0xFFFFFFFF:
                widths.append(4 if fields[3] == 16 else 8)
        if not widths:
            raise ValueError('Invalid SDRangel header')
        prefix = prefix[:32+((len(prefix)-32)//widths[0])*widths[0]]
    expected = entry.get('expected_excerpt_sha256_16m') if output_limit == 16*1024*1024 else None
    if expected and hashlib.sha256(prefix).hexdigest() != expected:
        raise ValueError('Source excerpt changed: review provenance and manifest before accepting new data')
    path.write_bytes(prefix)
    if suffix == '.wav':
        x, fs, center = read_wave_iq(path, seconds=10, allow_prefix=True)
    else:
        x, fs, center = read_iq(path, limit_seconds=10)
    if fs != entry['sample_rate']:
        raise ValueError(f"Sample rate differs from source catalog: {fs} != {entry['sample_rate']}")
    # Export a complete self-describing excerpt that normal import can validate.
    import numpy as np
    x.astype('<c8').tofile(out/'excerpt.sigmf-data')
    (out/'excerpt.sigmf-meta').write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs,'core:version':'1.2.0'},'captures':[{'core:sample_start':0,'core:frequency':center}],'annotations':[]},indent=2))
    report = analyze_samples(x, fs, center, out/'results', source=url)
    frame_count = sum(len(t.get('frames',[])) for t in report['wideband_trials'])
    evidence = {'source_page':'https://www.sdrangel.org/iq-files/', 'archive_url':url,
                'archive_member':name, 'compressed_bytes_received':downloaded,
                'excerpt_bytes':len(prefix), 'excerpt_sha256':hashlib.sha256(prefix).hexdigest(),
                'whole_archive_verified':False, 'sample_rate':fs,
                'center_frequency_hz':center, 'samples':len(x), 'seconds':len(x)/fs,
                'validated_adsb_frames':frame_count,
                'decoder_attempts':[{k:v for k,v in t.items() if k != 'frames'} for t in report['wideband_trials']],
                'validation':'import only' if entry['id'] != 'adsb' else 'CRC-24 packet smoke test',
                'limitations':'A bounded prefix, not a complete ZIP integrity check or golden protocol corpus.'}
    (out/'provenance.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence),flush=True)
    if entry['id'] == 'adsb' and frame_count == 0:
        raise ValueError('No CRC-valid ADS-B packet recovered from this real excerpt')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', action='append', default=[])
    parser.add_argument('--out', default='corpus-cache')
    parser.add_argument('--manifest', default=str(Path(__file__).resolve().parents[1]/'corpus/sdrangel.json'))
    parser.add_argument('--max-uncompressed-mib', type=int, choices=range(1,33), default=16)
    args = parser.parse_args()
    entries = json.loads(Path(args.manifest).read_text())['entries']
    selected = args.name or ['adsb','rtty']
    known = {entry['id']:entry for entry in entries}
    if set(selected)-set(known):
        parser.error('Unknown recording name')
    try:
        for name in selected:
            run(known[name], args.out, args.max_uncompressed_mib*1024*1024)
    except Exception as exc:
        parser.exit(1,f'Corpus check failed: {exc}\n')


if __name__ == '__main__':
    main()
