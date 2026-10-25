"""Validate a bounded first Panoradio NPY window, without downloading 5+ GB."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request

import numpy as np

from iqscope import analyze
from iqscope_datasets import catalog, check_panoradio_shape, export_panoradio_window

URL = 'https://www.panoradio-sdr.de/wp-content/uploads/dataset_panoradio_hf.npy'
LIMIT = 65536


def parse_first_window(prefix):
    handle = io.BytesIO(prefix)
    version = np.lib.format.read_magic(handle)
    readers = {(1,0):np.lib.format.read_array_header_1_0, (2,0):np.lib.format.read_array_header_2_0}
    if version not in readers:
        raise ValueError('Only NPY v1/v2 headers are supported in the bounded probe')
    shape, fortran, dtype = readers[version](handle)
    check_panoradio_shape(shape, dtype)
    if fortran:
        raise ValueError('A Fortran-order source needs strided range reads; no row is inferred from this prefix')
    size = shape[1]*dtype.itemsize
    payload = handle.read(size)
    if len(payload) != size:
        raise ValueError('The bounded prefix does not contain one full independent window')
    x = np.frombuffer(payload, dtype=dtype).copy()
    if not np.all(np.isfinite(x)):
        raise ValueError('Source window contains non-finite values')
    return x, {'source_shape':list(shape),'source_dtype':dtype.str,
               'record_index':0,'fortran_order':fortran,
               'source_window_sha256':hashlib.sha256(payload).hexdigest()}


def main():
    out = Path('corpus-cache/panoradio')
    out.mkdir(parents=True,exist_ok=True)
    request = urllib.request.Request(URL,headers={'Range':f'bytes=0-{LIMIT-1}','User-Agent':'IQScope-corpus/0.3'})
    with urllib.request.urlopen(request, timeout=30) as response:
        status = response.status
        content_range = response.headers.get('Content-Range')
        if status == 206 and not (content_range or '').startswith('bytes 0-'):
            raise ValueError('Server returned an unexpected byte range')
        prefix = response.read(LIMIT)
    row, provenance = parse_first_window(prefix)
    entry = next(item for item in catalog()['entries'] if item['id']=='panoradio_hf')
    expected = entry.get('reference_first_window_sha256')
    if expected and provenance['source_window_sha256'] != expected:
        raise ValueError('Reference source window changed: review the dataset before accepting a new hash')
    if provenance['source_shape'] != [172800,2048]:
        raise ValueError('Source shape differs from the documented corpus; review the adapter')
    path = out/'one-window.npy'
    np.save(path,row[None,:],allow_pickle=False)
    exported = export_panoradio_window(path,out/'window',record=0)
    report = analyze(exported['metadata'],out/'results')
    provenance.update(source_url=URL,http_status=status,content_range=content_range,
                      received_bytes=len(prefix),prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                      exported_samples=exported['sample_count'],sample_rate_hz=report['sample_rate'],
                      analyzed_seconds=report['analyzed_seconds'],class_label=None,
                      validation_scope='one-window import and analysis only; no recognition or content decoding',
                      continuous_across_rows=False,full_source_hash=None,source_kind='synthetic_windows')
    if report['sample_rate'] != 6000 or exported['sample_count'] != 2048:
        raise ValueError('Unexpected exported sample metadata')
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2))
    print(json.dumps(provenance,indent=2),flush=True)


if __name__ == '__main__':
    main()
