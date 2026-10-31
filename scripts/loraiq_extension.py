"""Frozen-decoder first-pass benchmark on four previously unused sessions."""
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
from loraiq_reference import BASE,RECORD,FIELDS,reference_stem,small_get
from loraiq_batch import compare_frames
from fpv_metadata_probe import RangeReader


def select_extension(rows):
    selected=[]
    seen={('7','125000','1'):set(),('10','250000','1'):set()}
    for row in rows:
        config=(row.get('sf'),row.get('bandwidth'),row.get('cr'))
        session=reference_stem(row).split('/')[1]
        if config not in seen or session=='25_01_17-13_40' or session in seen[config] or len(seen[config])>=2:
            continue
        seen[config].add(session)
        selected.append({key:row.get(key) for key in FIELDS})
    return selected


def verify_pipeline_export(samples,fs,folder,row,rows,stem):
    from iqscope import analyze_samples
    report=analyze_samples(samples,fs,0,folder/'analysis')
    trial=next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
    frames=trial.get('frames',[])
    comparisons=compare_frames(frames,rows,stem,fs)
    for frame,comparison in zip(frames,comparisons):
        if comparison['status']=='exact_match' and comparison['annotation']==row:
            expected=bytes.fromhex(comparison['expected_payload_hex'])
            if (folder/'analysis'/frame['artifact']).read_bytes()!=expected:
                raise ValueError('Main pipeline binary export differs from reference')
            return {'verified':True,'payload_bytes':len(expected),'frequency_reference':'baseband_hz',
                    'center_frequency_verified':False,'artifact':frame['artifact']}
    raise ValueError('Main pipeline missed the independently matched reference')


