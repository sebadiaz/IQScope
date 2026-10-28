"""Inspect an independent LoRaIQ reference with strict metadata/download bounds."""
import base64
import math
import re
import zipfile
import numpy as np
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
from datetime import datetime,timezone
from mendeley_metadata_probe import SameHostRedirect
from fpv_metadata_probe import RangeReader

RECORD='20341802'
BASE='https://zenodo.org/records/'+RECORD
FIELDS=('sf','cr','fc','bandwidth','payload_base64','rrh_idx','rx_sample_rate','cfo','snr','sigmf_file','sigmf_file_offset','sigmf_file_n_samples')


def small_get(url,limit):
    with urllib.request.build_opener(SameHostRedirect()).open(url,timeout=30) as response:
        body=response.read(limit+1)
    if len(body)>limit:
        raise ValueError('Metadata exceeds the download limit')
    return body


def inspect_reference(rows,result):
    supported=[row for row in rows if row.get('sf')=='7' and row.get('cr')=='1' and float(row['bandwidth'])==125000]
    if not supported:
        raise ValueError('No supported reference in bounded annotation prefix')
    strong=[row for row in supported if float(row['snr'])>20]
    row=strong[0] if strong else max(supported,key=lambda entry:float(entry['snr']))
    result['selection_rule']='First SF7/BW125k/CR1 row above annotated SNR20dB, otherwise highest SNR in prefix'
    result['selected_annotation']={key:row.get(key) for key in FIELDS}
    stem=row['sigmf_file'].removeprefix('./')
    if not re.fullmatch(r'sigmfs/[0-9_-]+/rrh[1-4]/[0-9]+',stem):
        raise ValueError('Unexpected annotation member path')
    expected=base64.b64decode(row['payload_base64'],validate=True)
    archive_url=BASE+'/files/sigmfs.zip?download=1&iqscope=reference'
    with RangeReader(archive_url,budget=48*1024*1024) as remote:
        if remote.size!=71002741525:
            raise ValueError('Archive size differs from publisher inventory')
        with zipfile.ZipFile(remote) as archive:
            members=archive.infolist()
            result['archive_members']=len(members)
            result['archive_example_paths']=[member.filename for member in members[:5]]
            def member(suffix,limit):
                matches=[entry for entry in members if entry.filename==stem+suffix]
                if len(matches)!=1 or not 0<matches[0].file_size<=limit:
                    raise ValueError('Missing/duplicated or oversized reference member: '+stem+suffix)
                item=matches[0]
                if item.flag_bits&1:
                    raise ValueError('Encrypted ZIP member not supported')
                with archive.open(item) as stream:
                    body=stream.read(limit+1)
                if len(body)!=item.file_size:
                    raise ValueError('Incomplete reference member')
                return body
            meta_bytes=member('.sigmf-meta',65536)
            data_bytes=member('.sigmf-data',8*1024*1024)
            result['archive_bytes_transferred']=remote.received
    meta=json.loads(meta_bytes)
    result['sigmf_global']=meta['global']
    result['sigmf_captures']=meta.get('captures')
    result['data_sha256']=hashlib.sha256(data_bytes).hexdigest()
    result['meta_sha256']=hashlib.sha256(meta_bytes).hexdigest()
    result['member_zip_crc_verified']=True
    root=Path('corpus-cache/loraiq')
    root.mkdir(parents=True,exist_ok=True)
    (root/'source.sigmf-meta').write_bytes(meta_bytes)
    (root/'source.sigmf-data').write_bytes(data_bytes)
    from iqscope import read_iq
    from iqscope_lora import detect_lora_preamble
    samples,fs,center=read_iq(root/'source.sigmf-meta')
    if fs!=float(row['rx_sample_rate']):
        raise ValueError('SigMF and annotation sampling rates disagree')
    result['source_sample_count']=len(samples)
    result['sample_rate_hz']=fs
    result['reference_payload_hex']=expected.hex()
    modes=[('whole_member_blind',samples)]
    start=max(0,int(math.floor(float(row['sigmf_file_offset'])))-int(fs*128/125000))
    end=min(len(samples),int(math.ceil(float(row['sigmf_file_offset'])))+int(row['sigmf_file_n_samples'])+int(fs*128/125000))
    modes.append(('annotation_window_only',samples[start:end]))
    result['decodes']=[]
    for mode,x in modes:
        trial=detect_lora_preamble(x,fs)
        entry={'mode':mode,'input_samples':len(x),'trial':trial,
               'payload_matches_reference':any(frame['payload_hex']==expected.hex() for frame in trial.get('frames',[])),
               'oracle_parameters_applied':[] if mode=='whole_member_blind' else ['annotation time window only']}
        result['decodes'].append(entry)
    result['automatic_payload_verified']=result['decodes'][0]['payload_matches_reference']
    result['scope']='One independent whole SigMF member and annotated frame window; no SF/BW/CFO/payload oracle given to detector'
    result['archive_integrity_verified']=False


def main():
    result={'source':BASE,'checked_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Public metadata, small loader document and 128 KiB CSV prefix; no IQ downloaded'}
    try:
        record=json.loads(small_get('https://zenodo.org/api/records/'+RECORD,1024*1024))
        if str(record['id'])!=RECORD:
            raise ValueError('Unexpected record identity')
        metadata=record['metadata']
        result.update(title=metadata['title'],license=metadata.get('license'),doi=metadata.get('doi'),
                      files=[{k:f.get(k) for k in ('key','size','checksum')} for f in record['files']])
        if metadata.get('license',{}).get('id')!='cc-by-4.0':
            raise ValueError('Expected CC BY 4.0; source licence needs review')
        loader=next(f for f in record['files'] if f['key']=='load_and_plot_samples.py')
        body=small_get(BASE+'/files/load_and_plot_samples.py?download=1',16384)
        if len(body)!=loader['size'] or 'md5:'+hashlib.md5(body).hexdigest()!=loader['checksum']:
            raise ValueError('Loader document integrity differs from publisher inventory')
        result['loader_document']={'sha256':hashlib.sha256(body).hexdigest(),'text':body.decode()}
        with RangeReader(BASE+'/files/dataset.csv?download=1&iqscope=reference',budget=262144) as remote:
            body=remote.read(131072)
            result['csv_total_bytes']=remote.size
        prefix=body[:body.rfind(b'\n')+1].decode('utf-8-sig')
        reader=csv.DictReader(io.StringIO(prefix))
        rows=list(reader)
        result.update(csv_prefix_sha256=hashlib.sha256(body).hexdigest(),csv_prefix_bytes=len(body),
                      columns=reader.fieldnames,rows_in_prefix=len(rows),
                      reference_rows=[{key:row.get(key) for key in FIELDS} for row in rows[:20]])
        inspect_reference(rows,result)
    except Exception as exc:
        result['error']=str(exc)
    out=Path('corpus-cache/loraiq/observation.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    if 'error' in result or result.get('automatic_payload_verified') is False:
        raise SystemExit(1)


if __name__=='__main__':
    main()
