"""Inspect the five declared Iraq RF source records; never download IQ archives."""
import argparse
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


def probe():
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Five declared source records; metadata only, no file or archive downloads',
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
