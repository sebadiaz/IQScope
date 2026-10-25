"""Bounded stationary CW trials; timing agreement does not certify text."""
import numpy as np
from scipy import signal

MORSE = dict(zip(
    '.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. ----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.'.split(),
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'))


def timing_candidate(envelope, rate):
    low,high = np.percentile(envelope,[15,85])
    if high < max(low*4,1e-12):
        return None
    keyed = envelope > (low+high)/2
    edges = np.r_[0,np.flatnonzero(keyed[1:]!=keyed[:-1])+1,len(keyed)]
    durations = np.diff(edges)/rate
    states = keyed[edges[:-1]]
    # Boundary runs may be truncated; only complete runs support timing fits.
    durations,states = durations[1:-1],states[1:-1]
    if len(durations)<20 or sum(states)<10:
        return None
    on = durations[states]
    off = durations[~states]
    best = None
    for dot in np.linspace(.024,.24,433):
        on_units = on/dot
        off_units = off/dot
        on_error = np.min(abs(on_units[:,None]-np.array([1,3])),axis=1)
        off_error = np.min(abs(off_units[:,None]-np.array([1,3,7])),axis=1)
        error = float(np.mean(np.r_[on_error,off_error]**2))
        if best is None or error < best[0]:
            best = error,dot
    error,dot = best
    if error > .12 or not np.any(on/dot<2) or not np.any(on/dot>2):
        return None
    if not np.any(off/dot>2) or not np.any(off/dot<2):
        return None
    text,pattern,raw = [],'',[]
    unknown = 0
    for duration,state in zip(durations,states):
        units = duration/dot
        if state:
            pattern += '.' if units<2 else '-'
        elif units>2:
            if pattern:
                raw.append(pattern)
                value = MORSE.get(pattern,'?')
                unknown += value=='?'
                text.append(value)
                pattern = ''
            if units>5 and text and text[-1]!=' ':
                text.append(' ')
    # Last complete keyed run ends at the final, possibly truncated silence.
    if pattern:
        raw.append(pattern)
        value = MORSE.get(pattern,'?')
        unknown += value=='?'
        text.append(value)
    if len(raw)<5 or unknown/max(1,len(raw))>.1:
        return None
    return {'text':''.join(text).strip(),'parameters':{'words_per_minute':1.2/dot,'dot_seconds':dot},
            'evidence':{'timing_mean_squared_error_units':error,'characters':len(raw),
                        'unknown_characters':unknown,'checksum':'not_present'},
            'raw_morse':raw,'score':len(raw)/(1+error),'score_kind':'heuristic_not_probability'}


def search_cw(x,fs,center_hz=0,max_channels=6,max_seconds=20):
    if not 1000<=fs<=2_400_000 or len(x)<fs:
        return {'decoder':'cw_morse','status':'not_applicable','candidates':[]}
    original = len(x)
    x = np.asarray(x[:int(fs*max_seconds)])
    size = min(len(x),262144,max(4096,int(fs/8)))
    f,p = signal.welch(x,fs,nperseg=size,return_onesided=False)
    f,p = np.fft.fftshift(f),np.fft.fftshift(p)
    peaks,_ = signal.find_peaks(p,distance=max(1,int(150/(fs/size))))
    floor = max(float(np.median(p)),1e-30)
    peaks = sorted((int(i) for i in peaks if p[i]>floor*30),key=lambda i:p[i],reverse=True)
    selected = peaks[:max_channels]
    time = np.arange(len(x))/fs
    decimation = max(1,int(fs/1000))
    rate = fs/decimation
    candidates,channels = [],[]
    for peak in selected:
        offset = float(f[peak])
        mixed = x*np.exp(-2j*np.pi*offset*time)
        narrow = signal.resample_poly(mixed,1,decimation)
        taps = signal.firwin(101,80,fs=rate)
        narrow = signal.convolve(narrow,taps,mode='same')
        envelope = np.abs(narrow)
        smooth = max(1,int(rate*.005))
        envelope = np.convolve(envelope,np.ones(smooth)/smooth,mode='same')
        step = max(1,int(rate/200))
        candidate = timing_candidate(envelope[::step],rate/step)
        channels.append({'offset_hz':offset,'frequency_hz':center_hz+offset,
                         'status':'timing_consistent_candidate' if candidate else 'no_consistent_candidate'})
        if candidate:
            candidate['channel'] = {'offset_hz':offset,'frequency_hz':center_hz+offset}
            candidates.append(candidate)
    candidates.sort(key=lambda c:c['score'],reverse=True)
    return {'decoder':'cw_morse','family':'CW / Morse','status':'timing_consistent_candidate' if candidates else 'no_consistent_candidate',
            'candidates':candidates,'channels_examined':channels,'channel_budget':max_channels,
            'deferred_peak_count':max(0,len(peaks)-len(selected)),
            'analyzed_seconds':len(x)/fs,'duration_limited':len(x)<original,
            'validation_scope':'Morse timing and alphabet consistency only; no checksum or authenticity',
            'limitations':['Stationary on-off keyed carriers, 5–50 WPM and standard spacing only.',
                           'Short messages, hand keying, Farnsworth spacing, fading, overlap and hopping may fail.',
                           'Boundary characters may be incomplete; alphabet supports A–Z and 0–9 only.']}
