"""Bounded public VKSDR recording import, shared by corpus checks and the UI."""
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit
import urllib.request

import numpy as np
from iqscope import analyze_samples, read_iq
from iqscope_formats import wave_layout, read_wave_iq


class VKSDRRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        check_url(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def check_url(url):
    parsed = urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='bucket.vksdr.com' or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only the fixed HTTPS VKSDR bucket is supported')


def read_prefix(response,limit):
    if not 4096<=limit<=4*1024*1024:
        raise ValueError('VKSDR prefix budget must be 4 KiB to 4 MiB')
    parts = []
    count = 0
    while count<limit:
        part = response.read(min(65536,limit-count))
        if not part:
            break
        parts.append(part)
        count += len(part)
    return b''.join(parts)


def inspect_prefix(prefix,entry,out):
    out = Path(out)/entry['id']
    out.mkdir(parents=True,exist_ok=True)
    path = out/'source-prefix.wav'
    path.write_bytes(prefix)
    layout = wave_layout(path,allow_prefix=True)
    x,fs,center = read_wave_iq(path,seconds=1,allow_prefix=True)
    data = out/'excerpt.sigmf-data'
    meta = out/'excerpt.sigmf-meta'
    x.astype('<c8').tofile(data)
    captures = [{'core:sample_start':0}]
    if center:
        captures[0]['core:frequency'] = center
    meta.write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs,'core:version':'1.2.0'},'captures':captures,'annotations':[]},indent=2))
    restored,restored_fs,restored_center = read_iq(data,limit_seconds=1)
    if restored_fs!=fs or restored_center!=center or not np.array_equal(x,restored):
        raise ValueError('Complete SigMF excerpt did not round-trip exactly')
    report = analyze_samples(x,fs,center,out/'results',source=entry['url'])
    hint = re.search(r'(\d+)Hz',unquote(entry['url']))
    return {'dataset_id':'vksdr','entry_id':entry['id'],'source_page':'https://vksdr.com/iq/',
            'source_url':entry['url'],'source_label':entry['source_label'],
            'source_label_independently_verified':False,'prefix_bytes':len(prefix),
            'prefix_sha256':hashlib.sha256(prefix).hexdigest(),'whole_source_integrity_verified':False,
            'layout':layout,'sample_count':len(x),'sample_rate_hz':fs,'analyzed_seconds':len(x)/fs,
            'header_center_frequency_hz':center if center else None,
            'filename_center_hint_hz':int(hint.group(1)) if hint else None,
            'center_policy':'Use auxi header when present; do not promote filename hints to verified RF metadata.',
            'sigmf_roundtrip_exact':True,'detected_spectral_bands':len(report['signals']),
            'validation_scope':'bounded WAV IQ import, complete SigMF round-trip and existing analysis only; no satellite or military protocol validation'}


def probe(entry,out,limit=2*1024*1024):
    check_url(entry['url'])
    request = urllib.request.Request(entry['url'],headers={'Range':f'bytes=0-{limit-1}',
                                                         'User-Agent':'IQScope-VKSDR-corpus/0.11'})
    with urllib.request.build_opener(VKSDRRedirectHandler()).open(request,timeout=30) as response:
        status = response.status
        content_range = response.headers.get('Content-Range')
        if status==206 and not re.match(r'^bytes 0-\d+/\d+$',content_range or ''):
            raise ValueError('Expected a byte range starting at offset zero')
        content_type = response.headers.get('Content-Type','')
        prefix = read_prefix(response,limit)
    evidence = inspect_prefix(prefix,entry,out)
    evidence.update(http_status=status,content_range=content_range,http_content_type=content_type,
                    download_limit_bytes=limit)
    (Path(out)/entry['id']/'provenance.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence),flush=True)
    return evidence


def recordings():
    return json.loads(files('iqscope_web').joinpath('data/vksdr_recordings.json').read_text(encoding='utf-8'))


def import_vksdr(identifier,out):
    entry = next((e for e in recordings()['entries'] if e['id']==identifier),None)
    if entry is None:
        raise ValueError('Unknown VKSDR recording')
    out = Path(out)
    evidence = probe(entry,out)
    source = out/identifier
    report = json.loads((source/'results/report.json').read_text())
    for path in (source/'results').iterdir():
        if path.is_file():
            shutil.copy2(path,out/path.name)
    for name in ('excerpt.sigmf-data','excerpt.sigmf-meta','provenance.json'):
        shutil.copy2(source/name,out/name)
    report['recording_provenance'] = evidence
    report['recording_artifacts'] = {'data':'excerpt.sigmf-data','metadata':'excerpt.sigmf-meta','provenance':'provenance.json'}
    report['source_kind'] = 'remote_iq_excerpt'
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return report
