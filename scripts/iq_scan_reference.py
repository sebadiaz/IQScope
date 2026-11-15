"""Check automatic traversal of the already pinned original-IQ reference."""
import argparse
import json
from pathlib import Path

from aprs_iq_reference import EXPECTED_HEX,source_wave
from iqscope_scan import scan_file
from iqscope_ax25 import crc_x25


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root',type=Path,default=Path('corpus-cache/aprs-iq'))
    parser.add_argument('--out',type=Path,default=Path('corpus-cache/iq-file-scan'))
    args=parser.parse_args()
    path,provenance=source_wave(args.cache_root,offline=True)
    result=scan_file(path,args.out,seconds=10,max_windows=4)
    if result['status']!='source_end_reached' or not result['coverage']['whole_file_read']:
        raise AssertionError('Pinned IQ scan did not read through the source')
    if [w['start_sample'] for w in result['windows']]!=[0,195310,390620]:
        raise AssertionError('Pinned IQ scan overlap or sample positions changed')
    counts=[];received=set()
    for window in result['windows']:
        report=json.loads((args.out/window['report_artifact']).read_text())
        trial=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_fm_ax25')
        counts.append(len(trial['frames']))
        if trial['source_window_reference']['start_sample']!=window['start_sample']:
            raise AssertionError('Per-window decoder provenance was lost')
        for frame in trial['frames']:
            raw=bytes.fromhex(frame['hex'])
            if not frame['fcs_valid'] or crc_x25(raw[:-2])!=int.from_bytes(raw[-2:],'little'):
                raise AssertionError('Scan frame FCS failed')
            if frame['fields']['pid'] is not None or frame['fields']['payload_hex']:
                raise AssertionError('Scan selected ambiguous connected-mode application data')
            received.add(frame['hex'])
    if counts!=[3,5,2] or received!=set(EXPECTED_HEX):
        raise AssertionError('Pinned IQ scan frame regression changed')
    provenance['scope']='Original-IQ development regression: 3/5/2 overlapping observations, five distinct known frame byte strings; not an independent total or exhaustive decoder coverage.'
    (args.out/'provenance.json').write_text(json.dumps(provenance,indent=2))
    print(json.dumps(dict(windows=3,frame_observations=counts,distinct_frame_bytes=5,
                         whole_iq_source_read=True,exhaustive_packet_recovery=False)))


if __name__=='__main__':main()
