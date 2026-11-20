"""Pinned historical APT IQ regression, numeric images and lossless source conversion."""
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
    parser.add_argument('--cache-root',type=Path,default=Path('corpus-cache/apt'))
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args();root=args.cache_root;root.mkdir(parents=True,exist_ok=True)
    reference=json.loads((Path(__file__).resolve().parents[1]/'corpus/apt-reference.json').read_text())
    source=root/'source-prefix.wav';provenance_path=root/'provenance.json'
    if not source.exists():
        if args.offline:raise ValueError('Pinned APT IQ prefix is absent')
        name,data,received=download_prefix(reference['archive_url'],16*1024*1024)
        source.write_bytes(data)
        provenance=dict(source_page=reference['source_page'],archive_url=reference['archive_url'],
            archive_member=name,compressed_bytes_received=received,excerpt_bytes=len(data),whole_archive_verified=False)
    else:
        provenance=json.loads(provenance_path.read_text()) if provenance_path.exists() else dict(whole_archive_verified=False)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=reference['excerpt_sha256_16m']:raise ValueError('APT IQ prefix changed; review before updating reference')
    layout=wave_layout(source,allow_prefix=True)
    x,fs,center=read_wave_iq(source,seconds=reference['seconds'],allow_prefix=True)
    if (fs,center)!=(reference['sample_rate'],reference['center_frequency_hz']):raise AssertionError('APT source header changed')
    # Export only complete received samples; a deliberately truncated RIFF prefix
    # must not be offered to the ordinary import reader as a complete WAV.
    data_path=root/'source.sigmf-data';meta_path=root/'source.sigmf-meta'
    x.astype('<c8').tofile(data_path)
    meta_path.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs,'core:version':'1.2.0'},
        'captures':[{'core:sample_start':0,'core:frequency':center}],'annotations':[]},indent=2))
    restored,rate,frequency=read_iq(meta_path,limit_seconds=reference['seconds'])
    if rate!=fs or frequency!=center or not np.array_equal(restored,x):raise AssertionError('APT SigMF conversion changed samples')
    report=analyze(meta_path,root/'results',seconds=reference['seconds'])
    trial=next(t for t in report['wideband_trials'] if t['decoder']=='noaa_apt')
    if len(trial['images'])!=1:raise AssertionError('Expected one APT image strip')
    image=trial['images'][0]
    if (image['width'],image['height'])!=(2080,reference['expected_lines']):raise AssertionError('APT line count changed')
    for key,expected in [('time_seconds','first_line_seconds'),('time_end_seconds','last_line_end_seconds')]:
        if abs(image[key]-reference[expected])>2/4160:raise AssertionError('APT line origin changed')
    pixels=np.frombuffer(bytes.fromhex(image['pixels_u8_hex']),dtype='u1').reshape(image['height'],2080)
    differences={}
    for key,(lo,hi) in image['channel_image_columns'].items():
        profile=np.array([[float(np.median(part)) for part in np.array_split(row,8)] for row in pixels[:,lo:hi]])
        difference=float(np.max(abs(profile-np.array(reference['image_profile_median_8_columns'][key]))))
        if difference>reference['profile_tolerance']:raise AssertionError(f'APT {key} numeric image profile changed')
        differences[key]=difference
    if (root/'results'/image['artifacts']['pixels']).read_bytes()!=pixels.tobytes():raise AssertionError('APT pixel export changed')
    csv=np.loadtxt(root/'results'/image['artifacts']['csv'],delimiter=',',dtype='u1')
    if not np.array_equal(csv,pixels):raise AssertionError('APT CSV differs from binary pixels')
    if json.loads((root/'results'/trial['artifact']).read_text())!=trial:raise AssertionError('APT JSON origin changed')
    provenance.update(excerpt_sha256=digest,layout=layout,source_sample_count=len(x),sample_rate=fs,
        center_frequency_hz=center,sigmf_roundtrip_exact=True,source_window=report['source_window'],scope=reference['scope'])
    provenance_path.write_text(json.dumps(provenance,indent=2))
    summary=dict(lines=image['height'],full_width=2080,channel_width=909,
        time_seconds=image['time_seconds'],time_end_seconds=image['time_end_seconds'],
        min_sync_a_correlation=min(min(l['sync_a_correlation'],l['next_sync_a_correlation']) for l in image['lines']),
        min_sync_b_correlation=min(l['sync_b_correlation'] for l in image['lines']),
        profile_max_difference=differences,pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        scope=reference['scope'])
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()
