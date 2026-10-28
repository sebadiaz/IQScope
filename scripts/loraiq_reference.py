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
CSV_PREFIX_SHA256='96122f6ae2f1ff6b3ea8601a4d1e3336abab94e35cb6313a01fe5a16d6d135cf'
DATA_SHA256='954c295af3fa3e129eef981915401428bf22b401d5a9d414f4a316554f1f4bc4'
META_SHA256='92c4ca429c73e128f07de282a963eede7c1534f90ba7227c228bbe861ea5034d'
FIELDS=('sf','cr','fc','bandwidth','payload_base64','rrh_idx','rx_sample_rate','cfo','snr','sigmf_file','sigmf_file_offset','sigmf_file_n_samples')


def small_get(url,limit):
    with urllib.request.build_opener(SameHostRedirect()).open(url,timeout=30) as response:
        body=response.read(limit+1)
    if len(body)>limit:
        raise ValueError('Metadata exceeds the download limit')
    return body


def select_reference(rows):
    supported=[row for row in rows if row.get('sf')=='7' and row.get('cr')=='1' and float(row['bandwidth'])==125000]
    if not supported:
        raise ValueError('No supported reference in bounded annotation prefix')
    strong=[row for row in supported if float(row['snr'])>20]
    return strong[0] if strong else max(supported,key=lambda entry:float(entry['snr']))


def reference_stem(row):
    stem=row['sigmf_file'].removeprefix('./')
    if not re.fullmatch(r'sigmfs/[0-9_-]+/rrh[1-4]/[0-9]+',stem):
        raise ValueError('Unexpected annotation member path')
    return stem


def inspect_reference(rows,result):
    row=select_reference(rows)
    result['selection_rule']='First SF7/BW125k/CR1 row above annotated SNR20dB, otherwise highest SNR in prefix'
    result['selected_annotation']={key:row.get(key) for key in FIELDS}
    stem=reference_stem(row)
    expected=base64.b64decode(row['payload_base64'],validate=True)
    if not 1<=len(expected)<=255:
        raise ValueError('Expected payload length outside LoRa byte bound')
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
    if hashlib.sha256(meta_bytes).hexdigest()!=META_SHA256 or hashlib.sha256(data_bytes).hexdigest()!=DATA_SHA256:
        raise ValueError('Reference member hashes differ from the reviewed capture')
    meta=json.loads(meta_bytes)
    if hashlib.sha512(data_bytes).hexdigest()!=meta['global'].get('core:sha512'):
        raise ValueError('SigMF data SHA512 differs from publisher metadata')
    result['publisher_sigmf_sha512_verified']=True
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
    from iqscope import analyze_samples
    out=root/'analysis'
    report=analyze_samples(samples,fs,0,out,source=str(root/'source.sigmf-meta'))
    report['frequency_reference']='baseband_hz'
    report['center_frequency_verified']=False
    report['limitations'].insert(0,'Source SigMF frequency is numeric 862.5 with uncertain units; no verified RF center promoted.')
    report['reference_provenance']={'source_url':BASE,'doi':result['doi'],'license':result['license'],'creators':result['creators'],
        'source_data_sha256':result['data_sha256'],'source_metadata_sha256':result['meta_sha256'],
        'source_member':stem,'payload_matches_independent_annotation':result['automatic_payload_verified']}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    trial=next(trial for trial in report['wideband_trials'] if trial['decoder']=='lora_preamble')
    matches=[frame for frame in trial.get('frames',[]) if frame['payload_hex']==expected.hex()]
    if not matches or (out/matches[0]['artifact']).read_bytes()!=expected:
        raise ValueError('Main analysis/export differs from independent payload reference')
    result['main_pipeline_export_verified']=True
    result['main_pipeline_report']=str(out/'report.json')
    result['scope']='One whole independent SigMF member and main pipeline/export; no SF/BW/CFO/payload oracle given to detector'
    result['rf_center_policy']='Numeric 862.5 in source SigMF has uncertain units; use baseband only'
    result['archive_integrity_verified']=False


def main():
    result={'source':BASE,'checked_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Bounded independent IQ reference inspection and post-decode comparison; progress recorded explicitly'}
    try:
        record=json.loads(small_get('https://zenodo.org/api/records/'+RECORD,1024*1024))
        if str(record['id'])!=RECORD:
            raise ValueError('Unexpected record identity')
        metadata=record['metadata']
        result.update(title=metadata['title'],license=metadata.get('license'),doi=metadata.get('doi'),
                      creators=[entry.get('name') for entry in metadata.get('creators',[])],
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
        if hashlib.sha256(body).hexdigest()!=CSV_PREFIX_SHA256:
            raise ValueError('Annotation CSV prefix differs from the reviewed reference')
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
