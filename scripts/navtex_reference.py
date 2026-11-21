"""Pinned original NAVTEX IQ regression, two-copy decisions and text exports."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iqscope import analyze,read_iq
from iqscope_formats import read_wave_iq,wave_layout
from sdrangel_corpus import download_prefix


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root',type=Path,default=Path('corpus-cache/navtex'))
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args();root=args.cache_root;root.mkdir(parents=True,exist_ok=True)
    reference=json.loads((Path(__file__).resolve().parents[1]/'corpus/navtex-reference.json').read_text())
    source=root/'source-prefix.wav';provenance_path=root/'provenance.json'
    if not source.exists():
        if args.offline:raise ValueError('Pinned NAVTEX IQ is absent')
        name,data,received=download_prefix(reference['archive_url'],reference['iq_prefix_limit'])
        source.write_bytes(data)
        provenance=dict(source_page=reference['source_page'],archive_url=reference['archive_url'],archive_member=name,
            compressed_bytes_received=received,excerpt_bytes=len(data),whole_archive_verified=False)
    else:
        provenance=json.loads(provenance_path.read_text()) if provenance_path.exists() else dict(whole_archive_verified=False)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=reference['iq_sha256'] or source.stat().st_size!=reference['iq_bytes']:
        raise ValueError('NAVTEX IQ changed; review source before updating reference')
    x,fs,center=read_wave_iq(source,seconds=reference['seconds'],allow_prefix=True)
    if (fs,center)!=(reference['sample_rate'],reference['center_frequency_hz']):raise AssertionError('NAVTEX WAV header changed')
    data_path=root/'source.sigmf-data';meta_path=root/'source.sigmf-meta';x.astype('<c8').tofile(data_path)
    meta_path.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs,'core:version':'1.2.0'},
        'captures':[{'core:sample_start':0,'core:frequency':center}],'annotations':[]},indent=2))
    restored,rate,frequency=read_iq(meta_path,limit_seconds=reference['seconds'])
    if rate!=fs or frequency!=center or not np.array_equal(restored,x):raise AssertionError('NAVTEX SigMF conversion changed IQ')
    report=analyze(meta_path,root/'results',seconds=reference['seconds'])
    trial=next(t for t in report['wideband_trials'] if t['decoder']=='sitor_b')
    if [m['text'] for m in trial['messages']]!=reference['expected_messages']:raise AssertionError('NAVTEX message text changed')
    if [m['header'] for m in trial['messages']]!=reference['expected_headers']:raise AssertionError('NAVTEX header changed')
    if abs(trial['messages'][0]['time_seconds']-reference['first_message_seconds'])>.02:raise AssertionError('NAVTEX source timing changed')
    for candidate in trial['candidates']:
        symbols=candidate['received_symbols']
        received=bytes(s['code'] for s in symbols)
        if (root/'results'/candidate['symbols_artifact']).read_bytes()!=received:raise AssertionError('Received CCIR words changed')
        if (root/'results'/candidate['text_artifact']).read_bytes()!=candidate['text'].encode():raise AssertionError('SITOR text export changed')
        for event in candidate['characters']:
            a=received[event['direct_symbol_index']];b=received[event['repeat_symbol_index']]
            if (a,b)!=(event['direct_code'],event['repeat_code']):raise AssertionError('Copy index changed')
            va=a.bit_count()==4;vb=b.bit_count()==4
            expected=None if (va and vb and a!=b) or not (va or vb) else a if va else b
            if event['selected_code']!=expected:raise AssertionError('A copy conflict was guessed or a received word repaired')
    for message in trial['messages']:
        if not message['framing_complete'] or not message['text_interpretation_complete']:raise AssertionError('NAVTEX reference became partial')
        if (root/'results'/message['artifact']).read_bytes()!=message['text'].encode():raise AssertionError('NAVTEX UTF-8 bytes changed')
    if json.loads((root/'results'/trial['artifact']).read_text())!=trial:raise AssertionError('NAVTEX JSON origin changed')
    provenance.update(excerpt_sha256=digest,layout=wave_layout(source,True),source_sample_count=len(x),
        sample_rate=fs,center_frequency_hz=center,sigmf_roundtrip_exact=True,source_window=report['source_window'],scope=reference['scope'])
    provenance_path.write_text(json.dumps(provenance,indent=2))
    summary=dict(candidate_hypotheses=len(trial['candidates']),message_headers=[m['header'] for m in trial['messages']],
        messages=[dict(station=m['station_designator'],subject=m['subject_designator'],serial=m['serial_text'],
            framing_complete=m['framing_complete'],text_interpretation_complete=m['text_interpretation_complete'],
            text_sha256=hashlib.sha256(m['text'].encode()).hexdigest(),time_seconds=m['time_seconds'],time_end_seconds=m['time_end_seconds'])
            for m in trial['messages']],evidence=[c['evidence'] for c in trial['candidates']],crc_present=False,
        scope=reference['scope'])
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()
