"""Bounded FM/RDS reception with four strict offset/CRC-10 checks per group."""
from fractions import Fraction
import json
import math
from pathlib import Path

import numpy as np
from scipy import signal

OFFSETS = (0x0FC,0x198,0x168,0x1B4)
POLYNOMIAL = 0x5B9
BIT_RATE = 1187.5


def remainder(word):
    for bit in range(25,9,-1):
        if word & (1<<bit):word ^= POLYNOMIAL<<(bit-10)
    return word


def checked_rds_group(packet):
    """Reparse all 104 received bits; no error correction or trusted JSON fields."""
    if not isinstance(packet,bytes) or len(packet)!=13:raise ValueError('RDS group requires 104 received bits')
    number=int.from_bytes(packet,'big')
    blocks=[(number>>(26*(3-index)))&0x3ffffff for index in range(4)]
    words=[b>>10 for b in blocks];version='B' if words[1]&0x800 else 'A'
    expected=[OFFSETS[0],OFFSETS[1],0x350 if version=='B' else OFFSETS[2],OFFSETS[3]]
    if any(remainder(block)!=offset for block,offset in zip(blocks,expected)):
        raise ValueError('Invalid RDS offset/CRC-10 check')
    fields=dict(pi=words[0],pi_hex=f'{words[0]:04X}',group_type=words[1]>>12,version=version,
        group_name=f'{words[1]>>12}{version}',tp=bool(words[1]&0x400),pty=(words[1]>>5)&31,
        information_words_hex=[f'{word:04X}' for word in words],
        received_blocks_hex=[f'{block:07X}' for block in blocks],offset_words=expected)
    if version=='B':fields['repeated_pi_matches']=words[2]==words[0]
    if fields['group_type']==0:
        fields.update(ta=bool(words[1]&0x10),music=bool(words[1]&8),di_bit=bool(words[1]&4),
                      segment=words[1]&3,ps_segment_hex=words[3].to_bytes(2,'big').hex())
    elif fields['group_type']==2:
        text=(words[2].to_bytes(2,'big') if version=='A' else b'')+words[3].to_bytes(2,'big')
        fields.update(text_ab=bool(words[1]&0x10),segment=words[1]&15,radiotext_segment_hex=text.hex())
    return fields


def _display(data):
    # Conservative subset of the RDS G0 repertoire. Unsupported/control codes
    # remain explicit escapes, rather than silently guessing ISO-8859-1/UTF-8.
    return ''.join(chr(v) if 32<=v<127 and v not in (0x24,0x5e,0x60,0x7e) else f'\\x{v:02X}' for v in data)


def _text_state(slots,segment_size,terminator=False):
    end=next((i for i,v in enumerate(slots) if v==13),len(slots)) if terminator else len(slots)
    prefix=slots[:end]
    complete=all(v is not None for v in prefix) and (end<len(slots) or all(v is not None for v in slots))
    return dict(complete=complete,text=_display(bytes(prefix)) if complete else None,
        display_text=''.join('·' if v is None else _display(bytes([v])) for v in prefix),
        raw_hex=bytes(prefix).hex() if complete else None,
        slots=slots,segments_received=[i//segment_size for i in range(0,len(slots),segment_size)
                                       if all(v is not None for v in slots[i:i+segment_size])],
        termination='CR' if complete and end<len(slots) else 'fixed_width' if complete else 'incomplete',
        character_scope='conservative basic Latin subset; unsupported RDS character codes escaped')


def station_views(frames):
    stations={};states={}
    for frame in sorted(frames,key=lambda f:f['time_seconds']):
        f=checked_rds_group(bytes.fromhex(frame['hex']));c=frame['channel'];key=(f['pi'],c['offset_hz'])
        if key not in states:
            states[key]=dict(ps=[None]*8,rt=[None]*64,mode=None,ab=None,ps_resets=0,rt_resets=0)
            stations[key]=dict(pi=f['pi'],pi_hex=f['pi_hex'],channel=c,groups=0)
        state=states[key];station=stations[key];station.update(tp=f['tp'],pty=f['pty']);station['groups']+=1
        if f['group_type']==0:
            data=bytes.fromhex(f['ps_segment_hex']);pos=f['segment']*2
            if any(old is not None and old!=new for old,new in zip(state['ps'][pos:pos+2],data)):
                state['ps']=[None]*8;state['ps_resets']+=1
            state['ps'][pos:pos+2]=list(data)
            station.update(ta=f['ta'],music=f['music'])
        elif f['group_type']==2:
            if state['mode']!=f['version'] or state['ab']!=f['text_ab']:
                if state['mode'] is not None:state['rt_resets']+=1
                state['rt']=[None]*(64 if f['version']=='A' else 32)
            state['mode']=f['version'];state['ab']=f['text_ab']
            data=bytes.fromhex(f['radiotext_segment_hex']);pos=f['segment']*len(data)
            if any(old is not None and old!=new for old,new in zip(state['rt'][pos:pos+len(data)],data)):
                state['rt']=[None]*len(state['rt']);state['rt_resets']+=1
            state['rt'][pos:pos+len(data)]=list(data)
    for key,station in stations.items():
        state=states[key];station['ps']=_text_state(state['ps'],2)
        station['radiotext']=dict(_text_state(state['rt'],4 if state['mode']!='B' else 2,True),
                                 text_ab=state['ab'],version=state['mode'])
        station.update(ps_resets=state['ps_resets'],radiotext_resets=state['rt_resets'])
    return list(stations.values())


