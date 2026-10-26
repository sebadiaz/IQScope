"""Inspect one bounded public imec IQ prefix; retain both byte-order hypotheses."""
import argparse
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

import numpy as np
from imec_catalog_probe import HOST, SameHostRedirect, fetch, public_listing
from iqscope import analyze_samples, read_iq
from iqscope_datasets import export_imec_hypotheses

TOKEN = 'qrJCWgzQaGPfHPr'
ROOT = '/public.php/dav/files/'+TOKEN+'/'
LIMIT = 262144


def checked_path(href):
    parsed = urllib.parse.urlsplit(href)
    decoded = urllib.parse.unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith(ROOT) or '..' in decoded.split('/'):
        raise ValueError('Only paths in the fixed public share are supported')
    return parsed.path


def list_directory(path):
    checked_path(path)
    request = urllib.request.Request(HOST+path,method='PROPFIND',
        headers={'Depth':'1','Content-Type':'application/xml','X-Requested-With':'XMLHttpRequest'},
        data=b'<d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:getcontentlength/><d:getcontenttype/><d:resourcetype/></d:prop></d:propfind>')
    status,_,body,truncated = fetch(request)
    if status!=207 or truncated:
        raise ValueError('Need a complete bounded public directory listing')
    return public_listing(body)


def select_file(location):
    if location not in ('rabot','merelbeke','uz','reep','gentbrugge','igent'):
        raise ValueError('Unknown documented location')
    path = ROOT+location+'/'
    visited = []
    for _ in range(3):
        visited.append(path)
        listing = list_directory(path)
        candidates = [f for f in listing if not f.get('directory') and (f.get('name') or '').lower().endswith('.bin') and int(f.get('bytes') or 0)>=4096]
        if candidates:
            candidates.sort(key=lambda f:(not f['name'].lower().startswith(('wf','wifi')),f['name']))
            selected = candidates[0]
            checked_path(selected['href'])
            return selected,visited
        folders = [f for f in listing if f.get('directory') and f['href'] not in visited]
        folders.sort(key=lambda f:(not (f.get('name') or '').lower().startswith(('wf','wifi')),f.get('name') or ''))
        if not folders:
            break
        path = checked_path(folders[0]['href'])
    raise ValueError('No .bin found in the bounded three-directory path; this is not an exhaustive search')


def download_prefix(entry):
    path = checked_path(entry['href'])
    total = int(entry['bytes'])
    if total%4:
        raise ValueError('Remote file does not contain complete int16 I/Q pairs')
    request = urllib.request.Request(HOST+path,headers={'Range':f'bytes=0-{LIMIT-1}','Accept-Encoding':'identity'})
    with urllib.request.build_opener(SameHostRedirect()).open(request,timeout=30) as response:
        status = response.status
        content_range = response.headers.get('Content-Range')
        if status==206:
            match = re.fullmatch(r'bytes 0-(\d+)/(\d+)',content_range or '')
            if match is None or int(match.group(2))!=total:
                raise ValueError('Unexpected byte range or source size changed')
        if response.headers.get('Content-Type','').lower().startswith(('text/html','application/xml','text/xml')):
            raise ValueError('Received a page instead of IQ bytes')
        chunks,count = [],0
        while count<LIMIT:
            block = response.read(min(65536,LIMIT-count))
            if not block:
                break
            chunks.append(block)
            count += len(block)
    payload = b''.join(chunks)
    if len(payload)>total or (status==206 and len(payload)!=min(LIMIT,int(match.group(1))+1)):
        raise ValueError('Body size does not match the requested prefix or declared source')
    return payload,{'http_status':status,'content_range':content_range,'source_file_bytes':total}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--location',default='rabot')
    parser.add_argument('--out',default='corpus-cache/imec-iq-prefix')
    args = parser.parse_args()
    entry,visited = select_file(args.location)
    prefix,http = download_prefix(entry)
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    source = out/entry['name']
    if Path(entry['name']).name!=entry['name']:
        raise ValueError('Unexpected source filename')
    with source.open('xb') as handle:
        handle.write(prefix)
    evidence = export_imec_hypotheses(source,out/'excerpt',max_bytes=LIMIT)
    evidence.update(source_url=HOST+entry['href'],source_file_bytes=http['source_file_bytes'],
                    source_share=HOST+'/index.php/s/'+TOKEN,visited_directories=visited,
                    download_limit_bytes=LIMIT,http=http,whole_source_integrity_verified=False)
    for hypothesis in evidence['interpretations']:
        x,fs,center = read_iq(hypothesis['metadata'])
        dtype = '<i2' if hypothesis['byte_order_hypothesis']=='le' else '>i2'
        restored = np.empty((len(x),2),dtype=dtype)
        restored[:,0],restored[:,1] = np.rint(x.real*32768),np.rint(x.imag*32768)
        if restored.tobytes()!=prefix:
            raise ValueError('SigMF candidate did not reproduce source bytes exactly')
        result_dir = out/hypothesis['byte_order_hypothesis']/'results'
        report = analyze_samples(x,fs,center,result_dir,source=HOST+entry['href'])
        report['interpretation_status'] = 'unverified_byte_order_and_header_layout'
        report['sample_rate_source'] = evidence['sample_rate_source']
        (result_dir/'report.json').write_text(json.dumps(report,indent=2))
        hypothesis['roundtrip_exact'] = True
        hypothesis['analyzed_seconds'] = len(x)/fs
        hypothesis['detected_spectral_bands'] = len(report['signals'])
        cp = next(t for t in report['wideband_trials'] if t['decoder']=='ofdm_cp')
        cp['input_interpretation_status'] = report['interpretation_status']
        cp['input_datatype_hypothesis'] = 'ci16_'+hypothesis['byte_order_hypothesis']
        cp['sample_rate_source'] = evidence['sample_rate_source']
        if report.get('ofdm_artifact'):
            (result_dir/report['ofdm_artifact']).write_text(json.dumps(cp,indent=2))
        (result_dir/'report.json').write_text(json.dumps(report,indent=2))
        hypothesis['cyclic_prefix_status'] = cp['status']
        hypothesis['cyclic_prefix_candidates'] = cp['candidates']
    (out/'provenance.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence),flush=True)


if __name__=='__main__':
    main()
