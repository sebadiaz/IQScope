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


def fpv_annotations(path):
    """Read source sweep annotations, never interpret their ambiguous rate units."""
    import csv
    import math
    import re

    path = Path(path)
    if path.stat().st_size > 1024*1024:
        raise ValueError('Sweep annotation CSV exceeds 1 MiB')
    with path.open(newline='',encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        original_headers = reader.fieldnames
        if not original_headers:
            raise ValueError('Missing CSV header')
        names = [re.sub(r'\s+','',name.rstrip('\\').lower()) for name in original_headers]
        names = ['obstacles' if name == 'obtacles' else name for name in names]
        if len(set(names)) != len(names):
            raise ValueError('Ambiguous duplicate normalized CSV columns')
        required = {'id','drone_freq','vtx_power_mw','iq_folder','sample_rate','samples_per_freq'}
        if not required.issubset(names):
            raise ValueError('Missing required FPV sweep annotation columns')
        recordings, ids, folders = [], set(), set()
        for source in reader:
            if None in source or any(value is None for value in source.values()):
                raise ValueError('CSV row has a different number of fields than its header')
            row = {name:source[old].strip() for old,name in zip(original_headers,names)}
            number = int(row['id'])
            power = float(row['vtx_power_mw'])
            frequency = row['drone_freq']
            no_tx = frequency.lower() == 'none'
            if number <= 0 or number in ids or row['iq_folder'] in folders or not row['iq_folder']:
                raise ValueError('Invalid or duplicate sweep identifier/folder')
            if not math.isfinite(power) or power < 0 or (no_tx and power != 0) or (not no_tx and power <= 0):
                raise ValueError('Inconsistent transmitter state and power annotation')
            if not no_tx and (not math.isfinite(float(frequency)) or float(frequency) <= 0):
                raise ValueError('Invalid transmitter frequency annotation')
            ids.add(number)
            folders.add(row['iq_folder'])
            recordings.append({'sweep_id':number,'iq_folder':row['iq_folder'],
                               'target_transmitter_active':not no_tx,
                               'label_scope':'sweep_experiment_not_each_IQ_window',
                               'transmitter_frequency_raw':frequency,
                               'transmitter_frequency_unit':None,
                               'sample_rate_raw':row['sample_rate'],'sample_rate_unit':None,
                               'samples_per_frequency_raw':row['samples_per_freq'],
                               'samples_per_frequency_unit':None,
                               'distance_raw':row.get('distance_m'),
                               'source_row':row})
    if not recordings:
        raise ValueError('No annotated sweeps')
    return {'dataset_id':'fpv_analog','schema_version':'1.0',
            'source_headers':original_headers,'recordings':recordings,
            'summary':{'sweeps':len(recordings),
                       'tx_active':sum(r['target_transmitter_active'] for r in recordings),
                       'tx_inactive':sum(not r['target_transmitter_active'] for r in recordings)},
            'limitations':['An inactive target transmitter is not a guarantee of noise-only RF.',
                           'Sample rate and frequency units are not inferred from bare numeric CSV values.',
                           'This is annotation import, not IQ import or video reconstruction.']}


def imec_filename_metadata(name):
    """Author-described rate convention; filename hints are not RF measurements."""
    import re
    name = Path(name).name
    rates = re.findall(r'(\d+(?:\.\d+)?)([mk]?)sps',name,re.I)
    if len(rates)>1:
        raise ValueError('Ambiguous sampling rates in filename')
    rate = float(rates[0][0])*{'':1,'k':1000,'m':1000000}[rates[0][1].lower()] if rates else 1000000
    if not 1000<=rate<=20000000:
        raise ValueError('Filename sample rate is outside the supported 1 kS/s to 20 MS/s range')
    centers = re.findall(r'f(\d+(?:\.\d+)?)mhz',name,re.I)
    return {'sample_rate_hz':rate,'sample_rate_source':'filename' if rates else 'authors_default_not_measured',
            'filename_center_hint_hz':float(centers[0])*1e6 if len(centers)==1 else None}


def export_imec_hypotheses(path,out,max_bytes=262144):
    """Export both int16 byte orders. Neither hypothesis is selected as truth."""
    if not 4096<=max_bytes<=1048576 or max_bytes%4:
        raise ValueError('IQ prefix budget must be 4 KiB to 1 MiB and divisible by four')
    path = Path(path)
    if path.stat().st_size%4:
        raise ValueError('Source does not contain complete int16 I/Q pairs')
    with path.open('rb') as handle:
        prefix = handle.read(max_bytes)
    if len(prefix)%4:
        raise ValueError('Prefix does not contain complete int16 I/Q pairs')
    if len(prefix)<4096:
        raise ValueError('Need at least 1024 int16 I/Q pairs')
    info = imec_filename_metadata(path.name)
    target = Path(out)
    target.parent.mkdir(parents=True,exist_ok=True)
    outputs = {}
    interpretations = []
    for order in ('le','be'):
        name = str(target)+'.'+order
        data_path,meta_path = Path(name+'.sigmf-data'),Path(name+'.sigmf-meta')
        words = np.frombuffer(prefix,dtype='<i2' if order=='le' else '>i2').reshape(-1,2)
        interpretations.append({'byte_order_hypothesis':order,'data':str(data_path),'metadata':str(meta_path),
            'rms_normalized':float(np.sqrt(np.mean((words.astype(float)/32768)**2))),
            'mean_i_normalized':float(np.mean(words[:,0])/32768),
            'mean_q_normalized':float(np.mean(words[:,1])/32768),
            'clipped_scalar_fraction':float(np.mean((words==-32768)|(words==32767)))})
        meta = {'global':{'core:datatype':'ci16_'+order,'core:sample_rate':info['sample_rate_hz'],'core:version':'1.2.0',
                         'core:description':'imec int16 I/Q candidate interpretation; byte order and header layout not independently verified',
                         'iqscope:byte_order_status':'unverified_hypothesis','iqscope:sample_rate_source':info['sample_rate_source']},
                'captures':[{'core:sample_start':0}],'annotations':[]}
        outputs[data_path] = prefix
        outputs[meta_path] = json.dumps(meta,indent=2).encode()
    provenance = {'dataset_id':'imec_lte_wifi_dvbt','source_filename':path.name,'source_file_bytes':path.stat().st_size,
                  'prefix_bytes':len(prefix),'sample_count':len(prefix)//4,'prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                  **info,'iq_order_basis':'public author MATLAB example: I then Q',
                  'endianness_verified':False,'header_layout_verified':False,'selected_hypothesis':None,
                  'whole_source_integrity_verified':False,
                  'interpretations':interpretations,'scope':'candidate conversion only; no class prediction, protocol or payload validation'}
    outputs[Path(str(target)+'.provenance.json')] = json.dumps(provenance,indent=2).encode()
    if any(p.exists() for p in outputs):
        raise ValueError('Output exists; choose a new prefix')
    created = []
    try:
        for name,payload in outputs.items():
            with name.open('xb') as handle:
                created.append(name)
                handle.write(payload)
    except BaseException:
        for name in created:
            name.unlink(missing_ok=True)
        raise
    return provenance