def _frontend(x,fs,offset):
    mixed=x*np.exp(-2j*np.pi*offset*np.arange(len(x))/fs)
    down=max(1,math.ceil(fs/228000))
    channel=signal.resample_poly(mixed,1,down) if down>1 else mixed;rate=fs/down
    channel=signal.convolve(channel,signal.firwin(129,min(105000,rate*.45),fs=rate),mode='same')
    mpx=np.angle(channel[1:]*np.conj(channel[:-1]))*rate/(2*np.pi)
    baseband=mpx*np.exp(-2j*np.pi*57000*np.arange(len(mpx))/rate)
    baseband=signal.convolve(baseband,signal.firwin(513,2400,fs=rate),mode='same')
    ratio=Fraction(19000/rate).limit_denominator(4096)
    baseband=signal.resample_poly(baseband,ratio.numerator,ratio.denominator)
    output_rate=rate*ratio.numerator/ratio.denominator
    return baseband,output_rate,dict(tuning_offset_hz=float(offset),input_sample_rate=float(fs),
        channel_sample_rate=float(rate),baseband_sample_rate=float(output_rate),subcarrier_hz=57000,
        discriminator_start_seconds=.5/rate,filter_delay_compensated=True,edge_padding='zero',fm_deemphasis=False)


def _carrier(z,rate):
    # Squaring removes the BPSK sign. Search only +/-100 Hz of the doubled
    # nominal carrier; the spectral peak is an estimate, not a lock guarantee.
    nfft=1<<int(math.ceil(math.log2(max(1024,4*len(z)))))
    spectrum=abs(np.fft.fft(z*z*np.hanning(len(z)),n=nfft))**2
    freq=np.fft.fftfreq(nfft,1/rate);eligible=np.flatnonzero(abs(freq)<=100)
    peak=int(eligible[np.argmax(spectrum[eligible])]);left=(peak-1)%nfft;right=(peak+1)%nfft
    logs=np.log(np.maximum(spectrum[[left,peak,right]],1e-30));denom=logs[0]-2*logs[1]+logs[2]
    delta=float(np.clip(.5*(logs[0]-logs[2])/denom,-.5,.5)) if denom else 0.
    residual=(freq[peak]+delta*rate/nfft)/2
    aligned=z*np.exp(-2j*np.pi*residual*np.arange(len(z))/rate)
    phase=.5*np.angle(np.sum(aligned*aligned))
    return (aligned*np.exp(-1j*phase)).real,dict(residual_subcarrier_hz=float(residual),phase_radians=float(phase),
        recovery='blind BPSK squared-carrier peak; no stereo pilot required')


def _groups(bits):
    if len(bits)<208:return []
    count=len(bits)-25;words=np.zeros(count,dtype=np.uint32)
    for index in range(26):words=(words<<1)|bits[index:index+count]
    syndromes=words.copy()
    for bit in range(25,9,-1):
        mask=(syndromes&(1<<bit))!=0;syndromes[mask]^=np.uint32(POLYNOMIAL<<(bit-10))
    starts=np.flatnonzero(syndromes[:len(bits)-103]==OFFSETS[0]);valid=[]
    for start in starts:
        if syndromes[start+26]!=OFFSETS[1] or syndromes[start+78]!=OFFSETS[3]:continue
        expected=0x350 if (words[start+26]>>10)&0x800 else OFFSETS[2]
        if syndromes[start+52]!=expected:continue
        valid.append(int(start))
    # Acquire only on at least two adjacent complete groups. Keep members of
    # such runs; isolated groups are never promoted to recovered content.
    positions=set(valid)
    return [pos for pos in valid if pos-104 in positions or pos+104 in positions]


