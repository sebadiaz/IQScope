"""Bounded square 16-QAM trials. Symbol labels do not identify a protocol."""
import math
from pathlib import Path
import json
import numpy as np
from scipy import signal, optimize
from iqscope_psk_rrc import _line, rrc_taps

LEVELS=np.array([-3,-1,1,3],dtype=float)/np.sqrt(10)


def decode_qam16(x,fs,max_seconds=3,max_bits=40000):
    result={'decoder':'qam16_generic','family':'16-QAM','candidates':[],
            'validation':'constellation, occupancy and timing only; protocol, bit mapping, byte alignment and CRC unknown',
            'limitations':['Stationary single-carrier square 16-QAM with RRC pulse shaping; no fading, equalizer or persistent phase tracking.',
                            '1–96 kS/s; 30 to min(9600, sample_rate/8) baud; at least 256 recovered symbols.',
                            'Carrier offset ambiguity modulo sample_rate/4; direct unambiguous range is +/- sample_rate/8.',
                            'Strongest envelope clock line only, three RRC rolloffs; bursts, low rolloff and interfering carriers may fail.']}
    if not math.isfinite(fs) or not 1000<=fs<=96000 or len(x)<1024:
        return dict(result,status='not_applicable')
    count=min(len(x),int(fs*max_seconds),288000)
    source=np.array(x[:count],dtype=np.complex128,copy=True)
    result.update(analyzed_seconds=count/fs,duration_limited=count<len(x))
    power=float(np.mean(abs(source)**2))
    if not np.isfinite(power) or power<1e-20 or not np.all(np.isfinite(source)):
        return dict(result,status='no_consistent_candidate')
    source/=np.sqrt(power)
    envelope=abs(source)**2
    clock=_line(envelope-envelope.mean(),fs,30,min(9600,fs/8),.001)
    if clock is None or count/fs*clock[0]<280:
        return dict(result,status='no_consistent_candidate')
    carrier=_line(source**4,fs,-fs/2,fs/2,.005)
    if carrier is None:return dict(result,status='no_consistent_candidate')
    baud,clock_strength=clock;frequency,carrier_strength=carrier
    time=np.arange(count)/fs
    corrected=source*np.exp(-2j*np.pi*frequency/4*time)
    down=max(1,int(fs/(16*baud)))
    y=signal.resample_poly(corrected,1,down) if down>1 else corrected
    rate=fs/down;period=rate/baud
    for rolloff in (.2,.35,.5):
        filtered=signal.fftconvolve(y,rrc_taps(period,rolloff),mode='same')
        numbers=np.arange(int((len(y)-12*period)/period))
        if len(numbers)<256:continue
        fit_numbers=numbers[np.unique(np.linspace(0,len(numbers)-1,min(2048,len(numbers)),dtype=int))]
        def evaluate(parameters,full=False):
            trial_baud,phase=parameters
            centers=6*period+(numbers if full else fit_numbers)*rate/trial_baud+phase*period
            values=np.interp(centers,np.arange(len(filtered)),filtered.real)+1j*np.interp(centers,np.arange(len(filtered)),filtered.imag)
            values/=max(np.sqrt(np.mean(abs(values)**2)),1e-15)
            origin=(np.angle(np.mean(values**4))-np.pi)/4
            values*=np.exp(-1j*origin)
            i=np.argmin(abs(values.real[:,None]-LEVELS),axis=1)
            q=np.argmin(abs(values.imag[:,None]-LEVELS),axis=1)
            ideal=LEVELS[i]+1j*LEVELS[q]
            evm=float(np.sqrt(np.mean(abs(values-ideal)**2)))
            return evm,values,i,q,centers,origin
        phases=np.arange(24)/24
        initial=min(phases,key=lambda p:evaluate((baud,p))[0])
        width=fs/count
        fit=optimize.minimize(lambda p:evaluate(p)[0],(baud,initial),method='Powell',
                             bounds=((max(30,baud-width),min(9600,fs/8,baud+width)),(0,1)),
                             options={'maxiter':12,'maxfev':160,'xtol':1e-6,'ftol':1e-6})
        evm,values,i,q,centers,origin=evaluate(fit.x,True)
        labels=4*i+q
        if evm>.12 or min(np.mean(labels==k) for k in range(16))<.015:continue
        ideal=LEVELS[i]+1j*LEVELS[q]
        if max(np.sqrt(np.mean(abs(a-b)**2)) for a,b in zip(np.array_split(values,2),np.array_split(ideal,2)))>.14:continue
        total=len(labels);n=min(total,max_bits//4)
        if n<256:continue
        labels=labels[:n];points=values[np.unique(np.linspace(0,n-1,min(n,512),dtype=int))]
        bits=''.join(format(int(label),'04b') for label in labels)
        result['candidates']=[{'modulation':'16-QAM','symbols':labels.tolist(),'bits':bits,'symbol_count':n,'bit_count':len(bits),
                               'bit_budget_reached':total>n,'packed_padding_bits':(-len(bits))%8,
                               'byte_alignment':'arbitrary recovered symbol; natural I/Q labels packed MSB-first, final zero padding',
                               'parameters':{'baud':float(fit.x[0]),'carrier_offset_hz':frequency/4,'phase_origin_radians':float(origin),
                                             'first_symbol_center_seconds':float(centers[0]/rate),'rrc_rolloff_trial':rolloff,
                                             'symbol_mapping':'4*I_rank+Q_rank, ranks ascending -3,-1,+1,+3; arbitrary natural binary, rotation/conjugation unresolved'},
                               'evidence':{'symbol_evm_rms':evm,'clock_line_energy_fraction':clock_strength,
                                           'carrier_line_energy_fraction':carrier_strength,'checksum':'not_checked','protocol':'unknown'},
                               'constellation':{'i':points.real.tolist(),'q':points.imag.tolist(),'normalization':'common RMS gain; symbol amplitudes retained','sampled_symbols':True}}]
        return dict(result,status='constellation_consistent_candidate')
    return dict(result,status='no_consistent_candidate')


def search_qam16(x,fs,bands,center_hz=0):
    result=decode_qam16(x,fs)
    if result['candidates']:
        result['search_mode']='direct_single_channel'
        for candidate in result['candidates']:
            offset=candidate['parameters']['carrier_offset_hz']
            candidate['channel']={'offset_hz':offset,'frequency_hz':center_hz+offset if center_hz else None,'sample_rate':fs}
        return result
    if not math.isfinite(fs) or not 1000<=fs<=2_400_000:return result
    eligible=sorted((b for b in bands if b['bandwidth_hz']<=48000),key=lambda b:b['spectral_snr_db'],reverse=True)
    source=np.asarray(x[:min(len(x),int(fs*3),2_400_000)])
    time=np.arange(len(source))/fs
    channels=[];candidates=[]
    for band in eligible[:4]:
        offset=band['offset_hz'];target=min(96000,fs,max(12000,6*band['bandwidth_hz']))
        down=max(1,math.ceil(fs/target));rate=fs/down
        mixed=source*np.exp(-2j*np.pi*offset*time)
        narrow=signal.resample_poly(mixed,1,down) if down>1 else mixed
        trial=decode_qam16(narrow,rate)
        channels.append({'offset_hz':offset,'sample_rate':rate,'status':trial['status'],'source_sample_start':0,'source_sample_end':len(source)})
        for candidate in trial['candidates']:
            actual=offset+candidate['parameters']['carrier_offset_hz']
            candidate['channel']={'offset_hz':actual,'frequency_hz':center_hz+actual if center_hz else None,'sample_rate':rate}
            candidates.append(candidate)
    result['limitations']+=['At most four spectral bands <=48 kHz from sources <=2.4 MS/s, first three seconds and 2400000 input samples; weak, overlapping or hopping signals may be missed.']
    result.update(candidates=candidates,channels_examined=channels,search_mode='detected_spectral_bands',
                  channel_budget=4,deferred_channel_count=max(0,len(eligible)-4),
                  analyzed_seconds=len(source)/fs,duration_limited=len(source)<len(x),
                  status='constellation_consistent_candidate' if candidates else 'no_consistent_candidate')
    return result


def write_qam_artifacts(trial,out):
    out=Path(out)
    for index,candidate in enumerate(trial['candidates'],1):
        prefix=f'qam16-{index}'
        candidate['artifacts']={'bits':prefix+'-bits.txt','packed':prefix+'-packed.bin','symbols':prefix+'-symbols.json'}
        artifacts=candidate['artifacts']
        (out/artifacts['bits']).write_text(candidate['bits'],encoding='ascii')
        (out/artifacts['packed']).write_bytes(np.packbits(np.array(list(candidate['bits']),dtype='u1'),bitorder='big').tobytes())
        (out/artifacts['symbols']).write_text(json.dumps(candidate['symbols']))
    if trial['candidates']:
        trial['artifact']='qam16-candidates.json'
        (out/trial['artifact']).write_text(json.dumps(trial,indent=2))
