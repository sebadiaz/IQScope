"""Bounded collective SITOR-B / CCIR 476 FSK candidates and NAVTEX framing.

Constant-ratio and repeated-copy evidence is not a CRC or authentication.
"""
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy import signal

# ITU-R M.476-5 Tables 1/2, B=high, Y=low, emitted leftmost element first.
LETTER_CODES=(0x47,0x72,0x1d,0x53,0x56,0x1b,0x35,0x69,0x4d,0x17,0x1e,0x65,0x39,
              0x59,0x71,0x2d,0x2e,0x55,0x4b,0x74,0x4e,0x3c,0x27,0x3a,0x2b,0x63)
LETTERS=dict(zip(LETTER_CODES,'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
FIGURES=dict(zip(LETTER_CODES,('-', '?', ':', '[FIG-D]', '3', '[FIG-F]', '[FIG-G]', '[FIG-H]',
    '8','[BEL]','(',')','.',',','9','0','1','4',"'",'5','7','=','2','/','6','+')))
SHARED={0x78:'\r',0x6c:'\n',0x5c:' '}
LTRS=0x5a;FIGS=0x36
IDLE=frozenset((0x0f,0x33,0x66,0x6a))
VALID=np.array([v.bit_count()==4 for v in range(128)])


def _text(events):
    mode=None;parts=[];position=0
    for event in events:
        if event.get('observed_phasing_before'):mode=None
        code=event['selected_code'];value='';status='control'
        if code is None:
            value='\ufffd';mode=None;status='erasure'
        elif code==LTRS:mode='letters'
        elif code==FIGS:mode='figures'
        elif code in SHARED:value=SHARED[code];status='shared_character'
        elif code in LETTERS:
            if mode is None:value='\ufffd';status='unknown_shift'
            else:
                value=(LETTERS if mode=='letters' else FIGURES)[code]
                status='unsupported_figure' if value.startswith('[FIG-') else 'character'
        elif code not in IDLE:value='\ufffd';status='unmapped'
        event.update(text_start=position,text_end=position+len(value),decoded_status=status,shift_after=mode)
        parts.append(value);position+=len(value)
    return ''.join(parts)


def _navtex(text,events,limit=16):
    header=re.compile(r'ZCZC +([A-Z])([A-Z])([0-9]{2})[ \t]*[\r\n]+')
    ender=re.compile(r'(?:^|(?<=[\r\n]))NNNN(?:[ \t]*[\r\n]+|$)')
    phasing={e['text_start'] for e in events if e.get('observed_phasing_before')}
    starts=[m for m in header.finditer(text) if m.start()==0 or text[m.start()-1] in '\r\n' or m.start() in phasing]
    messages=[]
    for index,match in enumerate(starts[:limit]):
        boundary=starts[index+1].start() if index+1<len(starts) else len(text)
        end=ender.search(text,match.end(),boundary)
        stop=end.end() if end else boundary
        relevant=[e for e in events if e['text_end']>match.start() and e['text_start']<stop]
        uncertain=sum(e['decoded_status'] in ('erasure','unknown_shift','unsupported_figure','unmapped') for e in relevant)
        messages.append(dict(station_designator=match[1],subject_designator=match[2],serial_text=match[3],
            serial=int(match[3]),header=match.group().rstrip('\r\n'),text=text[match.start():stop],
            body=text[match.end():end.start() if end else boundary],framing_complete=end is not None,
            text_interpretation_complete=end is not None and uncertain==0,uncertain_characters=uncertain,
            termination='NNNN' if end else 'next_header' if index+1<len(starts) else 'window_end',
            text_start=match.start(),text_end=stop,
            time_seconds=relevant[0]['time_seconds'] if relevant else None,
            time_end_seconds=relevant[-1]['repeat_end_seconds'] if relevant else None))
    return messages,max(0,len(starts)-limit)


def _best(discriminator,rate):
    grid=np.arange(len(discriminator));step=rate/100;best=None;best_score=-1
    for phase in np.arange(20)*step/20:
        times=np.arange(phase,len(discriminator)-1,step)
        values=np.interp(times,grid,discriminator)
        for polarity in (1,-1):
            bits=(values*polarity>0).astype('u1')
            for word_phase in range(7):
                length=(len(bits)-word_phase)//7
                if length<29:continue
                matrix=bits[word_phase:word_phase+length*7].reshape(-1,7)
                codes=(matrix*(1<<np.arange(7))).sum(axis=1).astype('u1')
                word_times=times[word_phase:word_phase+length*7:7]-.5*step
                full=(word_times>=0)&(word_times+.07*rate<=len(discriminator))
                contrasts=abs(values[word_phase:word_phase+length*7]).reshape(-1,7).min(axis=1)[full]
                codes=codes[full];word_times=word_times[full]
                if len(codes)<29:continue
                valid=VALID[codes]
                ratio=float(valid.mean())
                if ratio<.7:continue
                for parity in (0,1):
                    indices=np.arange(parity,len(codes)-5,2);a=codes[indices];b=codes[indices+5]
                    active=~(np.isin(a,list(IDLE))&np.isin(b,list(IDLE)))
                    va=valid[indices];vb=valid[indices+5]
                    same=active&va&vb&(a==b);conflict=active&va&vb&(a!=b)
                    confirmed=int(same.sum());conflicts=int(conflict.sum())
                    recovered=int((active&(va^vb)).sum());missing=int((active&~va&~vb).sum())
                    total=int(active.sum())
                    if (confirmed<12 or confirmed/max(1,confirmed+conflicts)<.85
                            or (confirmed+recovered)/max(1,total)<.8
                            or len(set(map(int,a[same]))&set(LETTERS))<4):continue
                    contrast=float(np.mean(abs(values)))
                    score=confirmed-conflicts*3-missing*2+ratio+contrast*.1
                    if score<=best_score:continue
                    best_score=score
                    best=dict(codes=codes,times=word_times,bit_contrast=contrasts,
                        parity=parity,phase=float(phase),word_phase=word_phase,polarity=polarity,
                        confirmed=confirmed,conflicts=conflicts,recovered=recovered,missing=missing,
                        valid_ratio=ratio,score=score)
    return best


def _candidate(best,rate,channel):
    codes=best['codes'];times=best['times']/rate;events=[];phasing=0
    for pos in range(best['parity'],len(codes)-5,2):
        a=int(codes[pos]);b=int(codes[pos+5]);va=a.bit_count()==4;vb=b.bit_count()==4
        if a in IDLE and b in IDLE:
            phasing=phasing+1 if a==0x66 and b==0x0f else 0
            continue
        if va and vb and a==b:chosen=a;decision='matching_copies'
        elif va and vb:chosen=None;decision='valid_copy_conflict'
        elif va:chosen=a;decision='direct_copy_only'
        elif vb:chosen=b;decision='repeated_copy_only'
        else:chosen=None;decision='both_invalid'
        events.append(dict(direct_symbol_index=pos,repeat_symbol_index=pos+5,
            direct_code=a,repeat_code=b,direct_constant_ratio_valid=va,repeat_constant_ratio_valid=vb,
            selected_code=chosen,decision=decision,time_seconds=float(times[pos]),
            repeat_end_seconds=float(times[pos+5]+.07),observed_phasing_before=phasing>=6))
        phasing=0
    text=_text(events);messages,deferred=_navtex(text,events)
    symbols=[dict(code=int(code),time_seconds=float(time),minimum_bit_contrast=float(contrast),
                  constant_ratio_valid=int(code).bit_count()==4)
             for code,time,contrast in zip(codes,times,best['bit_contrast'])]
    return dict(text=text,channel=channel,characters=events,received_symbols=symbols,
        messages=messages,deferred_messages=deferred,initial_shift_state='unknown_until_observed_LTRS_or_FIGS',
        parameters=dict(baud=100,shift_hz=channel['high_tone_hz']-channel['low_tone_hz'],
            high_tone_is_mark=best['polarity']==1,bit_order='lsb_first',symbol_bits=7,
            direct_parity=best['parity'],word_phase=best['word_phase'],sample_phase=best['phase'],
            repeat_delay_symbols=5,repeat_start_delay_seconds=.35,intervening_symbol_time_seconds=.28),
        evidence=dict(matching_traffic_pairs=best['confirmed'],valid_copy_conflicts=best['conflicts'],
            single_valid_copy_pairs=best['recovered'],both_invalid_pairs=best['missing'],
            constant_ratio_valid_fraction=best['valid_ratio'],checksum='not_present'),
        score=float(best['score']),score_kind='structural_repeat_score_not_probability')


def search_sitor(x,fs,center_hz=0,max_channels=4,max_seconds=40):
    result=dict(decoder='sitor_b',family='SITOR-B / CCIR 476 / NAVTEX',candidates=[],messages=[],channels_examined=[],
        validation_scope='4-of-7 code and five-symbol direct/repeat pairing; framing only for NAVTEX, no CRC or authentication',
        budgets=dict(channels=min(4,max(0,max_channels)),seconds=min(40,max(0,max_seconds)),input_samples=8000000,
                     spectral_peaks=96,sample_phases=20,messages_per_candidate=16),
        limitations=['1 kS/s to 2.4 MS/s complex IQ; stationary separated 170-Hz tone pairs at nominal 100 baud, no hopping or FM frontend.',
            'At most four channels, forty seconds and eight million input samples; twenty sampling phases, seven word alignments and both polarities.',
            'Requires >=12 matching traffic pairs, >=70% valid constant-ratio words, >=85% agreement among two-valid-copy pairs and four distinct letter codes.',
            'One valid copy may replace an invalid copy; conflicting valid copies remain erasures, with both received values retained. No bit flipping.',
            'Shift state starts unknown and is invalidated by erasures; no invented missing letters, start/end framing or inter-window assembly.',
            'Spectral pairs may be sidelobe responses of the same emission; candidate counts are not emitter counts and identical texts remain labelled hypotheses.',
            'Collective FEC evidence only; no SITOR-A ARQ, selective-call procedure, M.625 extended applications or authenticated safety messages.'])
    if (not math.isfinite(fs) or not 1000<=fs<=2400000 or not math.isfinite(center_hz)
            or not np.iscomplexobj(x) or np.ndim(x)!=1 or len(x)<fs*2):return dict(result,status='not_applicable')
    original_count=len(x)
    count=min(original_count,int(fs*result['budgets']['seconds']),8000000);x=np.asarray(x[:count])
    if len(x)<fs*2 or not np.all(np.isfinite(x)):return dict(result,status='not_applicable')
    size=min(262144,len(x),max(4096,int(fs/8)))
    f,p=signal.welch(x,fs,nperseg=size,return_onesided=False);f=np.fft.fftshift(f);p=np.fft.fftshift(p)
    peaks,_=signal.find_peaks(p,distance=max(1,int(35/(fs/size))));floor=max(float(np.median(p)),1e-30)
    peaks=sorted((int(i) for i in peaks if p[i]>floor*8),key=lambda i:p[i],reverse=True)[:96]
    pairs=[]
    for index,a in enumerate(peaks):
        for b in peaks[index+1:]:
            low,high=sorted((float(f[a]),float(f[b])))
            if abs(high-low-170)<=25 and abs((low+high)/2)+300<fs/2:
                pairs.append((math.sqrt(float(p[a]*p[b])),low,high))
    pairs.sort(reverse=True);selected=[]
    for _,low,high in pairs:
        if all(abs((low+high)/2-(a+b)/2)>350 for a,b in selected):selected.append((low,high))
    for low,high in selected[:result['budgets']['channels']]:
        offset=(low+high)/2;down=max(1,int(fs/4000));rate=fs/down
        mixed=x*np.exp(-2j*np.pi*offset*np.arange(len(x))/fs)
        y=signal.resample_poly(mixed,1,down) if down>1 else mixed
        width=max(3,round(rate/100*.8));window=np.ones(width)/width;clock=np.arange(len(y))/rate
        energies=[abs(signal.convolve(y*np.exp(-2j*np.pi*(tone-offset)*clock),window,mode='same'))**2 for tone in (low,high)]
        d=(energies[1]-energies[0])/np.maximum(energies[0]+energies[1],1e-24)
        best=_best(d,rate)
        channel=dict(offset_hz=offset,frequency_hz=float(center_hz+offset),rf_center_known=center_hz!=0,
            low_tone_hz=low,high_tone_hz=high,sample_rate=rate,input_sample_rate=float(fs),
            decimation=down,filter_delay_compensated=True,edge_padding='zero',
            frequency_estimate='stationary spectral tone peaks, not an authenticated transmitter')
        result['channels_examined'].append(dict(channel,status='fec_consistent_candidate' if best else 'no_consistent_candidate'))
        if best:
            candidate=_candidate(best,rate,channel);candidate_index=len(result['candidates'])
            candidate['same_text_as_candidate_index']=next((i for i,c in enumerate(result['candidates']) if c['text']==candidate['text']),None)
            for message in candidate['messages']:result['messages'].append(dict(message,candidate_index=candidate_index))
            result['candidates'].append(candidate)
    return dict(result,status='fec_consistent_text_candidate' if result['candidates'] else 'no_consistent_candidate',
        analyzed_seconds=count/fs,duration_limited=count<original_count,deferred_channel_count=max(0,len(selected)-result['budgets']['channels']),
        spectral_peaks_examined=len(peaks),spectral_peak_budget_reached=len(peaks)==96)


def write_sitor_artifacts(trial,out):
    if not trial['candidates']:return
    out=Path(out)
    for index,candidate in enumerate(trial['candidates'],1):
        candidate['text_artifact']=f'sitor-{index:02d}-text.txt'
        candidate['symbols_artifact']=f'sitor-{index:02d}-received-symbols.bin'
        (out/candidate['text_artifact']).write_bytes(candidate['text'].encode('utf-8'))
        (out/candidate['symbols_artifact']).write_bytes(bytes(s['code'] for s in candidate['received_symbols']))
        candidate['symbols_encoding']='one received 7-bit LSB-first code value per octet, high bit zero; not a packed RF bitstream'
    for index,message in enumerate(trial['messages'],1):
        message['artifact']=f'navtex-message-{index:02d}.txt'
        (out/message['artifact']).write_bytes(message['text'].encode('utf-8'))
    trial['artifact']='sitor-navtex.json';(out/trial['artifact']).write_text(json.dumps(trial,indent=2))
