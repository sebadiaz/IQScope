"""Dataset catalog and bounded import of independent Panoradio HF windows."""
import hashlib
from importlib.resources import files
import json
from pathlib import Path

import numpy as np

PANORADIO_URL = 'https://panoradio-sdr.de/radio-signal-classification-dataset/'


def catalog():
    resource = files('iqscope_web').joinpath('data/datasets.json')
    return json.loads(resource.read_text(encoding='utf-8'))


def check_panoradio_shape(shape, dtype):
    if len(shape) != 2 or shape[0] <= 0 or shape[1] != 2048:
        raise ValueError('Panoradio input must have shape (number_of_windows, 2048); rows must remain independent')
    if np.dtype(dtype).kind != 'c' or np.dtype(dtype).itemsize not in (8,16):
        raise ValueError('Expected complex64/complex128 IQ, never pickle/object or real-valued features')


def load_panoradio(path):
    with Path(path).open('rb') as handle:
        if handle.read(6) != b'\x93NUMPY':
            raise ValueError('Expected a single NPY array, not NPZ, pickle or another container')
    try:
        return np.load(path, mmap_mode='r', allow_pickle=False)
    except EOFError as exc:
        raise ValueError('NPY file is truncated') from exc


def inspect_panoradio(path):
    data = load_panoradio(path)
    check_panoradio_shape(data.shape, data.dtype)
    return {'shape': list(data.shape), 'dtype': data.dtype.str,
            'sample_rate_hz':6000, 'window_seconds':2048/6000,
            'continuous_across_rows':False}


def export_panoradio_window(path, out, record=0):
    """Read only the requested row via mmap; export a complete local SigMF pair.

    The author's mode is not inferred from row order. Classifier labels/CSV
    mappings must be verified separately before they can become ground truth.
    """
    if not isinstance(record, int) or record < 0:
        raise ValueError('Record must be a non-negative integer')
    path = Path(path)
    matrix = load_panoradio(path)
    check_panoradio_shape(matrix.shape, matrix.dtype)
    if record >= matrix.shape[0]:
        raise ValueError(f'Record {record} is out of range for {matrix.shape[0]} windows')
    original = np.asarray(matrix[record])
    if not np.all(np.isfinite(original)):
        raise ValueError('Selected window contains non-finite IQ samples')
    x = np.asarray(original, dtype='<c8')
    if not np.all(np.isfinite(x)):
        raise ValueError('Selected values cannot be represented as complex float32')
    prefix = Path(out)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {kind:Path(str(prefix)+extension) for kind,extension in
             [('data','.sigmf-data'),('metadata','.sigmf-meta'),('provenance','.provenance.json')]}
    if any(target.exists() for target in paths.values()):
        raise ValueError('Output exists; choose a new prefix')
    payload = x.tobytes()
    provenance = {'dataset_id':'panoradio_hf','source_url':PANORADIO_URL,
                  'source_filename':path.name,'source_file_bytes':path.stat().st_size,
                  'source_shape':list(matrix.shape),'source_dtype':matrix.dtype.str,
                  'record_index':record,'sample_count':len(x),'sample_rate_hz':6000,
                  'continuous_across_rows':False,'synthetic':True,
                  'class_label':None,'label_status':'not imported or predicted',
                  'output_datatype':'cf32_le','output_sha256':hashlib.sha256(payload).hexdigest(),
                  'full_source_hash':None,
                  'note':'Only the selected independent window is exported. No packet or message is claimed.'}
    meta = {'global':{'core:datatype':'cf32_le','core:sample_rate':6000,
                      'core:version':'1.2.0','core:description':f'Panoradio HF independent synthetic window {record}; class label not imported.'},
            'captures':[{'core:sample_start':0}],
            'annotations':[{'core:sample_start':0,'core:sample_count':len(x),
                            'core:description':'Independent classification window; do not concatenate with other rows.'}]}
    outputs = {'data':payload,'metadata':json.dumps(meta,indent=2).encode(),
               'provenance':json.dumps(provenance,indent=2).encode()}
    created = []
    try:
        for kind,target in paths.items():
            with target.open('xb') as handle:
                created.append(target)
                handle.write(outputs[kind])
    except BaseException:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    return {'dataset_id':'panoradio_hf','record_index':record,
            'sample_count':len(x),'seconds':len(x)/6000,
            **{kind:str(target) for kind,target in paths.items()}}
