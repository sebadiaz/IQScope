"""Blind binary FSK trials for a single stationary complex-IQ channel."""
import numpy as np
from scipy import ndimage


def decode_fsk(x,fs,max_seconds=12,max_bits=100000):
    base = {'decoder':'fsk2_generic','family':'2-FSK','candidates':[]}
    if not 1000<=fs<=96000 or len(x)<fs*.1:
        return dict(base,status='not_applicable')
    original = len(x)
    x = np.asarray(x[:int(fs*max_seconds)])
    base.update(analyzed_seconds=len(x)/fs,duration_limited=len(x)<original,
                validation_scope='two frequency levels and symbol timing only; no frame, checksum or protocol validation',
                limitations=['Single stationary channel, binary unshaped FSK, 20 baud to sample_rate/8 (max 9600).',
                             'Polarity and byte alignment are unknown; first and last partial symbols are omitted.',
                             'Rate aliases are possible when the data does not expose the fundamental clock.',
                             'Clock drift, bursts, overlapping channels, GFSK/MSK and M-FSK are not supported.'])
    amplitude = np.abs(x)
    median = float(np.median(amplitude))
    if median<1e-12 or np.mean(amplitude<median*.25)>.05:
        return dict(base,status='no_consistent_candidate')
    frequency = np.angle(x[1:]*np.conj(x[:-1]))*fs/(2*np.pi)
    frequency = ndimage.median_filter(frequency,size=3)
    low,high = np.percentile(frequency,[20,80])
    if high-low < 20:
        return dict(base,status='no_consistent_candidate')
    for _ in range(6):
        state = frequency>(low+high)/2
        if min(np.mean(state),np.mean(~state))<.1:
            return dict(base,status='no_consistent_candidate')
        low,high = np.median(frequency[~state]),np.median(frequency[state])
    spread = np.median(np.minimum(abs(frequency-low),abs(frequency-high)))
    if spread/(high-low)>.12:
        return dict(base,status='no_consistent_candidate')
    threshold = (low+high)/2
    state = frequency>threshold
    indices = np.flatnonzero(state[1:]!=state[:-1])
    if len(indices)<24:
        return dict(base,status='no_consistent_candidate')
    # Interpolate discriminator crossings. Frequency samples are at IQ midpoints.
    fraction = (threshold-frequency[indices])/(frequency[indices+1]-frequency[indices])
    edges = indices+fraction+.5
    durations = np.diff(edges)
    shortest = fs/min(9600,fs/8)
    longest = fs/20
    fit_durations = durations[:512]
    hypotheses = np.unique(np.round((fit_durations[:,None]/np.arange(1,9)).ravel(),3))
    hypotheses = hypotheses[(hypotheses>=shortest)&(hypotheses<=longest)]
    good = []
    for period in hypotheses:
        units = fit_durations/period
        error = float(np.mean(np.minimum(abs(units-np.round(units)),1)**2))
        if error<.008 and np.mean(abs(units-np.round(units))<.2)>.95:
            good.append((period,error))
    if not good:
        return dict(base,status='no_consistent_candidate')
    # The slowest consistent clock avoids arbitrary integer-multiple oversampling.
    period,_ = max(good)
    symbol_numbers = np.r_[0,np.cumsum(np.maximum(1,np.round(durations/period)))]
    period,origin = np.polyfit(symbol_numbers,edges,1)
    residual = float(np.sqrt(np.mean(((edges-(origin+period*symbol_numbers))/period)**2)))
    if residual>.15 or not shortest*.98<=period<=longest*1.02:
        return dict(base,status='no_consistent_candidate')
    count = int(np.floor((edges[-1]-origin)/period))
    if count<32:
        return dict(base,status='no_consistent_candidate')
    count_out = min(count,max_bits)
    centers = origin+(np.arange(count_out)+.5)*period
    values = np.interp(centers-.5,np.arange(len(frequency)),frequency)
    bits = (values>threshold).astype(np.uint8)
    contrast = np.minimum(abs(values-low),abs(values-high))/(high-low)
    if np.mean(contrast<.25)<.95:
        return dict(base,status='no_consistent_candidate')
    candidate = {'bits':''.join(map(str,bits.tolist())),
                 'parameters':{'baud':float(fs/period),'low_tone_hz':float(low),'high_tone_hz':float(high),
                               'shift_hz':float(high-low),'polarity':'high_tone_is_1; inverse equally possible',
                               'first_symbol_center_seconds':float(centers[0]/fs)},
                 'evidence':{'transitions':len(edges),'clock_residual_rms_symbols':residual,
                             'checksum':'not_checked','protocol':'unknown'},
                 'bit_count':count_out,'bit_budget_reached':count>max_bits,
                 'byte_alignment':'arbitrary first recovered bit; MSB-first packing with zero padding',
                 'packed_padding_bits':(-count_out)%8}
    return dict(base,status='timing_consistent_candidate',candidates=[candidate])


