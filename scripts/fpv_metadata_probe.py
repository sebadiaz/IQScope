"""Read FPV dataset metadata and ZIP index by bounded HTTP ranges. No video decoding."""
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

from iqscope_datasets import fpv_annotations

RECORD = '19870020'
BASE = f'https://zenodo.org/records/{RECORD}'
CSV_URL = BASE+'/files/iq_recording_meta.csv?download=1'
CSV_MD5 = '74a1530b212e4e4bf4b98f7efe444d46'


def small_get(url, limit):
    with urllib.request.urlopen(url,timeout=30) as response:
        data = response.read(limit+1)
        if len(data) > limit:
            raise ValueError('Metadata exceeds download budget')
        return data


class RangeReader(io.RawIOBase):
    """Seekable read-only remote ZIP, refusing silent whole-file transfers."""
    def __init__(self,url,budget=1024*1024):
        self.url, self.budget, self.received, self.position = url,budget,0,0
        data,total = self._range(0,0)
        self.size = total

    def _range(self,start,end):
        wanted = end-start+1
        if wanted > self.budget-self.received:
            raise ValueError('Remote ZIP metadata transfer budget exceeded')
        request = urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'})
        with urllib.request.urlopen(request,timeout=30) as response:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if response.status != 206 or not match or (int(match[1]),int(match[2])) != (start,end):
                raise ValueError('Server does not honor exact HTTP ranges; full ZIP download refused')
            data = response.read(wanted+1)
            if len(data) != wanted:
                raise ValueError('Remote ZIP range is incomplete or oversized')
        self.received += len(data)
        return data,int(match[3])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self,offset,whence=0):
        if whence not in (0,1,2):
            raise ValueError('Invalid seek mode')
        position = offset if whence == 0 else (self.position if whence == 1 else self.size)+offset
        if position < 0 or position > self.size:
            raise ValueError('Seek outside remote archive')
        self.position = position
        return position

    def read(self,count=-1):
        if count is None or count < 0:
            count = self.size-self.position
        count = min(count,self.size-self.position)
        if count == 0:
            return b''
        data,total = self._range(self.position,self.position+count-1)
        if total != self.size:
            raise ValueError('Remote archive size changed during inspection')
        self.position += len(data)
        return data


def main():
    out = Path('corpus-cache/fpv')
    out.mkdir(parents=True,exist_ok=True)
    record = json.loads(small_get('https://zenodo.org/api/records/'+RECORD,1024*1024))
    metadata = record.get('metadata',{})
    csv = small_get(CSV_URL,65536)
    if hashlib.md5(csv).hexdigest() != CSV_MD5:
        raise ValueError('Source sweep CSV changed; review the record before accepting a new hash')
    path = out/'iq_recording_meta.csv'
    path.write_bytes(csv)
    annotations = fpv_annotations(path)
    if annotations['summary'] != {'sweeps':48,'tx_active':38,'tx_inactive':10}:
        raise ValueError('Annotation counts differ from the inspected source')
    archive_url = BASE+'/files/chunk10.zip?download=1'
    with RangeReader(archive_url) as remote:
        with zipfile.ZipFile(remote) as archive:
            members = archive.infolist()
            candidates = [item for item in members if item.filename.endswith('/metadata.csv')]
            if not candidates:
                raise ValueError('No per-sweep metadata.csv found')
            selected = candidates[0]
            if selected.file_size > 256*1024:
                raise ValueError('Per-sweep metadata exceeds inspection budget')
            per_sweep = archive.read(selected)
            raw_files = [{'name':item.filename,'uncompressed_bytes':item.file_size}
                         for item in members if item.filename.endswith('/iq.bin')]
        transfer = remote.received
    lines = per_sweep.decode('utf-8-sig').splitlines()
    (out/'annotations.json').write_text(json.dumps(annotations,indent=2))
    result = {'record_url':BASE,'title':metadata.get('title'),
              'license_as_reported_by_api':metadata.get('license') or metadata.get('rights'),
              'annotations':annotations['summary'],'annotation_csv_sha256':hashlib.sha256(csv).hexdigest(),
              'archive_url':archive_url,'raw_files':raw_files,
              'inspected_metadata_member':selected.filename,
              'metadata_first_lines':lines[:4],'metadata_rows_excluding_header':max(0,len(lines)-1),
              'archive_metadata_transfer_bytes':transfer,
              'validation_scope':'sweep annotations and archive metadata only',
              'iq_extracted':False,'video_decoded':False,
              'limitations':annotations['limitations']}
    (out/'provenance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)


if __name__ == '__main__':
    main()
