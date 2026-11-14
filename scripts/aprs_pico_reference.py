"""Independent Pico line-output recording with published position/altitude; no RF claim."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqscope_audio import analyze_audio
from iqscope_ax25 import crc_x25

PIN = 'd78e42f10dc11d6a8e983e90927b0ecc6cd9fedd'
ROOT_URL = f'https://github.com/eleccoder/raspi-pico-aprs-tnc/blob/{PIN}'
SOURCE_URL = f'https://raw.githubusercontent.com/eleccoder/raspi-pico-aprs-tnc/{PIN}/doc/aprs_pico_beacon_demo.wav'
SOURCE_BYTES = 639436
SOURCE_BLOB = 'b5dfa24975035cb82390879fa75c54ca0587d080'
ENCODER = 'https://github.com/eleccoder/ax25-aprs-lib/blob/2d8a85f7b5ec1f51d31c58a27f8693ebec76ce17/src/ax25beacon.c'
# Published transmitter parameters: 48.75588 N, 9.19011 E, 483 metres.
# The upstream encoder floors positive compressed-coordinate words and rounds
# feet to a six-digit integer. These literal wire values are derived from that
# independent implementation, not from IQScope's first decode of the audio.
EXPECTED_PAYLOAD = b'!/5n5qPkBr>   /A=001585APRS by RPi-Pico - https://github.com/eleccoder/raspi-pico-aprs-tnc'
EXPECTED_LATITUDE = 90-15710957/380926
EXPECTED_LONGITUDE = -180+36033715/190463


def verified_source(root, offline=False):
    path = root/'aprs_pico_beacon_demo.wav'
    if offline:
        data = path.read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
            data = response.read(SOURCE_BYTES+1)
    blob = b'blob '+str(len(data)).encode('ascii')+b'\0'+data
    if len(data) != SOURCE_BYTES or hashlib.sha1(blob).hexdigest() != SOURCE_BLOB:
        raise ValueError('Pico APRS reference size/Git blob mismatch')
    digest = hashlib.sha256(data).hexdigest()
    if not offline:
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path, digest


def validate_result(report, out):
    trial = next(t for t in report['wideband_trials'] if t['decoder'] == 'afsk1200_ax25')
    if not trial['frames']:
        raise AssertionError('No CRC-valid packet recovered from Pico hardware recording')
    for frame in trial['frames']:
        raw = bytes.fromhex(frame['hex'])
        fields = frame['fields']
        if not frame['fcs_valid'] or crc_x25(raw[:-2]) != int.from_bytes(raw[-2:], 'little'):
            raise AssertionError('Pico recorded frame has invalid original FCS')
        addresses = [fields['source'], fields['destination'], *fields['via']]
        if [(a['callsign'], a['ssid']) for a in addresses] != [('DL3TG', 9), ('APPIPI', 0), ('WIDE1', 1), ('WIDE2', 2)]:
            raise AssertionError('Pico recorded addresses differ from published transmitter')
        if fields['pid'] != 240 or bytes.fromhex(fields['payload_hex']) != EXPECTED_PAYLOAD:
            raise AssertionError('Pico recorded payload differs from independent encoder/configuration')
        aprs = fields['aprs']
        if (aprs['status'], aprs['format'], aprs['symbol_table'], aprs['symbol_code'],
                aprs['altitude_ft'], aprs['altitude_source']) != ('decoded_position', 'compressed', '/', '>', 1585, 'comment_annotation'):
            raise AssertionError('Pico numeric APRS position/altitude regression')
        if not (math.isclose(aprs['latitude_deg'], EXPECTED_LATITUDE, rel_tol=0, abs_tol=1e-12)
                and math.isclose(aprs['longitude_deg'], EXPECTED_LONGITUDE, rel_tol=0, abs_tol=1e-12)
                and math.isclose(aprs['altitude_m'], 483.108, rel_tol=0, abs_tol=1e-12)):
            raise AssertionError('Pico coordinates or foot-to-metre conversion regression')
        if any(key in aprs for key in ('course_deg', 'speed_knots', 'telemetry')):
            raise AssertionError('Untransmitted Pico motion/telemetry was invented')
        if frame['frontend'] != 'audio_afsk1200' or frame['channel'] != {'audio_frequency_hz': 1700}:
            raise AssertionError('Pico line-output audio promoted to an RF channel')
    if report['source_kind'] != 'receiver_audio' or report['center_frequency_hz'] is not None:
        raise AssertionError('Pico audio import promoted to original RF IQ')
    if json.loads((out/report['frame_artifact']).read_text()) != trial:
        raise AssertionError('Pico frame JSON export differs from report')
    if json.loads((out/'report.json').read_text()) != report:
        raise AssertionError('Pico full JSON export differs from result')
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, default=Path('corpus-cache/aprs-pico'))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    path, digest = verified_source(args.cache_root, args.offline)
    out = args.cache_root/'results'
    report = analyze_audio(path, out, 20)
    observed = next(t for t in report['wideband_trials'] if t['decoder'] == 'afsk1200_ax25')
    print(json.dumps(dict(source_sha256=digest, analyzed_seconds=report['analyzed_seconds'],
                          observed_frame_hex=[f['hex'] for f in observed['frames']],
                          phase_trials=observed.get('phase_trials'),
                          crc_rejected=observed.get('crc_rejected_across_hypotheses'))))
    trial = validate_result(report, out)
    summary = dict(source_sha256=digest, analyzed_seconds=report['analyzed_seconds'],
                   checked_frames=len(trial['frames']), frame_hex=[f['hex'] for f in trial['frames']],
                   latitude_deg=EXPECTED_LATITUDE, longitude_deg=EXPECTED_LONGITUDE,
                   altitude_ft=1585, altitude_m=483.108)
    provenance = dict(source_url=SOURCE_URL, source_commit=PIN, source_bytes=SOURCE_BYTES,
                      source_git_blob_sha1=SOURCE_BLOB, source_sha256=digest,
                      recording_description=ROOT_URL+'/README.md', transmitter_configuration=ROOT_URL+'/src/aprs_pico_beacon_demo.c',
                      independent_encoder=ENCODER, license=ROOT_URL+'/LICENSE',
                      source_kind='laboratory analog line-output audio recorded by sound card; not off-air',
                      original_rf_iq=False, rf_center_hz=None,
                      oracle_basis='published transmitter configuration and independent base91/altitude encoder, not received geographic ground truth',
                      declared_transmitter_values=dict(latitude_deg=48.75588, longitude_deg=9.19011, altitude_m=483),
                      expected_payload_hex=EXPECTED_PAYLOAD.hex(), observed=summary,
                      input_processing='unmodified WAV imported automatically; ffmpeg mono resampling to 8 kHz; existing fixed-phase AFSK1200 trials',
                      scope='one static compressed-position profile and textual altitude through actual analog hardware; no RF link, telemetry, motion, live reception or verified geographic location')
    (out/'provenance.json').write_text(json.dumps(provenance, indent=2))
    (args.cache_root/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