def run(result):
    manifest=json.loads(Path('corpus/loraiq-extension-manifest.json').read_text())
    actual_hashes={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in manifest['decoder_file_sha256']}
    import numpy,scipy
    result.update(decoder_file_sha256=actual_hashes,decoder_matches_frozen=actual_hashes==manifest['decoder_file_sha256'],
                  numpy_version=numpy.__version__,scipy_version=scipy.__version__)
    result['validation_mode']='frozen_first_pass_reproduction' if result['decoder_matches_frozen'] else 'follow_up_on_exposed_captures'
    record=json.loads(small_get('https://zenodo.org/api/records/'+RECORD,1048576))
    if str(record['id'])!=RECORD or record['metadata'].get('license',{}).get('id')!='cc-by-4.0':
        raise ValueError('Record identity or license changed')
    result.update(source=BASE,doi=record['metadata']['doi'],license=record['metadata']['license'],
                  creators=[c['name'] for c in record['metadata']['creators']],
                  frozen_decoder_commit=manifest['frozen_decoder_commit'],selection_rule=manifest['selection_rule'],observations=[])
    cached_csv=Path('corpus-cache/loraiq-inventory/dataset.csv')
    if cached_csv.exists():
        if cached_csv.stat().st_size!=manifest['csv_size']:
            raise ValueError('Cached CSV size mismatch')
        body=cached_csv.read_bytes()
        result['csv_bytes_transferred']=0
    else:
        with RangeReader(BASE+'/files/dataset.csv?download=1&iqscope=inventory',budget=32*1024*1024) as remote:
            if remote.size!=manifest['csv_size']:
                raise ValueError('CSV size changed')
            body=remote.read(remote.size)
            result['csv_bytes_transferred']=remote.received
    publisher=next(f for f in record['files'] if f['key']=='dataset.csv')
    if (hashlib.sha256(body).hexdigest()!=manifest['csv_sha256'] or
        'md5:'+hashlib.md5(body).hexdigest()!=publisher['checksum'] or publisher['checksum']!=manifest['csv_publisher_checksum']):
        raise ValueError('CSV integrity mismatch')
    rows=list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
    selection=select_extension(rows)
    if selection!=manifest['selected_annotations']:
        raise ValueError('Deterministic selection differs from reviewed manifest')
    result.update(csv_sha256=manifest['csv_sha256'],selected_count=len(selection),csv_rows=len(rows))
    root=Path('corpus-cache/loraiq-extension');root.mkdir(parents=True,exist_ok=True)
    from iqscope import read_iq
    from iqscope_lora import detect_lora_preamble
    with RangeReader(BASE+'/files/sigmfs.zip?download=1&iqscope=extension',budget=192*1024*1024) as remote:
        if remote.size!=71002741525:
            raise ValueError('Archive size changed')
        with zipfile.ZipFile(remote) as archive:
            index={}
            for item in archive.infolist():
                index.setdefault(item.filename,[]).append(item)
            def member(name,limit):
                matches=index.get(name,[])
                if len(matches)!=1 or matches[0].flag_bits&1 or not 0<matches[0].file_size<=limit:
                    raise ValueError('Invalid or oversized member: '+name)
                with archive.open(matches[0]) as stream:
                    data=stream.read(limit+1)
                if len(data)!=matches[0].file_size:
                    raise ValueError('Incomplete member: '+name)
                return data
            for number,row in enumerate(selection):
                entry={'annotation':row,'oracle_parameters_applied':[]}
                result['observations'].append(entry)
                stem=reference_stem(row)
                meta_bytes=member(stem+'.sigmf-meta',65536)
                data=member(stem+'.sigmf-data',32*1024*1024)
                meta=json.loads(meta_bytes)
                if hashlib.sha512(data).hexdigest()!=meta['global'].get('core:sha512'):
                    raise ValueError('Publisher data SHA512 mismatch: '+stem)
                entry.update(data_sha256=hashlib.sha256(data).hexdigest(),meta_sha256=hashlib.sha256(meta_bytes).hexdigest(),publisher_sha512_verified=True,zip_member_crc_verified=True)
                folder=root/str(number);folder.mkdir(exist_ok=True)
                (folder/'source.sigmf-meta').write_bytes(meta_bytes)
                (folder/'source.sigmf-data').write_bytes(data)
                samples,fs,_=read_iq(folder/'source.sigmf-meta')
                if fs!=float(row['rx_sample_rate']):
                    raise ValueError('Sampling rate disagreement')
                # Frozen automatic detector: no annotation is passed into it.
                trial=detect_lora_preamble(samples,fs)
                comparisons=compare_frames(trial.get('frames',[]),rows,stem,fs)
                entry.update(input_samples=len(samples),sample_rate_hz=fs,trial=trial,
                    frame_reference_comparisons=comparisons,
                    payload_matches_reference=any(c['status']=='exact_match' and c['annotation']==row for c in comparisons))
                if entry['payload_matches_reference']:
                    entry['main_pipeline_export']=verify_pipeline_export(samples,fs,folder,row,rows,stem)
                print('EXTENSION_MEMBER '+json.dumps({'member':stem,'matched':entry['payload_matches_reference'],'frames':len(trial.get('frames',[]))}),flush=True)
        result['archive_bytes_transferred']=remote.received
    result['matched_count']=sum(e['payload_matches_reference'] for e in result['observations'])
    result['missed_count']=len(selection)-result['matched_count']
    result['frame_reference_counts']={s:sum(c['status']==s for e in result['observations'] for c in e['frame_reference_comparisons']) for s in ('exact_match','payload_mismatch','ambiguous_annotation','no_annotation_in_prefix')}
    result['limitations']=['Four first-pass members from previously unused sessions of the same dataset; not a population sensitivity estimate.',
        'First two distinct sessions per available supported SF/BW/CR configuration, excluding the development session; selected before decoding.',
        'Whole member blind detection; no verified RF center; source member hashes verified, full archive hash not verified.',
        'Subsequent decoder changes invalidate the first-pass label; preserve this report as historical evidence.',
        'Decode misses remain outcomes; transport, integrity or size errors fail the run without selecting replacements.']


def main():
    result={}
    try:
        run(result)
    except Exception as exc:
        result['error']=str(exc)
    path=Path('corpus-cache/loraiq-extension/observation.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print('EXTENSION_RESULT '+json.dumps({k:v for k,v in result.items() if k!='observations'}),flush=True)
    if 'error' in result:
        raise SystemExit(1)


if __name__=='__main__':
    main()
