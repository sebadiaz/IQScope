"""Seek bounded IQ windows without reading samples preceding the requested start."""
import json
import math
from pathlib import Path

import numpy as np

from iqscope_formats import MAX_SAMPLES,check_samples,read_sdriq,read_wave_iq,sdriq_layout,wave_layout


def _layout(path, sample_rate):
    path=Path(path)
    kind=path.suffix.lower()
    if kind in ('.wav','.sdriq'):
        layout=wave_layout(path) if kind=='.wav' else sdriq_layout(path)
        return dict(layout,path=path,kind=kind,total_samples=layout['data_bytes']//layout['block_align'])
    meta_path=path if path.suffix=='.sigmf-meta' else path.with_suffix('.sigmf-meta')
    center=0.;dtype='<c8'
    if meta_path.exists():
        meta=json.loads(meta_path.read_text());glob=meta['global']
        if glob.get('core:offset',0) or glob.get('core:num_channels',1)!=1:
            raise ValueError('Only single-channel, zero-offset SigMF data is supported')
        if len(meta.get('captures',[]))>1:
            raise ValueError('Multiple capture segments are not supported yet')
        sample_rate=float(glob['core:sample_rate'])
        types={'cf32_le':'<c8','cf32_be':'>c8','ci16_le':'<i2','ci16_be':'>i2','cu8':'u1'}
        datatype=glob['core:datatype']
        if datatype not in types:
            raise ValueError(f'Unsupported SigMF datatype: {datatype}')
        dtype=types[datatype]
        captures=meta.get('captures',[])
        if captures:
            center=float(captures[0].get('core:frequency',0))
            if captures[0].get('core:sample_start',0):
                raise ValueError('Capture must start at sample zero')
        path=meta_path.with_suffix('.sigmf-data')
    if sample_rate is None or not math.isfinite(sample_rate) or sample_rate<=0:
        raise ValueError('Raw cf32 IQ requires a positive --sample-rate; use SigMF for automatic metadata')
    if not math.isfinite(center):
        raise ValueError('Center frequency must be finite')
    width=np.dtype(dtype).itemsize*(1 if np.dtype(dtype).kind=='c' else 2)
    size=path.stat().st_size
    if size%width:
        raise ValueError('File ends with an incomplete IQ sample')
    return dict(path=path,kind='raw',dtype=dtype,sample_rate=sample_rate,
                center_frequency_hz=center,block_align=width,total_samples=size//width)


def iq_source_info(path, sample_rate=None):
    layout=_layout(path,sample_rate)
    return dict(sample_rate=layout['sample_rate'],center_frequency_hz=layout['center_frequency_hz'],
                total_samples=layout['total_samples'],source_format=layout['kind'])


def read_iq_window(path, sample_rate=None, seconds=10, start_seconds=0, start_sample=None):
    layout=_layout(path,sample_rate)
    fs,center=layout['sample_rate'],layout['center_frequency_hz']
    if not math.isfinite(seconds) or seconds<=0:
        raise ValueError('Analysis duration must be positive and finite')
    if not math.isfinite(start_seconds) or start_seconds<0 or not math.isfinite(start_seconds*fs):
        raise ValueError('Start time must be nonnegative and finite')
    if start_sample is not None:
        if type(start_sample) is not int or start_sample<0 or start_seconds!=0:
            raise ValueError('Choose either a nonnegative integer start sample or a start time')
        start=start_sample
    else:
        start=math.floor(start_seconds*fs)
    total=layout['total_samples']
    if total-start<1024:
        raise ValueError('Need at least 1024 complex samples remaining after the requested start')
    requested=fs*seconds
    count=MAX_SAMPLES if not math.isfinite(requested) else min(MAX_SAMPLES,int(requested))
    if count<1024:
        raise ValueError('Need at least 1024 complex samples in the requested window')
    if layout['kind']=='.wav':
        x,_,_=read_wave_iq(layout['path'],seconds,start_sample=start)
    elif layout['kind']=='.sdriq':
        x,_,_=read_sdriq(layout['path'],seconds,start_sample=start)
    else:
        dtype=layout['dtype'];complex_input=np.dtype(dtype).kind=='c'
        raw=np.fromfile(layout['path'],dtype=dtype,count=(1 if complex_input else 2)*min(count,total-start),
                        offset=start*layout['block_align'])
        if complex_input:
            x=raw
        else:
            raw=raw.astype(np.float32)
            raw=(raw-127.5)/127.5 if dtype=='u1' else raw/32768
            x=raw[::2]+1j*raw[1::2]
        check_samples(x)
    end=start+len(x)
    window=dict(start_sample=start,end_sample=end,total_samples=total,
        start_seconds=start/fs,end_seconds=end/fs,total_seconds=total/fs,
        requested_start_seconds=start_seconds if start_sample is None else None,
        requested_seconds=seconds,window_sample_limit=count,sample_budget_limited=requested>MAX_SAMPLES,
        previous_start_sample=max(0,start-count) if start else None,
        next_start_sample=end if total-end>=1024 else None,remaining_samples=total-end,
        decoder_time_reference='seconds relative to this window start; add start_seconds for source time',
        reader_scope='seeked IQ window; finite-sample validation applies to samples read, not the entire source')
    return x,fs,center,window
