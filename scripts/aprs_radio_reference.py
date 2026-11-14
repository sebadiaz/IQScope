"""Pinned ISS AFSK recording and independent published packet, not original RF IQ."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqscope_audio import analyze_audio
from iqscope_ax25 import crc_x25

PIN = 'bb0f4dfdc876f4b13d75c25621766895bb4d2ad0'
SOURCE_BYTES = 70444
SOURCE_BLOB = '7333932b16fc2c4bfa7bfef5a5301922370f6b91'
SOURCE_URL = f'https://raw.githubusercontent.com/lm-t/ee123-labs/{PIN}/lab5/ISSpkt.wav'
NOTEBOOK = f'https://github.com/lm-t/ee123-labs/blob/{PIN}/lab5/Lab5-APRS.ipynb'
COURSE = 'https://www-inst.cs.berkeley.edu/~ee123/sp17/lab/lab5/Lab5_Part_C-APRS.html'
# Independent oracle: the notebook's printed, stuffed NRZ packet, converted
# LSB-first to octets. Includes the original received FCS, not a generated one.
EXPECTED_HEX = ('86a24040404060a4a66092a6a6e103f03e4152495353202d20496e7465726e617469'
                '6f6e616c2053706163652053746174696f6efb84')
EXPECTED_TEXT = '>ARISS - International Space Station'


def verify_source(data):
    git_blob = b'blob '+str(len(data)).encode('ascii')+b'\0'+data
    if len(data) != SOURCE_BYTES or hashlib.sha1(git_blob).hexdigest() != SOURCE_BLOB:
        raise ValueError('APRS reference size/Git blob SHA-1 mismatch')
    return hashlib.sha256(data).hexdigest()


def verified_source(root, offline=False):
    path = root/'ISSpkt.wav'
    if offline:
        data = path.read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
            data = response.read(SOURCE_BYTES+1)
    digest = verify_source(data)
    if not offline:
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path, digest


def validate_result(report, out):
    trial = next(t for t in report['wideband_trials'] if t['decoder'] == 'afsk1200_ax25')
    if len(trial['frames']) != 1:
        raise AssertionError(f"Expected one recorded APRS packet, got {len(trial['frames'])}")
    frame = trial['frames'][0]
    raw = bytes.fromhex(frame['hex'])
    if (frame['hex'] != EXPECTED_HEX or not frame['fcs_valid']
            or crc_x25(raw[:-2]) != int.from_bytes(raw[-2:], 'little')):
        raise AssertionError('Recorded APRS bytes/FCS differ from published packet')
    fields = frame['fields']
    if (fields['source']['callsign'], fields['source']['ssid'],
            fields['destination']['callsign'], fields['destination']['ssid'],
            fields['via'], fields['pid'], fields['text']) != ('RS0ISS', 0, 'CQ', 0, [], 240, EXPECTED_TEXT):
        raise AssertionError('Recorded APRS addresses or status text regression')
    if (report['source_kind'] != 'receiver_audio' or report['center_frequency_hz'] is not None
            or frame['frontend'] != 'audio_afsk1200' or frame['channel'] != {'audio_frequency_hz': 1700}):
        raise AssertionError('Receiver audio promoted to RF IQ')
    if json.loads((out/report['frame_artifact']).read_text()) != trial:
        raise AssertionError('APRS frame JSON export differs from report')
    if json.loads((out/'report.json').read_text()) != report:
        raise AssertionError('APRS report JSON export differs from result')
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, default=Path('corpus-cache/aprs-radio'))
    parser.add_argument('--offline', action='store_true', help='Verify cached original WAV without network')
    args = parser.parse_args()
    path, digest = verified_source(args.cache_root, args.offline)
    out = args.cache_root/'results'
    report = analyze_audio(path, out, 20)
    trial = validate_result(report, out)
    provenance = dict(source_url=SOURCE_URL, source_commit=PIN, source_bytes=SOURCE_BYTES,
                      source_git_blob_sha1=SOURCE_BLOB, source_sha256=digest,
                      source_kind='receiver_audio', original_rf_iq=False, rf_center_hz=None,
                      course_description=COURSE, mirror_notebook=NOTEBOOK,
                      origin='course author describes an APRS packet recorded during an ISS flyby; WAV accessed through a pinned student course mirror',
                      expected_packet_basis='independent printed stuffed NRZ bits and decoded source/destination/text in the pinned notebook',
                      input_processing='unmodified source WAV; ffmpeg mono resampling to 8 kHz; automatic fixed-phase AFSK1200 trials',
                      analyzed_seconds=report['analyzed_seconds'], checked_frames=len(trial['frames']),
                      observed_frame_hex=trial['frames'][0]['hex'], observed_text=EXPECTED_TEXT,
                      redistribution='No recording copied into IQScope; upstream mirror has no explicit recording license identified',
                      scope='One recorded APRS status packet with AX.25 FCS; no original RF IQ, positions, telemetry, sender authentication or broad APRS coverage')
    (out/'provenance.json').write_text(json.dumps(provenance, indent=2))
    summary = dict(source_sha256=digest, analyzed_seconds=report['analyzed_seconds'],
                   checked_frames=1, frame_hex=trial['frames'][0]['hex'], text=EXPECTED_TEXT)
    (args.cache_root/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
