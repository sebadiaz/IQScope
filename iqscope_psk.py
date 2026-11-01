"""Conservative blind rectangular/RRC BPSK/QPSK trials; no protocol validation."""
import math
import numpy as np
from scipy import signal, optimize
from iqscope_fsk import recover_clock


def _decode_rectangular(x, fs, max_seconds=3, max_bits=50000):
    result = {'decoder':'psk_generic','family':'BPSK / QPSK','candidates':[],
              'validation_scope':'phase clusters and symbol timing only; no protocol, CRC or authenticity',
              'limitations':['Rectangular, stationary single-carrier BPSK/QPSK only; not RRC-shaped PSK, OQPSK or QAM.',
                              '20 baud to min(9600, sample_rate/8); carrier offset must be within sample_rate/(2*M).',
                              'Absolute rotation, I/Q conjugation, bit mapping and byte alignment remain ambiguous.',
                              'Bursts, fading, clock drift and overlapping signals may fail; baud aliases remain possible.']}
    if not math.isfinite(fs) or not 1000 <= fs <= 96000 or len(x) < fs*.1:
        return dict(result,status='not_applicable')
    original=len(x)
    count=min(original,int(fs*max_seconds),288000)
    x=np.asarray(x[:count],dtype=np.complex128)
    result.update(analyzed_seconds=count/fs,duration_limited=count<original)
    if not np.all(np.isfinite(x)):
        return dict(result,status='no_consistent_candidate')
    amplitude=np.abs(x)
    median=float(np.median(amplitude))
    if median<1e-12 or np.mean(amplitude<median*.5)>.02 or np.std(amplitude)/np.mean(amplitude)>.25:
        return dict(result,status='no_consistent_candidate')
    unit=x/np.maximum(amplitude,1e-15)
    time=np.arange(count)/fs
    for order in (2,4):
        # A power-spectrum line removes symbols without unwrapping through
        # transition fades. Refine inside one FFT bin, then estimate phase.
        powered=unit**order
        spectrum=abs(np.fft.fft(powered))**2
        peak=int(np.argmax(spectrum))
        if spectrum[peak]/max(float(np.sum(spectrum)),1e-30)<.2:
            continue
        coarse=float(np.fft.fftfreq(count,1/fs)[peak])
        width=fs/count
        def loss(frequency):
            return -abs(np.mean(powered*np.exp(-2j*np.pi*frequency*time)))
        fit=optimize.minimize_scalar(loss,bounds=(coarse-width,coarse+width),
                                     method='bounded',options={'xatol':width*1e-5,'maxiter':24})
        slope=2*np.pi*float(fit.x)
        mean=np.mean(powered*np.exp(-1j*slope*time))
        intercept=float(np.angle(mean))
        coherence=float(abs(mean))
        if coherence<.95:
            continue
        corrected=unit*np.exp(-1j*(slope*time+intercept)/order)
        labels=np.mod(np.rint(np.angle(corrected)*order/(2*np.pi)).astype(int),order)
        error=np.angle(corrected*np.exp(-2j*np.pi*labels/order))
        rms=float(np.sqrt(np.mean(error**2)))
        if rms>.15 or min(np.mean(labels==k) for k in range(order))<.1:
            continue
        indices=np.flatnonzero(labels[1:]!=labels[:-1])
        if len(indices)<32 or len(indices)>60000:
            continue
        # A filtered phase jump can briefly cross an intermediate rank.
        groups=np.r_[0,np.flatnonzero(np.diff(indices)>3)+1,len(indices)]
        edges=np.array([(indices[a]+indices[b-1])/2+.5 for a,b in zip(groups[:-1],groups[1:])])
        clock=recover_clock(edges,fs,max_bits//(1 if order==2 else 2))
        if clock is None:
            continue
        centers,residual,total=clock
        if len(centers)<64:
            continue
        samples=np.interp(centers,np.arange(count),corrected.real)+1j*np.interp(centers,np.arange(count),corrected.imag)
        symbols=np.mod(np.rint(np.angle(samples)*order/(2*np.pi)).astype(int),order)
        bits=''.join(format(int(value),'01b' if order==2 else '02b') for value in symbols)
        constellation=samples[np.unique(np.linspace(0,len(samples)-1,min(512,len(samples)),dtype=int))]
        candidate={'modulation':'BPSK' if order==2 else 'QPSK','symbols':''.join(map(str,symbols.tolist())),
                   'bits':bits,'symbol_count':len(symbols),'bit_count':len(bits),
                   'bit_budget_reached':total>len(symbols),'packed_padding_bits':(-len(bits))%8,
                   'byte_alignment':'arbitrary first recovered symbol; MSB-first packing, zero-padded final byte',
                   'parameters':{'baud':float(fs/(centers[1]-centers[0])),
                                 'carrier_offset_hz':float(slope/(2*np.pi*order)),
                                 'phase_origin_radians':float(intercept/order),
                                 'first_symbol_center_seconds':float(centers[0]/fs),
                                 'symbol_mapping':'counterclockwise phase ranks; natural binary, rotation and conjugation unresolved'},
                   'evidence':{'power_coherence':coherence,'phase_error_rms_radians':rms,
                               'clock_residual_rms_symbols':residual,'transitions':len(edges),
                               'checksum':'not_checked','protocol':'unknown'},
                   'constellation':{'i':constellation.real.tolist(),'q':constellation.imag.tolist(),
                                    'amplitude_normalized':True,'sampled_symbols':True}}
        result['candidates']=[candidate]
        return dict(result,status='timing_consistent_candidate')
    return dict(result,status='no_consistent_candidate')


def decode_psk(x, fs, max_seconds=3, max_bits=50000, quality_start_seconds=0):
    if not math.isfinite(quality_start_seconds) or quality_start_seconds<0:
        raise ValueError('PSK quality start must be finite and nonnegative')
    result=_decode_rectangular(x,fs,max_seconds,max_bits)
    result['limitations'][0]='Stationary rectangular or bounded RRC BPSK/QPSK trials; not OQPSK, differential PSK or QAM.'
    result['limitations'].append('RRC: strongest envelope clock line only, >=100 examined symbols, rolloff trials .2/.35/.5; feed-forward window fit, not continuous tracking.')
    if result['candidates'] or result['status']=='not_applicable':
        for candidate in result['candidates']:
            candidate['parameters']['pulse_shape']='rectangular_trial'
        return result
    source=np.asarray(x[:min(len(x),int(fs*max_seconds),288000)],dtype=np.complex128)
    if not np.all(np.isfinite(source)):
        return result
    from iqscope_psk_rrc import recover_rrc
    candidate=recover_rrc(source,fs,max_bits,quality_start_seconds=quality_start_seconds)
    result['rrc_search']={'rolloff_trials':[.2,.35,.5], 'minimum_examined_symbols':100,
                          'validation':'structural EVM only; no protocol or CRC'}
    if candidate is not None:
        result.update(candidates=[candidate],status='timing_consistent_candidate')
    return result


def search_psk(x, fs, bands, center_hz=0, max_channels=4):
    original=len(x)
    direct=decode_psk(x,fs)
    if direct['candidates']:
        direct['search_mode']='direct_single_channel'
        for candidate in direct['candidates']:
            offset=candidate['parameters']['carrier_offset_hz']
            candidate['channel']={'offset_hz':offset,'frequency_hz':center_hz+offset if center_hz else None,'sample_rate':fs}
        return direct
    if not math.isfinite(fs) or not 1000<=fs<=2_400_000:
        return direct
    eligible=sorted((b for b in bands if b['bandwidth_hz']<=48000),key=lambda b:b['spectral_snr_db'],reverse=True)
    source=np.asarray(x[:min(len(x),int(fs*3),2_400_000)])
    time=np.arange(len(source))/fs
    channels=[]
    candidates=[]
    for band in eligible[:max_channels]:
        target=min(96000,fs,max(12000,6*band['bandwidth_hz']))
        down=max(1,math.ceil(fs/target))
        rate=fs/down
        offset=band['offset_hz']
        mixed=source*np.exp(-2j*np.pi*offset*time)
        narrow=signal.resample_poly(mixed,1,down) if down>1 else mixed
        trial=decode_psk(narrow,rate)
        channels.append({'offset_hz':offset,'sample_rate':rate,'source_sample_start':0,
                         'source_sample_end':len(source),'status':trial['status']})
        for candidate in trial['candidates']:
            actual=offset+candidate['parameters']['carrier_offset_hz']
            candidate['channel']={'offset_hz':actual,'frequency_hz':center_hz+actual if center_hz else None,
                                  'sample_rate':rate,'detected_band_offset_hz':offset}
            candidates.append(candidate)
    direct.update(candidates=candidates,channels_examined=channels,channel_budget=max_channels,
                  deferred_channel_count=max(0,len(eligible)-max_channels),
                  search_mode='detected_spectral_bands',duration_limited=len(source)<original,
                  analyzed_seconds=len(source)/fs,
                  status='timing_consistent_candidate' if candidates else 'no_consistent_candidate')
    return direct


def write_psk_artifacts(trial, out):
    import json
    from pathlib import Path
    out=Path(out)
    for index,candidate in enumerate(trial.get('candidates',[])):
        prefix='psk' if index==0 else f'psk-{index+1}'
        artifacts={'bits':prefix+'-bits.txt','packed':prefix+'-packed.bin','symbols':prefix+'-symbols.txt'}
        (out/artifacts['bits']).write_text(candidate['bits'],encoding='ascii')
        (out/artifacts['symbols']).write_text(candidate['symbols'],encoding='ascii')
        bits=np.fromiter((int(bit) for bit in candidate['bits']),dtype=np.uint8)
        (out/artifacts['packed']).write_bytes(np.packbits(bits,bitorder='big').tobytes())
        candidate['artifacts']=artifacts
    if trial.get('candidates'):
        trial['artifact']='psk-candidates.json'
        (out/trial['artifact']).write_text(json.dumps(trial,indent=2),encoding='utf-8')
