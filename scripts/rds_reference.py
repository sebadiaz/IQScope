"""Pinned original multi-station IQ RDS regression; strict received groups and PS."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iqscope import analyze,read_iq
from iqscope_formats import read_wave_iq,wave_layout
from iqscope_rds import checked_rds_group
from sdrangel_corpus import download_prefix


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root',type=Path,default=Path('corpus-cache/rds'))
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args();root=args.cache_root;root.mkdir(parents=True,exist_ok=True)
    reference=json.loads((Path(__file__).resolve().parents[1]/'corpus/rds-reference.json').read_text())
    source=root/'source-prefix.wav';provenance_path=root/'provenance.json'
    if not source.exists():
        if args.offline:raise ValueError('Pinned RDS IQ prefix is absent')
        name,data,received=download_prefix(reference['archive_url'],32*1024*1024)
        source.write_bytes(data)
        provenance=dict(source_page=reference['source_page'],archive_url=reference['archive_url'],archive_member=name,
            compressed_bytes_received=received,excerpt_bytes=len(data),whole_archive_verified=False)
    else:
        provenance=json.loads(provenance_path.read_text()) if provenance_path.exists() else dict(whole_archive_verified=False)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=reference['excerpt_sha256_32m']:raise ValueError('FM IQ prefix changed; review before updating reference')
    x,fs,center=read_wave_iq(source,seconds=reference['seconds'],allow_prefix=True)
    if (fs,center)!=(reference['sample_rate'],reference['center_frequency_hz']):raise AssertionError('FM source header changed')
    data_path=root/'source.sigmf-data';meta_path=root/'source.sigmf-meta'
    x.astype('<c8').tofile(data_path)
    meta_path.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs,'core:version':'1.2.0'},
        'captures':[{'core:sample_start':0,'core:frequency':center}],'annotations':[]},indent=2))
    restored,rate,frequency=read_iq(meta_path,limit_seconds=reference['seconds'])
    if rate!=fs or frequency!=center or not np.array_equal(restored,x):raise AssertionError('FM SigMF conversion changed IQ')
    del restored,x
    report=analyze(meta_path,root/'results',seconds=reference['seconds'])
    trial=next(t for t in report['wideband_trials'] if t['decoder']=='rds_fm')
    for pi,expected in reference['expected_frames_by_pi'].items():
        actual=[f['hex'] for f in trial['frames'] if f['fields']['pi_hex']==pi]
        if actual!=expected:raise AssertionError(f'RDS {pi} received groups changed: {len(actual)} != {len(expected)}')
        station=next(s for s in trial['stations'] if s['pi_hex']==pi)
        if not station['ps']['complete'] or station['ps']['text']!=reference['expected_ps'][pi]:raise AssertionError('RDS PS changed')
    for frame in trial['frames']:
        data=bytes.fromhex(frame['hex'])
        if checked_rds_group(data)!=frame['fields']:raise AssertionError('RDS fields differ from received bits')
        if (root/'results'/frame['wire_artifact']).read_bytes()!=data:raise AssertionError('RDS 104-bit export changed')
        words=bytes.fromhex(''.join(frame['fields']['information_words_hex']))
        if (root/'results'/frame['payload_artifact']).read_bytes()!=words:raise AssertionError('RDS information words changed')
    if json.loads((root/'results'/trial['artifact']).read_text())!=trial:raise AssertionError('RDS JSON origin changed')
    provenance.update(excerpt_sha256=digest,layout=wave_layout(source,True),source_sample_count=8000000,
        sample_rate=fs,center_frequency_hz=center,sigmf_roundtrip_exact=True,source_window=report['source_window'],scope=reference['scope'])
    provenance_path.write_text(json.dumps(provenance,indent=2))
    summary=dict(group_observations=len(trial['frames']),crc_checked_blocks=4*len(trial['frames']),
        stations=[dict(pi=s['pi_hex'],ps=s['ps']['text'],groups=s['groups'],radiotext_complete=s['radiotext']['complete']) for s in trial['stations']],
        deferred_channels=trial['deferred_channel_count'],scope=reference['scope'])
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()
