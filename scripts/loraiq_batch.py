"""Deterministic, bounded real-capture benchmark; decode misses remain in results."""
import base64
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile
from loraiq_reference import BASE, RECORD, CSV_PREFIX_SHA256, FIELDS, small_get, reference_stem
from fpv_metadata_probe import RangeReader


def select_batch(rows):
    """First distinct member in each SNR stratum, never selected by payload/CRC."""
    selected=[]
    seen=set()
    for lower,upper in ((-math.inf,0),(0,5),(5,10),(10,15),(15,20),(20,math.inf)):
        for row in rows:
            if row.get('sf')!='7' or row.get('cr')!='1' or float(row['bandwidth'])!=125000:
                continue
            snr=float(row['snr'])
            stem=reference_stem(row)
            if lower<=snr<upper and stem not in seen:
                selected.append((f'[{lower},{upper}) dB',row))
                seen.add(stem)
                break
    return selected


def compare_frames(frames,rows,stem,fs):
    """Post-decode interval matching; payload bytes never choose an annotation."""
    comparisons=[]
    for frame in frames:
        parameters=frame['parameters']
        matches=[]
        for row in rows:
            if reference_stem(row)!=stem:
                continue
            if (float(row['rx_sample_rate'])!=fs or int(row['sf'])!=parameters['spreading_factor']
                    or float(row['bandwidth'])!=parameters['bandwidth_hz']
                    or frame.get('coding_rate')!=f"4/{4+int(row['cr'])}"):
                continue
            start=float(row['sigmf_file_offset'])/fs
            end=start+float(row['sigmf_file_n_samples'])/fs
            if start<=frame['time_seconds']<end:
                matches.append(row)
        item={'time_seconds':frame['time_seconds'],'payload_hex':frame['payload_hex'],
              'annotation_candidates':len(matches),'status':'no_annotation_in_prefix'}
        if len(matches)>1:
            item['status']='ambiguous_annotation'
        elif len(matches)==1:
            row=matches[0]
            expected=base64.b64decode(row['payload_base64'],validate=True).hex()
            item.update(annotation={key:row.get(key) for key in FIELDS},expected_payload_hex=expected,
                        status='exact_match' if frame['payload_hex']==expected else 'payload_mismatch')
        comparisons.append(item)
    return comparisons


def run(result):
    record=json.loads(small_get('https://zenodo.org/api/records/'+RECORD,1024*1024))
    metadata=record['metadata']
    if str(record['id'])!=RECORD or metadata.get('license',{}).get('id')!='cc-by-4.0':
        raise ValueError('Record identity or license changed')
    result.update(source=BASE,doi=metadata['doi'],license=metadata['license'],
                  creators=[entry['name'] for entry in metadata['creators']])
    with RangeReader(BASE+'/files/dataset.csv?download=1&iqscope=reference',budget=262144) as remote:
        body=remote.read(131072)
    if hashlib.sha256(body).hexdigest()!=CSV_PREFIX_SHA256:
        raise ValueError('Reviewed CSV prefix changed')
    rows=list(csv.DictReader(io.StringIO(body[:body.rfind(b'\n')+1].decode('utf-8-sig'))))
    selection=select_batch(rows)
    if not selection:
        raise ValueError('No eligible references')
    result.update(csv_prefix_sha256=CSV_PREFIX_SHA256,rows_in_prefix=len(rows),
        selection_rule='First distinct member per SNR stratum [-inf,0),[0,5),[5,10),[10,15),[15,20),[20,inf); SF7/BW125k/CR1 only',
        selected_count=len(selection),observations=[])
    from iqscope import read_iq
    from iqscope_lora import detect_lora_preamble
    root=Path('corpus-cache/loraiq-batch')
    root.mkdir(parents=True,exist_ok=True)
    with RangeReader(BASE+'/files/sigmfs.zip?download=1&iqscope=batch',budget=224*1024*1024) as remote:
        if remote.size!=71002741525:
            raise ValueError('Archive size changed')
        with zipfile.ZipFile(remote) as archive:
            index={}
            for item in archive.infolist():
                index.setdefault(item.filename,[]).append(item)
            def member(name,limit):
                entries=index.get(name,[])
                if len(entries)!=1 or entries[0].flag_bits&1 or not 0<entries[0].file_size<=limit:
                    raise ValueError('Invalid member '+name+': '+str([(e.filename,e.file_size,e.flag_bits) for e in entries]))
                with archive.open(entries[0]) as stream:
                    data=stream.read(limit+1)
                if len(data)!=entries[0].file_size:
                    raise ValueError('Incomplete member')
                return data
            for number,(stratum,row) in enumerate(selection):
                entry={'stratum':stratum,'annotation':{key:row.get(key) for key in FIELDS}}
                result['observations'].append(entry)
                stem=reference_stem(row)
                meta_bytes=member(stem+'.sigmf-meta',65536)
                data=member(stem+'.sigmf-data',32*1024*1024)
                meta=json.loads(meta_bytes)
                if hashlib.sha512(data).hexdigest()!=meta['global'].get('core:sha512'):
                    raise ValueError('Publisher SigMF SHA512 mismatch: '+stem)
                entry.update(data_sha256=hashlib.sha256(data).hexdigest(),meta_sha256=hashlib.sha256(meta_bytes).hexdigest(),
                    publisher_sha512_verified=True,zip_member_crc_verified=True)
                folder=root/str(number)
                folder.mkdir(exist_ok=True)
                (folder/'source.sigmf-meta').write_bytes(meta_bytes)
                (folder/'source.sigmf-data').write_bytes(data)
                samples,fs,_=read_iq(folder/'source.sigmf-meta')
                if fs!=float(row['rx_sample_rate']):
                    raise ValueError('Sampling rate disagreement')
                # No reference payload, timing, CFO, SF, BW or CR is passed to the detector.
                trial=detect_lora_preamble(samples,fs)
                expected=base64.b64decode(row['payload_base64'],validate=True).hex()
                frames=trial.get('frames',[])
                comparisons=compare_frames(frames,rows,stem,fs)
                entry.update(input_samples=len(samples),sample_rate_hz=fs,trial=trial,
                    expected_payload_hex=expected,payload_matches_reference=any(c['status']=='exact_match' and c['annotation']==entry['annotation'] for c in comparisons),
                    crc_valid_other_payloads=[f['payload_hex'] for f in frames if f['payload_hex']!=expected],
                    oracle_parameters_applied=[],frame_reference_comparisons=comparisons)
        result['archive_bytes_transferred']=remote.received
    result['matched_count']=sum(entry['payload_matches_reference'] for entry in result['observations'])
    result['missed_count']=len(selection)-result['matched_count']
    result['frame_reference_counts']={status:sum(c['status']==status for e in result['observations'] for c in e['frame_reference_comparisons'])
        for status in ('exact_match','payload_mismatch','ambiguous_annotation','no_annotation_in_prefix')}
    result['limitations']=['Small bounded CSV prefix; not a representative population or sensitivity curve.',
        'Whole-member blind decoding only; no RF center verified; no guided timing/CFO correction.',
        'Only SF7/BW125k/CR4/5; unoccupied SNR strata omitted. Full archive hash not verified.',
        'Decoder misses are benchmark outcomes; transport/integrity errors fail the job.']


def main():
    result={}
    try:
        run(result)
    except Exception as exc:
        result['error']=str(exc)
    path=Path('corpus-cache/loraiq-batch/observation.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    if 'error' in result:
        raise SystemExit(1)


if __name__=='__main__':
    main()
