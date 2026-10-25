"""Bounded blind RTTY/ITA2 trials. Framing consistency is not a checksum."""
import math

import numpy as np
from scipy import signal

LETTERS = ('', 'E', '\n', 'A', ' ', 'S', 'I', 'U', '\r', 'D', 'R', 'J', 'N', 'F', 'C', 'K',
           'T', 'Z', 'L', 'W', 'H', 'Y', 'P', 'Q', 'O', 'B', 'G', '', 'M', 'X', 'V', '')
# International ITA2 figures. National variants require separate profiles.
FIGURES = ('', '3', '\n', '-', ' ', "'", '8', '7', '\r', '\x05', '4', '\a', ',', '!', ':', '(',
           '5', '+', ')', '2', '£', '6', '0', '1', '9', '?', '&', '', '.', '/', '=', '')
BAUD_RATES = (45.45, 50.0, 75.0, 100.0)


def ita2_text(codes):
    figures = False
    text = []
    for code in codes:
        if code == 27:
            figures = True
        elif code == 31:
            figures = False
        else:
            value = (FIGURES if figures else LETTERS)[code]
            # Keep CR/LF, but display enquiry/bell without triggering terminals.
            text.append({'\x05':'[ENQ]', '\a':'[BEL]'}.get(value,value))
    return ''.join(text)


def tone_pairs(x, fs, limit=4):
    size = min(4096, len(x))
    frequencies, power = signal.welch(x,fs,nperseg=size,return_onesided=False)
    frequencies, power = np.fft.fftshift(frequencies), np.fft.fftshift(power)
    peaks,_ = signal.find_peaks(power,distance=max(1,int(35/(fs/size))))
    floor = max(float(np.median(power)),1e-30)
    peaks = sorted((int(i) for i in peaks if power[i] > floor*5),key=lambda i:power[i],reverse=True)[:12]
    pairs = []
    for a in range(len(peaks)):
        for b in range(a+1,len(peaks)):
            i,j = peaks[a],peaks[b]
            shift = abs(float(frequencies[i]-frequencies[j]))
            if not 80 <= shift <= min(1100,fs*.8):
                continue
            relative_error = min(abs(shift-nominal)/nominal for nominal in (170,425,450,850))
            if relative_error > .15:
                continue
            rank = math.sqrt(float(power[i]*power[j]))/(1+relative_error*5)
            low,high = sorted((float(frequencies[i]),float(frequencies[j])))
            pairs.append((rank,low,high))
    pairs.sort(reverse=True)
    selected = []
    for _,low,high in pairs:
        if any(abs(low-a)<25 and abs(high-b)<25 for a,b in selected):
            continue
        selected.append((low,high))
        if len(selected) >= limit:
            break
    return selected


def frame_trial(discriminator, fs, baud, high_is_mark):
    d = discriminator if high_is_mark else -discriminator
    spb = fs/baud
    mark = d > 0
    edges = np.flatnonzero(mark[:-1] & ~mark[1:])
    codes,events = [],[]
    rejected = 0
    next_allowed = spb
    for edge in edges:
        if edge < next_allowed:
            continue
        denominator = d[edge]-d[edge+1]
        start = edge+(d[edge]/denominator if denominator else .5)
        times = start+spb*np.array([-.4,.5,1.5,2.5,3.5,4.5,5.5,6.5,7.0])
        if times[0] < 0 or times[-1] >= len(d)-1:
            continue
        indices = np.floor(times).astype(int)
        fractions = times-indices
        values = d[indices]*(1-fractions)+d[indices+1]*fractions
        decisions = values > 0
        framing = decisions[0] and not decisions[1] and decisions[-2] and decisions[-1]
        if not framing or np.min(np.abs(values)) < .2:
            rejected += 1
            continue
        code = sum(int(bit) << i for i,bit in enumerate(decisions[2:7]))
        codes.append(code)
        events.append({'sample_start':int(round(start)),'time_seconds':float(start/fs),
                       'code':code,'minimum_bit_contrast':float(np.min(np.abs(values)))})
        next_allowed = start+spb*7.2
    longest = current = 0
    previous = None
    for event in events:
        position = event['sample_start']
        gap = (position-previous)/spb if previous is not None else 0
        current = current+1 if previous is not None and 7.1 <= gap <= 10 else 1
        longest = max(longest,current)
        previous = position
    ratio = len(codes)/max(1,len(codes)+rejected)
    return codes,events,longest,ratio


