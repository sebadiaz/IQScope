"""Pinned original-IQ AIS regression; optional independent message-field oracle."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iqscope import analyze
from iqscope_ais import checked_ais_packet
from sdrangel_corpus import download_prefix


def nmea_for_oracle(payload):
    # Presentation adapter only. These sentences were NOT supplied by the IQ publisher.
    bits=''.join(f'{v:08b}' for v in payload);fill=(-len(bits))%6;bits+='0'*fill
    text=''
    for i in range(0,len(bits),6):
        value=int(bits[i:i+6],2);text+=chr(value+48 if value<40 else value+56)
    chunks=[text[i:i+60] for i in range(0,len(text),60)];out=[]
    for index,chunk in enumerate(chunks,1):
        line=f'AIVDM,{len(chunks)},{index},{"0" if len(chunks)>1 else ""},A,{chunk},{fill if index==len(chunks) else 0}'
        check=0
        for c in line:check^=ord(c)
        out.append('!'+line+f'*{check:02X}')
    return out


def compare_oracle(trial):
    from pyais import decode
    version=importlib.metadata.version('pyais')
    if version!='3.3.1':raise ValueError('Reference oracle requires pyais==3.3.1')
    results=[];checked=0
    for frame in trial['frames']:
        nmea=nmea_for_oracle(bytes.fromhex(frame['hex'])[:-2]);oracle=decode(*nmea).asdict();fields=frame['fields']
        for ours,theirs in [('message_type','msg_type'),('mmsi','mmsi'),('longitude_deg','lon'),('latitude_deg','lat'),
                           ('speed_over_ground_knots','speed'),('course_over_ground_deg','course'),
                           ('true_heading_deg','heading'),('ship_name','shipname'),('callsign','callsign')]:
            if ours not in fields or fields[ours] is None or theirs not in oracle:continue
            a,b=fields[ours],oracle[theirs]
            if isinstance(a,(int,float)) and isinstance(b,(int,float)):equal=abs(a-b)<1e-6
            else:equal=a.strip()==b.strip()
            if not equal:raise AssertionError(f'AIS oracle disagrees on {ours}: {a!r} != {b!r}')
            checked+=1
        results.append(dict(hex=frame['hex'],offset_hz=frame['channel']['offset_hz'],generated_nmea=nmea,oracle=oracle))
    return dict(oracle='pyais',version=version,checked_fields=checked,frames=len(results),results=results,
        scope='Independent message-field interpretation only; generated NMEA, no independent RF reception or authenticated positions.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root',type=Path,default=Path('corpus-cache/ais'))
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--oracle',action='store_true')
    args=parser.parse_args();root=args.cache_root;root.mkdir(parents=True,exist_ok=True)
    reference=json.loads((Path(__file__).resolve().parents[1]/'corpus/ais-reference.json').read_text())
    source=root/'source-prefix.sdriq';provenance_path=root/'provenance.json'
    if not source.exists():
        if args.offline:raise ValueError('Pinned AIS prefix is absent')
        name,data,downloaded=download_prefix(reference['archive_url'],16*1024*1024)
        source.write_bytes(data)
        provenance=dict(source_page=reference['source_page'],archive_url=reference['archive_url'],archive_member=name,
                        compressed_bytes_received=downloaded,excerpt_bytes=len(data),whole_archive_verified=False)
    else:provenance=json.loads(provenance_path.read_text()) if provenance_path.exists() else dict(whole_archive_verified=False)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=reference['excerpt_sha256_16m']:raise ValueError('AIS IQ prefix changed; review source before updating the reference')
    report=analyze(source,root/'results',seconds=10)
    if report['sample_rate']!=reference['sample_rate'] or report['center_frequency_hz']!=reference['center_frequency_hz']:
        raise AssertionError('AIS source header changed')
    trial=next(t for t in report['wideband_trials'] if t['decoder']=='ais_gmsk')
    for channel,expected in reference['expected_frames_by_channel'].items():
        actual=[f['hex'] for f in trial['frames'] if f['channel']['ais_channel']==channel]
        if actual!=expected:raise AssertionError(f'AIS channel {channel} regression changed: {len(actual)} != {len(expected)}')
    for frame in trial['frames']:
        packet=bytes.fromhex(frame['hex'])
        if checked_ais_packet(packet)!=frame['fields']:raise AssertionError('AIS fields differ from received bytes')
        if (root/'results'/frame['wire_artifact']).read_bytes()!=packet:raise AssertionError('AIS received octets changed')
    if json.loads((root/'results'/trial['artifact']).read_text())!=trial:raise AssertionError('AIS artifact origin changed')
    if args.oracle:
        proof=compare_oracle(trial);(root/'oracle-proof.json').write_text(json.dumps(proof,indent=2,default=str))
    provenance.update(excerpt_sha256=digest,sample_rate=report['sample_rate'],center_frequency_hz=report['center_frequency_hz'],
                      source_window=report['source_window'],scope=reference['scope'])
    provenance_path.write_text(json.dumps(provenance,indent=2))
    summary=dict(frame_observations=len(trial['frames']),channel_a=43,channel_b=38,
        unassigned_rf_observations=sum(f['channel']['ais_channel'] is None for f in trial['frames']),
        oracle='pyais 3.3.1 message fields' if args.oracle else None,
        scope='Bounded IQ development regression; not an independent packet total or authenticated vessel data.')
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()
