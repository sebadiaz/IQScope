"""Pinned independent laboratory receiver-audio regression, never original RF IQ."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqscope_audio import analyze_audio
from iqscope_pocsag import valid_codeword

PIN = '9c484c54d8afcde5357e1c170df43a865ac2bf7a'
COLLECTION = f'https://github.com/rrruark/POCSAG-Decoder/tree/{PIN}'
BLOB_ROOT = f'https://github.com/rrruark/POCSAG-Decoder/blob/{PIN}'
RECORDINGS = {
    0: (133256, '2852348f021f4da0f491fd9bc0d01e8619cad636280f5ee4ce241c9d7add6e65'),
    1: (133220, '3daafd73120d95a689389b1ea2584b7fcfdba36888cf3e39d4c70c4127aa04e6'),
    2: (133236, 'fa97d5f87bce6681a9acab8c352bbd643b7a7b537090b3577470289d5e220e6a'),
    3: (133200, '519f7b8c8499d9da1d9e6c110c2783100e4d8f00f979069a6946e6f7324f3a99'),
    4: (133234, 'cb4c19e17fb8a58f57d09133fc2d7180b4b275fbf63171339f17f1823672cfbd'),
    5: (176754, 'c5ddf278fd366805acbe9d0125e6bcabdcfd75d8ac511ef32155a1b32796a46b'),
    7: (176744, '4062fa24421ad7e3ef5950237670dcd2a604be975cf1a82f7018af0f3fb9febb'),
    8: (133204, '5f9659e434bea4851f1b40a5728564a0c8244370e05e19cd7814ebf7e51828ab'),
}
PUBLISHED_TEXT = 'This is a test of the pager. It should span a couple frames.'
# These two shorter outputs are development regression oracles from the
# received words, not completion of the author's published demonstration text.
SHORT_OUTPUTS = {5: 'This is a test of the pager. It should span a couple fram',
                 7: 'This is a test of the pager. It should span a'}


def verified_source(root, number, offline=False):
    name = f'pager_addr{number}.wav'
    size, digest = RECORDINGS[number]
    url = f'https://raw.githubusercontent.com/rrruark/POCSAG-Decoder/{PIN}/{name}'
    path = root/'lab'/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if offline:
        data = path.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(size+1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('POCSAG reference size/SHA-256 mismatch: '+name)
    if not offline:
        path.write_bytes(data)
    return path, url


def validate_result(report, out, number):
    trial = next(t for t in report['wideband_trials'] if t['decoder'] == 'pocsag')
    if len(trial['messages']) != 1:
        raise AssertionError('Expected exactly one checked recorded POCSAG message')
    message = trial['messages'][0]
    fields = message['fields']
    if (fields['capcode'], fields['function'], fields.get('text')) != (1100000+number, 3, SHORT_OUTPUTS.get(number, PUBLISHED_TEXT)):
        raise AssertionError('Recorded POCSAG content regression')
    if not all(valid_codeword(int(w, 16)) for w in message['codewords_hex']+[message['terminator_hex']]):
        raise AssertionError('Exported POCSAG word failed BCH/parity')
    if message['corrected_bits'] != 0 or not message['bch_valid'] or not message['even_parity_valid']:
        raise AssertionError('Unexpected correction/integrity claim')
    if (report['source_kind'] != 'receiver_audio' or report['center_frequency_hz'] is not None
            or message['channel'] is not None or message['frontend'] != 'receiver_audio_discriminator'):
        raise AssertionError('Demodulated receiver audio promoted to RF IQ')
    if json.loads((out/trial['artifact']).read_text()) != trial:
        raise AssertionError('POCSAG JSON export differs from report')
    return trial, message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, default=Path('corpus-cache/pocsag-radio'))
    parser.add_argument('--offline', action='store_true', help='Verify existing pinned WAVs without network')
    args = parser.parse_args()
    summary = {}
    for number, (size, digest) in RECORDINGS.items():
        path, url = verified_source(args.cache_root, number, args.offline)
        out = args.cache_root/'results'/path.stem
        report = analyze_audio(path, out, 20)
        trial, message = validate_result(report, out, number)
        provenance = dict(source_url=url, source_commit=PIN, source_sha256=digest, source_bytes=size,
                          collection=COLLECTION, license=BLOB_ROOT+'/LICENSE',
                          source_kind='laboratory receiver audio; RadioLib test transmissions recorded with GQRX, filtered and trimmed upstream',
                          author_description=BLOB_ROOT+'/README.md', original_rf_iq=False, rf_center_hz=None,
                          input_processing='WAV header; explicit ffmpeg mono resampling to 8 kHz; automatic level/clock recovery',
                          expected_text_basis='development oracle for shorter recorded output' if number in SHORT_OUTPUTS else 'author published demonstration sentence; per-file comparison is a development regression',
                          expected_capcode_basis='1100004 independently shown by author; remaining values checked as development regressions against received bits and filename suffix',
                          checked_messages=len(trial['messages']), message_capcode=message['fields']['capcode'],
                          observed_text=message['fields']['text'], measured_baud=message['baud'], corrected_bits=0,
                          scope='BCH/parity and standard IA5 only; no original IQ, authenticated sender, live network or broad paging validation')
        (out/'provenance.json').write_text(json.dumps(provenance, indent=2))
        summary[path.name] = dict(capcode=message['fields']['capcode'], text=message['fields']['text'],
                                  baud=message['baud'], checked_messages=1, source_sha256=digest,
                                  batch_count=len(message['batch_sync_bit_starts']))
    (args.cache_root/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(dict(recordings=len(summary), checked_messages=sum(v['checked_messages'] for v in summary.values()),
                          root=str(args.cache_root))))


if __name__ == '__main__':
    main()