def decode_rtty(x,fs,max_seconds=12,max_pairs=4):
    """Search common shifts and 45.45/50/75/100 baud without user DSP settings.

    This first receiver operates on a single low-bandwidth complex IQ source.
    It does not search an arbitrary wideband receiver or claim CRC validation.
    """
    if not 1000 <= fs <= 12000 or len(x) < fs*.8:
        return {'decoder':'rtty_ita2','family':'RTTY / ITA2','status':'not_applicable','candidates':[]}
    original_count = len(x)
    count = min(original_count,int(fs*max_seconds))
    x = np.asarray(x[:count])
    pairs = tone_pairs(x,fs,max_pairs)
    time = np.arange(len(x))/fs
    candidates = []
    diagnostics = []
    trials = 0
    for low,high in pairs:
        mixed = [x*np.exp(-2j*np.pi*f*time) for f in (low,high)]
        for baud in BAUD_RATES:
            width = max(3,int(round(fs/baud*.65)))
            window = np.ones(width)/width
            energies = [np.abs(np.convolve(v,window,mode='same'))**2 for v in mixed]
            d = (energies[1]-energies[0])/np.maximum(energies[1]+energies[0],1e-20)
            if np.mean(d > .45)<.04 or np.mean(d < -.45)<.04:
                continue
            for normal in (True,False):
                trials += 1
                codes,events,longest,ratio = frame_trial(d,fs,baud,normal)
                diagnostics.append({'baud':baud,'low_tone_hz':low,'high_tone_hz':high,'high_tone_is_mark':normal,
                                    'framed_characters':len(codes),'longest_consistent_run':longest,'framing_ratio':ratio})
                text = ita2_text(codes)
                visible_text = text.replace('[ENQ]','').replace('[BEL]','')
                printable = [v for v in visible_text if v.isprintable() and not v.isspace()]
                if longest < 8 or ratio < .7 or len(printable)<8 or len(set(printable))<2:
                    continue
                score = longest*ratio+len(codes)*ratio*.15
                candidates.append({'text':text,'parameters':{'baud':baud,'shift_hz':high-low,
                    'low_tone_hz':low,'high_tone_hz':high,'high_tone_is_mark':normal,
                    'data_bits':5,'stop_bits_tested':1.5,'bit_order':'lsb_first'},
                    'score':score,'score_kind':'heuristic_not_probability',
                    'evidence':{'framed_characters':len(codes),'longest_consistent_run':longest,
                                'framing_ratio':ratio,'checksum':'not_present'},
                    'raw_codes':codes,'characters':events,
                    'initial_shift_state':'letters_assumed_until_first_shift_code'})
    candidates.sort(key=lambda c:c['score'],reverse=True)
    distinct = []
    for candidate in candidates:
        if not any(c['text']==candidate['text'] for c in distinct):
            distinct.append(candidate)
        if len(distinct)==3:
            break
    return {'decoder':'rtty_ita2','family':'RTTY / ITA2',
            'status':'framing_consistent_candidate' if distinct else 'no_consistent_candidate',
            'candidates':distinct,'trials':trials,'tone_pairs_examined':len(pairs),
            'analyzed_seconds':count/fs,'duration_limited':count<original_count,
            'best_trial_diagnostics':sorted(diagnostics,key=lambda d:d['longest_consistent_run']*d['framing_ratio'],reverse=True)[:3],
            'validation_scope':'timing and framing consistency only; no checksum or content authenticity',
            'limitations':['Single low-bandwidth IQ source; wideband RTTY channel search is not implemented.',
                           'National ITA2 variants, fading, collisions and clock drift may alter text.']}


def search_rtty(x, fs, center_hz=0, max_channels=8, max_seconds=12):
    """Bounded spectral-pair search followed by filtered narrowband trials.

    Frequency estimates refer to the original IQ center. This searches stationary
    FSK tone pairs, not arbitrary bursts or frequency-hopping transmissions.
    """
    if fs <= 12000:
        return decode_rtty(x, fs, max_seconds=max_seconds)
    if fs > 2_400_000 or len(x) < fs*.8:
        return {'decoder':'rtty_ita2','status':'not_applicable','candidates':[]}
    original_count = len(x)
    x = np.asarray(x[:int(fs*max_seconds)])
    size = min(262144, len(x), max(4096, int(fs/8)))
    f,p = signal.welch(x,fs,nperseg=size,return_onesided=False)
    f,p = np.fft.fftshift(f),np.fft.fftshift(p)
    peaks,_ = signal.find_peaks(p,distance=max(1,int(35/(fs/size))))
    floor = max(float(np.median(p)),1e-30)
    peaks = sorted((int(i) for i in peaks if p[i]>floor*10),key=lambda i:p[i],reverse=True)[:96]
    pairs = []
    for a,i in enumerate(peaks):
        for j in peaks[a+1:]:
            shift = abs(float(f[i]-f[j]))
            if min(abs(shift-v)/v for v in (170,425,450,850)) <= .12:
                offset = float((f[i]+f[j])/2)
                if abs(offset)+1500 < fs/2:
                    pairs.append((math.sqrt(float(p[i]*p[j])),offset))
    pairs.sort(reverse=True)
    offsets = []
    for _,offset in pairs:
        if not any(abs(offset-v)<1000 for v in offsets):
            offsets.append(offset)
    selected = offsets[:max_channels]
    candidates,channels = [],[]
    decimation = max(1,int(fs/4000))
    rate = fs/decimation
    time = np.arange(len(x))/fs
    for offset in selected:
        mixed = x*np.exp(-2j*np.pi*offset*time)
        narrow = signal.resample_poly(mixed,1,decimation)
        trial = decode_rtty(narrow,rate,max_seconds=max_seconds)
        channels.append({'offset_hz':offset,'frequency_hz':center_hz+offset,
                         'sample_rate':rate,'status':trial['status'],
                         'candidate_count':len(trial['candidates'])})
        for candidate in trial['candidates']:
            candidate['channel'] = {'offset_hz':offset,'frequency_hz':center_hz+offset,'sample_rate':rate}
            for name in ('low_tone_hz','high_tone_hz'):
                candidate['parameters'][name] += offset
            candidates.append(candidate)
    candidates.sort(key=lambda v:v['score'],reverse=True)
    return {'decoder':'rtty_ita2','family':'RTTY / ITA2',
            'status':'framing_consistent_candidate' if candidates else 'no_consistent_candidate',
            'candidates':candidates,'search_mode':'wideband_spectral_pairs',
            'channels_examined':channels,'channel_budget':max_channels,
            'deferred_channel_count':max(0,len(offsets)-len(selected)),
            'spectral_peak_budget':96,'spectral_peak_budget_reached':len(peaks)==96,
            'analyzed_seconds':len(x)/fs,'duration_limited':len(x)<original_count,
            'validation_scope':'framing consistency only; no checksum or content authenticity',
            'limitations':['Stationary separated tone pairs only; weak, overlapping or hopping signals may be missed.',
                           'Peak, channel and duration budgets bound the search; this is not an exhaustive detector.']}
