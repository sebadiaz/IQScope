"""Inspect the five declared Iraq RF source records; never download IQ archives."""
import argparse
import csv
import io
import re
import urllib.parse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from mendeley_metadata_probe import SameHostRedirect

RECORDS = ('22019720', '22036530', '22046487', '22052172', '22071547')
LIMIT = 1024 * 1024


def normalize(document, record_id):
    if str(document.get('id')) != record_id:
        raise ValueError('Zenodo record identity differs from the requested record')
    metadata = document.get('metadata', {})
    files = document.get('files', [])
    return {'id': record_id, 'doi': metadata.get('doi'), 'title': metadata.get('title'),
            'publication_date': metadata.get('publication_date'),
            'license': metadata.get('license'), 'access_right': metadata.get('access_right'),
            'creators': metadata.get('creators', []),
            'description': metadata.get('description'),
            'related_identifiers': metadata.get('related_identifiers', []),
            'file_count': len(files), 'files': [
                {key: item.get(key) for key in ('key', 'size', 'checksum', 'type')}
                for item in files],
            'interpretation': 'Publisher metadata only; sample layout, labels and payloads not validated'}


def inspect_documents(document, record_id):
    """Read only inventoried Markdown and the single master CSV, each <=256 KiB."""
    normalize(document, record_id)
    results = []
    for file in document.get('files', []):
        name = file.get('key', '')
        if not (re.fullmatch(r'(?:README|METADATA)_Iraq_RF_Spectrum_Dataset_Part[1-5][A-Za-z0-9_]*\.md', name)
                or name == 'Iraq_RF_Master_Metadata_FINAL.csv'):
            continue
        item = {'name': name, 'declared_bytes': file.get('size')}
        try:
            size = file['size']
            if not isinstance(size, int) or not 0 < size <= 262144:
                raise ValueError('Document exceeds the 256 KiB contract')
            checksum = file.get('checksum', '')
            if not re.fullmatch(r'md5:[0-9a-f]{32}', checksum):
                raise ValueError('Expected a published MD5 for document integrity')
            url = 'https://zenodo.org/records/' + record_id + '/files/' + urllib.parse.quote(name, safe='') + '?download=1'
            with urllib.request.build_opener(SameHostRedirect()).open(url, timeout=20) as response:
                body = response.read(262145)
            if len(body) != size or hashlib.md5(body).hexdigest() != checksum[4:]:
                raise ValueError('Document size or MD5 differs from inventory')
            text = body.decode('utf-8-sig')
            item.update(bytes_read=len(body), sha256=hashlib.sha256(body).hexdigest(), published_md5_verified=True)
            if name.endswith('.csv'):
                reader = csv.DictReader(io.StringIO(text))
                rows = list(reader)
                item.update(columns=reader.fieldnames, rows=len(rows), first_rows=rows[:3])
                item['column_values'] = {key: sorted({str(row.get(key, '')) for row in rows})[:40]
                                         for key in reader.fieldnames or []
                                         if re.search(r'format|type|sampl|rate|gain|band|day', key, re.I)}
            else:
                item['text'] = text
        except Exception as exc:
            item['error'] = str(exc)
        results.append(item)
    return results


def probe():
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Five declared source records; metadata and small verified documentation only; no IQ archive downloads',
              'records': []}
    for record_id in RECORDS:
        url = 'https://zenodo.org/api/records/' + record_id
        item = {'record_id': record_id, 'url': url}
        try:
            request = urllib.request.Request(url, headers={'Accept': 'application/json',
                                            'User-Agent': 'IQScope-metadata-probe/0.15'})
            with urllib.request.build_opener(SameHostRedirect()).open(request, timeout=20) as response:
                if 'json' not in response.headers.get('Content-Type', '').lower():
                    raise ValueError('Expected JSON metadata; body not downloaded')
                body = response.read(LIMIT + 1)
                item['http_status'] = response.status
            if len(body) > LIMIT:
                raise ValueError('Metadata exceeds the 1 MiB bound')
            item.update(bytes_read=len(body), sha256=hashlib.sha256(body).hexdigest(),
                        metadata=normalize(json.loads(body), record_id))
            item['documents'] = inspect_documents(json.loads(body), record_id)
        except Exception as exc:
            item['error'] = str(exc)
        result['records'].append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='corpus-cache/iraq-zenodo/metadata.json')
    args = parser.parse_args()
    result = probe()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
