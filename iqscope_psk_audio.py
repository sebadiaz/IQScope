"""PSK trials on derived analytic receiver audio; never original RF IQ."""
import numpy as np
from scipy import signal, ndimage
from iqscope_psk import decode_psk
from iqscope_ax25 import decode_psk_ax25


def search_audio_psk(audio, fs):
    block=max(1,round(fs*.01))
    count=len(audio)//block
    energy=np.mean(np.asarray(audio[:count*block]).reshape(count,block)**2,axis=1)
    floor=max(float(np.percentile(energy,30)),1e-15)
    labels,number=ndimage.label(energy>floor*100)
    windows=[]
    for index in range(1,number+1):
        bins=np.flatnonzero(labels==index)
        start=int(bins[0]*block+.02*fs)
        end=int((bins[-1]+1)*block)
        if end-start>=.15*fs:
            windows.append((start,min(end,start+int(3*fs))))
    burst_mode=bool(windows)
    if not windows:
        windows=[(0,min(len(audio),int(3*fs)))]
    # Interpolation improves numerical timing resolution; it adds no bandwidth.
    analytic=signal.resample_poly(signal.hilbert(audio),2,1)
    rate=fs*2
    result={'decoder':'psk_generic','family':'BPSK / QPSK receiver audio','candidates':[],
            'frequency_reference':'audio_hz','source_kind':'derived_analytic_receiver_audio',
            'windows_examined':[],'deferred_window_count':max(0,len(windows)-4),
            'search_mode':'energy_bursts' if burst_mode else 'first_audio_window',
            'validation_scope':'PSK phase/timing candidates only; AX.25 requires separate CRC validation',
            'limitations':['Mono receiver audio converted by Hilbert transform and interpolated 2x; no original RF IQ or RF frequency.',
                            'At most four energy bursts, three seconds each; trim 20 ms from burst starts; carrier tracking discards a 30 ms ending guard.',
                            'Energy threshold is 20 dB over the 30th percentile; weak bursts and overlapping signals may be missed.',
                            'At most one 100 ms leading-context retry per candidate window without valid AX.25; replacement requires valid FCS and UI structure.',
                            'Constant low-SNR or long signals may fail. No continuity of carrier tracking between windows.']}
    for start,end in windows[:4]:
        trial=decode_psk(analytic[start*2:end*2],rate)
        result['windows_examined'].append({'source_sample_start':start,'source_sample_end':end,
                                           'source_sample_rate':fs,'status':trial['status']})
        candidate_start=start
        if trial['candidates'] and not decode_psk_ax25(trial['candidates'])['frames'] and start>0:
            padded=max(0,start-round(.1*fs))
            prefix=(start-padded)/fs
            retry=decode_psk(analytic[padded*2:end*2],rate,max_seconds=3+prefix,quality_start_seconds=prefix)
            accepted=bool(decode_psk_ax25(retry['candidates'])['frames'])
            result['windows_examined'][-1]['context_retry']={'source_sample_start':padded,'quality_start_source_sample':start,
                                                          'accepted_by_ax25_crc':accepted}
            if accepted:
                trial=retry
                candidate_start=padded
        for candidate in trial['candidates']:
            candidate['parameters']['first_symbol_center_seconds']+=candidate_start/fs
            candidate['channel']={'audio_frequency_hz':candidate['parameters']['carrier_offset_hz'],
                                  'sample_rate':rate,'frequency_reference':'audio_hz'}
            candidate['source_window']={'source_sample_start':candidate_start,'source_sample_end':end,
                                        'source_sample_rate':fs,'end_exclusive':True,'quality_start_source_sample':start}
            result['candidates'].append(candidate)
    result['status']='timing_consistent_candidate' if result['candidates'] else 'no_consistent_candidate'
    return result
