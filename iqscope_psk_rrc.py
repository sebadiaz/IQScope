"""Bounded feed-forward RRC PSK recovery; structural candidates, no protocol."""
import numpy as np
from scipy import signal, optimize, ndimage


def rrc_taps(samples_per_symbol, rolloff, span=10):
    half=int(np.ceil(span*samples_per_symbol/2))
    t=np.arange(-half,half+1)/samples_per_symbol
    with np.errstate(divide='ignore',invalid='ignore'):
        h=(np.sin(np.pi*t*(1-rolloff))+4*rolloff*t*np.cos(np.pi*t*(1+rolloff)))/(np.pi*t*(1-(4*rolloff*t)**2))
    h[half]=1+rolloff*(4/np.pi-1)
    special=np.isclose(abs(t),1/(4*rolloff),atol=1e-10,rtol=0)
    h[special]=rolloff/np.sqrt(2)*((1+2/np.pi)*np.sin(np.pi/(4*rolloff))+(1-2/np.pi)*np.cos(np.pi/(4*rolloff)))
    return h/np.sqrt(np.sum(h*h))


def _line(values, fs, lower, upper, minimum_fraction):
    n=len(values)
    power=abs(np.fft.fft(values))**2
    frequency=np.fft.fftfreq(n,1/fs)
    allowed=(frequency>=lower)&(frequency<=upper)
    if not np.any(allowed):
        return None
    index=np.flatnonzero(allowed)[np.argmax(power[allowed])]
    fraction=float(power[index]/max(np.sum(power),1e-30))
    if fraction<minimum_fraction:
        return None
    time=np.arange(n)/fs
    width=fs/n
    fit=optimize.minimize_scalar(lambda f:-abs(np.mean(values*np.exp(-2j*np.pi*f*time))),
                                 bounds=(max(lower,frequency[index]-width),min(upper,frequency[index]+width)),
                                 method='bounded',options={'xatol':width*1e-5,'maxiter':24})
    return float(fit.x),fraction


