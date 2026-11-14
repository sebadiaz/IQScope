"""Pinned original-IQ FM/AFSK AX.25 link regression; I-mode interpretations stay unresolved."""
import argparse
import base64
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqscope import analyze
from iqscope_ax25 import crc_x25

SOURCE_URL = 'https://www.sigidwiki.com/images/6/64/APRS_IQ_145070kHz_IQ.zip'
SOURCE_PAGE = 'https://www.sigidwiki.com/wiki/File:APRS_IQ_145070kHz_IQ.zip'
ARCHIVE_BUDGET = 2*1024*1024
MEMBER_BUDGET = 4*1024*1024
ARCHIVE_BYTES = 622860
ARCHIVE_SHA256 = '72342eb27b8b8bd1df53f3eda6f4d159a5c279596f2641f192bcdc2bda7cd034'
MEMBER_SHA256 = '0df449836168ab3d6e3f470910e6401b5ad8a14a9310871239a0ad220d36cc50'
# Development regression from FCS-valid received frames. The publisher only
# labels the recording APRS; no independent golden packets or total are given.
EXPECTED_HEX = [
    '9664b2b28840f49c64a4a2404072ae6496a0a240e544f03b204b325959442d3130204445204e3252512d392028464e33304651292051544320302e2e2e0dc7ae',
    '9c64a4a2404072ae6496a0a240e1b1373c',
    '9664b2b28840f49c64a4a2404072ae6496a0a240e546f046460de132',
    '9c64a4a24040f2ae6496a0a24061aaf046510de242',
    '9664b2b28840749c64a4a24040f2ae6496a0a240e56135a6']


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
            executable = shutil.which('7zz') or shutil.which('7z') or shutil.which('unzip')
            if not executable:
                raise ValueError('This Deflate64 reference requires 7-Zip or Info-ZIP with Deflate64 support')
            arguments = ([executable, '-p', str(archive), member.filename] if Path(executable).name=='unzip'
                         else [executable, 'e', '-so', '-bd', '-y', str(archive), member.filename])
            process = subprocess.run(arguments,
                                     capture_output=True, timeout=30)
            if process.returncode:
                raise ValueError('Deflate64 reference extraction failed using '+Path(executable).name)
            payload = process.stdout
            backend = Path(executable).name+' Deflate64'
        else:
            with source.open(member) as handle:
                payload = handle.read(MEMBER_BUDGET+1)
            backend = 'Python zipfile'
        if len(payload)!=member.file_size or zlib.crc32(payload)&0xffffffff!=member.CRC:
            raise ValueError('APRS IQ member is incomplete')
        if hashlib.sha256(payload).hexdigest()!=MEMBER_SHA256:
            raise ValueError('IQ WAV SHA-256 mismatch')
    path = root/'recording.wav'
    path.write_bytes(payload)
    provenance = dict(source_url=SOURCE_URL, source_page=SOURCE_PAGE, archive_bytes=len(data),
                      archive_sha256=hashlib.sha256(data).hexdigest(), archive_member=member.filename,
                      member_bytes=len(payload), member_sha256=hashlib.sha256(payload).hexdigest(),
                      inventory=inventory, extraction_backend=backend,
                      content_oracle='development regression from FCS-valid IQ reception; no author-provided golden packets/count',
                      redistribution='Original archive/WAV not committed or included in the reference artifact')
    return path, provenance


def validate_result(report, out):
    trial = next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_fm_ax25')
    if [f['hex'] for f in trial['frames']]!=EXPECTED_HEX:
        raise AssertionError('Recorded IQ frame bytes/count regression')
    if [f['fields']['frame_type'] for f in trial['frames']]!=['I','S','I','I','S']:
        raise AssertionError('Recorded control layout regression')
    for frame in trial['frames']:
        raw=bytes.fromhex(frame['hex'])
        if not frame['fcs_valid'] or crc_x25(raw[:-2])!=int.from_bytes(raw[-2:],'little'):
            raise AssertionError('Recorded IQ frame FCS failed')
        fields=frame['fields']
        if fields['pid'] is not None or fields['payload_hex'] or 'aprs' in fields:
            raise AssertionError('Unresolved link content was promoted to application/APRS data')
        if fields['frame_type']=='I' and [v['mode'] for v in fields['control_candidates']]!=['modulo_8','modulo_128']:
            raise AssertionError('Recorded I-frame mode ambiguity was suppressed')
        if frame['frontend']!='fm_iq_afsk1200' or frame['channel']['rf_center_known']:
            raise AssertionError('IQ provenance or missing RF center was misrepresented')
        if (out/frame['wire_artifact']).read_bytes()!=raw:
            raise AssertionError('Binary full-frame export changed original bytes')
    if json.loads((out/trial['artifact']).read_text())!=trial:
        raise AssertionError('IQ AX.25 JSON export differs from report')
    expected_kiss=b''.join(b'\xc0\x00'+bytes.fromhex(h)[:-2]+b'\xc0' for h in EXPECTED_HEX)
    if (out/trial['kiss_artifact']).read_bytes()!=expected_kiss:
        raise AssertionError('Recorded IQ KISS export changed frame order or bytes')
    if trial['kiss_export']['frame_count']!=5 or trial['kiss_export']['fcs_included'] is not False:
        raise AssertionError('Recorded IQ KISS scope is incorrect')
    if report['sample_rate']!=39062 or report['center_frequency_hz']!=0:
        raise AssertionError('Header metadata was replaced with filename assumptions')
    if not any(s['validated_content'] and s['validated_content']['frame_count']==5 for s in report['signals']):
        raise AssertionError('Validated FM frames were not associated with their detected band')
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, default=Path('corpus-cache/aprs-iq'))
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--development-archive', action='store_true', help='Print the verified small public ZIP for offline receiver development')
    args = parser.parse_args()
    path, provenance = source_wave(args.cache_root, args.offline)
    (args.cache_root/'provenance.json').write_text(json.dumps(provenance, indent=2))
    print(json.dumps(provenance))
    if args.development_archive:
        encoded = base64.b64encode((args.cache_root/'source.zip').read_bytes()).decode('ascii')
        for offset in range(0,len(encoded),4096):
            print(f'IQSCOPE_ZIP_B64:{offset}:{encoded[offset:offset+4096]}')
    out=args.cache_root/'results'
    report=analyze(path,out,seconds=20)
    trial=validate_result(report,out)
    summary=dict(archive_sha256=provenance['archive_sha256'],member_sha256=provenance['member_sha256'],
                 sample_rate=report['sample_rate'],analyzed_seconds=report['analyzed_seconds'],
                 rf_center_known=False,checked_frames=len(trial['frames']),frame_hex=EXPECTED_HEX,
                 frame_types=[f['fields']['frame_type'] for f in trial['frames']],
                 budget_exhausted=trial['budget_exhausted'])
    provenance.update(input_kind='publisher-provided complex IQ; stereo PCM16 WAV, I then Q',
                      rf_center_hz=None,frequency_basis='relative; filename frequency is not applied',
                      scope='five FCS-valid link frames observed: three I, two RR; no confirmed APRS UI, application payload, connection reassembly or independent message ground truth',
                      observed=summary)
    (args.cache_root/'provenance.json').write_text(json.dumps(provenance,indent=2))
    (args.cache_root/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
