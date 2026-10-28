"""Inspect an independent LoRaIQ reference with strict metadata/download bounds."""
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
    except Exception as exc:
        result['error']=str(exc)
    out=Path('corpus-cache/loraiq/observation.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    if 'error' in result:
        raise SystemExit(1)


if __name__=='__main__':
    main()