def _recover_rrc(x, fs, max_bits=50000, gain_control=False):
    # Source is already bounded by decode_psk. Downsample after carrier
    # correction only if an estimated baud supports a narrower front end.
    if len(x)<1024:
        return None
    power=float(np.mean(abs(x)**2))
    if power<1e-20:
        return None
    x=x/np.sqrt(power)
    envelope=abs(x)**2
    clock=_line(envelope-np.mean(envelope),fs,30,min(9600,fs/8),.006)
    if clock is None:
        return None
    baud,clock_fraction=clock
    if len(x)/fs*baud<100:
        return None
    time=np.arange(len(x))/fs
    for order in (2,4):
        # Clip rare amplitude spikes before taking the nonlinear power.
        bounded=x/np.maximum(1,abs(x)/2)
        carrier=_line(bounded**order,fs,-fs/2,fs/2,.025)
        if carrier is None:
            continue
        frequency,carrier_fraction=carrier
        corrected=x*np.exp(-2j*np.pi*frequency/order*time)
        # Limit matched-filter work to about 16 samples/symbol.
        down=max(1,int(fs/(16*baud)))
        y=signal.resample_poly(corrected,1,down) if down>1 else corrected
        rate=fs/down
        period=rate/baud
        if period<8:
            continue
        for rolloff in (.2,.35,.5):
            taps=rrc_taps(period,rolloff)
            filtered=signal.fftconvolve(y,taps,mode='same')
            gain_summary=None
            if gain_control:
                # Average many symbols: preserve symbol-to-symbol amplitudes.
                length=max(3,int(round(64*period))|1)
                gain=np.sqrt(np.maximum(ndimage.uniform_filter1d(abs(filtered)**2,size=length,mode='reflect'),1e-20))
                reference=float(np.median(gain))
                if reference<1e-12 or np.mean(gain<reference*.25)>.02:
                    continue
                gain=np.clip(gain,reference*.25,reference*4)
                filtered=filtered/gain
                gain_summary=np.percentile(gain,[10,90]).tolist()
            margin=6*period
            first=margin
            last=len(y)-margin
            if last-first<90*period:
                continue
            numbers=np.arange(int((last-first)/period))
            # Fit on <=2048 centers spread across the examined duration.
            chosen=np.unique(np.linspace(0,len(numbers)-1,min(2048,len(numbers)),dtype=int))
            fit_numbers=numbers[chosen]
            def evaluate(parameters, all_symbols=False):
                trial_baud,phase=parameters
                centers=first+(fit_numbers if not all_symbols else numbers)*rate/trial_baud+phase*period
                values=np.interp(centers,np.arange(len(filtered)),filtered.real)+1j*np.interp(centers,np.arange(len(filtered)),filtered.imag)
                values=values/max(np.sqrt(np.mean(abs(values)**2)),1e-15)
                origin=np.angle(np.mean(values**order))/order
                values*=np.exp(-1j*origin)
                labels=np.mod(np.rint(np.angle(values)*order/(2*np.pi)).astype(int),order)
                evm=float(np.sqrt(np.mean(abs(values-np.exp(2j*np.pi*labels/order))**2)))
                return evm,values,labels,centers,origin
            phases=np.arange(24)/24
            initial=min(phases,key=lambda p:evaluate((baud,p))[0])
            width=fs/len(x)
            fit=optimize.minimize(lambda p:evaluate(p)[0],(baud,initial),method='Powell',
                                  bounds=((max(30,baud-width),min(9600,fs/8,baud+width)),(0,1)),
                                  options={'maxiter':12,'maxfev':160,'xtol':1e-6,'ftol':1e-6})
            evm,values,labels,centers,origin=evaluate(fit.x,True)
            if evm>.16 or min(np.mean(labels==k) for k in range(order))<.12:
                continue
            # Require consistency in both halves, not only a favorable subset.
            target=np.exp(2j*np.pi*labels/order)
            if max(np.sqrt(np.mean(abs(a-b)**2)) for a,b in zip(np.array_split(values,2),np.array_split(target,2)))>.18:
                continue
            count=min(len(labels),max_bits//(1 if order==2 else 2))
            if count<64:
                continue
            samples=values[:count]
            symbols=labels[:count]
            bits=''.join(format(int(v),'01b' if order==2 else '02b') for v in symbols)
            points=samples[np.unique(np.linspace(0,count-1,min(512,count),dtype=int))]
            return {'modulation':'BPSK' if order==2 else 'QPSK',
                    'symbols':''.join(map(str,symbols.tolist())),'bits':bits,
                    'symbol_count':count,'bit_count':len(bits),'bit_budget_reached':len(labels)>count,
                    'packed_padding_bits':(-len(bits))%8,
                    'byte_alignment':'arbitrary first recovered symbol; MSB-first packing, zero-padded final byte',
                    'parameters':{'baud':float(fit.x[0]),'carrier_offset_hz':frequency/order,
                                  'amplitude_recovery':'local_rms_64_symbols' if gain_control else 'common_rms',
                                  'phase_origin_radians':float(origin),'first_symbol_center_seconds':float(centers[0]/rate),
                                  'pulse_shape':'rrc_trial','rrc_rolloff_trial':rolloff,'matched_filter_span_symbols':10,
                                  'timing_recovery':'cyclic envelope line plus bounded feed-forward EVM fit',
                                  'symbol_mapping':'counterclockwise phase ranks; natural binary, rotation and conjugation unresolved'},
                    'evidence':{'power_coherence':carrier_fraction,'power_measure':'FFT peak energy fraction before frequency refinement',
                                'clock_line_energy_fraction':clock_fraction,'symbol_evm_rms':evm,
                                'local_gain_p10_p90':gain_summary,
                                'checksum':'not_checked','protocol':'unknown'},
                    'constellation':{'i':points.real.tolist(),'q':points.imag.tolist(),
                                     'amplitude_normalized':True,'normalization':('local RMS over 64 symbols then common RMS; no per-symbol normalization' if gain_control else 'common RMS gain; per-symbol amplitudes preserved'),
                                     'sampled_symbols':True}}
    return None


def recover_rrc(x, fs, max_bits=50000):
    candidate=_recover_rrc(x,fs,max_bits)
    if candidate is not None or len(x)<1024:
        return candidate
    power=float(np.mean(abs(x)**2))
    if not np.isfinite(power) or power<1e-20:
        return None
    source=x/np.sqrt(power)
    envelope=abs(source)**2
    clock=_line(envelope-envelope.mean(),fs,30,min(9600,fs/8),.006)
    if clock is None or len(source)/fs*clock[0]<100:
        return None
    time=np.arange(len(source))/fs
    for order in (2,):
        bounded=source/np.maximum(1,abs(source)/2)
        powered=bounded**order
        spectrum=abs(np.fft.fft(powered))**2
        peak=int(np.argmax(spectrum))
        if spectrum[peak]/max(spectrum.sum(),1e-30)<.003:
            continue
        coarse=float(np.fft.fftfreq(len(source),1/fs)[peak])
        # Smooth the powered carrier below the symbol clock, so data
        # transitions are suppressed before following its unwrapped phase.
        down=max(1,int(np.ceil(fs/min(200,clock[0]/3))))
        rate=fs/down
        carrier=signal.resample_poly(powered*np.exp(-2j*np.pi*coarse*time),1,down)
        carrier_time=np.arange(len(carrier))/rate
        phase=np.unwrap(np.angle(carrier))
        tracked=np.interp(time,carrier_time,phase)
        corrected=source*np.exp(-1j*(2*np.pi*coarse*time+tracked)/order)
        guard=max(1,int(np.ceil(.03*fs)))
        candidate=_recover_rrc(corrected[:-guard],fs,max_bits)
        if candidate is None:
            candidate=_recover_rrc(corrected[:-guard],fs,max_bits,gain_control=True)
        if candidate is None or candidate['modulation']!=('BPSK' if order==2 else 'QPSK'):
            continue
        # Tracked phase is a numerical estimate, not a protocol reference.
        instantaneous=coarse/order+np.diff(phase)*rate/(2*np.pi*order)
        candidate['parameters']['carrier_offset_hz']+=float(np.median(instantaneous))
        candidate['parameters']['carrier_recovery']='smoothed Mth-power phase tracking within this window'
        candidate['parameters']['carrier_tracking_rate_hz']=rate
        candidate['parameters']['carrier_tracking_end_guard_seconds']=guard/fs
        candidate['evidence']['tracked_carrier_frequency_p10_p90_hz']=np.percentile(instantaneous,[10,90]).tolist()
        candidate['evidence']['carrier_tracking_order']=order
        return candidate
    return None