def search_fsk(x,fs,bands,center_hz=0,max_channels=8,max_seconds=12,max_bits=100000):
    """Try the full narrowband input, otherwise isolate detected spectral bands.

    Bands come from the shared stationary-spectrum detector. This does not infer
    a protocol and cannot guarantee that all FSK emitters have been found.
    """
    from scipy import signal
    direct = decode_fsk(x,fs,max_seconds=max_seconds,max_bits=max_bits)
    if direct['candidates']:
        direct['search_mode'] = 'direct_single_channel'
        for candidate in direct['candidates']:
            p = candidate['parameters']
            offset = (p['low_tone_hz']+p['high_tone_hz'])/2
            candidate['channel'] = {'offset_hz':offset,'frequency_hz':center_hz+offset,'sample_rate':fs}
        return direct
    if not 1000<=fs<=2_400_000 or len(x)<fs*.1:
        return direct
    original = len(x)
    x = np.asarray(x[:int(fs*max_seconds)])
    eligible = sorted((b for b in bands if b['bandwidth_hz']<=24000),
                      key=lambda b:b['spectral_snr_db'],reverse=True)
    selected = eligible[:max_channels]
    time = np.arange(len(x))/fs
    channels,candidates = [],[]
    for band in selected:
        offset = band['offset_hz']
        target = min(fs,96000,max(12000,4*band['bandwidth_hz']))
        decimation = max(1,int(fs/target))
        rate = fs/decimation
        if rate>96000:
            decimation += 1
            rate = fs/decimation
        mixed = x*np.exp(-2j*np.pi*offset*time)
        narrow = signal.resample_poly(mixed,1,decimation)
        # Explicit channel filter also isolates bands when no decimation is used.
        cutoff = min(rate*.4,max(1500,band['bandwidth_hz']))
        taps = signal.firwin(129,cutoff,fs=rate)
        narrow = signal.convolve(narrow,taps,mode='same')
        # Exclude filter boundary transients from timing evidence.
        trim = min(int(rate*.02),len(narrow)//10)
        trial = decode_fsk(narrow[trim:len(narrow)-trim],rate,max_seconds=max_seconds,max_bits=max_bits)
        channels.append({'offset_hz':offset,'frequency_hz':center_hz+offset,
                         'sample_rate':rate,'status':trial['status'],
                         'bandwidth_hz':band['bandwidth_hz']})
        for candidate in trial['candidates']:
            p = candidate['parameters']
            p['first_symbol_center_seconds'] += trim/rate
            for name in ('low_tone_hz','high_tone_hz'):
                p[name] += offset
            tone_center = (p['low_tone_hz']+p['high_tone_hz'])/2
            candidate['channel'] = {'offset_hz':tone_center,'frequency_hz':center_hz+tone_center,
                                    'sample_rate':rate,'detected_band_offset_hz':offset}
            candidates.append(candidate)
    return {'decoder':'fsk2_generic','family':'2-FSK','search_mode':'detected_spectral_bands',
            'status':'timing_consistent_candidate' if candidates else 'no_consistent_candidate',
            'candidates':candidates,'channels_examined':channels,'channel_budget':max_channels,
            'deferred_channel_count':max(0,len(eligible)-len(selected)),
            'excluded_wide_band_count':sum(b['bandwidth_hz']>24000 for b in bands),
            'analyzed_seconds':len(x)/fs,'duration_limited':len(x)<original,
            'validation_scope':direct.get('validation_scope','timing only; no protocol or checksum validation'),
            'limitations':['Shared stationary spectral detector; weak, overlapping, hopping and short burst signals can be missed.',
                           'At most eight bands <=24 kHz; output rate limits supported baud to channel_rate/8 (max 9600).',
                           'Polarity, byte alignment and protocol are unknown. Integer baud aliases remain possible.']}
