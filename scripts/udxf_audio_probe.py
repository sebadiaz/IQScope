"""Bounded UDXF MP3 inspection and experimental CW trials on analytic audio.

This is not an IQ importer. The analytic signal of receiver audio does not
recover the original RF bandwidth, center frequency, phase or sideband sense.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request

import numpy as np
from scipy import signal
from iqscope_cw import search_cw
from iqscope_audio import decode_audio, analyze_audio


def read_prefix(response,limit=1024*1024):
    if not 4096<=limit<=2*1024*1024:
        raise ValueError('Audio prefix budget must be 4 KiB to 2 MiB')
    chunks = []
    received = 0
    while received<limit:
        part = response.read(min(65536,limit-received))
        if not part:
            break
        chunks.append(part)
        received += len(part)
    return b''.join(chunks)


def inspect_audio(audio,fs):
    analytic = signal.hilbert(audio)
    cw = search_cw(analytic,fs,center_hz=0)
    return {'input_kind':'receiver_audio_not_rf_iq','audio_sample_rate_hz':fs,
            'decoded_audio_seconds':len(audio)/fs,
            'audio_rms':float(np.sqrt(np.mean(np.asarray(audio,dtype=float)**2))),
            'cw_trial':cw,'independently_verified_text':None,
            'validation_scope':'audio decoding and experimental CW timing candidates only',
            'limitations':['Analytic audio is derived from real receiver audio, not original RF IQ.',
                           'Lossy MP3, receiver filtering and unknown sideband can affect decoding.',
                           'Source station/mode labels and any recovered text remain unverified.',
                           'No Link-11, MIL-STD-110A, Akula, voice transcription or protected payload decoding is implemented.']}


def probe(entry,out,limit=1024*1024):
    request = urllib.request.Request(entry['url'],headers={'Range':f'bytes=0-{limit-1}',
                                                         'User-Agent':'IQScope-audio-probe/0.9'})
    with urllib.request.urlopen(request,timeout=30) as response:
        status = response.status
        content_type = response.headers.get('Content-Type','')
        prefix = read_prefix(response,limit)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'prefix.mp3'
        path.write_bytes(prefix)
        audio,fs = decode_audio(path)
        ui_report = analyze_audio(path,Path(directory)/'results')
    result = {'dataset_id':'udxf_uc4','entry_id':entry['id'],'source_page':'https://www.udxf.nl/uc4.html',
              'source_url':entry['url'],'source_label':entry['source_label'],
              'source_mode_hint':entry['source_mode_hint'],'source_labels_independently_verified':False,
              'http_status':status,'http_content_type':content_type,
              'received_bytes':len(prefix),'download_limit_bytes':limit,
              'prefix_sha256':hashlib.sha256(prefix).hexdigest(),'whole_source_integrity_verified':False,
              'ui_audio_import_check':{'source_kind':ui_report['source_kind'],
                  'frequency_reference':ui_report['frequency_reference'],
                  'rf_center_is_null':ui_report['center_frequency_hz'] is None,
                  'cw_status':ui_report['wideband_trials'][0]['status']},
              **inspect_audio(audio,fs)}
    out = Path(out)/entry['id']
    out.mkdir(parents=True,exist_ok=True)
    (out/'provenance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',action='append',default=[])
    parser.add_argument('--out',default='corpus-cache/udxf-audio')
    parser.add_argument('--manifest',default=str(Path(__file__).resolve().parents[1]/'corpus/udxf_uc4.json'))
    args = parser.parse_args()
    entries = json.loads(Path(args.manifest).read_text())['entries']
    selected = args.name or [e['id'] for e in entries if e['probe_default']]
    known = {e['id']:e for e in entries}
    if set(selected)-known.keys():
        parser.error('Unknown UDXF entry')
    for name in selected:
        probe(known[name],args.out)


if __name__=='__main__':
    main()