def search_rds(x,fs,bands,center_hz=0,max_channels=2,max_seconds=10,max_frames=128):
    result=dict(decoder='rds_fm',family='FM / RDS',frames=[],stations=[],channels_examined=[],
        validation_scope='All four received offset/CRC-10 checks, version-specific C/C-prime and adjacent-group acquisition; no bit repair or authentication',
        budgets=dict(channels=min(2,max(0,max_channels)),seconds=min(10,max(0,max_seconds)),input_samples=8000000,
                     frames=min(128,max(0,max_frames)),sample_phases=32),
        limitations=['192 kS/s to 4 MS/s complex IQ, at most two channels, ten seconds and eight million input samples.',
            'Stationary spectral channels and a remaining-slot baseband fallback; mono or stereo FM, no pilot requirement.',
            'Blind squared-carrier estimate within +/-50 Hz of 57 kHz; fixed nominal biphase clock with 32 sampling phases, no adaptive PLL or error correction.',
            'Only complete groups belonging to adjacent CRC-valid runs; isolated, partial or corrupted groups are rejected.',
            'Partial PS (0A/0B) and RadioText (2A/2B) per declared PI/channel within this window; conflicts or text A/B changes reset assembly.',
            'Unsupported RDS characters escaped; no country/PTY labels, alternate-frequency tuning, clock-time, TMC, ODA or RDS2 interpretation.',
            'CRC checks do not authenticate a station, PI, text or broadcaster; no cross-window station state.'])
    if (not math.isfinite(fs) or not 192000<=fs<=4000000 or not math.isfinite(center_hz)
            or not np.iscomplexobj(x) or np.ndim(x)!=1 or len(x)<fs*.3):return dict(result,status='not_applicable')
    count=min(len(x),int(fs*result['budgets']['seconds']),8000000);samples=np.asarray(x[:count])
    if len(samples)<fs*.3 or not np.all(np.isfinite(samples)):return dict(result,status='not_applicable')
    offsets=[]
    for band in sorted(bands,key=lambda b:b.get('spectral_snr_db',0),reverse=True):
        offset=band.get('offset_hz',float('nan'))
        if (90000<=band.get('bandwidth_hz',0)<=270000 and math.isfinite(offset)
                and abs(offset)+90000<fs/2 and all(abs(offset-v)>30000 for v in offsets)):
            offsets.append(float(offset))
    if all(abs(v)>30000 for v in offsets):offsets.append(0.)
    for offset in offsets[:result['budgets']['channels']]:
        if len(result['frames'])>=result['budgets']['frames']:break
        z,rate,channel=_frontend(samples,fs,offset);levels,carrier=_carrier(z,rate)
        channel.update(offset_hz=offset,frequency_hz=float(center_hz+offset),rf_center_known=center_hz!=0,
                       frequency_estimate='spectral power center or baseband trial, not a measured RF carrier')
        matched=signal.convolve(levels,np.r_[np.ones(8),-np.ones(8)][::-1]/16,mode='same')
        step=rate/BIT_RATE;grid=np.arange(len(matched));accepted=0;phases=0
        for phase in np.arange(32)*step/32:
            if len(result['frames'])>=result['budgets']['frames']:break
            phases+=1;times=np.arange(phase,len(matched)-1,step)
            states=np.interp(times,grid,matched)>0;bits=np.logical_xor(states[1:],states[:-1]).astype('u1')
            for start in _groups(bits):
                time=float((times[start+1]-8)/rate+channel['discriminator_start_seconds'])
                end=time+104/BIT_RATE
                if time<0 or end>len(samples)/fs:continue
                packet=np.packbits(bits[start:start+104],bitorder='big').tobytes()
                if any(f['hex']==packet.hex() and abs(f['time_seconds']-time)<2/BIT_RATE
                       and abs(f['channel']['offset_hz']-offset)<5000 for f in result['frames']):continue
                if len(result['frames'])>=result['budgets']['frames']:break
                result['frames'].append(dict(decoder='rds_fm',hex=packet.hex(),crc_valid=True,
                    fields=checked_rds_group(packet),time_seconds=time,time_end_seconds=end,channel=channel.copy(),
                    timing=dict(nominal_baud=BIT_RATE,sample_phase=float(phase),sample_rate=float(rate)),
                    frontend='fm_57khz_biphase_dbpsk',validation_scope=result['validation_scope']))
                accepted+=1
        result['channels_examined'].append(dict(channel,carrier=carrier,phases_examined=phases,accepted_frames=accepted))
    result['frames'].sort(key=lambda f:f['time_seconds']);result['stations']=station_views(result['frames'])
    return dict(result,status='validated_groups' if result['frames'] else 'no_valid_groups',analyzed_seconds=count/fs,
        duration_limited=count<len(x),deferred_channel_count=max(0,len(offsets)-result['budgets']['channels']),
        budget_exhausted=len(result['frames'])>=result['budgets']['frames'])


def write_rds_artifacts(trial,out):
    if not trial['frames']:return
    out=Path(out)
    for index,frame in enumerate(trial['frames'],1):
        fields=checked_rds_group(bytes.fromhex(frame['hex']))
        frame['wire_artifact']=f'rds-group-{index:03d}.bin';frame['payload_artifact']=f'rds-data-{index:03d}.bin'
        (out/frame['wire_artifact']).write_bytes(bytes.fromhex(frame['hex']))
        (out/frame['payload_artifact']).write_bytes(bytes.fromhex(''.join(fields['information_words_hex'])))
    trial['artifact']='rds-groups.json';(out/trial['artifact']).write_text(json.dumps(trial,indent=2))
