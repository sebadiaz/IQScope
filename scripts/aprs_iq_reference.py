"""Bounded inspection of a public APRS-labelled original-IQ archive; no golden content yet."""
import argparse
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import zlib

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqscope import discover
from iqscope_afsk import decode_afsk1200
from iqscope_formats import read_wave_iq, wave_layout

SOURCE_URL = 'https://www.sigidwiki.com/images/6/64/APRS_IQ_145070kHz_IQ.zip'
SOURCE_PAGE = 'https://www.sigidwiki.com/wiki/File:APRS_IQ_145070kHz_IQ.zip'
ARCHIVE_BUDGET = 2*1024*1024
MEMBER_BUDGET = 4*1024*1024
ARCHIVE_BYTES = 622860
ARCHIVE_SHA256 = '72342eb27b8b8bd1df53f3eda6f4d159a5c279596f2641f192bcdc2bda7cd034'


def source_wave(root, offline=False):
    archive = root/'source.zip'
    if offline:
        data = archive.read_bytes()
    else:
        request = urllib.request.Request(SOURCE_URL, headers={'User-Agent': 'IQScope-corpus/0.15'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(ARCHIVE_BUDGET+1)
    if len(data)>ARCHIVE_BUDGET:
        raise ValueError('APRS IQ archive exceeded download budget')
    if len(data)!=ARCHIVE_BYTES or hashlib.sha256(data).hexdigest()!=ARCHIVE_SHA256:
        raise ValueError('APRS IQ archive size/SHA-256 mismatch')
    root.mkdir(parents=True, exist_ok=True)
    if not offline:
        archive.write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        members = source.infolist()
        inventory = [dict(name=m.filename, bytes=m.file_size, compressed_bytes=m.compress_size,
                          compression_method=m.compress_type, flags=m.flag_bits) for m in members]
        print(json.dumps(dict(archive_bytes=len(data), archive_sha256=hashlib.sha256(data).hexdigest(),
                              inventory=inventory)))
        if len(members)>16 or sum(m.file_size for m in members)>2*MEMBER_BUDGET:
            raise ValueError('APRS IQ ZIP inventory exceeds inspection budget')
        waves = [m for m in members if not m.is_dir() and m.filename.lower().endswith('.wav')]
        if len(waves)!=1:
            raise ValueError('Expected one unambiguous IQ WAV member')
        member = waves[0]
        if (member.file_size>MEMBER_BUDGET or member.flag_bits&1
                or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, 9)):
            raise ValueError('Unsupported or oversized APRS IQ ZIP member')
        if member.compress_type==9:
            # This pinned small archive uses Deflate64, absent from Python's
            # zipfile decoder. 7-Zip writes only the selected WAV to stdout.
            executable = shutil.which('7zz') or shutil.which('7z')
            if not executable:
                raise ValueError('This Deflate64 reference requires 7-Zip on PATH')
            process = subprocess.run([executable, 'e', '-so', '-bd', '-y', str(archive), member.filename],
                                     capture_output=True, timeout=30)
            if process.returncode:
                raise ValueError('7-Zip could not decode the pinned Deflate64 reference')
            payload = process.stdout
            backend = Path(executable).name+' Deflate64'
        else:
            with source.open(member) as handle:
                payload = handle.read(MEMBER_BUDGET+1)
            backend = 'Python zipfile'
        if len(payload)!=member.file_size or zlib.crc32(payload)&0xffffffff!=member.CRC:
            raise ValueError('APRS IQ member is incomplete')
    path = root/'recording.wav'
    path.write_bytes(payload)
    provenance = dict(source_url=SOURCE_URL, source_page=SOURCE_PAGE, archive_bytes=len(data),
                      archive_sha256=hashlib.sha256(data).hexdigest(), archive_member=member.filename,
                      member_bytes=len(payload), member_sha256=hashlib.sha256(payload).hexdigest(),
                      inventory=inventory, extraction_backend=backend, content_oracle='not established; source page calls this APRS IQ',
                      redistribution='Original archive/WAV not committed or included in the reference artifact')
    return path, provenance


def inspect(path, out):
    x, fs, center = read_wave_iq(path, seconds=20)
    bands, _, _, _ = discover(x, fs, 9)
    offsets = [0.]
    for band in sorted(bands, key=lambda b:b['spectral_snr_db'], reverse=True):
        offset = band['offset_hz']
        if abs(offset)<fs/2-6000 and all(abs(offset-v)>1500 for v in offsets):
            offsets.append(offset)
        if len(offsets)>=8:
            break
    results = []
    for offset in offsets:
        mixed = x*np.exp(-2j*np.pi*offset*np.arange(len(x))/fs)
        sos = signal.butter(6, min(10000, fs*.4), fs=fs, output='sos')
        filtered = signal.sosfilt(sos, mixed)
        down = max(1, int(np.ceil(fs/48000)))
        channel = signal.resample_poly(filtered, 1, down) if down>1 else filtered
        rate = fs/down
        frequency = np.angle(channel[1:]*np.conj(channel[:-1]))*rate/(2*np.pi)
        frequency -= np.median(frequency)
        frequency = signal.sosfilt(signal.butter(5, min(3400, rate*.4), fs=rate, output='sos'), frequency)
        ratio = Fraction(8000/rate).limit_denominator(4096)
        audio = signal.resample_poly(frequency, ratio.numerator, ratio.denominator)
        trial = decode_afsk1200(audio, 8000)
        results.append(dict(offset_hz=offset, frames=trial['frames'], timing=trial.get('timing_trials'),
                            flag_pairs=trial.get('flag_pairs_examined'), rejected_crc=trial.get('crc_rejected_across_hypotheses')))
    report = dict(layout=wave_layout(path), samples=len(x), seconds=len(x)/fs,
                  sample_rate=fs, center_from_header_hz=center, bands=bands,
                  inspection_only=True, trials=results)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, default=Path('corpus-cache/aprs-iq'))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    path, provenance = source_wave(args.cache_root, args.offline)
    (args.cache_root/'provenance.json').write_text(json.dumps(provenance, indent=2))
    print(json.dumps(provenance))
    inspect(path, args.cache_root/'inspection.json')


if __name__ == '__main__':
    main()
