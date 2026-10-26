"""Four-level stationary FSK trials; frequency ranks do not identify a protocol."""
import numpy as np
from scipy import ndimage
from iqscope_fsk import recover_clock, search_fsk


def decode_fsk4(x,fs,max_seconds=12,max_bits=100000):
    base = {'decoder':'fsk4_generic','family':'4-FSK','candidates':[]}
    if not 1000<=fs<=96000 or len(x)<fs*.1:
        return dict(base,status='not_applicable')
    original = len(x)
    x = np.asarray(x[:int(fs*max_seconds)])
    base.update(analyzed_seconds=len(x)/fs,duration_limited=len(x)<original,
                validation_scope='four frequency levels and timing only; no protocol or checksum validation',
                limitations=['Stationary unshaped equally spaced 4-FSK; all four levels must be sufficiently present.',
                             'Symbol ranks are frequency order, not known protocol symbols; natural binary mapping is arbitrary.',
                             '20 baud to sample_rate/8 (max 9600); integer baud aliases remain possible.',
                             'Bursts, fading, clock drift, shaped FSK and overlapping channels may fail.'])
    amplitude = np.abs(x)
    median = float(np.median(amplitude))
    if median<1e-12 or np.mean(amplitude<median*.25)>.05:
        return dict(base,status='no_consistent_candidate')
    frequency = ndimage.median_filter(np.angle(x[1:]*np.conj(x[:-1]))*fs/(2*np.pi),size=3)
    levels = np.percentile(frequency,[12.5,37.5,62.5,87.5])
    for _ in range(8):
        labels = np.argmin(abs(frequency[:,None]-levels),axis=1)
        if min(np.mean(labels==k) for k in range(4))<.08:
            return dict(base,status='no_consistent_candidate')
        levels = np.array([np.median(frequency[labels==k]) for k in range(4)])
    gaps = np.diff(levels)
    spacing = float(np.mean(gaps))
    if min(gaps)<20 or max(abs(gaps/spacing-1))>.12:
        return dict(base,status='no_consistent_candidate')
    distance = np.min(abs(frequency[:,None]-levels),axis=1)
    if np.mean(distance<spacing*.22)<.9:
        return dict(base,status='no_consistent_candidate')
    labels = np.argmin(abs(frequency[:,None]-levels),axis=1)
    indices = np.flatnonzero(labels[1:]!=labels[:-1])
    if len(indices)<24:
        return dict(base,status='no_consistent_candidate')
    # Filtered jumps may pass briefly through intermediate ranks. Keep one edge
    # per cluster; supported clocks have at least eight samples per symbol.
    breaks = np.r_[0,np.flatnonzero(np.diff(indices)>3)+1,len(indices)]
    edges = []
    for start,end in zip(breaks[:-1],breaks[1:]):
        first,last = indices[start],indices[end-1]
        threshold = (levels[labels[first]]+levels[labels[last+1]])/2
        segment = frequency[first:last+2]
        nearest = int(np.argmin(abs(segment-threshold)))+first
        edges.append(float(nearest)+.5)
    edges = np.array(edges)
    if len(edges)<24:
        return dict(base,status='no_consistent_candidate')
    clock = recover_clock(edges,fs,max_bits//2)
    if clock is None:
        return dict(base,status='no_consistent_candidate')
    centers,residual,count = clock
    values = np.interp(centers-.5,np.arange(len(frequency)),frequency)
    distances = abs(values[:,None]-levels)
    symbols = np.argmin(distances,axis=1)
    if np.mean(np.min(distances,axis=1)<spacing*.22)<.95:
        return dict(base,status='no_consistent_candidate')
    bits = ''.join(format(int(value),'02b') for value in symbols)
    candidate = {'symbols':''.join(map(str,symbols.tolist())),'bits':bits,
                 'parameters':{'baud':float(fs/(centers[1]-centers[0])),'tone_hz':levels.tolist(),
                               'spacing_hz':spacing,'first_symbol_center_seconds':float(centers[0]/fs),
                               'symbol_mapping':'ascending tone ranks 0,1,2,3; arbitrary natural binary 00,01,10,11'},
                 'evidence':{'transitions':len(edges),'clock_residual_rms_symbols':residual,
                             'checksum':'not_checked','protocol':'unknown'},
                 'symbol_count':len(symbols),'bit_count':len(bits),'bit_budget_reached':count>len(symbols),
                 'byte_alignment':'arbitrary first recovered symbol; natural binary dibits packed MSB-first',
                 'packed_padding_bits':(-len(bits))%8}
    return dict(base,status='timing_consistent_candidate',candidates=[candidate])


def search_fsk4(x,fs,bands,center_hz=0,max_channels=8,max_seconds=12,max_bits=100000):
    return search_fsk(x,fs,bands,center_hz,max_channels,max_seconds,max_bits,decoder=decode_fsk4)
